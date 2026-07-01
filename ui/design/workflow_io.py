"""Workflow file helpers for the design mode."""

import json
import os

from node_editor import EdgeItem, NodeItem
from core.manifest_builder import attach_run_manifest
from core.workflow.schema import migrate_workflow_config, operation_display_name
from operator_registry import NODE_REGISTRY, get_operator_title


def load_workflow_file(path):
    with open(path, "r", encoding="utf-8") as f:
        workflow = json.load(f)
    workflow = migrate_workflow_config(workflow)
    validate_workflow_config(workflow)
    return workflow


def validate_workflow_config(workflow):
    if not isinstance(workflow, dict):
        raise ValueError("工作流 JSON 顶层必须是对象")
    steps = workflow.get("steps")
    if not isinstance(steps, list):
        raise ValueError("工作流 JSON 缺少 steps 列表")
    seen_ids = set()
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"第 {index} 个步骤必须是对象")
        node_id = step.get("node_id")
        action = step.get("action")
        params = step.get("params")
        if not node_id:
            raise ValueError(f"第 {index} 个步骤缺少 node_id")
        if node_id in seen_ids:
            raise ValueError(f"重复的 node_id: {node_id}")
        seen_ids.add(node_id)
        if not action:
            raise ValueError(f"第 {index} 个步骤缺少 action")
        if action not in NODE_REGISTRY:
            raise ValueError(f"未知算子 action: {action}")
        if not isinstance(params, dict):
            raise ValueError(f"第 {index} 个步骤 params 必须是对象")
        if "inputs" in params and not isinstance(params.get("inputs"), list):
            raise ValueError(f"第 {index} 个步骤 inputs 必须是列表")
        if "outputs" in params and not isinstance(params.get("outputs"), list):
            raise ValueError(f"第 {index} 个步骤 outputs 必须是列表")
    return True


def save_workflow_file(path, config):
    config = migrate_workflow_config(config)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


def find_missing_load_files(steps):
    missing_files = {}
    for step in steps or []:
        if step.get("action") not in ("load_file", "import_template"):
            continue
        params = step.get("params", {})
        fpath = params.get("file_path") or params.get("template_path")
        if fpath and not os.path.exists(fpath):
            missing_files[step.get("node_id")] = fpath
    return missing_files


def apply_file_mapping(steps, mapping):
    if not mapping:
        return
    for step in steps or []:
        node_id = step.get("node_id")
        if node_id not in mapping:
            continue
        params = step.setdefault("params", {})
        if step.get("action") == "import_template":
            params["template_path"] = mapping[node_id]
        else:
            params["file_path"] = mapping[node_id]


def restore_runtime_metadata(widget, workflow):
    widget.runtime_parameters = workflow.get("runtime_parameters", {})
    widget.parameter_mappings = workflow.get("parameter_mappings", {})
    widget.global_code = str(workflow.get("global_code") or "")
    widget.crpa_metadata = workflow.get("crpa", {})
    widget.run_manifest = workflow.get("run_manifest", {})


def attach_publish_metadata(config, crpa=None, run_manifest=None):
    return attach_run_manifest(config, crpa, run_manifest)


def _input_dependencies(params):
    deps = []
    seen = set()
    for item in params.get("inputs", []) or []:
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_node_id")
        if source_id and source_id not in seen:
            deps.append(source_id)
            seen.add(source_id)
    return deps


def restore_steps_to_scene(steps, canvas_scene, clear_scene=True):
    """Rebuild node and edge items from saved workflow steps."""
    if clear_scene:
        canvas_scene.clear()

    created_nodes = {}
    for i, step in enumerate(steps or []):
        node_id = step.get("design_node_id") or step.get("node_id")
        if not node_id:
            raise ValueError(f"第 {i + 1} 个步骤缺少 node_id")
        action = step.get("action")
        if action not in NODE_REGISTRY:
            raise ValueError(f"未知算子 action: {action}")
        params = dict(step.get("params", {}) or {})
        params["action"] = action

        color = NODE_REGISTRY.get(action, {}).get("color", "#1976D2")
        title = operation_display_name(
            {"params": params, "action": action},
            get_operator_title(action),
        )
        node = NodeItem(
            node_id,
            action,
            title,
            color,
            step.get("x", 50),
            step.get("y", 50 + i * 100),
            operator_name=get_operator_title(action),
        )
        node.params = params
        node.is_dirty = True
        canvas_scene.addItem(node)
        created_nodes[node_id] = node

    for step in steps or []:
        node_id = step.get("design_node_id") or step.get("node_id")
        node = created_nodes.get(node_id)
        if not node:
            continue
        dependencies = step.get("design_dependencies") or _input_dependencies(step.get("params", {}) or {})
        for src_id in dependencies:
            if src_id in created_nodes:
                edge = EdgeItem(created_nodes[src_id], node)
                canvas_scene.addItem(edge)
                created_nodes[src_id].edges_out.append(edge)
                node.edges_in.append(edge)

    return created_nodes
