"""Design-mode settings dialog."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from operator_registry import CATEGORY_ORDER, NODE_REGISTRY, OPERATOR_NAME_STYLES, get_operator_title


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
