"""Main execute-mode layout builders."""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.execute.workflow_graph import WorkflowGraphView


def build_execute_workspace(owner):
    """Build the workflow info, graph, preview, and log areas."""
    owner.main_splitter = QSplitter(Qt.Horizontal)

    owner.main_splitter.addWidget(_build_info_panel(owner))
    owner.main_splitter.addWidget(_build_right_workspace(owner))
    owner.main_splitter.setSizes([180, 1100])
    return owner.main_splitter


def _build_info_panel(owner):
    info_panel = QWidget()
    info_panel.setMaximumWidth(220)
    info_panel.setMinimumWidth(140)
    info_panel.setStyleSheet(
        "background: #f8f9fa; border: 1px solid #ddd; border-radius: 4px;"
    )

    info_layout = QVBoxLayout(info_panel)
    info_layout.setContentsMargins(8, 8, 8, 8)
    info_layout.setSpacing(6)

    info_title = QLabel("工作流信息")
    info_title.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
    info_title.setStyleSheet("border: none;")

    owner.info_name = QLabel("未加载")
    owner.info_name.setWordWrap(True)
    owner.info_name.setStyleSheet("border: none; color: #333; font-size: 11px;")

    owner.info_steps = QLabel("步骤: —")
    owner.info_steps.setStyleSheet("border: none; color: #666; font-size: 11px;")

    owner.info_files_label = QLabel("数据源:")
    owner.info_files_label.setStyleSheet(
        "border: none; color: #666; font-size: 10px; font-weight: bold;"
    )
    owner.info_files = QLabel("—")
    owner.info_files.setWordWrap(True)
    owner.info_files.setStyleSheet("border: none; color: #999; font-size: 10px;")

    info_layout.addWidget(info_title)
    info_layout.addWidget(owner.info_name)
    info_layout.addWidget(owner.info_steps)
    info_layout.addWidget(owner.info_files_label)
    info_layout.addWidget(owner.info_files)
    info_layout.addStretch(1)
    return info_panel


def _build_right_workspace(owner):
    right_splitter = QSplitter(Qt.Vertical)
    right_splitter.addWidget(_build_graph_panel(owner))
    right_splitter.addWidget(_build_bottom_splitter(owner))
    right_splitter.setStretchFactor(0, 6)
    right_splitter.setStretchFactor(1, 4)
    return right_splitter


def _build_graph_panel(owner):
    graph_panel = QWidget()
    graph_layout = QVBoxLayout(graph_panel)
    graph_layout.setContentsMargins(0, 0, 0, 0)
    graph_layout.setSpacing(2)

    lbl_graph = QLabel(" 监控大盘 (中键漫游 | Ctrl+滚轮缩放 | 右键导出)")
    lbl_graph.setFont(QFont("Arial", 9, QFont.Bold))
    lbl_graph.setStyleSheet("color: #666; padding: 2px;")

    owner.graph_view = WorkflowGraphView()
    owner.graph_view.node_clicked.connect(owner.on_node_clicked)
    owner.graph_view.request_export.connect(owner.export_single_table)

    graph_layout.addWidget(lbl_graph)
    graph_layout.addWidget(owner.graph_view)
    return graph_panel


def _build_bottom_splitter(owner):
    bottom_splitter = QSplitter(Qt.Horizontal)
    bottom_splitter.addWidget(_build_preview_panel(owner))
    bottom_splitter.addWidget(_build_logs_panel(owner))
    bottom_splitter.setSizes([600, 400])
    return bottom_splitter


def _build_preview_panel(owner):
    preview_panel = QWidget()
    preview_layout = QVBoxLayout(preview_panel)
    preview_layout.setContentsMargins(4, 4, 4, 4)
    preview_layout.setSpacing(2)

    preview_header = QHBoxLayout()
    owner.preview_title = QLabel("点击画布节点预览数据")
    owner.preview_title.setStyleSheet("padding: 3px; color: gray; font-size: 11px;")

    owner.btn_export_preview = QPushButton("导出")
    owner.btn_export_preview.setFixedHeight(24)
    owner.btn_export_preview.setStyleSheet(
        "background-color: #4CAF50; color: white; font-weight: bold; "
        "padding: 2px 12px; border-radius: 3px; font-size: 11px;"
    )
    owner.btn_export_preview.hide()
    owner.btn_export_preview.clicked.connect(owner.export_current_table)

    preview_header.addWidget(owner.preview_title, stretch=1)
    preview_header.addWidget(owner.btn_export_preview)

    owner.result_table = None
    owner.result_preview_tabs = QTabWidget()
    owner.result_preview_tabs.setStyleSheet("""
        QTabWidget::pane { border: 1px solid #eee; background: white; }
        QTabBar::tab { background: #f5f5f5; border: 1px solid #ddd; padding: 4px 10px;
            border-top-left-radius: 3px; border-top-right-radius: 3px; margin-right: 1px; font-size: 11px; }
        QTabBar::tab:selected { background: #E1F5FE; color: #0277BD; border-bottom: none; }
    """)
    owner.result_preview_tabs.currentChanged.connect(owner._on_preview_tab_changed)

    preview_layout.addLayout(preview_header)
    preview_layout.addWidget(owner.result_preview_tabs)
    return preview_panel


def _build_logs_panel(owner):
    logs_panel = QWidget()
    logs_layout = QVBoxLayout(logs_panel)
    logs_layout.setContentsMargins(4, 4, 4, 4)
    logs_layout.setSpacing(2)

    logs_label = QLabel(" 运行日志")
    logs_label.setFont(QFont("Consolas", 9, QFont.Bold))
    logs_label.setStyleSheet("color: #888; padding: 2px;")

    owner.log_output = QTextEdit()
    owner.log_output.setReadOnly(True)
    owner.log_output.setStyleSheet(
        "background-color: #1E1E1E; color: #D4D4D4; font-family: Consolas; "
        "border: 1px solid #333; padding: 6px; font-size: 12px;"
    )

    logs_layout.addWidget(logs_label)
    logs_layout.addWidget(owner.log_output)
    return logs_panel


def build_execute_status_bar(owner):
    status_bar = QHBoxLayout()
    status_bar.setSpacing(8)

    owner.progress_bar = QProgressBar()
    owner.progress_bar.setFixedHeight(18)
    owner.progress_bar.setTextVisible(True)
    owner.progress_bar.setFormat("%v / %m 步")
    owner.progress_bar.setStyleSheet("""
        QProgressBar { border: 1px solid #ccc; border-radius: 8px; background-color: #f0f0f0; text-align: center; font-size: 11px; }
        QProgressBar::chunk { background-color: #4CAF50; border-radius: 8px; }
    """)

    owner.status_detail = QLabel("")
    owner.status_detail.setStyleSheet("color: #999; font-size: 11px;")

    status_bar.addWidget(owner.progress_bar, stretch=1)
    status_bar.addWidget(owner.status_detail)
    return status_bar
