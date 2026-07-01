"""Full-workflow run controls for the design mode."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox, QProgressDialog

from node_editor import NodeItem


class RunControlsMixin:
    def run_full_workflow(self):
        self.save_current_node_draft()
        self._sync_runtime_parameters()
        nodes = [
            item for item in self.canvas_scene.items() if isinstance(item, NodeItem)
        ]

        config = self.ctx.build_workflow_logic(nodes)
        if not config:
            QMessageBox.warning(self, "警告", "存在死循环连线，无法处理。")
            return

        total_steps = len(config["steps"])

        self.progress = QProgressDialog("正在高速全量执行流水线...", None, 0, total_steps, self)
        self.progress.setWindowTitle("执行中")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setAutoClose(True)
        self.progress.show()
        self.ctx.run_full_workflow()
        if self.ctx.engine:
            self.ctx.engine.progress_signal.connect(self.progress.setValue)

    def _on_full_run_finished(self, success, result_pool):
        self.progress.close()
        self._update_status_bar()
        if success:
            for item in self.canvas_scene.items():
                if isinstance(item, NodeItem):
                    item.is_dirty = False
                    item.update()
            self.refresh_combo_list()
            QMessageBox.information(self, "成功", "流水线跑批完毕！")
            node = self._current_live_node() if hasattr(self, "_current_live_node") else self.current_selected_node
            if self.chk_auto_follow.isChecked() and node is not None:
                self._render_node_preview(node)
            elif not self.chk_auto_follow.isChecked():
                table_name = self.combo_preview_tables.currentText()
                if table_name and table_name != "暂无数据":
                    self._render_specific_table(table_name)
        else:
            QMessageBox.critical(
                self, "错误", "执行出错，请检查数据完整性或查看执行模式下的日志信息。"
            )
