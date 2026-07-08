"""Design-mode main page."""

import pandas as pd
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from ui.design.app_state import (
    apply_design_state,
    collect_design_state,
    load_workspace_config,
    save_workspace_config,
    workspace_config_path,
)
from ui.design.canvas_actions import CanvasActionsMixin
from ui.design.context_menu import CanvasContextMenuMixin
from ui.design.dock_controls import DockControlsMixin
from ui.design.import_export_ui import ImportExportUIMixin
from ui.design.layout_builder import build_config_dialog, build_dock_workspace
from ui.design.node_config import NodeConfigMixin
from ui.design.preview_panel import PreviewPanelMixin
from ui.design.run_controls import RunControlsMixin
from ui.design.status_bar import StatusBarMixin, build_status_bar
from ui.design.toolbar import build_design_toolbar
from workspace_context import WorkspaceContext


class DesignModeWidget(
    CanvasActionsMixin,
    CanvasContextMenuMixin,
    NodeConfigMixin,
    ImportExportUIMixin,
    RunControlsMixin,
    DockControlsMixin,
    PreviewPanelMixin,
    StatusBarMixin,
    QWidget,
):
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
        self.global_code = ""
        self.function_spaces = []
        self.crpa_metadata = {}
        self.run_manifest = {}

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 4, 6, 4)
        main_layout.setSpacing(4)

        # === Top Toolbar ===
        main_layout.addLayout(build_design_toolbar(self))

        # === Dockable Layout: Toolbox | Canvas | Preview ===
        main_layout.addWidget(build_dock_workspace(self), stretch=1)

        # === Right Inspector Dock ===
        build_config_dialog(self)

        # === Bottom Status Bar ===
        main_layout.addLayout(build_status_bar(self))

        # 恢复上次保存的设置
        self._load_app_settings()

    @property
    def _settings_path(self):
        return workspace_config_path()

    def save_design_state(self):
        """保存设计模式状态到配置文件（供 main.py closeEvent 调用）"""
        self._save_app_settings()

    def shutdown_for_close(self, timeout_ms=3000):
        if hasattr(self, "_stop_full_run_timeout_timer"):
            self._stop_full_run_timeout_timer()
        if hasattr(self, "shutdown_single_node_runtime") and not self.shutdown_single_node_runtime(timeout_ms):
            return False
        if hasattr(self.ctx, "shutdown_for_close") and not self.ctx.shutdown_for_close(timeout_ms):
            return False
        if hasattr(self, "_clear_preview_model_cache"):
            self._clear_preview_model_cache()
        self.current_selected_node = None
        if hasattr(self, "preview_tabs"):
            self.preview_tabs.clear()
        if hasattr(self, "canvas_scene"):
            self.canvas_scene.clear()
        return True

    def _save_app_settings(self):
        data = load_workspace_config()
        data["design_mode"] = collect_design_state(self)
        save_workspace_config(data)

    def _load_app_settings(self):
        data = load_workspace_config()
        dm = data.get("design_mode", {})

        # 自动加载设计模式上次工作流
        last_path = apply_design_state(self, dm)
        self._load_last_workflow_if_needed(last_path)
