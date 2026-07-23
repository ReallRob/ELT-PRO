"""Development page for reviewing code-block packaging dependencies."""

from __future__ import annotations

import copy
import json
import os
import re
import traceback

from PyQt5.QtCore import QProcess, QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.packaging.dependency_manifest import (
    get_manifest_path,
    is_baseline_dependency,
    is_standard_library_module,
    load_dependencies,
    requires_collect_all,
    save_dependencies,
)
from core.packaging.external_extensions import (
    ExtensionBuildError,
    copy_installed_arguments,
    discard_extension_build,
    finalize_extension_build,
    import_extension_archive,
    prepare_extension_build,
)
from core.packaging.spec_generator import generate_spec_files
from core.runtime_extensions import (
    active_extension_info,
    get_runtime_root,
)


_MODULE_ROOT_RE = re.compile(r"^[A-Za-z_]\w*$")
_INVALID_ARCHIVE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TARGETS = (
    ("main", "RPA_json设计器"),
    ("crpa_launcher", "RPA_json运行器"),
    ("crpa_json", "RPA_json运行器（单文件）"),
)

_TARGET_DESCRIPTIONS = {
    "main": "设计和编辑 RPA_json 工作流",
    "crpa_launcher": "运行目录版 RPA_json 工作流",
    "crpa_json": "运行单文件 RPA_json 工作流",
}

_PYTHON_ENVIRONMENT_DISCOVERY_SCRIPT = r'''
import json
import platform
import re
import subprocess
import sys


def default_import_root(distribution):
    candidate = re.sub(r"[-.]+", "_", str(distribution or "").strip())
    return candidate if re.match(r"^[A-Za-z_]\w*$", candidate) else ""


def normalize(name):
    return re.sub(r"[-_.]+", "-", str(name or "").strip()).lower()


packages = {}
try:
    import pkg_resources
except ImportError:
    pkg_resources = None

if pkg_resources is not None:
    for distribution in pkg_resources.working_set:
        name = str(distribution.project_name or "").strip()
        if not name:
            continue
        modules = []
        try:
            if distribution.has_metadata("top_level.txt"):
                modules = [
                    item.strip()
                    for item in distribution.get_metadata("top_level.txt").splitlines()
                    if re.match(r"^[A-Za-z_]\w*$", item.strip())
                ]
        except Exception:
            modules = []
        if not modules:
            module = default_import_root(name)
            modules = [module] if module else []
        packages[normalize(name)] = {
            "name": name,
            "version": str(distribution.version or ""),
            "modules": modules,
        }

if not packages:
    process = subprocess.Popen(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.strip() or stdout.strip() or "无法执行 pip list")
    for item in json.loads(stdout):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        module = default_import_root(name)
        packages[normalize(name)] = {
            "name": name,
            "version": str(item.get("version") or ""),
            "modules": [module] if module else [],
        }

print(json.dumps({
    "python": sys.version.split()[0],
    "executable": sys.executable,
    "architecture": platform.architecture()[0],
    "packages": sorted(packages.values(), key=lambda item: item["name"].lower()),
}))
'''


def _default_import_root(distribution):
    candidate = re.sub(r"[-.]+", "_", str(distribution or "").strip())
    return candidate if _MODULE_ROOT_RE.match(candidate) else ""


def _default_python_command():
    return "python" if os.name == "nt" else "python3"


class ExtensionArchiveImportThread(QThread):
    """Merge an extension ZIP without blocking the package-manager page."""

    def __init__(self, archive_path, runtime_root, parent=None):
        super().__init__(parent)
        self.archive_path = str(archive_path)
        self.runtime_root = runtime_root
        self.result = None
        self.error = ""
        self.error_trace = ""

    def run(self):
        try:
            self.result = import_extension_archive(self.archive_path, self.runtime_root)
        except ExtensionBuildError as exc:
            self.error = str(exc)
            self.error_trace = traceback.format_exc()
        except Exception as exc:
            self.error = "导入扩展包时发生未预期错误：{}".format(exc)
            self.error_trace = traceback.format_exc()


