"""Top toolbar construction for the execute mode."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton

from ui.execute.styles import MAPPING_BUTTON_STYLE, RUN_BUTTON_ACTIVE_STYLE, TOOLBAR_BUTTON_STYLE


def _make_separator():
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setStyleSheet("color: #ddd;")
    return line


def build_execute_toolbar(owner):
    """Create the run-mode toolbar and wire actions back to the main widget."""
    toolbar = QHBoxLayout()
    toolbar.setSpacing(8)

    owner.btn_load_json = QPushButton("导入工作流")
    owner.btn_load_json.setFixedHeight(32)
    owner.btn_load_json.setCursor(Qt.PointingHandCursor)
    owner.btn_load_json.setStyleSheet(TOOLBAR_BUTTON_STYLE)
    owner.btn_load_json.clicked.connect(owner.load_workflow_config)

    owner.btn_mapping = QPushButton("数据源映射")
    owner.btn_mapping.setFixedHeight(32)
    owner.btn_mapping.setCursor(Qt.PointingHandCursor)
    owner.btn_mapping.setStyleSheet(MAPPING_BUTTON_STYLE)
    owner.btn_mapping.clicked.connect(owner.show_mapping_dialog)
    owner.btn_mapping.setEnabled(False)

    owner.btn_run = QPushButton("▶ 运行引擎")
    owner.btn_run.setFixedHeight(32)
    owner.btn_run.setCursor(Qt.PointingHandCursor)
    owner.btn_run.setStyleSheet(RUN_BUTTON_ACTIVE_STYLE)
    owner.btn_run.clicked.connect(owner.run_engine)
    owner.btn_run.setEnabled(False)

    owner.cb_debug = QCheckBox("保留中间表")
    owner.cb_debug.setStyleSheet("font-weight: bold; color: #1976D2;")
    owner.cb_debug.setToolTip("开启后引擎保留所有节点的中间数据以便预览。")

    owner.lbl_status = QLabel("就绪")
    owner.lbl_status.setStyleSheet("color: #666; font-weight: bold; font-size: 12px;")

    toolbar.addWidget(owner.btn_load_json)
    toolbar.addWidget(owner.btn_mapping)
    toolbar.addWidget(_make_separator())
    toolbar.addWidget(owner.btn_run)
    toolbar.addWidget(_make_separator())
    toolbar.addWidget(owner.cb_debug)
    toolbar.addStretch(1)
    toolbar.addWidget(owner.lbl_status)
    return toolbar
