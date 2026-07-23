"""Build, archive and install versioned external code-block extensions."""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import time
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath, PureWindowsPath

from core.packaging.dependency_manifest import is_standard_library_module
from core.runtime_extensions import (
    IMPORTS_DIRECTORY,
    MANIFEST_FILENAME,
    SITE_PACKAGES_DIRECTORY,
    VERSIONS_DIRECTORY,
    active_extension_info,
    get_extensions_root,
    imported_extension_info,
    runtime_identity,
    set_active_extension,
)


ARCHIVES_DIRECTORY = "archives"
_INVALID_ARCHIVE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_LOCAL_COPY_SCRIPT = r'''
import json
import os
import re
import shutil
import subprocess
import sys

def normalize(name):
    return re.sub(r"[-_.]+", "-", str(name or "")).lower()


def requirement_name(requirement):
    text = str(requirement or "").split(";", 1)[0].strip()
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9_.-]*", text)
    return match.group(0) if match else ""


def package_info(distribution):
    completed = subprocess.Popen(
        [sys.executable, "-m", "pip", "show", "--files", distribution],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    stdout, _stderr = completed.communicate()
    if completed.returncode != 0 or not stdout.strip():
        return None
    info = {"files": []}
    in_files = False
    for line in stdout.splitlines():
        if in_files and line.startswith("  "):
            info["files"].append(line.strip())
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key == "files":
            info["files"] = []
            in_files = True
        else:
            info[key] = value.strip()
            in_files = False
    return info


def _fallback_files(info, distribution):
    """Recover files for distro-managed packages without a pip RECORD list."""
    location = info.get("location")
    if not location or not os.path.isdir(location):
        return []

    files = []
    top_level = []
    try:
        import pkg_resources
        installed = pkg_resources.get_distribution(distribution)
        info["name"] = str(installed.project_name or info.get("name") or distribution)
        info["version"] = str(installed.version or info.get("version") or "")
        info["location"] = str(installed.location or location)
        for metadata_name in ("RECORD",):
            try:
                entries = installed.get_metadata_lines(metadata_name)
            except Exception:
                entries = []
            for entry in entries or ():
                value = str(entry or "").split(",", 1)[0].strip()
                if value and value not in files:
                    files.append(value)
            if files:
                break
        try:
            top_level = [
                str(item or "").strip()
                for item in installed.get_metadata_lines("top_level.txt") or ()
                if str(item or "").strip()
            ]
        except Exception:
            top_level = []
    except Exception:
        installed = None

    location = info.get("location") or location
    distribution_key = normalize(info.get("name") or distribution)
    try:
        entries = os.listdir(location)
    except OSError:
        entries = []

    if files:
        return files

    # Debian/Ubuntu packages often omit RECORD but keep their dist-info directory.
    for entry in entries:
        lower = str(entry).lower()
        suffix = next((item for item in (".dist-info", ".egg-info") if lower.endswith(item)), "")
        if suffix:
            metadata_key = normalize(lower[:-len(suffix)])
            if (
                metadata_key == distribution_key
                or metadata_key.startswith(distribution_key + "-")
            ) and entry not in files:
                files.append(entry)

    if not top_level:
        normalized = re.sub(r"[-.]+", "_", str(distribution or "").strip())
        top_level = [normalized, normalized.replace("_", "")]
    for root in top_level:
        root = os.path.normpath(str(root))
        if not root or os.path.isabs(root) or root == ".." or root.startswith(".." + os.sep):
            continue
        candidate = os.path.join(location, root)
        if os.path.isdir(candidate) or os.path.isfile(candidate):
            files.append(root)
    return files


def copy_distribution(info, target):
    files = info.get("files") or []
    if not files:
        files = _fallback_files(info, info.get("name") or "")
    if not files:
        raise RuntimeError("发行包 %s 缺少可复制的安装文件清单" % info.get("name", "unknown"))
    location = info.get("location")
    if not location:
        raise RuntimeError("发行包 %s 缺少 site-packages 位置" % info.get("name", "unknown"))
    copied = 0
    for entry in files:
        relative = os.path.normpath(str(entry))
        if os.path.isabs(relative) or relative == ".." or relative.startswith(".." + os.sep):
            continue
        source = os.path.join(location, relative)
        if os.path.isdir(source):
            for current_root, _directories, names in os.walk(source):
                for filename in names:
                    current_source = os.path.join(current_root, filename)
                    current_relative = os.path.relpath(current_source, location)
                    current_destination = os.path.join(target, current_relative)
                    current_parent = os.path.dirname(current_destination)
                    if not os.path.isdir(current_parent):
                        os.makedirs(current_parent)
                    shutil.copy2(current_source, current_destination)
                    copied += 1
            continue
        if not os.path.isfile(source):
            continue
        destination = os.path.join(target, relative)
        parent = os.path.dirname(destination)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        shutil.copy2(source, destination)
        copied += 1
    return copied


target = os.path.abspath(sys.argv[1])
requested = json.loads(sys.argv[2])
if not os.path.isdir(target):
    os.makedirs(target)

pending = [requirement_name(item) for item in requested]
pending = [item for item in pending if item]
copied = set()
missing = []
while pending:
    name = pending.pop(0)
    key = normalize(name)
    if not key or key in copied:
        continue
    info = package_info(name)
    if info is None:
        missing.append(name)
        continue
    copy_distribution(info, target)
    copied.add(key)
    for requirement in str(info.get("requires") or "").split(","):
        dependency = requirement_name(requirement)
        if dependency and normalize(dependency) not in copied:
            pending.append(dependency)

if missing:
    raise RuntimeError("当前 Python 环境未安装以下发行包：%s" % ", ".join(sorted(set(missing))))

print("已从本地 site-packages 复制发行包：%s" % ", ".join(sorted(copied)))
'''


