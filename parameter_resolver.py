import copy
import json
import re
from decimal import Decimal, InvalidOperation


PLACEHOLDER_RE = re.compile(r"\$\{([^{}]+)\}")
LIST_SPLIT_RE = re.compile(r"\s*[,，;；]\s*")
RANGE_RE = re.compile(r"^\s*(-?\d+)\s*(?:-|~|至|到|\.\.)\s*(-?\d+)\s*([^\d\s,，;；]*)\s*$")
MONTH_RANGE_RE = re.compile(r"^\s*(-?\d+)\s*([^\d\s,，;；\-~.]+)\s*(?:-|~|至|到|\.\.)\s*(-?\d+)\s*\2\s*$")
MAX_EXPANDED_RANGE = 5000


def _normalize_numeric_key(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, "g")
    if isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text):
            return None
        try:
            number = Decimal(text)
        except InvalidOperation:
            return None
        if number == number.to_integral_value():
            return str(int(number))
        return format(number.normalize(), "f").rstrip("0").rstrip(".")
    return None


def parse_parameter_literal(value):
    """Parse a UI-entered parameter value into a useful Python scalar/list."""
    if not isinstance(value, str):
        return value

    text = value.strip()
    if text == "":
        return ""

    try:
        return json.loads(text)
    except Exception:
        pass

    lowered = text.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False

    if LIST_SPLIT_RE.search(text):
        return [
            parse_parameter_literal(part)
            for part in LIST_SPLIT_RE.split(text)
            if part.strip() != ""
        ]

    try:
        if re.fullmatch(r"[-+]?\d+", text):
            digits = text.lstrip("+-")
            if len(digits) > 1 and digits.startswith("0"):
                return text
            return int(text)
        if re.fullmatch(r"[-+]?(?:\d+\.\d*|\.\d+)", text):
            return float(text)
    except Exception:
        pass

    return text


def _format_mapping_key(value):
    numeric_key = _normalize_numeric_key(value)
    if numeric_key is not None:
        return numeric_key
    parsed = parse_parameter_literal(value)
    numeric_key = _normalize_numeric_key(parsed)
    if numeric_key is not None:
        return numeric_key
    return str(parsed)


def _format_typed_mapping_key(value, data_type=None):
    # String 映射键必须保留原始文本，避免编码类值如 001 被转成数字 1。
    if str(data_type or "").strip() == "String":
        return "" if value is None else str(value).strip()
    return _format_mapping_key(value)


def _expand_range_literal(value):
    if not isinstance(value, str):
        return None

    text = value.strip()
    match = MONTH_RANGE_RE.match(text)
    if match:
        start, suffix, end = int(match.group(1)), match.group(2), int(match.group(3))
        if abs(end - start) + 1 > MAX_EXPANDED_RANGE:
            raise ValueError(f"映射范围过大: {value}")
        step = 1 if end >= start else -1
        return [f"{i}{suffix}" for i in range(start, end + step, step)]

    match = RANGE_RE.match(text)
    if not match:
        return None

    start, end, suffix = int(match.group(1)), int(match.group(2)), match.group(3)
    if abs(end - start) + 1 > MAX_EXPANDED_RANGE:
        raise ValueError(f"映射范围过大: {value}")
    step = 1 if end >= start else -1
    if suffix:
        return [f"{i}{suffix}" for i in range(start, end + step, step)]
    return list(range(start, end + step, step))


def expand_mapping_inputs(value):
    parsed = parse_parameter_literal(value)
    if isinstance(parsed, (list, tuple, set)):
        expanded = []
        for item in parsed:
            range_values = _expand_range_literal(item)
            if range_values is not None:
                expanded.extend(range_values)
            else:
                expanded.append(parse_parameter_literal(item))
        return expanded

    range_values = _expand_range_literal(parsed)
    if range_values is not None:
        return range_values
    return [parsed]


def expand_mapping_output(value):
    parsed = parse_parameter_literal(value)
    if isinstance(parsed, str):
        range_values = _expand_range_literal(parsed)
        if range_values is not None:
            return range_values
    if isinstance(parsed, tuple):
        return list(parsed)
    return parsed


def normalize_runtime_parameters(parameters):
    return {
        str(key).strip(): parse_parameter_literal(value)
        for key, value in (parameters or {}).items()
        if str(key).strip()
    }


