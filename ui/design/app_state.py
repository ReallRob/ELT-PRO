"""Workspace state helpers for the design mode."""

import json
import sys
from pathlib import Path

from PyQt5.QtCore import QByteArray


def workspace_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def workspace_config_path():
    return workspace_root() / "config" / "workspace_config.json"


def load_workspace_config():
    path = workspace_config_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_workspace_config(data):
    path = workspace_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def collect_design_state(widget):
    state = {
        "naming_style": widget.naming_style,
        "custom_names": widget.custom_names,
        "hidden_toolbox": list(widget.hidden_toolbox),
        "hidden_context_menu": list(widget.hidden_context_menu),
        "runtime_parameters": widget.runtime_parameters,
        "parameter_mappings": widget.parameter_mappings,
        "dock_state": str(widget.dock_main.saveState().toBase64(), encoding="ascii"),
    }
    if getattr(widget, "_last_workflow_path", None):
        state["last_workflow_path"] = widget._last_workflow_path
    return state


def apply_design_state(widget, state):
    """Apply saved editor chrome state and return the last workflow path, if any."""
    widget.naming_style = state.get("naming_style", "默认")
    widget.custom_names = state.get("custom_names", {})
    widget.hidden_toolbox = set(state.get("hidden_toolbox", []))
    widget.hidden_context_menu = set(state.get("hidden_context_menu", []))
    widget.runtime_parameters = state.get("runtime_parameters", {})
    widget.parameter_mappings = state.get("parameter_mappings", {})

    widget.toolbox._hidden = widget.hidden_toolbox
    widget.toolbox._naming_style = widget.naming_style
    widget.toolbox._custom_names = widget.custom_names
    widget.toolbox.init_ui()
    widget._sync_runtime_parameters()

    dock_b64 = state.get("dock_state", "")
    if dock_b64:
        try:
            dock_state = QByteArray.fromBase64(dock_b64.encode("ascii"))
            widget.dock_main.restoreState(dock_state)
        except Exception:
            pass

    return state.get("last_workflow_path")