class ExtensionBuildError(RuntimeError):
    pass


class ExtensionVersionConflict(ExtensionBuildError):
    """Raised when an imported package would replace an installed distribution."""

    def __init__(self, conflicts):
        self.conflicts = list(conflicts or [])
        details = ", ".join(
            "{} {} -> {}".format(item["name"], item["current_version"], item["incoming_version"])
            for item in self.conflicts
        )
        super().__init__("检测到扩展依赖版本差异：{}".format(details or "未知依赖"))


def _safe_version(value):
    version = str(value or "").strip()
    return version if version and Path(version).name == version else ""


def _safe_archive_name(value):
    """Return a single portable ZIP base name, without its optional extension."""

    name = str(value or "").strip()
    if name.casefold().endswith(".zip"):
        name = name[:-4].rstrip()
    if (
        not name
        or name in {".", ".."}
        or Path(name).name != name
        or _INVALID_ARCHIVE_NAME_RE.search(name)
    ):
        return ""
    return name.rstrip(". ")


def _default_archive_name(dependencies, fallback):
    roots = []
    seen = set()
    for dependency in dependencies or []:
        module = str(dependency.get("module") or "").strip()
        if not module:
            continue
        key = module.casefold()
        if key in seen:
            continue
        seen.add(key)
        roots.append(module)
    name = "_".join(roots)
    return _safe_archive_name(name[:120]) or _safe_archive_name(fallback) or "extension"


def _extension_version():
    return time.strftime("%Y%m%d-%H%M%S")


def _write_json(path, payload):
    with Path(path).open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _normalize_distribution_name(name):
    return re.sub(r"[-_.]+", "-", str(name or "").strip()).casefold()


def _distribution_inventory(site_packages):
    """Read distribution names and versions from copied wheel metadata."""

    inventory = {}
    if not site_packages:
        return inventory
    site_packages = Path(site_packages)
    if not site_packages.is_dir():
        return inventory
    for metadata_directory in sorted(site_packages.glob("*.dist-info")):
        metadata_path = metadata_directory / "METADATA"
        if not metadata_path.is_file():
            continue
        try:
            with metadata_path.open("r", encoding="utf-8", errors="replace") as handle:
                metadata = Parser().parsestr(handle.read())
        except OSError:
            continue
        name = str(metadata.get("Name") or "").strip()
        version = str(metadata.get("Version") or "").strip()
        key = _normalize_distribution_name(name)
        if not key or not version:
            continue
        previous = inventory.get(key)
        if previous and previous["version"] != version:
            raise ExtensionBuildError("扩展环境包含多个 {} 版本".format(name))
        inventory[key] = {
            "name": name,
            "version": version,
            "metadata_directory": metadata_directory.name,
        }
    return inventory