def normalize_parameter_mappings(mappings):
    normalized = {}
    for map_name, mapping in (mappings or {}).items():
        name = str(map_name).strip()
        if not name:
            continue

        if isinstance(mapping, list):
            mapping_dict = {}
            for row in mapping:
                if isinstance(row, dict) and "from" in row:
                    output = expand_mapping_output(row.get("to"))
                    source_type = row.get("sourceDataType")
                    if str(source_type or "").strip() == "String":
                        input_values = row.get("from")
                        if not isinstance(input_values, (list, tuple, set)):
                            input_values = [input_values]
                    else:
                        input_values = expand_mapping_inputs(row.get("from"))
                    for input_value in input_values:
                        mapping_dict[_format_typed_mapping_key(input_value, source_type)] = output
            normalized[name] = mapping_dict
        elif isinstance(mapping, dict):
            mapping_dict = {}
            for key, output in mapping.items():
                raw_key = "" if key is None else str(key).strip()
                if raw_key:
                    mapping_dict[raw_key] = output
                normalized_key = _format_mapping_key(key)
                if normalized_key and normalized_key not in mapping_dict:
                    mapping_dict[normalized_key] = output
            normalized[name] = mapping_dict
        else:
            normalized[name] = {}

    return normalized


def _lookup_variable(name, parameters, strict):
    if name in parameters:
        return parameters[name]
    if strict:
        raise KeyError(f"未定义运行参数: {name}")
    return "${" + name + "}"


def _lookup_mapping_value(value, mapping):
    # String 类型映射优先保留原始文本键，避免编码类值如 001 被转成数字 1。
    raw_key = "" if value is None else str(value).strip()
    if raw_key in mapping:
        return True, mapping[raw_key]

    key = _format_mapping_key(value)
    if key in mapping:
        return True, mapping[key]

    parsed_key = _format_mapping_key(key)
    if parsed_key in mapping:
        return True, mapping[parsed_key]
    return False, None


def _apply_mapping(value, map_name, mappings, strict):
    mapping = mappings.get(map_name)
    if mapping is None:
        if strict:
            raise KeyError(f"未定义参数映射: {map_name}")
        return value

    found, mapped_value = _lookup_mapping_value(value, mapping)
    if found:
        return mapped_value

    if isinstance(value, (list, tuple, set)):
        resolved = []
        missing = []
        for item in value:
            item_found, item_value = _lookup_mapping_value(item, mapping)
            if not item_found:
                if strict:
                    missing.append(item)
                    continue
                item_value = item
            # 数组参数映射时，单项映射到数组会被摊平，支持 1-3 -> [1,2,3]。
            if isinstance(item_value, (list, tuple)):
                resolved.extend(item_value)
            else:
                resolved.append(item_value)
        if missing and strict:
            raise KeyError(f"映射 {map_name} 中找不到输入值: {missing[0]}")
        return resolved

    if strict:
        raise KeyError(f"映射 {map_name} 中找不到输入值: {value}")
    return value


def resolve_placeholder(expression, parameters, mappings, strict=False):
    parameters = normalize_runtime_parameters(parameters)
    mappings = normalize_parameter_mappings(mappings)
    parts = [part.strip() for part in expression.split("|") if part.strip()]
    if not parts:
        return ""

    value = _lookup_variable(parts[0], parameters, strict)
    for pipe in parts[1:]:
        if pipe.startswith("map:"):
            value = _apply_mapping(value, pipe[4:].strip(), mappings, strict)
        else:
            if strict:
                raise ValueError(f"不支持的参数管道: {pipe}")
    return value


def resolve_runtime_value(value, parameters=None, mappings=None, strict=False):
    parameters = normalize_runtime_parameters(parameters)
    mappings = normalize_parameter_mappings(mappings)

    if isinstance(value, dict):
        return {
            key: resolve_runtime_value(val, parameters, mappings, strict)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [
            resolve_runtime_value(item, parameters, mappings, strict)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(resolve_runtime_value(item, parameters, mappings, strict)
                     for item in value)
    if not isinstance(value, str):
        return value

    matches = list(PLACEHOLDER_RE.finditer(value))
    if not matches:
        return value

    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        return resolve_placeholder(matches[0].group(1), parameters, mappings, strict)

    def replace(match):
        resolved = resolve_placeholder(match.group(1), parameters, mappings, strict)
        if isinstance(resolved, (dict, list, tuple)):
            return json.dumps(resolved, ensure_ascii=False)
        return str(resolved)

    return PLACEHOLDER_RE.sub(replace, value)


def clone_resolved_runtime_value(value, parameters=None, mappings=None, strict=False):
    return resolve_runtime_value(copy.deepcopy(value), parameters, mappings, strict)
