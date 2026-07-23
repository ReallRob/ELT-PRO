"""Runtime activation for versioned code-block extension packages."""

from __future__ import annotations

import json
import os
import platform
import shutil
import site
import sys
from pathlib import Path


EXTENSIONS_DIRECTORY = "extensions"
VERSIONS_DIRECTORY = "versions"
IMPORTS_DIRECTORY = "imports"
ACTIVE_FILENAME = "active.json"
MANIFEST_FILENAME = "manifest.json"
SITE_PACKAGES_DIRECTORY = "site-packages"
_DLL_DIRECTORY_HANDLES = []


def get_runtime_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def get_extensions_root(runtime_root=None):
    return Path(runtime_root or get_runtime_root()) / EXTENSIONS_DIRECTORY


def get_active_path(runtime_root=None):
    return get_extensions_root(runtime_root) / ACTIVE_FILENAME


def get_imports_root(runtime_root=None):
    return get_extensions_root(runtime_root) / IMPORTS_DIRECTORY


def runtime_identity():
    return {
        "python": ".".join(str(value) for value in sys.version_info[:2]),
        "architecture": platform.architecture()[0],
        "implementation": platform.python_implementation(),
    }


def _read_json(path):
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _safe_version(value):
    version = str(value or "").strip()
    return version if version and Path(version).name == version else ""


def _package_info(identifier, package_root):
    identifier = _safe_version(identifier)
    package_dir = Path(package_root) / identifier if identifier else None
    site_packages = package_dir / SITE_PACKAGES_DIRECTORY if package_dir else None
    manifest_path = package_dir / MANIFEST_FILENAME if package_dir else None
    manifest = _read_json(manifest_path) if manifest_path else None
    info = {
        "version": identifier,
        "version_dir": package_dir,
        "site_packages": site_packages,
        "manifest": manifest,
        "available": bool(package_dir and site_packages and site_packages.is_dir() and manifest),
        "compatible": False,
        "message": "",
    }
    if not identifier:
        info["message"] = "扩展版本无效"
        return info
    if not info["available"]:
        info["message"] = "扩展版本目录、manifest.json 或 site-packages 不完整"
        return info

    expected = manifest.get("runtime") if isinstance(manifest, dict) else {}
    expected = expected if isinstance(expected, dict) else {}
    current = runtime_identity()
    expected_python = str(expected.get("python") or "").strip()
    expected_architecture = str(expected.get("architecture") or "").strip()
    if expected_python and expected_python != current["python"]:
        info["message"] = "扩展包 Python 版本为 {}，当前程序为 {}".format(
            expected_python, current["python"]
        )
        return info
    if expected_architecture and expected_architecture != current["architecture"]:
        info["message"] = "扩展包架构为 {}，当前程序为 {}".format(
            expected_architecture, current["architecture"]
        )
        return info
    info["compatible"] = True
    info["message"] = "可用"
    return info


def extension_info(version, runtime_root=None):
    root = get_extensions_root(runtime_root) / VERSIONS_DIRECTORY
    return _package_info(version, root)


def imported_extension_info(import_id, runtime_root=None):
    info = _package_info(import_id, get_imports_root(runtime_root))
    manifest = info.get("manifest") if isinstance(info.get("manifest"), dict) else {}
    info["import_id"] = info.get("version") or ""
    info["import_dir"] = info.get("version_dir")
    info["source_version"] = _safe_version(manifest.get("version"))
    return info


def active_extension_info(runtime_root=None):
    payload = _read_json(get_active_path(runtime_root))
    if not payload:
        return {
            "version": "",
            "available": False,
            "compatible": False,
            "message": "未启用外置扩展包",
        }
    return extension_info(payload.get("active_version"), runtime_root)


def list_extension_versions(runtime_root=None):
    versions_root = get_extensions_root(runtime_root) / VERSIONS_DIRECTORY
    if not versions_root.is_dir():
        return []
    active = active_extension_info(runtime_root).get("version")
    items = []
    for child in sorted(versions_root.iterdir(), key=lambda item: item.name, reverse=True):
        if not child.is_dir():
            continue
        info = extension_info(child.name, runtime_root)
        info["active"] = child.name == active
        items.append(info)
    return items


def list_imported_extensions(runtime_root=None):
    imports_root = get_imports_root(runtime_root)
    if not imports_root.is_dir():
        return []
    items = []
    for child in sorted(imports_root.iterdir(), key=lambda item: item.name, reverse=True):
        if child.is_dir():
            items.append(imported_extension_info(child.name, runtime_root))
    return items


def set_active_extension(version, runtime_root=None):
    info = extension_info(version, runtime_root)
    if not info.get("available"):
        raise ValueError(info.get("message") or "扩展包不可用")
    if not info.get("compatible"):
        raise ValueError(info.get("message") or "扩展包与当前运行时不兼容")

    active_path = get_active_path(runtime_root)
    active_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = active_path.with_name(active_path.name + ".tmp")
    payload = {"schema_version": 1, "active_version": info["version"]}
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(str(temporary_path), str(active_path))
    return info


def delete_extension_version(version, runtime_root=None):
    version = _safe_version(version)
    if not version:
        raise ValueError("扩展版本无效")
    active = active_extension_info(runtime_root).get("version")
    if version == active:
        raise ValueError("当前启用的扩展版本不能删除，请先启用其他版本")
    version_dir = get_extensions_root(runtime_root) / VERSIONS_DIRECTORY / version
    if not version_dir.is_dir():
        raise ValueError("扩展版本不存在：{}".format(version))
    shutil.rmtree(str(version_dir))


def delete_imported_extension(import_id, runtime_root=None):
    import_id = _safe_version(import_id)
    if not import_id:
        raise ValueError("导入扩展包编号无效")
    import_dir = get_imports_root(runtime_root) / import_id
    if not import_dir.is_dir():
        raise ValueError("导入扩展包不存在：{}".format(import_id))
    shutil.rmtree(str(import_dir))


def _register_dll_directories(site_packages):
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    candidates = [site_packages]
    candidates.extend(site_packages.glob("*.libs"))
    candidates.extend(site_packages.glob("*/.libs"))
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        try:
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(candidate)))
        except OSError:
            pass


def activate_external_extensions(runtime_root=None):
    info = active_extension_info(runtime_root)
    if not info.get("available") or not info.get("compatible"):
        return info

    site_packages = str(info["site_packages"])
    site.addsitedir(site_packages)
    while site_packages in sys.path:
        sys.path.remove(site_packages)
    sys.path.insert(0, site_packages)
    _register_dll_directories(info["site_packages"])
    info["activated"] = True
    return info
