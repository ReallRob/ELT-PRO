import os
import sys
import copy
import pandas as pd
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QFrame,
    QPushButton,
    QComboBox,
    QLineEdit,
    QLabel,
    QMessageBox,
    QFileDialog,
    QScrollArea,
    QMenu,
    QAction,
    QStyle,
)
from PyQt5.QtGui import QCursor
from PyQt5.QtCore import Qt, pyqtSignal, QEvent

from xlsx_fun import (
    get_col_data,
    filter_data,
    group_calc,
    left_join,
    rank_col,
    sort_data,
    calc_col,
    clean_data,
    export_df,
    normalize_columns,
    pivot_table,
    melt_table,
    concat_rows,
    drop_duplicates,
    sample_data,
    describe_data,
    transpose_data,
    cumsum_data,
    pct_change_data,
)
from parameter_resolver import (
    clone_resolved_runtime_value,
    normalize_parameter_mappings,
    normalize_runtime_parameters,
)
from parameter_input import ParameterTextInput, ParameterTextEdit

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
                border-radius: 8px;
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
                font-size: 15px;
                font-weight: bold;
                border: none;
            }}
            QLabel#panel_hint {{
                color: #607D8B;
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
                min-width: 100px;
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
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(10)
        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(2)
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
        header_layout.addWidget(self.panel_badge, alignment=Qt.AlignTop)
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
        combo.setMinimumWidth(120)
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


class LoadFilePanel(BaseToolPanel):
    use_df = False
    use_type = False
    theme_color = "#1976D2"
    action_name = "导入"

    def init_custom_ui(self):
        card, inner = self._make_card("数据源配置")
        self.custom_layout.addWidget(card)

        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.set_parameter_enabled(False)
        self.path_input.setPlaceholderText("选择源文件 (.xlsx / .csv)")
        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self.browse_path)
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(btn_browse)

        fl = QFormLayout()
        fl.addRow("文件路径:", path_layout)
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentTextChanged.connect(self.auto_update_out_name)
        fl.addRow("工作表(Excel):", self.sheet_combo)
        self.skip_input = QLineEdit("0")
        fl.addRow("跳过前N行:", self.skip_input)
        self.nrows_input = QLineEdit()
        self.nrows_input.setPlaceholderText("读取行数 (留空为全部)")
        fl.addRow("限制行数:", self.nrows_input)
        inner.addLayout(fl)

    def browse_path(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择数据源", "", "Excel/CSV (*.xlsx *.xls *.csv)"
        )
        if path:
            self.path_input.setText(path)
            self.update_sheets(path)

    def update_sheets(self, path):
        self.sheet_combo.clear()
        if path.endswith((".xlsx", ".xls")):
            try:
                sheets = pd.ExcelFile(path).sheet_names
                self.sheet_combo.addItems(sheets)
            except:
                pass
        else:
            self.sheet_combo.addItem("CSV (无工作表)")

    def auto_update_out_name(self, text):
        if not text:
            return
        if text == "CSV (无工作表)":
            if self.path_input.text():
                base_name = os.path.basename(self.path_input.text()).split(".")[0]
                self.out_input.setText(base_name)
        else:
            self.out_input.setText(text)

    def get_custom_params(self):
        return {
            "file_path": self.path_input.text().strip(),
            "sheet_name": (
                self.sheet_combo.currentText() if self.sheet_combo.count() > 0 else 0
            ),
            "skiprows": int(self.skip_input.text() or 0),
            "nrows": (
                int(self.nrows_input.text())
                if self.nrows_input.text().strip()
                else None
            ),
        }

    def set_custom_params(self, p):
        if "file_path" in p:
            self.path_input.setText(p["file_path"])
            self.update_sheets(p["file_path"])
        if "sheet_name" in p:
            self.sheet_combo.setCurrentText(str(p["sheet_name"]))
        if "skiprows" in p:
            self.skip_input.setText(str(p["skiprows"]))
        if "nrows" in p and p["nrows"] is not None:
            self.nrows_input.setText(str(p["nrows"]))

    def execute(self):
        p = self.get_params()
        if not p["file_path"] or not os.path.exists(p["file_path"]):
            return QMessageBox.warning(self, "错误", "请选择有效的文件路径！")

        out_name = p["out_name"] or os.path.basename(p["file_path"]).split(".")[0]
        try:
            if p["file_path"].endswith((".xlsx", ".xls")):
                sheet = p["sheet_name"] if p["sheet_name"] != "CSV (无工作表)" else 0
                df = pd.read_excel(
                    p["file_path"],
                    sheet_name=sheet,
                    skiprows=p["skiprows"],
                    nrows=p["nrows"],
                )
            else:
                df = pd.read_csv(
                    p["file_path"], skiprows=p["skiprows"], nrows=p["nrows"]
                )
            self.step_recorded.emit("load_file", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))


