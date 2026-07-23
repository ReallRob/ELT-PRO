"""Full-workflow run controls for the design mode."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox, QProgressDialog

from node_editor import NodeItem


class RunControlsMixin:
    def _clear_all_stale_edges(self):
        for item in self.canvas_scene.items():
            if hasattr(item, "set_stale"):
                item.set_stale(False)

    def _set_node_run_status(self, node_id, status):
        target = str(node_id or "")
        if not target:
            return
        for item in self.canvas_scene.items():
            if isinstance(item, NodeItem) and str(item.node_id) == target:
                item.run_status = status
                item.update()
                return

    def _clear_node_run_statuses(self):
        for item in self.canvas_scene.items():
            if isinstance(item, NodeItem):
                item.run_status = "idle"
                item.update()

    def run_full_workflow(self):
        if hasattr(self, "_single_node_run_active") and self._single_node_run_active():
            QMessageBox.information(self, "运行中", "当前已有单节点在后台运行，请等待完成后再执行全量流程。")
            return
        if hasattr(self, "_discarded_single_node_engine_running") and self._discarded_single_node_engine_running():
            QMessageBox.information(self, "运行中", "仍有已废弃的后台任务在收尾，请等待结束后再执行全量流程。")
            return
        if hasattr(self.ctx, "discarded_engine_running") and self.ctx.discarded_engine_running():
            QMessageBox.information(self, "运行中", "仍有已废弃的全量流程在收尾，请等待结束后再执行。")
            return
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
        self._clear_node_run_statuses()

        self.progress = QProgressDialog("正在高速全量执行流水线...", "停止", 0, total_steps, self)
        self.progress.setWindowTitle("执行中")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setAutoClose(True)
        self.progress.canceled.connect(self._request_full_run_stop)
        self.progress.show()
        self.ctx.run_full_workflow()
        if self.ctx.engine:
            self.ctx.engine.progress_signal.connect(self.progress.setValue)

    def _request_full_run_stop(self):
        engine = getattr(self.ctx, "engine", None)
        if engine is None or not hasattr(engine, "request_cancel"):
            return
        engine.request_cancel()
        if hasattr(self, "status_label"):
            self.status_label.setText("已请求停止，等待当前代码块自行退出...")
        if hasattr(self, "progress") and self.progress:
            self.progress.setLabelText("已请求停止，等待当前代码块自行退出...")

    def _close_full_run_progress(self):
        progress = getattr(self, "progress", None)
        if progress is None:
            return
        try:
            progress.canceled.disconnect(self._request_full_run_stop)
        except (TypeError, RuntimeError):
            pass
        progress.close()

    def _on_full_run_finished(self, success, result_pool):
        self._close_full_run_progress()
        result_pool = result_pool or {}
        success_node_ids = set(result_pool.get("success_node_ids") or []) if isinstance(result_pool, dict) else set()
        failed_node_id = result_pool.get("failed_node_id") if isinstance(result_pool, dict) else ""
        for node_id in success_node_ids:
            self._set_node_run_status(node_id, "success")
        if failed_node_id:
            self._set_node_run_status(failed_node_id, "error")
        self._update_status_bar()
        if success:
            for item in self.canvas_scene.items():
                if isinstance(item, NodeItem):
                    item.is_dirty = False
                    item.run_status = "success"
                    item.update()
            self._clear_all_stale_edges()
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
            if isinstance(result_pool, dict) and result_pool.get("cancelled"):
                if hasattr(self, "status_label"):
                    self.status_label.setText("流程已停止")
                QMessageBox.information(self, "已停止", "已请求停止，当前流程已结束。")
                return
            QMessageBox.critical(
                self, "错误", "执行出错，请检查数据完整性或查看执行模式下的日志信息。"
            )