def _manifest_distributions(site_packages):
    inventory = _distribution_inventory(site_packages)
    return [
        {"name": item["name"], "version": item["version"]}
        for _key, item in sorted(inventory.items())
    ]


def _versioned_dependencies(dependencies, site_packages):
    inventory = _distribution_inventory(site_packages)
    versioned = []
    for dependency in dependencies or []:
        if not isinstance(dependency, dict):
            continue
        item = dict(dependency)
        distribution = str(item.get("distribution") or item.get("module") or "").strip()
        installed = inventory.get(_normalize_distribution_name(distribution))
        if installed:
            item["version"] = installed["version"]
        versioned.append(item)
    return versioned


def _safe_relative_path(value):
    path = PurePosixPath(str(value or "").replace("\\", "/"))
    if not path.parts or path.is_absolute() or ".." in path.parts:
        return None
    return Path(*path.parts)


def _remove_distribution(site_packages, distribution):
    """Remove one installed distribution using its wheel RECORD file."""

    site_packages = Path(site_packages)
    metadata_directory = site_packages / str(distribution["metadata_directory"])
    record_path = metadata_directory / "RECORD"
    if not record_path.is_file():
        raise ExtensionBuildError(
            "无法安全更新 {} {}：缺少 {}".format(
                distribution["name"], distribution["version"], record_path.name
            )
        )
    paths = []
    try:
        with record_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.reader(handle):
                relative = _safe_relative_path(row[0] if row else "")
                if relative is not None:
                    paths.append(relative)
    except OSError as exc:
        raise ExtensionBuildError(
            "无法读取 {} 的文件清单：{}".format(distribution["name"], exc)
        )

    for relative in paths:
        target = site_packages / relative
        try:
            if target.is_file() or target.is_symlink():
                target.unlink()
        except OSError as exc:
            raise ExtensionBuildError(
                "无法移除旧版 {} 文件 {}：{}".format(distribution["name"], relative, exc)
            )
    if metadata_directory.is_dir():
        shutil.rmtree(str(metadata_directory))

    for relative in paths:
        parent = (site_packages / relative).parent
        while parent != site_packages:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _copy_site_packages(source, destination):
    destination = Path(destination)
    if source and Path(source).is_dir():
        source = Path(source)
        shutil.copytree(str(source), str(destination))
    else:
        destination.mkdir(parents=True, exist_ok=False)


def _copy_tree_contents(source, destination):
    source = Path(source)
    destination = Path(destination)
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(path), str(target))


def _merge_dependencies(existing, incoming):
    merged = {}
    order = []
    for dependency in list(existing or []) + list(incoming or []):
        if not isinstance(dependency, dict):
            continue
        copied = dict(dependency)
        key = _normalize_distribution_name(copied.get("module") or copied.get("distribution"))
        if not key:
            continue
        if key not in merged:
            order.append(key)
        merged[key] = copied
    return [merged[key] for key in order]


def _version_conflicts(current, incoming):
    conflicts = []
    for key, incoming_distribution in incoming.items():
        current_distribution = current.get(key)
        if current_distribution and current_distribution["version"] != incoming_distribution["version"]:
            conflicts.append(
                {
                    "name": incoming_distribution["name"],
                    "current_version": current_distribution["version"],
                    "incoming_version": incoming_distribution["version"],
                }
            )
    return sorted(conflicts, key=lambda item: item["name"].casefold())


def _temporary_root(extension_root, prefix):
    extension_root = Path(extension_root)
    base = extension_root / (prefix + _extension_version())
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = extension_root / (base.name + "-{}".format(suffix))
        suffix += 1
    return candidate


def _promote_directory(source, destination, operation, attempts=12, retry_delay=0.25):
    """Promote a completed staging directory, tolerating short Windows file locks."""

    source = Path(source)
    destination = Path(destination)
    if not source.is_dir():
        raise ExtensionBuildError("{}失败：暂存目录不存在：{}".format(operation, source))
    if destination.exists():
        raise ExtensionBuildError("{}失败：目标目录已存在：{}".format(operation, destination))

    last_error = None
    for attempt in range(max(1, int(attempts))):
        try:
            source.replace(destination)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt + 1 < max(1, int(attempts)):
                time.sleep(retry_delay)
    raise ExtensionBuildError(
        "{}失败：Windows 暂时占用了暂存目录，已重试 {} 次。"
        "暂存内容已保留：{}。原始错误：{}".format(operation, attempts, source, last_error)
    )