class ExtractPanel(BaseToolPanel):
    theme_color = "#009688"
    action_name = "提取"

    def init_custom_ui(self):
        self.fill_input = QLineEdit()
        self.fill_input.setPlaceholderText("可选: 缺失值填充...")
        self.top_form.addRow("填充空值:", self.fill_input)

        card, inner = self._make_card("提取列及重命名")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加提取列")
        btn_add.setStyleSheet(
            "QPushButton { background: #E0F2F1; border: 1px dashed #80CBC4; "
            "border-radius: 4px; padding: 6px; color: #00695C; font-size: 12px; }"
            "QPushButton:hover { background: #B2DFDB; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)

    def clear_custom_ui(self):
        self.fill_input.clear()
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", rename=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("选择列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("重命名(可选)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(r_input)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def set_custom_params(self, p):
        if "fill_value" in p:
            self.fill_input.setText(str(p["fill_value"] or ""))
        col_list, col_names = p.get("col_list", []), p.get("col_names", [])
        if col_list:
            self.clear_dynamic_layout(self.rules_layout)
            for i, c in enumerate(col_list):
                r = col_names[i] if col_names and i < len(col_names) else ""
                self.add_rule_row(c, r)

    def get_custom_params(self):
        clist, rlist = [], []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c = self._get_col_name(w.findChild(QComboBox, "col"))
                r = w.findChild(QLineEdit, "rename").text().strip()
                if c:
                    clist.append(c)
                    rlist.append(r)
        return {
            "col_list": clist,
            "col_names": rlist,
            "fill_value": self.fill_input.text() or None,
        }

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["col_list"]:
            return QMessageBox.warning(self, "错误", "缺少参数")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            actual_cols = normalize_columns(
                self.data_pool[p["df_name"]], p["col_list"], p["col_type"]
            )
            final_cols = [
                p["col_names"][i] if p["col_names"][i] else actual_cols[i]
                for i in range(len(actual_cols))
            ]
            df = get_col_data(
                self.data_pool[p["df_name"]],
                p["col_list"],
                p["col_type"],
                p["fill_value"],
                final_cols,
            )
            self.step_recorded.emit("get_col_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class FilterPanel(BaseToolPanel):
    theme_color = "#E91E63"
    action_name = "筛选"

    OP_MAP = {
        "大于": ">", "小于": "<", "大于等于": ">=", "小于等于": "<=",
        "等于": "==", "不等于": "!=",
        "包含": "contains", "不包含": "not_contains",
        "开头是": "startswith", "结尾是": "endswith",
        "为空": "isnull", "不为空": "notnull",
    }
    OP_REV = {v: k for k, v in OP_MAP.items()}

    def init_custom_ui(self):
        self.logic_combo = QComboBox()
        self.logic_combo.addItems(["AND (满足所有)", "OR (满足其一)"])
        self.top_form.addRow("条件逻辑:", self.logic_combo)

        card, inner = self._make_card("筛选条件")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule()
        btn_add = QPushButton("+ 添加筛选条件")
        btn_add.setStyleSheet(
            "QPushButton { background: #FCE4EC; border: 1px dashed #F48FB1; "
            "border-radius: 4px; padding: 6px; color: #880E4F; font-size: 12px; }"
            "QPushButton:hover { background: #F8BBD0; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule())
        inner.addWidget(btn_add)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule()

    def add_rule(self, col="", op="等于", val=""):
        summary = f"{col or '?'} {op} {val}" if col or val else "新筛选条件"
        container, header_btn, body = self._make_collapsible_rule(summary)

        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(6, 6, 6, 6)
        col_combo = self._make_col_combo("排查列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        col_combo.currentTextChanged.connect(
            lambda: self._update_filter_summary(container, header_btn)
        )
        op_combo = QComboBox()
        op_combo.setObjectName("op")
        op_combo.addItems(list(self.OP_MAP.keys()))
        if op in self.OP_MAP:
            op_combo.setCurrentText(op)
        elif op in self.OP_REV:
            op_combo.setCurrentText(self.OP_REV[op])
        op_combo.currentTextChanged.connect(
            lambda: self._update_filter_summary(container, header_btn)
        )
        v_input = QLineEdit(str(val))
        v_input.setObjectName("val")
        v_input.setPlaceholderText("目标值")
        v_input.textChanged.connect(
            lambda: self._update_filter_summary(container, header_btn)
        )
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(container.deleteLater)
        body_layout.addWidget(col_combo)
        body_layout.addWidget(op_combo)
        body_layout.addWidget(v_input)
        body_layout.addWidget(btn_rm)

        # assign objectNames to body widgets too for get_custom_params
        body.setObjectName("rule_body")

        self.rules_layout.addWidget(container)

    def _update_filter_summary(self, container, header_btn):
        body = container.findChild(QWidget, "rule_body")
        if not body:
            return
        col_combo = body.findChild(QComboBox, "col")
        op_combo = body.findChild(QComboBox, "op")
        v_input = body.findChild(QLineEdit, "val")
        c = self._get_col_name(col_combo) if col_combo else "?"
        o = op_combo.currentText() if op_combo else "?"
        v = v_input.text() if v_input else ""
        summary = f"{c or '?'} {o} {v}" if (c or v) else "新筛选条件"
        self._update_rule_summary(header_btn, summary)

    def set_custom_params(self, p):
        self._set_combo_by_prefix(self.logic_combo, p.get("logic"))
        conds = p.get("conditions", [])
        if conds:
            self.clear_dynamic_layout(self.rules_layout)
            for c in conds:
                self.add_rule(c.get("col"), c.get("op"), c.get("value"))

    def get_custom_params(self):
        conds = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c = self._get_col_name(w.findChild(QComboBox, "col"))
                op_cn = w.findChild(QComboBox, "op").currentText()
                op = self.OP_MAP.get(op_cn, "==")
                v = w.findChild(QLineEdit, "val").text().strip()
                if c:
                    conds.append({"col": c, "op": op, "value": v})
        return {
            "logic": self.logic_combo.currentText().split(" ")[0],
            "conditions": conds,
        }

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "缺少目标表")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = filter_data(
                self.data_pool[p["df_name"]], p["conditions"], p["logic"], p["col_type"]
            )
            self.step_recorded.emit("filter_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class GroupPanel(BaseToolPanel):
    theme_color = "#673AB7"
    action_name = "汇总"

    def init_custom_ui(self):
        card1, inner1 = self._make_card("分组依据列")
        self.custom_layout.addWidget(card1)
        self.group_keys_layout = QVBoxLayout()
        self.group_keys_layout.setSpacing(4)
        inner1.addLayout(self.group_keys_layout)
        self.add_group_key_row()
        btn_add_key = QPushButton("+ 添加分组列")
        btn_add_key.setStyleSheet(
            "QPushButton { background: #EDE7F6; border: 1px dashed #B39DDB; "
            "border-radius: 4px; padding: 6px; color: #4527A0; font-size: 12px; }"
            "QPushButton:hover { background: #D1C4E9; }"
        )
        btn_add_key.clicked.connect(lambda: self.add_group_key_row())
        inner1.addWidget(btn_add_key)

        card2, inner2 = self._make_card("聚合统计规则")
        self.custom_layout.addWidget(card2)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner2.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加聚合规则")
        btn_add.setStyleSheet(
            "QPushButton { background: #EDE7F6; border: 1px dashed #B39DDB; "
            "border-radius: 4px; padding: 6px; color: #4527A0; font-size: 12px; }"
            "QPushButton:hover { background: #D1C4E9; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner2.addWidget(btn_add)
        hint = QLabel("sum(求和), mean(平均), max, min, count(计数), first(取第一行)")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        inner2.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.group_keys_layout)
        self.add_group_key_row()
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_group_key_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("分组列")
        col_combo.setObjectName("group_col")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.group_keys_layout.addWidget(row)

    def add_rule_row(self, col="", func="sum", rename=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("运算列", dtype_filter="numeric")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        f_combo = QComboBox()
        f_combo.setObjectName("func")
        f_combo.addItems(["sum", "mean", "max", "min", "count", "first"])
        f_combo.setCurrentText(func)
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("重命名(可选)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(f_combo)
        l.addWidget(r_input)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def set_custom_params(self, p):
        g_keys = p.get("group_key", [])
        if g_keys:
            self.clear_dynamic_layout(self.group_keys_layout)
            for k in g_keys:
                self.add_group_key_row(k)
        rules = p.get("agg_rules", [])
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(r.get("col"), r.get("func"), r.get("rename"))

    def get_custom_params(self):
        g_keys = []
        for i in range(self.group_keys_layout.count()):
            w = self.group_keys_layout.itemAt(i).widget()
            if w:
                combo = w.findChild(QComboBox, "group_col")
                if combo:
                    c = self._get_col_name(combo)
                    if c:
                        g_keys.append(c)
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c = self._get_col_name(w.findChild(QComboBox, "col"))
                f = w.findChild(QComboBox, "func").currentText()
                r = w.findChild(QLineEdit, "rename").text().strip()
                if c:
                    rules.append({"col": c, "func": f, "rename": r})
        return {"group_key": g_keys, "agg_rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["group_key"]:
            return QMessageBox.warning(self, "错误", "缺少必要参数")
        col_dict = {}
        for r in p["agg_rules"]:
            c, f = r["col"], r["func"]
            if c in col_dict:
                (
                    col_dict[c].append(f)
                    if isinstance(col_dict[c], list)
                    else col_dict.update({c: [col_dict[c], f]})
                )
            else:
                col_dict[c] = f
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = group_calc(
                self.data_pool[p["df_name"]], p["group_key"], col_dict, p["col_type"]
            )
            rename_dict = {}
            for rule in p["agg_rules"]:
                if rule["rename"]:
                    actual_cols = normalize_columns(
                        self.data_pool[p["df_name"]], [rule["col"]], p["col_type"]
                    )
                    if actual_cols:
                        rename_dict[f"{actual_cols[0]}_{rule['func']}"] = rule["rename"]
            if rename_dict:
                df = df.rename(columns=rename_dict)
            self.step_recorded.emit("group_calc", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class JoinPanel(BaseToolPanel):
    use_df = False
    theme_color = "#4CAF50"
    action_name = "连接"

    def _refresh_col_combos(self):
        """JoinPanel 使用右表(df2_combo)的列名"""
        if not hasattr(self, "_col_combos"):
            return
        df_name = self.df2_combo.currentText() if hasattr(self, "df2_combo") else ""
        df = self.data_pool.get(df_name) if df_name else None
        all_cols = list(df.columns) if df is not None else []

        valid_combos = []
        for combo in self._col_combos:
            try:
                cur = combo.currentText()
            except RuntimeError:
                continue
            valid_combos.append(combo)

            dtype_filter = self._col_combo_filters.get(combo) if hasattr(self, "_col_combo_filters") else None
            if dtype_filter and df is not None:
                cols = [c for c in all_cols if self._col_matches_dtype(df[c], dtype_filter)]
            else:
                cols = all_cols

            combo.blockSignals(True)
            combo.clear()
            if cols:
                for c in cols:
                    try:
                        dt = str(df[c].dtype)
                        if "int" in dt:       tag = "int"
                        elif "float" in dt:   tag = "float"
                        elif "datetime" in dt: tag = "date"
                        elif "bool" in dt:    tag = "bool"
                        else:                 tag = "str"
                    except Exception:
                        tag = "?"
                    combo.addItem(c, userData=c)
                    combo.setItemData(combo.count() - 1, f"类型: {tag}", Qt.ToolTipRole)
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

    def init_custom_ui(self):
        self.df1_combo = QComboBox()
        self.df2_combo = QComboBox()
        self.combo_boxes_to_update.extend([self.df1_combo, self.df2_combo])
        self.top_form.insertRow(0, "主表 (左):", self.df1_combo)
        self.top_form.insertRow(1, "匹配表 (右):", self.df2_combo)
        self.l_key = QLineEdit()
        self.r_key = QLineEdit()
        self.top_form.addRow("左表匹配键:", self.l_key)
        self.top_form.addRow("右表匹配键:", self.r_key)
        card, inner = self._make_card("提取右表列及重命名")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加提取列")
        btn_add.setStyleSheet(
            "QPushButton { background: #E8F5E9; border: 1px dashed #81C784; "
            "border-radius: 4px; padding: 6px; color: #1B5E20; font-size: 12px; }"
            "QPushButton:hover { background: #C8E6C9; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)
        hint = QLabel("类似于 VLOOKUP，提取右表的列放入左表。")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        inner.addWidget(hint)

    def clear_custom_ui(self):
        self.l_key.clear()
        self.r_key.clear()
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", rename=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("右表列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("重命名(可选)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(r_input)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def set_custom_params(self, p):
        if "df1_name" in p:
            self.df1_combo.setCurrentText(p["df1_name"])
        if "df2_name" in p:
            self.df2_combo.setCurrentText(p["df2_name"])
        if "l_key" in p:
            self.l_key.setText(p["l_key"])
        if "r_key" in p:
            self.r_key.setText(p["r_key"])
        get_cols, col_names = p.get("get_cols", []), p.get("col_names", [])
        if get_cols:
            self.clear_dynamic_layout(self.rules_layout)
            for i, c in enumerate(get_cols):
                r = col_names[i] if col_names and i < len(col_names) else ""
                self.add_rule_row(c, r)

    def get_custom_params(self):
        get_cols, col_names = [], []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c = self._get_col_name(w.findChild(QComboBox, "col"))
                r = w.findChild(QLineEdit, "rename").text().strip()
                if c:
                    get_cols.append(c)
                    col_names.append(r)
        return {
            "df1_name": self.df1_combo.currentText(),
            "df2_name": self.df2_combo.currentText(),
            "l_key": self.l_key.text().strip(),
            "r_key": self.r_key.text().strip(),
            "get_cols": get_cols,
            "col_names": col_names,
        }

    def execute(self):
        p = self.get_params()
        if not p["df1_name"] or not p["df2_name"]:
            return QMessageBox.warning(self, "错误", "请选择表")
        if not p["get_cols"]:
            return QMessageBox.warning(self, "错误", "请配置提取列")
        out_name = p["out_name"] or f"{p['df1_name']}_{self.action_name}"
        try:
            actual_cols = normalize_columns(
                self.data_pool[p["df2_name"]], p["get_cols"], p["col_type"]
            )
            final_names = [
                p["col_names"][i] if p["col_names"][i] else actual_cols[i]
                for i in range(len(actual_cols))
            ]
            df = left_join(
                self.data_pool[p["df1_name"]],
                self.data_pool[p["df2_name"]],
                p["l_key"],
                p["r_key"],
                p["get_cols"],
                key_type=p["col_type"],
                col_names=final_names,
            )
            self.step_recorded.emit("left_join", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class RankPanel(BaseToolPanel):
    theme_color = "#2196F3"
    action_name = "排名"

    def init_custom_ui(self):
        card, inner = self._make_card("排名规则")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(6)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加排名规则")
        btn_add.setStyleSheet(
            "QPushButton { background: #E3F2FD; border: 1px dashed #90CAF9; "
            "border-radius: 4px; padding: 6px; color: #0D47A1; font-size: 12px; }"
            "QPushButton:hover { background: #BBDEFB; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)
        hint = QLabel(
            "min(中国式1,2,2,4) | dense(密集1,2,2,3) | max(1,3,3,4) | average | first(顺延)"
        )
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        inner.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", method="min", asc=True, rename=""):
        container = QWidget()
        container.setStyleSheet(
            "background-color: #F8F9FA; border: 1px solid #E0E0E0; border-radius: 4px;"
        )
        v_layout = QVBoxLayout(container)
        v_layout.setContentsMargins(5, 5, 5, 5)
        v_layout.setSpacing(4)
        h1 = QHBoxLayout()
        h1.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("排序列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("新列名 (必填)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.setStyleSheet("border:none; color: red;")
        btn_rm.clicked.connect(container.deleteLater)
        h1.addWidget(col_combo)
        h1.addWidget(QLabel("->"))
        h1.addWidget(r_input)
        h1.addWidget(btn_rm)
        h2 = QHBoxLayout()
        h2.setContentsMargins(0, 0, 0, 0)
        m_combo = QComboBox()
        m_combo.setObjectName("method")
        m_combo.addItems(["min", "dense", "max", "average", "first"])
        self._set_combo_by_prefix(m_combo, method.split(" ")[0])
        asc_combo = QComboBox()
        asc_combo.setObjectName("asc")
        asc_combo.addItems(["升序", "降序"])
        asc_combo.setCurrentIndex(0 if asc else 1)
        h2.addWidget(m_combo)
        h2.addWidget(asc_combo)
        v_layout.addLayout(h1)
        v_layout.addLayout(h2)
        self.rules_layout.addWidget(container)

    def set_custom_params(self, p):
        rules = p.get("rules", [])
        if not rules and "rank_cols" in p:
            for c in p.get("rank_cols", []):
                rules.append(
                    {
                        "col": c,
                        "method": "min",
                        "ascending": p.get("ascending", True),
                        "rename": "",
                    }
                )
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(
                    r.get("col"),
                    r.get("method", "min"),
                    r.get("ascending", True),
                    r.get("rename", ""),
                )

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                col_combo = w.findChild(QComboBox, "col")
                c = self._get_col_name(col_combo) if col_combo else ""
                r = w.findChild(QLineEdit, "rename").text().strip()
                m, asc = (
                    w.findChild(QComboBox, "method").currentText(),
                    w.findChild(QComboBox, "asc").currentIndex() == 0,
                )
                if c:
                    rules.append({"col": c, "method": m, "ascending": asc, "rename": r})
        return {"rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["rules"]:
            return QMessageBox.warning(self, "错误", "参数不完整")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = self.data_pool[p["df_name"]].copy()
            for rule in p["rules"]:
                df = rank_col(
                    df,
                    [rule["col"]],
                    [rule["rename"]] if rule["rename"] else [],
                    col_type=p["col_type"],
                    method=rule["method"],
                    ascending=rule["ascending"],
                )
            self.step_recorded.emit("rank_col", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class SortPanel(BaseToolPanel):
    theme_color = "#FF9800"
    action_name = "排序"

    def init_custom_ui(self):
        card, inner = self._make_card("排序规则 (从上到下优先级递减)")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加排序规则")
        btn_add.setStyleSheet(
            "QPushButton { background: #FFF3E0; border: 1px dashed #FFB74D; "
            "border-radius: 4px; padding: 6px; color: #E65100; font-size: 12px; }"
            "QPushButton:hover { background: #FFE0B2; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)
        hint = QLabel("升序(从小到大), 降序(从大到小), 自定义(手写词典如: 高,中,低)")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        inner.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", asc=True, custom_order=None):
        if custom_order is None:
            custom_order = []
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 8)
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("排序列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        asc_combo = QComboBox()
        asc_combo.setObjectName("asc")
        asc_combo.addItems(["升序", "降序", "自定义"])
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(container.deleteLater)
        h.addWidget(col_combo)
        h.addWidget(asc_combo)
        h.addWidget(btn_rm)
        v.addLayout(h)

        # 自定义排序区域（动态行）
        cus_area = QWidget()
        cus_area.setObjectName("custom_area")
        cl = QVBoxLayout(cus_area)
        cl.setContentsMargins(12, 4, 0, 0)
        cl.setSpacing(3)

        def _add_cus_row(val=""):
            cr = QWidget()
            rl = QHBoxLayout(cr)
            rl.setContentsMargins(0, 0, 0, 0)
            inp = QLineEdit(str(val))
            inp.setObjectName("custom_val")
            inp.setPlaceholderText("排序值")
            inp.setMinimumWidth(80)
            rm = QPushButton("×")
            rm.setFixedWidth(22)
            rm.clicked.connect(cr.deleteLater)
            rl.addWidget(inp)
            rl.addWidget(rm)
            rl.addStretch()
            cl.addWidget(cr)

        for val in custom_order:
            _add_cus_row(val)

        btn_add_cus = QPushButton("+ 添加排序值")
        btn_add_cus.setStyleSheet(
            "QPushButton { background: #FFF8E1; border: 1px dashed #FFB300; "
            "border-radius: 3px; padding: 3px 8px; font-size: 11px; color: #E65100; }"
            "QPushButton:hover { background: #FFECB3; }"
        )
        btn_add_cus.clicked.connect(lambda: _add_cus_row())
        cl.addWidget(btn_add_cus)

        cus_area.setVisible(asc_combo.currentIndex() == 2)
        if custom_order:
            asc_combo.setCurrentIndex(2)
        else:
            asc_combo.setCurrentIndex(0 if asc else 1)
        asc_combo.currentIndexChanged.connect(
            lambda idx, ca=cus_area: ca.setVisible(idx == 2)
        )
        v.addWidget(cus_area)
        self.rules_layout.addWidget(container)

    def set_custom_params(self, p):
        rules = p.get("sort_rules", [])
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(
                    r.get("col"), r.get("ascending"), r.get("custom_order", [])
                )

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if not w:
                continue
            col_combo = w.findChild(QComboBox, "col")
            c = self._get_col_name(col_combo) if col_combo else ""
            asc_idx = w.findChild(QComboBox, "asc").currentIndex()
            cus_vals = []
            if asc_idx == 2:
                ca = w.findChild(QWidget, "custom_area")
                if ca:
                    for inp in ca.findChildren(QLineEdit, "custom_val"):
                        v = inp.text().strip()
                        if v:
                            cus_vals.append(v)
            if c:
                rules.append({
                    "col": c,
                    "ascending": True if asc_idx == 2 else asc_idx == 0,
                    "custom_order": cus_vals,
                })
        return {"sort_rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["sort_rules"]:
            return QMessageBox.warning(self, "错误", "参数缺失")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = sort_data(
                self.data_pool[p["df_name"]], p["sort_rules"], col_type=p["col_type"]
            )
            self.step_recorded.emit("sort_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class CalcPanel(BaseToolPanel):
    use_type = False
    theme_color = "#00BCD4"
    action_name = "计算"

    def init_custom_ui(self):
        card, inner = self._make_card("计算公式")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加新公式列")
        btn_add.setStyleSheet(
            "QPushButton { background: #E0F7FA; border: 1px dashed #4DD0E1; "
            "border-radius: 4px; padding: 6px; color: #006064; font-size: 12px; }"
            "QPushButton:hover { background: #B2EBF2; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)

        hint = QLabel("列名务必用中括号包裹。如: ([销售额] - [成本]) * 0.1")
        hint.setStyleSheet(
            "color: #E65100; font-size: 11px; font-weight: bold; "
            "background: #FFF8E1; border-radius: 4px; padding: 6px; border: none;"
        )
        inner.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, new_col="", formula=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        n_input = QLineEdit(str(new_col))
        n_input.setObjectName("new_col")
        n_input.setPlaceholderText("新列名")
        f_input = ParameterTextEdit(str(formula))
        f_input.setObjectName("formula")
        f_input.setPlaceholderText("表达式 (如: [销售额]*0.1)")
        f_input.setMinimumHeight(72)

        btn_insert = QPushButton("📥")
        btn_insert.setFixedWidth(28)
        btn_insert.setToolTip("插入列名到公式")
        btn_insert.setStyleSheet(
            "QPushButton { background: #E0F7FA; border: 1px solid #B2EBF2; "
            "border-radius: 3px; font-size: 12px; }"
            "QPushButton:hover { background: #B2EBF2; }"
        )
        btn_insert.clicked.connect(lambda checked, fi=f_input: self._show_col_menu(fi))

        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(n_input)
        l.addWidget(f_input)
        l.addWidget(btn_insert)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def _show_col_menu(self, target_input):
        df_name = self.df_combo.currentText() if self.use_df else ""
        cols = []
        if df_name and df_name in self.data_pool:
            cols = list(self.data_pool[df_name].columns)
        if not cols:
            QMessageBox.information(self, "提示", "当前目标表无可用列，请先选择数据源。")
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: white; border: 1px solid #DDD; border-radius: 4px; }
            QMenu::item { padding: 6px 16px; font-size: 12px; font-family: monospace; }
            QMenu::item:selected { background: #E0F7FA; color: #006064; }
        """)
        for col in cols:
            action = menu.addAction(f"[{col}]")
            action.triggered.connect(
                lambda checked, c=col, fi=target_input: self._insert_col_at_cursor(fi, c)
            )
        # show near the button
        menu.exec_(QCursor.pos())

    def _insert_col_at_cursor(self, line_edit, col_name):
        text = line_edit.text()
        pos = line_edit.cursorPosition()
        insert = f"[{col_name}]"
        new_text = text[:pos] + insert + text[pos:]
        line_edit.setText(new_text)
        line_edit.setCursorPosition(pos + len(insert))
        line_edit.setFocus()

    def set_custom_params(self, p):
        rules = p.get("rules", [])
        if not rules and "new_col_name" in p:
            rules = [{"new_col_name": p["new_col_name"], "formula": p["formula"]}]
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(r.get("new_col_name"), r.get("formula"))

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                n, f = (
                    w.findChild(QLineEdit, "new_col").text().strip(),
                    (w.findChild(ParameterTextEdit, "formula") or w.findChild(QLineEdit, "formula")).text().strip(),
                )
                if n and f:
                    rules.append({"new_col_name": n, "formula": f})
        return {"rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["rules"]:
            return QMessageBox.warning(self, "错误", "参数缺失")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = self.data_pool[p["df_name"]].copy()
            for rule in p["rules"]:
                df = calc_col(df, rule["new_col_name"], rule["formula"])
            self.step_recorded.emit("calc_col", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class CleanPanel(BaseToolPanel):
    theme_color = "#FF5722"
    action_name = "清洗"

    ACT_CN_MAP = {
        "转数字": "to_numeric", "转文本": "to_string", "转整数": "to_int",
        "转浮点": "to_float", "转日期": "to_datetime",
        "去空格": "strip_space", "填空值": "fill_na", "删空行": "drop_na",
        "文本替换": "replace", "转大写": "upper_case", "转小写": "lower_case",
        "四舍五入": "round_val", "裁剪范围": "clip",
    }
    ACT_EN_MAP = {v: k for k, v in ACT_CN_MAP.items()}
    ACT_PARAM_SPECS = {
        "填空值":   [("param_val", "填充值")],
        "文本替换": [("param_val", "旧文本→新文本")],
        "四舍五入": [("param_val", "小数位")],
        "裁剪范围": [("param_val", "最小值,最大值")],
        "转日期":   [("param_val", "@date")],
    }
    DATE_FORMATS = [
        ("自动识别", ""), ("YYYY-MM-DD", "%Y-%m-%d"),
        ("YYYY/MM/DD", "%Y/%m/%d"), ("YYYY年MM月DD日", "%Y年%m月%d日"),
        ("DD/MM/YYYY", "%d/%m/%Y"), ("MM/DD/YYYY", "%m/%d/%Y"),
        ("YYYYMMDD", "%Y%m%d"), ("自定义...", "__custom__"),
    ]

    def init_custom_ui(self):
        card, inner = self._make_card("清洗规则 (从上到下执行)")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule()
        btn_add = QPushButton("+ 添加清洗规则")
        btn_add.setStyleSheet(
            "QPushButton { background: #FBE9E7; border: 1px dashed #FFAB91; "
            "border-radius: 4px; padding: 6px; color: #BF360C; font-size: 12px; }"
            "QPushButton:hover { background: #FFCCBC; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule())
        inner.addWidget(btn_add)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)

    def add_rule(self, col="", action="to_numeric", fill_val=""):
        cn_action = self.ACT_EN_MAP.get(action, action)
        summary = f"{col or '?'} -> {cn_action}" if col else "新清洗规则"
        container, header_btn, body = self._make_collapsible_rule(summary)
        body.setObjectName("rule_body")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(6, 6, 6, 6)
        body_layout.setSpacing(4)

        row1 = QHBoxLayout()
        col_combo = self._make_col_combo("清洗列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        col_combo.currentTextChanged.connect(
            lambda: self._update_clean_summary(container, header_btn))
        action_combo = QComboBox()
        action_combo.setObjectName("action")
        action_combo.addItems(list(self.ACT_CN_MAP.keys()))
        action_combo.setCurrentText(cn_action)
        action_combo.currentTextChanged.connect(
            lambda t, c=container, h=header_btn:
                (self._update_clean_summary(c, h), self._build_clean_params(c, t)))
        btn_rm = QPushButton("x")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(container.deleteLater)
        row1.addWidget(col_combo)
        row1.addWidget(action_combo)
        row1.addWidget(btn_rm)
        body_layout.addLayout(row1)
        self._build_clean_params(container, cn_action, fill_val)
        self.rules_layout.addWidget(container)

    def _build_clean_params(self, container, cn_action, fill_val=""):
        old = container.findChild(QWidget, "param_area")
        if old:
            container.layout().removeWidget(old)
            old.deleteLater()
        specs = self.ACT_PARAM_SPECS.get(cn_action)
        if not specs:
            return
        area = QWidget()
        area.setObjectName("param_area")
        al = QHBoxLayout(area)
        al.setContentsMargins(2, 2, 2, 0)
        for obj_name, placeholder in specs:
            if placeholder == "@date":
                fmt_combo = QComboBox()
                fmt_combo.setObjectName("fill")
                for label, code in self.DATE_FORMATS:
                    fmt_combo.addItem(label, userData=code)
                if fill_val:
                    idx = fmt_combo.findData(fill_val)
                    fmt_combo.setCurrentIndex(idx if idx >= 0 else len(self.DATE_FORMATS)-1)
                else:
                    fmt_combo.setCurrentIndex(0)
                custom_input = QLineEdit()
                custom_input.setObjectName("fill_custom")
                custom_input.setPlaceholderText("自定义格式...")
                custom_input.setMinimumWidth(100)
                custom_input.setVisible(
                    fmt_combo.currentData() == "__custom__")
                if custom_input.isVisible() and fill_val:
                    custom_input.setText(fill_val)
                fmt_combo.currentTextChanged.connect(
                    lambda t, ci=custom_input, fc=fmt_combo:
                        ci.setVisible(fc.currentData() == "__custom__"))
                al.addWidget(QLabel("格式:"))
                al.addWidget(fmt_combo)
                al.addWidget(custom_input)
            else:
                inp = QLineEdit()
                inp.setObjectName("fill")
                inp.setPlaceholderText(placeholder)
                inp.setMinimumWidth(80)
                if fill_val:
                    inp.setText(str(fill_val))
                al.addWidget(inp)
        al.addStretch()
        container.layout().addWidget(area)

    def _update_clean_summary(self, container, header_btn):
        body = container.findChild(QWidget, "rule_body")
        if not body: return
        col_combo = body.findChild(QComboBox, "col")
        action_combo = body.findChild(QComboBox, "action")
        c = self._get_col_name(col_combo) if col_combo else "?"
        a = action_combo.currentText() if action_combo else "?"
        self._update_rule_summary(header_btn, f"{c} -> {a}" if c != "?" else "新清洗规则")

    def set_custom_params(self, p):
        rules = p.get("rules", [])
        self.clear_dynamic_layout(self.rules_layout)
        if rules:
            for r in rules:
                self.add_rule(r.get("cols"), r.get("action"), r.get("fill_value"))
        else:
            self.add_rule()

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if not w: continue
            body = w.findChild(QWidget, "rule_body")
            if not body: continue
            col_combo = body.findChild(QComboBox, "col")
            c = self._get_col_name(col_combo) if col_combo else ""
            cn = body.findChild(QComboBox, "action").currentText()
            a = self.ACT_CN_MAP.get(cn, cn)
            if not c: continue
            fill_val = ""
            area = w.findChild(QWidget, "param_area")
            if area:
                fmt_combo = area.findChild(QComboBox, "fill")
                if fmt_combo:
                    code = fmt_combo.currentData()
                    if code == "__custom__":
                        ci = area.findChild(QLineEdit, "fill_custom")
                        fill_val = ci.text().strip() if ci else ""
                    else:
                        fill_val = code
                else:
                    plain = area.findChild(QLineEdit, "fill")
                    if plain: fill_val = plain.text().strip()
            rules.append({"cols": c, "action": a, "fill_value": fill_val})
        return {"rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["rules"]:
            return QMessageBox.warning(self, "错误", "参数缺失")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = clean_data(self.data_pool[p["df_name"]], p["rules"], p["col_type"])
            self.step_recorded.emit("clean_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))



class ExportNodePanel(BaseToolPanel):
    use_type = False
    use_out = False
    theme_color = "#607D8B"

    def init_custom_ui(self):
        card, inner = self._make_card("导出配置")
        self.custom_layout.addWidget(card)

        fl = QFormLayout()
        self.fname_input = QLineEdit("Export_Result.xlsx")
        fl.addRow("导出文件名:", self.fname_input)

        path_layout = QHBoxLayout()
        self.dir_input = QLineEdit()
        self.dir_input.set_parameter_enabled(False)
        self.dir_input.setPlaceholderText("留空默认为程序运行目录")
        btn_browse = QPushButton("浏览目录")
        btn_browse.clicked.connect(self.browse_dir)
        path_layout.addWidget(self.dir_input)
        path_layout.addWidget(btn_browse)
        fl.addRow("保存至目录:", path_layout)
        inner.addLayout(fl)

        hint = QLabel("支持 .xlsx 和 .csv 格式。目录留空则保存至程序根目录。")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        inner.addWidget(hint)

    def browse_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择保存目录", "")
        if folder:
            self.dir_input.setText(folder)

    def clear_custom_ui(self):
        self.fname_input.setText("Export_Result.xlsx")
        self.dir_input.clear()

    def set_custom_params(self, p):
        if "file_name" in p:
            self.fname_input.setText(p["file_name"])
        if "folder_path" in p:
            self.dir_input.setText(p["folder_path"])
        if "target_path" in p and not p.get("file_name"):
            full_path = p["target_path"]
            self.fname_input.setText(os.path.basename(full_path))
            self.dir_input.setText(os.path.dirname(full_path))

    def get_custom_params(self):
        return {
            "file_name": self.fname_input.text().strip(),
            "folder_path": self.dir_input.text().strip(),
            "out_name": "Export_Point",
        }

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "未选择导出表")

        default_dir = (
            Path(sys.executable).parent
            if getattr(sys, "frozen", False)
            else Path(__file__).parent.absolute()
        )
        fname = p.get("file_name") or "Result.xlsx"
        fdir = p.get("folder_path", "").strip()

        if not fdir:
            target_path = str(default_dir / fname)
        else:
            target_path = str(Path(fdir) / fname)

        try:
            success, final_path = export_df(
                self.data_pool[p["df_name"]], target_path, default_dir
            )
            if success:
                QMessageBox.information(self, "成功", f"文件已保存至：\n{final_path}")
            else:
                QMessageBox.warning(
                    self, "路径重定向", f"由于权限或路径问题，已转存至：\n{final_path}"
                )
            self.step_recorded.emit(
                "export_df", p, self.data_pool[p["df_name"]], "导出记录"
            )
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class ImportTemplatePanel(BaseToolPanel):
    use_df = False
    use_type = False
    theme_color = "#795548"
    action_name = "导入模板"

    def init_custom_ui(self):
        card, inner = self._make_card("模板配置")
        self.custom_layout.addWidget(card)

        path_layout = QHBoxLayout()
        self.template_input = QLineEdit()
        self.template_input.set_parameter_enabled(False)
        self.template_input.setPlaceholderText("选择模板文件 (.xlsx)")
        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self._browse_template)
        path_layout.addWidget(self.template_input)
        path_layout.addWidget(btn_browse)

        fl = QFormLayout()
        fl.addRow("模板文件:", path_layout)
        inner.addLayout(fl)

        self.info_label = QLabel("选择模板后自动扫描结构")
        self.info_label.setStyleSheet(
            "color: #888; font-size: 12px; padding: 8px; "
            "background: #FAFAFA; border-radius: 4px; border: none;"
        )
        inner.addWidget(self.info_label)

    def _browse_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择模板文件", "", "Excel (*.xlsx)")
        if not path:
            return
        self.template_input.setText(path)
        try:
            from template_engine import load_template
            _, meta = load_template(path)
            lines = [f"文件: {os.path.basename(path)}"]
            for sn, info in meta["sheets"].items():
                lines.append(f"  Sheet [{sn}]: {info['max_row']} 行 x {info['max_col']} 列")
            self.info_label.setText("\n".join(lines))
        except Exception as e:
            self.info_label.setText(f"加载失败: {e}")

    def clear_custom_ui(self):
        self.template_input.clear()
        self.info_label.setText("选择模板后自动扫描结构")

    def get_custom_params(self):
        return {"template_path": self.template_input.text().strip()}

    def set_custom_params(self, p):
        if "template_path" in p:
            self.template_input.setText(p["template_path"])

    def execute(self):
        p = self.get_params()
        if not p["template_path"] or not os.path.exists(p["template_path"]):
            return QMessageBox.warning(self, "错误", "请选择有效的模板文件！")
        try:
            from template_engine import load_template
            wb, meta = load_template(p["template_path"])
            out_name = p["out_name"] or f"模板_{os.path.basename(p['template_path']).split('.')[0]}"
            # 存储 metadata DataFrame 供预览 + 标记 _is_template
            import pandas as pd
            rows = []
            for sn, info in meta["sheets"].items():
                rows.append({"工作表": sn, "行数": info["max_row"], "列数": info["max_col"]})
            df = pd.DataFrame(rows)
            df.attrs["_is_template"] = True
            df.attrs["_template_path"] = p["template_path"]
            df.attrs["_sheets"] = meta["sheets"]
            self.step_recorded.emit("import_template", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))


class InsertBlockPanel(BaseToolPanel):
    use_type = False
    theme_color = "#FF6F00"
    action_name = "插入模板"

    def init_custom_ui(self):
        self.template_combo = QComboBox()
        self.combo_boxes_to_update.append(self.template_combo)
        self.top_form.insertRow(0, "目标模板:", self.template_combo)
        self.sheet_combo = QComboBox()
        self.top_form.addRow("目标工作表:", self.sheet_combo)
        self.chk_header = QComboBox()
        self.chk_header.addItems(["是 (写入表头)", "否 (仅写数据)"])
        self.top_form.addRow("写入表头:", self.chk_header)

        pos_card, pos_inner = self._make_card("插入位置")
        self.custom_layout.addWidget(pos_card)
        pos_layout = QHBoxLayout()
        self.start_row_input = QLineEdit("max_row + 1")
        self.start_row_input.setPlaceholderText("如: max_row+1")
        self.start_row_input.setMinimumWidth(100)
        self.start_col_input = QLineEdit("1")
        self.start_col_input.setPlaceholderText("如: 1")
        self.start_col_input.setMinimumWidth(100)
        pos_layout.addWidget(QLabel("起始行:"))
        pos_layout.addWidget(self.start_row_input)
        pos_layout.addWidget(QLabel("起始列:"))
        pos_layout.addWidget(self.start_col_input)
        pos_inner.addLayout(pos_layout)
        hint = QLabel("可用变量: max_row, max_col。max_row+1=追加到末尾")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        pos_inner.addWidget(hint)

        col_card, col_inner = self._make_card("提取列及重命名")
        self.custom_layout.addWidget(col_card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        col_inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加提取列")
        btn_add.setStyleSheet(
            "QPushButton { background: #FFF3E0; border: 1px dashed #FFB74D; "
            "border-radius: 4px; padding: 6px; color: #E65100; font-size: 12px; }"
            "QPushButton:hover { background: #FFE0B2; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        col_inner.addWidget(btn_add)

    def _refresh_sheet_combo(self):
        self.sheet_combo.clear()
        tmpl_name = self.template_combo.currentText()
        if tmpl_name and tmpl_name in self.data_pool:
            entry = self.data_pool[tmpl_name]
            if hasattr(entry, "attrs") and entry.attrs.get("_is_template"):
                sheets = entry.attrs.get("_sheets", {})
                for sn in sheets:
                    self.sheet_combo.addItem(sn)

    def clear_custom_ui(self):
        self.start_row_input.setText("max_row + 1")
        self.start_col_input.setText("1")
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", rename=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("选择列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("重命名(可选)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(r_input)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def update_combos(self, table_names):
        super().update_combos(table_names)
        # 筛选模板类型的条目
        tmpl_names = []
        for name, entry in self.data_pool.items():
            if hasattr(entry, "attrs") and entry.attrs.get("_is_template"):
                tmpl_names.append(name)
        cur = self.template_combo.currentText()
        self.template_combo.clear()
        self.template_combo.addItems(tmpl_names)
        if cur in tmpl_names:
            self.template_combo.setCurrentText(cur)
        self._refresh_sheet_combo()

    def set_custom_params(self, p):
        if "template_name" in p:
            self.template_combo.setCurrentText(p["template_name"])
        if "sheet_name" in p:
            self.sheet_combo.setCurrentText(p["sheet_name"])
        if "start_row" in p:
            self.start_row_input.setText(str(p["start_row"]))
        if "start_col" in p:
            self.start_col_input.setText(str(p["start_col"]))
        if "write_header" in p:
            self.chk_header.setCurrentIndex(0 if p["write_header"] else 1)
        col_list, col_names = p.get("col_list", []), p.get("col_names", [])
        if col_list:
            self.clear_dynamic_layout(self.rules_layout)
            for i, c in enumerate(col_list):
                r = col_names[i] if col_names and i < len(col_names) else ""
                self.add_rule_row(c, r)

    def get_custom_params(self):
        clist, rlist = [], []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c = self._get_col_name(w.findChild(QComboBox, "col"))
                r = w.findChild(QLineEdit, "rename").text().strip()
                if c:
                    clist.append(c)
                    rlist.append(r)
        return {
            "template_name": self.template_combo.currentText(),
            "sheet_name": self.sheet_combo.currentText(),
            "start_row": self.start_row_input.text().strip(),
            "start_col": self.start_col_input.text().strip(),
            "write_header": self.chk_header.currentIndex() == 0,
            "col_list": clist,
            "col_names": rlist,
        }

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["template_name"]:
            return QMessageBox.warning(self, "错误", "请连接上游数据表和模板表")
        tmpl_entry = self.data_pool.get(p["template_name"])
        if tmpl_entry is None or not (hasattr(tmpl_entry, "attrs") and tmpl_entry.attrs.get("_is_template")):
            return QMessageBox.warning(self, "错误", "模板表无效")
        template_path = tmpl_entry.attrs.get("_template_path")
        if not template_path or not os.path.exists(template_path):
            return QMessageBox.warning(self, "错误", f"模板文件不存在: {template_path}")

        try:
            from template_engine import load_template, insert_into_template, save_template
            import pandas as pd

            wb, _ = load_template(template_path)
            df = self.data_pool[p["df_name"]]
            cols = p["col_list"] if p["col_list"] else ["*"]
            col_names = p["col_names"]

            # 列重命名
            if col_names and any(col_names):
                actual_cols = [c for c in cols if c != "*"]
                if actual_cols:
                    available = [c for c in actual_cols if c in df.columns]
                else:
                    available = list(df.columns)
                rename_map = {}
                for i, c in enumerate(available):
                    if i < len(col_names) and col_names[i]:
                        rename_map[c] = col_names[i]
                if rename_map:
                    df = df.rename(columns=rename_map)

            success, msg = insert_into_template(
                wb, df, p["sheet_name"], p["start_row"], p["start_col"],
                columns=cols, write_header=p["write_header"], inherit_style=True,
            )
            if not success:
                return QMessageBox.critical(self, "插入失败", msg)

            default_dir = (
                Path(sys.executable).parent
                if getattr(sys, "frozen", False)
                else Path(__file__).parent.absolute()
            )
            out_path = str(default_dir / f"template_filled_{p['out_name'] or 'result'}.xlsx")
            save_template(wb, out_path)

            QMessageBox.information(self, "完成", f"{msg}\n\n已保存至: {out_path}")
            self.step_recorded.emit("insert_block", p, df, p["out_name"] or "插入结果")
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class PivotPanel(BaseToolPanel):
    theme_color = "#8E24AA"
    action_name = "数据透视"

    def init_custom_ui(self):
        card, inner = self._make_card("透视配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("行标签 (可多个):"))
        self.index_layout = QVBoxLayout()
        self.index_layout.setSpacing(4)
        inner.addLayout(self.index_layout)
        self.add_index_row()
        btn_add_idx = QPushButton("+ 添加行标签")
        btn_add_idx.setStyleSheet(
            "QPushButton { background: #F3E5F5; border: 1px dashed #CE93D8; "
            "border-radius: 4px; padding: 6px; color: #7B1FA2; font-size: 12px; }"
            "QPushButton:hover { background: #E1BEE7; }"
        )
        btn_add_idx.clicked.connect(lambda: self.add_index_row())
        inner.addWidget(btn_add_idx)

        inner.addWidget(QLabel("列标签:"))
        self.col_combo = self._make_col_combo("选择列标签列")
        inner.addWidget(self.col_combo)

        inner.addWidget(QLabel("统计值:"))
        self.val_combo = self._make_col_combo("选择统计值列", dtype_filter="numeric")
        inner.addWidget(self.val_combo)

        inner.addWidget(QLabel("聚合方式:"))
        self.agg_combo = QComboBox()
        self.agg_combo.addItems(["sum", "mean", "max", "min", "count", "median"])
        inner.addWidget(self.agg_combo)

        fl = QFormLayout()
        self.fill_input = QLineEdit("0")
        fl.addRow("空值填充:", self.fill_input)
        self.margin_combo = QComboBox()
        self.margin_combo.addItems(["是 (含汇总行列)", "否 (不含汇总)"])
        fl.addRow("汇总行列:", self.margin_combo)
        inner.addLayout(fl)

    def add_index_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("行标签列")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.index_layout.addWidget(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.index_layout)
        self.add_index_row()
        self.fill_input.setText("0")

    def get_custom_params(self):
        idx_cols = []
        for i in range(self.index_layout.count()):
            w = self.index_layout.itemAt(i).widget()
            if w:
                combo = w.findChild(QComboBox)
                if combo:
                    c = self._get_col_name(combo)
                    if c:
                        idx_cols.append(c)
        return {
            "index_cols": idx_cols,
            "columns_col": self._get_col_name(self.col_combo),
            "values_col": self._get_col_name(self.val_combo),
            "aggfunc": self.agg_combo.currentText(),
            "fill_value": (float(self.fill_input.text()) if self.fill_input.text() else 0),
            "margins": self.margin_combo.currentIndex() == 0,
        }

    def set_custom_params(self, p):
        if "index_cols" in p:
            self.clear_dynamic_layout(self.index_layout)
            for c in p["index_cols"]:
                self.add_index_row(c)
        if "columns_col" in p:
            self._set_col_name(self.col_combo, p["columns_col"])
        if "values_col" in p:
            self._set_col_name(self.val_combo, p["values_col"])
        if "aggfunc" in p:
            self.agg_combo.setCurrentText(p["aggfunc"])
        if "fill_value" in p:
            self.fill_input.setText(str(p["fill_value"]))
        if "margins" in p:
            self.margin_combo.setCurrentIndex(0 if p["margins"] else 1)

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["index_cols"] or not p["columns_col"] or not p["values_col"]:
            return QMessageBox.warning(self, "错误", "请填写行标签、列标签和统计值")
        out_name = p["out_name"] or f"{p['df_name']}_透视"
        try:
            df = pivot_table(self.data_pool[p["df_name"]],
                p["index_cols"], p["columns_col"], p["values_col"],
                p["aggfunc"], p["fill_value"], p["margins"], p["col_type"])
            self.step_recorded.emit("pivot_table", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class MeltPanel(BaseToolPanel):
    theme_color = "#26A69A"
    action_name = "逆透视"

    def init_custom_ui(self):
        card, inner = self._make_card("逆透视配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("保留列 (留空=自动使用非融合列):"))
        self.id_layout = QVBoxLayout()
        self.id_layout.setSpacing(4)
        inner.addLayout(self.id_layout)
        self.add_id_row()
        btn_add_id = QPushButton("+ 添加保留列")
        btn_add_id.setStyleSheet(
            "QPushButton { background: #E0F2F1; border: 1px dashed #80CBC4; "
            "border-radius: 4px; padding: 6px; color: #00695C; font-size: 12px; }"
            "QPushButton:hover { background: #B2DFDB; }"
        )
        btn_add_id.clicked.connect(lambda: self.add_id_row())
        inner.addWidget(btn_add_id)

        inner.addWidget(QLabel("融合列 (宽表变长表，这些列的值会汇入一列):"))
        self.val_layout = QVBoxLayout()
        self.val_layout.setSpacing(4)
        inner.addLayout(self.val_layout)
        self.add_val_row()
        btn_add_val = QPushButton("+ 添加融合列")
        btn_add_val.setStyleSheet(
            "QPushButton { background: #E0F2F1; border: 1px dashed #80CBC4; "
            "border-radius: 4px; padding: 6px; color: #00695C; font-size: 12px; }"
            "QPushButton:hover { background: #B2DFDB; }"
        )
        btn_add_val.clicked.connect(lambda: self.add_val_row())
        inner.addWidget(btn_add_val)

        fl = QFormLayout()
        self.var_input = QLineEdit("变量")
        fl.addRow("新列名(变量):", self.var_input)
        self.val_name_input = QLineEdit("值")
        fl.addRow("新列名(值):", self.val_name_input)
        inner.addLayout(fl)

    def add_id_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("保留列")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.id_layout.addWidget(row)

    def add_val_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("融合列")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.val_layout.addWidget(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.id_layout)
        self.add_id_row()
        self.clear_dynamic_layout(self.val_layout)
        self.add_val_row()
        self.var_input.setText("变量")
        self.val_name_input.setText("值")

    def _gather_cols(self, layout):
        cols = []
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w:
                combo = w.findChild(QComboBox)
                if combo:
                    c = self._get_col_name(combo)
                    if c:
                        cols.append(c)
        return cols

    def get_custom_params(self):
        return {
            "id_cols": self._gather_cols(self.id_layout),
            "value_cols": self._gather_cols(self.val_layout),
            "var_name": self.var_input.text().strip() or "变量",
            "value_name": self.val_name_input.text().strip() or "值",
        }

    def set_custom_params(self, p):
        if "id_cols" in p:
            self.clear_dynamic_layout(self.id_layout)
            for c in p["id_cols"]:
                self.add_id_row(c)
        if "value_cols" in p:
            self.clear_dynamic_layout(self.val_layout)
            for c in p["value_cols"]:
                self.add_val_row(c)
        if "var_name" in p:
            self.var_input.setText(p["var_name"])
        if "value_name" in p:
            self.val_name_input.setText(p["value_name"])

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["value_cols"]:
            return QMessageBox.warning(self, "错误", "请填写融合列")
        out_name = p["out_name"] or f"{p['df_name']}_逆透视"
        try:
            df = melt_table(self.data_pool[p["df_name"]],
                p["id_cols"], p["value_cols"], p["var_name"], p["value_name"], p["col_type"])
            self.step_recorded.emit("melt_table", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class ConcatPanel(BaseToolPanel):
    use_df = False
    theme_color = "#5C6BC0"
    action_name = "纵向拼接"

    def init_custom_ui(self):
        self.df1_combo = QComboBox()
        self.df2_combo = QComboBox()
        self.combo_boxes_to_update.extend([self.df1_combo, self.df2_combo])
        self.top_form.insertRow(0, "表1 (上方):", self.df1_combo)
        self.top_form.insertRow(1, "表2 (下方):", self.df2_combo)
        self.ignore_idx_combo = QComboBox()
        self.ignore_idx_combo.addItems(["是 (重建索引)", "否 (保留原索引)"])
        self.top_form.addRow("重建索引:", self.ignore_idx_combo)

        hint_card, hint_inner = self._make_card()
        self.custom_layout.addWidget(hint_card)
        hint = QLabel("纵向拼接将两个表上下接起来，类似 SQL 的 UNION ALL。")
        hint.setStyleSheet("color: #888; font-size: 11px; border: none;")
        hint.setWordWrap(True)
        hint_inner.addWidget(hint)

    def clear_custom_ui(self):
        pass

    def get_custom_params(self):
        return {
            "df1_name": self.df1_combo.currentText(),
            "df2_name": self.df2_combo.currentText(),
            "ignore_index": self.ignore_idx_combo.currentIndex() == 0,
        }

    def set_custom_params(self, p):
        if "df1_name" in p:
            self.df1_combo.setCurrentText(p["df1_name"])
        if "df2_name" in p:
            self.df2_combo.setCurrentText(p["df2_name"])
        if "ignore_index" in p:
            self.ignore_idx_combo.setCurrentIndex(0 if p["ignore_index"] else 1)

    def execute(self):
        p = self.get_params()
        if not p["df1_name"] or not p["df2_name"]:
            return QMessageBox.warning(self, "错误", "请选择两个表")
        out_name = p["out_name"] or f"{p['df1_name']}_拼接"
        try:
            df = concat_rows(self.data_pool[p["df1_name"]],
                self.data_pool[p["df2_name"]], p["ignore_index"])
            self.step_recorded.emit("concat_rows", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class DedupPanel(BaseToolPanel):
    theme_color = "#EF5350"
    action_name = "去重"

    def init_custom_ui(self):
        card, inner = self._make_card("去重配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("去重依据列 (留空=所有列完全相同才去重):"))
        self.subset_layout = QVBoxLayout()
        self.subset_layout.setSpacing(4)
        inner.addLayout(self.subset_layout)
        self.add_subset_row()
        btn_add = QPushButton("+ 添加去重列")
        btn_add.setStyleSheet(
            "QPushButton { background: #FFEBEE; border: 1px dashed #EF9A9A; "
            "border-radius: 4px; padding: 6px; color: #C62828; font-size: 12px; }"
            "QPushButton:hover { background: #FFCDD2; }"
        )
        btn_add.clicked.connect(lambda: self.add_subset_row())
        inner.addWidget(btn_add)

        inner.addWidget(QLabel("保留策略:"))
        self.keep_combo = QComboBox()
        self.keep_combo.addItems(["first (保留第一条)", "last (保留最后一条)", "False (全删)"])
        inner.addWidget(self.keep_combo)

    def add_subset_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("去重列")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.subset_layout.addWidget(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.subset_layout)
        self.add_subset_row()

    def get_custom_params(self):
        cols = []
        for i in range(self.subset_layout.count()):
            w = self.subset_layout.itemAt(i).widget()
            if w:
                combo = w.findChild(QComboBox)
                if combo:
                    c = self._get_col_name(combo)
                    if c:
                        cols.append(c)
        keep_map = {0: "first", 1: "last", 2: False}
        return {
            "subset_cols": cols,
            "keep": keep_map.get(self.keep_combo.currentIndex(), "first"),
        }

    def set_custom_params(self, p):
        if "subset_cols" in p:
            self.clear_dynamic_layout(self.subset_layout)
            for c in p["subset_cols"]:
                self.add_subset_row(c)
        if "keep" in p:
            k = p["keep"]
            if k == "last":
                self.keep_combo.setCurrentIndex(1)
            elif k is False:
                self.keep_combo.setCurrentIndex(2)
            else:
                self.keep_combo.setCurrentIndex(0)

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "缺少目标表")
        out_name = p["out_name"] or f"{p['df_name']}_去重"
        try:
            df = drop_duplicates(self.data_pool[p["df_name"]],
                p["subset_cols"], p["keep"], p["col_type"])
            self.step_recorded.emit("drop_duplicates", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class SamplePanel(BaseToolPanel):
    use_type = False
    theme_color = "#78909C"
    action_name = "抽样"

    def init_custom_ui(self):
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["按数量抽取", "按比例抽取"])
        self.top_form.addRow("抽样方式:", self.mode_combo)

        self.n_input = QLineEdit("100")
        self.n_input.setPlaceholderText("抽取行数")
        self.top_form.addRow("数量/比例:", self.n_input)

        self.seed_input = QLineEdit()
        self.seed_input.setPlaceholderText("随机种子 (留空=每次不同)")
        self.top_form.addRow("随机种子:", self.seed_input)

        hint_card, hint_inner = self._make_card()
        self.custom_layout.addWidget(hint_card)
        hint = QLabel("抽样从大数据集中随机抽取子集用于快速测试。种子固定时可复现相同结果。")
        hint.setStyleSheet("color: #888; font-size: 11px; border: none;")
        hint.setWordWrap(True)
        hint_inner.addWidget(hint)

    def clear_custom_ui(self):
        self.n_input.setText("100")
        self.seed_input.clear()

    def get_custom_params(self):
        seed = int(self.seed_input.text()) if self.seed_input.text().strip() else None
        p = {"random_state": seed}
        if self.mode_combo.currentIndex() == 0:
            p["n"] = int(self.n_input.text() or 100)
        else:
            p["frac"] = float(self.n_input.text() or 0.1)
        return p

    def set_custom_params(self, p):
        if "n" in p and p["n"]:
            self.mode_combo.setCurrentIndex(0)
            self.n_input.setText(str(p["n"]))
        elif "frac" in p and p["frac"]:
            self.mode_combo.setCurrentIndex(1)
            self.n_input.setText(str(p["frac"]))
        if "random_state" in p and p["random_state"] is not None:
            self.seed_input.setText(str(p["random_state"]))

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "缺少目标表")
        out_name = p["out_name"] or f"{p['df_name']}_抽样"
        try:
            df = sample_data(self.data_pool[p["df_name"]],
                p.get("n"), p.get("frac"), p.get("random_state"))
            self.step_recorded.emit("sample_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class DescribePanel(BaseToolPanel):
    use_type = False
    theme_color = "#3F51B5"
    action_name = "描述统计"

    def init_custom_ui(self):
        card, inner = self._make_card("分位数设置")
        self.custom_layout.addWidget(card)
        self.pct_layout = QVBoxLayout()
        self.pct_layout.setSpacing(4)
        inner.addLayout(self.pct_layout)
        self.add_pct_row("0.25")
        self.add_pct_row("0.5")
        self.add_pct_row("0.75")
        btn_add = QPushButton("+ 添加分位数")
        btn_add.setStyleSheet(
            "QPushButton { background: #E8EAF6; border: 1px dashed #9FA8DA; "
            "border-radius: 4px; padding: 6px; color: #283593; font-size: 12px; }"
            "QPushButton:hover { background: #C5CAE9; }"
        )
        btn_add.clicked.connect(lambda: self.add_pct_row())
        inner.addWidget(btn_add)

        hint_card, hint_inner = self._make_card()
        self.custom_layout.addWidget(hint_card)
        hint = QLabel("输出均值/标准差/最大最小/分位数等统计信息。")
        hint.setStyleSheet("color: #888; font-size: 11px; border: none;")
        hint.setWordWrap(True)
        hint_inner.addWidget(hint)

    def add_pct_row(self, val=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        inp = QLineEdit(str(val))
        inp.setObjectName("pct_val")
        inp.setPlaceholderText("如: 0.25")
        inp.setMinimumWidth(80)
        rm = QPushButton("×")
        rm.setFixedWidth(25)
        rm.clicked.connect(row.deleteLater)
        l.addWidget(inp)
        l.addWidget(rm)
        l.addStretch()
        self.pct_layout.addWidget(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.pct_layout)
        self.add_pct_row("0.25")
        self.add_pct_row("0.5")
        self.add_pct_row("0.75")

    def get_custom_params(self):
        pcts = []
        for i in range(self.pct_layout.count()):
            w = self.pct_layout.itemAt(i).widget()
            if w:
                inp = w.findChild(QLineEdit, "pct_val")
                if inp:
                    t = inp.text().strip()
                    if t:
                        try:
                            pcts.append(float(t))
                        except ValueError:
                            pass
        return {"percentiles": pcts if pcts else None}

    def set_custom_params(self, p):
        if "percentiles" in p and p["percentiles"]:
            self.pct_input.setText(", ".join(str(x) for x in p["percentiles"]))

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "缺少目标表")
        out_name = p["out_name"] or f"{p['df_name']}_描述"
        try:
            df = describe_data(self.data_pool[p["df_name"]], p.get("percentiles"))
            self.step_recorded.emit("describe_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class TransposePanel(BaseToolPanel):
    use_type = False
    theme_color = "#9E9E9E"
    action_name = "转置"

    def init_custom_ui(self):
        hint_card, hint_inner = self._make_card()
        self.custom_layout.addWidget(hint_card)
        hint = QLabel("转置将行列互换。原列名变为第一列，原行变为列。适合需要行列翻转的场景。")
        hint.setStyleSheet("color: #888; font-size: 11px; border: none;")
        hint.setWordWrap(True)
        hint_inner.addWidget(hint)

    def clear_custom_ui(self):
        pass

    def get_custom_params(self):
        return {}

    def set_custom_params(self, p):
        pass

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "缺少目标表")
        out_name = p["out_name"] or f"{p['df_name']}_转置"
        try:
            df = transpose_data(self.data_pool[p["df_name"]])
            self.step_recorded.emit("transpose_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class CumsumPanel(BaseToolPanel):
    theme_color = "#00897B"
    action_name = "累加"

    def init_custom_ui(self):
        card, inner = self._make_card("累加配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("累加列 (从第一行开始逐行累计):"))
        self.col_layout = QVBoxLayout()
        self.col_layout.setSpacing(4)
        inner.addLayout(self.col_layout)
        self.add_col_row()
        btn_add = QPushButton("+ 添加累加列")
        btn_add.setStyleSheet(
            "QPushButton { background: #E0F2F1; border: 1px dashed #80CBC4; "
            "border-radius: 4px; padding: 6px; color: #00695C; font-size: 12px; }"
            "QPushButton:hover { background: #B2DFDB; }"
        )
        btn_add.clicked.connect(lambda: self.add_col_row())
        inner.addWidget(btn_add)

        hint = QLabel("累加计算逐行累计。新列名 = 原列名_累加。适合做累计销售额、累计数量等。")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        inner.addWidget(hint)

    def add_col_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("累加列", dtype_filter="numeric")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.col_layout.addWidget(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.col_layout)
        self.add_col_row()

    def get_custom_params(self):
        cols = []
        for i in range(self.col_layout.count()):
            w = self.col_layout.itemAt(i).widget()
            if w:
                combo = w.findChild(QComboBox)
                if combo:
                    c = self._get_col_name(combo)
                    if c:
                        cols.append(c)
        return {"col_list": cols}

    def set_custom_params(self, p):
        if "col_list" in p:
            self.clear_dynamic_layout(self.col_layout)
            for c in p["col_list"]:
                self.add_col_row(c)

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["col_list"]:
            return QMessageBox.warning(self, "错误", "请填写累加列")
        out_name = p["out_name"] or f"{p['df_name']}_累加"
        try:
            df = cumsum_data(self.data_pool[p["df_name"]], p["col_list"], p["col_type"])
            self.step_recorded.emit("cumsum_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class PctChangePanel(BaseToolPanel):
    theme_color = "#F4511E"
    action_name = "环比"

    def init_custom_ui(self):
        card, inner = self._make_card("环比配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("环比列 (对指定列计算变化率):"))
        self.col_layout = QVBoxLayout()
        self.col_layout.setSpacing(4)
        inner.addLayout(self.col_layout)
        self.add_col_row()
        btn_add = QPushButton("+ 添加环比列")
        btn_add.setStyleSheet(
            "QPushButton { background: #FBE9E7; border: 1px dashed #FFAB91; "
            "border-radius: 4px; padding: 6px; color: #BF360C; font-size: 12px; }"
            "QPushButton:hover { background: #FFCCBC; }"
        )
        btn_add.clicked.connect(lambda: self.add_col_row())
        inner.addWidget(btn_add)

        fl = QFormLayout()
        self.periods_input = QLineEdit("1")
        fl.addRow("间隔期数:", self.periods_input)
        inner.addLayout(fl)

        hint = QLabel("环比 = (当前值 - 上期值) / 上期值。间隔期数: 1=逐行对比, 12=同比(月度数据)")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        inner.addWidget(hint)

    def add_col_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("环比列", dtype_filter="numeric")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.col_layout.addWidget(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.col_layout)
        self.add_col_row()
        self.periods_input.setText("1")

    def get_custom_params(self):
        cols = []
        for i in range(self.col_layout.count()):
            w = self.col_layout.itemAt(i).widget()
            if w:
                combo = w.findChild(QComboBox)
                if combo:
                    c = self._get_col_name(combo)
                    if c:
                        cols.append(c)
        return {
            "col_list": cols,
            "periods": int(self.periods_input.text() or 1),
        }

    def set_custom_params(self, p):
        if "col_list" in p:
            self.clear_dynamic_layout(self.col_layout)
            for c in p["col_list"]:
                self.add_col_row(c)
        if "periods" in p:
            self.periods_input.setText(str(p["periods"]))

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["col_list"]:
            return QMessageBox.warning(self, "错误", "请填写环比列")
        out_name = p["out_name"] or f"{p['df_name']}_环比"
        try:
            df = pct_change_data(self.data_pool[p["df_name"]],
                p["col_list"], p["periods"], p["col_type"])
            self.step_recorded.emit("pct_change_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class InputParamPanel(BaseToolPanel):
    use_df = False
    use_type = False
    use_out = False
    theme_color = "#1565C0"
    action_name = "输入参数"

    def init_custom_ui(self):
        card, inner = self._make_card("运行参数")
        self.custom_layout.addWidget(card)
        hint = QLabel("定义后可在任意输入框中引用，例如 ${report_month}")
        hint.setStyleSheet("color: #607D8B; font-size: 11px; border: none;")
        inner.addWidget(hint)

        self.param_rows = QVBoxLayout()
        self.param_rows.setSpacing(6)
        inner.addLayout(self.param_rows)
        self.add_param_row()

        btn_add = QPushButton("+ 添加参数")
        btn_add.clicked.connect(lambda: self.add_param_row())
        inner.addWidget(btn_add)

    def add_param_row(self, name="", value=""):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        name_input = QLineEdit(str(name))
        name_input.setObjectName("param_name")
        name_input.setPlaceholderText("参数名，如 report_month")
        value_input = QLineEdit(str(value))
        value_input.setObjectName("param_value")
        value_input.setPlaceholderText("参数值，如 2月份 / 2024-02-01 / [1,2,3]")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(26)
        btn_rm.clicked.connect(row.deleteLater)
        layout.addWidget(name_input)
        layout.addWidget(value_input)
        layout.addWidget(btn_rm)
        self.param_rows.addWidget(row)
        self._attach_parameter_action(name_input)
        self._attach_parameter_action(value_input)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.param_rows)
        self.add_param_row()

    def get_custom_params(self):
        params = {}
        for i in range(self.param_rows.count()):
            row = self.param_rows.itemAt(i).widget()
            if not row:
                continue
            name_input = row.findChild(QLineEdit, "param_name")
            value_input = row.findChild(QLineEdit, "param_value")
            name = name_input.text().strip() if name_input else ""
            value = value_input.text().strip() if value_input else ""
            if name:
                params[name] = value
        return {"parameters": params}

    def set_custom_params(self, p):
        params = p.get("parameters", {})
        if params:
            self.clear_dynamic_layout(self.param_rows)
            for name, value in params.items():
                self.add_param_row(name, value)

    def execute(self):
        p = self.get_params()
        params = normalize_runtime_parameters(p.get("parameters", {}))
        df = pd.DataFrame(
            [{"参数名": key, "当前值": value} for key, value in params.items()]
        )
        self.step_recorded.emit("input_param", p, df, "运行参数")


class ParamMappingPanel(BaseToolPanel):
    use_df = False
    use_type = False
    use_out = False
    theme_color = "#6A1B9A"
    action_name = "参数映射"

    def init_custom_ui(self):
        top_card, top_inner = self._make_card("映射名称")
        self.custom_layout.addWidget(top_card)
        form = QFormLayout()
        self.mapping_name_input = QLineEdit()
        self.mapping_name_input.setPlaceholderText("如 quarter_months")
        form.addRow("映射名:", self.mapping_name_input)
        top_inner.addLayout(form)

        card, inner = self._make_card("映射规则")
        self.custom_layout.addWidget(card)
        hint = QLabel("一行可写多对多，例如 输入: 1月份,2月份,3月份  输出: 1-3")
        hint.setStyleSheet("color: #607D8B; font-size: 11px; border: none;")
        inner.addWidget(hint)

        self.mapping_rows = QVBoxLayout()
        self.mapping_rows.setSpacing(6)
        inner.addLayout(self.mapping_rows)
        self.add_mapping_row()

        btn_add = QPushButton("+ 添加映射规则")
        btn_add.clicked.connect(lambda: self.add_mapping_row())
        inner.addWidget(btn_add)

    def add_mapping_row(self, from_value="", to_value=""):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        from_input = QLineEdit(str(from_value))
        from_input.setObjectName("from_value")
        from_input.setPlaceholderText("输入值/集合/范围")
        to_input = QLineEdit(str(to_value))
        to_input.setObjectName("to_value")
        to_input.setPlaceholderText("输出值/集合/范围")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(26)
        btn_rm.clicked.connect(row.deleteLater)
        layout.addWidget(from_input)
        layout.addWidget(to_input)
        layout.addWidget(btn_rm)
        self.mapping_rows.addWidget(row)
        self._attach_parameter_action(from_input)
        self._attach_parameter_action(to_input)

    def clear_custom_ui(self):
        self.mapping_name_input.clear()
        self.clear_dynamic_layout(self.mapping_rows)
        self.add_mapping_row()

    def get_custom_params(self):
        rules = []
        for i in range(self.mapping_rows.count()):
            row = self.mapping_rows.itemAt(i).widget()
            if not row:
                continue
            from_input = row.findChild(QLineEdit, "from_value")
            to_input = row.findChild(QLineEdit, "to_value")
            from_value = from_input.text().strip() if from_input else ""
            to_value = to_input.text().strip() if to_input else ""
            if from_value:
                rules.append({"from": from_value, "to": to_value})
        return {
            "mapping_name": self.mapping_name_input.text().strip(),
            "rules": rules,
        }

    def set_custom_params(self, p):
        self.mapping_name_input.setText(str(p.get("mapping_name", "")))
        rules = p.get("rules", [])
        if rules:
            self.clear_dynamic_layout(self.mapping_rows)
            for rule in rules:
                self.add_mapping_row(rule.get("from", ""), rule.get("to", ""))

    def execute(self):
        p = self.get_params()
        mapping_name = p.get("mapping_name", "")
        if not mapping_name:
            return QMessageBox.warning(self, "错误", "请填写映射名")
        mappings = normalize_parameter_mappings({mapping_name: p.get("rules", [])})
        rows = [
            {"映射名": mapping_name, "输入值": key, "输出值": value}
            for key, value in mappings.get(mapping_name, {}).items()
        ]
        df = pd.DataFrame(rows)
        self.step_recorded.emit("param_mapping", p, df, f"映射_{mapping_name}")


# NODE_REGISTRY / CATEGORY_ORDER → operator_registry.py
