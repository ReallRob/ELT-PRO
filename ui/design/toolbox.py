"""Toolbox widgets for the design canvas."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QGroupBox, QPushButton, QScrollArea, QVBoxLayout, QWidget

from operator_registry import CATEGORY_ORDER, NODE_REGISTRY, get_operator_title


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
