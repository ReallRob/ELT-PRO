"""PyQt launcher that builds a runtime form from workflow JSON."""

import fnmatch
import json
import os
import sys
import traceback
from pathlib import Path

from PyQt5.QtCore import QProcess, QRectF, QSize, Qt, QThread, QTimer
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QApplication,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from engine import WorkflowEngine
from crpa import CRPA
from crpa_launcher.manifest_runtime import (
    build_crpa_payload,
    build_runtime_workflow,
    collect_file_contexts,
    file_dialog_filter,
    load_excel_sheet_names,
    load_workflow_json,
    save_workflow_json,
)
from crpa_launcher.settings import (
    get_json_history,
    record_json_load,
    record_json_open,
    remove_json_history_item,
    set_json_history_name,
    set_json_history_tag,
    set_last_workflow_path,
)
from core.packaging.external_extensions import ExtensionBuildError, import_extension_archive
from core.parameters.mapping_schema import normalize_list_item_limits, normalize_select_options
from core.runtime_extensions import activate_external_extensions


class ExtensionArchiveImportThread(QThread):
    """Merge one extension ZIP without blocking the launcher UI."""

    def __init__(self, archive_path, parent=None):
        super().__init__(parent)
        self.archive_path = str(archive_path)
        self.result = None
        self.error = ""
        self.error_trace = ""

    def run(self):
        try:
            self.result = import_extension_archive(self.archive_path)
        except ExtensionBuildError as exc:
            self.error = str(exc)
            self.error_trace = traceback.format_exc()
        except Exception as exc:
            self.error = "导入扩展包时发生未预期错误：{}".format(exc)
            self.error_trace = traceback.format_exc()


class SwitchCheckBox(QCheckBox):
    def __init__(self, text="", show_state_text=False, parent=None):
        super().__init__(text, parent)
        self._show_state_text = show_state_text
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(34 if show_state_text else 28)
        self.setMinimumWidth(118 if show_state_text else 48)
        self.setSizePolicy(
            QSizePolicy.Expanding if show_state_text else QSizePolicy.Fixed,
            QSizePolicy.Fixed,
        )
        self.toggled.connect(lambda _=False: self.update())

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def _display_text(self):
        if self._show_state_text:
            return "已启用" if self.isChecked() else "已关闭"
        return self.text()

    def sizeHint(self):
        text = self._display_text()
        width = 118 if self._show_state_text else 48
        if text:
            width = max(width, 62 + self.fontMetrics().horizontalAdvance(text))
        return QSize(width, 34 if self._show_state_text else 28)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        enabled = self.isEnabled()
        checked = self.isChecked()
        track_color = QColor("#0B7DDA" if checked else "#D7DEE6")
        knob_color = QColor("#FFFFFF")
        text_color = QColor("#334155" if enabled else "#94A3B8")
        if not enabled:
            track_color = QColor("#E5E7EB")
            knob_color = QColor("#F8FAFC")
        if self._show_state_text:
            row_rect = QRectF(0, 0, self.width() - 1, self.height() - 1)
            painter.setPen(QColor("#D4E0EA"))
            painter.setBrush(QColor("#F7FBFE"))
            painter.drawRoundedRect(row_rect, 6, 6)
        track_x = 12 if self._show_state_text else 0
        track = QRectF(track_x, (self.height() - 22) / 2, 38, 22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 11, 11)
        knob_x = track_x + (18 if checked else 2)
        painter.setBrush(knob_color)
        painter.drawEllipse(QRectF(knob_x, (self.height() - 18) / 2, 18, 18))
        label = self._display_text()
        if label:
            painter.setPen(text_color)
            label_x = 62 if self._show_state_text else 48
            painter.drawText(label_x, 0, self.width() - label_x, self.height(), Qt.AlignVCenter | Qt.AlignLeft, label)


class CollapsibleListParam(QWidget):
    def __init__(
        self,
        label,
        values=None,
        required=False,
        initial_count=None,
        max_items=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("listParamBox")
        self.setProperty("param_type", "list")
        self._label = str(label or "列表")
        self._required = required
        initial_values = list(values or [])
        try:
            self._initial_count, self._max_items = normalize_list_item_limits(
                initial_count,
                max_items,
                len(initial_values),
            )
        except ValueError:
            self._initial_count = max(1, len(initial_values))
            self._max_items = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.header = QToolButton()
        self.header.setObjectName("listParamHeader")
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.DownArrow)
        self.header.clicked.connect(self._toggle_body)
        layout.addWidget(self.header)

        self.preview = QLabel()
        self.preview.setObjectName("listParamPreview")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        self.body = QWidget()
        self.body.setObjectName("listParamBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)

        self.list_scroll = QScrollArea()
        self.list_scroll.setObjectName("listParamScroll")
        self.list_scroll.viewport().setObjectName("listParamScrollViewport")
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_scroll.setFrameShape(QFrame.NoFrame)
        self.list_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.list_content = QWidget()
        self.list_content.setObjectName("listParamListContent")
        self.list_layout = QVBoxLayout(self.list_content)
        self.list_layout.setContentsMargins(8, 8, 8, 8)
        self.list_layout.setSpacing(6)
        self.list_scroll.setWidget(self.list_content)
        self.body_layout.addWidget(self.list_scroll)
        layout.addWidget(self.body)

        self.add_btn = QPushButton("添加项目")
        self.add_btn.setObjectName("listParamAdd")
        self.add_btn.clicked.connect(lambda _=False: self.add_item("", focus=True))
        self.body_layout.addWidget(self.add_btn)

        for item in initial_values:
            self.add_item(item)
        while self._row_count() < self._initial_count:
            self.add_item("")
        self._update_summary()
        self._update_scroll_height()
        self._update_add_button_state()

    def _toggle_body(self):
        visible = self.header.isChecked()
        self.header.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)
        self.body.setVisible(visible)
        self.preview.setVisible(not visible)
        self._update_summary()

    def add_item(self, value="", focus=False):
        if self._max_items and self._row_count() >= self._max_items:
            self._update_add_button_state()
            return None
        row = QWidget()
        row.setObjectName("listParamItemRow")
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.setFixedHeight(40)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        line = QLineEdit(str(value or ""))
        line.setObjectName("listParamItem")
        line.setPlaceholderText("请输入一项")
        line.textChanged.connect(self._update_summary)
        remove = QToolButton()
        remove.setObjectName("listParamRemove")
        remove.setText("删除")
        remove.setFixedSize(58, 34)
        remove.clicked.connect(lambda _=False, r=row: self._remove_item(r))
        row_layout.addWidget(line, stretch=1)
        row_layout.addWidget(remove)
        self.list_layout.addWidget(row)
        self.header.setChecked(True)
        self._toggle_body()
        if focus:
            QTimer.singleShot(0, lambda r=row, l=line: self._focus_new_item(r, l))
        self._update_summary()
        self._update_scroll_height()
        self._update_add_button_state()
        return row

    def _focus_new_item(self, row, line):
        if row.parentWidget() is not self.list_content:
            return
        self.list_scroll.ensureWidgetVisible(row, 0, 8)
        line.setFocus()

    def _remove_item(self, row):
        self.list_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._update_summary()
        self._update_scroll_height()
        self._update_add_button_state()

    def _row_count(self):
        return sum(
            1
            for index in range(self.list_layout.count())
            if self.list_layout.itemAt(index).widget() is not None
        )

    def _update_scroll_height(self):
        visible_rows = min(max(1, self._row_count()), 5)
        margins = self.list_layout.contentsMargins()
        row_height = 40
        spacing = self.list_layout.spacing()
        height = (
            margins.top()
            + margins.bottom()
            + visible_rows * row_height
            + max(0, visible_rows - 1) * spacing
        )
        content_height = (
            margins.top()
            + margins.bottom()
            + self._row_count() * row_height
            + max(0, self._row_count() - 1) * spacing
        )
        self.list_content.setMinimumHeight(content_height)
        self.list_scroll.setFixedHeight(height)

    def _values(self):
        return [
            line.text().strip()
            for line in self.findChildren(QLineEdit, "listParamItem")
            if line.text().strip()
        ]

    def _update_summary(self):
        values = self._values()
        marker = " *" if self._required else ""
        count = self._row_count()
        limit = f" / {self._max_items}" if self._max_items else ""
        self.header.setText(f"{self._label}{marker} ({count}{limit})")
        if values:
            preview = "、".join(values[:3])
            if len(values) > 3:
                preview += f" 等 {len(values)} 项"
        else:
            preview = "未添加"
        self.preview.setText(preview)

    def _update_add_button_state(self):
        if not hasattr(self, "add_btn"):
            return
        reached_limit = bool(self._max_items and self._row_count() >= self._max_items)
        self.add_btn.setEnabled(not reached_limit)
        if reached_limit:
            self.add_btn.setText(f"已达到上限 ({self._max_items} 项)")
            self.add_btn.setToolTip(f"最多只能填写 {self._max_items} 项")
        else:
            self.add_btn.setText("添加项目")
            self.add_btn.setToolTip("")


