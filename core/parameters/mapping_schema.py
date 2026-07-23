"""Schema builder for the runtime parameter input operator."""

import json
import re

from parameter_resolver import parse_parameter_literal


SCHEMA_NAME = "rule-engine.parameter-mapping.v1"
OPERATOR_NAME = "advanced_param_mapping"
MAPPING_OUTPUT_TYPES = ["Integer", "Float", "String", "Boolean", "Array", "Object"]
DATA_TYPES = [*MAPPING_OUTPUT_TYPES, "File", "Folder", "List", "Text", "Select", "Password"]
TEXT_LIKE_DATA_TYPES = {"String", "File", "Folder", "Select", "Password"}
DEFAULT_FILE_FILTERS = ["*.*"]


def _normalize_data_type(data_type):
    normalized = str(data_type or "String").strip() or "String"
    select_aliases = {"select", "choice", "dropdown", "enum", "下拉选择"}
    if normalized.lower() in select_aliases:
        return "Select"
    if normalized.lower() in {"password", "secret", "密码"}:
        return "Password"
    if normalized == "Text":
        return "String"
    if normalized == "List":
        return "Array"
    return normalized


def is_text_like_data_type(data_type):
    return _normalize_data_type(data_type) in TEXT_LIKE_DATA_TYPES


def normalize_file_filters(filters):
    if isinstance(filters, str):
        parts = re.split(r"[\s,;，；]+", filters.strip())
    elif isinstance(filters, (list, tuple, set)):
        parts = []
        for item in filters:
            parts.extend(re.split(r"[\s,;，；]+", "" if item is None else str(item).strip()))
    else:
        parts = []

    normalized = []
    seen = set()
    for item in parts:
        item = str(item or "").strip()
        if not item:
            continue
        if item == "*":
            item = "*.*"
        elif item.startswith("."):
            item = f"*{item}"
        elif "*" not in item and "." not in item:
            item = f"*.{item}"
        if item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized or list(DEFAULT_FILE_FILTERS)


def format_file_filters(filters):
    return ", ".join(normalize_file_filters(filters))


def normalize_select_options(options):
    if isinstance(options, str):
        parts = re.split(r"[\n,;，；]+", options.strip())
    elif isinstance(options, (list, tuple, set)):
        parts = []
        for item in options:
            parts.extend(re.split(r"[\n,;，；]+", "" if item is None else str(item).strip()))
    else:
        parts = []

    normalized = []
    seen = set()
    for item in parts:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def normalize_list_item_limits(initial_count=None, max_items=None, default_count=0):
    """Normalize the runtime list's initial row count and optional upper limit."""

    try:
        initial = int(initial_count)
    except (TypeError, ValueError):
        initial = 1
    try:
        maximum = int(max_items)
    except (TypeError, ValueError):
        maximum = 0
    try:
        defaults = int(default_count)
    except (TypeError, ValueError):
        defaults = 0

    initial = max(1, initial, defaults)
    maximum = max(0, maximum)
    if maximum and maximum < initial:
        raise ValueError("列表最多项目数不能小于初始项目数")
    return initial, maximum


def normalize_parameter_layout(layout, rows):
    """Keep a stable, backwards-compatible parameter/container layout tree."""

    names = [
        str(row.get("fieldName") or "").strip()
        for row in rows or []
        if isinstance(row, dict) and str(row.get("fieldName") or "").strip()
    ]
    valid_names = set(names)
    used_names = set()
    used_ids = set()

    def parameter_node(value):
        if isinstance(value, dict):
            name = str(value.get("fieldName") or value.get("name") or "").strip()
        else:
            name = str(value or "").strip()
        if not name or name not in valid_names or name in used_names:
            return None
        used_names.add(name)
        return {"kind": "parameter", "fieldName": name}

    normalized = []
    for index, node in enumerate(layout or [], start=1):
        if not isinstance(node, dict) or str(node.get("kind") or "parameter") != "container":
            parameter = parameter_node(node)
            if parameter:
                normalized.append(parameter)
            continue
        container_id = str(node.get("id") or "container_{}".format(index)).strip()
        if not container_id or container_id in used_ids:
            container_id = "container_{}".format(index)
        used_ids.add(container_id)
        children = []
        for child in node.get("children") or []:
            parameter = parameter_node(child)
            if parameter:
                children.append(parameter)
        normalized.append(
            {
                "kind": "container",
                "id": container_id,
                "title": str(node.get("title") or "参数组").strip() or "参数组",
                "direction": "horizontal",
                "children": children,
            }
        )

    for name in names:
        if name not in used_names:
            normalized.append({"kind": "parameter", "fieldName": name})
    return normalized


