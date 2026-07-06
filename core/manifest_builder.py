"""Build CRPA run manifests from workflow JSON."""

import os
from pathlib import Path

from core.parameters.mapping_schema import normalize_file_filters

from core.workflow.schema import step_display_name


EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}
CSV_EXTENSIONS = {".csv"}


_PARAM_TYPE_MAP = {
    "string": "text",
    "str": "text",
    "text": "text",
    "number": "number",
    "numeric": "number",
    "int": "number",
    "float": "number",
    "date": "date",
    "datetime": "date",
    "bool": "bool",
    "boolean": "bool",
    "file": "file",
    "folder": "folder",
}


def _safe_key(prefix, index):
    return f"{prefix}_{index}"


def _file_type(path):
    ext = Path(str(path or "")).suffix.lower()
    if ext in EXCEL_EXTENSIONS:
        return "excel"
    if ext in CSV_EXTENSIONS:
        return "csv"
    return "file"


def _filters_for_type(file_type):
    if file_type == "excel":
        return ["*.xlsx", "*.xls", "*.xlsm"]
    if file_type == "csv":
        return ["*.csv"]
    return ["*.*"]


def _export_filters(path):
    ext = Path(str(path or "")).suffix.lower()
    if ext == ".csv":
        return ["*.csv"]
    if ext in EXCEL_EXTENSIONS or not ext:
        return ["*.xlsx", "*.csv"]
    return _filters_for_type(_file_type(path))


def _label_from_path(path, fallback):
    name = os.path.basename(str(path or ""))
    return name or fallback


def _parameter_type(data_type):
    return _PARAM_TYPE_MAP.get(str(data_type or "").strip().lower(), "text")


def _build_file_resource(path, key, label, role, required=True, file_type=None, filters=None, **extra):
    file_type = file_type or _file_type(path)
    resource = {
        "key": key,
        "label": label,
        "role": role,
        "type": file_type,
        "path": path or "",
        "required": required,
        "filters": filters or _filters_for_type(file_type),
    }
    resource.update({k: v for k, v in extra.items() if v not in (None, "")})
    return resource


def _read_options(params):
    return {
        "skiprows": params.get("skiprows", 0),
        "nrows": params.get("nrows"),
        "start_col": params.get("start_col", 1),
        "ncols": params.get("ncols"),
        "has_header": params.get("has_header", True),
    }


def _export_target_path(params):
    file_name = str(params.get("file_name") or "").strip()
    folder_path = str(params.get("folder_path") or "").strip()
    if folder_path and file_name:
        return str(Path(folder_path) / file_name)
    return file_name


def _template_output_target_path(params):
    output_path = str(params.get("output_path") or "").strip()
    if output_path:
        return output_path
    return _export_target_path(params)


def _iter_parameter_rows(step):
    params = step.get("params", {}) or {}
    rows = params.get("advanced_parameters")
    if rows:
        for row in rows:
            yield row
        return

    config = params.get("rule_engine_config") or {}
    for item in config.get("parameters", []) or []:
        yield {
            "fieldName": item.get("fieldName", ""),
            "dataType": item.get("dataType", "String"),
            "input": item.get("input", item.get("value", "")),
            "filters": item.get("filters"),
        }

    typed = params.get("typed_parameters") or {}
    for key, value in typed.items():
        yield {
            "fieldName": key,
            "dataType": type(value).__name__,
            "input": value,
        }


def build_run_manifest(workflow_config, existing_manifest=None):
    """Build a run_manifest without changing the executable steps structure."""
    existing_manifest = existing_manifest or {}
    steps = workflow_config.get("steps", []) or []
    file_resources = []
    data_sources = []
    parameters = []
    path_to_key = {}
    param_seen = set()
    file_counter = 1
    template_counter = 1
    output_counter = 1

    for step in steps:
        action = step.get("action")
        params = step.get("params", {}) or {}
        if action == "load_file":
            path = params.get("file_path", "") or ""
            resource_id = ("input", path) if path else ("input", step.get("node_id") or len(data_sources))
            if resource_id not in path_to_key:
                key = _safe_key("file", file_counter)
                file_counter += 1
                path_to_key[resource_id] = key
                file_resources.append(
                    _build_file_resource(
                        path,
                        key,
                        _label_from_path(path, f"数据源文件{file_counter - 1}"),
                        "input",
                    )
                )
            data_sources.append(
                {
                    "key": step.get("node_id") or f"data_{len(data_sources) + 1}",
                    "label": step_display_name(step, "数据源"),
                    "node_id": step.get("node_id", ""),
                    "file_key": path_to_key[resource_id],
                    "sheet": params.get("sheet_name", ""),
                    "sheet_mode": "fixed",
                    "read_options": _read_options(params),
                }
            )
        elif action == "import_template":
            path = params.get("template_path", "") or ""
            resource_id = ("template", path) if path else ("template", step.get("node_id") or template_counter)
            if resource_id not in path_to_key:
                key = _safe_key("template", template_counter)
                template_counter += 1
                path_to_key[resource_id] = key
                file_resources.append(
                    _build_file_resource(
                        path,
                        key,
                        _label_from_path(path, f"模板文件{template_counter - 1}"),
                        "template",
                        node_id=step.get("node_id", ""),
                        param_key="template_path",
                    )
                )
        elif action == "save_template":
            output_path = _template_output_target_path(params)
            key = _safe_key("output", output_counter)
            output_counter += 1
            file_resources.append(
                _build_file_resource(
                    output_path,
                    key,
                    step_display_name(step, params.get("file_name") or f"模板输出{output_counter - 1}"),
                    "output",
                    required=False,
                    file_type="excel",
                    filters=["*.xlsx"],
                    node_id=step.get("node_id", ""),
                    action="save_template",
                    param_key="output_path",
                )
            )
        elif action == "export_df":
            output_path = _export_target_path(params)
            key = _safe_key("output", output_counter)
            output_counter += 1
            file_resources.append(
                _build_file_resource(
                    output_path,
                    key,
                    step_display_name(step, params.get("file_name") or f"导出文件{output_counter - 1}"),
                    "output",
                    required=False,
                    filters=_export_filters(output_path),
                    node_id=step.get("node_id", ""),
                    action="export_df",
                    param_key="export_path",
                )
            )

        if action == "advanced_param_mapping":
            for row in _iter_parameter_rows(step):
                name = str(row.get("fieldName") or "").strip()
                if not name or name in param_seen:
                    continue
                param_seen.add(name)
                item = {
                    "key": name,
                    "label": name,
                    "type": _parameter_type(row.get("dataType")),
                    "default": row.get("input", ""),
                    "required": True,
                }
                if item["type"] == "file":
                    item["filters"] = normalize_file_filters(row.get("filters"))
                parameters.append(item)

    return {
        "file_resources": file_resources,
        "data_sources": data_sources,
        "parameters": parameters,
    }


def ensure_crpa_metadata(workflow_config, existing_crpa=None):
    existing_crpa = existing_crpa or workflow_config.get("crpa") or {}
    return {
        "code": str(existing_crpa.get("code", "")),
        "name": str(existing_crpa.get("name") or workflow_config.get("workflow_name") or ""),
    }


def attach_run_manifest(workflow_config, existing_crpa=None, existing_manifest=None):
    workflow_config["crpa"] = ensure_crpa_metadata(workflow_config, existing_crpa)
    workflow_config["run_manifest"] = build_run_manifest(workflow_config, existing_manifest)
    return workflow_config
