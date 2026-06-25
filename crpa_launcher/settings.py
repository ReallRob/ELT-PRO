"""Persistent settings for the isolated CRPA launcher."""

import json
from pathlib import Path

from core.app_paths import get_workspace_config_path


SECTION_KEY = "crpa_launcher"
CONFIG_PATH = get_workspace_config_path()


def load_workspace_config():
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_workspace_config(data):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def get_last_workflow_path():
    state = load_workspace_config().get(SECTION_KEY, {})
    path = state.get("last_workflow_path", "")
    return path if path and Path(path).exists() else ""


def set_last_workflow_path(path):
    data = load_workspace_config()
    section = data.setdefault(SECTION_KEY, {})
    section["last_workflow_path"] = str(path)
    save_workspace_config(data)
