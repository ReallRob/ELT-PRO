"""Shared dynamic-import manifest used by package-management tooling and specs."""

from __future__ import annotations

import copy
import importlib.machinery
import json
import re
import sys
import sysconfig
from pathlib import Path


MANIFEST_RELATIVE_PATH = Path("config") / "dynamic_imports.json"
TARGETS = ("main", "crpa_launcher", "crpa_json")
_MODULE_ROOT_RE = re.compile(r"^[A-Za-z_]\w*$")
DELIVERY_BUNDLED = "bundled"
DELIVERY_EXTERNAL = "external"
DELIVERY_MODES = (DELIVERY_BUNDLED, DELIVERY_EXTERNAL)
_DEFAULT_DEPENDENCIES = (
    "PyQt5",
    "numpy",
    "openpyxl",
    "pandas",
)
_BASELINE_MODULES = frozenset(module.casefold() for module in _DEFAULT_DEPENDENCIES)
_STDLIB_MODULES = frozenset(getattr(sys, "stdlib_module_names", ())) | {"tkinter"}
_STDLIB_COLLECT_ALL_MODULES = frozenset({"tkinter"})
_RUNTIME_STDLIB_EXCLUDES = frozenset(
    {
        "ensurepip",
        "idlelib",
        "lib2to3",
        "pydoc_data",
        "test",
        "tests",
        "turtledemo",
    }
)


def get_project_root():
    return Path(__file__).resolve().parents[2]


def get_manifest_path(project_root=None):
    return Path(project_root or get_project_root()) / MANIFEST_RELATIVE_PATH


def is_standard_library_module(module):
    root = str(module or "").strip().split(".", 1)[0]
    return root in _STDLIB_MODULES


def requires_collect_all(module):
    root = str(module or "").strip().split(".", 1)[0]
    return root in _STDLIB_COLLECT_ALL_MODULES


def runtime_stdlib_import_roots():
    """Return the build host's runtime standard-library roots for PyInstaller."""
    roots = set(getattr(sys, "stdlib_module_names", ())) | {"tkinter"}
    return tuple(sorted(root for root in roots if root not in _RUNTIME_STDLIB_EXCLUDES))


def runtime_stdlib_hidden_imports():
    """List the build host's importable standard-library modules and submodules."""
    roots = set(runtime_stdlib_import_roots())
    stdlib_path = Path(sysconfig.get_path("stdlib") or "")
    if not stdlib_path.is_dir():
        return tuple(sorted(roots))

    suffixes = tuple(
        sorted((".py",) + tuple(importlib.machinery.EXTENSION_SUFFIXES), key=len, reverse=True)
    )
    for path in stdlib_path.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(stdlib_path)
        except ValueError:
            continue
        if not relative.parts or relative.parts[0] in _RUNTIME_STDLIB_EXCLUDES:
            continue
        if "__pycache__" in relative.parts or "site-packages" in relative.parts:
            continue

        filename = relative.name
        suffix = next((item for item in suffixes if filename.endswith(item)), "")
        if not suffix:
            continue
        module_parts = list(relative.parts[:-1]) + [filename[: -len(suffix)]]
        if module_parts[-1] == "__init__":
            module_parts.pop()
        if module_parts and all(part.isidentifier() for part in module_parts):
            roots.add(".".join(module_parts))
    return tuple(sorted(roots))


def is_baseline_dependency(module):
    return str(module or "").strip().casefold() in _BASELINE_MODULES


def default_dependencies():
    return [
        {
            "module": module,
            "distribution": module,
            "collect": "all",
            "delivery": DELIVERY_BUNDLED,
            "targets": list(TARGETS),
            "source": "baseline",
        }
        for module in _DEFAULT_DEPENDENCIES
    ]


def _normalize_dependency(item):
    if not isinstance(item, dict):
        return None
    module = str(item.get("module") or "").strip()
    if not _MODULE_ROOT_RE.match(module):
        return None
    targets = [target for target in item.get("targets") or [] if target in TARGETS]
    if not targets:
        targets = list(TARGETS)
    delivery = str(item.get("delivery") or DELIVERY_BUNDLED).strip().lower()
    if delivery not in DELIVERY_MODES:
        delivery = DELIVERY_BUNDLED
    return {
        "module": module,
        "distribution": str(item.get("distribution") or module).strip() or module,
        "collect": "all",
        "delivery": delivery,
        "targets": list(dict.fromkeys(targets)),
        "source": str(item.get("source") or "manual").strip() or "manual",
    }


def normalize_dependencies(dependencies):
    normalized = []
    seen = set()
    for item in dependencies or []:
        dependency = _normalize_dependency(item)
        if dependency is None:
            continue
        key = dependency["module"].casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(dependency)
    return sorted(normalized, key=lambda item: item["module"].casefold())


def _with_baseline_dependencies(dependencies):
    return normalize_dependencies(list(default_dependencies()) + list(dependencies or []))


def load_dependencies(project_root=None):
    path = get_manifest_path(project_root)
    if not path.exists():
        return default_dependencies()
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return default_dependencies()
    dependencies = _with_baseline_dependencies(payload.get("packages") if isinstance(payload, dict) else [])
    return dependencies


def save_dependencies(dependencies, project_root=None):
    normalized = _with_baseline_dependencies(dependencies)
    path = get_manifest_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 2, "packages": normalized}
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return copy.deepcopy(normalized)


def bundled_import_roots(target=None, project_root=None):
    target = str(target or "").strip()
    dependencies = load_dependencies(project_root)
    return tuple(
        dependency["module"]
        for dependency in dependencies
        if dependency["delivery"] == DELIVERY_BUNDLED
        and (not target or target in dependency["targets"])
    )


def external_dependencies(targets=None, project_root=None):
    selected_targets = set(targets or TARGETS)
    dependencies = load_dependencies(project_root)
    return [
        dependency
        for dependency in dependencies
        if dependency["delivery"] == DELIVERY_EXTERNAL
        and selected_targets.intersection(dependency["targets"])
    ]


def bundled_import_roots_text(project_root=None):
    roots = bundled_import_roots(project_root=project_root)
    external_roots = [
        dependency["module"]
        for dependency in external_dependencies(project_root=project_root)
    ]
    external_text = ""
    if external_roots:
        external_text = "\n\n以下根模块作为外置扩展发布，不会写入当前 Spec：\n" + "\n".join(external_roots)
    return (
        "代码块支持正常 Python import。以下根模块由打包清单默认预收集；"
        "新增第三方包后，请保存清单并生成 Spec。\n\n"
        + "\n".join(roots)
        + external_text
    )
