"""Execute-mode main page."""

from PyQt5.QtWidgets import QVBoxLayout, QWidget

from ui.execute.layout_builder import build_execute_status_bar, build_execute_workspace
from ui.execute.logging_panel import ExecuteLoggingMixin
from ui.execute.preview_panel import ExecutePreviewMixin
from ui.execute.run_controls import ExecuteRunControlsMixin
from ui.execute.toolbar import build_execute_toolbar
from ui.execute.workflow_file import ExecuteWorkflowFileMixin


class ExecuteModeWidget(
    ExecuteWorkflowFileMixin,
    ExecuteRunControlsMixin,
    ExecutePreviewMixin,
    ExecuteLoggingMixin,
    QWidget,
):
    """Runtime page that imports workflow JSON, executes it, and previews results."""

    def __init__(self):
        super().__init__()
        self.workflow_config = None
        self.current_workflow_path = None
        self.file_mapping = {}
        self.file_context = {}
        self.final_pool = {}
        self.current_preview_table = None
        self.engine_thread = None
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 4, 6, 4)
        main_layout.setSpacing(4)

        # 执行模式只负责运行已生成的工作流，参数配置入口统一留在设计态算子中。
        main_layout.addLayout(build_execute_toolbar(self))
        main_layout.addWidget(build_execute_workspace(self), stretch=1)
        main_layout.addLayout(build_execute_status_bar(self))