def coerce_advanced_value(value, data_type):
    data_type = _normalize_data_type(data_type)
    text = "" if value is None else str(value).strip()
    if is_text_like_data_type(data_type):
        return text
    if data_type == "Boolean":
        lowered = text.lower()
        if lowered in ("true", "yes", "y", "1", "是", "勾选"):
            return True
        if lowered in ("false", "no", "n", "0", "否", ""):
            return False
        raise ValueError(f"无法转换为 Boolean: {value}")
    if data_type == "Array":
        if text == "":
            return []
        parsed = parse_parameter_literal(text)
        if isinstance(parsed, tuple):
            return list(parsed)
        return parsed if isinstance(parsed, list) else [parsed]
    if text == "":
        return ""
    if data_type == "Integer":
        parsed = parse_parameter_literal(text)
        if isinstance(parsed, list):
            return [int(parse_parameter_literal(item)) for item in parsed]
        return int(parsed)
    if data_type == "Float":
        parsed = parse_parameter_literal(text)
        if isinstance(parsed, list):
            return [float(parse_parameter_literal(item)) for item in parsed]
        return float(parsed)
    if data_type == "Object":
        parsed = parse_parameter_literal(text)
        if not isinstance(parsed, dict):
            raise ValueError(f"无法转换为 Object: {value}")
        return parsed
    return parse_parameter_literal(text)


def format_advanced_value(value):
    if isinstance(value, (dict, list, tuple, bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def coerce_parameter_rows(ui_rows):
    rows = []
    seen = set()
    for index, row in enumerate(ui_rows, start=1):
        field_name = str(row.get("fieldName", "")).strip()
        raw_value = str(row.get("input", "")).strip()
        data_type = _normalize_data_type(row.get("dataType", "String"))
        label = str(row.get("label") or field_name).strip()
        tip = str(row.get("tip") or "").strip()
        has_content = any([field_name, label, raw_value, tip])

        if not has_content:
            continue
        if not field_name:
            raise ValueError(f"第 {index} 行输入参数缺少参数名")
        if field_name in seen:
            raise ValueError(f"参数名重复: {field_name}")
        if data_type not in DATA_TYPES:
            raise ValueError(f"不支持的数据类型: {data_type}")

        seen.add(field_name)
        coerced_value = coerce_advanced_value(raw_value, data_type)
        normalized = {
            "fieldName": field_name,
            "label": label or field_name,
            "dataType": data_type,
            "input": raw_value,
            "value": coerced_value,
            "tip": tip,
            "required": bool(row.get("required", True)),
        }
        if data_type in {"Array", "Object"}:
            initial_count, max_items = normalize_list_item_limits(
                row.get("initial_count"),
                row.get("max_items"),
                len(coerced_value) if isinstance(coerced_value, (list, dict)) else 0,
            )
            normalized["initial_count"] = initial_count
            normalized["max_items"] = max_items
        if data_type == "File":
            normalized["filters"] = normalize_file_filters(row.get("filters"))
        if data_type == "Select":
            options = normalize_select_options(row.get("options"))
            if not options:
                raise ValueError(f"第 {index} 行下拉选择至少需要一个选项")
            if raw_value and raw_value not in options:
                options.insert(0, raw_value)
            if not raw_value:
                normalized["input"] = options[0]
                normalized["value"] = options[0]
            normalized["options"] = options
        rows.append(normalized)
    return rows


def build_rule_engine_config(rows):
    """Build parameter config and runtime payload without mapping rules."""
    parameters = []
    typed_parameters = {}
    raw_parameters = {}

    for param in rows:
        field_name = param["fieldName"]
        typed_parameters[field_name] = param["value"]
        raw_parameters[field_name] = param["input"]
        item = {
            "fieldName": field_name,
            "label": param.get("label") or field_name,
            "dataType": param["dataType"],
            "input": param["input"],
            "value": param["value"],
            "tip": param.get("tip", ""),
            "required": bool(param.get("required", True)),
        }
        if param["dataType"] == "File":
            item["filters"] = normalize_file_filters(param.get("filters"))
        if param["dataType"] == "Select":
            item["options"] = normalize_select_options(param.get("options"))
        if param["dataType"] in {"Array", "Object"}:
            item["initial_count"] = param.get("initial_count", 1)
            item["max_items"] = param.get("max_items", 0)
        parameters.append(item)

    return {
        "schema": SCHEMA_NAME,
        "operator": OPERATOR_NAME,
        "parameters": parameters,
        "rules": [],
        "runtime_payload": {
            "runtime_parameters": typed_parameters,
            "raw_parameters": raw_parameters,
            "parameter_mappings": {},
        },
    }
