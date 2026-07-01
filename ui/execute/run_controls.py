"""Workflow engine run controls for execute mode."""

from PyQt5.QtWidgets import QMessageBox

from engine import WorkflowEngine
from ui.execute.styles import RUN_BUTTON_ACTIVE_STYLE, RUN_BUTTON_BUSY_STYLE


class ExecuteRunControlsMixin:
    def run_engine(self):
        if not self.workflow_config:
            return

        self.log_output.clear()
        self._set_running_ui_state(total_steps=len(self.workflow_config.get("steps", [])))

        for item in self.graph_view.node_items_dict.values():
            item.has_data = False
            item.set_status("pending")

        keep_mem = self.cb_debug.isChecked()
        self.engine_thread = WorkflowEngine(
            self.file_mapping, self.workflow_config, keep_intermediates=keep_mem
        )
        self.engine_thread.log_signal.connect(self.log_print)
        self.engine_thread.progress_signal.connect(self.progress_bar.setValue)
        self.engine_thread.finished_signal.connect(self.on_engine_finished)
        self.engine_thread.start()

    def _set_running_ui_state(self, total_steps):
        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳ 执行中...")
        self.btn_run.setStyleSheet(RUN_BUTTON_BUSY_STYLE)
        self.btn_load_json.setEnabled(False)
        self.btn_mapping.setEnabled(False)
        self.cb_debug.setEnabled(False)

        self.progress_bar.setRange(0, total_steps)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"%v / {total_steps} 步")
        self.lbl_status.setText("正在跑批计算...")
        self.lbl_status.setStyleSheet("color: #E65100; font-weight: bold;")
        self.status_detail.setText("")

    def on_engine_finished(self, success, pool):
        self._restore_idle_ui_state()

        if success:
            self._handle_engine_success(pool)
        else:
            self._handle_engine_failure()

    def _restore_idle_ui_state(self):
        self.btn_run.setEnabled(True)
        self.btn_run.setText("▶ 运行引擎")
        self.btn_run.setStyleSheet(RUN_BUTTON_ACTIVE_STYLE)
        self.btn_load_json.setEnabled(True)
        self.btn_mapping.setEnabled(True)
        self.cb_debug.setEnabled(True)

    def _handle_engine_success(self, pool):
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.progress_bar.setFormat("完成")
        self.lbl_status.setText("执行完毕")
        self.lbl_status.setStyleSheet("color: #4CAF50; font-weight: bold;")
        data_pool = pool.get("data", pool) if isinstance(pool, dict) else {}
        self.status_detail.setText("已完成")

        self.graph_view.set_all_nodes_status("success")
        self.final_pool = data_pool

        # 节点是否有可预览数据取决于最终 pool；状态成功不代表一定保留中间表。
        for item in set(self.graph_view.node_items_dict.values()):
            if item.status == "success":
                item.has_data = item.table_name in self.final_pool
            item.update()

        QMessageBox.information(
            self, "成功", "工作流执行完毕！\n请在下方数据预览区域点击节点查看结果。"
        )

    def _handle_engine_failure(self):
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("失败")
        self.lbl_status.setText("执行中断")
        self.lbl_status.setStyleSheet("color: #F44336; font-weight: bold;")
        self.status_detail.setText("请查看运行日志定位问题")

        self.graph_view.set_all_nodes_status("error")

        QMessageBox.critical(
            self, "执行失败", "工作流执行遇到错误，请查看右侧运行日志定位问题节点。"
        )
