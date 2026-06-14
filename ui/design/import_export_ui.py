"""Import/export entry points for design-mode workflow files."""

import os

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QDialog

from node_editor import NodeItem
from ui.design.workflow_io import (
    apply_file_mapping,
    attach_design_preferences,
    find_missing_load_files,
    load_workflow_file,
    restore_design_preferences,
    restore_runtime_metadata,
    restore_steps_to_scene,
    save_workflow_file,
)
from ui.dialogs.path_remap import PathRemapDialog


class ImportExportUIMixin:
    def _auto_load_workflow(self, path):
        """启动时静默加载上次工作流（不弹窗、不执行）。"""
        try:
            workflow = load_workflow_file(path)
            restore_runtime_metadata(self, workflow)
            steps = workflow.get("steps", [])
            if not steps:
                return

            self.ctx.clear_context()
            restore_steps_to_scene(steps, self.canvas_scene)

            self._update_status_bar()
            QTimer.singleShot(100, self.run_full_workflow)
            QTimer.singleShot(
                0,
                lambda: self.canvas_view.centerOn(
                    self.canvas_scene.itemsBoundingRect().center()
                ),
            )
        except Exception:
            pass

    def export_workflow(self):
        self.save_current_node_draft()
        self._sync_runtime_parameters()
        nodes = [item for item in self.canvas_scene.items() if isinstance(item, NodeItem)]
        config = self.ctx.build_workflow_logic(nodes)

        if not config:
            QMessageBox.warning(self, "错误", "无法导出：可能存在异常连线结构。")
            return

        attach_design_preferences(
            config,
            self.hidden_toolbox,
            self.hidden_context_menu,
            self.naming_style,
            self.custom_names,
        )

        path, _ = QFileDialog.getSaveFileName(
            self, "保存工作流模板", "my_workflow.json", "JSON (*.json)"
        )
        if path:
            save_workflow_file(path, config)
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
            workflow = load_workflow_file(path)
            restore_runtime_metadata(self, workflow)
            restore_design_preferences(self, workflow)

            steps = workflow.get("steps", [])
            if not steps:
                return

            missing_files = find_missing_load_files(steps)
            if missing_files:
                dlg = PathRemapDialog(missing_files, self)
                if dlg.exec_() == QDialog.Accepted:
                    apply_file_mapping(steps, dlg.get_mapping())
                else:
                    return

            self.ctx.clear_context()
            restore_steps_to_scene(steps, self.canvas_scene)

            QTimer.singleShot(
                0,
                lambda: self.canvas_view.centerOn(
                    self.canvas_scene.itemsBoundingRect().center()
                ),
            )

            QMessageBox.information(self, "导入成功", "工作流模板装载完毕。")
            self.run_full_workflow()
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"读取失败: {exc}")

    def _load_last_workflow_if_needed(self, last_path):
        if last_path and os.path.exists(last_path):
            self._auto_load_workflow(last_path)