class AddDependencyDialog(QDialog):
    """Collect one dependency draft without writing the final manifest yet."""

    def __init__(self, targets, available_packages=None, parent=None, extension_manifest=False):
        super().__init__(parent)
        self.setWindowTitle("新增打包依赖")
        self.setMinimumSize(760, 440)
        self._available_packages = self._normalize_available_packages(available_packages)
        self._extension_manifest = bool(extension_manifest)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        content = QHBoxLayout()
        content.setSpacing(12)

        library_panel = QFrame()
        library_panel.setObjectName("library_panel")
        library_panel.setStyleSheet(
            "QFrame#library_panel { background: #F8FAFC; border: 1px solid #D9E1EA; border-radius: 6px; }"
            "QListWidget { background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 4px; }"
            "QListWidget::item { padding: 7px 8px; }"
            "QListWidget::item:selected { background: #DDEEF8; color: #102A43; }"
        )
        library_layout = QVBoxLayout(library_panel)
        library_layout.setContentsMargins(10, 10, 10, 10)
        library_layout.setSpacing(8)
        library_title = QLabel("当前 Python 环境")
        library_title.setStyleSheet("font-weight: 600; color: #334155;")
        self.package_search = QLineEdit()
        self.package_search.setPlaceholderText("搜索已安装库")
        self.package_search.textChanged.connect(self._refresh_package_list)
        self.package_list = QListWidget()
        self.package_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.package_list.currentItemChanged.connect(self._select_available_package)
        library_layout.addWidget(library_title)
        library_layout.addWidget(self.package_search)
        library_layout.addWidget(self.package_list, 1)
        content.addWidget(library_panel, 2)

        details_panel = QWidget()
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(10)
        details_title = QLabel("依赖配置")
        details_title.setStyleSheet("font-weight: 600; color: #334155;")
        details_layout.addWidget(details_title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.module_input = QLineEdit()
        self.module_input.setPlaceholderText("例如 selenium")
        self.distribution_input = QLineEdit()
        self.distribution_input.setPlaceholderText("默认与根模块相同")
        self.collect_combo = QComboBox()
        self.collect_combo.addItem("collect_all", "all")
        self.delivery_combo = QComboBox()
        self.delivery_combo.addItem("内置到程序", "bundled")
        self.delivery_combo.addItem("外置扩展（代码块热更新）", "external")
        if self._extension_manifest:
            self.delivery_combo.setCurrentIndex(self.delivery_combo.findData("external"))
            self.delivery_combo.setEnabled(False)

        form.addRow("根模块", self.module_input)
        form.addRow("发行包", self.distribution_input)
        form.addRow("收集方式", self.collect_combo)
        form.addRow("交付方式", self.delivery_combo)
        details_layout.addLayout(form)
        if self._extension_manifest:
            extension_hint = QLabel("扩展清单中的库会作为外置扩展打入 ZIP，不写入程序内置清单。")
            extension_hint.setWordWrap(True)
            extension_hint.setStyleSheet("color: #6D28D9; background: #F5F3FF; padding: 6px 8px;")
            details_layout.addWidget(extension_hint)

        target_frame = QFrame()
        target_frame.setObjectName("target_frame")
        target_frame.setStyleSheet(
            "QFrame#target_frame { background: #F8FAFC; border: 1px solid #E2E8F0; "
            "border-radius: 5px; }"
        )
        target_layout = QVBoxLayout(target_frame)
        target_layout.setContentsMargins(12, 10, 12, 10)
        target_layout.setSpacing(7)
        target_layout.addWidget(QLabel("包含在以下构建目标中"))
        self.target_checks = {}
        selected = set(targets or [])
        for key, label in _TARGETS:
            check = QCheckBox(label)
            check.setChecked(key in selected)
            self.target_checks[key] = check
            target_layout.addWidget(check)
        details_layout.addWidget(target_frame)
        details_layout.addStretch(1)
        content.addWidget(details_panel, 3)
        layout.addLayout(content, 1)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #B91C1C;")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("添加")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_package_list()

    @staticmethod
    def _normalize_available_packages(packages):
        normalized = {
            "tkinter": {
                "name": "tkinter",
                "version": "Python 标准库",
                "module": "tkinter",
                "standard_library": True,
            }
        }
        for package in packages or []:
            if not isinstance(package, dict):
                continue
            name = str(package.get("name") or "").strip()
            if not name:
                continue
            key = name.casefold()
            normalized[key] = {
                "name": name,
                "version": str(package.get("version") or "").strip(),
                "module": str(package.get("module") or _default_import_root(name)).strip(),
                "standard_library": bool(package.get("standard_library")),
            }
        return sorted(normalized.values(), key=lambda item: item["name"].casefold())

    def _refresh_package_list(self):
        query = self.package_search.text().strip().casefold() if hasattr(self, "package_search") else ""
        self.package_list.blockSignals(True)
        self.package_list.clear()
        for package in self._available_packages:
            searchable = "{} {} {}".format(
                package["name"], package["version"], package["module"]
            ).casefold()
            if query and query not in searchable:
                continue
            suffix = " · 标准库" if package["standard_library"] else ""
            label = package["name"]
            if package["version"]:
                label += "  " + package["version"]
            item = QListWidgetItem(label + suffix)
            item.setData(Qt.UserRole, package)
            self.package_list.addItem(item)
        self.package_list.blockSignals(False)

    def _select_available_package(self, item, _previous):
        package = item.data(Qt.UserRole) if item is not None else None
        if not isinstance(package, dict):
            return
        self.distribution_input.setText(str(package.get("name") or ""))
        self.module_input.setText(str(package.get("module") or ""))
        if package.get("standard_library"):
            if self._extension_manifest:
                self._show_error("标准库不能加入扩展清单；请返回内置清单后添加。")
                return
            index = self.delivery_combo.findData("bundled")
            if index >= 0:
                self.delivery_combo.setCurrentIndex(index)
        self.error_label.hide()

    def dependency(self):
        module = self.module_input.text().strip()
        return {
            "module": module,
            "distribution": self.distribution_input.text().strip() or module,
            "collect": self.collect_combo.currentData() or "all",
            "delivery": "external" if self._extension_manifest else self.delivery_combo.currentData() or "bundled",
            "targets": [key for key, check in self.target_checks.items() if check.isChecked()],
            "source": "stdlib" if is_standard_library_module(module) else "manual",
        }

    def _validate_and_accept(self):
        dependency = self.dependency()
        if not _MODULE_ROOT_RE.match(dependency["module"]):
            self._show_error("根模块必须是有效的 Python 标识符，例如 selenium。")
            return
        if dependency["delivery"] == "external" and is_standard_library_module(dependency["module"]):
            self._show_error(
                "{} 是 Python 标准库，不能生成外置扩展；请改选“内置到程序”。".format(
                    dependency["module"]
                )
            )
            return
        if not dependency["targets"]:
            self._show_error("请至少选择一个构建目标。")
            return
        self.accept()

    def _show_error(self, message):
        self.error_label.setText(message)
        self.error_label.show()


class ExtensionManifestDialog(QDialog):
    """Create one temporary third-party extension manifest without touching the base manifest."""

    def __init__(self, available_packages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("生成外置扩展包")
        self.setMinimumSize(820, 520)
        self.dependencies = []
        self._available_packages = list(available_packages or [])
        self._archive_name_customized = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("选择要导出到扩展 ZIP 的第三方库")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #1E293B;")
        hint = QLabel("扩展包仅用于代码块运行，不会修改程序基础依赖或 Spec。")
        hint.setStyleSheet("color: #64748B;")
        layout.addWidget(title)
        layout.addWidget(hint)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)

        available_panel = QFrame()
        available_panel.setObjectName("extensionManifestAvailable")
        available_layout = QVBoxLayout(available_panel)
        available_layout.setContentsMargins(10, 10, 10, 10)
        available_layout.setSpacing(8)
        available_layout.addWidget(QLabel("本机 Python 环境"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索包名")
        self.search_input.textChanged.connect(self._refresh_available_packages)
        self.available_list = QListWidget()
        self.available_list.itemDoubleClicked.connect(lambda _item: self._add_selected_package())
        add_selected = QPushButton("加入扩展清单")
        add_selected.clicked.connect(self._add_selected_package)
        available_layout.addWidget(self.search_input)
        available_layout.addWidget(self.available_list, 1)
        available_layout.addWidget(add_selected)

        selected_panel = QFrame()
        selected_panel.setObjectName("extensionManifestSelected")
        selected_layout = QVBoxLayout(selected_panel)
        selected_layout.setContentsMargins(10, 10, 10, 10)
        selected_layout.setSpacing(8)
        selected_layout.addWidget(QLabel("本次扩展包"))
        self.selected_table = QTableWidget(0, 2)
        self.selected_table.setHorizontalHeaderLabels(["根模块", "发行包"])
        self.selected_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.selected_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.selected_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.selected_table.horizontalHeader().setStretchLastSection(True)
        self.selected_table.verticalHeader().setVisible(False)
        remove_selected = QToolButton()
        remove_selected.setText("移除所选")
        remove_selected.setToolTip("从本次扩展清单移除所选库")
        remove_selected.clicked.connect(self._remove_selected_package)
        manual_add = QPushButton("手动配置")
        manual_add.clicked.connect(self._add_manually)
        selected_actions = QHBoxLayout()
        selected_actions.addWidget(manual_add)
        selected_actions.addStretch(1)
        selected_actions.addWidget(remove_selected)
        selected_layout.addWidget(self.selected_table, 1)
        selected_layout.addLayout(selected_actions)

        body.addWidget(available_panel)
        body.addWidget(selected_panel)
        body.setSizes([380, 380])
        layout.addWidget(body, 1)

        archive_name_row = QHBoxLayout()
        archive_name_label = QLabel("ZIP 文件名")
        archive_name_label.setStyleSheet("font-weight: 600; color: #334155;")
        self.archive_name_input = QLineEdit("extension")
        self.archive_name_input.setPlaceholderText("默认使用本次选择的根模块名")
        self.archive_name_input.setToolTip("默认格式：requests_selenium.zip；可直接输入自定义名称")
        self.archive_name_input.textEdited.connect(self._mark_archive_name_customized)
        archive_name_suffix = QLabel(".zip")
        archive_name_suffix.setStyleSheet("color: #64748B;")
        self.archive_name_error = QLabel("")
        self.archive_name_error.setStyleSheet("color: #B91C1C; font-size: 12px;")
        self.archive_name_error.hide()
        archive_name_row.addWidget(archive_name_label)
        archive_name_row.addWidget(self.archive_name_input, 1)
        archive_name_row.addWidget(archive_name_suffix)
        layout.addLayout(archive_name_row)
        layout.addWidget(self.archive_name_error)

        actions = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.build_button = QPushButton("生成扩展包")
        self.build_button.setEnabled(False)
        self.build_button.setStyleSheet(
            "QPushButton { background: #7C3AED; border-color: #7C3AED; color: #FFFFFF; font-weight: 600; }"
            "QPushButton:hover { background: #6D28D9; border-color: #6D28D9; }"
        )
        self.build_button.clicked.connect(self._accept_manifest)
        actions.addButton(self.build_button, QDialogButtonBox.AcceptRole)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

        self._refresh_available_packages()

    def _refresh_available_packages(self):
        query = self.search_input.text().strip().casefold()
        self.available_list.clear()
        for package in self._available_packages:
            name = str(package.get("name") or "").strip()
            module = str(package.get("module") or _default_import_root(name)).strip()
            if not name or not module or is_standard_library_module(module):
                continue
            searchable = "{} {}".format(name, module).casefold()
            if query and query not in searchable:
                continue
            item = QListWidgetItem("{}  {}".format(name, package.get("version") or ""))
            item.setData(Qt.UserRole, {"name": name, "module": module})
            self.available_list.addItem(item)

    def _add_selected_package(self):
        item = self.available_list.currentItem()
        package = item.data(Qt.UserRole) if item is not None else None
        if not isinstance(package, dict):
            return
        self._add_dependency(
            {
                "module": package["module"],
                "distribution": package["name"],
                "collect": "all",
                "delivery": "external",
                "targets": [key for key, _label in _TARGETS],
                "source": "manual",
            }
        )

    def _add_manually(self):
        dialog = AddDependencyDialog(
            [key for key, _label in _TARGETS],
            available_packages=self._available_packages,
            parent=self,
            extension_manifest=True,
        )
        if dialog.exec_() == QDialog.Accepted:
            self._add_dependency(dialog.dependency())

    def _add_dependency(self, dependency):
        if any(item["module"].casefold() == dependency["module"].casefold() for item in self.dependencies):
            return
        self.dependencies.append(dict(dependency))
        self._refresh_selected_dependencies()

    def _mark_archive_name_customized(self, _text):
        self._archive_name_customized = True

    def archive_name(self):
        return self.archive_name_input.text().strip()

    def _suggested_archive_name(self):
        modules = [str(item.get("module") or "").strip() for item in self.dependencies]
        modules = [module for module in modules if module]
        return "_".join(modules)[:120] or "extension"

    def _remove_selected_package(self):
        selected = self.selected_table.selectedItems()
        if not selected:
            return
        module = selected[0].data(Qt.UserRole)
        self.dependencies = [item for item in self.dependencies if item["module"] != module]
        self._refresh_selected_dependencies()

    def _refresh_selected_dependencies(self):
        self.selected_table.setRowCount(len(self.dependencies))
        for row, dependency in enumerate(self.dependencies):
            module = dependency["module"]
            module_item = QTableWidgetItem(module)
            module_item.setData(Qt.UserRole, module)
            self.selected_table.setItem(row, 0, module_item)
            self.selected_table.setItem(row, 1, QTableWidgetItem(dependency["distribution"]))
        if not self._archive_name_customized:
            self.archive_name_input.setText(self._suggested_archive_name())
        self.build_button.setEnabled(bool(self.dependencies))

    def _accept_manifest(self):
        if not self.dependencies:
            return
        archive_name = self.archive_name()
        base_name = archive_name[:-4].rstrip() if archive_name.casefold().endswith(".zip") else archive_name
        if (
            not base_name
            or base_name in {".", ".."}
            or _INVALID_ARCHIVE_NAME_RE.search(base_name)
        ):
            self.archive_name_error.setText("ZIP 文件名无效，请勿使用路径或 \\ / : * ? \" < > | 等字符。")
            self.archive_name_error.show()
            return
        self.archive_name_error.hide()
        self.accept()


class PackageManagerPage(QWidget):
    """Read-only environment inspection plus an in-memory dependency draft."""

    dependencies_changed = pyqtSignal(object)

    def __init__(self, parent=None, project_root=None):
        super().__init__(parent)
        self._project_root = project_root
        self._dependencies = load_dependencies(project_root)
        self._environment_packages = []
        self._environment_runtime = {}
        self._environment_scan_command = ""
        self._environment_scan_error = ""
        self._target_checks = {}
        self._draft_dirty = False
        self._pending_builds = []
        self._active_target = ""
        self._stop_requested = False
        self._extension_build_context = None
        self._extension_import_thread = None
        self._extension_stop_requested = False
        self._process = QProcess(self)
        self._process.readyReadStandardOutput.connect(self._read_process_stdout)
        self._process.readyReadStandardError.connect(self._read_process_stderr)
        self._process.errorOccurred.connect(self._on_process_error)
        self._process.finished.connect(self._on_process_finished)
        self._extension_process = QProcess(self)
        self._extension_process.readyReadStandardOutput.connect(self._read_extension_stdout)
        self._extension_process.readyReadStandardError.connect(self._read_extension_stderr)
        self._extension_process.errorOccurred.connect(self._on_extension_process_error)
        self._extension_process.finished.connect(self._on_extension_process_finished)
        self._environment_process = QProcess(self)
        self._environment_process.finished.connect(self._on_environment_process_finished)
        self._environment_process.errorOccurred.connect(self._on_environment_process_error)
        self._build_ui()
        self._refresh_dependency_table()
        self._refresh_extensions()
        QTimer.singleShot(0, self.refresh_environment)

    def _build_ui(self):
        self.setObjectName("package_manager_page")
        self.setStyleSheet(
            "QWidget#package_manager_page { background: #F6F8FB; }"
            "QLabel { color: #1F2937; }"
            "QLineEdit { background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 4px; "
            "padding: 5px 8px; min-height: 20px; }"
            "QLineEdit:focus { border-color: #0284C7; }"
            "QTableWidget { background: #FFFFFF; border: 1px solid #D9E1EA; gridline-color: #E8EDF3; "
            "selection-background-color: #DDEEF8; selection-color: #102A43; }"
            "QHeaderView::section { background: #F1F5F9; color: #475569; border: none; "
            "border-bottom: 1px solid #D9E1EA; padding: 7px 8px; font-weight: 600; }"
            "QTabBar::tab { background: transparent; color: #64748B; padding: 8px 14px; "
            "border: none; border-bottom: 2px solid transparent; }"
            "QTabBar::tab:selected { color: #0369A1; border-bottom-color: #0284C7; font-weight: 600; }"
            "QPushButton { background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 4px; "
            "padding: 5px 10px; color: #334155; }"
            "QPushButton:hover { background: #F1F5F9; border-color: #94A3B8; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("打包管理")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.environment_label = QLabel("等待读取构建 Python 环境")
        self.environment_label.setStyleSheet("color: #64748B; font-size: 12px;")
        title_box.addWidget(title)
        title_box.addWidget(self.environment_label)
        header.addLayout(title_box)
        header.addStretch(1)

        self.refresh_button = QToolButton()
        self.refresh_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.refresh_button.setToolTip("刷新当前 Python 环境")
        self.refresh_button.setFixedSize(30, 30)
        self.refresh_button.clicked.connect(self.refresh_environment)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_build_tab(), "构建程序")
        self.tabs.addTab(self._build_extensions_tab(), "外置扩展")
        self.tabs.addTab(self._build_dependency_tab(), "程序基础包")
        layout.addWidget(self.tabs, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #64748B; font-size: 12px;")
        layout.addWidget(self.status_label)
        self._build_report_panel(layout)
        self._update_draft_label()

    def _build_dependency_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(8)

        summary = QLabel(
            "基础清单用于构建设计器和运行器。第三方依赖可选择内置或外置；标准库会随构建 Python 自动收集。"
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #475569; background: #F1F5F9; padding: 7px 9px; border-radius: 4px;")
        layout.addWidget(summary)

        toolbar = QHBoxLayout()
        self.dependency_search = QLineEdit()
        self.dependency_search.setPlaceholderText("筛选根模块或发行包")
        self.dependency_search.textChanged.connect(self._refresh_dependency_table)
        toolbar.addWidget(self.dependency_search, 1)

        self.add_button = QPushButton("新增库")
        self.add_button.setToolTip("从当前 Python 环境选择并添加打包依赖")
        self.add_button.setStyleSheet(
            "QPushButton { background: #2563EB; border-color: #2563EB; color: #FFFFFF; font-weight: 600; }"
            "QPushButton:hover { background: #1D4ED8; border-color: #1D4ED8; }"
        )
        self.add_button.clicked.connect(self._add_dependency)
        self.remove_button = QToolButton()
        self.remove_button.setText("-")
        self.remove_button.setToolTip("移除选中的预收集依赖")
        self.remove_button.setFixedSize(30, 30)
        self.remove_button.clicked.connect(self._remove_selected_dependencies)
        self.remove_button.setStyleSheet(
            "QToolButton { background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 4px; "
            "font-size: 18px; color: #334155; }"
            "QToolButton:hover { background: #F1F5F9; border-color: #94A3B8; }"
        )
        self.save_button = QPushButton("保存基础清单")
        self.save_button.setToolTip("保存到 config/dynamic_imports.json，供生成 Spec 和构建程序使用")
        self.save_button.setStyleSheet(
            "QPushButton { background: #475569; border-color: #475569; color: #FFFFFF; font-weight: 600; }"
            "QPushButton:hover { background: #334155; border-color: #334155; }"
        )
        self.save_button.clicked.connect(self._save_manifest)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.remove_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.save_button)
        layout.addLayout(toolbar)

        self.stdlib_notice = QLabel(
            "标准库不需要加入外置扩展。构建时会按所选 Python 自动预收集；tkinter 的 Tcl/Tk 资源仍需内置到程序。"
        )
        self.stdlib_notice.setWordWrap(True)
        self.stdlib_notice.setStyleSheet(
            "color: #0F3D63; background: #E0F2FE; border: 1px solid #7DD3FC; "
            "border-radius: 5px; padding: 7px 9px;"
        )
        layout.addWidget(self.stdlib_notice)

        self.dependency_table = self._create_table(
            ["根模块", "发行包", "交付方式", "构建目标", "来源", "环境"],
            selection_mode=QAbstractItemView.ExtendedSelection,
        )
        self.dependency_table.setColumnWidth(0, 150)
        self.dependency_table.setColumnWidth(2, 95)
        self.dependency_table.setColumnWidth(4, 105)
        layout.addWidget(self.dependency_table, 1)
        self.draft_label = QLabel("")
        self.draft_label.setStyleSheet("color: #64748B; font-size: 12px;")
        layout.addWidget(self.draft_label)
        return page

    def _build_extensions_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(8)

        self.extension_status_label = QLabel("")
        self.extension_status_label.setWordWrap(True)
        self.extension_status_label.setStyleSheet("color: #475569; background: #F1F5F9; padding: 8px;")
        layout.addWidget(self.extension_status_label)

        current_toolbar = QHBoxLayout()
        current_title_box = QVBoxLayout()
        current_title_box.setSpacing(2)
        current_title = QLabel("当前加载的扩展环境")
        current_title.setStyleSheet("font-weight: 600; color: #334155;")
        self.current_environment_details = QLabel("")
        self.current_environment_details.setStyleSheet("color: #64748B; font-size: 12px;")
        current_title_box.addWidget(current_title)
        current_title_box.addWidget(self.current_environment_details)
        self.extension_refresh_button = QToolButton()
        self.extension_refresh_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.extension_refresh_button.setToolTip("刷新当前加载环境和待合并导入包")
        self.extension_refresh_button.setFixedSize(30, 30)
        self.extension_refresh_button.clicked.connect(self._refresh_extensions)
        current_toolbar.addLayout(current_title_box)
        current_toolbar.addStretch(1)
        current_toolbar.addWidget(self.extension_refresh_button)
        layout.addLayout(current_toolbar)

        self.extensions_table = self._create_table(
            ["包名", "版本", "角色"],
        )
        self.extensions_table.setColumnWidth(0, 260)
        self.extensions_table.setColumnWidth(1, 160)
        self.extensions_table.setMinimumHeight(150)
        layout.addWidget(self.extensions_table, 1)

        extension_toolbar = QHBoxLayout()
        self.extension_build_button = QPushButton("生成扩展包")
        self.extension_build_button.setToolTip("打开独立清单，选择本次要导出的第三方库并生成 ZIP")
        self.extension_build_button.setStyleSheet(
            "QPushButton { background: #7C3AED; border-color: #7C3AED; color: #FFFFFF; font-weight: 600; }"
            "QPushButton:hover { background: #6D28D9; border-color: #6D28D9; }"
        )
        self.extension_build_button.clicked.connect(self._open_extension_manifest_dialog)
        self.extension_import_button = QPushButton("导入并自动合并")
        self.extension_import_button.setToolTip("导入 ZIP 后自动合并到当前扩展环境并刷新库列表")
        self.extension_import_button.clicked.connect(self._import_extension_archive)
        extension_toolbar.addWidget(self.extension_build_button)
        extension_toolbar.addWidget(self.extension_import_button)
        extension_toolbar.addStretch(1)
        layout.addLayout(extension_toolbar)

        self._refresh_extensions()
        return page

    def _build_build_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(8)

        command_frame = QFrame()
        command_frame.setObjectName("build_command_frame")
        command_frame.setStyleSheet(
            "QFrame#build_command_frame { background: #FFFFFF; border: 1px solid #D9E1EA; border-radius: 5px; }"
        )
        command_layout = QHBoxLayout(command_frame)
        command_layout.setContentsMargins(12, 9, 12, 9)
        command_layout.setSpacing(8)
        command_label = QLabel("构建 Python")
        command_label.setStyleSheet("font-weight: 600; color: #334155;")
        self.python_command_input = QLineEdit(_default_python_command())
        self.python_command_input.setMinimumWidth(240)
        self.python_command_input.setToolTip("输入 Python 命令或完整 python.exe 路径")
        self.python_command_input.editingFinished.connect(self.refresh_environment)
        self.python_browse_button = QToolButton()
        self.python_browse_button.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.python_browse_button.setToolTip("选择 Python 可执行文件")
        self.python_browse_button.setFixedSize(30, 30)
        self.python_browse_button.clicked.connect(self._browse_python_command)
        command_hint = QLabel("Spec 和 PyInstaller 均使用此 Python 环境")
        command_hint.setStyleSheet("color: #64748B; font-size: 12px;")
        command_layout.addWidget(command_label)
        command_layout.addWidget(self.python_command_input, 1)
        command_layout.addWidget(self.python_browse_button)
        command_layout.addWidget(command_hint)
        layout.addWidget(command_frame)

        targets_frame = QFrame()
        targets_frame.setObjectName("build_targets_frame")
        targets_frame.setStyleSheet(
            "QFrame#build_targets_frame { background: #FFFFFF; border: 1px solid #D9E1EA; border-radius: 5px; }"
            "QFrame#build_target_card { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 4px; }"
        )
        targets_layout = QVBoxLayout(targets_frame)
        targets_layout.setContentsMargins(12, 10, 12, 12)
        targets_layout.setSpacing(8)
        targets_title = QLabel("构建目标")
        targets_title.setStyleSheet("font-weight: 600; color: #334155;")
        targets_layout.addWidget(targets_title)
        target_cards = QHBoxLayout()
        target_cards.setSpacing(8)
        for key, label in _TARGETS:
            card = QFrame()
            card.setObjectName("build_target_card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(3)
            check = QCheckBox(label)
            check.setChecked(True)
            self._target_checks[key] = check
            description = QLabel(_TARGET_DESCRIPTIONS[key])
            description.setWordWrap(True)
            description.setStyleSheet("color: #64748B; font-size: 12px;")
            card_layout.addWidget(check)
            card_layout.addWidget(description)
            target_cards.addWidget(card, 1)
        targets_layout.addLayout(target_cards)
        layout.addWidget(targets_frame)

        actions = QHBoxLayout()
        self.generate_button = QPushButton("生成 Spec")
        self.generate_button.setToolTip("保存基础清单并覆盖选中目标的 Spec 文件")
        self.generate_button.setStyleSheet(
            "QPushButton { background: #0F766E; border-color: #0F766E; color: #FFFFFF; font-weight: 600; }"
            "QPushButton:hover { background: #0B625C; border-color: #0B625C; }"
        )
        self.generate_button.clicked.connect(self._generate_specs)
        self.start_build_button = QPushButton("开始打包")
        self.start_build_button.setToolTip("保存清单、生成 Spec 并执行 PyInstaller")
        self.start_build_button.setStyleSheet(
            "QPushButton { background: #2563EB; border-color: #2563EB; color: #FFFFFF; font-weight: 600; }"
            "QPushButton:hover { background: #1D4ED8; border-color: #1D4ED8; }"
        )
        self.start_build_button.clicked.connect(self._start_packaging)
        self.stop_build_button = QPushButton("停止")
        self.stop_build_button.setToolTip("停止当前 PyInstaller 打包任务")
        self.stop_build_button.setEnabled(False)
        self.stop_build_button.clicked.connect(self._stop_packaging)
        actions.addWidget(self.generate_button)
        actions.addStretch(1)
        actions.addWidget(self.stop_build_button)
        actions.addWidget(self.start_build_button)
        layout.addLayout(actions)
        layout.addStretch(1)
        return page

    def _build_report_panel(self, parent_layout):
        header = QHBoxLayout()
        self.report_toggle = QToolButton()
        self.report_toggle.setText("构建日志")
        self.report_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.report_toggle.setArrowType(Qt.RightArrow)
        self.report_toggle.setCheckable(True)
        self.report_toggle.setToolTip("展开或收起构建日志")
        self.report_toggle.toggled.connect(self._toggle_report_panel)
        self.clear_report_button = QToolButton()
        self.clear_report_button.setText("清空")
        self.clear_report_button.setToolTip("清空构建日志")
        self.clear_report_button.clicked.connect(lambda: self.report_view.clear())
        header.addWidget(self.report_toggle)
        header.addStretch(1)
        header.addWidget(self.clear_report_button)
        parent_layout.addLayout(header)

        self.report_panel = QFrame()
        self.report_panel.setObjectName("build_report_panel")
        self.report_panel.setStyleSheet(
            "QFrame#build_report_panel { background: #FFFFFF; border: 1px solid #D9E1EA; border-radius: 5px; }"
        )
        layout = QVBoxLayout(self.report_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.report_view = QPlainTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setPlainText("暂无构建报告")
        self.report_view.setStyleSheet(
            "QPlainTextEdit { background: #FFFFFF; border: 1px solid #D9E1EA; color: #64748B; "
            "padding: 10px; }"
        )
        layout.addWidget(self.report_view)
        self.report_panel.setMinimumHeight(180)
        self.report_panel.setMaximumHeight(280)
        self.report_panel.hide()
        parent_layout.addWidget(self.report_panel)

    def _toggle_report_panel(self, visible):
        self.report_panel.setVisible(visible)
        self.report_toggle.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)

    def _show_report_panel(self):
        self.report_toggle.setChecked(True)

    @staticmethod
    def _create_table(headers, selection_mode=QAbstractItemView.NoSelection):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(selection_mode)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(30)
        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        return table

    def refresh_environment(self):
        if self._environment_process.state() != QProcess.NotRunning:
            self.status_label.setText("正在读取构建 Python 环境")
            return
        command = self.python_command_input.text().strip()
        if not command:
            self._set_environment_scan_error("请填写 Python 命令或选择 python.exe")
            return
        self._environment_scan_command = command
        self._environment_scan_error = ""
        self.environment_label.setText(f"正在读取 {command} 的本地 site-packages...")
        self._refresh_dependency_table()
        self._refresh_extensions()
        self.status_label.setText("正在读取构建 Python 环境")
        self._environment_process.start(command, ["-c", _PYTHON_ENVIRONMENT_DISCOVERY_SCRIPT])

    @staticmethod
    def _parse_environment_scan_output(output):
        payload = json.loads(str(output or "").strip())
        if not isinstance(payload, dict):
            raise ValueError("Python 环境返回的内容不是对象")
        packages = {}
        for distribution in payload.get("packages") or []:
            if not isinstance(distribution, dict):
                continue
            name = str(distribution.get("name") or "").strip()
            if not name:
                continue
            modules = [
                str(module).strip()
                for module in distribution.get("modules") or []
                if _MODULE_ROOT_RE.match(str(module).strip())
            ]
            module = modules[0] if modules else _default_import_root(name)
            packages[name.casefold()] = {
                "name": name,
                "version": str(distribution.get("version") or ""),
                "module": module,
                "modules": modules or ([module] if module else []),
            }
        runtime = {
            "python": str(payload.get("python") or "").strip(),
            "executable": str(payload.get("executable") or "").strip(),
            "architecture": str(payload.get("architecture") or "").strip(),
        }
        if not runtime["python"] or not runtime["executable"]:
            raise ValueError("Python 环境信息不完整")
        return runtime, sorted(packages.values(), key=lambda item: item["name"].casefold())

    def _set_environment_scan_error(self, message):
        self._environment_runtime = {}
        self._environment_packages = []
        self._environment_scan_error = str(message or "无法读取 Python 环境")
        self.environment_label.setText(f"无法读取构建 Python 环境：{self._environment_scan_error}")
        self._refresh_dependency_table()
        self.status_label.setText("构建 Python 环境读取失败")

    def _on_environment_process_error(self, error):
        if error == QProcess.FailedToStart:
            self._set_environment_scan_error("无法启动 {}".format(self._environment_scan_command or "Python 命令"))

    def _on_environment_process_finished(self, exit_code, _exit_status):
        stdout = bytes(self._environment_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        stderr = bytes(self._environment_process.readAllStandardError()).decode("utf-8", errors="replace")
        if exit_code != 0:
            self._set_environment_scan_error(stderr.strip() or stdout.strip() or "Python 命令退出码 {}".format(exit_code))
            return
        try:
            runtime, packages = self._parse_environment_scan_output(stdout)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            details = stderr.strip() or str(exc)
            self._set_environment_scan_error("环境信息格式无效：{}".format(details))
            return
        self._environment_runtime = runtime
        self._environment_packages = packages
        self._environment_scan_error = ""
        self.environment_label.setText(
            "Python {}  |  {}  |  已发现 {} 个发行包".format(
                runtime["python"], runtime["executable"], len(packages)
            )
        )
        self._refresh_dependency_table()
        self._refresh_extensions()
        self.status_label.setText("已读取构建 Python 环境")

    def _selected_targets(self):
        return [key for key, check in self._target_checks.items() if check.isChecked()]

    def _refresh_dependency_table(self):
        query = self.dependency_search.text().strip().casefold() if hasattr(self, "dependency_search") else ""
        rows = []
        for dependency in self._dependencies:
            searchable = f"{dependency['module']} {dependency['distribution']}".casefold()
            if query and query not in searchable:
                continue
            rows.append(dependency)

        self.dependency_table.setRowCount(len(rows))
        for row_index, dependency in enumerate(rows):
            is_collect_all_stdlib = requires_collect_all(dependency["module"])
            values = [
                dependency["module"],
                dependency["distribution"],
                (
                    "标准库 · collect_all"
                    if is_collect_all_stdlib
                    else "外置扩展"
                    if dependency.get("delivery") == "external"
                    else f"内置 collect_{dependency['collect']}"
                ),
                self._target_text(dependency["targets"]),
                (
                    "标准库"
                    if is_standard_library_module(dependency["module"])
                    else dependency["source"]
                ),
                "已安装"
                if self._module_is_available(dependency["module"], dependency.get("distribution"))
                else "未安装",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, dependency["module"])
                if column == 5:
                    item.setForeground(Qt.darkGreen if value == "已安装" else Qt.darkRed)
                self.dependency_table.setItem(row_index, column, item)
        self._update_draft_label()

    def _module_is_available(self, module, distribution=""):
        if self._environment_scan_error:
            return False
        module_key = str(module or "").casefold()
        distribution_key = re.sub(r"[-_.]+", "-", str(distribution or "").strip()).casefold()
        for package in self._environment_packages:
            package_key = re.sub(r"[-_.]+", "-", package["name"]).casefold()
            modules = {str(item).casefold() for item in package.get("modules") or []}
            if module_key in modules or distribution_key == package_key:
                return True
        return False

    @staticmethod
    def _target_text(targets):
        labels = dict(_TARGETS)
        return "、".join(labels.get(target, target) for target in targets)

    def _add_dependency(self):
        dialog = AddDependencyDialog(
            self._selected_targets(),
            available_packages=self._environment_packages,
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        dependency = dialog.dependency()
        if any(item["module"] == dependency["module"] for item in self._dependencies):
            self.status_label.setText(f"根模块 {dependency['module']} 已在当前草稿中")
            return
        self._dependencies.append(dependency)
        self._draft_dirty = True
        self._refresh_dependency_table()
        self.status_label.setText(f"已加入当前会话草稿：{dependency['module']}")
        self.dependencies_changed.emit(self.dependencies())

    def _remove_selected_dependencies(self):
        selected_modules = {
            self.dependency_table.item(row, 0).data(Qt.UserRole)
            for row in {index.row() for index in self.dependency_table.selectedIndexes()}
            if self.dependency_table.item(row, 0) is not None
        }
        if not selected_modules:
            self.status_label.setText("请选择要移除的依赖")
            return
        removable_modules = {
            module for module in selected_modules if not is_baseline_dependency(module)
        }
        protected_modules = selected_modules - removable_modules
        if not removable_modules:
            self.status_label.setText("程序基线依赖会自动保留，不能删除")
            return
        self._dependencies = [
            item for item in self._dependencies if item["module"] not in removable_modules
        ]
        self._draft_dirty = True
        if protected_modules:
            self.status_label.setText("程序基线依赖会自动保留；已移除其余选中依赖")
        self._refresh_dependency_table()
        self.status_label.setText(f"已从当前会话草稿移除 {len(removable_modules)} 项")
        self.dependencies_changed.emit(self.dependencies())

    def dependencies(self):
        return copy.deepcopy(self._dependencies)

    def _update_draft_label(self):
        state = "未保存" if self._draft_dirty else "已保存"
        self.draft_label.setText(f"当前草稿 · {len(self._dependencies)} 项 · {state}")

    @staticmethod
    def _extension_modules(info):
        manifest = info.get("manifest") if isinstance(info, dict) else {}
        dependencies = manifest.get("requested_dependencies") if isinstance(manifest, dict) else []
        return "、".join(
            "{}{}".format(
                str(item.get("module") or ""),
                " {}".format(item.get("version")) if item.get("version") else "",
            )
            for item in dependencies or []
            if isinstance(item, dict) and item.get("module")
        ) or "-"

    @staticmethod
    def _extension_distributions(info):
        manifest = info.get("manifest") if isinstance(info, dict) else {}
        distributions = manifest.get("distributions") if isinstance(manifest, dict) else []
        return "、".join(
            "{}{}".format(
                str(item.get("name") or ""),
                " {}".format(item.get("version")) if item.get("version") else "",
            )
            for item in distributions or []
            if isinstance(item, dict) and item.get("name")
        ) or "-"

    @staticmethod
    def _extension_distribution_rows(info):
        manifest = info.get("manifest") if isinstance(info, dict) else {}
        dependencies = manifest.get("requested_dependencies") if isinstance(manifest, dict) else []
        distributions = manifest.get("distributions") if isinstance(manifest, dict) else []

        def normalize(name):
            return re.sub(r"[-_.]+", "-", str(name or "").strip()).casefold()

        root_keys = {
            normalize(item.get("distribution") or item.get("module"))
            for item in dependencies or []
            if isinstance(item, dict) and (item.get("distribution") or item.get("module"))
        }
        if not distributions:
            distributions = [
                {
                    "name": item.get("distribution") or item.get("module"),
                    "version": item.get("version"),
                }
                for item in dependencies or []
                if isinstance(item, dict)
            ]
        rows = []
        for item in distributions or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            rows.append(
                {
                    "name": name,
                    "version": str(item.get("version") or "-").strip() or "-",
                    "role": "根包" if normalize(name) in root_keys else "依赖",
                }
            )
        return sorted(rows, key=lambda item: (item["role"] != "根包", item["name"].casefold()))

    def _extension_runtime_root(self):
        return get_runtime_root()

    def _refresh_extensions(self):
        if not hasattr(self, "extensions_table"):
            return
        active = active_extension_info(self._extension_runtime_root())
        current_rows = self._extension_distribution_rows(active) if active.get("available") else []
        self.extensions_table.setRowCount(len(current_rows))
        if active.get("available"):
            manifest = active.get("manifest") if isinstance(active.get("manifest"), dict) else {}
            runtime = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
            self.current_environment_details.setText(
                "环境 {}  |  Python {}  |  {}  |  {} 个发行包".format(
                    active.get("version") or "-",
                    runtime.get("python") or "-",
                    runtime.get("architecture") or "-",
                    len(current_rows),
                )
            )
            for row, package in enumerate(current_rows):
                for column, value in enumerate((package["name"], package["version"], package["role"])):
                    item = QTableWidgetItem(value)
                    if column == 2:
                        item.setForeground(Qt.darkGreen if package["role"] == "根包" else Qt.darkGray)
                    self.extensions_table.setItem(row, column, item)
            self.extension_status_label.setText(
                f"当前环境已加载 {len(current_rows)} 个发行包。导入 ZIP 会自动合并到这里。"
            )
        else:
            self.current_environment_details.setText("当前没有已加载的外置扩展环境")
            self.extension_status_label.setText(
                "当前尚未加载外置扩展。导入第一个 ZIP 后会自动创建当前环境。"
            )

    def _open_extension_manifest_dialog(self):
        if self._process.state() != QProcess.NotRunning:
            self.status_label.setText("当前正在执行程序打包")
            return
        if self._environment_process.state() != QProcess.NotRunning:
            self.status_label.setText("正在读取构建 Python 环境，请稍后再新建扩展清单")
            return
        if self._extension_process.state() != QProcess.NotRunning or self._extension_import_thread is not None:
            self.status_label.setText("当前正在处理外置扩展")
            return
        dialog = ExtensionManifestDialog(self._environment_packages, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self._start_extension_build(dialog.dependencies, dialog.archive_name())

    def _start_extension_build(self, dependencies, archive_name=None):
        if self._process.state() != QProcess.NotRunning:
            self.status_label.setText("当前正在执行程序打包")
            return
        if self._extension_process.state() != QProcess.NotRunning:
            return
        command = self.python_command_input.text().strip()
        if not command:
            self.status_label.setText("请填写 Python 命令或选择 python.exe")
            return
        if not dependencies:
            self.status_label.setText("扩展清单为空；请先选择要导出的库")
            return
        try:
            context = prepare_extension_build(
                command,
                dependencies,
                runtime_root=self._extension_runtime_root(),
                archive_name=archive_name,
            )
        except ExtensionBuildError as exc:
            self.status_label.setText(f"无法生成扩展包：{exc}")
            return
        self._extension_build_context = context
        self._extension_stop_requested = False
        arguments = copy_installed_arguments(context)
        self.report_view.clear()
        self._show_report_panel()
        self._append_report(
            f"[扩展 {context['version']}] 从 {command} 的本地 site-packages 复制："
            f"{', '.join(context['requirements'])}"
        )
        self.status_label.setText(f"正在生成外置扩展包：{context['version']}")
        self._set_extension_controls(True, can_stop=True)
        self._extension_process.setWorkingDirectory(str(self._extension_runtime_root()))
        self._extension_process.start(command, arguments)

    def _read_extension_stdout(self):
        output = bytes(self._extension_process.readAllStandardOutput()).decode("utf-8", errors="replace").rstrip()
        if output:
            self._append_report(output)

    def _read_extension_stderr(self):
        output = bytes(self._extension_process.readAllStandardError()).decode("utf-8", errors="replace").rstrip()
        if output:
            self._append_report(output)

    def _on_extension_process_error(self, error):
        if error != QProcess.FailedToStart:
            return
        discard_extension_build(self._extension_build_context)
        self._extension_build_context = None
        self._extension_stop_requested = False
        self._set_extension_controls(False)
        self.status_label.setText("无法启动 Python 命令以生成扩展包")
        self._append_report("无法启动 Python 命令，请检查 Python 命令或 python.exe 路径。")

    def _on_extension_process_finished(self, exit_code, _exit_status):
        context = self._extension_build_context
        self._extension_build_context = None
        self._set_extension_controls(False)
        if context is None:
            return
        if self._extension_stop_requested:
            self._extension_stop_requested = False
            discard_extension_build(context)
            self.status_label.setText("外置扩展包安装已停止")
            self._append_report(f"[扩展 {context['version']}] 安装已停止")
            return
        if exit_code != 0:
            discard_extension_build(context)
            self.status_label.setText(f"生成外置扩展包失败，退出码 {exit_code}")
            self._append_report(f"[扩展 {context['version']}] 生成失败，退出码 {exit_code}")
            return
        try:
            result = finalize_extension_build(context, activate=True)
            self._refresh_extensions()
            self.status_label.setText(
                f"已生成扩展包 {result['version']}。请在目标程序中导入 ZIP 自动合并"
            )
            self._append_report(f"[扩展 {result['version']}] 已生成：{result['archive_path']}")
        except ExtensionBuildError as exc:
            self.status_label.setText(f"扩展包整理失败：{exc}")
            self._append_report(
                f"[扩展] 整理失败：{exc}\n"
                f"[扩展 {context['version']}] 暂存目录已保留：{context['staging_root']}"
            )
        except Exception as exc:  # Keep an unexpected Qt-slot failure inside the page.
            self.status_label.setText(f"扩展包整理发生未预期错误：{exc}")
            self._append_report(
                "[扩展] 未预期错误：\n{}\n[扩展 {}] 暂存目录已保留：{}".format(
                    traceback.format_exc(), context["version"], context["staging_root"]
                )
            )

    def _import_extension_archive(self):
        if self._extension_import_thread is not None:
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "导入外置扩展包",
            "",
            "扩展包 (*.zip)",
        )
        if not path:
            return
        thread = ExtensionArchiveImportThread(path, self._extension_runtime_root(), self)
        thread.finished.connect(self._on_extension_import_thread_finished)
        self._extension_import_thread = thread
        self._set_extension_controls(True)
        self.status_label.setText("正在导入并自动合并扩展包")
        self._append_report(f"[扩展] 正在导入并自动合并：{path}")
        thread.start()

    def _on_extension_import_thread_finished(self):
        thread = self._extension_import_thread
        self._extension_import_thread = None
        if thread is None:
            return
        thread.deleteLater()
        self._set_extension_controls(False)

        if thread.error:
            self.status_label.setText(f"导入扩展包失败：{thread.error}")
            self._append_report(f"[扩展] 导入失败：{thread.error}")
            if thread.error_trace:
                self._append_report(thread.error_trace)
            return

        result = thread.result or {}
        self._refresh_extensions()
        added = ", ".join(result.get("added_distributions") or [])
        updated = ", ".join(
            "{} {} -> {}".format(item["name"], item["current_version"], item["incoming_version"])
            for item in result.get("updated_distributions") or []
        )
        details = "；".join(
            item for item in (
                "新增 {}".format(added) if added else "",
                "更新 {}".format(updated) if updated else "",
            ) if item
        )
        suffix = "（{}）".format(details) if details else ""
        if result.get("created_initial_environment"):
            self.status_label.setText(
                f"已导入并自动创建当前扩展环境 {result['version']}{suffix}。"
            )
        else:
            self.status_label.setText(
                f"已导入并自动合并到当前扩展环境 {result['version']}{suffix}。"
            )

    def _save_manifest(self):
        try:
            self._dependencies = save_dependencies(self._dependencies, self._project_root)
        except OSError as exc:
            self.status_label.setText(f"保存依赖清单失败：{exc}")
            return False
        self._draft_dirty = False
        self._refresh_dependency_table()
        self.status_label.setText(f"已保存依赖清单：{get_manifest_path(self._project_root)}")
        self.dependencies_changed.emit(self.dependencies())
        return True

    def _generate_specs(self):
        targets = self._selected_targets()
        if not targets:
            self.status_label.setText("请至少选择一个构建目标")
            return
        generated = self._save_and_generate_specs(targets)
        if generated is None:
            return
        paths = "\n".join(str(path) for path in generated)
        self.report_view.setPlainText(f"已生成并覆盖 Spec：\n{paths}")
        self._show_report_panel()
        self.status_label.setText(f"已覆盖 {len(generated)} 个 Spec 文件")

    def _save_and_generate_specs(self, targets):
        if not self._save_manifest():
            return None
        try:
            return generate_spec_files(targets, self._project_root)
        except OSError as exc:
            self.status_label.setText(f"生成 Spec 失败：{exc}")
            return None

    def _browse_python_command(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择 Python 可执行文件",
            self.python_command_input.text().strip(),
            "Python (python.exe python3 python)"
        )
        if path:
            self.python_command_input.setText(path)

    def _start_packaging(self):
        if self._process.state() != QProcess.NotRunning:
            return
        if self._extension_process.state() != QProcess.NotRunning:
            self.status_label.setText("当前正在生成外置扩展包")
            return
        command = self.python_command_input.text().strip()
        if not command:
            self.status_label.setText("请填写 Python 命令或选择 python.exe")
            return
        targets = self._selected_targets()
        if not targets:
            self.status_label.setText("请至少选择一个构建目标")
            return
        generated = self._save_and_generate_specs(targets)
        if generated is None:
            return
        self._pending_builds = list(zip(targets, [str(path) for path in generated]))
        self._stop_requested = False
        self.report_view.clear()
        self._show_report_panel()
        self._set_build_controls(True)
        self._start_next_build()

    def _start_next_build(self):
        if not self._pending_builds:
            self._active_target = ""
            self._set_build_controls(False)
            self.status_label.setText("所选构建目标已完成")
            self._append_report("\n打包完成")
            return
        target, spec_path = self._pending_builds.pop(0)
        self._active_target = target
        command = self.python_command_input.text().strip()
        arguments = ["-m", "PyInstaller", spec_path, "--clean", "--noconfirm"]
        self._append_report(f"\n[{target}] {command} {' '.join(arguments)}")
        self.status_label.setText(f"正在打包：{target}")
        self._process.setWorkingDirectory(str(self._resolved_project_root()))
        self._process.start(command, arguments)

    def _stop_packaging(self):
        if self._process.state() != QProcess.NotRunning:
            self._stop_requested = True
            self._pending_builds = []
            self.status_label.setText("正在停止当前打包任务")
            self._append_report("\n已请求停止当前打包任务")
            self._process.terminate()
            QTimer.singleShot(1500, self._kill_process_if_running)
            return
        if self._extension_process.state() != QProcess.NotRunning:
            self._extension_stop_requested = True
            self.status_label.setText("正在停止外置扩展包安装")
            self._append_report("\n已请求停止外置扩展包安装")
            self._extension_process.terminate()
            QTimer.singleShot(1500, self._kill_extension_process_if_running)

    def _kill_process_if_running(self):
        if self._process.state() != QProcess.NotRunning:
            self._process.kill()

    def _kill_extension_process_if_running(self):
        if self._extension_process.state() != QProcess.NotRunning:
            self._extension_process.kill()

    def _read_process_stdout(self):
        output = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace").rstrip()
        if output:
            self._append_report(output)

    def _read_process_stderr(self):
        output = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace").rstrip()
        if output:
            self._append_report(output)

    def _on_process_error(self, error):
        if error != QProcess.FailedToStart:
            return
        self._pending_builds = []
        self._set_build_controls(False)
        self.status_label.setText("无法启动 Python 命令")
        self._append_report("无法启动 Python 命令，请检查 Python 命令或 python.exe 路径。")

    def _on_process_finished(self, exit_code, _exit_status):
        target = self._active_target
        if self._stop_requested:
            self._active_target = ""
            self._set_build_controls(False)
            self.status_label.setText("打包已停止")
            self._append_report("打包已停止")
            return
        if exit_code != 0:
            self._pending_builds = []
            self._active_target = ""
            self._set_build_controls(False)
            self.status_label.setText(f"打包失败：{target}，退出码 {exit_code}")
            self._append_report(f"[{target}] 打包失败，退出码 {exit_code}")
            return
        self._append_report(f"[{target}] 打包成功")
        self._start_next_build()

    def _set_build_controls(self, running):
        self.start_build_button.setEnabled(not running)
        self.stop_build_button.setEnabled(running)
        self.save_button.setEnabled(not running)
        self.generate_button.setEnabled(not running)
        self.add_button.setEnabled(not running)
        self.remove_button.setEnabled(not running)
        self.python_command_input.setEnabled(not running)
        self.python_browse_button.setEnabled(not running)
        self.extension_build_button.setEnabled(not running)
        self.extension_import_button.setEnabled(not running and self._extension_import_thread is None)
        self.extension_refresh_button.setEnabled(not running)
        for check in self._target_checks.values():
            check.setEnabled(not running)

    def _set_extension_controls(self, running, can_stop=False):
        self.extension_build_button.setEnabled(not running)
        self.extension_import_button.setEnabled(not running and self._extension_import_thread is None)
        self.extension_refresh_button.setEnabled(not running)
        self.save_button.setEnabled(not running)
        self.generate_button.setEnabled(not running)
        self.start_build_button.setEnabled(not running)
        self.stop_build_button.setEnabled(running and can_stop)
        self.python_command_input.setEnabled(not running)
        self.python_browse_button.setEnabled(not running)
        self.add_button.setEnabled(not running)
        self.remove_button.setEnabled(not running)
        for check in self._target_checks.values():
            check.setEnabled(not running)

    def _append_report(self, text):
        self.report_view.appendPlainText(str(text))

    def _resolved_project_root(self):
        return get_manifest_path(self._project_root).parents[1]

    def get_state(self):
        return {"python_command": self.python_command_input.text().strip() or _default_python_command()}

    def restore_state(self, state):
        if isinstance(state, dict):
            self.python_command_input.setText(
                str(state.get("python_command") or _default_python_command())
            )
            QTimer.singleShot(0, self.refresh_environment)

    def shutdown_for_close(self):
        return (
            self._process.state() == QProcess.NotRunning
            and self._extension_process.state() == QProcess.NotRunning
            and self._environment_process.state() == QProcess.NotRunning
            and self._extension_import_thread is None
        )