class CollapsibleKeyValueParam(CollapsibleListParam):
    def __init__(
        self,
        label,
        values=None,
        required=False,
        initial_count=None,
        max_items=None,
        parent=None,
    ):
        if isinstance(values, dict):
            pairs = list(values.items())
        else:
            pairs = list(values or [])
        super().__init__(label, pairs, required, initial_count, max_items, parent)
        self.setObjectName("keyValueParamBox")
        self.setProperty("param_type", "key_value")

    def add_item(self, value=("", ""), focus=False):
        if self._max_items and self._row_count() >= self._max_items:
            self._update_add_button_state()
            return None
        if isinstance(value, (tuple, list)) and len(value) >= 2:
            key, item = value[0], value[1]
        elif isinstance(value, dict) and value:
            key, item = next(iter(value.items()))
        else:
            key, item = "", "" if value is None else value
        row = QWidget()
        row.setObjectName("keyValueParamItemRow")
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.setFixedHeight(40)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        key_input = QLineEdit(str(key or ""))
        key_input.setObjectName("keyValueParamKey")
        key_input.setPlaceholderText("键，例如：docx{姓名}")
        key_input.textChanged.connect(self._update_summary)
        separator = QLabel(":")
        separator.setObjectName("keyValueParamSeparator")
        value_input = QLineEdit("" if item is None else str(item))
        value_input.setObjectName("keyValueParamValue")
        value_input.setPlaceholderText("值，例如：小明")
        value_input.textChanged.connect(self._update_summary)
        remove = QToolButton()
        remove.setObjectName("listParamRemove")
        remove.setText("删除")
        remove.setFixedSize(58, 34)
        remove.clicked.connect(lambda _=False, r=row: self._remove_item(r))
        row_layout.addWidget(key_input, stretch=1)
        row_layout.addWidget(separator)
        row_layout.addWidget(value_input, stretch=1)
        row_layout.addWidget(remove)
        self.list_layout.addWidget(row)
        self.header.setChecked(True)
        self._toggle_body()
        if focus:
            QTimer.singleShot(0, lambda r=row, line=key_input: self._focus_new_item(r, line))
        self._update_summary()
        self._update_scroll_height()
        self._update_add_button_state()
        return row

    def value(self, validate=True):
        values = {}
        for row in self.findChildren(QWidget, "keyValueParamItemRow"):
            key_input = row.findChild(QLineEdit, "keyValueParamKey")
            value_input = row.findChild(QLineEdit, "keyValueParamValue")
            key = key_input.text().strip() if key_input else ""
            item = value_input.text() if value_input else ""
            if not key:
                if item and validate:
                    raise ValueError(f"键值对参数“{self._label}”存在未填写键的值")
                continue
            if key in values:
                if validate:
                    raise ValueError(f"键值对参数“{self._label}”存在重复键: {key}")
            values[key] = item
        return values

    def _update_summary(self):
        values = self.value(validate=False)
        marker = " *" if self._required else ""
        count = self._row_count()
        limit = f" / {self._max_items}" if self._max_items else ""
        self.header.setText(f"{self._label}{marker} ({count}{limit})")
        if values:
            preview = "、".join(f"{key}:{item}" for key, item in list(values.items())[:3])
            if len(values) > 3:
                preview += f" 等 {len(values)} 项"
        else:
            preview = "未添加"
        self.preview.setText(preview)


