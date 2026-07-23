"""Persistent settings for the isolated CRPA launcher."""

import json
from datetime import datetime
from pathlib import Path

from core.app_paths import get_crpa_launcher_config_path, get_workspace_config_path


SECTION_KEY = "crpa_launcher"
CONFIG_PATH = get_crpa_launcher_config_path()
LEGACY_CONFIG_PATH = get_workspace_config_path()
JSON_HISTORY_KEY = "json_history"
MAX_JSON_HISTORY = 50


def _read_json(path):
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_legacy_config():
    state = _read_json(LEGACY_CONFIG_PATH).get(SECTION_KEY, {})
    return {SECTION_KEY: state} if isinstance(state, dict) else {}


def load_workspace_config():
    if CONFIG_PATH.exists():
        return _read_json(CONFIG_PATH)
    return _load_legacy_config()


def save_workspace_config(data):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def _normalize_workflow_path(path):
    if not path:
        return ""
    try:
        return str(Path(path).expanduser().resolve())
    except Exception:
        return str(path)


def _history_key(path):
    return _normalize_workflow_path(path).casefold()


def _safe_count(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _sort_history(history):
    return sorted(
        history,
        key=lambda item: (
            str(item.get("last_opened") or ""),
            _safe_count(item.get("open_count")),
        ),
        reverse=True,
    )


def _clean_history(history):
    if not isinstance(history, list):
        return []

    merged = {}
    for raw_item in history:
        if not isinstance(raw_item, dict):
            continue
        path = _normalize_workflow_path(raw_item.get("path") or "")
        if not path:
            continue
        key = _history_key(path)
        item = merged.setdefault(
            key,
            {
                "path": path,
                "crpa_code": "",
                "crpa_name": "",
                "display_name": "",
                "tag": "",
                "open_count": 0,
                "last_opened": "",
            },
        )
        item["open_count"] += _safe_count(raw_item.get("open_count"))
        crpa_code = str(raw_item.get("crpa_code") or raw_item.get("code") or "").strip()
        if crpa_code:
            item["crpa_code"] = crpa_code
        crpa_name = str(raw_item.get("crpa_name") or raw_item.get("name") or "").strip()
        if crpa_name:
            item["crpa_name"] = crpa_name
        display_name = str(raw_item.get("display_name") or raw_item.get("history_name") or "").strip()
        if display_name:
            item["display_name"] = display_name
        tag = str(raw_item.get("tag") or raw_item.get("label") or "").strip()
        if tag and not item["tag"]:
            item["tag"] = tag
        last_opened = str(raw_item.get("last_opened") or "")
        if last_opened > item["last_opened"]:
            item["last_opened"] = last_opened

    return _sort_history(list(merged.values()))[:MAX_JSON_HISTORY]


def get_json_history():
    state = load_workspace_config().get(SECTION_KEY, {})
    return _clean_history(state.get(JSON_HISTORY_KEY, []))


def record_json_load(path, crpa_code="", crpa_name="", tag=None):
    """Add or refresh a history item without treating it as a workflow run."""
    normalized_path = _normalize_workflow_path(path)
    if not normalized_path:
        return get_json_history()

    data = load_workspace_config()
    section = data.setdefault(SECTION_KEY, {})
    history = _clean_history(section.get(JSON_HISTORY_KEY, []))
    key = _history_key(normalized_path)
    now = datetime.now().isoformat(timespec="seconds")
    crpa_code = str(crpa_code or "").strip()
    crpa_name = str(crpa_name or "").strip()
    tag = None if tag is None else str(tag or "").strip()

    for item in history:
        if _history_key(item.get("path")) == key:
            item["last_opened"] = now
            if crpa_code:
                item["crpa_code"] = crpa_code
            if crpa_name:
                item["crpa_name"] = crpa_name
            if tag is not None:
                item["tag"] = tag
            break
    else:
        history.append(
            {
                "path": normalized_path,
                "crpa_code": crpa_code,
                "crpa_name": crpa_name,
                "display_name": "",
                "tag": tag or "",
                "open_count": 0,
                "last_opened": now,
            }
        )

    section[JSON_HISTORY_KEY] = _sort_history(history)[:MAX_JSON_HISTORY]
    save_workspace_config(data)
    return section[JSON_HISTORY_KEY]


def record_json_open(path, crpa_code="", crpa_name="", tag=None):
    normalized_path = _normalize_workflow_path(path)
    if not normalized_path:
        return get_json_history()

    data = load_workspace_config()
    section = data.setdefault(SECTION_KEY, {})
    history = _clean_history(section.get(JSON_HISTORY_KEY, []))
    key = _history_key(normalized_path)
    now = datetime.now().isoformat(timespec="seconds")
    crpa_code = str(crpa_code or "").strip()
    crpa_name = str(crpa_name or "").strip()
    tag = None if tag is None else str(tag or "").strip()

    for item in history:
        if _history_key(item.get("path")) == key:
            item["open_count"] = _safe_count(item.get("open_count")) + 1
            item["last_opened"] = now
            if crpa_code:
                item["crpa_code"] = crpa_code
            if crpa_name:
                item["crpa_name"] = crpa_name
            if tag is not None:
                item["tag"] = tag
            break
    else:
        history.append(
            {
                "path": normalized_path,
                "crpa_code": crpa_code,
                "crpa_name": crpa_name,
                "display_name": "",
                "tag": tag or "",
                "open_count": 1,
                "last_opened": now,
            }
        )

    section[JSON_HISTORY_KEY] = _sort_history(history)[:MAX_JSON_HISTORY]
    save_workspace_config(data)
    return section[JSON_HISTORY_KEY]


def set_json_history_tag(path, tag):
    normalized_path = _normalize_workflow_path(path)
    if not normalized_path:
        return get_json_history()

    data = load_workspace_config()
    section = data.setdefault(SECTION_KEY, {})
    history = _clean_history(section.get(JSON_HISTORY_KEY, []))
    key = _history_key(normalized_path)
    tag = str(tag or "").strip()

    for item in history:
        if _history_key(item.get("path")) == key:
            item["tag"] = tag
            break
    else:
        history.append(
            {
                "path": normalized_path,
                "crpa_code": "",
                "crpa_name": "",
                "display_name": "",
                "tag": tag,
                "open_count": 0,
                "last_opened": "",
            }
        )

    section[JSON_HISTORY_KEY] = _sort_history(history)[:MAX_JSON_HISTORY]
    save_workspace_config(data)
    return section[JSON_HISTORY_KEY]


def set_json_history_name(path, display_name):
    normalized_path = _normalize_workflow_path(path)
    if not normalized_path:
        return get_json_history()

    data = load_workspace_config()
    section = data.setdefault(SECTION_KEY, {})
    history = _clean_history(section.get(JSON_HISTORY_KEY, []))
    key = _history_key(normalized_path)
    display_name = str(display_name or "").strip()

    for item in history:
        if _history_key(item.get("path")) == key:
            item["display_name"] = display_name
            break
    else:
        history.append(
            {
                "path": normalized_path,
                "crpa_code": "",
                "crpa_name": "",
                "display_name": display_name,
                "tag": "",
                "open_count": 0,
                "last_opened": "",
            }
        )

    section[JSON_HISTORY_KEY] = _sort_history(history)[:MAX_JSON_HISTORY]
    save_workspace_config(data)
    return section[JSON_HISTORY_KEY]


def remove_json_history_item(path):
    normalized_path = _normalize_workflow_path(path)
    if not normalized_path:
        return get_json_history()

    data = load_workspace_config()
    section = data.setdefault(SECTION_KEY, {})
    key = _history_key(normalized_path)
    history = [
        item
        for item in _clean_history(section.get(JSON_HISTORY_KEY, []))
        if _history_key(item.get("path")) != key
    ]
    section[JSON_HISTORY_KEY] = history
    if _history_key(section.get("last_workflow_path")) == key:
        section["last_workflow_path"] = ""
    save_workspace_config(data)
    return history


def get_last_workflow_path():
    state = load_workspace_config().get(SECTION_KEY, {})
    path = state.get("last_workflow_path", "")
    return path if path and Path(path).exists() else ""


def set_last_workflow_path(path):
    data = load_workspace_config()
    section = data.setdefault(SECTION_KEY, {})
    section["last_workflow_path"] = str(path)
    save_workspace_config(data)
