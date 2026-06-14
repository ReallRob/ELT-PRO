import traceback

from PyQt5.QtCore import QThread, pyqtSignal

from core.workflow.action_handlers import (
    collect_action_dependencies,
    get_exec_dir,
    handle_parameter_action,
    run_action,
    should_log_dataframe_shape,
    should_publish_output,
)
from parameter_resolver import (
    clone_resolved_runtime_value,
    normalize_runtime_parameters,
)


class WorkflowEngine(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, object)

    def __init__(self, file_mapping, workflow_config, keep_intermediates=False):
        super().__init__()
        self.file_mapping = file_mapping
        self.workflow_config = workflow_config
        self.data_pool = {}
        self.keep_intermediates = keep_intermediates

    def log(self, msg):
        self.log_signal.emit(msg)

    def get_df(self, df_id):
        df = self.data_pool.get(df_id)
        if df is None:
            raise ValueError(f"无法在内存中找到上游输入表，请检查连线！(ID: {df_id})")
        return df

    def _get_df(self, df_id):
        """Compatibility alias for older helper code that still calls _get_df."""
        return self.get_df(df_id)

    def _collect_runtime_metadata(self, steps):
        parameters = {}
        mappings = {}

        for step in steps:
            action = step.get("action")
            params = step.get("params", {})
            if action == "input_param":
                parameters.update(
                    normalize_runtime_parameters(params.get("parameters", {}))
                )
            elif action == "param_mapping":
                mapping_name = str(params.get("mapping_name", "")).strip()
                if mapping_name:
                    mappings[mapping_name] = params.get("rules", [])
            elif action == "advanced_param_mapping":
                typed_params = params.get("typed_parameters")
                if isinstance(typed_params, dict):
                    parameters.update(typed_params)
                else:
                    parameters.update(
                        normalize_runtime_parameters(params.get("parameters", {}))
                    )
                mappings.update(params.get("parameter_mappings", {}) or {})

        # 工作流根级参数覆盖节点内参数，兼容旧 JSON 的同时让最新配置优先。
        parameters.update(
            normalize_runtime_parameters(
                self.workflow_config.get("runtime_parameters", {})
            )
        )
        mappings.update(self.workflow_config.get("parameter_mappings", {}) or {})
        return parameters, mappings

    def _build_ref_count(self, steps):
        ref_count = {}
        for step in steps:
            action = step.get("action")
            params = step.get("params", {})
            for dep in collect_action_dependencies(action, params):
                if dep:
                    ref_count[dep] = ref_count.get(dep, 0) + 1
        return ref_count

    def _log_action_output_shape(self, action, node_id):
        if not should_log_dataframe_shape(action):
            return
        df = self.data_pool[node_id]
        self.log(f"    - 完成. 数据规模: {df.shape[0]} 行, {df.shape[1]} 列")

    def _publish_output_if_needed(self, action, node_id, out_name, display_pool, dedup_counters, ref_count):
        if not should_publish_output(action):
            return
        if ref_count.get(node_id, 0) != 0 and not self.keep_intermediates:
            return

        key = out_name
        if key in display_pool:
            counter = dedup_counters.get(out_name, 1) + 1
            dedup_counters[out_name] = counter
            key = f"{out_name} ({counter})"

        display_pool[key] = self.data_pool[node_id]
        self._dedup_map[node_id] = key

    def _release_consumed_dependencies(self, action, params, ref_count):
        for dep in collect_action_dependencies(action, params):
            if not dep or dep not in ref_count:
                continue
            ref_count[dep] -= 1
            if (
                not self.keep_intermediates
                and ref_count[dep] <= 0
                and dep in self.data_pool
            ):
                del self.data_pool[dep]
                self.log(f"    - [内存优化] 中间表已释放 (ID: {dep})")

    def run(self):
        try:
            steps = self.workflow_config.get("steps", [])
            total_steps = len(steps)
            workflow_name = self.workflow_config.get("workflow_name", "未命名")
            runtime_parameters, parameter_mappings = self._collect_runtime_metadata(steps)

            self.data_pool = {}
            display_pool = {}
            dedup_counters = {}
            self._dedup_map = {}
            ref_count = self._build_ref_count(steps)

            self.log(f"开始执行工作流: {workflow_name} (共 {total_steps} 步)")

            for i, step in enumerate(steps):
                self.progress_signal.emit(i + 1, total_steps)
                step_id = step.get("step_id", i + 1)
                node_id = step.get("node_id")
                action = step.get("action")
                out_name = clone_resolved_runtime_value(
                    step.get("out_name", f"Result_{step_id}"),
                    runtime_parameters,
                    parameter_mappings,
                    strict=True,
                )
                params = clone_resolved_runtime_value(
                    step.get("params", {}),
                    runtime_parameters,
                    parameter_mappings,
                    strict=True,
                )

                self.log(
                    f"\n  [步骤 {step_id}/{total_steps}] 节点: {action} -> 输出表: {out_name}"
                )

                try:
                    if handle_parameter_action(self, action, params):
                        continue

                    run_action(self, action, params, node_id)
                    self._log_action_output_shape(action, node_id)
                    self._publish_output_if_needed(
                        action, node_id, out_name, display_pool, dedup_counters, ref_count
                    )
                    self._release_consumed_dependencies(action, params, ref_count)

                except Exception as step_e:
                    err_msg = traceback.format_exc()
                    self.log(
                        f"\n    × [步骤 {step_id}] 节点执行失败！\n原因: {str(step_e)}\n{err_msg}"
                    )
                    self.finished_signal.emit(False, {})
                    return

            self.log("\n成功！所有节点执行完毕。")
            self.finished_signal.emit(
                True,
                {
                    "data": display_pool,
                    "dedup_map": self._dedup_map,
                },
            )

        except Exception:
            err_msg = traceback.format_exc()
            self.log(f"\n× 致命错误: 引擎解析崩溃\n{err_msg}")
            self.finished_signal.emit(False, {})
