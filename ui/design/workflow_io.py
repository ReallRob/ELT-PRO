"""Workflow file helpers for the design mode."""

import json
import os

from node_editor import EdgeItem, NodeItem
from operator_registry import NODE_REGISTRY


def load_workflow_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_workflow_file(path, config):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


def attach_design_preferences(config, hidden_toolbox, hidden_context_menu, naming_style, custom_names):
    """Persist design-only preferences beside workflow steps for round-trip editing."""
    config["hidden_toolbox"] = list(hidden_toolbox)
    config["hidden_context_menu"] = list(hidden_context_menu)
    config["naming_style"] = naming_style
    if custom_names:
        config["custom_names"] = dict(custom_names)
    return config


def find_missing_load_files(steps):
    missing_files = {}
    for step in steps or []:
        if step.get("action") != "load_file":
            continue
        fpath = step.get("params", {}).get("file_path")
        if fpath and not os.path.exists(fpath):
            missing_files[step.get("node_id")] = fpath
    return missing_files


def apply_file_mapping(steps, mapping):
    if not mapping:
        return
    for step in steps or []:
        node_id = step.get("node_id")
        if node_id in mapping:
            step.setdefault("params", {})["file_path"] = mapping[node_id]


def restore_design_preferences(widget, workflow):
    """Restore settings that affect editor chrome rather than execution semantics."""
    saved_tb = workflow.get("hidden_toolbox", [])
    saved_ctx = workflow.get("hidden_context_menu", [])
    if saved_tb:
        widget.hidden_toolbox = set(saved_tb)
        widget.toolbox.set_hidden_operators(widget.hidden_toolbox)
    if saved_ctx:
        widget.hidden_context_menu = set(saved_ctx)

    widget.naming_style = workflow.get("naming_style", "默认")
    widget.custom_names = workflow.get("custom_names", {})
    widget.toolbox.set_naming(widget.naming_style, widget.custom_names)


def restore_runtime_metadata(widget, workflow):
    widget.runtime_parameters = workflow.get("runtime_parameters", {})
    widget.parameter_mappings = workflow.get("parameter_mappings", {})
    widget._sync_runtime_parameters()


def _dependency_ids(action, params):
    deps = []
    if action in ("left_join", "concat_rows"):
        if "df1_id" in params:
            deps.append(params["df1_id"])
        if "df2_id" in params:
            deps.append(params["df2_id"])
    elif action == "insert_block":
        if "df_id" in params:
            deps.append(params["df_id"])
        if "template_id" in params:
            deps.append(params["template_id"])
    elif "df_id" in params:
        deps.append(params["df_id"])
    return deps


def restore_steps_to_scene(steps, canvas_scene, clear_scene=True):
    """Rebuild node and edge items from saved workflow steps."""
    if clear_scene:
        canvas_scene.clear()

    created_nodes = {}
    for i, step in enumerate(steps or []):
        node_id = step.get("node_id", f"legacy_{i}")
        action = step.get("action")
        out_name = step.get("out_name", f"Result_{i}")
        params = dict(step.get("params", {}))
        params["out_name"] = out_name
        params["action"] = action

        color = NODE_REGISTRY.get(action, {}).get("color", "#1976D2")
        title = f"{out_name}" if action != "load_file" else f"表: {out_name}"
        node = NodeItem(
            node_id,
            action,
            title,
            color,
            step.get("x", 50),
            step.get("y", 50 + i * 100),
        )
        node.params = params
        node.is_dirty = True
        canvas_scene.addItem(node)
        created_nodes[node_id] = node

    for step in steps or []:
        node = created_nodes.get(step.get("node_id"))
        if not node:
            continue
        for src_id in _dependency_ids(node.action_type, step.get("params", {})):
            if src_id in created_nodes:
                edge = EdgeItem(created_nodes[src_id], node)
                canvas_scene.addItem(edge)
                created_nodes[src_id].edges_out.append(edge)
                node.edges_in.append(edge)

    return created_nodes
