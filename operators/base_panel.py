"""Shared base class for operator configuration panels."""

import copy

import pandas as pd
from PyQt5.QtCore import QEvent, Qt, pyqtSignal
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
    QStyle,
    QVBoxLayout,
    QWidget,
)

from parameter_input import ParameterTextEdit, ParameterTextInput
from parameter_resolver import clone_resolved_runtime_value

QLineEdit = ParameterTextInput


class BaseToolPanel(QWidget):
    step_recorded = pyqtSignal(str, dict, object, str)

    use_df = True
    use_type = True
    use_out = True
    theme_color = "#2196F3"
    action_name = "未命名"

    def __init__(self, data_pool, parent=None):
        super().__init__(parent)
        self.data_pool = data_pool
        self.combo_boxes_to_update = []
        self._panel_action_key = ""
        self._runtime_parameters = {}
        self._parameter_mappings = {}
        self._resolve_params_on_get = False
        self._last_raw_params = None
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
        icon = self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        action = QAction(icon, "引入参数", line_edit)
        action.setToolTip("引入运行参数或映射")
        action.triggered.connect(lambda checked=False, le=line_edit: self._show_parameter_menu(le))
        line_edit.addAction(action, QLineEdit.TrailingPosition)
        line_edit.setProperty("_param_action_installed", True)

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
        menu = QMenu(self)
        params = sorted((self._runtime_parameters or {}).keys())
        mappings = sorted((self._parameter_mappings or {}).keys())

        if params:
            param_menu = menu.addMenu("插入参数")
            for name in params:
                param_menu.addAction(
                    name,
                    lambda checked=False, n=name: self._insert_text_at_cursor(
                        line_edit, "${" + n + "}"
                    ),
                )
        else:
            action = menu.addAction("暂无可用参数")
            action.setEnabled(False)

        if params and mappings:
            mapped_menu = menu.addMenu("插入参数映射")
            for mapping_name in mappings:
                sub = mapped_menu.addMenu(mapping_name)
                for param_name in params:
                    sub.addAction(
                        param_name,
                        lambda checked=False, p=param_name, m=mapping_name: self._insert_text_at_cursor(
                            line_edit, "${" + p + "|map:" + m + "}"
                        ),
                    )
        elif mappings:
            action = menu.addAction("先定义参数后再引入映射")
            action.setEnabled(False)

        menu.exec_(line_edit.mapToGlobal(line_edit.rect().bottomRight()))

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

    def _init_base_ui(self):
        soft_theme = self._mix_hex_color(self.theme_color, "#FFFFFF", 0.90)
        softer_theme = self._mix_hex_color(self.theme_color, "#FFFFFF", 0.96)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.scroll_area.setStyleSheet(
            "QScrollArea { background-color: transparent; border: none; }"
        )

        self.content_widget = QWidget()
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
        self.panel_badge = QLabel(self.action_name)
        self.panel_badge.setObjectName("panel_badge")
        header_layout.addLayout(title_stack, stretch=1)
        self.panel_hint.hide()
        self.panel_badge.hide()
        self.main_layout.addWidget(self.panel_header)

        self.top_form = QFormLayout()
        self.top_form.setHorizontalSpacing(12)
        self.top_form.setVerticalSpacing(8)
        self.top_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        has_top = self.use_df or self.use_type
        if has_top:
            top_card, top_inner = self._make_card("基础配置")
            self.main_layout.addWidget(top_card)
            top_inner.addLayout(self.top_form)

        if self.use_df:
            self.df_combo = QComboBox()
            self.combo_boxes_to_update.append(self.df_combo)
            self.df_combo.currentTextChanged.connect(self._on_df_combo_changed)
            self.top_form.addRow("目标表:", self.df_combo)
            self.df_summary = QLabel("未选择数据表")
            self.df_summary.setObjectName("df_summary")
            self.top_form.addRow("", self.df_summary)

        if self.use_type:
            self.type_combo = QComboBox()
            self.type_combo.addItems(["列名", "字母", "索引"])
            self.top_form.addRow("匹配模式:", self.type_combo)

        self.custom_layout = QVBoxLayout()
        self.custom_layout.setSpacing(8)
        self.main_layout.addLayout(self.custom_layout)
        self.init_custom_ui()

        self.bottom_form = QFormLayout()
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

        self.main_layout.addStretch()
        self.scroll_area.setWidget(self.content_widget)
        outer_layout.addWidget(self.scroll_area)

        btn_layout = QVBoxLayout()
        btn_layout.setContentsMargins(12, 8, 12, 12)
        btn = QPushButton(f"单步执行并更新")
        btn.setObjectName("primary_execute")
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {self.theme_color}; color: white; "
            f"height: 40px; font-weight: bold; border-radius: 8px; font-size: 13px; "
            f"border: none; }}"
            f"QPushButton:hover {{ background-color: {self.theme_color}; opacity: 0.85; }}"
        )
        btn.clicked.connect(self._on_execute)
        btn_layout.addWidget(btn)

        outer_layout.addLayout(btn_layout)
        self._install_child_filters(self)
        self._install_parameter_actions()

    def _on_execute(self):
        ok, _ = self._validate()
        if not ok:
            return
        self._resolve_params_on_get = True
        self._last_raw_params = None
        try:
            self.execute()
        except Exception as exc:
            QMessageBox.warning(self, "参数解析失败", str(exc))
        finally:
            self._resolve_params_on_get = False

    def _on_df_combo_changed(self, *_):
        self._refresh_df_summary()
        self._refresh_col_combos()

    def _refresh_df_summary(self):
        if not hasattr(self, "df_summary"):
            return
        df_name = self.df_combo.currentText().strip() if hasattr(self, "df_combo") else ""
        df = self.data_pool.get(df_name) if df_name else None
        if df is None:
            self.df_summary.setText("未选择数据表")
            return
        rows, cols = df.shape
        self.df_summary.setText(f"{rows:,} 行 · {cols:,} 列")

    def set_params(self, p):
        if self.use_df and "df_name" in p:
            self.df_combo.setCurrentText(p["df_name"])
            self._refresh_df_summary()
        if self.use_type:
            _type_map = {"col_name": "列名", "col_word": "字母", "col_index": "索引"}
            ct = p.get("col_type", "")
            if ct in _type_map:
                self.type_combo.setCurrentText(_type_map[ct])
        if self.use_out and "out_name" in p:
            self.out_input.setText(p["out_name"])
        self.set_custom_params(p)

    def get_params(self):
        p = {}
        if self.use_df:
            p["df_name"] = self.df_combo.currentText()
        if self.use_type:
            _type_map = {"列名": "col_name", "字母": "col_word", "索引": "col_index"}
            p["col_type"] = _type_map.get(self.type_combo.currentText(), "col_name")
        if self.use_out:
            p["out_name"] = self.out_input.text().strip()
        p.update(self.get_custom_params())
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
        if self.use_out:
            self.out_input.clear()
        self.clear_custom_ui()

    def _set_combo_by_prefix(self, combo, prefix):
        if not prefix:
            return
        for i in range(combo.count()):
            if combo.itemText(i).startswith(prefix):
                return combo.setCurrentIndex(i)

    def _get_col_name(self, combo):
        """从下拉框提取列名"""
        return combo.currentText().strip()

    def _set_col_name(self, combo, name):
        """设置下拉框为指定列名"""
        if not name:
            return
        combo.setCurrentText(str(name))

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
            widget.setPlaceholderText(f"必填: {label}" if label else "此项必填")
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
        header_btn = QPushButton(f" ▾ {summary}" if summary else " ▾ 规则")
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
        body = QWidget()
        body.setVisible(True)
        body.setStyleSheet("QWidget { background: #FFFFFF; border: none; }")
        cl.addWidget(body)

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
        label.setFixedWidth(34)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
        return label

    def clear_dynamic_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _make_col_combo(self, placeholder="选择列", dtype_filter=None):
        """创建可编辑的列名下拉框。dtype_filter: 'numeric'/'datetime'/'string'/None(全部)"""
        combo = QComboBox()
        combo.setEditable(True)
        combo.setPlaceholderText(placeholder)
        if combo.lineEdit():
            combo.lineEdit().setPlaceholderText(placeholder)
        combo.setMinimumWidth(110)
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
        if not hasattr(self, "_col_combos"):
            return
        df_name = self.df_combo.currentText() if self.use_df else ""
        df = self.data_pool.get(df_name) if df_name else None
        all_cols = list(df.columns) if df is not None else []

        # 按 dtype_filter 缓存列分组，避免同一过滤条件重复扫描
        filtered_cache = {}

        valid_combos = []
        for combo in self._col_combos:
            try:
                cur = combo.currentText()
            except RuntimeError:
                continue
            valid_combos.append(combo)

            dtype_filter = self._col_combo_filters.get(combo)
            if dtype_filter and df is not None:
                if dtype_filter not in filtered_cache:
                    filtered_cache[dtype_filter] = [
                        c for c in all_cols if self._col_matches_dtype(df[c], dtype_filter)
                    ]
                cols = filtered_cache[dtype_filter]
            else:
                cols = all_cols

            combo.blockSignals(True)
            combo.clear()
            if cols:
                combo.addItems(cols)
            combo.blockSignals(False)
            if cur:
                idx = combo.findData(cur)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setCurrentText(cur)
        self._col_combos = valid_combos
        if hasattr(self, "_col_combo_filters"):
            self._col_combo_filters = {
                cb: f for cb, f in self._col_combo_filters.items()
                if cb in valid_combos
            }

    def update_combos(self, table_names):
        for combo in self.combo_boxes_to_update:
            current = combo.currentText()
            combo.clear()
            combo.addItems(table_names)
            if current in table_names:
                combo.setCurrentText(current)
            elif combo.count() > 0:
                combo.setCurrentIndex(0)
        self._refresh_df_summary()
        self._refresh_col_combos()

    def init_custom_ui(self):
        pass

    def set_custom_params(self, p):
        pass

    def get_custom_params(self):
        return {}

    def clear_custom_ui(self):
        pass

    def execute(self):
        pass