class HistoryItemCard(QFrame):
    def __init__(self, path, on_open, parent=None):
        super().__init__(parent)
        self._path = path
        self._on_open = on_open
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self._on_open(self._path)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CrpaLauncher(QWidget):
    def __init__(self):
        super().__init__()
        self.workflow_path = ""
        self.workflow = None
        self.crpa_code = ""
        self.name = ""
        self.file_inputs = {}
        self.sheet_combos = {}
        self.param_inputs = {}
        self.sheet_sources = []
        self.advanced_sheet_card = None
        self.advanced_sheet_body = None
        self.advanced_sheet_toggle = None
        self.sheet_status_label = None
        self.engine = None
        self._extension_import_thread = None
        self._pending_history_path = None
        self._sheet_name_cache = {}
        self._history_meta_cache = {}
        self.setWindowTitle("RPA_json运行器")
        self.resize(1120, 760)
        self.setMinimumSize(900, 620)
        self._init_ui()

    def _init_ui(self):
        self._apply_styles()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._build_header(root)

        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.setObjectName("mainSplitter")
        self.main_splitter.setHandleWidth(1)
        self.main_splitter.setChildrenCollapsible(False)
        root.addWidget(self.main_splitter, stretch=1)

        work_area = QWidget()
        work_area.setObjectName("workArea")
        work_layout = QHBoxLayout(work_area)
        work_layout.setContentsMargins(0, 0, 0, 0)
        work_layout.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setObjectName("formScroll")
        self.form_container = QWidget()
        self.form_container.setObjectName("formContainer")
        self.form_layout = QVBoxLayout(self.form_container)
        self.form_layout.setContentsMargins(16, 12, 18, 14)
        self.form_layout.setSpacing(10)
        self.form_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.form_container)
        self.history_panel = self._build_history_panel()
        work_layout.addWidget(self.history_panel)
        work_layout.addWidget(self.scroll, stretch=1)

        work_layout.addWidget(self._build_run_panel())

        self.main_splitter.addWidget(work_area)
        self.main_splitter.addWidget(self._build_log_card())
        self.main_splitter.setSizes([520, 200])

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QWidget {
                font-family: "Microsoft YaHei UI", "Segoe UI", "Microsoft YaHei", Arial;
                color: #1F2937;
                font-size: 13px;
                background: #EEF2F5;
            }
            QWidget#formContainer,
            QWidget#pairRow {
                background: transparent;
            }
            QWidget#advancedBody {
                background: transparent;
            }
            QFrame#headerCard,
            QFrame#sectionCard,
            QFrame#runPanel,
            QFrame#logCard {
                background: #FFFFFF;
                border: 1px solid #D8E0E8;
                border-radius: 8px;
            }
            QLabel#pageTitle {
                font-size: 20px;
                font-weight: 700;
                color: #111827;
                background: transparent;
            }
            QLabel#badge {
                color: #14532D;
                background: #DCFCE7;
                border: 1px solid #BBF7D0;
                border-radius: 5px;
                padding: 3px 9px;
                font-weight: 600;
            }
            QLabel#sectionTitle,
            QLabel#sideTitle,
            QLabel#logTitle {
                color: #111827;
                background: transparent;
                font-weight: 700;
                font-size: 14px;
            }
            QLabel#formChip {
                color: #334155;
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 5px;
                padding: 3px 9px;
                font-weight: 700;
                font-size: 13px;
            }
            QLabel#statusLabel {
                color: #475569;
                background: transparent;
            }
            QLabel#sheetStatusOk {
                color: #166534;
                background: transparent;
            }
            QLabel#sheetStatusWarn {
                color: #B45309;
                background: transparent;
                font-weight: 600;
            }
            QLabel#fieldCaption {
                color: #64748B;
                background: transparent;
                font-weight: 600;
            }
            QLineEdit,
            QComboBox {
                min-height: 30px;
                background: #FFFFFF;
                border: 1px solid #C9D3DD;
                border-radius: 5px;
                padding: 3px 8px;
                selection-background-color: #2563EB;
            }
            QLineEdit:focus,
            QComboBox:focus {
                border: 1px solid #2563EB;
            }
            QPushButton {
                min-height: 30px;
                background: #F8FAFC;
                border: 1px solid #C9D3DD;
                border-radius: 5px;
                padding: 0 14px;
                color: #1F2937;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #EEF2FF;
                border-color: #9DB4D6;
            }
            QPushButton#primaryRunButton {
                min-height: 36px;
                background: #2E7D32;
                color: white;
                border: 1px solid #27672B;
                padding: 0 12px;
                font-weight: 700;
            }
            QPushButton#primaryRunButton:hover {
                background: #256D2A;
            }
            QPushButton#primaryRunButton:disabled {
                background: #9CA3AF;
                border-color: #9CA3AF;
                color: #F3F4F6;
            }
            QPushButton#stopRunButton {
                min-height: 36px;
                background: #DC2626;
                color: white;
                border: 1px solid #B91C1C;
                padding: 0 12px;
                font-weight: 700;
            }
            QPushButton#stopRunButton:hover {
                background: #B91C1C;
            }
            QPushButton#stopRunButton:disabled {
                background: #FCA5A5;
                border-color: #FCA5A5;
                color: #FEF2F2;
            }
            QToolButton#advancedToggle {
                background: transparent;
                border: none;
                color: #2563EB;
                font-weight: 700;
                padding: 0;
            }
            QCheckBox {
                background: transparent;
                color: #334155;
            }
            QProgressBar {
                height: 14px;
                border: 1px solid #C9D3DD;
                border-radius: 4px;
                background: #E5EAF0;
                text-align: center;
                color: #334155;
                font-size: 11px;
            }
            QProgressBar::chunk {
                border-radius: 3px;
                background: #2563EB;
            }
            QTextEdit#logOutput {
                background: #111827;
                color: #D1D5DB;
                border: 1px solid #111827;
                border-radius: 6px;
                font-family: Consolas, "Courier New";
                font-size: 12px;
                padding: 8px;
            }
            QScrollArea#formScroll {
                background: transparent;
                border: none;
            }
            QFrame#headerCard {
                background: #FFFFFF;
                border: none;
                border-bottom: 1px solid #D8E3EC;
                border-radius: 0;
            }
            QLabel#headerIcon {
                background: transparent;
                color: #0B7DDA;
                font-size: 12px;
                font-weight: 800;
                border: 1px solid #BFD8EF;
                border-radius: 5px;
                padding: 4px 6px;
            }
            QWidget#headerTitleBlock {
                background: transparent;
            }
            QLabel#pageTitle {
                font-size: 18px;
                font-weight: 700;
                color: #001B36;
                background: transparent;
            }
            QLabel#badge {
                color: #475569;
                background: transparent;
                border: none;
                padding: 0;
                font-size: 12px;
                font-weight: 500;
            }
            QLineEdit#jsonPathInput {
                min-height: 36px;
                background: #F4F7FA;
                border: 1px solid #D9E2EA;
                border-radius: 6px;
                padding: 0 12px;
                color: #00142A;
            }
            QPushButton#jsonBrowseButton {
                min-height: 36px;
                background: #FFFFFF;
                border: 1px solid #D9E2EA;
                border-radius: 6px;
                color: #00142A;
                font-weight: 600;
            }
            QPushButton#extensionImportButton {
                min-height: 36px;
                background: #E8F4FF;
                border: 1px solid #9CC9EE;
                border-radius: 6px;
                color: #075A9F;
                font-weight: 600;
            }
            QPushButton#extensionImportButton:hover {
                background: #D7ECFC;
            }
            QPushButton#extensionImportButton:disabled {
                background: #F1F5F9;
                border-color: #D9E2EA;
                color: #94A3B8;
            }
            QWidget#workArea,
            QWidget#formContainer {
                background: #EAF4FB;
            }
            QFrame#historyPanel {
                background: #F8FCFF;
                border: none;
                border-right: 1px solid #D6E2EC;
                border-radius: 0;
            }
            QLabel#historyTitle {
                color: #00142A;
                background: transparent;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#historySummary,
            QLabel#historyEmpty {
                color: #64748B;
                background: transparent;
                font-size: 12px;
            }
            QLineEdit#historySearch {
                min-height: 28px;
                background: #FFFFFF;
                border: 1px solid #C7D8E8;
                border-radius: 5px;
                padding: 2px 8px;
                color: #1F2937;
            }
            QLineEdit#historySearch:focus {
                border-color: #0B7DDA;
            }
            QScrollArea#historyScroll {
                background: #F1F7FC;
                border: 1px solid #D4E0EA;
                border-radius: 6px;
            }
            QWidget#historyViewport,
            QWidget#historyList {
                background: #F1F7FC;
            }
            QFrame#historyCard {
                min-height: 122px;
                background: #FFFFFF;
                border: 1px solid #D4E0EA;
                border-radius: 6px;
            }
            QFrame#historyCard:hover {
                background: #F8FCFF;
                border-color: #9DC3E4;
            }
            QFrame#historyCard[active="true"] {
                background: #E7F3FD;
                border-color: #0B7DDA;
            }
            QFrame#historyInfoRow {
                min-height: 24px;
                border-radius: 5px;
            }
            QFrame#historyInfoRow[infoType="name"] {
                color: #0F3D64;
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
            }
            QFrame#historyInfoRow[infoType="name"]:hover {
                background: #DBEAFE;
                border-color: #60A5FA;
            }
            QFrame#historyInfoRow[infoType="name"] QLabel[historyField="true"] {
                color: #0F3D64;
            }
            QFrame#historyInfoRow[infoType="tag"] {
                color: #7C2D12;
                background: #FFF7ED;
                border: 1px solid #FED7AA;
            }
            QFrame#historyInfoRow[infoType="tag"]:hover {
                background: #FFEDD5;
                border-color: #FB923C;
            }
            QFrame#historyInfoRow[infoType="tag"] QLabel[historyField="true"] {
                color: #7C2D12;
            }
            QFrame#historyInfoRow[infoType="tag"][empty="true"] {
                color: #64748B;
                background: #F8FAFC;
                border: 1px dashed #CBD5E1;
            }
            QFrame#historyInfoRow[infoType="tag"][empty="true"]:hover {
                color: #475569;
                background: #F1F5F9;
                border-color: #94A3B8;
            }
            QFrame#historyInfoRow[infoType="tag"][empty="true"] QLabel[historyField="true"] {
                color: #64748B;
            }
            QFrame#historyInfoRow[infoType="code"] {
                color: #075985;
                background: #E0F2FE;
                border: 1px solid #BAE6FD;
            }
            QFrame#historyInfoRow[infoType="code"] QLabel[historyField="true"] {
                color: #075985;
            }
            QLabel[historyField="true"] {
                background: transparent;
                font-weight: 700;
                font-size: 12px;
                line-height: 16px;
            }
            QToolButton[historyEdit="true"] {
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
                background: transparent;
                border: 0;
                border-radius: 5px;
                color: #64748B;
                font-size: 15px;
                font-weight: 700;
                padding: 0;
            }
            QToolButton[historyEdit="true"]:hover {
                background: rgba(255, 255, 255, 170);
                color: #0B7DDA;
            }
            QLabel#historyFile {
                color: #526174;
                background: transparent;
                font-size: 12px;
                line-height: 16px;
            }
            QLabel#historyCount {
                color: #0F5EA8;
                background: #DCEEFF;
                border: 1px solid #B9DDFC;
                border-radius: 8px;
                padding: 1px 7px;
                font-size: 12px;
                font-weight: 700;
            }
            QToolButton#historyDeleteButton {
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                max-height: 24px;
                background: #FFF7F7;
                border: 1px solid #FECACA;
                border-radius: 5px;
                color: #B91C1C;
                font-size: 16px;
                font-weight: 700;
                padding: 0;
            }
            QToolButton#historyDeleteButton:hover {
                background: #FEE2E2;
                border-color: #FCA5A5;
            }
            QFrame#sectionCard {
                background: #F8FCFF;
                border: 1px solid #D4E0EA;
                border-radius: 8px;
            }
            QLabel#sectionTitle {
                color: #00142A;
                font-size: 14px;
                font-weight: 700;
                background: transparent;
            }
            QLabel#fieldLabel {
                color: #526174;
                font-size: 13px;
                font-weight: 700;
                background: #F8FAFC;
                border: 1px solid #D4E0EA;
                border-radius: 5px;
                padding: 3px 10px;
            }
            QWidget#fieldBlock,
            QWidget#pathInputRow,
            QWidget#listParamBody {
                background: transparent;
            }
            QWidget#listParamBox,
            QWidget#keyValueParamBox {
                background: #F5FAFE;
                border: 1px solid #CFE0EE;
                border-radius: 8px;
            }
            QScrollArea#listParamScroll {
                background: #FFFFFF;
                border: 1px solid #D4E0EA;
                border-radius: 6px;
            }
            QWidget#listParamScrollViewport,
            QWidget#listParamListContent {
                background: #FFFFFF;
            }
            QScrollArea#listParamScroll QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 4px 2px 4px 0;
            }
            QScrollArea#listParamScroll QScrollBar::handle:vertical {
                background: #C6D5E2;
                border-radius: 3px;
                min-height: 24px;
            }
            QScrollArea#listParamScroll QScrollBar::add-line:vertical,
            QScrollArea#listParamScroll QScrollBar::sub-line:vertical {
                height: 0;
                border: none;
            }
            QLineEdit#pathInput,
            QLineEdit#paramInput,
            QLineEdit#listParamItem,
            QLineEdit#keyValueParamKey,
            QLineEdit#keyValueParamValue,
            QComboBox {
                min-height: 34px;
                background: #F7FBFE;
                border: 1px solid #D4E0EA;
                border-radius: 6px;
                padding: 0 12px;
                color: #00142A;
            }
            QLineEdit#pathInput:focus,
            QLineEdit#paramInput:focus,
            QLineEdit#listParamItem:focus,
            QLineEdit#keyValueParamKey:focus,
            QLineEdit#keyValueParamValue:focus,
            QComboBox:focus {
                border: 1px solid #0B7DDA;
                background: #FFFFFF;
            }
            QToolButton#browseIconButton,
            QToolButton#listParamRemove {
                background: #F7FBFE;
                border: 1px solid #D4E0EA;
                border-radius: 6px;
                color: #00142A;
                font-weight: 700;
            }
            QToolButton#browseIconButton:hover,
            QToolButton#listParamRemove:hover {
                background: #FFFFFF;
                border-color: #9DC3E4;
            }
            QToolButton#listParamHeader {
                min-height: 34px;
                background: transparent;
                border: none;
                color: #00142A;
                font-weight: 600;
                text-align: left;
                padding: 0 2px;
            }
            QToolButton#advancedToggle {
                background: transparent;
                border: none;
                color: #334155;
                font-weight: 600;
                padding: 0;
            }
            QLabel#listParamPreview {
                color: #64748B;
                background: transparent;
                padding: 0 2px 2px 22px;
            }
            QLabel#keyValueParamSeparator {
                color: #526174;
                background: transparent;
                font-weight: 700;
            }
            QPushButton#listParamAdd {
                min-height: 32px;
                background: #F7FBFE;
                border: 1px solid #D4E0EA;
                border-radius: 6px;
                color: #00142A;
                font-weight: 600;
            }
            QPushButton#listParamAdd:disabled {
                background: #EAF0F5;
                border-color: #D4E0EA;
                color: #8291A0;
            }
            QFrame#runPanel {
                background: #FFFFFF;
                border: none;
                border-left: 2px solid #D6E2EC;
                border-radius: 0;
            }
            QLabel#sideTitle {
                color: #00142A;
                font-size: 14px;
                font-weight: 600;
                background: transparent;
            }
            QLabel#statusPill {
                color: #475569;
                background: #F1F5F9;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QWidget#operationActions {
                background: transparent;
                border: none;
                border-top: 1px solid #D6E2EC;
            }
            QFrame#metricFile,
            QFrame#metricSheet,
            QFrame#metricParam {
                background: #EEF2F5;
                border: none;
                border-radius: 7px;
                min-height: 70px;
            }
            QLabel#metricFileValue,
            QLabel#metricSheetValue,
            QLabel#metricParamValue {
                color: #00142A;
                background: transparent;
                font-size: 26px;
                font-weight: 800;
            }
            QLabel#metricLabel,
            QLabel#optionLabel,
            QLabel#progressPercent {
                color: #526174;
                background: transparent;
                font-weight: 500;
            }
            QProgressBar {
                height: 8px;
                border: none;
                border-radius: 4px;
                background: #BFE1FA;
            }
            QProgressBar::chunk {
                border-radius: 4px;
                background: #0B7DDA;
            }
            QPushButton#saveConfigButton {
                min-height: 34px;
                background: #F3F9FE;
                border: 1px solid #D4E0EA;
                border-radius: 6px;
                color: #00142A;
                font-weight: 600;
            }
            QPushButton#primaryRunButton {
                min-height: 36px;
                background: #087AD8;
                color: #FFFFFF;
                border: 1px solid #087AD8;
                border-radius: 6px;
                font-weight: 700;
            }
            QPushButton#primaryRunButton:hover {
                background: #066FC6;
            }
            QPushButton#primaryRunButton:disabled {
                background: #9CCCF2;
                border-color: #9CCCF2;
            }
            QPushButton#stopRunButton {
                min-height: 36px;
                background: #F1999F;
                color: #FFFFFF;
                border: 1px solid #F1999F;
                border-radius: 6px;
                font-weight: 700;
            }
            QPushButton#stopRunButton:hover {
                background: #E78189;
            }
            QPushButton#stopRunButton:disabled {
                background: #F4C4C8;
                border-color: #F4C4C8;
            }
            QFrame#logCard {
                background: #070B10;
                border: none;
                border-radius: 0;
            }
            QLabel#logTitle {
                color: #F8FAFC;
                background: transparent;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#logCount {
                color: #94A3B8;
                background: transparent;
                font-size: 12px;
            }
            QTextEdit#logOutput {
                background: #070B10;
                color: #D8E2EE;
                border: none;
                border-radius: 0;
                font-family: "Cascadia Mono", Consolas, "Courier New";
                font-size: 12px;
                padding: 12px 14px;
            }
            QSplitter#mainSplitter::handle {
                background: #D6E2EC;
            }
            """
        )

    def _build_header(self, root):
        header = QFrame()
        header.setObjectName("headerCard")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 10, 18, 10)
        header_layout.setSpacing(12)
        header.setFixedHeight(72)

        icon_label = QLabel()
        icon_label.setObjectName("headerIcon")
        icon_label.setText("CRPA")
        header_layout.addWidget(icon_label)

        title_block = QWidget()
        title_block.setObjectName("headerTitleBlock")
        title_layout = QVBoxLayout(title_block)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        self.workflow_name_label = QLabel("未加载 JSON")
        self.workflow_name_label.setObjectName("pageTitle")
        self.workflow_name_label.setMinimumWidth(150)
        self.crpa_label = QLabel("CRPA: 未填写")
        self.crpa_label.setObjectName("badge")
        title_layout.addWidget(self.workflow_name_label)
        title_layout.addWidget(self.crpa_label)

        self.json_path_input = QLineEdit()
        self.json_path_input.setObjectName("jsonPathInput")
        self.json_path_input.setPlaceholderText("选择工作流 JSON")
        btn_browse = QPushButton("选择 JSON")
        btn_browse.setObjectName("jsonBrowseButton")
        btn_browse.setFixedWidth(102)
        btn_browse.clicked.connect(self.browse_json)
        header_layout.addWidget(title_block)
        header_layout.addWidget(self.json_path_input, stretch=1)
        header_layout.addWidget(btn_browse)

        root.addWidget(header)

    def _history_path_key(self, path):
        try:
            return os.path.normcase(os.path.abspath(str(path)))
        except Exception:
            return str(path).casefold()

    def _build_history_panel(self):
        panel = QFrame()
        panel.setObjectName("historyPanel")
        panel.setFixedWidth(220)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        title = QLabel("JSON 历史")
        title.setObjectName("historyTitle")
        self.history_summary_label = QLabel("0 个")
        self.history_summary_label.setObjectName("historySummary")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.history_summary_label)
        layout.addLayout(title_row)

        self.history_search_input = QLineEdit()
        self.history_search_input.setObjectName("historySearch")
        self.history_search_input.setPlaceholderText("搜索名称、标签或 CRPA 代码")
        self.history_search_input.textChanged.connect(self._refresh_history_panel)
        layout.addWidget(self.history_search_input)

        self.history_scroll = QScrollArea()
        self.history_scroll.setObjectName("historyScroll")
        self.history_scroll.viewport().setObjectName("historyViewport")
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.history_scroll.setFrameShape(QFrame.NoFrame)

        self.history_list = QWidget()
        self.history_list.setObjectName("historyList")
        self.history_list.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.history_list.setMinimumWidth(0)
        self.history_list_layout = QVBoxLayout(self.history_list)
        self.history_list_layout.setContentsMargins(4, 4, 4, 4)
        self.history_list_layout.setSpacing(6)
        self.history_list_layout.setAlignment(Qt.AlignTop)
        self.history_scroll.setWidget(self.history_list)
        layout.addWidget(self.history_scroll, stretch=1)

        self._refresh_history_panel()
        return panel

    def _refresh_history_panel(self):
        if not hasattr(self, "history_list_layout"):
            return
        while self.history_list_layout.count():
            item = self.history_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        history = get_json_history()
        query = self.history_search_input.text().strip().casefold()
        rows = []
        for item in history:
            values = self._history_card_values(item)
            searchable = " ".join(
                [values["name"], values["tag"], values["code"]]
            ).casefold()
            if query and query not in searchable:
                continue
            rows.append((item, values))
        self.history_summary_label.setText(
            f"{len(rows)} / {len(history)}" if query else f"{len(history)} 个"
        )
        if not history:
            empty = QLabel("暂无打开记录")
            empty.setObjectName("historyEmpty")
            empty.setWordWrap(True)
            self.history_list_layout.addWidget(empty)
            return
        if not rows:
            empty = QLabel("没有匹配的历史记录")
            empty.setObjectName("historyEmpty")
            empty.setWordWrap(True)
            self.history_list_layout.addWidget(empty)
            return

        for item, values in rows:
            self.history_list_layout.addWidget(self._make_history_row(item, values))

    def _history_crpa_meta(self, path):
        try:
            normalized = os.path.normcase(os.path.abspath(str(path)))
            modified = os.path.getmtime(path)
        except OSError:
            return "", ""
        cache_key = (normalized, modified)
        if cache_key in self._history_meta_cache:
            return self._history_meta_cache[cache_key]
        try:
            workflow = load_workflow_json(path)
            crpa = workflow.get("crpa") or {}
            code = str(crpa.get("code") or "").strip()
            name = str(crpa.get("name") or workflow.get("workflow_name") or "").strip()
        except Exception:
            code, name = "", ""
        self._history_meta_cache[cache_key] = (code, name)
        return code, name

    def _history_card_values(self, item):
        path = str(item.get("path") or "")
        file_name = os.path.basename(path) or path
        crpa_code = str(item.get("crpa_code") or "").strip()
        crpa_name = str(item.get("crpa_name") or "").strip()
        if (not crpa_code or not crpa_name) and path and Path(path).exists():
            code_from_file, name_from_file = self._history_crpa_meta(path)
            crpa_code = crpa_code or code_from_file
            crpa_name = crpa_name or name_from_file
        display_name = str(item.get("display_name") or "").strip()
        display_name = display_name or crpa_name or Path(path).stem or "未命名 JSON"
        tag = str(item.get("tag") or "").strip()
        return {
            "path": path,
            "file_name": file_name,
            "code": crpa_code,
            "name": display_name,
            "tag": tag,
        }

    def _make_history_row(self, item, values=None):
        values = values or self._history_card_values(item)
        path = values["path"]
        file_name = values["file_name"]
        crpa_code = values["code"]
        crpa_name = values["name"]
        tag = values["tag"]
        try:
            count = int(item.get("open_count") or 0)
        except (TypeError, ValueError):
            count = 0
        active = bool(self.workflow_path) and self._history_path_key(path) == self._history_path_key(self.workflow_path)

        row = HistoryItemCard(path, self._load_history_json)
        row.setObjectName("historyCard")
        row.setProperty("active", active)
        row.setToolTip(path)
        row.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.setMinimumWidth(0)
        row.setMinimumHeight(122)
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(7, 7, 7, 7)
        row_layout.setSpacing(4)

        name_row, name_widget, name_edit = self._make_history_info_row(
            "name", f"名称：{crpa_name}", "编辑名称"
        )
        name_widget.setObjectName("historyName")
        name_edit.clicked.connect(
            lambda _=False, json_path=path, current_name=crpa_name: self._edit_history_name(
                json_path, current_name
            )
        )

        tag_row, tag_widget, tag_edit = self._make_history_info_row(
            "tag", f"标签：{tag}" if tag else "标签：未添加", "编辑标签", empty=not bool(tag)
        )
        tag_widget.setObjectName("historyTag")
        tag_edit.clicked.connect(
            lambda _=False, json_path=path, current_tag=tag: self._edit_history_tag(
                json_path, current_tag
            )
        )

        code_row, code_widget, _ = self._make_history_info_row(
            "code", f"CRPA 代码：{crpa_code or '未填写'}"
        )
        code_widget.setObjectName("historyCode")
        code_widget.setToolTip(f"CRPA 代码：{crpa_code or '未填写'}")

        file_widget = QLabel(file_name)
        file_widget.setObjectName("historyFile")
        file_widget.setToolTip(f"JSON：{path}")
        file_widget.setWordWrap(True)
        file_widget.setMinimumWidth(0)
        file_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)
        count_widget = QLabel(f"{count} 次")
        count_widget.setObjectName("historyCount")
        count_widget.setToolTip(f"运行 {count} 次")
        count_widget.setAlignment(Qt.AlignCenter)
        count_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        delete_button = QToolButton()
        delete_button.setObjectName("historyDeleteButton")
        delete_button.setText("×")
        delete_button.setToolTip("删除这条历史记录")
        delete_button.setFixedSize(24, 24)
        delete_button.clicked.connect(lambda _=False, json_path=path: self._delete_history_item(json_path))

        action_row.addWidget(file_widget, stretch=1)
        action_row.addWidget(count_widget)
        action_row.addWidget(delete_button)

        row_layout.addWidget(name_row)
        row_layout.addWidget(tag_row)
        row_layout.addWidget(code_row)
        row_layout.addLayout(action_row)
        return row

    @staticmethod
    def _make_history_info_row(info_type, text, edit_tooltip="", empty=False):
        info_row = QFrame()
        info_row.setObjectName("historyInfoRow")
        info_row.setProperty("infoType", info_type)
        info_row.setProperty("empty", empty)
        info_row.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(info_row)
        layout.setContentsMargins(7, 1, 2, 1)
        layout.setSpacing(4)

        field = QLabel(text)
        field.setProperty("historyField", True)
        field.setCursor(Qt.PointingHandCursor)
        field.setMinimumWidth(0)
        field.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        field.setWordWrap(True)
        layout.addWidget(field, stretch=1)

        edit_button = None
        if edit_tooltip:
            edit_button = QToolButton()
            edit_button.setObjectName(f"historyEdit{info_type.title()}")
            edit_button.setProperty("historyEdit", True)
            edit_button.setText("\u270e")
            edit_button.setToolTip(edit_tooltip)
            edit_button.setFixedSize(20, 20)
            edit_button.setCursor(Qt.PointingHandCursor)
            layout.addWidget(edit_button)
        return info_row, field, edit_button

    def _load_history_json(self, path):
        if self._pending_history_path == path:
            return
        if self.workflow_path and self._history_path_key(path) == self._history_path_key(self.workflow_path):
            return
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "文件不存在", "这个 JSON 文件已不存在。")
            self._refresh_history_panel()
            return
        self._pending_history_path = path
        QTimer.singleShot(0, lambda json_path=path: self._load_history_json_deferred(json_path))

    def _load_history_json_deferred(self, path):
        try:
            self.load_json(path)
        finally:
            self._pending_history_path = None

    def _edit_history_tag(self, path, current_tag):
        tag, ok = QInputDialog.getText(self, "编辑标签", "标签名称", text=current_tag)
        if not ok:
            return
        set_json_history_tag(path, tag)
        self._refresh_history_panel()

    def _edit_history_name(self, path, current_name):
        name, ok = QInputDialog.getText(self, "编辑名称", "显示名称", text=current_name)
        if not ok:
            return
        set_json_history_name(path, name)
        self._refresh_history_panel()

    def _delete_history_item(self, path):
        remove_json_history_item(path)
        self._refresh_history_panel()

    def _build_run_panel(self):
        panel = QFrame()
        panel.setObjectName("runPanel")
        panel.setFixedWidth(270)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("操作区")
        title.setObjectName("sideTitle")
        self.status_label = QLabel("未加载")
        self.status_label.setObjectName("statusPill")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(0)
        layout.addWidget(title)
        layout.addWidget(self.status_label)

        writeback_row = QHBoxLayout()
        writeback_row.setContentsMargins(0, 0, 0, 0)
        writeback_row.setSpacing(8)
        writeback_label = QLabel("运行前写回 JSON")
        writeback_label.setObjectName("optionLabel")
        self.writeback_check = SwitchCheckBox(show_state_text=True)
        self.writeback_check.setChecked(True)
        writeback_row.addWidget(writeback_label)
        writeback_row.addStretch(1)
        writeback_row.addWidget(self.writeback_check)
        layout.addLayout(writeback_row)

        progress_header = QHBoxLayout()
        progress_header.setContentsMargins(0, 0, 0, 0)
        progress_label = QLabel("进度")
        progress_label.setObjectName("fieldCaption")
        self.progress_percent_label = QLabel("0%")
        self.progress_percent_label.setObjectName("progressPercent")
        progress_header.addWidget(progress_label)
        progress_header.addStretch(1)
        progress_header.addWidget(self.progress_percent_label)
        layout.addLayout(progress_header)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        layout.addStretch(1)

        actions = QWidget()
        actions.setObjectName("operationActions")
        actions_layout = QVBoxLayout(actions)
        actions_layout.setContentsMargins(0, 12, 0, 0)
        actions_layout.setSpacing(8)

        extension_caption = QLabel("扩展包")
        extension_caption.setObjectName("fieldCaption")
        actions_layout.addWidget(extension_caption)
        self.btn_import_extension = QPushButton("导入扩展包")
        self.btn_import_extension.setObjectName("extensionImportButton")
        self.btn_import_extension.setToolTip("导入 ZIP 并自动合并到当前扩展环境")
        self.btn_import_extension.clicked.connect(self.import_extension_archive)
        actions_layout.addWidget(self.btn_import_extension)

        self.btn_save_config = QPushButton("保存当前配置")
        self.btn_save_config.setObjectName("saveConfigButton")
        self.btn_save_config.setEnabled(False)
        self.btn_save_config.clicked.connect(self.save_current_config)
        actions_layout.addWidget(self.btn_save_config)

        self.btn_run = QPushButton("运行")
        self.btn_run.setObjectName("primaryRunButton")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self.run_workflow)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setObjectName("stopRunButton")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_workflow)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        action_row.addWidget(self.btn_run, stretch=1)
        action_row.addWidget(self.btn_stop, stretch=1)
        actions_layout.addLayout(action_row)

        layout.addWidget(actions)

        return panel

    def _build_log_card(self):
        log_card = QFrame()
        log_card.setObjectName("logCard")
        layout = QVBoxLayout(log_card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title = QLabel("运行日志")
        title.setObjectName("logTitle")
        self.log_count = 0
        self.log_count_label = QLabel("0 条记录")
        self.log_count_label.setObjectName("logCount")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.log_count_label)
        layout.addLayout(title_row)

        self.log_output = QTextEdit()
        self.log_output.setObjectName("logOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(170)
        layout.addWidget(self.log_output, stretch=1)
        return log_card

    def log(self, text):
        self.log_count += 1
        self.log_count_label.setText(f"{self.log_count} 条记录")
        self.log_output.append(str(text))

    def browse_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择工作流 JSON", "", "JSON (*.json)")
        if path:
            self.load_json(path)

    def import_extension_archive(self):
        if self.engine is not None:
            QMessageBox.warning(self, "正在运行", "请等待当前工作流结束后再导入扩展包。")
            return
        if self._extension_import_thread is not None:
            return

        path, _ = QFileDialog.getOpenFileName(self, "导入扩展包", "", "扩展包 (*.zip)")
        if not path:
            return

        thread = ExtensionArchiveImportThread(path, self)
        thread.finished.connect(self._on_extension_import_thread_finished)
        self._extension_import_thread = thread
        self.btn_import_extension.setEnabled(False)
        self.status_label.setText("正在导入扩展包")
        self.log(f"[扩展] 正在导入并自动合并：{os.path.basename(path)}")
        thread.start()

    def _on_extension_import_thread_finished(self):
        thread = self._extension_import_thread
        self._extension_import_thread = None
        if thread is None:
            return
        thread.deleteLater()

        if thread.error:
            self.btn_import_extension.setEnabled(True)
            self.status_label.setText("扩展导入失败")
            self.log(f"[扩展] 导入扩展包失败：{thread.error}")
            if thread.error_trace:
                self.log(thread.error_trace)
            QMessageBox.warning(self, "导入扩展包失败", thread.error)
            return

        result = thread.result or {}
        added = ", ".join(result.get("added_distributions") or [])
        updated = ", ".join(
            "{} {} -> {}".format(
                item["name"], item["current_version"], item["incoming_version"]
            )
            for item in result.get("updated_distributions") or []
        )
        details = "；".join(
            item
            for item in (
                f"新增 {added}" if added else "",
                f"更新 {updated}" if updated else "",
            )
            if item
        )
        action = "创建当前扩展环境" if result.get("created_initial_environment") else "合并到当前扩展环境"
        message = f"已导入扩展包并{action}"
        if details:
            message = f"{message}：{details}"
        self.status_label.setText("扩展已导入，正在重启")
        self.log(f"[扩展] {message}。导入完成，正在重启运行器。")
        self._restart_after_extension_import()

    def _restart_after_extension_import(self):
        if getattr(sys, "frozen", False):
            program = sys.executable
            arguments = list(sys.argv[1:])
        else:
            program = sys.executable
            arguments = [str(Path(__file__).with_name("main.py")), *sys.argv[1:]]

        started = QProcess.startDetached(program, arguments, os.getcwd())
        if isinstance(started, tuple):
            started = started[0]
        if started:
            QTimer.singleShot(0, QApplication.instance().quit)
            return

        activate_external_extensions()
        self.btn_import_extension.setEnabled(True)
        self.status_label.setText("扩展已导入，重启失败")
        message = "扩展已导入，但无法自动重启运行器；新代码块已可使用扩展库。"
        self.log(f"[扩展] {message}")
        QMessageBox.warning(self, "重启运行器失败", message)

    def load_json(self, path):
        try:
            workflow = load_workflow_json(path)
        except Exception as exc:
            QMessageBox.critical(self, "加载失败", str(exc))
            return
        self.workflow_path = path
        self.workflow = workflow
        set_last_workflow_path(path)
        self.json_path_input.setText(path)
        crpa = workflow.get("crpa") or {}
        self.crpa_code = str(crpa.get("code") or "")
        self.name = str(crpa.get("name") or workflow.get("workflow_name") or "")
        record_json_load(path, self.crpa_code, self.name)
        self.workflow_name_label.setText(self.name or "未命名")
        self.crpa_label.setText(f"CRPA: {self.crpa_code or '未填写'}")
        self._build_dynamic_form()
        self.btn_save_config.setEnabled(True)
        self.btn_run.setEnabled(True)
        self.status_label.setText("就绪")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress_percent_label.setText("0%")
        self.log_output.clear()
        self.log_count = 0
        self.log_count_label.setText("0 条记录")
        self.log(f"[加载] {os.path.basename(path)}")
        self._refresh_history_panel()

    def _clear_form(self):
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.file_inputs.clear()
        self.sheet_combos.clear()
        self.param_inputs.clear()
        self.sheet_sources = []
        self.advanced_sheet_card = None
        self.advanced_sheet_body = None
        self.advanced_sheet_toggle = None
        self.sheet_status_label = None

    def _make_card(self, title):
        card = QFrame()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        layout.addWidget(label)
        return card, layout

    def _make_field_label(self, text, required=False):
        suffix = " *" if required else ""
        label = QLabel(f"{text or ''}{suffix}")
        label.setObjectName("fieldLabel")
        label.setAlignment(Qt.AlignCenter)
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return label

    def _add_field_block(self, layout, label_text, widget, required=False):
        block = QWidget()
        block.setObjectName("fieldBlock")
        block_layout = QHBoxLayout(block)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(10)
        widget.setSizePolicy(QSizePolicy.Expanding, widget.sizePolicy().verticalPolicy())
        block_layout.addWidget(self._make_field_label(label_text, required), alignment=Qt.AlignVCenter)
        block_layout.addWidget(widget, stretch=1)
        layout.addWidget(block)
        return block

    def _make_browse_button(self, tooltip="浏览"):
        button = QToolButton()
        button.setObjectName("browseIconButton")
        button.setText(tooltip)
        button.setToolTip(tooltip)
        button.setFixedSize(70, 34)
        return button

    def _create_file_card(self, file_resources):
        if not file_resources:
            return None
        file_card, file_layout = self._make_card(f"文件资源 ({len(file_resources)})")
        for resource in file_resources:
            key = resource.get("key")
            row = QWidget()
            row.setObjectName("pathInputRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            line = QLineEdit(resource.get("path", ""))
            line.setObjectName("pathInput")
            line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn = self._make_browse_button("保存到" if resource.get("role") == "output" else "浏览")
            btn.clicked.connect(lambda _=False, r=resource, l=line: self._browse_resource(r, l))
            row_layout.addWidget(line, stretch=1)
            row_layout.addWidget(btn)
            self.file_inputs[key] = line
            self._add_field_block(
                file_layout,
                resource.get("label") or key,
                row,
                bool(resource.get("required")),
            )
        return file_card

    def _create_sheet_card(self, file_resources, contexts):
        sheet_rows = []
        for resource in file_resources:
            key = resource.get("key")
            if resource.get("type") != "excel":
                continue
            for source in contexts.get(key, []):
                sheet_rows.append((key, source))
        self.sheet_sources = sheet_rows
        if not sheet_rows:
            return None

        card = QFrame()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel(f"高级设置 - 工作表映射 ({len(sheet_rows)})")
        title.setObjectName("sectionTitle")
        self.sheet_status_label = QLabel(f"工作表已按模板预设 {len(sheet_rows)} 个")
        self.sheet_status_label.setObjectName("sheetStatusOk")
        self.advanced_sheet_toggle = QToolButton()
        self.advanced_sheet_toggle.setObjectName("advancedToggle")
        self.advanced_sheet_toggle.setCheckable(True)
        self.advanced_sheet_toggle.setChecked(False)
        self.advanced_sheet_toggle.setText("展开工作表映射")
        self.advanced_sheet_toggle.toggled.connect(self._set_sheet_mapping_visible)
        header.addWidget(title)
        header.addWidget(self.sheet_status_label, stretch=1)
        header.addWidget(self.advanced_sheet_toggle)
        layout.addLayout(header)

        self.advanced_sheet_body = QWidget()
        self.advanced_sheet_body.setObjectName("advancedBody")
        body_layout = QVBoxLayout(self.advanced_sheet_body)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(8)
        for file_key, source in sheet_rows:
            combo = QComboBox()
            combo.setEditable(True)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            combo.setProperty("file_key", file_key)
            combo.setProperty("source_key", source.get("key"))
            combo.setCurrentText(str(source.get("sheet") or ""))
            combo.currentTextChanged.connect(self._update_sheet_status)
            self.sheet_combos[source.get("key")] = combo
            self._add_field_block(body_layout, source.get("label") or source.get("key"), combo, False)
        layout.addWidget(self.advanced_sheet_body)
        self.advanced_sheet_body.hide()
        self.advanced_sheet_card = card
        return card

    def _create_param_card(self, parameters, parameter_layout=None):
        if not parameters:
            return None
        param_card, param_layout = self._make_card(f"运行参数 ({len(parameters)})")
        parameters_by_key = {
            str(param.get("key") or "").strip(): param
            for param in parameters
            if str(param.get("key") or "").strip()
        }
        rendered_keys = set()

        def add_parameter(layout, param, horizontal=False):
            key = str(param.get("key") or "").strip()
            if not key or key in rendered_keys:
                return
            widget = self._make_param_widget(param)
            self.param_inputs[key] = widget
            rendered_keys.add(key)
            if horizontal:
                field = QWidget()
                field_layout = QVBoxLayout(field)
                field_layout.setContentsMargins(0, 0, 0, 0)
                field_layout.setSpacing(5)
                field_layout.addWidget(
                    self._make_field_label(
                        param.get("label") or key,
                        bool(param.get("required", True)),
                    )
                )
                field_layout.addWidget(widget)
                layout.addWidget(field, stretch=1)
                return
            if str(param.get("type", "")).lower() in {"list", "array", "key_value", "object", "map"}:
                layout.addWidget(widget)
            else:
                self._add_field_block(
                    layout,
                    param.get("label") or param.get("key"),
                    widget,
                    bool(param.get("required", True)),
                )

        for node in parameter_layout or []:
            if not isinstance(node, dict):
                continue
            if node.get("kind") != "container":
                key = str(node.get("fieldName") or "").strip()
                if key in parameters_by_key:
                    add_parameter(param_layout, parameters_by_key[key])
                continue
            children = [
                parameters_by_key[str(child.get("fieldName") or "").strip()]
                for child in node.get("children") or []
                if isinstance(child, dict)
                and str(child.get("fieldName") or "").strip() in parameters_by_key
            ]
            if not children:
                continue
            compact_types = {"text", "password", "number", "date", "bool", "select"}
            horizontal = all(str(item.get("type") or "text").lower() in compact_types for item in children)
            group = QGroupBox(str(node.get("title") or "参数组"))
            group.setObjectName("paramHorizontalGroup")
            group_layout = QHBoxLayout(group) if horizontal else QVBoxLayout(group)
            group_layout.setContentsMargins(12, 10, 12, 10)
            group_layout.setSpacing(10)
            for child in children:
                add_parameter(group_layout, child, horizontal=horizontal)
            param_layout.addWidget(group)

        for param in parameters:
            add_parameter(param_layout, param)
        return param_card

    def _build_dynamic_form(self):
        self._clear_form()
        manifest = self.workflow.get("run_manifest") or {}
        contexts = collect_file_contexts(self.workflow)
        file_resources = manifest.get("file_resources", []) or []
        parameters = manifest.get("parameters", []) or []
        data_sources = manifest.get("data_sources", []) or []

        file_card = self._create_file_card(file_resources)
        sheet_card = self._create_sheet_card(file_resources, contexts)
        param_card = self._create_param_card(parameters, manifest.get("parameter_layout") or [])

        if file_card:
            self.form_layout.addWidget(file_card)

        if param_card:
            self.form_layout.addWidget(param_card)
        if sheet_card:
            self.form_layout.addWidget(sheet_card)

        if self.sheet_combos:
            self._refresh_all_sheet_combos()
            self._update_sheet_status()

    def _set_sheet_mapping_visible(self, visible):
        if self.advanced_sheet_body is not None:
            self.advanced_sheet_body.setVisible(visible)
        if self.advanced_sheet_toggle is not None:
            self.advanced_sheet_toggle.setText("收起工作表映射" if visible else "展开工作表映射")

    def _show_sheet_mapping(self):
        if self.advanced_sheet_toggle is not None:
            self.advanced_sheet_toggle.setChecked(True)
        elif self.advanced_sheet_body is not None:
            self.advanced_sheet_body.show()

    def _load_sheet_names_cached(self, path):
        if not path or not os.path.exists(path):
            return []
        try:
            normalized = os.path.normcase(os.path.abspath(str(path)))
            modified = os.path.getmtime(path)
        except OSError:
            return []
        cache_key = (normalized, modified)
        if cache_key not in self._sheet_name_cache:
            for key in list(self._sheet_name_cache):
                if key[0] == normalized and key != cache_key:
                    self._sheet_name_cache.pop(key, None)
            self._sheet_name_cache[cache_key] = load_excel_sheet_names(path)
        return self._sheet_name_cache[cache_key]

    def _sheet_validation_issues(self):
        issues = []
        for combo in self.sheet_combos.values():
            sheet = combo.currentText().strip()
            file_key = combo.property("file_key")
            source_key = combo.property("source_key")
            line = self.file_inputs.get(file_key)
            path = line.text().strip() if line is not None else ""
            if not path or not os.path.exists(path):
                continue
            sheets = self._load_sheet_names_cached(path)
            if sheet and sheets and sheet not in sheets:
                issues.append(f"{source_key}: {sheet}")
        return issues

    def _update_sheet_status(self):
        if self.sheet_status_label is None:
            return
        issues = self._sheet_validation_issues()
        if issues:
            self.sheet_status_label.setObjectName("sheetStatusWarn")
            self.sheet_status_label.setText("部分预设工作表未找到，请展开修正")
            self.sheet_status_label.style().unpolish(self.sheet_status_label)
            self.sheet_status_label.style().polish(self.sheet_status_label)
            self._show_sheet_mapping()
            self.status_label.setText("工作表需要确认")
        else:
            count = len(self.sheet_combos)
            self.sheet_status_label.setObjectName("sheetStatusOk")
            self.sheet_status_label.setText(f"工作表已按模板预设 {count} 个")
            self.sheet_status_label.style().unpolish(self.sheet_status_label)
            self.sheet_status_label.style().polish(self.sheet_status_label)

    def _make_param_widget(self, param):
        param_type = str(param.get("type", "text")).lower()
        default = param.get("default", "")
        hint = str(param.get("tip") or "").strip()
        if param_type == "bool":
            widget = SwitchCheckBox(show_state_text=True)
            widget.setChecked(str(default).lower() in {"1", "true", "yes", "是"})
            if hint:
                widget.setToolTip(hint)
            return widget
        if param_type in {"select", "choice", "dropdown", "enum"} or param.get("options"):
            widget = QComboBox()
            widget.setObjectName("paramInput")
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            options = normalize_select_options(param.get("options"))
            default_text = str(default or "").strip()
            if default_text and default_text not in options:
                options.insert(0, default_text)
            widget.addItems(options)
            if default_text:
                widget.setCurrentText(default_text)
            elif widget.count() > 0:
                widget.setCurrentIndex(0)
            if hint:
                setter = getattr(widget, "setPlaceholderText", None)
                if callable(setter) and not default_text:
                    setter(hint)
                widget.setToolTip(hint)
            return widget
        if param_type in {"list", "array"}:
            return self._make_list_param_widget(param)
        if param_type in {"key_value", "object", "map"}:
            return self._make_key_value_param_widget(param)
        if param_type in {"file", "folder"}:
            row = QWidget()
            row.setObjectName("pathInputRow")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            line = QLineEdit(str(default))
            line.setObjectName("pathInput")
            line.setProperty("path_value", True)
            line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            line.setPlaceholderText(
                hint or ("选择或输入文件路径" if param_type == "file" else "选择或输入文件夹路径")
            )
            if hint:
                line.setToolTip(hint)
            btn = self._make_browse_button("浏览")
            btn.clicked.connect(lambda _=False, p=param, l=line: self._browse_parameter_path(p, l))
            row.setProperty("param_type", param_type)
            if hint:
                row.setToolTip(hint)
            layout.addWidget(line, stretch=1)
            layout.addWidget(btn)
            return row
        widget = QLineEdit(str(default))
        widget.setObjectName("paramInput")
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if param_type == "password":
            widget.setEchoMode(QLineEdit.Password)
            widget.setPlaceholderText("请输入密码")
        if hint:
            widget.setPlaceholderText(hint)
            widget.setToolTip(hint)
        if param_type == "number":
            widget.setPlaceholderText("数字")
        elif param_type == "date":
            widget.setPlaceholderText("YYYY-MM-DD")
        return widget

    @staticmethod
    def _redact_crpa_payload(payload):
        """Hide saved password values in the diagnostic payload without changing execution data."""

        redacted = dict(payload or {})
        manifest = dict(redacted.get("manifest") or {})
        parameters = dict(redacted.get("parameters") or {})
        manifest_parameters = []
        password_keys = set()
        for item in manifest.get("parameters") or []:
            copied = dict(item)
            if str(copied.get("type") or "").casefold() == "password":
                key = str(copied.get("key") or "").strip()
                if key:
                    password_keys.add(key)
                copied["default"] = "******"
            manifest_parameters.append(copied)
        for key in password_keys:
            if key in parameters:
                parameters[key] = "******"
        manifest["parameters"] = manifest_parameters
        redacted["manifest"] = manifest
        redacted["parameters"] = parameters
        return redacted

    @staticmethod
    def _parse_list_default(default):
        if isinstance(default, list):
            return ["" if item is None else str(item) for item in default]
        text = str(default or "").strip()
        if not text:
            return [""]
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return ["" if item is None else str(item) for item in parsed]
        except Exception:
            pass
        return [
            part.strip()
            for part in text.replace("，", ",").replace("；", ";").replace(";", ",").split(",")
            if part.strip()
        ] or [""]

    def _make_list_param_widget(self, param):
        widget = CollapsibleListParam(
            param.get("label") or param.get("key"),
            self._parse_list_default(param.get("default", "")),
            bool(param.get("required", True)),
            param.get("initial_count"),
            param.get("max_items"),
        )
        if param.get("tip"):
            widget.setToolTip(str(param.get("tip")))
        return widget

    @staticmethod
    def _parse_key_value_default(default):
        if isinstance(default, dict):
            return list(default.items())
        text = str(default or "").strip()
        if not text:
            return [("", "")]
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return list(parsed.items())
        except Exception:
            pass
        pairs = []
        for line in text.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                pairs.append((key.strip(), value))
        return pairs or [("", "")]

    def _make_key_value_param_widget(self, param):
        widget = CollapsibleKeyValueParam(
            param.get("label") or param.get("key"),
            self._parse_key_value_default(param.get("default", "")),
            bool(param.get("required", True)),
            param.get("initial_count"),
            param.get("max_items"),
        )
        if param.get("tip"):
            widget.setToolTip(str(param.get("tip")))
        return widget

    @staticmethod
    def _path_start_dir(text):
        path = Path(str(text or "").strip())
        if path.is_dir():
            return str(path)
        if str(path) and path.parent and str(path.parent) != ".":
            return str(path.parent)
        return ""

    def _browse_parameter_path(self, param, line):
        current = line.text().strip()
        if str(param.get("type", "")).lower() == "folder":
            path = QFileDialog.getExistingDirectory(
                self,
                f"选择{param.get('label') or '文件夹'}",
                current or self._path_start_dir(current),
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                f"选择{param.get('label') or '文件'}",
                self._path_start_dir(current),
                file_dialog_filter(param),
            )
        if path:
            line.setText(path)

    def _browse_resource(self, resource, line):
        start_dir = str(Path(line.text()).parent) if line.text() else ""
        if resource.get("role") == "output":
            default_name = line.text() or resource.get("path") or "output.xlsx"
            path, _ = QFileDialog.getSaveFileName(
                self,
                f"保存{resource.get('label') or '文件'}",
                default_name,
                file_dialog_filter(resource),
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                f"选择{resource.get('label') or '文件'}",
                start_dir,
                file_dialog_filter(resource),
            )
        if path:
            line.setText(path)
            self._refresh_sheet_combos_for_file(resource.get("key"), path)
            self._update_sheet_status()

    def _refresh_all_sheet_combos(self):
        for key, line in self.file_inputs.items():
            self._refresh_sheet_combos_for_file(key, line.text().strip())

    def _refresh_sheet_combos_for_file(self, file_key, path):
        sheets = self._load_sheet_names_cached(path)
        for combo in self.sheet_combos.values():
            if combo.property("file_key") != file_key:
                continue
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            if sheets:
                combo.addItems(sheets)
            if current:
                combo.setCurrentText(current)
            combo.blockSignals(False)

    def _collect_file_paths(self):
        return {key: line.text().strip() for key, line in self.file_inputs.items()}

    def _collect_data_sources(self):
        data = {}
        for key, combo in self.sheet_combos.items():
            data[key] = {"sheet": combo.currentText().strip()}
        return data

    def _collect_parameters(self):
        params = {}
        for key, widget in self.param_inputs.items():
            if isinstance(widget, QCheckBox):
                params[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                params[key] = widget.currentText().strip()
            else:
                if isinstance(widget, QWidget) and widget.property("param_type") == "list":
                    params[key] = [
                        line.text().strip()
                        for line in widget.findChildren(QLineEdit, "listParamItem")
                        if line.text().strip()
                    ]
                    continue
                if isinstance(widget, QWidget) and widget.property("param_type") == "key_value":
                    params[key] = widget.value()
                    continue
                line = widget.findChild(QLineEdit) if isinstance(widget, QWidget) else None
                if line and line.property("path_value"):
                    params[key] = line.text().strip()
                else:
                    params[key] = widget.text().strip()
        return params

    @staticmethod
    def _matches_file_filters(path, filters):
        filters = filters or ["*.*"]
        for pattern in filters:
            pattern = str(pattern or "").strip().lower()
            if pattern in {"", "*", "*.*"}:
                return True
            if fnmatch.fnmatch(Path(path).name.lower(), pattern):
                return True
        return False

    def _validate_inputs(self, file_paths, parameters=None):
        manifest = self.workflow.get("run_manifest") or {}
        for resource in manifest.get("file_resources", []) or []:
            if resource.get("required") and not file_paths.get(resource.get("key")):
                raise ValueError(f"请选择文件: {resource.get('label') or resource.get('key')}")
            path = file_paths.get(resource.get("key"), "")
            if resource.get("role") == "output":
                parent = Path(path).parent if path else None
                if path and str(parent) != "." and not parent.exists():
                    raise ValueError(f"输出目录不存在: {parent}")
                continue
            if path and not os.path.exists(path):
                raise ValueError(f"文件不存在: {path}")
        parameters = parameters or {}
        for param in manifest.get("parameters", []) or []:
            param_type = str(param.get("type", "")).lower()
            key = param.get("key")
            label = param.get("label") or key
            value = parameters.get(key, param.get("default", ""))
            if param_type == "list":
                entries = [item for item in (value or []) if str(item).strip()]
                try:
                    max_items = int(param.get("max_items", 0))
                except (TypeError, ValueError):
                    max_items = 0
                if max_items and len(entries) > max_items:
                    raise ValueError(f"列表项目超过上限: {label}（最多 {max_items} 项）")
                if param.get("required") and not entries:
                    raise ValueError(f"请至少填写一项: {label}")
                continue
            if param_type in {"key_value", "object", "map"}:
                if param.get("required") and not value:
                    raise ValueError(f"请至少填写一项: {label}")
                continue
            if param_type == "bool":
                continue
            text_value = str(value or "").strip()
            if param_type not in {"file", "folder"}:
                if param.get("required") and not text_value:
                    raise ValueError(f"请填写参数: {label}")
                continue
            path = text_value
            if param.get("required") and not path:
                raise ValueError(f"请选择{'文件' if param_type == 'file' else '文件夹'}: {label}")
            if not path:
                continue
            path_obj = Path(path)
            if param_type == "folder":
                if not path_obj.is_dir():
                    raise ValueError(f"文件夹不存在: {path}")
            else:
                if not path_obj.is_file():
                    raise ValueError(f"文件不存在: {path}")
                if not self._matches_file_filters(path, param.get("filters")):
                    filters = " ".join(param.get("filters") or ["*.*"])
                    raise ValueError(f"文件类型不符合要求: {label} ({filters})")
        sheet_issues = self._sheet_validation_issues()
        if sheet_issues:
            self._show_sheet_mapping()
            raise ValueError("预设工作表在文件中不存在，请在高级设置中修正：" + "、".join(sheet_issues))

    def _build_current_runtime_workflow(self):
        file_paths = self._collect_file_paths()
        data_sources = self._collect_data_sources()
        parameters = self._collect_parameters()
        self._validate_inputs(file_paths, parameters)
        runtime_workflow = build_runtime_workflow(
            self.workflow, file_paths, data_sources, parameters
        )
        return runtime_workflow, file_paths, data_sources, parameters

    def save_current_config(self):
        if not self.workflow or not self.workflow_path:
            return
        try:
            runtime_workflow, _file_paths, _data_sources, _parameters = self._build_current_runtime_workflow()
            self.workflow = runtime_workflow
            save_workflow_json(self.workflow_path, runtime_workflow)
            self.status_label.setText("已保存")
            self.log("[保存] 已写回 JSON 路径、Sheet 和参数")
        except Exception as exc:
            self.status_label.setText("保存失败")
            QMessageBox.warning(self, "无法保存", str(exc))

    def run_workflow(self):
        if not self.workflow:
            return
        try:
            CRPA_Test = CRPA(self.crpa_code, self.name)
            if CRPA_Test.after_check_start():
                runtime_workflow, file_paths, data_sources, parameters = self._build_current_runtime_workflow()
                payload = build_crpa_payload(runtime_workflow, file_paths, data_sources, parameters)
                payload["crpa_code"] = self.crpa_code
                payload["crpa_name"] = self.name
                print("CRPA payload:", json.dumps(self._redact_crpa_payload(payload), ensure_ascii=False, indent=2))
                self.log("[CRPA] " + json.dumps({"code": self.crpa_code, "name": self.name}, ensure_ascii=False))
                self.log("[运行] 开始执行工作流")
                if self.writeback_check.isChecked() and self.workflow_path:
                    self.workflow = runtime_workflow
                    save_workflow_json(self.workflow_path, runtime_workflow)
                    self.log("[保存] 已写回 JSON 路径、Sheet 和参数")
                record_json_open(
                    self.workflow_path,
                    self.crpa_code,
                    self.name or Path(self.workflow_path).stem,
                )
                self._refresh_history_panel()
                self._start_engine(runtime_workflow, CRPA_Test)
        except Exception as exc:
            traceback.print_exc()
            CRPA_Test.after_check_end(False)
            self.status_label.setText("无法运行")
            QMessageBox.warning(self, "无法运行", str(exc))

    def _start_engine(self, workflow, CRPA_Test=None):
        self.btn_run.setEnabled(False)
        self.btn_save_config.setEnabled(False)
        self.btn_import_extension.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.writeback_check.setEnabled(False)
        total_steps = len(workflow.get("steps", []))
        self.progress.setRange(0, total_steps if total_steps else 1)
        self.progress.setValue(0)
        self.progress.setFormat(f"%v / {total_steps}")
        self.progress_percent_label.setText("0%")
        self.status_label.setText("运行中")
        self.engine = WorkflowEngine({}, workflow, keep_intermediates=False)
        self.engine.log_signal.connect(self.log)
        self.engine.progress_signal.connect(self._on_engine_progress)
        self.engine.finished_signal.connect(
            lambda success, result_pool: self._on_engine_finished(success, result_pool, CRPA_Test)
        )
        self.engine.start()

    def stop_workflow(self):
        engine = self.engine
        if engine is None or not hasattr(engine, "request_cancel"):
            return
        try:
            if not engine.isRunning():
                return
        except RuntimeError:
            return
        engine.request_cancel()
        self.btn_stop.setEnabled(False)
        self.status_label.setText("停止中")
        self.log("[停止] 已请求停止，等待当前代码块检查 state 后退出")

    def _restore_run_buttons(self):
        self.btn_run.setEnabled(bool(self.workflow))
        self.btn_save_config.setEnabled(bool(self.workflow))
        self.btn_import_extension.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.writeback_check.setEnabled(True)

    def _on_engine_progress(self, current, total):
        if self.progress.maximum() != total:
            self.progress.setRange(0, total if total else 1)
            self.progress.setFormat(f"%v / {total}")
        self.progress.setValue(current)
        percent = int((current / total) * 100) if total else 0
        self.progress_percent_label.setText(f"{percent}%")

    def _on_engine_finished(self, success, result_pool, CRPA_Test=None):
        self._restore_run_buttons()
        if CRPA_Test is not None:
            try:
                CRPA_Test.after_check_end(True if success else False)
            except Exception:
                traceback.print_exc()
                CRPA_Test.after_check_end(False)
        result_pool = result_pool or {}
        cancelled = isinstance(result_pool, dict) and result_pool.get("cancelled")
        self.progress.setFormat("完成" if success else ("已停止" if cancelled else "失败"))
        if success:
            self.progress.setValue(self.progress.maximum())
            self.status_label.setText("完成")
            self.progress_percent_label.setText("100%")
            self.log("[完成] 工作流执行完成")
            QMessageBox.information(self, "执行完成", "工作流执行完成。")
        else:
            if cancelled:
                self.status_label.setText("已停止")
                self.log("[停止] 工作流已停止")
                QMessageBox.information(self, "已停止", "已请求停止，工作流已结束。")
                self.engine = None
                return
            self.status_label.setText("失败")
            self.log("[失败] 工作流执行失败")
            QMessageBox.critical(self, "执行失败", "工作流执行失败，请查看日志。")
        self.engine = None
