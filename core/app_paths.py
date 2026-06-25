"""Application path helpers shared by UI and execution code."""

import sys
from pathlib import Path


def get_exec_dir():
    """Return the directory used for default runtime outputs."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]


def get_config_dir():
    """Return the shared application configuration directory."""
    return get_exec_dir() / "config"


def get_workspace_config_path():
    """Return the shared workspace state file path."""
    return get_config_dir() / "workspace_config.json"
