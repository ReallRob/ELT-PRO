"""Full-workflow run controls for the design mode."""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QMessageBox, QProgressDialog

from node_editor import NodeItem
from core.workflow.timeouts import workflow_code_timeout_ms


class RunControlsMixin:
    def _clear_all_stale_edges(self):
        for item in self.canvas_scene.items():
            if hasattr(item, "set_stale"):
                item.set_stale(False)

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

        self.progress = QProgressDialog("正在高速全量执行流水线...", None, 0, total_steps, self)
        self.progress.setWindowTitle("执行中")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setAutoClose(True)
        self.progress.show()
        self.ctx.run_full_workflow()
        if self.ctx.engine:
            self.ctx.engine.progress_signal.connect(self.progress.setValue)
        self._start_full_run_timeout_timer(config)

    def _start_full_run_timeout_timer(self, config):
        timer = getattr(self, "_full_run_timeout_timer", None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        timeout_ms = workflow_code_timeout_ms(config)
        self._full_run_timeout_timer = None
        if not timeout_ms:
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._on_full_run_timeout)
        self._full_run_timeout_timer = timer
        timer.start(timeout_ms)

    def _stop_full_run_timeout_timer(self):
        timer = getattr(self, "_full_run_timeout_timer", None)
        self._full_run_timeout_timer = None
        if timer is None:
            return
        timer.stop()
        timer.deleteLater()

    def _on_full_run_timeout(self):
        self._stop_full_run_timeout_timer()
        if hasattr(self.ctx, "discard_current_workflow_run"):
            self.ctx.discard_current_workflow_run()
        if hasattr(self, "progress") and self.progress:
            self.progress.close()
        if hasattr(self, "status_label"):
            self.status_label.setText("全量流程已超时，后台结果将被忽略")
        QMessageBox.warning(self, "运行超时", "全量流程已超过代码块超时时间，结果将被忽略；后台线程可能仍在收尾。")

    def _on_full_run_finished(self, success, result_pool):
        self._stop_full_run_timeout_timer()
        self.progress.close()
        self._update_status_bar()
        if success:
            for item in self.canvas_scene.items():
                if isinstance(item, NodeItem):
                    item.is_dirty = False
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
            QMessageBox.critical(
                self, "错误", "执行出错，请检查数据完整性或查看执行模式下的日志信息。"
            )
