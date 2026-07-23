"""Runtime parameter input operator panel."""

import copy
import json
from pathlib import Path

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.parameters.mapping_schema import (
    build_rule_engine_config,
    coerce_parameter_rows,
    format_advanced_value,
    format_file_filters,
    normalize_file_filters,
    normalize_list_item_limits,
    normalize_parameter_layout,
    normalize_select_options,
)
from operators.base_panel import BaseToolPanel, QLineEdit


class _CurrentPageStackedWidget(QStackedWidget):
    """A stacked editor should reserve space for its visible page only."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _index: self.updateGeometry())
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


class AdvancedParamMappingPanel(BaseToolPanel):
    """Parameter definition panel used by the CRPA runtime form."""

    use_df = False
    use_type = False
    use_out = False
    theme_color = "#455A64"
    action_name = "参数输入"

    UI_TYPE_TO_DATA = {
        "文本": "String",
        "密码": "Password",
        "勾选框": "Boolean",
        "文件": "File",
        "文件夹": "Folder",
        "下拉选择": "Select",
        "列表": "Array",
        "键值对": "Object",
    }
    DATA_TYPE_TO_UI = {
        "String": "文本",
        "Text": "文本",
        "Integer": "文本",
        "Float": "文本",
        "Object": "文本",
        "Password": "密码",
        "password": "密码",
        "secret": "密码",
        "Boolean": "勾选框",
        "bool": "勾选框",
        "File": "文件",
        "Folder": "文件夹",
        "Select": "下拉选择",
        "select": "下拉选择",
        "Array": "列表",
        "List": "列表",
        "list": "列表",
        "Object": "键值对",
        "object": "键值对",
        "key_value": "键值对",
        "keyvalue": "键值对",
    }
    FILE_FILTER_PRESETS = [
        ("所有文件", ["*.*"]),
        ("Excel", ["*.xlsx", "*.xls", "*.xlsm"]),
        ("PDF", ["*.pdf"]),
        ("CSV", ["*.csv"]),
        ("Word", ["*.docx", "*.doc"]),
        ("图片", ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif"]),
        ("自定义", None),
    ]

    def __init__(self, data_pool, parent=None, editor_mode=False):
        self._editor_mode = bool(editor_mode)
        self._parameter_editor_dialog = None
        self._parameter_draft = {}
        super().__init__(data_pool, parent)
        if self.top_card is not None:
            self.top_card.hide()
        if not self._editor_mode:
            self.panel_header.hide()
            for object_name in ("secondary_save", "primary_execute"):
                button = self.findChild(QPushButton, object_name)
                if button is not None:
                    button.hide()

    def init_custom_ui(self):
        if not self._editor_mode:
            self._build_summary_ui()
            return
        self._container_serial = 0
        card = QFrame()
        card.setObjectName("param_config_card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 10)
        card_layout.setSpacing(8)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        title = QLabel("运行参数配置")
        title.setObjectName("param_config_title")
        desc = QLabel("定义运行前需要填写的参数。导出 CRPA JSON 后，运行器会按这里生成输入表单。")
        desc.setObjectName("param_config_desc")
        desc.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(desc)
        card_layout.addLayout(header)

        self.param_rows = QVBoxLayout()
        self.param_rows.setContentsMargins(0, 0, 0, 0)
        self.param_rows.setSpacing(6)
        card_layout.addLayout(self.param_rows)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        btn_add = QPushButton("添加参数")
        btn_add.setObjectName("param_add_button")
        btn_add.setFixedHeight(32)
        btn_add.clicked.connect(lambda: self.add_parameter_row())
        btn_container = QPushButton("添加横向容器")
        btn_container.setObjectName("param_add_button")
        btn_container.setFixedHeight(32)
        btn_container.clicked.connect(self.add_parameter_container)
        self.collapse_all_button = QPushButton("收起全部")
        self.collapse_all_button.setObjectName("param_add_button")
        self.collapse_all_button.setFixedHeight(32)
        self.collapse_all_button.clicked.connect(self._toggle_all_parameter_bodies)
        actions.addWidget(btn_add, stretch=1)
        actions.addWidget(btn_container, stretch=1)
        actions.addWidget(self.collapse_all_button, stretch=1)
        card_layout.addLayout(actions)

        self.custom_layout.addWidget(card)
        self.setStyleSheet(self.styleSheet() + self._panel_stylesheet())
        self.add_parameter_row(focus_new=False)

    def _build_summary_ui(self):
        card = QFrame()
        card.setObjectName("param_config_card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        title = QLabel("运行参数")
        title.setObjectName("param_config_title")
        self.parameter_summary_label = QLabel("")
        self.parameter_summary_label.setWordWrap(True)
        self.parameter_summary_label.setObjectName("param_config_desc")
        self.parameter_editor_button = QPushButton("编辑运行参数")
        self.parameter_editor_button.setObjectName("param_add_button")
        self.parameter_editor_button.setToolTip("打开独立窗口配置参数、顺序和横向容器")
        self.parameter_editor_button.clicked.connect(self._open_parameter_editor)
        layout.addWidget(title)
        layout.addWidget(self.parameter_summary_label)
        layout.addWidget(self.parameter_editor_button)
        self.custom_layout.addWidget(card)
        self.setStyleSheet(self.styleSheet() + self._panel_stylesheet())
        self._refresh_parameter_summary()

    @staticmethod
    def _empty_parameter_params():
        config = build_rule_engine_config([])
        return {
            "advanced_parameters": [],
            "parameters": config["runtime_payload"]["raw_parameters"],
            "typed_parameters": config["runtime_payload"]["runtime_parameters"],
            "rule_engine_config": config,
            "parameter_layout": [],
        }

    def _refresh_parameter_summary(self):
        if not hasattr(self, "parameter_summary_label"):
            return
        draft = self._parameter_draft or self._empty_parameter_params()
        rows = draft.get("advanced_parameters") or (draft.get("rule_engine_config") or {}).get("parameters") or []
        containers = [
            item
            for item in draft.get("parameter_layout") or []
            if isinstance(item, dict) and item.get("kind") == "container"
        ]
        if not rows:
            self.parameter_summary_label.setText("未配置运行参数。点击按钮在独立窗口中新增参数或横向容器。")
            return
        self.parameter_summary_label.setText(
            "已配置 {} 个参数{}。".format(
                len(rows),
                "，{} 个横向容器".format(len(containers)) if containers else "",
            )
        )

    def _open_parameter_editor(self):
        existing = self._parameter_editor_dialog
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dialog = ParameterEditorDialog(self._parameter_draft, self.window())
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        self._parameter_editor_dialog = dialog
        dialog.accepted.connect(lambda d=dialog: self._apply_parameter_editor_result(d))
        dialog.finished.connect(lambda _result, d=dialog: self._on_parameter_editor_closed(d))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _apply_parameter_editor_result(self, dialog):
        self._parameter_draft = dialog.parameters()
        self._refresh_parameter_summary()
        self._emit_save_requested(show_error=True)

    def _on_parameter_editor_closed(self, dialog):
        if self._parameter_editor_dialog is dialog:
            self._parameter_editor_dialog = None

    @staticmethod
    def _panel_stylesheet():
        return """
            QFrame#param_config_card {
                background: #F7FAFC;
                border: 1px solid #DDE7EF;
                border-radius: 8px;
            }
            QLabel#param_config_title {
                color: #0B1820;
                font-size: 17px;
                font-weight: 900;
                border: none;
            }
            QLabel#param_config_desc {
                color: #3F5866;
                font-size: 12px;
                font-weight: 600;
                border: none;
            }
            QFrame#param_card {
                background: #FFFFFF;
                border: 1px solid #D7E2EA;
                border-radius: 6px;
            }
            QFrame#param_card:hover {
                border-color: #AFC1CF;
            }
            QGroupBox#param_container {
                background: #F8FAFC;
                border: 1px solid #BFD0DC;
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 5px;
                font-weight: 800;
                color: #102A3A;
            }
            QGroupBox#param_container::title {
                subcontrol-origin: margin;
                left: 6px;
                padding: 0 4px;
            }
            QLabel#param_index_badge {
                background: #DDE8EF;
                color: #12222B;
                border-radius: 6px;
                padding: 2px 6px;
                font-size: 13px;
                font-weight: 900;
            }
            QLabel#param_type_icon {
                background: #263238;
                color: #FFFFFF;
                border-radius: 6px;
                min-width: 18px;
                min-height: 18px;
                font-size: 11px;
                font-weight: 800;
            }
            QLabel#param_field_label {
                color: #102A3A;
                font-size: 13px;
                font-weight: 900;
                border: none;
                min-width: 72px;
            }
            QLabel#param_inline_hint {
                color: #5E7788;
                font-size: 12px;
                font-weight: 600;
                border: none;
            }
            QWidget#param_body, QWidget#param_field_row, QWidget#param_default_box,
            QWidget#list_editor, QWidget#list_item_row, QWidget#select_editor, QWidget#select_option_row,
            QWidget#key_value_editor, QWidget#key_value_item_row, QWidget#list_limits {
                background: transparent;
                border: none;
            }
            QLineEdit#field_name {
                min-height: 28px;
                background: #FFFFFF;
                border: 1px solid #BFD0DC;
                border-radius: 6px;
                padding: 3px 8px;
                color: #071923;
                font-size: 13px;
                font-weight: 800;
            }
            QLineEdit, QComboBox, QSpinBox {
                min-height: 28px;
                background: #FFFFFF;
                border: 1px solid #BFD0DC;
                border-radius: 6px;
                padding: 3px 8px;
                color: #071923;
                font-size: 13px;
                font-weight: 700;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border-color: #455A64;
                background: #FFFFFF;
            }
            QPushButton#param_add_button {
                min-height: 30px;
                background-color: #FFFFFF;
                border: 1px solid #94A3B8;
                color: #111827;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 900;
            }
            QPushButton#param_add_button:hover {
                background-color: #F1F5F9;
                border-color: #64748B;
                color: #111827;
            }
            QPushButton#param_add_button:pressed {
                background-color: #E2E8F0;
                border-color: #475569;
                color: #111827;
            }
            QPushButton#param_add_button:disabled {
                background-color: #E2E8F0;
                border: 1px solid #94A3B8;
                color: #111827;
                font-size: 13px;
                font-weight: 900;
            }
            QPushButton#param_collapse_button, QPushButton#path_browse_button,
            QPushButton#list_add_button, QPushButton#list_remove_button,
            QPushButton#select_add_button, QPushButton#select_remove_button,
            QPushButton#container_add_parameter_button {
                background: #FFFFFF;
                border: 1px solid #BFD0DC;
                border-radius: 6px;
                color: #14303D;
                padding: 3px 8px;
                font-size: 12px;
                font-weight: 800;
            }
            QPushButton#param_collapse_button:hover, QPushButton#path_browse_button:hover,
            QPushButton#list_add_button:hover, QPushButton#list_remove_button:hover,
            QPushButton#select_add_button:hover, QPushButton#select_remove_button:hover,
            QPushButton#container_add_parameter_button:hover {
                background: #F1F5F9;
                border-color: #94A3B8;
            }
            QPushButton#param_delete_button {
                background: #FFF7F7;
                border: 1px solid #FECACA;
                border-radius: 6px;
                color: #B91C1C;
                padding: 3px 8px;
            }
            QPushButton#param_delete_button:hover {
                background: #FEE2E2;
                border-color: #FCA5A5;
            }
            QToolButton#param_order_button, QToolButton#param_move_button {
                min-width: 26px;
                max-width: 26px;
                min-height: 26px;
                max-height: 26px;
                padding: 0;
                border: 1px solid #BFD0DC;
                border-radius: 6px;
                background: #FFFFFF;
            }
            QToolButton#param_order_button:hover, QToolButton#param_move_button:hover {
                background: #F1F5F9;
                border-color: #94A3B8;
            }
            QFrame#file_filters_box {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
            }
            QCheckBox {
                color: #102A3A;
                font-size: 13px;
                font-weight: 800;
                background: transparent;
                border: none;
            }
        """

    @staticmethod
    def _disable_parameter_action(widget):
        widget.setProperty("_param_disabled", True)
        if hasattr(widget, "set_parameter_enabled"):
            widget.set_parameter_enabled(False)

    @staticmethod
    def _start_dir_from_text(text):
        path = Path(str(text or "").strip())
        if path.is_dir():
            return str(path)
        if str(path) and path.parent and str(path.parent) != ".":
            return str(path.parent)
        return ""

    @staticmethod
    def _parameter_file_dialog_filter(filters):
        joined = " ".join(normalize_file_filters(filters))
        return f"可选文件 ({joined});;所有文件 (*.*)"

    @staticmethod
    def _data_type_to_ui(data_type):
        return AdvancedParamMappingPanel.DATA_TYPE_TO_UI.get(str(data_type or "String").strip(), "文本")

    @staticmethod
    def _ui_type_to_data(ui_type):
        return AdvancedParamMappingPanel.UI_TYPE_TO_DATA.get(str(ui_type or "文本").strip(), "String")

    @staticmethod
    def _parse_list_value(value):
        if isinstance(value, list):
            return ["" if item is None else str(item) for item in value]
        if isinstance(value, tuple):
            return ["" if item is None else str(item) for item in value]
        text = str(value or "").strip()
        if not text:
            return [""]
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return ["" if item is None else str(item) for item in parsed]
        except Exception:
            pass
        if "," in text or "，" in text or ";" in text or "；" in text:
            return [part.strip() for part in text.replace("，", ",").replace("；", ";").replace(";", ",").split(",")]
        return [text]

    @staticmethod
    def _parse_key_value_value(value):
        if isinstance(value, dict):
            return [(str(key), "" if item is None else str(item)) for key, item in value.items()]
        text = str(value or "").strip()
        if not text:
            return [("", "")]
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return [(str(key), "" if item is None else str(item)) for key, item in parsed.items()]
        except Exception:
            pass
        pairs = []
        for line in text.splitlines():
            key, separator, item = line.partition(":")
            if separator:
                pairs.append((key.strip(), item))
        return pairs or [("", "")]

    @staticmethod
    def _make_collection_limits(initial_count, max_items, default_count):
        initial_count, max_items = normalize_list_item_limits(
            initial_count,
            max_items,
            default_count,
        )
        limits = QWidget()
        limits.setObjectName("list_limits")
        layout = QHBoxLayout(limits)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        initial_spin = QSpinBox()
        initial_spin.setObjectName("list_initial_count")
        initial_spin.setRange(1, 999)
        initial_spin.setValue(initial_count)
        initial_spin.setToolTip("运行器首次显示的输入行数量")
        max_spin = QSpinBox()
        max_spin.setObjectName("list_max_items")
        max_spin.setRange(0, 999)
        max_spin.setSpecialValueText("不限制")
        max_spin.setValue(max_items)
        max_spin.setToolTip("0 表示不限制；达到正数上限后不能继续新增")

        def sync_limits():
            if max_spin.value() and max_spin.value() < initial_spin.value():
                max_spin.setValue(initial_spin.value())

        initial_spin.valueChanged.connect(lambda _value: sync_limits())
        max_spin.valueChanged.connect(lambda _value: sync_limits())
        layout.addWidget(QLabel("初始项目数"))
        layout.addWidget(initial_spin)
        layout.addWidget(QLabel("最多项目数"))
        layout.addWidget(max_spin)
        layout.addStretch(1)
        return limits, initial_spin, max_spin

    @staticmethod
    def _bool_from_value(value):
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是", "勾选"}

    def _set_file_filter_preset(self, combo, filters):
        normalized = normalize_file_filters(filters)
        combo.blockSignals(True)
        for i in range(combo.count()):
            preset = combo.itemData(i)
            if preset is not None and normalize_file_filters(preset) == normalized:
                combo.setCurrentIndex(i)
                combo.blockSignals(False)
                return
        index = combo.findText("自定义")
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _make_field_row(self, label_text, widget, hint_text="", align_top=False):
        row = QWidget()
        row.setObjectName("param_field_row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = QLabel(label_text)
        label.setObjectName("param_field_label")
        label.setAlignment(Qt.AlignRight | (Qt.AlignTop if align_top else Qt.AlignVCenter))
        layout.addWidget(label)
        layout.addWidget(widget, stretch=1)
        if hint_text:
            hint = QLabel(hint_text)
            hint.setObjectName("param_inline_hint")
            layout.addWidget(hint)
        return row

    def _make_value_box(
        self,
        row,
        value="",
        list_items=None,
        options=None,
        list_initial_count=None,
        list_max_items=None,
    ):
        box = QWidget()
        box.setObjectName("param_default_box")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        value_stack = _CurrentPageStackedWidget()
        value_stack.setObjectName("param_value_stack")
        layout.addWidget(value_stack)

        text_wrap = QWidget()
        text_wrap.setObjectName("param_default_text_wrap")
        text_layout = QHBoxLayout(text_wrap)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        value_input = QLineEdit(str(value or ""))
        value_input.setObjectName("input_value")
        value_input.setPlaceholderText("请输入默认值")
        self._disable_parameter_action(value_input)
        browse = QPushButton("浏览")
        browse.setObjectName("path_browse_button")
        browse.setFixedWidth(70)
        browse.clicked.connect(lambda checked=False, r=row: self._browse_parameter_path(r))
        text_layout.addWidget(value_input, stretch=1)
        text_layout.addWidget(browse)
        value_stack.addWidget(text_wrap)

        bool_page = QWidget()
        bool_layout = QVBoxLayout(bool_page)
        bool_layout.setContentsMargins(0, 0, 0, 0)
        bool_default = QCheckBox("默认勾选")
        bool_default.setObjectName("bool_default")
        bool_default.setChecked(self._bool_from_value(value))
        bool_layout.addWidget(bool_default)
        bool_layout.addStretch(1)
        value_stack.addWidget(bool_page)

        list_editor = QWidget()
        list_editor.setObjectName("list_editor")
        list_layout = QVBoxLayout(list_editor)
        list_layout.setObjectName("list_items_layout")
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(6)
        default_list_items = list_items if list_items is not None else self._parse_list_value(value)
        list_limits, list_initial_spin, list_max_spin = self._make_collection_limits(
            list_initial_count,
            list_max_items,
            len(default_list_items),
        )
        list_layout.addWidget(list_limits)
        add_list_btn = QPushButton("添加列表项")
        add_list_btn.setObjectName("list_add_button")
        add_list_btn.clicked.connect(lambda checked=False, l=list_layout: self._add_list_item(l, ""))
        list_layout.addWidget(add_list_btn, alignment=Qt.AlignLeft)
        for item in default_list_items:
            self._add_list_item(list_layout, item)
        value_stack.addWidget(list_editor)

        key_value_editor = QWidget()
        key_value_editor.setObjectName("key_value_editor")
        key_value_layout = QVBoxLayout(key_value_editor)
        key_value_layout.setObjectName("key_value_items_layout")
        key_value_layout.setContentsMargins(0, 0, 0, 0)
        key_value_layout.setSpacing(6)
        default_key_values = self._parse_key_value_value(value)
        key_value_limits, key_value_initial_spin, key_value_max_spin = self._make_collection_limits(
            list_initial_count,
            list_max_items,
            len(default_key_values),
        )
        key_value_layout.addWidget(key_value_limits)
        add_key_value_btn = QPushButton("添加键值对")
        add_key_value_btn.setObjectName("key_value_add_button")
        add_key_value_btn.clicked.connect(
            lambda checked=False, l=key_value_layout: self._add_key_value_item(l, "", "")
        )
        key_value_layout.addWidget(add_key_value_btn, alignment=Qt.AlignLeft)
        for key, item in default_key_values:
            self._add_key_value_item(key_value_layout, key, item)
        value_stack.addWidget(key_value_editor)

        select_page = QWidget()
        select_layout_outer = QVBoxLayout(select_page)
        select_layout_outer.setContentsMargins(0, 0, 0, 0)
        select_layout_outer.setSpacing(6)

        select_default = QComboBox()
        select_default.setObjectName("select_default")
        select_default.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        select_layout_outer.addWidget(select_default)

        select_editor = QWidget()
        select_editor.setObjectName("select_editor")
        select_layout = QVBoxLayout(select_editor)
        select_layout.setObjectName("select_options_layout")
        select_layout.setContentsMargins(0, 0, 0, 0)
        select_layout.setSpacing(6)
        add_select_btn = QPushButton("添加选项")
        add_select_btn.setObjectName("select_add_button")
        add_select_btn.clicked.connect(lambda checked=False, r=row, l=select_layout: self._add_select_option(r, l, ""))
        select_layout.addWidget(add_select_btn, alignment=Qt.AlignLeft)
        select_values = normalize_select_options(options)
        if not select_values:
            select_values = normalize_select_options(value)
        if not select_values:
            select_values = [""]
        for option in select_values:
            self._add_select_option(row, select_layout, option)
        select_layout_outer.addWidget(select_editor)
        value_stack.addWidget(select_page)

        row._value_stack = value_stack
        row._value_text_wrap = text_wrap
        row._value_input = value_input
        row._path_browse_button = browse
        row._select_default = select_default
        row._bool_default = bool_default
        row._list_editor = list_editor
        row._list_initial_count = list_initial_spin
        row._list_max_items = list_max_spin
        row._key_value_editor = key_value_editor
        row._key_value_initial_count = key_value_initial_spin
        row._key_value_max_items = key_value_max_spin
        row._select_editor = select_editor
        self._refresh_select_default_options(row, value)
        return box

    def _add_list_item(self, list_layout, value=""):
        row = QWidget()
        row.setObjectName("list_item_row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        line = QLineEdit(str(value or ""))
        line.setObjectName("list_item")
        line.setPlaceholderText("请输入列表项")
        self._disable_parameter_action(line)
        btn = QPushButton("删除")
        btn.setObjectName("list_remove_button")
        btn.setFixedWidth(58)
        btn.clicked.connect(lambda checked=False, r=row: self._remove_list_item(r))
        layout.addWidget(line, stretch=1)
        layout.addWidget(btn)
        last = list_layout.itemAt(list_layout.count() - 1).widget() if list_layout.count() else None
        if last and last.objectName() == "list_add_button":
            list_layout.insertWidget(list_layout.count() - 1, row)
        else:
            list_layout.addWidget(row)

    def _add_key_value_item(self, key_value_layout, key="", value=""):
        row = QWidget()
        row.setObjectName("key_value_item_row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        key_input = QLineEdit(str(key or ""))
        key_input.setObjectName("key_value_key")
        key_input.setPlaceholderText("键，例如：docx{姓名}")
        self._disable_parameter_action(key_input)
        value_input = QLineEdit(str(value or ""))
        value_input.setObjectName("key_value_value")
        value_input.setPlaceholderText("值，例如：小明")
        self._disable_parameter_action(value_input)
        separator = QLabel(":")
        separator.setObjectName("param_inline_hint")
        remove = QPushButton("删除")
        remove.setObjectName("list_remove_button")
        remove.setFixedWidth(58)
        remove.clicked.connect(lambda checked=False, r=row: self._remove_list_item(r))
        layout.addWidget(key_input, stretch=1)
        layout.addWidget(separator)
        layout.addWidget(value_input, stretch=1)
        layout.addWidget(remove)
        last = key_value_layout.itemAt(key_value_layout.count() - 1).widget() if key_value_layout.count() else None
        if last and last.objectName() == "key_value_add_button":
            key_value_layout.insertWidget(key_value_layout.count() - 1, row)
        else:
            key_value_layout.addWidget(row)

    @staticmethod
    def _remove_list_item(row):
        parent = row.parentWidget()
        if parent and parent.layout():
            parent.layout().removeWidget(row)
        row.hide()
        row.deleteLater()

    def _add_select_option(self, param_row, select_layout, value=""):
        row = QWidget()
        row.setObjectName("select_option_row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        line = QLineEdit(str(value or ""))
        line.setObjectName("select_option")
        line.setPlaceholderText("请输入选项")
        self._disable_parameter_action(line)
        line.textChanged.connect(lambda _text, r=param_row: self._refresh_select_default_options(r))
        btn = QPushButton("删除")
        btn.setObjectName("select_remove_button")
        btn.setFixedWidth(58)
        btn.clicked.connect(lambda checked=False, r=param_row, option_row=row: self._remove_select_option(r, option_row))
        layout.addWidget(line, stretch=1)
        layout.addWidget(btn)
        last = select_layout.itemAt(select_layout.count() - 1).widget() if select_layout.count() else None
        if last and last.objectName() == "select_add_button":
            select_layout.insertWidget(select_layout.count() - 1, row)
        else:
            select_layout.addWidget(row)
        self._refresh_select_default_options(param_row)

    def _remove_select_option(self, param_row, option_row):
        parent = option_row.parentWidget()
        if parent and parent.layout():
            parent.layout().removeWidget(option_row)
        option_row.setParent(None)
        option_row.hide()
        option_row.deleteLater()
        self._refresh_select_default_options(param_row)

    @staticmethod
    def _collect_select_options(row):
        editor = getattr(row, "_select_editor", None)
        if not editor:
            return []
        return normalize_select_options([line.text() for line in editor.findChildren(QLineEdit, "select_option")])

    def _refresh_select_default_options(self, row, preferred=None):
        combo = getattr(row, "_select_default", None)
        if combo is None:
            return
        current = str(preferred if preferred is not None else combo.currentText()).strip()
        options = self._collect_select_options(row)
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(options)
        if current and current in options:
            combo.setCurrentText(current)
        elif options:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    @staticmethod
    def _collect_list_items(row):
        editor = getattr(row, "_list_editor", None)
        if not editor:
            return []
        values = []
        for line in editor.findChildren(QLineEdit, "list_item"):
            text = line.text().strip()
            if text:
                values.append(text)
        return values

    @staticmethod
    def _collect_key_value_items(row):
        editor = getattr(row, "_key_value_editor", None)
        if not editor:
            return {}
        values = {}
        for item_row in editor.findChildren(QWidget, "key_value_item_row"):
            key_input = item_row.findChild(QLineEdit, "key_value_key")
            value_input = item_row.findChild(QLineEdit, "key_value_value")
            key = key_input.text().strip() if key_input else ""
            value = value_input.text() if value_input else ""
            if not key:
                if value:
                    raise ValueError("键值对的值已填写，但缺少键")
                continue
            if key in values:
                raise ValueError(f"键值对存在重复键: {key}")
            values[key] = value
        return values

    def _browse_parameter_path(self, row):
        type_combo = row.findChild(QComboBox, "input_type")
        value_input = getattr(row, "_value_input", None)
        filters_input = row.findChild(QLineEdit, "file_filters")
        if not type_combo or not value_input:
            return
        ui_type = type_combo.currentText().strip()
        current = value_input.text().strip()
        if ui_type == "文件夹":
            path = QFileDialog.getExistingDirectory(
                self,
                "选择文件夹",
                current or self._start_dir_from_text(current),
            )
        else:
            filter_text = self._parameter_file_dialog_filter(filters_input.text() if filters_input else "")
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择文件",
                self._start_dir_from_text(current),
                filter_text,
            )
        if path:
            value_input.setText(path)

    def _on_filter_preset_changed(self, row):
        preset_combo = row.findChild(QComboBox, "file_filter_preset")
        filters_input = row.findChild(QLineEdit, "file_filters")
        if not preset_combo or not filters_input:
            return
        filters = preset_combo.currentData()
        if filters is not None:
            filters_input.setText(format_file_filters(filters))

    def _mark_custom_filter_preset(self, row):
        preset_combo = row.findChild(QComboBox, "file_filter_preset")
        if not preset_combo:
            return
        index = preset_combo.findText("自定义")
        if index >= 0:
            preset_combo.blockSignals(True)
            preset_combo.setCurrentIndex(index)
            preset_combo.blockSignals(False)

    def _update_type_controls(self, row):
        type_combo = row.findChild(QComboBox, "input_type")
        filters_box = row.findChild(QFrame, "file_filters_box")
        icon = row.findChild(QLabel, "param_type_icon")
        ui_type = type_combo.currentText().strip() if type_combo else "文本"
        is_file = ui_type == "文件"
        is_folder = ui_type == "文件夹"
        is_password = ui_type == "密码"
        is_bool = ui_type == "勾选框"
        is_list = ui_type == "列表"
        is_key_value = ui_type == "键值对"
        is_select = ui_type == "下拉选择"

        if getattr(row, "_value_stack", None):
            page_index = 1 if is_bool else 2 if is_list else 3 if is_key_value else 4 if is_select else 0
            row._value_stack.setCurrentIndex(page_index)
        if getattr(row, "_path_browse_button", None):
            row._path_browse_button.setVisible(is_file or is_folder)
            row._path_browse_button.setText("文件夹" if is_folder else "浏览")
        if getattr(row, "_value_input", None):
            if is_file:
                row._value_input.setPlaceholderText("请选择或输入文件路径")
            elif is_folder:
                row._value_input.setPlaceholderText("请选择或输入文件夹路径")
            elif is_password:
                row._value_input.setPlaceholderText("请输入默认密码")
            else:
                row._value_input.setPlaceholderText("请输入默认文本")
            row._value_input.setEchoMode(QLineEdit.Password if is_password else QLineEdit.Normal)
        if filters_box:
            filters_box.setVisible(is_file)
        if getattr(row, "_filters_row", None):
            row._filters_row.setVisible(is_file)
        if icon:
            icon.setText({"文本": "T", "密码": "P", "勾选框": "Y", "文件": "F", "文件夹": "D", "下拉选择": "S", "列表": "L", "键值对": "K"}.get(ui_type, "P"))

    def _toggle_row_body(self, row):
        body = row.findChild(QWidget, "param_body")
        btn = row.findChild(QPushButton, "param_collapse_button")
        if not body or not btn:
            return
        visible = body.isVisible()
        body.setVisible(not visible)
        btn.setText("展开" if visible else "收起")

    def _toggle_all_parameter_bodies(self):
        rows = list(self._parameter_rows_in_order())
        collapse = any(
            not row.findChild(QWidget, "param_body").isHidden()
            for row in rows
            if row.findChild(QWidget, "param_body") is not None
        )
        self._set_all_parameter_bodies_visible(not collapse)

    def _set_all_parameter_bodies_visible(self, visible):
        rows = list(self._parameter_rows_in_order())
        for row in rows:
            body = row.findChild(QWidget, "param_body")
            button = row.findChild(QPushButton, "param_collapse_button")
            if body is None or button is None:
                continue
            body.setVisible(visible)
            button.setText("收起" if visible else "展开")
        self.collapse_all_button.setText("收起全部" if visible else "展开全部")

    def add_parameter_row(
        self,
        name="",
        data_type="String",
        value="",
        filters=None,
        label="",
        tip="",
        required=True,
        options=None,
        parent_container=None,
        focus_new=True,
        list_initial_count=None,
        list_max_items=None,
    ):
        row = QFrame()
        row.setObjectName("param_card")
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        row._parent_container = parent_container
        outer = QVBoxLayout(row)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(5)
        badge = QLabel("#1")
        badge.setObjectName("param_index_badge")
        badge.setAlignment(Qt.AlignCenter)
        icon = QLabel("T")
        icon.setObjectName("param_type_icon")
        icon.setAlignment(Qt.AlignCenter)
        param_name = str(name or label or "")
        field_name = QLineEdit(param_name)
        field_name.setObjectName("field_name")
        field_name.setPlaceholderText("参数名称，例如：报表月份")
        self._disable_parameter_action(field_name)
        move_container = QToolButton()
        move_container.setObjectName("param_move_button")
        move_container.clicked.connect(lambda checked=False, r=row, b=move_container: self._show_container_menu(r, b))
        move_up = QToolButton()
        move_up.setObjectName("param_order_button")
        move_up.setIcon(self.style().standardIcon(QStyle.SP_ArrowUp))
        move_up.setToolTip("上移参数")
        move_up.clicked.connect(lambda checked=False, r=row: self._move_parameter(r, -1))
        move_down = QToolButton()
        move_down.setObjectName("param_order_button")
        move_down.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        move_down.setToolTip("下移参数")
        move_down.clicked.connect(lambda checked=False, r=row: self._move_parameter(r, 1))
        collapse = QPushButton("收起")
        collapse.setObjectName("param_collapse_button")
        collapse.setFixedWidth(58)
        collapse.clicked.connect(lambda checked=False, r=row: self._toggle_row_body(r))
        delete = QPushButton("删除")
        delete.setObjectName("param_delete_button")
        delete.setFixedWidth(58)
        delete.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
        header.addWidget(badge)
        header.addWidget(icon)
        header.addWidget(field_name, stretch=1)
        header.addWidget(move_container)
        header.addWidget(move_up)
        header.addWidget(move_down)
        header.addWidget(collapse)
        header.addWidget(delete)
        outer.addLayout(header)

        body = QWidget()
        body.setObjectName("param_body")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)

        type_combo = QComboBox()
        type_combo.setObjectName("input_type")
        type_combo.addItems(list(self.UI_TYPE_TO_DATA.keys()))
        type_combo.setCurrentText(self._data_type_to_ui(data_type))
        body_layout.addWidget(self._make_field_row("输入类型", type_combo))

        value_box = self._make_value_box(
            row,
            value,
            options=options,
            list_initial_count=list_initial_count,
            list_max_items=list_max_items,
        )
        body_layout.addWidget(self._make_field_row("默认值", value_box, align_top=True))

        tip_input = QLineEdit(str(tip or ""))
        tip_input.setObjectName("tip")
        tip_input.setPlaceholderText("输入框为空时显示的提示信息，例如：填写本次要生成报表的月份")
        self._disable_parameter_action(tip_input)
        body_layout.addWidget(self._make_field_row("提示信息", tip_input))

        required_check = QCheckBox("运行前必须填写")
        required_check.setObjectName("required")
        required_check.setChecked(bool(required))
        body_layout.addWidget(self._make_field_row("是否必填", required_check))

        filters_box = QFrame()
        filters_box.setObjectName("file_filters_box")
        filters_layout = QHBoxLayout(filters_box)
        filters_layout.setContentsMargins(6, 5, 6, 5)
        filters_layout.setSpacing(6)
        preset_combo = QComboBox()
        preset_combo.setObjectName("file_filter_preset")
        for preset_label, preset in self.FILE_FILTER_PRESETS:
            preset_combo.addItem(preset_label, preset)
        filters_input = QLineEdit(format_file_filters(filters))
        filters_input.setObjectName("file_filters")
        filters_input.setPlaceholderText("例如：*.xlsx, *.pdf")
        self._disable_parameter_action(filters_input)
        self._set_file_filter_preset(preset_combo, filters_input.text())
        filters_layout.addWidget(QLabel("文件类型"))
        filters_layout.addWidget(preset_combo)
        filters_layout.addWidget(QLabel("过滤器"))
        filters_layout.addWidget(filters_input, stretch=1)
        filters_row = self._make_field_row("文件过滤器", filters_box)
        body_layout.addWidget(filters_row)
        row._filters_row = filters_row

        outer.addWidget(body)
        type_combo.currentTextChanged.connect(lambda _text, r=row: self._update_type_controls(r))
        preset_combo.currentIndexChanged.connect(lambda _index, r=row: self._on_filter_preset_changed(r))
        filters_input.textEdited.connect(lambda _text, r=row: self._mark_custom_filter_preset(r))

        target_layout = self._parameter_layout_for(parent_container)
        target_layout.addWidget(row)
        self._update_type_controls(row)
        self._refresh_row_move_button(row)
        self._refresh_parameter_titles()
        if focus_new:
            self._focus_new_widget(row, field_name)
        return row

    def _parameter_layout_for(self, container=None):
        if container is not None:
            return container._parameter_children_layout
        return self.param_rows

    def _parameter_containers(self):
        containers = []
        for index in range(self.param_rows.count()):
            widget = self.param_rows.itemAt(index).widget()
            if isinstance(widget, QGroupBox) and widget.property("parameter_container"):
                containers.append(widget)
        return containers

    def _parameter_rows_in_order(self):
        for index in range(self.param_rows.count()):
            widget = self.param_rows.itemAt(index).widget()
            if not widget or widget.isHidden():
                continue
            if isinstance(widget, QGroupBox) and widget.property("parameter_container"):
                child_layout = widget._parameter_children_layout
                for child_index in range(child_layout.count()):
                    row = child_layout.itemAt(child_index).widget()
                    if row and not row.isHidden():
                        yield row
            else:
                yield widget

    def _next_container_id(self):
        existing = {str(container._container_id) for container in self._parameter_containers()}
        while True:
            self._container_serial += 1
            container_id = "container_{}".format(self._container_serial)
            if container_id not in existing:
                return container_id

    def _focus_new_widget(self, widget, focus_widget):
        def reveal():
            self.scroll_area.ensureWidgetVisible(widget, 0, 28)
            self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())
            focus_widget.setFocus()

        QTimer.singleShot(0, reveal)

    def add_parameter_container(self, title="参数组", container_id=None, focus_new=True):
        container = QGroupBox("横向容器")
        container.setObjectName("param_container")
        container.setProperty("parameter_container", True)
        container._container_id = str(container_id or self._next_container_id())
        outer = QVBoxLayout(container)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title_input = QLineEdit(str(title or "参数组"))
        title_input.setObjectName("container_title")
        title_input.setPlaceholderText("容器标题，例如：筛选条件")
        self._disable_parameter_action(title_input)
        add_child = QPushButton("添加参数")
        add_child.setObjectName("container_add_parameter_button")
        add_child.clicked.connect(lambda checked=False, c=container: self.add_parameter_row(parent_container=c))
        move_up = QToolButton()
        move_up.setObjectName("param_order_button")
        move_up.setIcon(self.style().standardIcon(QStyle.SP_ArrowUp))
        move_up.setToolTip("上移容器")
        move_up.clicked.connect(lambda checked=False, c=container: self._move_container(c, -1))
        move_down = QToolButton()
        move_down.setObjectName("param_order_button")
        move_down.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        move_down.setToolTip("下移容器")
        move_down.clicked.connect(lambda checked=False, c=container: self._move_container(c, 1))
        delete = QPushButton("删除容器")
        delete.setObjectName("param_delete_button")
        delete.clicked.connect(lambda checked=False, c=container: self._remove_parameter_container(c))
        header.addWidget(title_input, stretch=1)
        header.addWidget(add_child)
        header.addWidget(move_up)
        header.addWidget(move_down)
        header.addWidget(delete)
        outer.addLayout(header)

        hint = QLabel("容器内参数会在 CRPA 运行器中横向显示；宽控件会自动改为纵向显示。")
        hint.setObjectName("param_inline_hint")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        children_host = QWidget()
        children_layout = QVBoxLayout(children_host)
        children_layout.setContentsMargins(0, 0, 0, 0)
        children_layout.setSpacing(6)
        outer.addWidget(children_host)
        container._title_input = title_input
        container._parameter_children_layout = children_layout
        self.param_rows.addWidget(container)
        if focus_new:
            self._focus_new_widget(container, title_input)
        return container

    def _refresh_row_move_button(self, row):
        button = next((item for item in row.findChildren(QToolButton) if item.objectName() == "param_move_button"), None)
        if button is None:
            return
        if row._parent_container is None:
            button.setIcon(self.style().standardIcon(QStyle.SP_ArrowRight))
            button.setToolTip("移入横向容器")
        else:
            button.setIcon(self.style().standardIcon(QStyle.SP_ArrowLeft))
            button.setToolTip("移入其他容器或移出当前容器")

    def _show_container_menu(self, row, button):
        containers = self._parameter_containers()
        if not containers and row._parent_container is None:
            return
        menu = QMenu(self)
        for container in containers:
            if container is row._parent_container:
                continue
            title = container._title_input.text().strip() or "未命名容器"
            action = menu.addAction("移入：{}".format(title))
            action.triggered.connect(lambda checked=False, r=row, c=container: self._move_parameter_to_container(r, c))
        if row._parent_container is not None:
            if menu.actions():
                menu.addSeparator()
            action = menu.addAction("移出到普通参数")
            action.triggered.connect(lambda checked=False, r=row: self._move_parameter_to_root(r))
        if menu.actions():
            menu.exec_(button.mapToGlobal(button.rect().bottomLeft()))

    def _move_parameter(self, row, offset):
        layout = self._parameter_layout_for(row._parent_container)
        index = layout.indexOf(row)
        target = index + offset
        if index < 0 or target < 0 or target >= layout.count():
            return
        layout.takeAt(index)
        layout.insertWidget(target, row)
        self._refresh_parameter_titles()

    def _move_container(self, container, offset):
        index = self.param_rows.indexOf(container)
        target = index + offset
        if index < 0 or target < 0 or target >= self.param_rows.count():
            return
        self.param_rows.takeAt(index)
        self.param_rows.insertWidget(target, container)
        self._refresh_parameter_titles()

    def _move_parameter_to_container(self, row, container):
        source = self._parameter_layout_for(row._parent_container)
        source.removeWidget(row)
        container._parameter_children_layout.addWidget(row)
        row._parent_container = container
        self._refresh_row_move_button(row)
        self._refresh_parameter_titles()
        self._focus_new_widget(container, row.findChild(QLineEdit, "field_name"))

    def _move_parameter_to_root(self, row):
        source = self._parameter_layout_for(row._parent_container)
        source.removeWidget(row)
        self.param_rows.addWidget(row)
        row._parent_container = None
        self._refresh_row_move_button(row)
        self._refresh_parameter_titles()
        self._focus_new_widget(row, row.findChild(QLineEdit, "field_name"))

    def _remove_parameter_container(self, container):
        root_index = self.param_rows.indexOf(container)
        children = []
        layout = container._parameter_children_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                children.append(widget)
        self.param_rows.removeWidget(container)
        container.hide()
        container.deleteLater()
        for offset, row in enumerate(children):
            row._parent_container = None
            self.param_rows.insertWidget(root_index + offset, row)
            self._refresh_row_move_button(row)
        self._refresh_parameter_titles()

    def _refresh_parameter_titles(self):
        visible_index = 1
        for row in self._parameter_rows_in_order():
            badge = row.findChild(QLabel, "param_index_badge")
            if badge:
                badge.setText(f"#{visible_index}")
            visible_index += 1

    def remove_dynamic_row(self, row):
        layout = self._parameter_layout_for(getattr(row, "_parent_container", None))
        layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        self._refresh_parameter_titles()

    def clear_custom_ui(self):
        if not self._editor_mode:
            self._parameter_draft = self._empty_parameter_params()
            self._refresh_parameter_summary()
            return
        self._clear_parameter_nodes()
        self.add_parameter_row(focus_new=False)

    def _clear_parameter_nodes(self):
        while self.param_rows.count():
            item = self.param_rows.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.deleteLater()

    def _collect_parameter_rows(self):
        ui_rows = []
        for row in self._parameter_rows_in_order():
            name_input = row.findChild(QLineEdit, "field_name")
            type_combo = row.findChild(QComboBox, "input_type")
            tip_input = row.findChild(QLineEdit, "tip")
            required_check = row.findChild(QCheckBox, "required")
            filters_input = row.findChild(QLineEdit, "file_filters")
            ui_type = type_combo.currentText().strip() if type_combo else "文本"
            data_type = self._ui_type_to_data(ui_type)

            if data_type == "Boolean":
                raw_value = "true" if getattr(row, "_bool_default", None) and row._bool_default.isChecked() else "false"
            elif data_type == "Array":
                raw_value = json.dumps(self._collect_list_items(row), ensure_ascii=False)
            elif data_type == "Object":
                raw_value = json.dumps(self._collect_key_value_items(row), ensure_ascii=False)
            elif data_type == "Select":
                raw_value = getattr(row, "_select_default", None).currentText().strip() if getattr(row, "_select_default", None) else ""
            else:
                raw_value = getattr(row, "_value_input", None).text().strip() if getattr(row, "_value_input", None) else ""

            item = {
                "fieldName": name_input.text().strip() if name_input else "",
                "label": name_input.text().strip() if name_input else "",
                "dataType": data_type,
                "input": raw_value,
                "tip": tip_input.text().strip() if tip_input else "",
                "required": bool(required_check.isChecked()) if required_check else True,
            }
            if data_type == "File":
                item["filters"] = normalize_file_filters(filters_input.text() if filters_input else "")
            if data_type == "Select":
                item["options"] = self._collect_select_options(row)
            if data_type == "Array":
                item["initial_count"] = getattr(row, "_list_initial_count", None).value() if getattr(row, "_list_initial_count", None) else 1
                item["max_items"] = getattr(row, "_list_max_items", None).value() if getattr(row, "_list_max_items", None) else 0
            if data_type == "Object":
                item["initial_count"] = getattr(row, "_key_value_initial_count", None).value() if getattr(row, "_key_value_initial_count", None) else 1
                item["max_items"] = getattr(row, "_key_value_max_items", None).value() if getattr(row, "_key_value_max_items", None) else 0
            has_select_options = bool(item.get("options")) if data_type == "Select" else False
            if any([item["fieldName"], item["input"].strip("[]\" "), item["tip"], has_select_options]):
                ui_rows.append(item)
        return coerce_parameter_rows(ui_rows)

    @staticmethod
    def _row_field_name(row):
        name_input = row.findChild(QLineEdit, "field_name") if row else None
        return name_input.text().strip() if name_input else ""

    def _collect_parameter_layout(self, rows):
        valid_names = {str(row.get("fieldName") or "").strip() for row in rows}
        nodes = []
        for index in range(self.param_rows.count()):
            widget = self.param_rows.itemAt(index).widget()
            if not widget or widget.isHidden():
                continue
            if isinstance(widget, QGroupBox) and widget.property("parameter_container"):
                children = []
                for child_index in range(widget._parameter_children_layout.count()):
                    row = widget._parameter_children_layout.itemAt(child_index).widget()
                    name = self._row_field_name(row)
                    if name in valid_names:
                        children.append({"kind": "parameter", "fieldName": name})
                nodes.append(
                    {
                        "kind": "container",
                        "id": widget._container_id,
                        "title": widget._title_input.text().strip() or "参数组",
                        "direction": "horizontal",
                        "children": children,
                    }
                )
                continue
            name = self._row_field_name(widget)
            if name in valid_names:
                nodes.append({"kind": "parameter", "fieldName": name})
        return normalize_parameter_layout(nodes, rows)

    def get_custom_params(self):
        if not self._editor_mode:
            return copy.deepcopy(self._parameter_draft or self._empty_parameter_params())
        rows = self._collect_parameter_rows()
        config = build_rule_engine_config(rows)
        runtime_payload = config["runtime_payload"]
        return {
            "advanced_parameters": rows,
            "parameters": runtime_payload["raw_parameters"],
            "typed_parameters": runtime_payload["runtime_parameters"],
            "rule_engine_config": config,
            "parameter_layout": self._collect_parameter_layout(rows),
        }

    def set_custom_params(self, p):
        if not self._editor_mode:
            self._parameter_draft = copy.deepcopy(p or self._empty_parameter_params())
            self._refresh_parameter_summary()
            return
        rows = p.get("advanced_parameters")
        if not rows and p.get("rule_engine_config"):
            rows = []
            config = p.get("rule_engine_config", {})
            for param in config.get("parameters", []) or []:
                rows.append({
                    "fieldName": param.get("fieldName", ""),
                    "dataType": param.get("dataType", "String"),
                    "input": param.get("input", ""),
                    "tip": param.get("tip", ""),
                    "required": param.get("required", True),
                    "filters": param.get("filters"),
                    "options": param.get("options"),
                    "initial_count": param.get("initial_count"),
                    "max_items": param.get("max_items"),
                })
        if not rows and p.get("parameters"):
            rows = [
                {
                    "fieldName": key,
                    "dataType": "String",
                    "input": value,
                    "tip": "",
                    "required": True,
                }
                for key, value in (p.get("parameters") or {}).items()
            ]
        parameter_layout = p.get("parameter_layout") or []
        if not rows and not parameter_layout:
            return
        rows = rows or []
        by_name = {
            str(param.get("fieldName") or "").strip(): param
            for param in rows
            if str(param.get("fieldName") or "").strip()
        }
        self._clear_parameter_nodes()
        self._container_serial = 0
        for node in normalize_parameter_layout(parameter_layout, rows):
            if node.get("kind") == "container":
                container = self.add_parameter_container(
                    node.get("title", "参数组"),
                    node.get("id"),
                    focus_new=False,
                )
                for child in node.get("children") or []:
                    param = by_name.get(str(child.get("fieldName") or "").strip())
                    if param:
                        self.add_parameter_row(
                            param.get("fieldName", ""),
                            param.get("dataType", "String"),
                            param.get("input", format_advanced_value(param.get("value", ""))),
                            param.get("filters"),
                            "",
                            param.get("tip", ""),
                            param.get("required", True),
                            param.get("options"),
                            parent_container=container,
                            focus_new=False,
                            list_initial_count=param.get("initial_count"),
                            list_max_items=param.get("max_items"),
                        )
                continue
            param = by_name.get(str(node.get("fieldName") or "").strip())
            if param:
                self.add_parameter_row(
                    param.get("fieldName", ""),
                    param.get("dataType", "String"),
                    param.get("input", format_advanced_value(param.get("value", ""))),
                    param.get("filters"),
                    "",
                    param.get("tip", ""),
                    param.get("required", True),
                    param.get("options"),
                    focus_new=False,
                    list_initial_count=param.get("initial_count"),
                    list_max_items=param.get("max_items"),
                )
        self._refresh_parameter_titles()
        self._set_all_parameter_bodies_visible(False)

    def _validate(self):
        try:
            self.get_custom_params()
        except Exception as exc:
            QMessageBox.warning(self, "参数配置错误", str(exc))
            return False, None
        return True, None


class ParameterEditorDialog(QDialog):
    """Independent editor for runtime parameters and their layout."""

    def __init__(self, params=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑运行参数")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setSizeGripEnabled(True)
        self.resize(980, 720)
        self._parameters = copy.deepcopy(params or AdvancedParamMappingPanel._empty_parameter_params())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        self.editor = AdvancedParamMappingPanel(None, self, editor_mode=True)
        self.editor.set_params(self._parameters)
        self.editor.panel_header.hide()
        for object_name in ("secondary_save", "primary_execute"):
            button = self.editor.findChild(QPushButton, object_name)
            if button is not None:
                button.hide()
        layout.addWidget(self.editor, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_parameters)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_parameters(self):
        try:
            self._parameters = self.editor.get_custom_params()
        except Exception as exc:
            QMessageBox.warning(self, "参数配置错误", str(exc))
            return
        self.accept()

    def parameters(self):
        return copy.deepcopy(self._parameters)
