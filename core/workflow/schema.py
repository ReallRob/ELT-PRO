"""Workflow JSON helpers for the explicit input/output model."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any


SOURCE_ACTIONS = {"load_file", "import_template"}
PARAMETER_ACTIONS = {"advanced_param_mapping"}
BATCH_MAP_ACTIONS = {
    "filter_data",
    "sort_data",
    "clean_data",
    "group_calc",
    "get_col_data",
    "drop_duplicates",
    "transpose_data",
    "pivot_table",
    "melt_table",
    "rank_col",
    "calc_col",
    "cumsum_data",
    "pct_change_data",
}
BINARY_ACTIONS = {"left_join", "concat_rows"}

LEGACY_PARAM_KEYS = {
    "action",
    "df_name",
    "df1_name",
    "df2_name",
    "template_name",
    "out_name",
    "df_id",
    "df1_id",
    "df2_id",
    "template_id",
    "input_bindings",
}

OUTPUT_SUFFIX = {
    "load_file": "\u6570\u636e",
    "get_col_data": "\u63d0\u53d6",
    "filter_data": "\u7b5b\u9009",
    "sort_data": "\u6392\u5e8f",
    "clean_data": "\u6e05\u6d17",
    "group_calc": "\u6c47\u603b",
    "drop_duplicates": "\u53bb\u91cd",
    "sample_data": "\u62bd\u6837",
    "transpose_data": "\u8f6c\u7f6e",
    "pivot_table": "\u900f\u89c6",
    "melt_table": "\u9006\u900f\u89c6",
    "describe_data": "\u63cf\u8ff0\u7edf\u8ba1",
    "left_join": "\u8fde\u63a5",
    "concat_rows": "\u62fc\u63a5",
    "rank_col": "\u6392\u540d",
    "calc_col": "\u8ba1\u7b97",
    "cumsum_data": "\u7d2f\u52a0",
    "pct_change_data": "\u73af\u6bd4",
    "export_df": "\u5bfc\u51fa",
    "insert_block": "\u5199\u5165\u6a21\u677f",
    "import_template": "\u52a0\u8f7d\u6a21\u677f",
    "save_template": "\u4fdd\u5b58\u6a21\u677f",
    "code_block": "\u4ee3\u7801\u7ed3\u679c",
}

OUTPUT_TYPE = {
    "import_template": "workbook",
    "insert_block": "workbook",
    "save_template": "workbook",
    "advanced_param_mapping": "parameter",
}


class WorkflowSchemaError(ValueError):
    """Raised when a canvas node cannot be compiled into the new workflow model."""


def strip_legacy_params(params: dict[str, Any] | None) -> dict[str, Any]:
    cleaned = copy.deepcopy(params or {})
    for key in LEGACY_PARAM_KEYS:
        cleaned.pop(key, None)
    return cleaned


def output_data_type(action: str) -> str:
    return OUTPUT_TYPE.get(action, "table")


def action_suffix(action: str) -> str:
    return OUTPUT_SUFFIX.get(action, "结果")


def default_load_output_name(params: dict[str, Any], fallback: str = "数据源") -> str:
    sheet = str(params.get("sheet_name") or "").strip()
    if sheet and sheet not in {"0", "CSV文件"}:
        return sheet
    path = str(params.get("file_path") or "").strip()
    if path:
        return Path(path).stem or fallback
    return fallback


def default_output_name(
    action: str,
    params: dict[str, Any],
    input_name: str = "",
    fallback_title: str = "",
) -> str:
    explicit = str(params.get("out_name") or "").strip()
    if explicit:
        return explicit
    if action == "load_file":
        return default_load_output_name(params, fallback_title or "数据源")
    if action == "import_template":
        path = str(params.get("template_path") or "").strip()
        if path:
            return f"模板_{Path(path).stem}"
        return "加载模板"
    if action == "insert_block":
        return "写入模板"
    if action == "save_template":
        return "保存模板"
    if action == "code_block":
        return "代码块结果"
    if action == "export_df":
        return "导出记录"
    suffix = action_suffix(action)
    base = str(input_name or "").strip()
    if base:
        return f"{base}_{suffix}"
    return str(fallback_title or suffix or "结果").strip() or "结果"


def operation_display_name(step: dict[str, Any], default: str = "") -> str:
    params = step.get("params", {}) or {}
    explicit = str(params.get("operation_name") or "").strip()
    if explicit:
        return explicit
    return str(step.get("title") or default or "").strip()


def normalize_output_refs(node_id: str, params: dict[str, Any] | None, source_action: str = "") -> list[dict[str, Any]]:
    refs = []
    for index, output in enumerate((params or {}).get("outputs") or [], start=1):
        if not isinstance(output, dict):
            continue
        name = str(output.get("name") or "").strip()
        if not name:
            continue
        refs.append(
            {
                "source_node_id": str(node_id),
                "source_output_id": str(output.get("output_id") or f"out_{index}"),
                "name": name,
                "data_type": str(output.get("data_type") or "table"),
                "source_action": str(source_action or (params or {}).get("action") or ""),
            }
        )
    return refs


def _available_key(ref: dict[str, Any]) -> tuple[str, str]:
    return (str(ref.get("source_node_id") or ""), str(ref.get("source_output_id") or "out_1"))


def _available_name(ref: dict[str, Any]) -> str:
    return str(ref.get("name") or "").strip()


def _io_prefs(params: dict[str, Any] | None) -> dict[str, Any]:
    prefs = (params or {}).get("io_prefs") or {}
    return copy.deepcopy(prefs) if isinstance(prefs, dict) else {}


def _input_prefs(params: dict[str, Any]) -> list[dict[str, Any]]:
    prefs = _io_prefs(params)
    has_pref_inputs = any(key in prefs for key in ("selected_input", "inputs", "bindings"))
    if not has_pref_inputs:
        return [item for item in params.get("inputs") or [] if isinstance(item, dict)]

    raw_items = []
    if isinstance(prefs.get("bindings"), list):
        raw_items = prefs.get("bindings") or []
    elif isinstance(prefs.get("inputs"), list):
        raw_items = prefs.get("inputs") or []
    elif isinstance(prefs.get("selected_input"), dict):
        raw_items = [prefs.get("selected_input")]

    inputs = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        normalized = copy.deepcopy(item)
        if not str(normalized.get("name") or "").strip():
            normalized["name"] = str(
                normalized.get("table_name")
                or normalized.get("input_name")
                or normalized.get("display_name")
                or ""
            )
        if not str(normalized.get("role") or "").strip():
            normalized["role"] = str(normalized.get("alias") or "current")
        if "enabled" not in normalized:
            normalized["enabled"] = True
        if not str(normalized.get("data_type") or "").strip() and prefs.get("input_data_type"):
            normalized["data_type"] = str(prefs.get("input_data_type") or "")
        inputs.append(normalized)
    return inputs


def _output_prefs(params: dict[str, Any]) -> list[dict[str, Any]]:
    saved_outputs = [item for item in params.get("outputs") or [] if isinstance(item, dict)]
    prefs = _io_prefs(params)
    has_pref_outputs = any(key in prefs for key in ("outputs", "output_name", "display_name", "output_data_type", "output_id"))
    if not has_pref_outputs:
        return saved_outputs

    if isinstance(prefs.get("outputs"), list):
        raw_outputs = prefs.get("outputs") or []
    else:
        raw_outputs = [
            {
                "output_id": prefs.get("output_id") or "out_1",
                "name": prefs.get("output_name") or prefs.get("display_name") or "",
                "data_type": prefs.get("output_data_type") or "",
            }
        ]

    pref_outputs = []
    for index, item in enumerate(raw_outputs, start=1):
        if not isinstance(item, dict):
            continue
        normalized = copy.deepcopy(item)
        normalized.setdefault("output_id", f"out_{index}")
        if not str(normalized.get("name") or "").strip():
            normalized["name"] = str(normalized.get("output_name") or normalized.get("display_name") or "")
        if not str(normalized.get("data_type") or "").strip() and prefs.get("output_data_type"):
            normalized["data_type"] = str(prefs.get("output_data_type") or "")
        pref_outputs.append(normalized)

    if not pref_outputs:
        return []
    if len(saved_outputs) > len(pref_outputs):
        return saved_outputs

    merged = []
    for index, pref in enumerate(pref_outputs):
        saved = copy.deepcopy(saved_outputs[index]) if index < len(saved_outputs) else {}
        item = saved
        for key, value in pref.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip() and key in item:
                continue
            item[key] = value
        merged.append(item)
    return merged


def _find_ref(incoming_refs: list[dict[str, Any]], name: str = "", data_type: str = ""):
    wanted_name = str(name or "").strip()
    for ref in incoming_refs:
        if wanted_name and _available_name(ref) == wanted_name:
            return ref
    for ref in incoming_refs:
        if data_type and str(ref.get("data_type") or "table") == data_type:
            return ref
    return incoming_refs[0] if incoming_refs else None


def _make_input(ref: dict[str, Any], index: int, role: str = "current", saved: dict[str, Any] | None = None):
    saved = saved or {}
    return {
        "input_id": str(saved.get("input_id") or f"in_{index}"),
        "source_node_id": str(ref.get("source_node_id") or ""),
        "source_output_id": str(ref.get("source_output_id") or "out_1"),
        "name": str(ref.get("name") or ""),
        "role": str(saved.get("role") or role),
        "data_type": str(saved.get("data_type") or ref.get("data_type") or "table"),
        "enabled": bool(saved.get("enabled", True)),
        "source_action": str(saved.get("source_action") or ref.get("source_action") or ""),
        "sheet_name": str(saved.get("sheet_name") or ref.get("sheet_name") or ""),
        "ws_alias": str(saved.get("ws_alias") or ref.get("ws_alias") or ""),
    }


def _normalize_saved_inputs(params: dict[str, Any], incoming_refs: list[dict[str, Any]]):
    available_by_key = {_available_key(ref): ref for ref in incoming_refs}
    available_by_name = {}
    for ref in incoming_refs:
        name = _available_name(ref)
        if name:
            available_by_name.setdefault(name, []).append(ref)
    normalized = []
    used = set()
    for index, saved in enumerate(_input_prefs(params), start=1):
        if not isinstance(saved, dict):
            continue
        key = (
            str(saved.get("source_node_id") or ""),
            str(saved.get("source_output_id") or "out_1"),
        )
        ref = available_by_key.get(key)
        if ref is None:
            for candidate in available_by_name.get(str(saved.get("name") or "").strip(), []):
                if _available_key(candidate) not in used:
                    ref = candidate
                    break
        if ref is None:
            continue
        input_item = _make_input(ref, index, role=str(saved.get("role") or "current"), saved=saved)
        used.add(_available_key(ref))
        normalized.append(input_item)
    return normalized, used


def _inputs_from_refs(incoming_refs: list[dict[str, Any]], role: str = "current", start_index: int = 1):
    return [
        _make_input(ref, index, role=role)
        for index, ref in enumerate(incoming_refs, start=start_index)
        if str(ref.get("name") or "").strip()
    ]


def _append_unsaved_refs(
    inputs: list[dict[str, Any]],
    incoming_refs: list[dict[str, Any]],
    used: set[tuple[str, str]],
    role: str = "current",
    data_type: str = "",
):
    merged = list(inputs)
    for ref in incoming_refs:
        if _available_key(ref) in used:
            continue
        if data_type and str(ref.get("data_type") or "table") != data_type:
            continue
        if not str(ref.get("name") or "").strip():
            continue
        merged.append(_make_input(ref, len(merged) + 1, role=role))
    return merged


def _code_block_aliases(inputs: list[dict[str, Any]]):
    table_count = sum(1 for item in inputs if item.get("data_type") == "table")
    workbook_count = sum(1 for item in inputs if item.get("data_type") == "workbook")
    return table_count, workbook_count


def _make_code_block_input(ref: dict[str, Any], index: int, inputs: list[dict[str, Any]]):
    data_type = str(ref.get("data_type") or "table")
    table_count, workbook_count = _code_block_aliases(inputs)
    if data_type == "workbook":
        role = "wb" if workbook_count == 0 else f"wb{workbook_count}"
        return _make_input(ref, index, role=role)
    role = "df" if table_count == 0 else f"df{table_count}"
    return _make_input(ref, index, role=role)


def normalize_inputs(action: str, params: dict[str, Any], incoming_refs: list[dict[str, Any]]):
    if action in SOURCE_ACTIONS or action in PARAMETER_ACTIONS:
        return []

    saved_inputs, used = _normalize_saved_inputs(params, incoming_refs)
    if not incoming_refs:
        return []

    if action in BATCH_MAP_ACTIONS:
        table_inputs = [item for item in saved_inputs if str(item.get("data_type") or "table") == "table"]
        return _append_unsaved_refs(table_inputs, incoming_refs, used, data_type="table")

    if action in BINARY_ACTIONS:
        if saved_inputs:
            merged = [item for item in saved_inputs if str(item.get("data_type") or "table") == "table"]
            role_by_index = ["left", "right"]
            for ref in incoming_refs:
                if len(merged) >= 2:
                    break
                if _available_key(ref) in used:
                    continue
                merged.append(_make_input(ref, len(merged) + 1, role_by_index[len(merged)]))
            return merged
        left = _find_ref(incoming_refs, params.get("df1_name"))
        right = _find_ref(
            [ref for ref in incoming_refs if ref is not left],
            params.get("df2_name"),
        )
        refs = [ref for ref in (left, right) if ref is not None]
        roles = ("left", "right")
        return [_make_input(ref, index, roles[index - 1]) for index, ref in enumerate(refs, start=1)]

    if action == "code_block":
        if saved_inputs:
            merged = [item for item in saved_inputs if str(item.get("data_type") or "table") in {"table", "workbook"}]
            for ref in incoming_refs:
                if _available_key(ref) in used:
                    continue
                if str(ref.get("data_type") or "table") not in {"table", "workbook"}:
                    continue
                merged.append(_make_code_block_input(ref, len(merged) + 1, merged))
            return merged
        inputs = []
        allowed_refs = [ref for ref in incoming_refs if str(ref.get("data_type") or "table") in {"table", "workbook"}]
        for index, ref in enumerate(allowed_refs, start=1):
            inputs.append(_make_code_block_input(ref, index, inputs))
        return inputs

    if action == "insert_block":
        merged = [item for item in saved_inputs if str(item.get("data_type") or "") in {"workbook", "table"}]
        used_insert = {_available_key(item) for item in merged}
        has_workbook = any(item.get("data_type") == "workbook" for item in merged)
        has_table = any(item.get("data_type") == "table" for item in merged)
        for ref in incoming_refs:
            if _available_key(ref) in used or _available_key(ref) in used_insert:
                continue
            data_type = str(ref.get("data_type") or "table")
            if data_type == "workbook" and not has_workbook:
                merged.append(_make_input(ref, len(merged) + 1, "workbook"))
                has_workbook = True
            elif data_type == "table" and not has_table:
                merged.append(_make_input(ref, len(merged) + 1, "table"))
                has_table = True
        return merged

    if action == "save_template":
        workbook_inputs = [item for item in saved_inputs if str(item.get("data_type") or "") == "workbook"]
        if workbook_inputs:
            return workbook_inputs[:1]
        workbook_ref = _find_ref(incoming_refs, data_type="workbook")
        return [_make_input(workbook_ref, 1, "workbook")] if workbook_ref else []

    if saved_inputs:
        return saved_inputs[:1]

    selected = _find_ref(incoming_refs, params.get("df_name"), data_type="table")
    return [_make_input(selected, 1)] if selected else []


def _saved_outputs(params: dict[str, Any]):
    return _output_prefs(params)


def _find_saved_output(params: dict[str, Any], input_item: dict[str, Any] | None = None, index: int = 1):
    outputs = _saved_outputs(params)
    if input_item:
        input_id = str(input_item.get("input_id") or "")
        source_node_id = str(input_item.get("source_node_id") or "")
        source_output_id = str(input_item.get("source_output_id") or "out_1")
        for output in outputs:
            if str(output.get("from_input_id") or "") == input_id:
                return output
            if (
                str(output.get("source_node_id") or "") == source_node_id
                and str(output.get("source_output_id") or "out_1") == source_output_id
            ):
                return output
        has_explicit_source = any(
            output.get("from_input_id")
            or output.get("source_node_id")
            or output.get("source_output_id")
            for output in outputs
        )
        if has_explicit_source:
            return {}
    if index - 1 < len(outputs):
        return outputs[index - 1]
    return {}


def _unique_output_id(base: str, used: set[str], fallback: str) -> str:
    output_id = str(base or fallback).strip() or fallback
    original = output_id
    counter = 1
    while output_id in used:
        counter += 1
        output_id = f"{original}_{counter}"
    used.add(output_id)
    return output_id


def _make_output(
    action: str,
    params: dict[str, Any],
    index: int,
    input_item: dict[str, Any] | None,
    fallback_title: str,
    data_type: str | None = None,
    used_ids: set[str] | None = None,
):
    saved = _find_saved_output(params, input_item, index)
    used_ids = used_ids if used_ids is not None else set()
    output_id = _unique_output_id(str(saved.get("output_id") or f"out_{index}"), used_ids, f"out_{index}")
    input_name = str((input_item or {}).get("name") or "")
    name = str(saved.get("name") or "").strip()
    if not name:
        name = default_output_name(action, params, input_name, fallback_title)
    output = {
        "output_id": output_id,
        "name": name,
        "data_type": str(saved.get("data_type") or data_type or output_data_type(action)),
    }
    if input_item:
        output.update(
            {
                "from_input_id": input_item.get("input_id"),
                "source_node_id": input_item.get("source_node_id", ""),
                "source_output_id": input_item.get("source_output_id", "out_1"),
            }
        )
    return output


def normalize_outputs(action: str, params: dict[str, Any], inputs: list[dict[str, Any]], fallback_title: str = ""):
    if action in PARAMETER_ACTIONS:
        return []

    used_ids: set[str] = set()
    enabled_inputs = [item for item in inputs if item.get("enabled", True)]
    if action == "load_file":
        has_source = str(params.get("file_path") or "").strip()
        if not has_source:
            return []
        return [
            _make_output(
                action,
                params,
                1,
                None,
                fallback_title,
                data_type=output_data_type(action),
                used_ids=used_ids,
            )
        ]

    if action == "import_template":
        has_template = str(params.get("template_path") or "").strip()
        if not has_template:
            return []
        return [
            _make_output(
                action,
                params,
                1,
                None,
                fallback_title,
                data_type=output_data_type(action),
                used_ids=used_ids,
            )
        ]

    if action == "code_block":
        saved_outputs = _saved_outputs(params)
        if saved_outputs:
            return [
                _make_output(
                    action,
                    params,
                    index,
                    None,
                    fallback_title,
                    data_type=str(output.get("data_type") or output_data_type(action)),
                    used_ids=used_ids,
                )
                for index, output in enumerate(saved_outputs, start=1)
            ]
        inferred_type = "workbook" if any(item.get("data_type") == "workbook" for item in enabled_inputs) else "table"
        return [
            _make_output(
                action,
                params,
                1,
                None,
                fallback_title,
                data_type=inferred_type,
                used_ids=used_ids,
            )
        ]

    if not enabled_inputs:
        return []

    if action in BATCH_MAP_ACTIONS:
        return [
            _make_output(action, params, index, input_item, fallback_title, used_ids=used_ids)
            for index, input_item in enumerate(enabled_inputs, start=1)
        ]

    if action == "insert_block":
        workbook_input = next((item for item in enabled_inputs if item.get("data_type") == "workbook"), None)
        if workbook_input is None:
            return []
        return [
            _make_output(
                action,
                params,
                1,
                workbook_input,
                fallback_title,
                data_type="workbook",
                used_ids=used_ids,
            )
        ]

    if action == "save_template":
        workbook_input = next((item for item in enabled_inputs if item.get("data_type") == "workbook"), None)
        if workbook_input is None:
            return []
        return [
            _make_output(
                action,
                params,
                1,
                workbook_input,
                fallback_title,
                data_type="workbook",
                used_ids=used_ids,
            )
        ]

    first_input = enabled_inputs[0]
    return [
        _make_output(
            action,
            params,
            1,
            first_input,
            fallback_title,
            data_type=output_data_type(action),
            used_ids=used_ids,
        )
    ]


def normalize_action_params(
    action: str,
    params: dict[str, Any] | None,
    incoming_refs: list[dict[str, Any]] | None = None,
    fallback_title: str = "",
    include_action: bool = False,
) -> dict[str, Any]:
    raw = copy.deepcopy(params or {})
    incoming_refs = copy.deepcopy(incoming_refs or [])
    inputs = normalize_inputs(action, raw, incoming_refs)
    outputs = normalize_outputs(action, raw, inputs, fallback_title=fallback_title)

    normalized = strip_legacy_params(raw)
    normalized["inputs"] = inputs
    normalized["outputs"] = outputs
    if include_action:
        normalized["action"] = action
    return normalized


def _merge_step_legacy_params(step: dict[str, Any]) -> dict[str, Any]:
    params = copy.deepcopy(step.get("params") or {})
    for key in LEGACY_PARAM_KEYS:
        if key == "action":
            continue
        if key in step and key not in params:
            params[key] = step.get(key)
    return params


def _step_needs_io_migration(step: dict[str, Any], params: dict[str, Any]) -> bool:
    legacy_io_keys = LEGACY_PARAM_KEYS - {"action"}
    if any(key in step for key in legacy_io_keys):
        return True
    if any(key in params for key in legacy_io_keys):
        return True
    if isinstance(params.get("io_prefs"), dict):
        return True
    return "inputs" not in params or "outputs" not in params


def _strip_step_legacy_keys(step: dict[str, Any]) -> dict[str, Any]:
    cleaned = copy.deepcopy(step)
    for key in LEGACY_PARAM_KEYS:
        if key == "action":
            continue
        cleaned.pop(key, None)
    return cleaned


def _ordered_unique(values):
    seen = set()
    ordered = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _refs_for_node_ids(node_ids, output_refs_by_node):
    refs = []
    for node_id in _ordered_unique(node_ids):
        refs.extend(copy.deepcopy(output_refs_by_node.get(node_id, [])))
    return refs


def _refs_by_legacy_names(previous_refs: list[dict[str, Any]], names):
    refs = []
    used = set()
    for name in names:
        target = str(name or "").strip()
        if not target:
            continue
        for ref in previous_refs:
            key = _available_key(ref)
            if key in used:
                continue
            if _available_name(ref) == target:
                refs.append(copy.deepcopy(ref))
                used.add(key)
                break
    return refs


def _incoming_refs_for_migration(action: str, params: dict[str, Any], step: dict[str, Any], output_refs_by_node, previous_refs):
    saved_inputs = _input_prefs(params)
    input_node_ids = [item.get("source_node_id") for item in saved_inputs]
    if input_node_ids:
        return _refs_for_node_ids(input_node_ids, output_refs_by_node)

    design_dependencies = step.get("design_dependencies") or []
    if design_dependencies:
        return _refs_for_node_ids(design_dependencies, output_refs_by_node)

    if action in SOURCE_ACTIONS or action in PARAMETER_ACTIONS:
        return []

    if action in BINARY_ACTIONS:
        refs = _refs_for_node_ids([params.get("df1_id"), params.get("df2_id")], output_refs_by_node)
        if refs:
            return refs
        return _refs_by_legacy_names(previous_refs, [params.get("df1_name"), params.get("df2_name")])

    if action == "insert_block":
        refs = _refs_for_node_ids([params.get("df_id"), params.get("template_id")], output_refs_by_node)
        if refs:
            return refs
        table_refs = _refs_by_legacy_names(previous_refs, [params.get("df_name")])
        workbook_refs = _refs_by_legacy_names(previous_refs, [params.get("template_name")])
        return table_refs + workbook_refs

    refs = _refs_for_node_ids([params.get("df_id")], output_refs_by_node)
    if refs:
        return refs
    return _refs_by_legacy_names(previous_refs, [params.get("df_name")])


def migrate_workflow_config(workflow: dict[str, Any] | None) -> dict[str, Any]:
    """Return a workflow config with legacy node params converted to inputs/outputs."""
    migrated = copy.deepcopy(workflow or {})
    steps = migrated.get("steps")
    if not isinstance(steps, list):
        return migrated

    output_refs_by_node = {}
    previous_refs = []
    migrated_steps = []
    for step in steps:
        if not isinstance(step, dict):
            migrated_steps.append(step)
            continue
        action = str(step.get("action") or "").strip()
        node_id = str(step.get("node_id") or step.get("design_node_id") or "").strip()
        if not action:
            migrated_steps.append(step)
            continue

        raw_params = _merge_step_legacy_params(step)
        if _step_needs_io_migration(step, raw_params):
            incoming_refs = _incoming_refs_for_migration(
                action,
                raw_params,
                step,
                output_refs_by_node,
                previous_refs,
            )
            fallback_title = step.get("title") or step.get("out_name") or ""
            normalized = normalize_action_params(
                action,
                raw_params,
                incoming_refs,
                fallback_title=fallback_title,
                include_action=False,
            )
        else:
            normalized = strip_legacy_params(raw_params)

        cleaned_step = _strip_step_legacy_keys(step)
        cleaned_step["params"] = normalized
        migrated_steps.append(cleaned_step)

        if node_id:
            refs = normalize_output_refs(node_id, normalized, action)
            output_refs_by_node[node_id] = refs
            previous_refs.extend(refs)
    migrated["steps"] = migrated_steps
    return migrated


def step_display_name(step: dict[str, Any], default: str = "结果") -> str:
    params = step.get("params", {}) or {}
    outputs = [item for item in params.get("outputs") or [] if isinstance(item, dict)]
    if len(outputs) == 1:
        return str(outputs[0].get("name") or default)
    if len(outputs) > 1:
        return f"{len(outputs)} 个输出"
    return str(step.get("title") or default)
