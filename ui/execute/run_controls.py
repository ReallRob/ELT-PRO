"""Workflow engine run controls for execute mode."""

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMessageBox

from engine import WorkflowEngine
from core.workflow.timeouts import workflow_code_timeout_ms
from ui.execute.styles import RUN_BUTTON_ACTIVE_STYLE, RUN_BUTTON_BUSY_STYLE


class ExecuteRunControlsMixin:
    def run_engine(self):
        if not self.workflow_config:
            return
        if self._discarded_engine_running():
            QMessageBox.information(self, "运行中", "仍有已废弃的后台任务在收尾，请等待结束后再运行。")
            return

        self.log_output.clear()
        self._set_running_ui_state(total_steps=len(self.workflow_config.get("steps", [])))

        for item in self.graph_view.node_items_dict.values():
            item.has_data = False
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
        self._start_engine_timeout_timer(self.workflow_config, generation)
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

    def on_engine_finished(self, success, pool, generation=None):
        if generation is not None and generation != getattr(self, "_run_generation", None):
            return
        self._stop_engine_timeout_timer()
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

    def _start_engine_timeout_timer(self, workflow_config, generation):
        self._stop_engine_timeout_timer()
        timeout_ms = workflow_code_timeout_ms(workflow_config)
        if not timeout_ms:
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda gen=generation: self._on_engine_timeout(gen))
        self._engine_timeout_timer = timer
        timer.start(timeout_ms)

    def _stop_engine_timeout_timer(self):
        timer = getattr(self, "_engine_timeout_timer", None)
        self._engine_timeout_timer = None
        if timer is None:
            return
        timer.stop()
        timer.deleteLater()

    def _on_engine_timeout(self, generation):
        if generation != getattr(self, "_run_generation", None):
            return
        self._stop_engine_timeout_timer()
        engine = getattr(self, "engine_thread", None)
        if engine is not None:
            self._retain_discarded_engine(engine)
        self.engine_thread = None
        self._run_generation = getattr(self, "_run_generation", 0) + 1
        self._restore_idle_ui_state()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("超时")
        self.lbl_status.setText("执行超时")
        self.lbl_status.setStyleSheet("color: #F44336; font-weight: bold;")
        self.status_detail.setText("结果已废弃，后台线程可能仍在收尾")
        self.graph_view.set_all_nodes_status("error")
        self.log_print("[超时] 工作流超过代码块超时时间，结果将被忽略。")
        QMessageBox.warning(self, "执行超时", "工作流超过代码块超时时间，结果将被忽略；后台线程可能仍在收尾。")

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
        self._stop_engine_timeout_timer()
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
