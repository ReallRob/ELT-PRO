"""Schema builder for the advanced parameter mapping operator."""

import json
import re

from parameter_resolver import (
    expand_mapping_inputs,
    expand_mapping_output,
    parse_parameter_literal,
)


SCHEMA_NAME = "rule-engine.parameter-mapping.v1"
OPERATOR_NAME = "advanced_param_mapping"
DATA_TYPES = ["Integer", "Float", "String", "Boolean", "Array", "Object"]


def normalize_mapping_groups(rules):
    """Normalize mapping groups from the current editor shape."""
    groups = []
    for index, rule in enumerate(rules or [], start=1):
        if not isinstance(rule, dict):
            continue
        cases = rule.get("cases")
        if not isinstance(cases, list):
            continue
        normalized_cases = [dict(case) for case in cases if isinstance(case, dict)]
        first_case = normalized_cases[0] if normalized_cases else {}

        groups.append({
            "ruleName": rule.get("ruleName") or rule.get("mappingName") or f"映射{index}",
            "evaluationStrategy": rule.get("evaluationStrategy", "first_match"),
            "matchMode": rule.get("matchMode", first_case.get("matchMode", "range")),
            "outputType": rule.get("outputType", first_case.get("outputType", "Array")),
            "mappingStrategy": rule.get("mappingStrategy", first_case.get("mappingStrategy", "broadcast")),
            "cases": normalized_cases,
        })
    return groups


def coerce_advanced_value(value, data_type):
    data_type = str(data_type or "String").strip()
    text = "" if value is None else str(value).strip()
    if data_type == "String":
        return text
    if text == "":
        return [] if data_type == "Array" else ""
    if data_type == "Integer":
        expanded = expand_mapping_output(text)
        if isinstance(expanded, list):
            return [int(parse_parameter_literal(item)) for item in expanded]
        return int(parse_parameter_literal(text))
    if data_type == "Float":
        expanded = expand_mapping_output(text)
        if isinstance(expanded, list):
            return [float(parse_parameter_literal(item)) for item in expanded]
        return float(parse_parameter_literal(text))
    if data_type == "Boolean":
        lowered = text.lower()
        if lowered in ("true", "yes", "y", "1", "是"):
            return True
        if lowered in ("false", "no", "n", "0", "否"):
            return False
        raise ValueError(f"无法转换为 Boolean: {value}")
    if data_type == "Array":
        parsed = expand_mapping_output(text)
        if isinstance(parsed, tuple):
            return list(parsed)
        return parsed if isinstance(parsed, list) else [parsed]
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


def expand_advanced_sources(value, match_mode, data_type):
    if match_mode == "expression":
        return ["" if value is None else str(value).strip()]
    if data_type != "String":
        return expand_mapping_inputs(value)

    text = "" if value is None else str(value).strip()
    # String 源值优先按文本拆分，保留 001 这类业务编码。
    if re.search(r"[,，;；]", text):
        return [part.strip() for part in re.split(r"\s*[,，;；]\s*", text) if part.strip()]
    parsed = parse_parameter_literal(text)
    if isinstance(parsed, (list, tuple, set)):
        return ["" if item is None else str(item).strip() for item in parsed]
    if match_mode == "range":
        expanded = expand_mapping_inputs(text)
        return [str(item) for item in expanded]
    return [text]


def coerce_parameter_rows(ui_rows):
    rows = []
    seen = set()
    for index, row in enumerate(ui_rows, start=1):
        field_name = str(row.get("fieldName", "")).strip()
        raw_value = str(row.get("input", "")).strip()
        data_type = str(row.get("dataType", "String")).strip() or "String"
        rules = normalize_mapping_groups(row.get("rules", []))

        if not any([field_name, raw_value, rules]):
            continue
        if not field_name:
            raise ValueError(f"第 {index} 行输入参数缺少 FieldName")
        if field_name in seen:
            raise ValueError(f"FieldName 重复: {field_name}")
        if data_type not in DATA_TYPES:
            raise ValueError(f"不支持的数据类型: {data_type}")

        seen.add(field_name)
        rows.append({
            "fieldName": field_name,
            "dataType": data_type,
            "input": raw_value,
            "value": coerce_advanced_value(raw_value, data_type),
            "rules": rules,
        })
    return rows


