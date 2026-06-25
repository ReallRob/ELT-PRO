"""Dock visibility and floating-window controls for design mode."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QWidget


class DockControlsMixin:
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
            action.toggled.connect(lambda checked, d=dock: d.setVisible(checked))

        menu.addSeparator()
        reset_action = menu.addAction("重置布局")
        reset_action.triggered.connect(self._reset_dock_layout)

        menu.exec_(self.sender().mapToGlobal(self.sender().rect().bottomLeft()))

    def _reset_dock_layout(self):
        """恢复默认停靠位置。"""
        self.dock_toolbox.setFloating(False)
        self.dock_preview.setFloating(False)
        self.dock_config.setFloating(False)
        self.dock_main.addDockWidget(Qt.LeftDockWidgetArea, self.dock_toolbox)
        self.dock_main.addDockWidget(Qt.RightDockWidgetArea, self.dock_config)
        self.dock_main.addDockWidget(Qt.BottomDockWidgetArea, self.dock_preview)
        self.dock_toolbox.show()
        self.dock_config.show()
        self.dock_preview.show()
        self.dock_main.resizeDocks(
            [self.dock_toolbox, self.dock_config], [240, 360], Qt.Horizontal
        )
        self.dock_main.resizeDocks([self.dock_preview], [220], Qt.Vertical)
        # 清除窗口置顶标志，避免重置后浮窗仍压在主窗口上。
        for dock in self._all_docks:
            if dock.isFloating():
                dock.setWindowFlags(dock.windowFlags() & ~Qt.WindowStaysOnTopHint)
                dock.show()

    def _on_dock_float_changed(self, dock, floating):
        """dock 变为浮动窗口时，标题栏增加置顶按钮。"""
        if not hasattr(self, "_pin_buttons"):
            self._pin_buttons = {}

        if floating:
            title_bar = QWidget()
            title_layout = QHBoxLayout(title_bar)
            title_layout.setContentsMargins(8, 2, 4, 2)
            title_layout.setSpacing(6)

            title = QLabel(dock.windowTitle())
            title.setStyleSheet("font-weight: bold; font-size: 12px; border: none;")
            pin_btn = QPushButton("📌")
            pin_btn.setFixedSize(24, 22)
            pin_btn.setCheckable(True)
            pin_btn.setToolTip("保持置顶")
            pin_btn.setStyleSheet(
                "QPushButton { border: 1px solid #DDD; border-radius: 3px; background: #FAFAFA; }"
                "QPushButton:hover { background: #EEE; }"
                "QPushButton:checked { background: #FFF3E0; border-color: #FF9800; }"
            )
            pin_btn.toggled.connect(lambda checked, d=dock: self._toggle_dock_pin(d, checked))
            self._pin_buttons[id(dock)] = pin_btn

            title_layout.addWidget(title)
            title_layout.addStretch()
            title_layout.addWidget(pin_btn)
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