def _unique_import_id(extension_root, preferred=None):
    extension_root = Path(extension_root)
    base = _safe_version(preferred) or _extension_version()
    candidate = base
    suffix = 1
    imports_root = extension_root / IMPORTS_DIRECTORY
    while (imports_root / candidate).exists():
        candidate = "{}-{}".format(base, suffix)
        suffix += 1
    return candidate


def probe_python_runtime(python_command):
    script = (
        "import json, platform, sys; "
        "print(json.dumps({'python': '.'.join(str(v) for v in sys.version_info[:2]), "
        "'architecture': platform.architecture()[0], "
        "'implementation': platform.python_implementation()}))"
    )
    try:
        completed = subprocess.run(
            [str(python_command), "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            universal_newlines=True,
        )
    except OSError as exc:
        raise ExtensionBuildError("无法启动 Python 命令：{}".format(exc))
    if completed.returncode != 0:
        raise ExtensionBuildError(
            "无法读取 Python 运行时信息：{}".format(completed.stderr.strip() or completed.stdout.strip())
        )
    try:
        identity = json.loads(completed.stdout.strip())
    except ValueError as exc:
        raise ExtensionBuildError("Python 运行时信息格式无效：{}".format(exc))
    if not isinstance(identity, dict) or not identity.get("python"):
        raise ExtensionBuildError("Python 运行时信息不完整")
    return identity


def external_requirements(dependencies):
    requirements = []
    seen = set()
    for dependency in dependencies or []:
        distribution = str(dependency.get("distribution") or dependency.get("module") or "").strip()
        if not distribution:
            continue
        key = distribution.casefold()
        if key in seen:
            continue
        seen.add(key)
        requirements.append(distribution)
    return requirements


def prepare_extension_build(python_command, dependencies, runtime_root=None, version=None, archive_name=None):
    standard_modules = sorted({
        str(item.get("module") or "").strip()
        for item in dependencies or []
        if isinstance(item, dict) and is_standard_library_module(item.get("module"))
    })
    if standard_modules:
        raise ExtensionBuildError(
            "标准库不能生成外置扩展：{}。请在打包依赖中改选“内置到程序”。".format(
                ", ".join(standard_modules)
            )
        )
    requirements = external_requirements(dependencies)
    if not requirements:
        raise ExtensionBuildError("没有可构建的外置扩展依赖")
    extension_root = get_extensions_root(runtime_root)
    version = _safe_version(version) or _extension_version()
    if archive_name is None:
        archive_name = _default_archive_name(dependencies, version)
    else:
        archive_name = _safe_archive_name(archive_name)
        if not archive_name:
            raise ExtensionBuildError("扩展 ZIP 文件名无效，请勿使用路径或 \\ / : * ? \" < > | 等字符")
    version_root = extension_root / VERSIONS_DIRECTORY / version
    staging_root = extension_root / (".staging-" + version)
    if version_root.exists() or staging_root.exists():
        raise ExtensionBuildError("扩展版本已存在：{}".format(version))
    runtime = probe_python_runtime(python_command)
    staging_site_packages = staging_root / SITE_PACKAGES_DIRECTORY
    staging_site_packages.mkdir(parents=True, exist_ok=False)
    return {
        "version": version,
        "archive_name": archive_name,
        "runtime_root": str(Path(runtime_root)) if runtime_root else "",
        "extension_root": extension_root,
        "staging_root": staging_root,
        "staging_site_packages": staging_site_packages,
        "version_root": version_root,
        "runtime": runtime,
        "dependencies": [dict(item) for item in dependencies or []],
        "requirements": requirements,
    }


def copy_installed_arguments(context):
    return [
        "-c",
        _LOCAL_COPY_SCRIPT,
        str(context["staging_site_packages"]),
        json.dumps(context["requirements"], ensure_ascii=False),
    ]


def discard_extension_build(context):
    staging_value = (context or {}).get("staging_root")
    if not staging_value:
        return
    staging_root = Path(staging_value)
    if staging_root.name.startswith(".staging-") and staging_root.is_dir():
        shutil.rmtree(str(staging_root), ignore_errors=True)


def _create_archive(package_root, extension_root, archive_name=None):
    archive_dir = Path(extension_root) / ARCHIVES_DIRECTORY
    archive_dir.mkdir(parents=True, exist_ok=True)
    package_root = Path(package_root)
    archive_path = archive_dir / (str(archive_name or package_root.name) + ".zip")
    with zipfile.ZipFile(str(archive_path), "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(str(path), path.relative_to(package_root).as_posix())
    return archive_path


def finalize_extension_build(context, activate=True):
    context = dict(context or {})
    staging_root = Path(context["staging_root"])
    extension_root = Path(context["extension_root"])
    site_packages = Path(context["staging_site_packages"])
    if not site_packages.is_dir():
        raise ExtensionBuildError("扩展安装目录不存在")
    requested_dependencies = _versioned_dependencies(context["dependencies"], site_packages)
    manifest = {
        "schema_version": 2,
        "version": context["version"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "runtime": context["runtime"],
        "requested_dependencies": requested_dependencies,
        "root_modules": [str(item.get("module") or "") for item in requested_dependencies],
        "distributions": _manifest_distributions(site_packages),
    }
    _write_json(staging_root / MANIFEST_FILENAME, manifest)
    archive_name = _safe_archive_name(context.get("archive_name"))
    if not archive_name:
        archive_name = _default_archive_name(context.get("dependencies"), context["version"])
    archive_path = _create_archive(staging_root, extension_root, archive_name)
    discard_extension_build(context)
    return {
        "version": context["version"],
        "archive_path": archive_path,
        "activated": False,
    }


def _archive_member_path(name):
    path = PurePosixPath(str(name).replace("\\", "/"))
    windows_path = PureWindowsPath(name)
    if path.is_absolute() or windows_path.is_absolute() or ".." in path.parts:
        raise ExtensionBuildError("扩展压缩包包含不安全路径：{}".format(name))
    return path


def import_extension_archive(archive_path, runtime_root=None):
    """Import a ZIP and automatically merge it into the current extension environment."""

    extension_root = get_extensions_root(runtime_root)
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise ExtensionBuildError("扩展压缩包不存在：{}".format(archive_path))
    temporary_root = _temporary_root(extension_root, ".import-")
    try:
        with zipfile.ZipFile(str(archive_path), "r") as archive:
            names = archive.namelist()
            for name in names:
                _archive_member_path(name)
            if MANIFEST_FILENAME not in names:
                raise ExtensionBuildError("扩展压缩包缺少 manifest.json")
            archive.extractall(str(temporary_root))
        manifest_path = temporary_root / MANIFEST_FILENAME
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        if not isinstance(manifest, dict):
            raise ExtensionBuildError("扩展压缩包 manifest.json 格式无效")
        version = _safe_version(manifest.get("version") if isinstance(manifest, dict) else "")
        if not version:
            raise ExtensionBuildError("扩展压缩包版本无效")
        if not (temporary_root / SITE_PACKAGES_DIRECTORY).is_dir():
            raise ExtensionBuildError("扩展压缩包缺少 site-packages")
        import_id = _unique_import_id(extension_root, version)
        import_root = extension_root / IMPORTS_DIRECTORY / import_id
        import_root.parent.mkdir(parents=True, exist_ok=True)
        _promote_directory(temporary_root, import_root, "导入扩展包")
        temporary_root = None
        info = imported_extension_info(import_id, runtime_root)
        if not info.get("compatible"):
            shutil.rmtree(str(import_root), ignore_errors=True)
            raise ExtensionBuildError(info.get("message") or "导入扩展包与当前运行时不兼容")
        try:
            result = merge_imported_extension(import_id, runtime_root, allow_version_updates=True)
        except ExtensionBuildError:
            shutil.rmtree(str(import_root), ignore_errors=True)
            raise
        result.update(
            {
                "source_version": version,
                "auto_merged": True,
                "manifest": info.get("manifest"),
            }
        )
        return result
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ExtensionBuildError("导入扩展压缩包失败：{}".format(exc))
    finally:
        if temporary_root is not None and temporary_root.exists():
            shutil.rmtree(str(temporary_root), ignore_errors=True)


def merge_imported_extension(import_id, runtime_root=None, allow_version_updates=False):
    """Merge one imported extension into the single currently loaded environment."""

    extension_root = get_extensions_root(runtime_root)
    imported = imported_extension_info(import_id, runtime_root)
    if not imported.get("available"):
        raise ExtensionBuildError(imported.get("message") or "导入扩展包不可用")
    if not imported.get("compatible"):
        raise ExtensionBuildError(imported.get("message") or "导入扩展包与当前运行时不兼容")

    manifest = imported["manifest"]
    incoming_site_packages = imported["site_packages"]
    source_version = imported.get("source_version") or imported.get("import_id")
    active = active_extension_info(runtime_root)
    active_site_packages = active.get("site_packages") if active.get("available") else None
    active_manifest = active.get("manifest") if isinstance(active.get("manifest"), dict) else {}
    current_distributions = _distribution_inventory(active_site_packages)
    incoming_distributions = _distribution_inventory(incoming_site_packages)
    conflicts = _version_conflicts(current_distributions, incoming_distributions)
    if conflicts and not allow_version_updates:
        raise ExtensionVersionConflict(conflicts)

    added_distributions = [
        item["name"]
        for key, item in sorted(incoming_distributions.items())
        if key not in current_distributions
    ]
    merged_dependencies = _merge_dependencies(
        active_manifest.get("requested_dependencies") if active_manifest else [],
        manifest.get("requested_dependencies") if isinstance(manifest, dict) else [],
    )

    if active_site_packages:
        try:
            version_root = active["version_dir"]
            for conflict in conflicts:
                key = _normalize_distribution_name(conflict["name"])
                _remove_distribution(active_site_packages, current_distributions[key])
            _copy_tree_contents(incoming_site_packages, active_site_packages)
            merged_manifest = {
                "schema_version": 2,
                "version": active["version"],
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "runtime": active_manifest.get("runtime") or manifest.get("runtime") or runtime_identity(),
                "requested_dependencies": merged_dependencies,
                "root_modules": [str(item.get("module") or "") for item in merged_dependencies],
                "distributions": _manifest_distributions(active_site_packages),
                "merged_from": [
                    item
                    for item in (active.get("version"), source_version)
                    if item
                ],
                "merged_import_id": imported.get("import_id") or "",
            }
            _write_json(version_root / MANIFEST_FILENAME, merged_manifest)
            try:
                shutil.rmtree(str(imported["import_dir"]))
            except OSError:
                pass
            return {
                "version": active["version"],
                "version_root": version_root,
                "merged_in_place": True,
                "created_initial_environment": False,
                "added_distributions": added_distributions,
                "updated_distributions": conflicts,
            }
        except (OSError, ValueError) as exc:
            raise ExtensionBuildError("合并导入扩展包失败：{}".format(exc))

    merge_root = _temporary_root(extension_root, ".merge-")
    try:
        merged_site_packages = merge_root / SITE_PACKAGES_DIRECTORY
        _copy_site_packages(incoming_site_packages, merged_site_packages)
        initial_version = "current"
        initial_manifest = {
            "schema_version": 2,
            "version": initial_version,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "runtime": manifest.get("runtime") or runtime_identity(),
            "requested_dependencies": merged_dependencies,
            "root_modules": [str(item.get("module") or "") for item in merged_dependencies],
            "distributions": _manifest_distributions(merged_site_packages),
            "merged_import_id": imported.get("import_id") or "",
        }
        _write_json(merge_root / MANIFEST_FILENAME, initial_manifest)

        version_root = extension_root / VERSIONS_DIRECTORY / initial_version
        if version_root.exists():
            raise ExtensionBuildError("当前扩展环境目录已存在但未启用：{}".format(version_root))
        version_root.parent.mkdir(parents=True, exist_ok=True)
        _promote_directory(merge_root, version_root, "创建初始加载环境")
        merge_root = None
        set_active_extension(initial_version, runtime_root)
        try:
            shutil.rmtree(str(imported["import_dir"]))
        except OSError:
            pass
        return {
            "version": initial_version,
            "version_root": version_root,
            "merged_in_place": False,
            "created_initial_environment": True,
            "added_distributions": added_distributions,
            "updated_distributions": conflicts,
        }
    except (OSError, ValueError) as exc:
        raise ExtensionBuildError("合并导入扩展包失败：{}".format(exc))
    finally:
        if merge_root is not None and merge_root.exists():
            shutil.rmtree(str(merge_root), ignore_errors=True)
