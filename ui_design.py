import json
import os
import sys
import uuid
import copy
import pandas as pd
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QTableView,
    QLineEdit,
    QLabel,
    QMessageBox,
    QStackedWidget,
    QFormLayout,
    QGroupBox,
    QDialog,
    QDialogButtonBox,
    QProgressDialog,
    QFrame,
    QTabWidget,
    QCheckBox,
    QComboBox,
    QMenu,
    QScrollArea,
    QApplication,
    QMainWindow,
    QDockWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal, QPointF, QByteArray, QTimer
from PyQt5.QtGui import QFont, QCursor

from workspace_context import WorkspaceContext
from table_model import PandasModel
from operator_registry import NODE_REGISTRY, CATEGORY_ORDER, get_operator_title, OPERATOR_NAME_STYLES
from node_editor import NodeCanvasScene, NodeCanvasView, NodeItem, EdgeItem
from parameter_dialog import RuntimeParametersDialog
from parameter_resolver import normalize_parameter_mappings, normalize_runtime_parameters
import utils


class PathRemapDialog(QDialog):
    def __init__(self, missing_files, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据源重映射")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self.missing_files = missing_files
        self.inputs = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        warn_lbl = QLabel(
            "注意：以下数据源已失效（文件不存在）。\n如果不需要替换，可留空，后续可手动配置。"
        )
        warn_lbl.setStyleSheet("color: #E65100; font-weight: bold;")
        layout.addWidget(warn_lbl)

        # 修复显示不全：增加滚动条容器处理超长文件列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        form = QFormLayout(scroll_content)

        for nid, old_path in self.missing_files.items():
            h = QHBoxLayout()
            line = QLineEdit()
            line.setPlaceholderText("请选择新的有效文件...")
            btn = QPushButton("浏览")
            btn.clicked.connect(lambda _, l=line: self.browse(l))
            h.addWidget(line)
            h.addWidget(btn)
            form.addRow(f"原路径: {os.path.basename(old_path)}", h)
            self.inputs[nid] = line

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def browse(self, line_edit):
        p, _ = QFileDialog.getOpenFileName(
            self, "选择有效文件", "", "Excel/CSV (*.xlsx *.xls *.csv)"
        )
        if p:
            line_edit.setText(p)

    def get_mapping(self):
        return {nid: line.text() for nid, line in self.inputs.items() if line.text()}


class _CollapsibleGroup(QWidget):
    """可折叠分组控件"""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._expanded = True
        self._title = title

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._header_btn = QPushButton(f" ▾ {title}")
        self._header_btn.setFixedHeight(28)
        self._header_btn.setCursor(Qt.PointingHandCursor)
        self._header_btn.setStyleSheet("""
            QPushButton {
                background-color: #eceff1; border: none; border-radius: 3px;
                text-align: left; padding-left: 8px; font-size: 12px; font-weight: bold;
                color: #455a64;
            }
            QPushButton:hover { background-color: #cfd8dc; }
        """)
        self._header_btn.clicked.connect(self._toggle)
        self._layout.addWidget(self._header_btn)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(2, 2, 2, 4)
        self._body_layout.setSpacing(3)
        self._layout.addWidget(self._body)

    def _toggle(self):
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        arrow = "▾" if self._expanded else "▸"
        self._header_btn.setText(f" {arrow} {self._title}")

    def add_button(self, action, config):
        btn = QPushButton(f"  {config['title']}")
        btn.setFixedHeight(30)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: white; border: 1px solid #ddd; border-radius: 3px;
                border-left: 3px solid {config['color']}; text-align: left; padding-left: 6px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background-color: {config['color']}; color: white; }}
        """)
        btn.clicked.connect(lambda checked, a=action: self._emit_add(a))
        self._body_layout.addWidget(btn)

    def _emit_add(self, action):
        w = self
        while w:
            if hasattr(w, 'add_node_requested'):
                w.add_node_requested.emit(action)
                return
            w = w.parent()


class ToolboxWidget(QGroupBox):
    add_node_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setTitle("工具箱")
        self.setStyleSheet(
            "QGroupBox { border: 1px solid #ddd; background-color: #f8f9fa; border-radius: 4px; font-weight: bold; padding-top: 18px; }"
        )
        self.setMinimumWidth(155)
        self.setMaximumWidth(220)
        self._hidden = set()
        self._naming_style = "默认"
        self._custom_names = {}
        self._main_layout = None
        self._scroll_area = None
        self.init_ui()

    def init_ui(self):
        if self._main_layout is None:
            self._main_layout = QVBoxLayout(self)
            self._main_layout.setContentsMargins(4, 4, 4, 4)
            self._main_layout.setSpacing(4)
        else:
            while self._main_layout.count():
                item = self._main_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll_area.setStyleSheet("QScrollArea { background-color: transparent; }")

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)

        self._groups = {}
        for cat_name in CATEGORY_ORDER:
            group = _CollapsibleGroup(cat_name)
            self._groups[cat_name] = group
            layout.addWidget(group)

        for action, config in NODE_REGISTRY.items():
            if action in self._hidden:
                continue
            cat = config.get("category", "其他")
            if cat in self._groups:
                title = get_operator_title(action, self._naming_style,
                                           self._custom_names)
                self._groups[cat].add_button(action, {**config, "title": title})

        layout.addStretch(1)
        self._scroll_area.setWidget(content_widget)
        self._main_layout.addWidget(self._scroll_area)

    def set_hidden_operators(self, hidden):
        """更新可见性并重建工具箱"""
        self._hidden = set(hidden) if hidden else set()
        self.init_ui()

    def set_naming(self, style, custom_names=None):
        """更新命名风格并重建工具箱"""
        self._naming_style = style or "默认"
        self._custom_names = custom_names or {}
        self.init_ui()


class SettingsDialog(QDialog):
    """独立设置页面，左侧导航 + 右侧内容，可扩展"""

    def __init__(self, hidden_toolbox, hidden_context_menu, naming_style="默认",
                 custom_names=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(700)
        self.resize(740, 560)
        self.setStyleSheet("QDialog { background: #F5F6F8; }")

        self._hidden_toolbox = set(hidden_toolbox) if hidden_toolbox else set()
        self._hidden_context_menu = set(hidden_context_menu) if hidden_context_menu else set()
        self._naming_style = naming_style or "默认"
        self._custom_names = dict(custom_names) if custom_names else {}

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === Left sidebar ===
        sidebar = QFrame()
        sidebar.setFixedWidth(140)
        sidebar.setStyleSheet(
            "QFrame { background: #FFFFFF; border-right: 1px solid #E0E0E0; }"
        )
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 12, 0, 12)
        sidebar_layout.setSpacing(2)

        title_lbl = QLabel("  设置")
        title_lbl.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #333; padding: 4px 12px 12px 12px; border: none;"
        )
        sidebar_layout.addWidget(title_lbl)

        self._nav_buttons = []
        nav_items = [("operator_display", "算子显示"), ("naming_style", "命名风格")]
        self._nav_stack = QStackedWidget()

        for i, (key, label) in enumerate(nav_items):
            btn = QPushButton(f"  {label}")
            btn.setFixedHeight(36)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent; border: none; border-radius: 0;
                    text-align: left; padding-left: 16px; font-size: 13px; color: #555;
                }
                QPushButton:hover { background: #F5F5F5; color: #1976D2; }
                QPushButton[active="true"] {
                    background: #E3F2FD; color: #1565C0; font-weight: bold;
                    border-left: 3px solid #1976D2;
                }
            """)
            btn.setProperty("nav_key", key)
            btn.clicked.connect(lambda checked, k=key: self._switch_nav(k))
            sidebar_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        sidebar_layout.addStretch()
        main_layout.addWidget(sidebar)

        # === Right content area ===
        right_panel = QFrame()
        right_panel.setStyleSheet("QFrame { background: #F5F6F8; border: none; }")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # --- Pages ---
        op_page = self._build_operator_page()
        self._nav_stack.addWidget(op_page)
        naming_page = self._build_naming_page()
        self._nav_stack.addWidget(naming_page)

        # header bar (dynamic title)
        self._page_titles = {
            "operator_display": "算子显示设置",
            "naming_style": "算子命名风格",
        }
        header = QHBoxLayout()
        header.setContentsMargins(16, 12, 16, 8)
        self._page_title_lbl = QLabel("算子显示设置")
        self._page_title_lbl.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #333; border: none;"
        )
        header.addWidget(self._page_title_lbl)
        header.addStretch()
        right_layout.addLayout(header)
        right_layout.addWidget(self._nav_stack)
        right_layout.addStretch()

        # bottom bar
        bottom = QHBoxLayout()
        bottom.setContentsMargins(16, 8, 16, 12)
        bottom.setSpacing(8)

        # --- 算子显示页的 bottom ---
        self._bottom_op = QWidget()
        bop = QHBoxLayout(self._bottom_op)
        bop.setContentsMargins(0, 0, 0, 0)
        bop.setSpacing(8)
        btn_all_tb = QPushButton("全选工具箱")
        btn_all_tb.setStyleSheet(self._small_btn_style("#E8F5E9", "#A5D6A7", "#2E7D32"))
        btn_all_tb.clicked.connect(lambda: self._check_all(self._toolbox_cbs, True))
        btn_none_tb = QPushButton("取消工具箱")
        btn_none_tb.setStyleSheet(self._small_btn_style("#FFEBEE", "#EF9A9A", "#C62828"))
        btn_none_tb.clicked.connect(lambda: self._check_all(self._toolbox_cbs, False))
        btn_all_ctx = QPushButton("全选右键")
        btn_all_ctx.setStyleSheet(self._small_btn_style("#E3F2FD", "#90CAF9", "#0D47A1"))
        btn_all_ctx.clicked.connect(lambda: self._check_all(self._context_cbs, True))
        btn_none_ctx = QPushButton("取消右键")
        btn_none_ctx.setStyleSheet(self._small_btn_style("#FFF3E0", "#FFB74D", "#E65100"))
        btn_none_ctx.clicked.connect(lambda: self._check_all(self._context_cbs, False))
        bop.addWidget(btn_all_tb)
        bop.addWidget(btn_none_tb)
        bop.addSpacing(16)
        bop.addWidget(btn_all_ctx)
        bop.addWidget(btn_none_ctx)
        bop.addStretch()

        # --- 命名风格页的 bottom ---
        self._bottom_naming = QWidget()
        bn = QHBoxLayout(self._bottom_naming)
        bn.setContentsMargins(0, 0, 0, 0)
        bn.setSpacing(8)
        btn_reset = QPushButton("恢复预设")
        btn_reset.setStyleSheet(self._small_btn_style("#FFF3E0", "#FFB74D", "#E65100"))
        btn_reset.clicked.connect(self._reset_naming)
        bn.addWidget(btn_reset)
        bn.addStretch()

        btn_save = QPushButton("保存设置")
        btn_save.setStyleSheet(
            "QPushButton { background: #1976D2; color: white; border: none; "
            "border-radius: 4px; padding: 8px 28px; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background: #1565C0; }"
        )
        btn_save.clicked.connect(self.accept)
        bn.addWidget(btn_save)
        bottom.addWidget(self._bottom_op)
        bottom.addWidget(self._bottom_naming)
        bottom.addStretch()
        right_layout.addLayout(bottom)

        main_layout.addWidget(right_panel)

        # activate first nav
        if self._nav_buttons:
            self._switch_nav("operator_display")

    @staticmethod
    def _small_btn_style(bg, border, color):
        return (
            f"QPushButton {{ background: {bg}; border: 1px solid {border}; "
            f"border-radius: 4px; padding: 5px 12px; font-size: 11px; color: {color}; }}"
            f"QPushButton:hover {{ background: {border}; }}"
        )

    def _switch_nav(self, key):
        for btn in self._nav_buttons:
            btn.setProperty("active", btn.property("nav_key") == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if key == "operator_display":
            self._nav_stack.setCurrentIndex(0)
            self._bottom_op.setVisible(True)
            self._bottom_naming.setVisible(False)
        elif key == "naming_style":
            self._nav_stack.setCurrentIndex(1)
            self._bottom_op.setVisible(False)
            self._bottom_naming.setVisible(True)
        title = self._page_titles.get(key, "")
        self._page_title_lbl.setText(title)

    def _check_all(self, checkbox_dict, checked):
        for cb in checkbox_dict.values():
            cb.setChecked(checked)

    def _build_operator_page(self):
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        main_layout = QHBoxLayout(page)
        main_layout.setContentsMargins(8, 0, 8, 0)
        main_layout.setSpacing(12)

        self._toolbox_cbs = {}  # action -> QCheckBox (toolbox column)
        self._context_cbs = {}  # action -> QCheckBox (context menu column)

        for col_title, cb_dict, hidden_set in [
            ("工具箱显示", self._toolbox_cbs, self._hidden_toolbox),
            ("右键菜单显示", self._context_cbs, self._hidden_context_menu),
        ]:
            col_card = QFrame()
            col_card.setStyleSheet(
                "QFrame { background: white; border: 1px solid #E8E8E8; border-radius: 8px; }"
            )
            col_layout = QVBoxLayout(col_card)
            col_layout.setContentsMargins(0, 0, 0, 0)
            col_layout.setSpacing(0)

            # column header
            col_header = QLabel(col_title)
            col_header.setStyleSheet(
                "font-weight: bold; font-size: 13px; color: #424242; "
                "padding: 10px 14px 8px 14px; border: none; "
                "border-bottom: 2px solid #E0E0E0;"
            )
            col_layout.addWidget(col_header)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            scroll_content = QWidget()
            scroll_content.setStyleSheet("background: transparent;")
            scroll_layout = QVBoxLayout(scroll_content)
            scroll_layout.setContentsMargins(10, 8, 10, 10)
            scroll_layout.setSpacing(8)

            for cat_name in CATEGORY_ORDER:
                cat_frame = QFrame()
                cat_frame.setStyleSheet(
                    "QFrame { background: #FAFAFA; border: 1px solid #EEEEEE; border-radius: 4px; }"
                )
                cat_inner = QVBoxLayout(cat_frame)
                cat_inner.setContentsMargins(10, 6, 10, 8)
                cat_inner.setSpacing(2)

                cat_label = QLabel(cat_name)
                cat_label.setStyleSheet(
                    "font-weight: bold; font-size: 11px; color: #757575; border: none;"
                )
                cat_inner.addWidget(cat_label)

                cat_actions = [
                    a for a, c in NODE_REGISTRY.items() if c.get("category") == cat_name
                ]
                for action in cat_actions:
                    display_name = get_operator_title(action, self._naming_style,
                                                      self._custom_names)
                    cb = QCheckBox(display_name)
                    cb.setStyleSheet(
                        "QCheckBox { font-size: 12px; color: #424242; padding: 2px 0; spacing: 6px; }"
                    )
                    cb.setChecked(action not in hidden_set)
                    cb_dict[action] = cb
                    cat_inner.addWidget(cb)

                scroll_layout.addWidget(cat_frame)

            scroll_layout.addStretch()
            scroll.setWidget(scroll_content)
            col_layout.addWidget(scroll)
            main_layout.addWidget(col_card)

        return page

    def get_hidden_toolbox(self):
        return {a for a, cb in self._toolbox_cbs.items() if not cb.isChecked()}

    def get_hidden_context_menu(self):
        return {a for a, cb in self._context_cbs.items() if not cb.isChecked()}

    def get_naming_style(self):
        return self._naming_style

    def get_custom_names(self):
        if self._naming_style == "自定义":
            return {a: inp.text().strip() or get_operator_title(a, "默认")
                    for a, inp in self._name_inputs.items()}
        return {}

    def _build_naming_page(self):
        page = QWidget()
        page.setStyleSheet(
            "QWidget { background: transparent; }"
            "QComboBox QAbstractItemView { background: white; color: #333; "
            "selection-background-color: #E3F2FD; selection-color: black; border: 1px solid #DDD; }"
        )
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)

        # 风格选择行
        style_row = QHBoxLayout()
        style_lbl = QLabel("命名风格:")
        style_lbl.setStyleSheet("font-weight: bold; font-size: 13px; border: none;")
        self._style_combo = QComboBox()
        self._style_combo.addItems(list(OPERATOR_NAME_STYLES.keys()) + ["自定义"])
        idx = self._style_combo.findText(self._naming_style)
        if idx >= 0:
            self._style_combo.setCurrentIndex(idx)
        self._style_combo.setStyleSheet(
            "QComboBox { background: white; border: 1px solid #D0D0D0; "
            "border-radius: 3px; padding: 3px 8px; min-width: 140px; }"
            "QComboBox:hover { border-color: #AAA; }"
            "QComboBox QAbstractItemView { background: white; color: #333; "
            "selection-background-color: #E3F2FD; selection-color: black; "
            "border: 1px solid #DDD; outline: none; }"
            "QComboBox::drop-down { border: none; width: 20px; }"
        )
        style_row.addWidget(style_lbl)
        style_row.addWidget(self._style_combo)

        # 展开/收起按钮
        self._expand_btn = QPushButton("展开编辑 ▸")
        self._expand_btn.setCheckable(True)
        self._expand_btn.setStyleSheet(
            "QPushButton { background: #FAFAFA; border: 1px solid #E0E0E0; "
            "border-radius: 3px; padding: 3px 12px; font-size: 12px; color: #666; }"
            "QPushButton:hover { background: #EEE; }"
            "QPushButton:checked { background: #E3F2FD; color: #1565C0; border-color: #90CAF9; }"
        )
        self._expand_btn.toggled.connect(self._on_expand_toggled)
        style_row.addWidget(self._expand_btn)
        style_row.addStretch()
        layout.addLayout(style_row)

        # 算子名称列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self._name_layout = QVBoxLayout(scroll_content)
        self._name_layout.setContentsMargins(0, 0, 0, 0)
        self._name_layout.setSpacing(6)

        self._name_inputs = {}
        self._name_cards = {}

        for cat_name in CATEGORY_ORDER:
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background: white; border: 1px solid #E8E8E8; border-radius: 6px; }"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 8, 12, 10)
            card_layout.setSpacing(4)

            cat_lbl = QLabel(cat_name)
            cat_lbl.setStyleSheet(
                "font-weight: bold; font-size: 12px; color: #757575; border: none;"
            )
            card_layout.addWidget(cat_lbl)

            cat_actions = [a for a, c in NODE_REGISTRY.items()
                           if c.get("category") == cat_name]
            for action in cat_actions:
                row = QHBoxLayout()
                row.setSpacing(8)
                default_name = get_operator_title(action, self._naming_style,
                                                  self._custom_names)
                inp = QLineEdit(default_name)
                inp.setMinimumWidth(160)
                inp.setObjectName(action)
                self._name_inputs[action] = inp

                orig = QLabel(NODE_REGISTRY[action]["title"])
                orig.setStyleSheet("font-size: 11px; color: #999; border: none;")
                orig.setFixedWidth(80)

                row.addWidget(orig)
                row.addWidget(QLabel("→"))
                row.addWidget(inp)
                row.addStretch()
                card_layout.addLayout(row)

            self._name_layout.addWidget(card)
            self._name_cards[cat_name] = card

        self._name_layout.addStretch()
        scroll.setWidget(scroll_content)
        self._name_editor_area = scroll
        layout.addWidget(self._name_editor_area)

        self._style_combo.currentTextChanged.connect(self._on_style_changed)
        self._update_name_inputs_state()

        # 初始状态: 自定义才展开
        collapsed = self._naming_style != "自定义"
        self._name_editor_area.setVisible(not collapsed)
        self._expand_btn.setChecked(not collapsed)
        self._expand_btn.setText("收起编辑 ▾" if not collapsed else "展开编辑 ▸")

        return page

    def _on_expand_toggled(self, checked):
        self._name_editor_area.setVisible(checked)
        self._expand_btn.setText("收起编辑 ▾" if checked else "展开编辑 ▸")

    def _on_style_changed(self, style):
        self._naming_style = style
        for action, inp in self._name_inputs.items():
            name = get_operator_title(action, style, self._custom_names)
            inp.setText(name)
        self._update_name_inputs_state()
        # 自定义自动展开
        if style == "自定义" and not self._expand_btn.isChecked():
            self._expand_btn.setChecked(True)
            self._name_editor_area.setVisible(True)
            self._expand_btn.setText("收起编辑 ▾")

    def _update_name_inputs_state(self):
        is_custom = self._naming_style == "自定义"
        for inp in self._name_inputs.values():
            inp.setReadOnly(not is_custom)
            if is_custom:
                inp.setStyleSheet(
                    "QLineEdit { background: white; border: 1px solid #D0D0D0; "
                    "border-radius: 3px; padding: 2px 6px; color: #333; }"
                    "QLineEdit:focus { border-color: #2196F3; }"
                )
            else:
                inp.setStyleSheet(
                    "QLineEdit { background: #F8F8F8; color: #555; "
                    "border: 1px solid #E8E8E8; border-radius: 3px; padding: 2px 6px; }"
                )

    def _reset_naming(self):
        self._style_combo.setCurrentIndex(0)
        self._naming_style = "默认"
        for action, inp in self._name_inputs.items():
            inp.setText(NODE_REGISTRY[action]["title"])
        self._update_name_inputs_state()


class DesignModeWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.ctx = WorkspaceContext()
        self.ctx.workflow_finished.connect(self._on_full_run_finished)

        self.ctx.data_updated.connect(self.refresh_combo_list)

        self._spawn_counter = 0
        self.current_selected_node = None
        self._current_tab_shapes = {}
        self._is_updating_combo = False
        self.hidden_toolbox = set()
        self.hidden_context_menu = set()
        self.naming_style = "默认"
        self.custom_names = {}
        self.runtime_parameters = {}
        self.parameter_mappings = {}

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 4, 6, 4)
        main_layout.setSpacing(4)

        # === Top Toolbar ===
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        btn_import = QPushButton("导入模板")
        btn_export = QPushButton("导出模板")
        btn_clear = QPushButton("清空画布")
        btn_params = QPushButton("运行参数")
        btn_view = QPushButton("▤ 视图")
        btn_settings = QPushButton("⚙ 设置")
        io_btn_style = """
            QPushButton { background-color: white; border: 1px solid #ccc; padding: 5px 12px; border-radius: 4px; font-size: 12px; }
            QPushButton:hover { background-color: #f0f0f0; border-color: #999; }
        """
        for b in [btn_import, btn_export, btn_clear, btn_params, btn_view, btn_settings]:
            b.setStyleSheet(io_btn_style)
            b.setCursor(Qt.PointingHandCursor)

        btn_import.clicked.connect(self.import_workflow)
        btn_export.clicked.connect(self.export_workflow)
        btn_clear.clicked.connect(self.clear_canvas_logic)
        btn_params.clicked.connect(self.open_runtime_parameters)
        btn_view.clicked.connect(self._show_view_menu)
        btn_settings.clicked.connect(self.open_operator_settings)

        def create_sep():
            line = QFrame()
            line.setFrameShape(QFrame.VLine)
            line.setStyleSheet("color: #ddd;")
            return line

        self.btn_run_all = QPushButton("全量跑批执行")
        self.btn_run_all.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold; border-radius: 4px; padding: 5px 15px;"
        )
        self.btn_run_all.clicked.connect(self.run_full_workflow)

        self.btn_auto_layout = QPushButton("整理排版")
        self.btn_auto_layout.setStyleSheet(
            "background-color: #009688; color: white; font-weight: bold; border-radius: 4px; padding: 5px 15px;"
        )
        self.btn_auto_layout.clicked.connect(self.auto_layout_nodes)

        self.btn_delete_node = QPushButton("删除选中")
        self.btn_delete_node.setStyleSheet(
            "background-color: #f44336; color: white; font-weight: bold; border-radius: 4px; padding: 5px 12px;"
        )
        self.btn_delete_node.clicked.connect(self.delete_canvas_node)

        toolbar.addWidget(btn_import)
        toolbar.addWidget(btn_export)
        toolbar.addWidget(btn_clear)
        toolbar.addWidget(btn_params)
        toolbar.addWidget(btn_view)
        toolbar.addWidget(btn_settings)
        toolbar.addWidget(create_sep())
        toolbar.addWidget(self.btn_run_all)
        toolbar.addWidget(self.btn_auto_layout)
        toolbar.addWidget(create_sep())
        toolbar.addStretch(1)
        toolbar.addWidget(self.btn_delete_node)
        main_layout.addLayout(toolbar)

        # === Dockable Layout: Toolbox | Canvas | Preview ===
        self.dock_main = QMainWindow()
        self.dock_main.setStyleSheet(
            "QMainWindow::separator { width: 3px; background: #DDD; }"
            "QMainWindow::separator:hover { background: #AAA; }"
        )
        self.dock_main.setDockNestingEnabled(True)
        self.dock_main.setTabPosition(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea,
            QTabWidget.North
        )

        # Central: Canvas
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)

        self.canvas_scene = NodeCanvasScene()
        self.canvas_scene.node_selected.connect(self.on_canvas_node_selected)
        self.canvas_scene.node_double_clicked.connect(self.on_canvas_node_double_clicked)
        self.canvas_scene.right_clicked.connect(self.show_context_menu)
        self.canvas_scene.edge_changed.connect(self._on_edge_changed)

        self.canvas_view = NodeCanvasView(self.canvas_scene)
        canvas_layout.addWidget(self.canvas_view)
        QTimer.singleShot(0, self.canvas_view.center_on_canvas)

        self.dock_main.setCentralWidget(canvas_container)

        # Left dock: Toolbox
        self.toolbox = ToolboxWidget()
        self.toolbox.add_node_requested.connect(self.add_node_to_canvas)
        self.dock_toolbox = QDockWidget("工具箱")
        self.dock_toolbox.setObjectName("dock_toolbox")
        self.dock_toolbox.setWidget(self.toolbox)
        self.dock_toolbox.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        self.dock_toolbox.topLevelChanged.connect(
            lambda floating, d=self.dock_toolbox: self._on_dock_float_changed(d, floating)
        )
        self.dock_main.addDockWidget(Qt.LeftDockWidgetArea, self.dock_toolbox)

        # Right dock: Preview
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        preview_header = QHBoxLayout()
        self.chk_auto_follow = QCheckBox("自动跟随")
        self.chk_auto_follow.setChecked(True)
        self.chk_auto_follow.setStyleSheet("font-weight: bold; color: #2196F3;")
        self.chk_auto_follow.stateChanged.connect(self._on_auto_follow_changed)

        self.combo_preview_tables = QComboBox()
        self.combo_preview_tables.setMinimumWidth(120)
        self.combo_preview_tables.addItem("暂无数据")
        self.combo_preview_tables.setStyleSheet("""
            QComboBox { background: white; border: 1px solid #ccc; border-radius: 3px; padding: 2px 5px; color: black; }
            QComboBox QAbstractItemView { background-color: white; color: black; selection-background-color: #E1F5FE; }
        """)
        self.combo_preview_tables.currentIndexChanged.connect(self._on_manual_combo_changed)

        self.preview_title = QLabel("未选择")
        self.preview_title.setStyleSheet("color: #888;")

        self.lbl_shape = QLabel("")
        preview_header.addWidget(self.chk_auto_follow)
        preview_header.addWidget(self.combo_preview_tables)
        preview_header.addWidget(self.preview_title, stretch=1)
        preview_header.addWidget(self.lbl_shape)

        self.preview_tabs = QTabWidget()
        self.preview_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #eee; background: white; }
            QTabBar::tab { background: #f5f5f5; border: 1px solid #ddd; padding: 4px 10px;
                border-top-left-radius: 3px; border-top-right-radius: 3px; margin-right: 1px; font-size: 11px; }
            QTabBar::tab:selected { background: #E1F5FE; color: #0277BD; border-bottom: none; }
        """)
        self.preview_tabs.currentChanged.connect(self._on_tab_changed)

        right_layout.addLayout(preview_header)
        right_layout.addWidget(self.preview_tabs)

        self.dock_preview = QDockWidget("数据预览")
        self.dock_preview.setObjectName("dock_preview")
        self.dock_preview.setWidget(right_panel)
        self.dock_preview.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        self.dock_preview.topLevelChanged.connect(
            lambda floating, d=self.dock_preview: self._on_dock_float_changed(d, floating)
        )
        self.dock_main.addDockWidget(Qt.RightDockWidgetArea, self.dock_preview)

        # 存储所有 dock 引用（供视图菜单使用）
        self._all_docks = [self.dock_toolbox, self.dock_preview]

        main_layout.addWidget(self.dock_main, stretch=1)

        # === Config Dialog (card-style popup) ===
        self.config_dialog = QDialog(self)
        self.config_dialog.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.config_dialog.setWindowTitle("算子配置")
        self.config_dialog.setMinimumSize(620, 560)
        self.config_dialog.resize(660, 640)
        self.config_dialog.setStyleSheet("""
            QDialog { background: #F3F6FA; border: 1px solid #D8E0EA; border-radius: 8px; }
            QStackedWidget { background: #F3F6FA; border: none; }
        """)
        self.config_dialog.setAttribute(Qt.WA_TranslucentBackground, False)

        dialog_layout = QVBoxLayout(self.config_dialog)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        dialog_layout.setSpacing(0)

        self.config_area = QStackedWidget()
        self.panel_instances = {}

        for action, config in NODE_REGISTRY.items():
            panel = config["panel_class"](self.ctx.data_pool)
            panel.set_runtime_parameters(self.runtime_parameters, self.parameter_mappings)
            panel.step_recorded.connect(self.on_tool_executed)
            self.config_area.addWidget(panel)
            self.panel_instances[action] = panel

        self.panel_empty = QWidget()
        self.panel_empty.setStyleSheet("background: #F3F6FA;")
        empty_layout = QVBoxLayout(self.panel_empty)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.addStretch()
        empty_card = QFrame()
        empty_card.setStyleSheet("""
            QFrame {
                background: #FFFFFF;
                border: 1px solid #DFE5EC;
                border-radius: 8px;
            }
        """)
        empty_card_layout = QVBoxLayout(empty_card)
        empty_card_layout.setContentsMargins(24, 22, 24, 22)
        empty_card_layout.setSpacing(8)
        empty_lbl = QLabel("选择一个算子节点")
        empty_lbl.setAlignment(Qt.AlignCenter)
        empty_lbl.setStyleSheet("color: #1F2933; font-size: 16px; font-weight: bold; border: none;")
        empty_hint = QLabel("配置参数会在这里显示")
        empty_hint.setAlignment(Qt.AlignCenter)
        empty_hint.setStyleSheet("color: #607D8B; font-size: 12px; border: none;")
        empty_card_layout.addWidget(empty_lbl)
        empty_card_layout.addWidget(empty_hint)
        empty_layout.addWidget(empty_card)
        empty_layout.addStretch()
        self.config_area.addWidget(self.panel_empty)
        self.panel_instances["sys_empty"] = self.panel_empty

        dialog_layout.addWidget(self.config_area)

        # === Bottom Status Bar ===
        status_bar = QHBoxLayout()
        status_bar.setSpacing(15)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #666; font-size: 11px; padding: 2px 8px;")
        self.status_node_count = QLabel("节点: 0")
        self.status_node_count.setStyleSheet("color: #999; font-size: 11px;")
        self.status_table_count = QLabel("内存表: 0")
        self.status_table_count.setStyleSheet("color: #999; font-size: 11px;")
        status_bar.addWidget(self.status_label)
        status_bar.addStretch(1)
        status_bar.addWidget(self.status_node_count)
        status_bar.addWidget(self.status_table_count)
        main_layout.addLayout(status_bar)

        # 恢复上次保存的设置
        self._load_app_settings()

    def show_context_menu(self, scene_pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: white; border: 1px solid #ccc; border-radius: 4px;}
            QMenu::item { padding: 8px 30px 8px 20px; font-size: 13px;}
            QMenu::item:selected { background-color: #E1F5FE; color: #0277BD; font-weight: bold;}
            QMenu::separator { height: 1px; background: #E0E0E0; margin: 4px 10px; }
        """)

        # 检测右键是否落在节点上
        hit_item = self.canvas_scene.itemAt(
            scene_pos, self.canvas_view.transform()
        )
        clicked_node = None
        if isinstance(hit_item, NodeItem):
            clicked_node = hit_item
        elif hit_item and hit_item.parentItem() and isinstance(hit_item.parentItem(), NodeItem):
            clicked_node = hit_item.parentItem()

        if clicked_node:
            del_action = menu.addAction("🗑 删除此节点")
            del_action.triggered.connect(
                lambda checked, n=clicked_node: self._delete_single_node(n)
            )
        else:
            # 画布空白处：添加算子菜单
            for action, config in NODE_REGISTRY.items():
                if action in self.hidden_context_menu:
                    continue
                title = get_operator_title(action, self.naming_style,
                                           self.custom_names)
                qaction = menu.addAction(title)
                qaction.triggered.connect(
                    lambda checked, a=action, pos=scene_pos: self.add_node_at_pos(a, pos)
                )

        menu.exec_(QCursor.pos())

    def _delete_single_node(self, node):
        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除节点 [{node.title}] 吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        for edge in list(node.edges_in):
            edge.source_node.edges_out.remove(edge)
            self.canvas_scene.removeItem(edge)
        for edge in list(node.edges_out):
            edge.dest_node.edges_in.remove(edge)
            self.canvas_scene.removeItem(edge)
        self.canvas_scene.removeItem(node)
        if self.current_selected_node == node:
            self.current_selected_node = None
        self._update_status_bar()

    def add_node_at_pos(self, action, scene_pos):
        config = NODE_REGISTRY[action]
        unique_id = f"node_{uuid.uuid4().hex[:8]}"
        title = get_operator_title(action, self.naming_style, self.custom_names)

        node = NodeItem(
            unique_id,
            action,
            title,
            config["color"],
            scene_pos.x(),
            scene_pos.y(),
        )
        node.params["action"] = action
        node.is_dirty = True
        self.canvas_scene.addItem(node)
        self.canvas_scene.clearSelection()
        node.setSelected(True)

        self.on_canvas_node_selected(node)
        self._update_status_bar()
        if action == "load_file":
            self.on_canvas_node_double_clicked(node)

    def refresh_combo_list(self, *args):
        self._is_updating_combo = True
        self.combo_preview_tables.blockSignals(True)

        current_text = self.combo_preview_tables.currentText()
        self.combo_preview_tables.clear()

        tables = list(self.ctx.data_pool.keys())
        if tables:
            self.combo_preview_tables.addItems(tables)
            if current_text in tables:
                self.combo_preview_tables.setCurrentText(current_text)
        else:
            self.combo_preview_tables.addItem("暂无数据")

        self.combo_preview_tables.blockSignals(False)
        self._is_updating_combo = False

    def _on_auto_follow_changed(self, state):
        if state == Qt.Checked:
            self.chk_auto_follow.setStyleSheet("font-weight: bold; color: #2196F3;")
            if self.current_selected_node:
                self._render_node_preview(self.current_selected_node)
        else:
            self.chk_auto_follow.setStyleSheet("font-weight: normal; color: #999;")
            if self.combo_preview_tables.currentText() != "暂无数据":
                self.preview_title.setText(
                    f"已锁定表: 【{self.combo_preview_tables.currentText()}】"
                )
                self.preview_title.setStyleSheet("color: #E65100; font-weight: bold;")

    def _on_manual_combo_changed(self, index):
        if self._is_updating_combo or index < 0:
            return

        table_name = self.combo_preview_tables.currentText()
        if table_name and table_name != "暂无数据":
            self.chk_auto_follow.blockSignals(True)
            self.chk_auto_follow.setChecked(False)
            self.chk_auto_follow.setStyleSheet("font-weight: normal; color: #999;")
            self.chk_auto_follow.blockSignals(False)
            self._render_specific_table(table_name)

    def _on_edge_changed(self):
        """连线变更时刷新当前配置面板的列下拉"""
        if self.current_selected_node and "action" in self.current_selected_node.params:
            action = self.current_selected_node.params["action"]
            panel = self.panel_instances.get(action)
            if panel:
                incoming = [
                    e.source_node.params.get("out_name") or e.source_node.title
                    for e in self.current_selected_node.edges_in
                ]
                panel.update_combos(incoming)
                panel._refresh_col_combos()

    def _render_specific_table(self, table_name):
        self.preview_tabs.clear()
        self._current_tab_shapes.clear()

        if table_name in self.ctx.data_pool:
            df = self.ctx.get_data(table_name)
            self.preview_title.setText(f"已锁定表: 【{table_name}】 (点击画布不切表)")
            self.preview_title.setStyleSheet("color: #E65100; font-weight: bold;")
            self._add_preview_tab(f"锁定视图: {table_name}", df)
        else:
            self.preview_title.setText(f"锁定表: 【{table_name}】 (暂无数据)")
            self.lbl_shape.setText("(0 行, 0 列)")

    def _render_node_preview(self, node):
        self.preview_tabs.clear()
        self._current_tab_shapes.clear()

        if not node:
            self.preview_title.setText(
                "数据预览: 未选择节点\n(提示: 双击画布节点可配置参数)"
            )
            self.preview_title.setStyleSheet("color: black; font-weight: bold;")
            self.lbl_shape.setText("(0 行, 0 列)")
            return

        # 优先用 dedup 后的实际 key，回退到原始 out_name
        out_name = self.ctx.dedup_map.get(node.node_id) or node.params.get("out_name")

        if out_name and out_name in self.ctx.data_pool:
            self._is_updating_combo = True
            if self.combo_preview_tables.findText(out_name) >= 0:
                self.combo_preview_tables.setCurrentText(out_name)
            self._is_updating_combo = False

            df = self.ctx.get_data(out_name)
            self.preview_title.setText(f"跟随节点: 【{out_name}】")
            self.preview_title.setStyleSheet("color: #2196F3; font-weight: bold;")
            self._add_preview_tab(f"当前输出: {out_name}", df)
        else:
            self.preview_title.setText(f"溯源模式: 【正在查看上游原材料】")
            self.preview_title.setStyleSheet("color: #673AB7; font-weight: bold;")

            upstream_nodes = [edge.source_node for edge in node.edges_in]
            valid_sources = 0
            for i, up_node in enumerate(upstream_nodes):
                up_name = self.ctx.dedup_map.get(up_node.node_id) or up_node.params.get("out_name")
                if up_name and up_name in self.ctx.data_pool:
                    df = self.ctx.get_data(up_name)
                    prefix = (
                        "左表(主)"
                        if node.action_type == "left_join" and i == 0
                        else "右表(附)" if node.action_type == "left_join" else "来源表"
                    )
                    self._add_preview_tab(f"{prefix}: {up_name}", df)
                    valid_sources += 1

            if valid_sources == 0:
                self.preview_title.setText(f"溯源失败: 【连入的上游尚未产生数据】")
                self.lbl_shape.setText("(0 行, 0 列)")

    def _add_preview_tab(self, title, df):
        table = QTableView()
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableView { border: none; background-color: white; gridline-color: #eee; } "
            "QHeaderView::section { background-color: #E1F5FE; font-weight: bold; border: 1px solid #ccc; padding: 4px; }"
        )
        model = PandasModel(df)
        table.setModel(model)
        idx = self.preview_tabs.addTab(table, title)
        self._current_tab_shapes[idx] = (df.shape[0], df.shape[1])
        if idx == 0:
            self.lbl_shape.setText(f"({df.shape[0]} 行, {df.shape[1]} 列)")

    def _on_tab_changed(self, index):
        if index in self._current_tab_shapes:
            rows, cols = self._current_tab_shapes[index]
            self.lbl_shape.setText(f"({rows} 行, {cols} 列)")
        else:
            self.lbl_shape.setText("(0 行, 0 列)")

    def _update_inspector_panel(self, node):
        if node and "action" in node.params:
            action = node.params["action"]
            active_panel = self.panel_instances.get(action)
            if active_panel:
                self.config_area.setCurrentWidget(active_panel)
                self.config_dialog.setWindowTitle(f"配置: {node.title}")
                if hasattr(active_panel, "set_panel_context"):
                    active_panel.set_panel_context(action, node.title)
                incoming = [
                    e.source_node.params.get("out_name") or e.source_node.title
                    for e in node.edges_in
                ]
                active_panel.clear_ui()
                active_panel.update_combos(incoming)
                active_panel.set_params(node.params)
                active_panel._refresh_col_combos()
        else:
            self.config_area.setCurrentWidget(self.panel_instances["sys_empty"])
            self.config_dialog.setWindowTitle("算子配置")

    def _update_status_bar(self):
        nodes = [item for item in self.canvas_scene.items() if isinstance(item, NodeItem)]
        edges = [item for item in self.canvas_scene.items() if isinstance(item, EdgeItem)]
        node_count = len(nodes)
        edge_count = len(edges)
        table_count = len(self.ctx.data_pool)
        self.status_node_count.setText(f"节点: {node_count}  连线: {edge_count}")
        self.status_table_count.setText(f"内存表: {table_count}")
        self.status_label.setText(
            "点击节点查看数据 | 双击配置参数 | 右键添加节点"
        )

    def save_current_node_draft(self):
        if self.current_selected_node and "action" in self.current_selected_node.params:
            action = self.current_selected_node.params["action"]
            active_panel = self.panel_instances.get(action)
            if active_panel and hasattr(active_panel, "get_params"):
                new_p = active_panel.get_params()
                if "out_name" in new_p and not str(new_p["out_name"]).strip():
                    new_p.pop("out_name")
                self.current_selected_node.params.update(new_p)

    def on_canvas_node_selected(self, node):
        # 点同一个节点不重复刷新面板，保留当前配置
        if node and self.current_selected_node == node:
            return

        if self.current_selected_node and self.current_selected_node != node:
            self.save_current_node_draft()
            self._sync_runtime_parameters()

        self.current_selected_node = node
        self._update_inspector_panel(node)

        if self.chk_auto_follow.isChecked():
            self._render_node_preview(node)

    def on_canvas_node_double_clicked(self, node):
        self.on_canvas_node_selected(node)
        if node:
            self.config_dialog.show()
            self.config_dialog.raise_()
            self.config_dialog.activateWindow()

    def on_tool_executed(self, action, params, result_df, out_name):
        node_id = self.current_selected_node.node_id if self.current_selected_node else None
        self.ctx.blockSignals(True)
        final_name = self.ctx.register_data(out_name, result_df, node_id)
        self.ctx.blockSignals(False)
        params_to_store = params
        active_panel = self.panel_instances.get(action)
        raw_params = getattr(active_panel, "_last_raw_params", None)
        if isinstance(raw_params, dict):
            params_to_store = copy.deepcopy(raw_params)
            active_panel._last_raw_params = None
        params_to_store["out_name"] = final_name

        if self.current_selected_node:
            self.current_selected_node.params.update(params_to_store)
            self.current_selected_node.title = f"{final_name}"
            self.current_selected_node.is_dirty = False
            self.current_selected_node.update()
            if action in ("input_param", "param_mapping"):
                self._sync_runtime_parameters()

        self._render_node_preview(self.current_selected_node)
        self.refresh_combo_list()
        self.config_dialog.hide()
        self._update_status_bar()

    def open_operator_settings(self):
        dlg = SettingsDialog(self.hidden_toolbox, self.hidden_context_menu,
                             self.naming_style, self.custom_names, self)
        if dlg.exec_() == QDialog.Accepted:
            self.hidden_toolbox = dlg.get_hidden_toolbox()
            self.hidden_context_menu = dlg.get_hidden_context_menu()
            self.naming_style = dlg.get_naming_style()
            self.custom_names = dlg.get_custom_names()
            self.toolbox.set_hidden_operators(self.hidden_toolbox)
            self.toolbox.set_naming(self.naming_style, self.custom_names)
            self._save_app_settings()

    def _sync_runtime_parameters(self):
        parameters = normalize_runtime_parameters(self.runtime_parameters)
        mappings = dict(self.parameter_mappings or {})

        if hasattr(self, "canvas_scene"):
            for item in self.canvas_scene.items():
                if not isinstance(item, NodeItem):
                    continue
                if item.action_type == "input_param":
                    parameters.update(
                        normalize_runtime_parameters(
                            item.params.get("parameters", {})
                        )
                    )
                elif item.action_type == "param_mapping":
                    mapping_name = str(item.params.get("mapping_name", "")).strip()
                    if mapping_name:
                        mappings[mapping_name] = item.params.get("rules", [])

        self.ctx.set_runtime_parameters(parameters, mappings)
        for panel in getattr(self, "panel_instances", {}).values():
            if hasattr(panel, "set_runtime_parameters"):
                panel.set_runtime_parameters(
                    parameters,
                    mappings,
                )
        self._update_status_bar()

    def open_runtime_parameters(self):
        dlg = RuntimeParametersDialog(
            self.runtime_parameters,
            self.parameter_mappings,
            self,
        )
        if dlg.exec_() == QDialog.Accepted:
            self.runtime_parameters = dlg.get_parameters()
            self.parameter_mappings = dlg.get_mappings()
            self._sync_runtime_parameters()
            self._save_app_settings()

    def _show_view_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: white; border: 1px solid #ddd; border-radius: 4px; }
            QMenu::item { padding: 8px 24px 8px 16px; font-size: 12px; }
            QMenu::item:selected { background: #E3F2FD; color: #1565C0; }
        """)

        for dock in self._all_docks:
            action = menu.addAction(dock.windowTitle())
            action.setCheckable(True)
            action.setChecked(dock.isVisible())
            action.toggled.connect(
                lambda checked, d=dock: d.setVisible(checked)
            )

        menu.addSeparator()
        reset_action = menu.addAction("重置布局")
        reset_action.triggered.connect(self._reset_dock_layout)

        menu.exec_(self.sender().mapToGlobal(
            self.sender().rect().bottomLeft()))

    def _reset_dock_layout(self):
        """恢复默认停靠位置"""
        self.dock_toolbox.setFloating(False)
        self.dock_preview.setFloating(False)
        self.dock_main.addDockWidget(Qt.LeftDockWidgetArea, self.dock_toolbox)
        self.dock_main.addDockWidget(Qt.RightDockWidgetArea, self.dock_preview)
        self.dock_toolbox.show()
        self.dock_preview.show()
        # 清除窗口置顶标志
        for d in self._all_docks:
            if d.isFloating():
                d.setWindowFlags(d.windowFlags() & ~Qt.WindowStaysOnTopHint)
                d.show()

    def _on_dock_float_changed(self, dock, floating):
        """dock 变为浮动窗口时，标题栏增加置顶按钮"""
        if not hasattr(self, '_pin_buttons'):
            self._pin_buttons = {}

        if floating:
            title_bar = QWidget()
            tb = QHBoxLayout(title_bar)
            tb.setContentsMargins(8, 2, 4, 2)
            tb.setSpacing(6)
            lbl = QLabel(dock.windowTitle())
            lbl.setStyleSheet("font-weight: bold; font-size: 12px; border: none;")
            pin_btn = QPushButton("📌")
            pin_btn.setFixedSize(24, 22)
            pin_btn.setCheckable(True)
            pin_btn.setToolTip("保持置顶")
            pin_btn.setStyleSheet(
                "QPushButton { border: 1px solid #DDD; border-radius: 3px; background: #FAFAFA; }"
                "QPushButton:hover { background: #EEE; }"
                "QPushButton:checked { background: #FFF3E0; border-color: #FF9800; }"
            )
            pin_btn.toggled.connect(
                lambda checked, d=dock: self._toggle_dock_pin(d, checked)
            )
            self._pin_buttons[id(dock)] = pin_btn
            tb.addWidget(lbl)
            tb.addStretch()
            tb.addWidget(pin_btn)
            dock.setTitleBarWidget(title_bar)
        else:
            dock.setTitleBarWidget(None)
            dock.setWindowFlags(dock.windowFlags() & ~Qt.WindowStaysOnTopHint)

    def _toggle_dock_pin(self, dock, pinned):
        if pinned:
            dock.setWindowFlags(dock.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            dock.setWindowFlags(dock.windowFlags() & ~Qt.WindowStaysOnTopHint)
        dock.show()

    def clear_canvas_logic(self):
        nodes = [
            item for item in self.canvas_scene.items() if isinstance(item, NodeItem)
        ]
        if not nodes:
            QTimer.singleShot(0, self.canvas_view.center_on_canvas)
            return
        reply = QMessageBox.question(
            self,
            "确认操作",
            "确定要清空当前所有节点吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.canvas_scene.clear()
            self.ctx.clear_context()
            self.refresh_combo_list()
            self.chk_auto_follow.setChecked(True)

            self.preview_tabs.clear()
            self._current_tab_shapes.clear()
            self.preview_title.setText("未选择")
            self.preview_title.setStyleSheet("color: #888;")
            self.lbl_shape.setText("")
            self.current_selected_node = None
            self.config_area.setCurrentWidget(self.panel_instances["sys_empty"])
            self.config_dialog.hide()
            self._update_status_bar()
            QTimer.singleShot(0, self.canvas_view.center_on_canvas)

    def delete_canvas_node(self):
        self.canvas_scene.delete_selected_items()
        self._update_status_bar()

    def add_node_to_canvas(self, action):
        view_center = self.canvas_view.viewport().rect().center()
        scene_pos = self.canvas_view.mapToScene(view_center)
        self._spawn_counter += 1
        offset = (self._spawn_counter % 5) * 20
        self.add_node_at_pos(
            action, QPointF(scene_pos.x() - 80 + offset, scene_pos.y() - 30 + offset)
        )

    def run_full_workflow(self):
        self.save_current_node_draft()
        self._sync_runtime_parameters()
        nodes = [
            item for item in self.canvas_scene.items() if isinstance(item, NodeItem)
        ]

        config = self.ctx.build_workflow_logic(nodes)
        if not config:
            QMessageBox.warning(self, "警告", "存在死循环连线，无法处理。")
            return

        total_steps = len(config["steps"])
        for step in config["steps"]:
            node_id = step["node_id"]
            node = next((n for n in nodes if n.node_id == node_id), None)
            if node:
                assigned_name = step["out_name"]
                # 默认名或临时名 → 替换为输出名
                default_titles = {
                    get_operator_title(node.action_type, s)
                    for s in OPERATOR_NAME_STYLES
                }
                if node.title in default_titles or node.title.startswith("临时表_"):
                    node.title = assigned_name
                    node.update()

        self.progress = QProgressDialog("正在高速全量执行流水线...", None, 0, total_steps, self)
        self.progress.setWindowTitle("执行中")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setAutoClose(True)
        self.progress.show()
        self.ctx.run_full_workflow()
        if self.ctx.engine:
            self.ctx.engine.progress_signal.connect(self.progress.setValue)

    def _on_full_run_finished(self, success, result_pool):
        self.progress.close()
        self._update_status_bar()
        if success:
            for item in self.canvas_scene.items():
                if isinstance(item, NodeItem):
                    item.is_dirty = False
                    item.update()
            QMessageBox.information(self, "成功", "流水线跑批完毕！")
            if self.chk_auto_follow.isChecked() and self.current_selected_node:
                self.on_canvas_node_selected(self.current_selected_node)
            elif not self.chk_auto_follow.isChecked():
                table_name = self.combo_preview_tables.currentText()
                if table_name and table_name != "暂无数据":
                    self._render_specific_table(table_name)
        else:
            QMessageBox.critical(
                self, "错误", "执行出错，请检查数据完整性或查看执行模式下的日志信息。"
            )

    @property
    def _settings_path(self):
        config_dir = Path(__file__).parent / "config"
        return config_dir / "workspace_config.json"

    def save_design_state(self):
        """保存设计模式状态到配置文件（供 main.py closeEvent 调用）"""
        self._save_app_settings()

    def _save_app_settings(self):
        data = {}
        if self._settings_path.exists():
            try:
                with open(self._settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        data["design_mode"] = data.get("design_mode", {})
        data["design_mode"]["naming_style"] = self.naming_style
        data["design_mode"]["custom_names"] = self.custom_names
        data["design_mode"]["hidden_toolbox"] = list(self.hidden_toolbox)
        data["design_mode"]["hidden_context_menu"] = list(self.hidden_context_menu)
        data["design_mode"]["runtime_parameters"] = self.runtime_parameters
        data["design_mode"]["parameter_mappings"] = self.parameter_mappings
        if getattr(self, '_last_workflow_path', None):
            data["design_mode"]["last_workflow_path"] = self._last_workflow_path
        data["design_mode"]["dock_state"] = str(
            self.dock_main.saveState().toBase64(), encoding="ascii"
        )
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._settings_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def _load_app_settings(self):
        if not self._settings_path.exists():
            return
        with open(self._settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        dm = data.get("design_mode", {})
        self.naming_style = dm.get("naming_style", "默认")
        self.custom_names = dm.get("custom_names", {})
        self.hidden_toolbox = set(dm.get("hidden_toolbox", []))
        self.hidden_context_menu = set(dm.get("hidden_context_menu", []))
        self.runtime_parameters = dm.get("runtime_parameters", {})
        self.parameter_mappings = dm.get("parameter_mappings", {})
        self.toolbox._hidden = self.hidden_toolbox
        self.toolbox._naming_style = self.naming_style
        self.toolbox._custom_names = self.custom_names
        self.toolbox.init_ui()
        self._sync_runtime_parameters()

        dock_b64 = dm.get("dock_state", "")
        if dock_b64:
            try:
                state = QByteArray.fromBase64(dock_b64.encode("ascii"))
                self.dock_main.restoreState(state)
            except Exception:
                pass

        # 自动加载设计模式上次工作流
        last_path = dm.get("last_workflow_path")
        if last_path and os.path.exists(last_path):
            self._auto_load_workflow(last_path)

    def _auto_load_workflow(self, path):
        """启动时静默加载上次工作流（不弹窗、不执行）"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                workflow = json.load(f)
            self.runtime_parameters = workflow.get("runtime_parameters", {})
            self.parameter_mappings = workflow.get("parameter_mappings", {})
            self._sync_runtime_parameters()
            steps = workflow.get("steps", [])
            if not steps:
                return

            self.canvas_scene.clear()
            self.ctx.clear_context()

            created_nodes = {}
            for i, step in enumerate(steps):
                node_id = step.get("node_id", f"legacy_{i}")
                action = step.get("action")
                out_name = step.get("out_name", f"Result_{i}")
                params = step.get("params", {})
                params["out_name"] = out_name
                params["action"] = action

                color = NODE_REGISTRY.get(action, {}).get("color", "#1976D2")
                title = f"{out_name}" if action != "load_file" else f"表: {out_name}"
                node = NodeItem(node_id, action, title, color,
                                step.get("x", 50), step.get("y", 50 + i * 100))
                node.params = params
                node.is_dirty = True
                self.canvas_scene.addItem(node)
                created_nodes[node_id] = node

            for step in steps:
                node = created_nodes.get(step.get("node_id"))
                if not node:
                    continue
                deps = []
                p = step.get("params", {})
                if node.action_type in ("left_join", "concat_rows"):
                    if "df1_id" in p: deps.append(p["df1_id"])
                    if "df2_id" in p: deps.append(p["df2_id"])
                elif node.action_type == "insert_block":
                    if "df_id" in p: deps.append(p["df_id"])
                    if "template_id" in p: deps.append(p["template_id"])
                elif "df_id" in p:
                    deps.append(p["df_id"])

                for src_id in deps:
                    if src_id in created_nodes:
                        edge = EdgeItem(created_nodes[src_id], node)
                        self.canvas_scene.addItem(edge)
                        created_nodes[src_id].edges_out.append(edge)
                        node.edges_in.append(edge)

            self._update_status_bar()
            QTimer.singleShot(100, self.run_full_workflow)
            QTimer.singleShot(0, lambda: self.canvas_view.centerOn(
                self.canvas_scene.itemsBoundingRect().center()))
        except Exception:
            pass  # 静默失败，不影响启动

    def auto_layout_nodes(self):
        nodes = [
            item for item in self.canvas_scene.items() if isinstance(item, NodeItem)
        ]
        if not nodes:
            return

        utils.topological_layout(
            nodes,
            get_outgoing=lambda n: [e.dest_node for e in n.edges_out],
            get_sort_key=lambda n: n.scenePos().y(),
            set_pos_func=lambda n, x, y: n.setPos(x, y),
            layout_mode="alap",
        )

        for item in self.canvas_scene.items():
            if isinstance(item, EdgeItem):
                item.update_position()

        QTimer.singleShot(0, lambda: self.canvas_view.centerOn(
            self.canvas_scene.itemsBoundingRect().center()))

    def export_workflow(self):
        self.save_current_node_draft()
        self._sync_runtime_parameters()
        nodes = [
            item for item in self.canvas_scene.items() if isinstance(item, NodeItem)
        ]
        config = self.ctx.build_workflow_logic(nodes)

        if not config:
            QMessageBox.warning(self, "错误", "无法导出：可能存在异常连线结构。")
            return

        # persist operator visibility settings
        config["hidden_toolbox"] = list(self.hidden_toolbox)
        config["hidden_context_menu"] = list(self.hidden_context_menu)
        config["naming_style"] = self.naming_style
        if self.custom_names:
            config["custom_names"] = dict(self.custom_names)

        path, _ = QFileDialog.getSaveFileName(
            self, "保存工作流模板", "my_workflow.json", "JSON (*.json)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            self._last_workflow_path = path
            self._save_app_settings()
            QMessageBox.information(self, "成功", "工作流模板已保存。")

    def import_workflow(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入工作流模板", "", "JSON (*.json)"
        )
        if not path:
            return
        self._last_workflow_path = path
        try:
            with open(path, "r", encoding="utf-8") as f:
                workflow = json.load(f)
            self.runtime_parameters = workflow.get("runtime_parameters", {})
            self.parameter_mappings = workflow.get("parameter_mappings", {})
            self._sync_runtime_parameters()

            # restore operator visibility settings
            saved_tb = workflow.get("hidden_toolbox", [])
            saved_ctx = workflow.get("hidden_context_menu", [])
            if saved_tb:
                self.hidden_toolbox = set(saved_tb)
                self.toolbox.set_hidden_operators(self.hidden_toolbox)
            if saved_ctx:
                self.hidden_context_menu = set(saved_ctx)

            # restore naming style
            self.naming_style = workflow.get("naming_style", "默认")
            self.custom_names = workflow.get("custom_names", {})
            self.toolbox.set_naming(self.naming_style, self.custom_names)

            steps = workflow.get("steps", [])
            if not steps:
                return

            missing_files = {}
            for step in steps:
                if step.get("action") == "load_file":
                    fpath = step.get("params", {}).get("file_path")
                    if fpath and not os.path.exists(fpath):
                        missing_files[step.get("node_id")] = fpath

            if missing_files:
                dlg = PathRemapDialog(missing_files, self)
                if dlg.exec_() == QDialog.Accepted:
                    mapping = dlg.get_mapping()
                    for step in steps:
                        if step.get("node_id") in mapping:
                            step["params"]["file_path"] = mapping[step["node_id"]]
                else:
                    return

            self.canvas_scene.clear()
            self.ctx.clear_context()

            created_nodes = {}
            for i, step in enumerate(steps):
                node_id = step.get("node_id", f"legacy_{i}")
                action = step.get("action")
                out_name = step.get("out_name", f"Result_{i}")
                params = step.get("params", {})
                params["out_name"] = out_name
                params["action"] = action

                color = NODE_REGISTRY.get(action, {}).get("color", "#1976D2")
                title = f"{out_name}" if action != "load_file" else f"表: {out_name}"
                node = NodeItem(
                    node_id,
                    action,
                    title,
                    color,
                    step.get("x", 50),
                    step.get("y", 50 + i * 100),
                )
                node.params = params
                node.is_dirty = True
                self.canvas_scene.addItem(node)
                created_nodes[node_id] = node

            for step in steps:
                node = created_nodes.get(step.get("node_id"))
                if not node:
                    continue
                deps = []
                p = step.get("params", {})
                if node.action_type in ("left_join", "concat_rows"):
                    if "df1_id" in p:
                        deps.append(p["df1_id"])
                    if "df2_id" in p:
                        deps.append(p["df2_id"])
                elif node.action_type == "insert_block":
                    if "df_id" in p:
                        deps.append(p["df_id"])
                    if "template_id" in p:
                        deps.append(p["template_id"])
                elif "df_id" in p:
                    deps.append(p["df_id"])

                for src_id in deps:
                    if src_id in created_nodes:
                        edge = EdgeItem(created_nodes[src_id], node)
                        self.canvas_scene.addItem(edge)
                        created_nodes[src_id].edges_out.append(edge)
                        node.edges_in.append(edge)

            QTimer.singleShot(0, lambda: self.canvas_view.centerOn(
                self.canvas_scene.itemsBoundingRect().center()))

            QMessageBox.information(self, "导入成功", "工作流模板装载完毕。")
            self.run_full_workflow()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取失败: {e}")
