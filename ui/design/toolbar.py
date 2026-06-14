"""Top toolbar construction for the design mode."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QPushButton


def _make_separator():
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setStyleSheet("color: #ddd;")
    return line


def build_design_toolbar(owner):
    toolbar = QHBoxLayout()
    toolbar.setSpacing(8)

    btn_import = QPushButton("导入模板")
    btn_export = QPushButton("导出模板")
    btn_clear = QPushButton("清空画布")
    btn_view = QPushButton("▤ 视图")
    btn_settings = QPushButton("⚙ 设置")
    io_btn_style = """
        QPushButton { background-color: white; border: 1px solid #ccc; padding: 5px 12px; border-radius: 4px; font-size: 12px; }
        QPushButton:hover { background-color: #f0f0f0; border-color: #999; }
    """
    for button in [btn_import, btn_export, btn_clear, btn_view, btn_settings]:
        button.setStyleSheet(io_btn_style)
        button.setCursor(Qt.PointingHandCursor)

    btn_import.clicked.connect(owner.import_workflow)
    btn_export.clicked.connect(owner.export_workflow)
    btn_clear.clicked.connect(owner.clear_canvas_logic)
    btn_view.clicked.connect(owner._show_view_menu)
    btn_settings.clicked.connect(owner.open_operator_settings)

    owner.btn_run_all = QPushButton("全量跑批执行")
    owner.btn_run_all.setStyleSheet(
        "background-color: #4CAF50; color: white; font-weight: bold; border-radius: 4px; padding: 5px 15px;"
    )
    owner.btn_run_all.clicked.connect(owner.run_full_workflow)

    owner.btn_auto_layout = QPushButton("整理排版")
    owner.btn_auto_layout.setStyleSheet(
        "background-color: #009688; color: white; font-weight: bold; border-radius: 4px; padding: 5px 15px;"
    )
    owner.btn_auto_layout.clicked.connect(owner.auto_layout_nodes)

    owner.btn_delete_node = QPushButton("删除选中")
    owner.btn_delete_node.setStyleSheet(
        "background-color: #f44336; color: white; font-weight: bold; border-radius: 4px; padding: 5px 12px;"
    )
    owner.btn_delete_node.clicked.connect(owner.delete_canvas_node)

    toolbar.addWidget(btn_import)
    toolbar.addWidget(btn_export)
    toolbar.addWidget(btn_clear)
    toolbar.addWidget(btn_view)
    toolbar.addWidget(btn_settings)
    toolbar.addWidget(_make_separator())
    toolbar.addWidget(owner.btn_run_all)
    toolbar.addWidget(owner.btn_auto_layout)
    toolbar.addWidget(_make_separator())
    toolbar.addStretch(1)
    toolbar.addWidget(owner.btn_delete_node)
    return toolbar
