"""Shared base class for operator configuration panels."""

import copy

import pandas as pd
from core.dataframe_ops.columns import stringify_column_name
from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from parameter_input import ParameterTextEdit, ParameterTextInput
from parameter_resolver import clone_resolved_runtime_value
from ui.design.layout_constants import CONFIG_DOCK_MIN_WIDTH

QLineEdit = ParameterTextInput


class BaseToolPanel(QWidget):
    save_requested = pyqtSignal(str, dict)
    run_requested = pyqtSignal(str, dict)

    use_df = True
    use_type = True
    use_out = True
    theme_color = "#2196F3"
    action_name = "未命名"
    _COL_REF_ROLE = Qt.UserRole
    _COL_POSITION_ROLE = Qt.UserRole + 1
    _COL_NAME_ROLE = Qt.UserRole + 2
    _INPUT_REF_ROLE = Qt.UserRole + 20

    def __init__(self, data_pool, parent=None):
        super().__init__(parent)
        self.data_pool = data_pool
        self.combo_boxes_to_update = []
        self._panel_action_key = ""
        self._runtime_parameters = {}
        self._parameter_mappings = {}
        self._resolve_params_on_get = False
        self._last_raw_params = None
        self._panel_update_depth = 0
        self._pending_df_summary_refresh = False
        self._pending_col_combo_refresh = False
        self._incoming_tables = []
        self._incoming_outputs = []
        self._saved_basic_input = None
        self._saved_basic_output = None
        self._init_base_ui()

    @staticmethod
    def _mix_hex_color(color, target="#FFFFFF", ratio=0.88):
        try:
            color = color.lstrip("#")
            target = target.lstrip("#")
            rgb = [int(color[i:i + 2], 16) for i in (0, 2, 4)]
            trg = [int(target[i:i + 2], 16) for i in (0, 2, 4)]
            mixed = [
                round(rgb[i] * (1 - ratio) + trg[i] * ratio)
                for i in range(3)
            ]
            return "#{:02X}{:02X}{:02X}".format(*mixed)
        except Exception:
            return "#F4F7FB"

    @staticmethod
    def _set_combo_placeholder(combo, placeholder):
        """Set a QComboBox placeholder while staying compatible with PyQt5 5.11."""
        if combo is None:
            return
        setter = getattr(combo, "setPlaceholderText", None)
        if callable(setter):
            setter(str(placeholder or ""))
        line_edit = combo.lineEdit() if hasattr(combo, "lineEdit") else None
        if line_edit is not None:
            line_edit.setPlaceholderText(str(placeholder or ""))

    def set_panel_context(self, action_key="", node_title=""):
        self._panel_action_key = action_key or ""
        if hasattr(self, "panel_badge"):
            self.panel_badge.setText(self.action_name)
            self.panel_badge.setToolTip(action_key or self.action_name)
            self.panel_badge.hide()
        if hasattr(self, "panel_title"):
            self.panel_title.setText(node_title or self.action_name)
            self.panel_title.setToolTip(node_title or self.action_name)

    def set_runtime_parameters(self, parameters=None, mappings=None):
        self._runtime_parameters = copy.deepcopy(parameters or {})
        self._parameter_mappings = copy.deepcopy(mappings or {})
        self._refresh_parameter_inputs()

    def _refresh_parameter_inputs(self):
        widgets = list(self.findChildren(QLineEdit)) + list(self.findChildren(ParameterTextEdit))
        for widget in widgets:
            if hasattr(widget, "set_runtime_context"):
                widget.set_runtime_context(
                    self._runtime_parameters,
                    self._parameter_mappings,
                )

    def eventFilter(self, obj, event):
        if event.type() == QEvent.ChildAdded:
            child = event.child()
            if isinstance(child, QWidget):
                self._install_child_filters(child)
                self._install_parameter_actions(child)
        return super().eventFilter(obj, event)

    def _install_child_filters(self, widget):
        try:
            widget.installEventFilter(self)
        except Exception:
            pass
        for child in widget.findChildren(QWidget):
            try:
                child.installEventFilter(self)
            except Exception:
                pass

    def _install_parameter_actions(self, root=None):
        root = root or self
        for line_edit in root.findChildren(QLineEdit):
            self._attach_parameter_action(line_edit)
        for text_edit in root.findChildren(ParameterTextEdit):
            self._attach_parameter_action(text_edit)

    def _attach_parameter_action(self, line_edit):
        if line_edit.property("_param_disabled"):
            if hasattr(line_edit, "set_parameter_enabled"):
                line_edit.set_parameter_enabled(False)
            return
        if hasattr(line_edit, "set_runtime_context"):
            line_edit.set_runtime_context(
                self._runtime_parameters,
                self._parameter_mappings,
            )
        if isinstance(line_edit, ParameterTextEdit):
            try:
                line_edit.parameterMenuRequested.disconnect()
            except Exception:
                pass
            line_edit.parameterMenuRequested.connect(self._show_parameter_menu)
            return
        if line_edit.property("_param_action_installed"):
            return
        action = QAction(self._parameter_action_icon(), "引用参数", line_edit)
        action.setToolTip("引用运行参数")
        action.triggered.connect(lambda checked=False, le=line_edit: self._show_parameter_menu(le))
        line_edit.addAction(action, QLineEdit.TrailingPosition)
        line_edit.setProperty("_param_action_installed", True)

    def _parameter_action_icon(self):
        pixmap = QPixmap(18, 18)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#E3F2FD"))
        painter.drawRoundedRect(1, 1, 16, 16, 5, 5)
        painter.setPen(QColor("#0D47A1"))
        font = QFont("Arial", 7, QFont.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "fx")
        painter.end()
        return QIcon(pixmap)

    def _insert_text_at_cursor(self, line_edit, text):
        if hasattr(line_edit, "insert_text"):
            line_edit.insert_text(text)
            return
        pos = line_edit.cursorPosition()
        old = line_edit.text()
        line_edit.setText(old[:pos] + text + old[pos:])
        line_edit.setCursorPosition(pos + len(text))
        line_edit.setFocus()

    def _show_parameter_menu(self, line_edit):
        menu = self._build_parameter_menu(line_edit)
        menu.exec_(line_edit.mapToGlobal(line_edit.rect().bottomRight()))

    def _build_parameter_menu(self, line_edit):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: white; border: 1px solid #CBD5E1; border-radius: 6px; }
            QMenu::item { padding: 7px 18px; font-size: 12px; }
            QMenu::item:selected { background: #E3F2FD; color: #0D47A1; }
            QMenu::separator { height: 1px; background: #E5EAF0; margin: 4px 8px; }
        """)
        params = sorted((self._runtime_parameters or {}).keys())

        if params:
            for name in params:
                action = menu.addAction(name)
                action.setToolTip("插入 ${" + name + "}")
                action.triggered.connect(
                    lambda checked=False, n=name: self._insert_text_at_cursor(
                        line_edit, "${" + n + "}"
                    )
                )
        else:
            action = menu.addAction("暂无可用参数")
            action.setEnabled(False)

        return menu

    def _make_card(self, title=""):
        card = QFrame()
        card.setStyleSheet("""
            QFrame#card {
                background: #FFFFFF;
                border: 1px solid #DFE5EC;
                border-radius: 8px;
            }
        """)
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 14)
        card_layout.setSpacing(10)

        if title:
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(8)
            accent = QFrame()
            accent.setFixedSize(4, 16)
            accent.setStyleSheet(
                f"background: {self.theme_color}; border: none; border-radius: 2px;"
            )
            tl = QLabel(title)
            tl.setObjectName("card_title")
            tl.setStyleSheet(
                "font-weight: bold; color: #263238; border: none; font-size: 13px;"
            )
            header.addWidget(accent)
            header.addWidget(tl)
            header.addStretch()
            card_layout.addLayout(header)
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet(
                "border: none; border-top: 1px solid #EEF2F6; max-height: 1px;"
            )
            card_layout.addWidget(sep)

        inner = QVBoxLayout()
        inner.setContentsMargins(0, 2, 0, 0)
        inner.setSpacing(8)
        card_layout.addLayout(inner)
        return card, inner

    def _make_add_button(self, text):
        btn = QPushButton(text)
        btn.setObjectName("add_rule_button")
        btn.setFixedHeight(34)
        return btn

    def _make_delete_button(self):
        btn = QPushButton("×")
        btn.setObjectName("mini_delete")
        btn.setToolTip("删除")
        return btn

    def _make_hint_label(self, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("panel_hint_text")
        label.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
        return label

    def _init_base_ui(self):
        soft_theme = self._mix_hex_color(self.theme_color, "#FFFFFF", 0.90)
        softer_theme = self._mix_hex_color(self.theme_color, "#FFFFFF", 0.96)
        self.setMinimumWidth(CONFIG_DOCK_MIN_WIDTH)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.scroll_area.setStyleSheet(
            "QScrollArea { background-color: transparent; border: none; }"
        )

        self.content_widget = QWidget()
        self.content_widget.setMinimumWidth(CONFIG_DOCK_MIN_WIDTH)
        self.content_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.content_widget.setStyleSheet(
            "background: #F3F6FA;"
        )
        self.content_widget.setObjectName("panel_content")
        self.setStyleSheet(f"""
            QWidget#panel_content {{ background: #F3F6FA; }}
            QFrame#panel_header {{
                background: {softer_theme};
                border: 1px solid {soft_theme};
                border-radius: 6px;
            }}
            QLabel#panel_badge {{
                background: {self.theme_color};
                color: white;
                border-radius: 8px;
                padding: 3px 8px;
                font-size: 11px;
                font-weight: bold;
            }}
            QLabel#panel_title {{
                color: #1F2933;
                font-size: 14px;
                font-weight: bold;
                border: none;
            }}
            QLabel#panel_hint {{
                color: #78909C;
                font-size: 11px;
                border: none;
            }}
            QLabel#df_summary {{
                color: #607D8B;
                background: #F7FAFC;
                border: 1px solid #E3EAF2;
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 11px;
            }}
            QComboBox {{
                min-width: 72px;
                min-height: 28px;
                background: white;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 3px 8px;
                color: #1F2933;
            }}
            QComboBox:hover {{ border-color: #94A3B8; }}
            QComboBox:focus {{ border: 1px solid {self.theme_color}; }}
            QComboBox QAbstractItemView {{
                background-color: white;
                color: #263238;
                border: 1px solid #CBD5E1;
                selection-background-color: {soft_theme};
                selection-color: #111827;
            }}
            QLineEdit {{
                min-width: 80px;
                min-height: 28px;
                background: white;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 3px 8px;
                color: #1F2933;
            }}
            QLineEdit:hover {{ border-color: #94A3B8; }}
            QLineEdit:focus {{
                border: 1px solid {self.theme_color};
                background: #FFFFFF;
            }}
            QTextEdit {{
                background: white;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 5px 8px;
                color: #1F2933;
            }}
            QTextEdit:hover {{ border-color: #94A3B8; }}
            QTextEdit:focus {{
                border: 1px solid {self.theme_color};
                background: #FFFFFF;
            }}
            QPushButton {{
                min-height: 28px;
                border-radius: 6px;
                border: 1px solid #CBD5E1;
                background: #FFFFFF;
                color: #263238;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                background: #F8FAFC;
                border-color: #94A3B8;
            }}
            QPushButton#add_rule_button {{
                background: #F8FAFC;
                border: 1px dashed #CBD5E1;
                color: #334155;
                font-size: 12px;
            }}
            QPushButton#add_rule_button:hover {{
                background: #EEF2F6;
                border-color: #94A3B8;
            }}
            QPushButton#mini_delete {{
                min-width: 26px;
                max-width: 26px;
                min-height: 26px;
                max-height: 26px;
                padding: 0;
                border-radius: 6px;
                color: #94A3B8;
            }}
            QPushButton#mini_delete:hover {{
                background: #FFF5F5;
                border-color: #FCA5A5;
                color: #B91C1C;
            }}
            QPushButton#primary_execute {{
                background-color: {self.theme_color};
                color: white;
                min-height: 40px;
                font-weight: bold;
                border-radius: 8px;
                font-size: 13px;
                border: none;
            }}
            QPushButton#primary_execute:hover {{ background-color: {self.theme_color}; }}
            QPushButton#secondary_save {{
                background-color: #FFFFFF;
                color: #334155;
                min-height: 40px;
                font-weight: 600;
                border-radius: 8px;
                font-size: 13px;
                border: 1px solid #CBD5E1;
            }}
            QPushButton#secondary_save:hover {{
                background-color: #F8FAFC;
                border-color: #94A3B8;
            }}
            QScrollBar:vertical {{
                width: 10px;
                background: transparent;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: #CBD5E1;
                border-radius: 5px;
                min-height: 36px;
            }}
            QScrollBar::handle:vertical:hover {{ background: #94A3B8; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
                border: none;
            }}
        """)
        self.main_layout = QVBoxLayout(self.content_widget)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(10)

        self.panel_header = QFrame()
        self.panel_header.setObjectName("panel_header")
        header_layout = QHBoxLayout(self.panel_header)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(10)
        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(0)
        self.panel_title = QLabel(self.action_name)
        self.panel_title.setObjectName("panel_title")
        self.panel_title.setWordWrap(True)
        self.panel_hint = QLabel("参数配置")
        self.panel_hint.setObjectName("panel_hint")
        title_stack.addWidget(self.panel_title)
        title_stack.addWidget(self.panel_hint)
        self.panel_badge = QLabel(self.action_name)
        self.panel_badge.setObjectName("panel_badge")
        header_layout.addLayout(title_stack, stretch=1)
        self.panel_badge.hide()
        self.main_layout.addWidget(self.panel_header)

        self.top_form = QFormLayout()
        self.top_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.top_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.top_form.setHorizontalSpacing(12)
        self.top_form.setVerticalSpacing(8)
        self.top_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        has_top = True
        self.top_card = None
        if has_top:
            self.top_card, top_inner = self._make_card("基础配置")
            self.main_layout.addWidget(self.top_card)
            top_inner.addLayout(self.top_form)

        self.operation_name_input = QLineEdit()
        self.operation_name_input.setPlaceholderText(f"可选: 用于说明这个{self.action_name}节点做什么")
        self.top_form.addRow("操作命名:", self.operation_name_input)

        if self.use_df:
            self.df_combo = QComboBox()
            self.combo_boxes_to_update.append(self.df_combo)
            self.df_combo.currentTextChanged.connect(self._on_df_combo_changed)
            self.df_combo.currentIndexChanged.connect(self._on_df_combo_changed)
            self.top_form.addRow("目标表:", self.df_combo)
            self._df_row_label = self.top_form.labelForField(self.df_combo)
            self.df_summary = QLabel("未选择数据表")
            self.df_summary.setObjectName("df_summary")
            self.top_form.addRow("", self.df_summary)

        if self.use_type:
            self.type_combo = QComboBox()
            self.type_combo.addItems(["列名", "字母", "索引"])
            self.type_combo.currentTextChanged.connect(self._refresh_col_combos)
            self.top_form.addRow("匹配模式:", self.type_combo)

        self.custom_layout = QVBoxLayout()
        self.custom_layout.setSpacing(8)
        self.main_layout.addLayout(self.custom_layout)
        self.init_custom_ui()

        self.bottom_form = QFormLayout()
        self.bottom_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.bottom_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.bottom_form.setHorizontalSpacing(12)
        self.bottom_form.setVerticalSpacing(8)
        self.bottom_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if self.use_out:
            bottom_card, bottom_inner = self._make_card("输出配置")
            self.main_layout.addWidget(bottom_card)
            bottom_inner.addLayout(self.bottom_form)

        if self.use_out:
            self.out_input = QLineEdit()
            self.out_input.setPlaceholderText(
                f"可选: 默认命名为 [目标表_{self.action_name}]"
            )
            self.bottom_form.addRow("结果命名:", self.out_input)
            self._out_row_label = self.bottom_form.labelForField(self.out_input)

        self.main_layout.addStretch()
        self.scroll_area.setWidget(self.content_widget)
        outer_layout.addWidget(self.scroll_area)

        btn_layout = QVBoxLayout()
        btn_layout.setContentsMargins(12, 8, 12, 12)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        btn_save = QPushButton("应用配置")
        btn_save.setObjectName("secondary_save")
        btn_save.clicked.connect(self._on_save_config)
        btn_run = QPushButton("运行当前节点")
        btn_run.setObjectName("primary_execute")
        btn_run.setStyleSheet(
            f"QPushButton {{ background-color: {self.theme_color}; color: white; "
            f"height: 40px; font-weight: bold; border-radius: 8px; font-size: 13px; "
            f"border: none; }}"
            f"QPushButton:hover {{ background-color: {self.theme_color}; opacity: 0.85; }}"
        )
        btn_run.clicked.connect(self._on_execute)
        action_row.addWidget(btn_save, stretch=1)
        action_row.addWidget(btn_run, stretch=1)
        btn_layout.addLayout(action_row)

        outer_layout.addLayout(btn_layout)
        self._refresh_df_summary()
        self._install_child_filters(self)
        self._install_parameter_actions()

    def _on_execute(self):
        if not self._emit_save_requested(show_error=True):
            return
        ok, _ = self._validate()
        if not ok:
            return
        try:
            params = self.get_params()
        except Exception as exc:
            QMessageBox.warning(self, "运行配置失败", str(exc))
            return
        self.run_requested.emit(self._panel_action_key or self.action_name, copy.deepcopy(params))

    def _on_save_config(self):
        self._emit_save_requested(show_error=True)

    def _emit_save_requested(self, show_error=False):
        old_resolve = self._resolve_params_on_get
        self._resolve_params_on_get = False
        self._last_raw_params = None
        try:
            params = self.get_params()
        except Exception as exc:
            if show_error:
                QMessageBox.warning(self, "保存配置失败", str(exc))
            return False
        finally:
            self._resolve_params_on_get = old_resolve
        self.save_requested.emit(self._panel_action_key or self.action_name, copy.deepcopy(params))
        return True

    def _on_df_combo_changed(self, *_):
        self._remember_current_input_ref()
        self._refresh_df_summary()
        self._refresh_col_combos()

    def set_incoming_outputs(self, incoming_outputs):
        self._incoming_outputs = [
            item
            for item in (incoming_outputs or [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        self.update_combos([item["name"] for item in self._incoming_outputs])

    def _input_ref_for_name(self, name):
        target = str(name or "").strip()
        for item in self._incoming_outputs:
            if str(item.get("name") or "").strip() == target:
                return item
        return None

    def _combo_input_ref(self, combo):
        if combo is None:
            return None
        try:
            index = combo.currentIndex()
            data = combo.itemData(index, self._INPUT_REF_ROLE) if index >= 0 else None
        except RuntimeError:
            return None
        return copy.deepcopy(data) if isinstance(data, dict) else None

    @staticmethod
    def _input_ref_key(item):
        return (
            str((item or {}).get("source_node_id") or ""),
            str((item or {}).get("source_output_id") or "out_1"),
        )

    def _input_ref_for_key(self, source_node_id, source_output_id):
        target = (str(source_node_id or ""), str(source_output_id or "out_1"))
        for item in self._incoming_outputs:
            if self._input_ref_key(item) == target:
                return item
        return None

    def _remember_current_input_ref(self):
        if not hasattr(self, "df_combo"):
            return
        ref = self._combo_input_ref(self.df_combo) or self._input_ref_for_name(self.df_combo.currentText())
        self.df_combo.setProperty("source_node_id", str((ref or {}).get("source_node_id") or ""))
        self.df_combo.setProperty("source_output_id", str((ref or {}).get("source_output_id") or "out_1"))
        self.df_combo.setProperty("data_key", str((ref or {}).get("data_key") or (ref or {}).get("name") or ""))

    def _current_input_ref(self):
        if not hasattr(self, "df_combo"):
            return None
        combo_ref = self._combo_input_ref(self.df_combo)
        if combo_ref:
            return combo_ref
        ref = self._input_ref_for_key(
            self.df_combo.property("source_node_id"),
            self.df_combo.property("source_output_id"),
        )
        return ref or self._input_ref_for_name(self.df_combo.currentText())

    def _current_dataframe(self):
        ref = self._current_input_ref()
        candidates = []
        if ref:
            candidates.extend([
                ref.get("data_key"),
                ref.get("name"),
            ])
        if hasattr(self, "df_combo"):
            candidates.extend([
                self.df_combo.property("data_key"),
                self.df_combo.currentText(),
            ])
        for key in candidates:
            key = str(key or "").strip()
            if key and key in self.data_pool:
                return self.data_pool.get(key)
        return None

    def _saved_input_for_basic_field(self, params):
        inputs = [item for item in (params or {}).get("inputs") or [] if isinstance(item, dict)]
        return inputs[0] if inputs else None

    def _saved_output_for_basic_field(self, params):
        outputs = [item for item in (params or {}).get("outputs") or [] if isinstance(item, dict)]
        return outputs[0] if outputs else None

    def _set_basic_input_selection(self, input_item):
        if not self.use_df or not hasattr(self, "df_combo") or not isinstance(input_item, dict):
            return
        name = str(input_item.get("name") or "").strip()
        self.df_combo.setProperty("source_node_id", str(input_item.get("source_node_id") or ""))
        self.df_combo.setProperty("source_output_id", str(input_item.get("source_output_id") or "out_1"))
        self._set_input_combo_items(self.df_combo, self._incoming_outputs, name)
        self._remember_current_input_ref()
        self._refresh_df_summary()

    def _default_output_name(self, input_name):
        base = str(input_name or "输入表").strip() or "输入表"
        suffix = str(self.action_name or "结果").strip() or "结果"
        return f"{base}_{suffix}"

    def _flow_output_data_type(self):
        if self._panel_action_key == "import_template":
            return "workbook"
        if self._panel_action_key == "insert_block":
            return "workbook"
        if self._panel_action_key == "save_template":
            return "workbook"
        return "table"

    def _flow_input_data_type(self, ref):
        return str(ref.get("data_type") or "table")

    def _flow_params_from_basic_fields(self, params):
        if not self.use_df:
            return params
        ref = self._current_input_ref()
        if not ref:
            return params
        input_name = str(ref.get("name") or self.df_combo.currentText()).strip()
        saved_output = self._saved_output_for_basic_field(params)
        if not saved_output:
            saved_output = self._saved_basic_output or {}
        output_name = ""
        if self.use_out and hasattr(self, "out_input"):
            output_name = self.out_input.text().strip()
        if not output_name and saved_output:
            output_name = str(saved_output.get("name") or "").strip()
        output_name = output_name or self._default_output_name(input_name)
        output_type = self._flow_output_data_type()
        prefs = copy.deepcopy(params.get("io_prefs") or {})
        prefs["selected_input"] = {
            "source_node_id": str(ref.get("source_node_id") or ""),
            "source_output_id": str(ref.get("source_output_id") or "out_1"),
            "name": input_name,
            "role": "current",
            "data_type": self._flow_input_data_type(ref),
            "enabled": True,
        }
        prefs["output_name"] = output_name
        prefs["output_data_type"] = str((saved_output or {}).get("data_type") or output_type)
        params["io_prefs"] = prefs
        return params

    def begin_panel_update(self):
        self._panel_update_depth += 1

    def end_panel_update(self):
        self._panel_update_depth = max(0, self._panel_update_depth - 1)
        if self._panel_update_depth:
            return
        refresh_summary = self._pending_df_summary_refresh
        refresh_cols = self._pending_col_combo_refresh
        self._pending_df_summary_refresh = False
        self._pending_col_combo_refresh = False
        if refresh_summary:
            self._refresh_df_summary_now()
        if refresh_cols:
            self._refresh_col_combos_now()

    def _refresh_df_summary(self):
        if self._panel_update_depth:
            self._pending_df_summary_refresh = True
            return
        self._refresh_df_summary_now()

    def _refresh_df_summary_now(self):
        if not hasattr(self, "df_summary"):
            if hasattr(self, "panel_hint"):
                self.panel_hint.setText("节点配置")
            return
        df_name = self.df_combo.currentText().strip() if hasattr(self, "df_combo") else ""
        ref = self._current_input_ref()
        df_name = str((ref or {}).get("name") or df_name).strip()
        df = self._current_dataframe()
        if df is None:
            self.df_summary.setText("未选择数据表")
            if hasattr(self, "panel_hint"):
                self.panel_hint.setText("未选择输入表")
            return
        rows, cols = df.shape
        self.df_summary.setText(f"{rows:,} 行 · {cols:,} 列")
        if hasattr(self, "panel_hint"):
            self.panel_hint.setText(f"输入: {df_name} · {rows:,} 行 · {cols:,} 列")

    def set_params(self, p):
        self.begin_panel_update()
        try:
            self._saved_basic_input = copy.deepcopy(self._saved_input_for_basic_field(p))
            self._saved_basic_output = copy.deepcopy(self._saved_output_for_basic_field(p))
            if hasattr(self, "operation_name_input"):
                self.operation_name_input.setText(str(p.get("operation_name") or ""))
            if self.use_df:
                self._set_basic_input_selection(self._saved_input_for_basic_field(p))
            if self.use_type:
                _type_map = {"col_name": "列名", "col_word": "字母", "col_index": "索引"}
                ct = p.get("col_type", "")
                if ct in _type_map:
                    self.type_combo.setCurrentText(_type_map[ct])
            if self.use_out and hasattr(self, "out_input"):
                saved_output = self._saved_output_for_basic_field(p)
                if saved_output:
                    self.out_input.setText(str(saved_output.get("name") or ""))
            self.set_custom_params(p)
        finally:
            self.end_panel_update()

    def get_params(self):
        p = {}
        if hasattr(self, "operation_name_input"):
            operation_name = self.operation_name_input.text().strip()
            if operation_name:
                p["operation_name"] = operation_name
        if self.use_type:
            _type_map = {"列名": "col_name", "字母": "col_word", "索引": "col_index"}
            p["col_type"] = _type_map.get(self.type_combo.currentText(), "col_name")
        p.update(self.get_custom_params())
        p = self._flow_params_from_basic_fields(p)
        if self._resolve_params_on_get:
            self._last_raw_params = copy.deepcopy(p)
            return clone_resolved_runtime_value(
                p,
                self._runtime_parameters,
                self._parameter_mappings,
                strict=True,
            )
        return p

    def clear_ui(self):
        self.begin_panel_update()
        try:
            if hasattr(self, "operation_name_input"):
                self.operation_name_input.clear()
            if self.use_out:
                self.out_input.clear()
            self.clear_custom_ui()
        finally:
            self.end_panel_update()

    def _set_combo_by_prefix(self, combo, prefix):
        if not prefix:
            return
        for i in range(combo.count()):
            if combo.itemText(i).startswith(prefix):
                return combo.setCurrentIndex(i)

    def _current_col_type(self):
        if not self.use_type or not hasattr(self, "type_combo"):
            return "col_name"
        _type_map = {"列名": "col_name", "字母": "col_word", "索引": "col_index"}
        return _type_map.get(self.type_combo.currentText(), "col_name")

    @staticmethod
    def _index_to_excel_col(index):
        index = int(index) + 1
        letters = []
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            letters.append(chr(65 + remainder))
        return "".join(reversed(letters))

    def _column_ref_for_mode(self, position, column, col_type=None):
        col_type = col_type or self._current_col_type()
        if col_type == "col_word":
            return self._index_to_excel_col(position)
        if col_type == "col_index":
            return str(position)
        return stringify_column_name(column)

    def _col_combo_selection_snapshot(self, combo):
        text = combo.currentText().strip()
        row = combo.currentIndex()
        ref = text
        position = None
        if row >= 0 and text == combo.itemText(row).strip():
            data = combo.itemData(row, self._COL_REF_ROLE)
            if data is not None:
                ref = str(data).strip()
            stored_position = combo.itemData(row, self._COL_POSITION_ROLE)
            try:
                position = int(stored_position)
            except (TypeError, ValueError):
                position = None
        old_mode = combo.property("_col_display_type") or self._current_col_type()
        return text, ref, position, old_mode

    def _find_col_combo_item(self, combo, value, role):
        if value is None:
            return -1
        target = str(value).strip()
        for i in range(combo.count()):
            data = combo.itemData(i, role)
            if data is not None and str(data).strip() == target:
                return i
        return -1

    def _find_col_combo_position(self, combo, position):
        if position is None:
            return -1
        for i in range(combo.count()):
            try:
                if int(combo.itemData(i, self._COL_POSITION_ROLE)) == int(position):
                    return i
            except (TypeError, ValueError):
                continue
        return -1

    def _populate_col_combo(self, combo, col_items):
        old_text, old_ref, old_position, old_mode = self._col_combo_selection_snapshot(combo)
        new_mode = self._current_col_type()

        combo.blockSignals(True)
        combo.clear()
        for position, column in col_items:
            display = self._column_ref_for_mode(position, column, new_mode)
            name = stringify_column_name(column)
            combo.addItem(display, userData=display)
            item_index = combo.count() - 1
            combo.setItemData(item_index, int(position), self._COL_POSITION_ROLE)
            combo.setItemData(item_index, name, self._COL_NAME_ROLE)
            combo.setItemData(
                item_index,
                f"column: {name}\nletter: {self._index_to_excel_col(position)}\nindex: {position}",
                Qt.ToolTipRole,
            )
        combo.setProperty("_col_display_type", new_mode)

        selected = -1
        if old_mode != new_mode:
            selected = self._find_col_combo_position(combo, old_position)
        if selected < 0:
            selected = self._find_col_combo_item(combo, old_ref, self._COL_REF_ROLE)
        if selected < 0:
            selected = combo.findText(old_text)
        if selected < 0:
            selected = self._find_col_combo_item(combo, old_ref, self._COL_NAME_ROLE)
        if selected < 0:
            selected = self._find_col_combo_position(combo, old_position)

        if selected >= 0:
            combo.setCurrentIndex(selected)
        elif old_text:
            combo.addItem(old_text, userData=old_ref or old_text)
            fallback_index = combo.count() - 1
            combo.setItemData(fallback_index, old_position, self._COL_POSITION_ROLE)
            combo.setItemData(fallback_index, old_ref or old_text, self._COL_NAME_ROLE)
            combo.setCurrentIndex(fallback_index)
            if combo.isEditable() and combo.lineEdit():
                combo.lineEdit().setText(old_text)
        combo.blockSignals(False)

    @staticmethod
    def _set_combo_items_preserving_text(combo, items, preferred_text=None):
        current = str(preferred_text if preferred_text is not None else combo.currentText()).strip()
        item_list = [str(item) for item in (items or [])]
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(item_list)
        if current:
            if combo.findText(current) < 0:
                combo.addItem(current)
            combo.setCurrentText(current)
        elif combo.count() > 0:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _set_input_combo_items(self, combo, refs, preferred_text=None):
        current_text = str(preferred_text if preferred_text is not None else combo.currentText()).strip()
        current_key = (
            str(combo.property("source_node_id") or ""),
            str(combo.property("source_output_id") or "out_1"),
        )
        combo.blockSignals(True)
        combo.clear()
        selected_index = -1
        for item in refs or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            combo.addItem(name)
            row = combo.count() - 1
            combo.setItemData(row, copy.deepcopy(item), self._INPUT_REF_ROLE)
            combo.setItemData(
                row,
                f"source: {item.get('source_node_id', '')}/{item.get('source_output_id', 'out_1')}",
                Qt.ToolTipRole,
            )
            key = self._input_ref_key(item)
            if current_key[0] and key == current_key:
                selected_index = row
            elif selected_index < 0 and current_text and name == current_text:
                selected_index = row
        if selected_index >= 0:
            combo.setCurrentIndex(selected_index)
        elif current_text:
            combo.addItem(current_text)
            combo.setCurrentIndex(combo.count() - 1)
        elif combo.count() > 0:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _get_col_name(self, combo):
        """Return the column reference used by the current matching mode."""
        if combo is None:
            return ""
        text = combo.currentText().strip()
        row = combo.currentIndex()
        if row >= 0 and text == combo.itemText(row).strip():
            data = combo.itemData(row, self._COL_REF_ROLE)
            if data is not None:
                return str(data).strip()
        return text

    def _set_col_name(self, combo, name):
        """Set a column combo by stored reference, display text, or source name."""
        if combo is None or name is None or name == "":
            return
        target = str(name).strip()
        idx = self._find_col_combo_item(combo, target, self._COL_REF_ROLE)
        if idx < 0:
            idx = combo.findText(target)
        if idx < 0:
            idx = self._find_col_combo_item(combo, target, self._COL_NAME_ROLE)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setCurrentText(target)

    def _show_field_error(self, widget, show):
        """显示/清除字段错误状态（红色边框）"""
        if show:
            widget.setStyleSheet(
                widget.styleSheet()
                + " border: 2px solid #EF5350; background: #FFF5F5;"
            )
        else:
            widget.setStyleSheet("")  # reset to parent styling

    def _validate_required(self, widget, label=""):
        """校验必填项，为空时返回 False 并标红"""
        text = ""
        if isinstance(widget, QComboBox):
            text = widget.currentText().strip()
        elif isinstance(widget, QLineEdit):
            text = widget.text().strip()
        if not text:
            self._show_field_error(widget, True)
            placeholder = f"必填: {label}" if label else "此项必填"
            if isinstance(widget, QComboBox):
                self._set_combo_placeholder(widget, placeholder)
            else:
                widget.setPlaceholderText(placeholder)
            return False
        self._show_field_error(widget, False)
        return True

    def _validate(self):
        """校验必填项，子类可扩展。返回 (ok, first_error_widget)"""
        if self.use_df and hasattr(self, "df_combo"):
            if not self._validate_required(self.df_combo, "目标表"):
                return False, self.df_combo
        return True, None

    def _make_collapsible_rule(self, summary=""):
        """创建可折叠规则行，返回 (container, header_btn, body_widget)"""
        container = QFrame()
        container.setStyleSheet(
            "QFrame#rule_container { background: #FFFFFF; border: 1px solid #E3EAF2; border-radius: 8px; }"
        )
        container.setObjectName("rule_container")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # header bar
        header_btn = QPushButton(f" ▾ {summary}" if summary else " ▾ 规则", container)
        header_btn.setFixedHeight(34)
        header_btn.setCursor(Qt.PointingHandCursor)
        header_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; text-align: left; "
            "padding-left: 10px; font-size: 12px; color: #374151; font-weight: bold; }"
            "QPushButton:hover { background: #F8FAFC; }"
        )
        header_btn.setObjectName("rule_header")
        cl.addWidget(header_btn)

        # body
        body = QWidget(container)
        body.setStyleSheet("QWidget { background: #FFFFFF; border: none; }")
        cl.addWidget(body)
        body.setVisible(True)

        header_btn.clicked.connect(
            lambda: self._toggle_rule_body(header_btn, body)
        )
        return container, header_btn, body

    def _toggle_rule_body(self, header_btn, body):
        body.setVisible(not body.isVisible())
        text = header_btn.text()
        if body.isVisible():
            header_btn.setText(text.replace("▸", "▾"))
        else:
            header_btn.setText(text.replace("▾", "▸"))

    def _update_rule_summary(self, header_btn, summary):
        arrow = "▾" if "▾" in header_btn.text() else "▸"
        header_btn.setText(f" {arrow} {summary}")

    def _inline_label(self, text):
        label = QLabel(text)
        label.setFixedWidth(32)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
        return label

    def _forget_col_combos_under(self, widget):
        if not hasattr(self, "_col_combos") or widget is None:
            return
        dead_combos = set(widget.findChildren(QComboBox))
        if isinstance(widget, QComboBox):
            dead_combos.add(widget)
        valid_combos = []
        for combo in self._col_combos:
            try:
                if combo not in dead_combos:
                    valid_combos.append(combo)
            except RuntimeError:
                pass
        self._col_combos = valid_combos
        if hasattr(self, "_col_combo_filters"):
            self._col_combo_filters = {
                combo: dtype_filter
                for combo, dtype_filter in self._col_combo_filters.items()
                if combo in valid_combos
            }

    def _remove_child_filters(self, widget):
        try:
            widget.removeEventFilter(self)
        except Exception:
            pass
        for child in widget.findChildren(QWidget):
            try:
                child.removeEventFilter(self)
            except Exception:
                pass

    def remove_dynamic_row(self, row):
        if row is None:
            return
        self._forget_col_combos_under(row)
        self._remove_child_filters(row)
        parent = row.parentWidget()
        if parent and parent.layout():
            parent.layout().removeWidget(row)
        row.hide()
        row.deleteLater()

    def clear_dynamic_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                self.remove_dynamic_row(widget)
                continue
            child_layout = item.layout()
            if child_layout:
                self.clear_dynamic_layout(child_layout)

    def _make_col_combo(self, placeholder="选择列", dtype_filter=None):
        """创建可编辑的列名下拉框。dtype_filter: 'numeric'/'datetime'/'string'/None(全部)"""
        combo = QComboBox()
        combo.setEditable(True)
        self._set_combo_placeholder(combo, placeholder)
        combo.setMinimumWidth(96)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        if not hasattr(self, "_col_combos"):
            self._col_combos = []
        if not hasattr(self, "_col_combo_filters"):
            self._col_combo_filters = {}
        self._col_combos.append(combo)
        self._col_combo_filters[combo] = dtype_filter
        self._refresh_col_combos()
        return combo

    @staticmethod
    def _col_matches_dtype(series, dtype_filter):
        if dtype_filter is None:
            return True
        try:
            if dtype_filter == "numeric":
                return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
            if dtype_filter == "datetime":
                return pd.api.types.is_datetime64_any_dtype(series)
            if dtype_filter == "string":
                return series.dtype == object and not pd.api.types.is_datetime64_any_dtype(series)
        except Exception:
            pass
        return True

    def _refresh_col_combos(self):
        """根据当前选中的 DataFrame 刷新所有列名下拉框"""
        if self._panel_update_depth:
            self._pending_col_combo_refresh = True
            return
        self._refresh_col_combos_now()

    def _refresh_col_combos_from_df(self, df):
        if not hasattr(self, "_col_combos"):
            return
        all_items = list(enumerate(df.columns)) if df is not None else []
        filtered_cache = {}
        valid_combos = []
        for combo in self._col_combos:
            try:
                combo.currentText()
            except RuntimeError:
                continue
            valid_combos.append(combo)

            dtype_filter = self._col_combo_filters.get(combo)
            if dtype_filter and df is not None:
                if dtype_filter not in filtered_cache:
                    filtered_cache[dtype_filter] = [
                        (position, column)
                        for position, column in all_items
                        if self._col_matches_dtype(df.iloc[:, position], dtype_filter)
                    ]
                col_items = filtered_cache[dtype_filter]
            else:
                col_items = all_items

            self._populate_col_combo(combo, col_items)

        self._col_combos = valid_combos
        if hasattr(self, "_col_combo_filters"):
            self._col_combo_filters = {
                cb: f for cb, f in self._col_combo_filters.items()
                if cb in valid_combos
            }

    def _refresh_col_combos_now(self):
        """根据当前选中的 DataFrame 刷新所有列名下拉框"""
        if not hasattr(self, "_col_combos"):
            return
        df = self._current_dataframe() if self.use_df else None
        self._refresh_col_combos_from_df(df)

    def update_combos(self, table_names):
        self.begin_panel_update()
        try:
            self._incoming_tables = list(table_names or [])
            for combo in self.combo_boxes_to_update:
                if combo is getattr(self, "df_combo", None) and self._incoming_outputs:
                    self._set_input_combo_items(combo, self._incoming_outputs)
                else:
                    self._set_combo_items_preserving_text(combo, table_names)
            self._remember_current_input_ref()
            self._refresh_df_summary()
            self._refresh_col_combos()
        finally:
            self.end_panel_update()

    def init_custom_ui(self):
        pass

    def set_custom_params(self, p):
        pass

    def get_custom_params(self):
        return {}

    def clear_custom_ui(self):
        pass

    def execute_batch(self):
        return False
