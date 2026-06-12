import copy
import json
import re


PLACEHOLDER_RE = re.compile(r"\$\{([^{}]+)\}")
LIST_SPLIT_RE = re.compile(r"\s*[,，;；]\s*")
RANGE_RE = re.compile(r"^\s*(-?\d+)\s*(?:-|~|至|到|\.\.)\s*(-?\d+)\s*([^\d\s,，;；]*)\s*$")
MONTH_RANGE_RE = re.compile(r"^\s*(-?\d+)\s*([^\d\s,，;；\-~.]+)\s*(?:-|~|至|到|\.\.)\s*(-?\d+)\s*\2\s*$")
MAX_EXPANDED_RANGE = 5000


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
            return int(text)
        if re.fullmatch(r"[-+]?\d+\.\d+", text):
            return float(text)
    except Exception:
        pass

    return text


def _format_mapping_key(value):
    parsed = parse_parameter_literal(value)
    return str(parsed)


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
                    for input_value in expand_mapping_inputs(row.get("from")):
                        mapping_dict[_format_mapping_key(input_value)] = output
            normalized[name] = mapping_dict
        elif isinstance(mapping, dict):
            mapping_dict = {}
            for key, value in mapping.items():
                output = expand_mapping_output(value)
                for input_value in expand_mapping_inputs(key):
                    mapping_dict[_format_mapping_key(input_value)] = output
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


def _apply_mapping(value, map_name, mappings, strict):
    mapping = mappings.get(map_name)
    if mapping is None:
        if strict:
            raise KeyError(f"未定义参数映射: {map_name}")
        return value

    key = _format_mapping_key(value)
    if key in mapping:
        return mapping[key]

    parsed_key = _format_mapping_key(key)
    if parsed_key in mapping:
        return mapping[parsed_key]

    if strict:
        raise KeyError(f"映射 {map_name} 中找不到输入值: {value}")
    return value


def resolve_placeholder(expression, parameters, mappings, strict=False):
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
