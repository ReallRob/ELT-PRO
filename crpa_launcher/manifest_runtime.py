"""Runtime helpers for CRPA launcher JSON files."""

import copy
import json
import os
from pathlib import Path

from core.manifest_builder import attach_run_manifest
from core.workflow.schema import migrate_workflow_config
from core.parameters.mapping_schema import build_rule_engine_config, coerce_parameter_rows


def load_workflow_json(path):
    with open(path, "r", encoding="utf-8") as f:
        workflow = json.load(f)
    workflow = migrate_workflow_config(workflow)
    if "run_manifest" not in workflow:
        attach_run_manifest(workflow, workflow.get("crpa"))
    if "crpa" not in workflow:
        attach_run_manifest(workflow)
    return workflow


def save_workflow_json(path, workflow):
    workflow = migrate_workflow_config(workflow)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(workflow, f, ensure_ascii=False, indent=4)


def file_dialog_filter(resource):
    filters = resource.get("filters") or ["*.*"]
    joined = " ".join(filters)
    if resource.get("role") == "template":
        label = "模板文件"
    elif resource.get("role") == "output":
        label = "输出文件"
    else:
        label = "数据文件"
    return f"{label} ({joined});;所有文件 (*.*)"


def collect_file_contexts(workflow):
    contexts = {}
    manifest = workflow.get("run_manifest") or {}
    data_sources = manifest.get("data_sources") or []
    by_file = {}
    for source in data_sources:
        by_file.setdefault(source.get("file_key"), []).append(source)
    for resource in manifest.get("file_resources", []) or []:
        key = resource.get("key")
        contexts[key] = by_file.get(key, [])
    return contexts


def load_excel_sheet_names(path):
    if not path or not os.path.exists(path):
        return []
    if Path(path).suffix.lower() not in {".xlsx", ".xls", ".xlsm"}:
        return []
    try:
        import pandas as pd

        with pd.ExcelFile(path) as excel:
            return list(excel.sheet_names)
    except Exception:
        return []


def _coerce_param_value(value, param_type):
    text = "" if value is None else str(value).strip()
    if param_type == "number":
        try:
            if "." in text:
                return float(text)
            return int(text)
        except ValueError:
            return text
    if param_type == "bool":
        return text.lower() in {"1", "true", "yes", "y", "是"}
    return text


def _update_parameter_steps(workflow, parameter_values):
    if not parameter_values:
        return
    for step in workflow.get("steps", []) or []:
        if step.get("action") != "advanced_param_mapping":
            continue
        params = step.setdefault("params", {})
        rows = copy.deepcopy(params.get("advanced_parameters") or [])
        if not rows and params.get("rule_engine_config"):
            for item in params.get("rule_engine_config", {}).get("parameters", []) or []:
                rows.append(
                    {
                        "fieldName": item.get("fieldName", ""),
                        "dataType": item.get("dataType", "String"),
                        "input": item.get("input", ""),
                        "rules": [],
                    }
                )
        if not rows:
            rows = [
                {"fieldName": key, "dataType": "String", "input": "", "rules": []}
                for key in parameter_values
            ]
        for row in rows:
            name = row.get("fieldName")
            if name in parameter_values:
                row["input"] = str(parameter_values[name])
        coerced = coerce_parameter_rows(rows)
        config = build_rule_engine_config(coerced)
        runtime_payload = config["runtime_payload"]
        params["advanced_parameters"] = coerced
        params["parameters"] = runtime_payload["raw_parameters"]
        params["typed_parameters"] = runtime_payload["runtime_parameters"]
        params["parameter_mappings"] = runtime_payload["parameter_mappings"]
        params["rule_engine_config"] = config


def _update_steps_from_manifest(workflow, manifest, file_paths, data_sources):
    resources = {
        item.get("key"): item for item in manifest.get("file_resources", []) or []
    }
    sources = {
        item.get("node_id") or item.get("key"): item
        for item in manifest.get("data_sources", []) or []
    }
    resources_by_path_role = {
        (item.get("role"), item.get("path")): item
        for item in resources.values()
        if item.get("role") and item.get("path")
    }
    resources_by_node_param = {
        (item.get("node_id"), item.get("param_key")): item
        for item in resources.values()
        if item.get("node_id") and item.get("param_key")
    }
    for key, path in file_paths.items():
        if key in resources:
            resources[key]["path"] = path

    for step in workflow.get("steps", []) or []:
        action = step.get("action")
        params = step.setdefault("params", {})
        if action == "load_file":
            source = sources.get(step.get("node_id"))
            if not source:
                continue
            file_key = source.get("file_key")
            if file_key in file_paths:
                params["file_path"] = file_paths[file_key]
            source_runtime = data_sources.get(source.get("key")) or data_sources.get(step.get("node_id")) or {}
            sheet = source_runtime.get("sheet") or source.get("sheet")
            if sheet not in (None, ""):
                params["sheet_name"] = sheet
                source["sheet"] = sheet
            read_options = source.get("read_options") or {}
            for opt_key, value in read_options.items():
                if value is not None:
                    params[opt_key] = value
        elif action == "import_template":
            template_resource = resources_by_node_param.get((step.get("node_id"), "template_path"))
            if not template_resource:
                template_resource = resources_by_path_role.get((
                    "template", params.get("template_path")
                ))
            if template_resource and template_resource.get("key") in file_paths:
                params["template_path"] = file_paths[template_resource["key"]]
        elif action == "save_template":
            output_resource = resources_by_node_param.get((step.get("node_id"), "output_path"))
            if output_resource and output_resource.get("key") in file_paths:
                output_path = file_paths[output_resource["key"]]
                params["output_path"] = output_path
                if output_path:
                    path_obj = Path(output_path)
                    params["file_name"] = path_obj.name
                    params["folder_path"] = str(path_obj.parent) if str(path_obj.parent) != "." else ""
        elif action == "export_df":
            export_resource = resources_by_node_param.get((step.get("node_id"), "export_path"))
            if export_resource and export_resource.get("key") in file_paths:
                export_path = file_paths[export_resource["key"]]
                if export_path:
                    path_obj = Path(export_path)
                    params["file_name"] = path_obj.name
                    params["folder_path"] = str(path_obj.parent) if str(path_obj.parent) != "." else ""


def build_runtime_workflow(base_workflow, file_paths, data_sources, parameters):
    workflow = copy.deepcopy(base_workflow)
    if "run_manifest" not in workflow:
        attach_run_manifest(workflow, workflow.get("crpa"))
    manifest = workflow.get("run_manifest") or {}
    _update_steps_from_manifest(workflow, manifest, file_paths, data_sources)
    _update_parameter_steps(workflow, parameters)
    workflow["runtime_parameters"] = {
        key: _coerce_param_value(value, item.get("type", "text"))
        for item in manifest.get("parameters", []) or []
        for key, value in [(item.get("key"), parameters.get(item.get("key"), item.get("default", "")))]
        if key
    }
    return workflow


def build_crpa_payload(workflow, file_paths, data_sources, parameters):
    crpa = workflow.get("crpa") or {}
    manifest = workflow.get("run_manifest") or {}
    return {
        "crpa_code": crpa.get("code", ""),
        "crpa_name": crpa.get("name", ""),
        "file_resources": dict(file_paths),
        "data_sources": copy.deepcopy(data_sources),
        "parameters": dict(parameters),
        "manifest": copy.deepcopy(manifest),
    }
