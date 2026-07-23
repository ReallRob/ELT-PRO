"""Workflow engine run controls for execute mode."""

from PyQt5.QtWidgets import QMessageBox

from engine import WorkflowEngine
from ui.execute.styles import RUN_BUTTON_ACTIVE_STYLE, RUN_BUTTON_BUSY_STYLE


class ExecuteRunControlsMixin:
    def run_engine(self):
        engine = getattr(self, "engine_thread", None)
        try:
            running = engine is not None and engine.isRunning()
        except RuntimeError:
            running = False
        if running:
            self.request_engine_stop()
            return
        if not self.workflow_config:
            return
        if self._discarded_engine_running():
            QMessageBox.information(self, "运行中", "仍有已废弃的后台任务在收尾，请等待结束后再运行。")
            return

        self.log_output.clear()
        self._set_running_ui_state(total_steps=len(self.workflow_config.get("steps", [])))

        for item in set(self.graph_view.node_items_dict.values()):
            item.has_data = False
            item.available_output_names = []
            item.set_status("pending")

        keep_mem = self.cb_debug.isChecked()
        self._run_generation = getattr(self, "_run_generation", 0) + 1
        generation = self._run_generation
        self.engine_thread = WorkflowEngine(
            self.file_mapping, self.workflow_config, keep_intermediates=keep_mem
        )
        self.engine_thread.log_signal.connect(self.log_print)
        self.engine_thread.progress_signal.connect(self.progress_bar.setValue)
        self.engine_thread.finished_signal.connect(
            lambda success, pool, gen=generation: self.on_engine_finished(success, pool, gen)
        )
        self.engine_thread.finished.connect(
            lambda thread=self.engine_thread: self._forget_discarded_engine(thread)
        )
        self.engine_thread.start()

    def _set_running_ui_state(self, total_steps):
        self.btn_run.setEnabled(True)
        self.btn_run.setText("停止")
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

    def on_engine_finished(self, success, pool, generation=None):
        if generation is not None and generation != getattr(self, "_run_generation", None):
            return
        self._last_engine_result_pool = pool
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
        if not isinstance(data_pool, dict):
            data_pool = {}
        output_key_map = pool.get("output_key_map", {}) if isinstance(pool, dict) else {}
        self.status_detail.setText("已完成")

        self.graph_view.set_all_nodes_status("success")
        self.final_pool = data_pool
        self.output_key_map = output_key_map
        if hasattr(self.graph_view, "update_node_output_names"):
            self.graph_view.update_node_output_names(output_key_map)

        # 节点是否有可预览数据取决于最终 pool；状态成功不代表一定保留中间表。
        for item in set(self.graph_view.node_items_dict.values()):
            if item.status == "success":
                output_names = list(getattr(item, "output_names", []) or [item.table_name])
                item.available_output_names = [
                    name for name in output_names if name in self.final_pool
                ]
                item.has_data = bool(item.available_output_names)
            item.update()

        QMessageBox.information(
            self, "成功", "工作流执行完毕！\n请在下方数据预览区域点击节点查看结果。"
        )

    def _handle_engine_failure(self):
        pool = getattr(self, "_last_engine_result_pool", None)
        if isinstance(pool, dict) and pool.get("cancelled"):
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("已停止")
            self.lbl_status.setText("已停止")
            self.lbl_status.setStyleSheet("color: #F44336; font-weight: bold;")
            self.status_detail.setText("代码块已按 state 停止")
            self.graph_view.set_all_nodes_status("error")
            QMessageBox.information(self, "已停止", "已请求停止，工作流已结束。")
            return
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("失败")
        self.lbl_status.setText("执行中断")
        self.lbl_status.setStyleSheet("color: #F44336; font-weight: bold;")
        self.status_detail.setText("请查看运行日志定位问题")

        self.graph_view.set_all_nodes_status("error")

        QMessageBox.critical(
            self, "执行失败", "工作流执行遇到错误，请查看右侧运行日志定位问题节点。"
        )

    def request_engine_stop(self):
        engine = getattr(self, "engine_thread", None)
        if engine is None or not hasattr(engine, "request_cancel"):
            return
        engine.request_cancel()
        self.btn_run.setEnabled(False)
        self.btn_run.setText("停止中...")
        self.lbl_status.setText("停止中")
        self.status_detail.setText("已请求停止，等待当前代码块自行退出")

    def _retain_discarded_engine(self, engine):
        retained = getattr(self, "_discarded_engine_threads", None)
        if retained is None:
            retained = []
            self._discarded_engine_threads = retained
        if engine not in retained:
            retained.append(engine)

    def _forget_discarded_engine(self, engine):
        try:
            self._discarded_engine_threads.remove(engine)
        except (AttributeError, ValueError):
            pass

    def _discarded_engine_running(self):
        running = []
        for engine in list(getattr(self, "_discarded_engine_threads", []) or []):
            try:
                if engine.isRunning():
                    running.append(engine)
                else:
                    self._forget_discarded_engine(engine)
            except RuntimeError:
                self._forget_discarded_engine(engine)
        return bool(running)

    def _disconnect_engine_signals(self, engine):
        if engine is None:
            return
        for signal_name in ("log_signal", "progress_signal", "finished_signal", "finished"):
            signal = getattr(engine, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect()
            except (TypeError, RuntimeError):
                pass

    def _wait_engine_stopped(self, engine, timeout_ms=3000):
        if engine is None:
            return True
        self._disconnect_engine_signals(engine)
        try:
            if not engine.isRunning():
                engine.deleteLater()
                return True
            engine.wait(timeout_ms)
            stopped = not engine.isRunning()
            if stopped:
                engine.deleteLater()
            return stopped
        except RuntimeError:
            return True

    def shutdown_for_close(self, timeout_ms=3000):
        self._run_generation = getattr(self, "_run_generation", 0) + 1
        engines = []
        if self.engine_thread is not None:
            engines.append(self.engine_thread)
        engines.extend(list(getattr(self, "_discarded_engine_threads", []) or []))
        for engine in engines:
            if not self._wait_engine_stopped(engine, timeout_ms):
                return False
        self.engine_thread = None
        self._discarded_engine_threads = []
        return True
