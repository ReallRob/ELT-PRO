"""Generate the project's PyInstaller specs from the dependency manifest."""

from __future__ import annotations

from pathlib import Path

from core.packaging.dependency_manifest import TARGETS, get_project_root


_SPEC_FILES = {
    "main": "main.spec",
    "crpa_launcher": "crpa_launcher.spec",
    "crpa_json": "crpa_json_py37_onefile.spec",
}


def generate_spec_files(targets=None, project_root=None):
    root = Path(project_root or get_project_root())
    selected = [target for target in targets or TARGETS if target in _SPEC_FILES]
    generated = []
    for target in dict.fromkeys(selected):
        path = root / _SPEC_FILES[target]
        # Path.write_text(newline=...) is unavailable on Python 3.7.
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(_render_spec(target))
        generated.append(path)
    return generated


def _render_spec(target):
    entry_script, app_name, onedir = _target_settings(target)
    common = """# -*- mode: python ; coding: utf-8 -*-
\"\"\"Generated PyInstaller spec. Dynamic code-block imports come from config/dynamic_imports.json.\"\"\"

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

PROJECT_ROOT = Path(SPECPATH).resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.packaging.dependency_manifest import bundled_import_roots, runtime_stdlib_hidden_imports


block_cipher = None
stdlib_hiddenimports = set(runtime_stdlib_hidden_imports())
collect_roots = set(bundled_import_roots(\"{target}\", PROJECT_ROOT))
datas = []
binaries = []
hiddenimports = list(stdlib_hiddenimports)


def _dedupe_toc(items):
    seen = set()
    result = []
    for item in items or []:
        key = item[0] if isinstance(item, tuple) and item else item
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


for root in sorted(collect_roots):
    try:
        root_datas, root_binaries, root_hiddenimports = collect_all(root)
    except Exception:
        hiddenimports.append(root)
        continue
    datas.extend(root_datas)
    binaries.extend(root_binaries)
    hiddenimports.extend(root_hiddenimports)

hiddenimports = sorted({{item for item in hiddenimports if item}})
datas = _dedupe_toc(datas)
binaries = _dedupe_toc(binaries)


a = Analysis(
    [\"{entry_script}\"],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
""".format(target=target, entry_script=entry_script)
    if onedir:
        return common + """exe = EXE(
    pyz,
    a.scripts,
    [],
    name=\"{app_name}\",
    exclude_binaries=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=\"{app_name}\",
)
""".format(app_name=app_name)
    return common + """exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=\"{app_name}\",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
""".format(app_name=app_name)


def _target_settings(target):
    if target == "main":
        return "main.py", "RPA_json设计器", True
    if target == "crpa_launcher":
        return "crpa_launcher/main.py", "RPA_json运行器", True
    return "crpa_launcher/main.py", "RPA_json运行器", False