def build_rule_engine_config(rows):
    """Build structured rule config and the runtime payload used by placeholders."""
    parameters = []
    typed_parameters = {}
    raw_parameters = {}
    runtime_mappings = {}
    engine_rules = []
    duplicate_sources = set()

    for param in rows:
        field_name = param["fieldName"]
        typed_parameters[field_name] = param["value"]
        raw_parameters[field_name] = param["input"]
        rule_refs = []
        runtime_rules = []

        for idx, rule in enumerate(param.get("rules", []), start=1):
            rule_name = rule.get("ruleName") or f"{field_name} 映射 {idx}"
            rule_id = f"{field_name}.rule_{idx}"
            case_configs = []
            default_match_mode = rule.get("matchMode", "range")
            default_output_type = rule.get("outputType", "Array")
            default_mapping_strategy = rule.get("mappingStrategy", "broadcast")

            for case_idx, case in enumerate(rule.get("cases", []), start=1):
                source_expr = str(case.get("source", "")).strip()
                if not source_expr:
                    continue
                output_type = case.get("outputType", default_output_type)
                target_raw = case.get("target", "")
                target_value = coerce_advanced_value(target_raw, output_type)
                match_mode = case.get("matchMode", default_match_mode)
                source_values = expand_advanced_sources(
                    source_expr, match_mode, param["dataType"]
                )
                for source_value in source_values:
                    if param["dataType"] == "String":
                        source_key = (field_name, str(source_value))
                    else:
                        source_key = (field_name, str(parse_parameter_literal(source_value)))
                    if source_key in duplicate_sources:
                        raise ValueError(f"参数 {field_name} 的映射源值重复: {source_key[1]}")
                    duplicate_sources.add(source_key)

                target_values = target_value if isinstance(target_value, list) else [target_value]
                if len(source_values) > 1 and len(target_values) > 1:
                    cardinality = "many_to_many"
                elif len(source_values) > 1:
                    cardinality = "many_to_one"
                elif len(target_values) > 1:
                    cardinality = "one_to_many"
                else:
                    cardinality = "one_to_one"

                mapping_strategy = case.get("mappingStrategy", default_mapping_strategy)
                if mapping_strategy == "pairwise" and len(source_values) > 1 and len(source_values) == len(target_values):
                    runtime_targets = target_values
                    runtime_strategy = "pairwise"
                else:
                    runtime_targets = [target_value for _ in source_values]
                    runtime_strategy = "broadcast"

                case_name = case.get("caseName") or f"分支{case_idx}"
                case_id = f"{rule_id}.case_{case_idx}"
                case_configs.append({
                    "caseId": case_id,
                    "caseName": case_name,
                    "enabled": True,
                    "cardinality": cardinality,
                    "sourceSelector": {
                        "matchMode": match_mode,
                        "expression": source_expr,
                        "values": source_values,
                    },
                    "targetTransformer": {
                        "outputType": output_type,
                        "value": target_raw,
                        "resolvedValue": target_value,
                    },
                    "mappingStrategy": mapping_strategy,
                    "runtime": {
                        "strategy": runtime_strategy,
                    },
                })
                for source_value, runtime_target in zip(source_values, runtime_targets):
                    runtime_rules.append({
                        "from": source_value,
                        "to": runtime_target,
                        "ruleName": rule_name,
                        "caseName": case_name,
                        "matchMode": match_mode,
                        "sourceDataType": param["dataType"],
                        "outputType": output_type,
                    })

            if not case_configs:
                continue
            # rule_engine_config 按 switch/if-elif-else 语义保留映射组和分支顺序。
            rule_refs.append(rule_id)
            engine_rules.append({
                "ruleId": rule_id,
                "ruleName": rule_name,
                "enabled": True,
                "fieldName": field_name,
                "evaluationStrategy": rule.get("evaluationStrategy", "first_match"),
                "matchMode": default_match_mode,
                "outputType": default_output_type,
                "mappingStrategy": default_mapping_strategy,
                "cases": case_configs,
            })

        parameters.append({
            "fieldName": field_name,
            "dataType": param["dataType"],
            "input": param["input"],
            "value": param["value"],
            "mappingRef": field_name if runtime_rules else "",
            "ruleRefs": rule_refs,
        })
        if runtime_rules:
            runtime_mappings[field_name] = runtime_rules

    return {
        "schema": SCHEMA_NAME,
        "operator": OPERATOR_NAME,
        "parameters": parameters,
        "rules": engine_rules,
        "runtime_payload": {
            "runtime_parameters": typed_parameters,
            "raw_parameters": raw_parameters,
            "parameter_mappings": runtime_mappings,
        },
    }
