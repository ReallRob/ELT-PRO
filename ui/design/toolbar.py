"""Top toolbar construction for the design mode."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QPushButton


BASE_BUTTON_STYLE = """
    QPushButton {
        min-height: 30px;
        padding: 0 12px;
        border-radius: 5px;
        font-size: 12px;
        font-weight: 500;
    }
"""

NEUTRAL_BUTTON_STYLE = BASE_BUTTON_STYLE + """
    QPushButton {
        background-color: #FFFFFF;
        border: 1px solid #CBD5E1;
        color: #1F2933;
    }
    QPushButton:hover { background-color: #F8FAFC; border-color: #94A3B8; }
    QPushButton:pressed { background-color: #EEF2F7; }
"""

PRIMARY_BUTTON_STYLE = BASE_BUTTON_STYLE + """
    QPushButton {
        background-color: #2E7D32;
        border: 1px solid #2E7D32;
        color: #FFFFFF;
        font-weight: 600;
    }
    QPushButton:hover { background-color: #276D2B; border-color: #276D2B; }
    QPushButton:pressed { background-color: #1F5B23; }
"""

ACCENT_BUTTON_STYLE = BASE_BUTTON_STYLE + """
    QPushButton {
        background-color: #00897B;
        border: 1px solid #00897B;
        color: #FFFFFF;
        font-weight: 600;
    }
    QPushButton:hover { background-color: #00796B; border-color: #00796B; }
    QPushButton:pressed { background-color: #00695C; }
"""

DANGER_BUTTON_STYLE = BASE_BUTTON_STYLE + """
    QPushButton {
        background-color: #E53935;
        border: 1px solid #E53935;
        color: #FFFFFF;
        font-weight: 600;
    }
    QPushButton:hover { background-color: #D32F2F; border-color: #D32F2F; }
    QPushButton:pressed { background-color: #B71C1C; }
"""


def _style_button(button, style):
    button.setStyleSheet(style)
    button.setCursor(Qt.PointingHandCursor)


def _make_separator():
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setFixedHeight(26)
    line.setStyleSheet("color: #D8DEE6; margin: 2px 4px;")
    return line


def build_design_toolbar(owner):
    toolbar = QHBoxLayout()
    toolbar.setContentsMargins(0, 0, 0, 0)
    toolbar.setSpacing(8)

    btn_import = QPushButton("导入模板")
    btn_export = QPushButton("导出模板")
    btn_clear = QPushButton("清空画布")
    btn_view = QPushButton("视图")
    btn_settings = QPushButton("设置")
    btn_publish = QPushButton("发布信息")
    for button in [btn_import, btn_export, btn_clear, btn_view, btn_settings, btn_publish]:
        _style_button(button, NEUTRAL_BUTTON_STYLE)

    btn_import.clicked.connect(owner.import_workflow)
    btn_export.clicked.connect(owner.export_workflow)
    btn_clear.clicked.connect(owner.clear_canvas_logic)
    btn_view.clicked.connect(owner._show_view_menu)
    btn_settings.clicked.connect(owner.open_operator_settings)
    btn_publish.clicked.connect(owner.open_publish_settings)

    owner.btn_run_all = QPushButton("全量跑批执行")
    _style_button(owner.btn_run_all, PRIMARY_BUTTON_STYLE)
    owner.btn_run_all.clicked.connect(owner.run_full_workflow)

    owner.btn_auto_layout = QPushButton("整理排版")
    _style_button(owner.btn_auto_layout, ACCENT_BUTTON_STYLE)
    owner.btn_auto_layout.clicked.connect(owner.auto_layout_nodes)

    owner.btn_copy_node = QPushButton("复制选中")
    _style_button(owner.btn_copy_node, NEUTRAL_BUTTON_STYLE)
    owner.btn_copy_node.clicked.connect(owner.copy_selected_nodes)

    owner.btn_delete_node = QPushButton("删除选中")
    _style_button(owner.btn_delete_node, DANGER_BUTTON_STYLE)
    owner.btn_delete_node.clicked.connect(owner.delete_canvas_node)

    toolbar.addWidget(btn_import)
    toolbar.addWidget(btn_export)
    toolbar.addWidget(btn_clear)
    toolbar.addWidget(btn_view)
    toolbar.addWidget(btn_settings)
    toolbar.addWidget(btn_publish)
    toolbar.addWidget(_make_separator())
    toolbar.addWidget(owner.btn_run_all)
    toolbar.addWidget(owner.btn_auto_layout)
    toolbar.addWidget(_make_separator())
    toolbar.addStretch(1)
    toolbar.addWidget(owner.btn_copy_node)
    toolbar.addWidget(owner.btn_delete_node)
    return toolbar
