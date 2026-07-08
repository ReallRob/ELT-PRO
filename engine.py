import time
import traceback

from PyQt5.QtCore import QThread, pyqtSignal

from core.workflow.operator_model import OperatorInput
from core.workflow.operators import create_operator
from core.workflow.runtime_store import WorkflowRuntimeStore
from parameter_resolver import clone_resolved_runtime_value, normalize_runtime_parameters
from template_engine import close_workbook, clone_workbook, workbook_to_preview_data

PARAMETER_ACTIONS = {"advanced_param_mapping"}
LEGACY_TEMPLATE_PREVIEW_MAX_ROWS = "5000"
LEGACY_TEMPLATE_PREVIEW_MAX_COLS = "200"


class WorkflowEngine(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, object)

    def __init__(
        self,
        file_mapping,
        workflow_config,
        keep_intermediates=False,
        profile_mode=None,
        template_preview_max_sheets=None,
        initial_runtime_data=None,
        return_raw_outputs=False,
    ):
        super().__init__()
        self.file_mapping = file_mapping or {}
        self.workflow_config = workflow_config or {}
        self.runtime_store = WorkflowRuntimeStore(log_callback=self.log)
        self.keep_intermediates = keep_intermediates
        if profile_mode is None:
            profile_mode = bool(
                self.workflow_config.get("profile_mode")
                or self.workflow_config.get("profile")
        )
        self.profile_mode = bool(profile_mode)
        self.initial_runtime_data = dict(initial_runtime_data or {})
        self.return_raw_outputs = bool(return_raw_outputs)
        self._seeded_runtime_value_ids = set()
        self._dedup_map = {}
        self._output_key_map = {}
        self._output_meta = {}
        self.runtime_parameters = {}
        self.parameter_mappings = {}
        self.runtime_state = {}
        self.global_code = ""
        self.function_spaces = []

    def log(self, msg):
        self.log_signal.emit(msg)

    def get_output(self, node_id, output_id="out_1"):
        return self.runtime_store.get_data(node_id, output_id or "out_1")

    def _format_ms(self, seconds):
        return f"{seconds * 1000:.1f}ms"

    def _dataframe_memory_mb(self, value):
        memory_usage = getattr(value, "memory_usage", None)
        if not callable(memory_usage):
            return None
        try:
            return float(memory_usage(deep=True).sum()) / (1024 * 1024)
        except Exception:
            return None

    def _value_profile_text(self, value):
        if hasattr(value, "shape"):
            rows, cols = value.shape
            memory_mb = self._dataframe_memory_mb(value)
            if memory_mb is None:
                return f"table {rows}x{cols}"
            return f"table {rows}x{cols}, {memory_mb:.2f}MB"
        if isinstance(value, dict) and value.get("_wb") is not None:
            meta = value.get("_meta") or {}
            sheet_count = len(meta.get("sheet_names") or meta.get("sheets") or [])
            return f"workbook {sheet_count} sheet(s)"
        if isinstance(value, dict) and value.get("_template_preview"):
            sheets = value.get("sheets") or {}
            total_sheets = value.get("sheet_count") or len(sheets)
            return f"template_preview {len(sheets)}/{total_sheets} sheet(s)"
        return type(value).__name__

    def _runtime_output_summary(self, node_id):
        parts = []
        for output in self.runtime_store.outputs_for_node(node_id):
            try:
                value = self.runtime_store.get_data(node_id, output.output_id)
                parts.append(f"{output.output_id}:{self._value_profile_text(value)}")
            except Exception:
                parts.append(f"{output.output_id}:unavailable")
        return "; ".join(parts) if parts else "none"

    def _log_step_profile(self, action, node_id, timings, published_count, released_count):
        total = sum(timings.values())
        outputs = self._runtime_output_summary(node_id)
        if self.profile_mode:
            details = ", ".join(
                f"{name}={self._format_ms(seconds)}"
                for name, seconds in timings.items()
            )
            self.log(
                f"    - [profile] {action}: total={self._format_ms(total)}; "
                f"{details}; outputs={outputs}; "
                f"published={published_count}; released={released_count}"
            )
            return
        self.log(
            f"    - [perf] elapsed={self._format_ms(total)}, "
            f"run={self._format_ms(timings.get('run', 0))}, "
            f"publish={self._format_ms(timings.get('publish', 0))}; "
            f"outputs={outputs}"
        )

    def _collect_runtime_metadata(self, steps):
        parameters = normalize_runtime_parameters(
            self.workflow_config.get("runtime_parameters", {})
        )
        mappings = dict(self.workflow_config.get("parameter_mappings", {}) or {})

        for step in steps:
            if step.get("action") != "advanced_param_mapping":
                continue
            params = step.get("params", {})
            typed_params = params.get("typed_parameters")
            if isinstance(typed_params, dict):
                parameters.update(typed_params)
            else:
                parameters.update(normalize_runtime_parameters(params.get("parameters", {})))
            mappings.update(params.get("parameter_mappings", {}) or {})
        return parameters, mappings

    def _build_ref_count(self, steps):
        ref_count = {}
        for step in steps:
            for item in (step.get("params", {}) or {}).get("inputs", []) or []:
                if not isinstance(item, dict) or not item.get("enabled", True):
                    continue
                source_node_id = str(item.get("source_node_id") or "")
                source_output_id = str(item.get("source_output_id") or "out_1")
                if source_node_id:
                    key = (source_node_id, source_output_id)
                    ref_count[key] = ref_count.get(key, 0) + 1
        return ref_count

    def _inputs_from_params(self, params):
        inputs = []
        for index, item in enumerate(params.get("inputs") or [], start=1):
            if not isinstance(item, dict) or not item.get("enabled", True):
                continue
            inputs.append(
                OperatorInput(
                    input_id=str(item.get("input_id") or f"in_{index}"),
                    source_node_id=str(item.get("source_node_id") or ""),
                    source_output_id=str(item.get("source_output_id") or "out_1"),
                    name=str(item.get("name") or ""),
                    role=str(item.get("role") or "current"),
                    data_type=str(item.get("data_type") or "table"),
                )
            )
        return inputs

    def _apply_file_mapping(self, action, params):
        mapped = dict(params or {})
        if action == "load_file":
            original = mapped.get("file_path")
            mapped["file_path"] = self.file_mapping.get(original, original)
        elif action == "import_template":
            original = mapped.get("template_path")
            mapped["template_path"] = self.file_mapping.get(original, original)
        elif action == "save_template":
            original = mapped.get("output_path")
            mapped["output_path"] = self.file_mapping.get(original, original)
        return mapped

    def _prepare_params(self, step, runtime_parameters, parameter_mappings):
        action = step.get("action")
        raw_params = step.get("params", {}) or {}
        params = clone_resolved_runtime_value(
            raw_params,
            runtime_parameters,
            parameter_mappings,
            strict=True,
        )
        params = self._apply_file_mapping(action, params)
        params["runtime_parameters"] = runtime_parameters
        params["parameter_mappings"] = parameter_mappings
        params["state"] = self.runtime_state
        params["global_code"] = self.global_code
        params["function_spaces"] = self.function_spaces
        return params

    def _preview_limit_from_params(self, params, key, legacy_default=None):
        raw = (params or {}).get(key)
        text = str(raw or "").strip()
        if not text or (legacy_default is not None and text == str(legacy_default)):
            return None
        try:
            value = int(text)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _to_display_value(self, value, params=None):
        if not (isinstance(value, dict) and value.get("_wb") is not None):
            return value
        params = params or {}
        saved_path = value.get("_saved_path", "")
        preview_kwargs = {
            "start_row": params.get("preview_start_row") or 1,
            "start_col": params.get("preview_start_col") or 1,
        }
        max_rows = self._preview_limit_from_params(
            params, "preview_max_rows", LEGACY_TEMPLATE_PREVIEW_MAX_ROWS
        )
        max_cols = self._preview_limit_from_params(
            params, "preview_max_cols", LEGACY_TEMPLATE_PREVIEW_MAX_COLS
        )
        if max_rows is not None:
            preview_kwargs["max_rows"] = max_rows
        if max_cols is not None:
            preview_kwargs["max_cols"] = max_cols
        return workbook_to_preview_data(
            value.get("_wb"),
            saved_path,
            max_sheets=None,
            **preview_kwargs,
        )

    def _runtime_value_identity(self, value):
        if isinstance(value, dict) and value.get("_wb") is not None:
            return id(value.get("_wb"))
        return id(value)

    def _clone_seed_value(self, value):
        if isinstance(value, dict) and value.get("_wb") is not None:
            cloned = dict(value)
            cloned["_wb"] = clone_workbook(value.get("_wb"))
            return cloned
        return value

    def _seed_runtime_store(self):
        for raw_key, value in self.initial_runtime_data.items():
            if not isinstance(raw_key, tuple) or len(raw_key) != 2:
                continue
            node_id, output_id = raw_key
            key = (str(node_id or ""), str(output_id or "out_1"))
            if not key[0]:
                continue
            seeded_value = self._clone_seed_value(value)
            self.runtime_store.data_pool[key] = seeded_value
            self._seeded_runtime_value_ids.add(self._runtime_value_identity(seeded_value))
        if self.initial_runtime_data:
            self.log(f"    - [cache] 复用上游缓存 {len(self.initial_runtime_data)} 个输出")

    def _close_workbooks(self):
        self._close_workbooks_for_result(keep_returned_raw=False)

    def _close_workbooks_for_result(self, keep_returned_raw=False):
        if keep_returned_raw:
            return
        for value in list(self.runtime_store.iter_all_data()):
            if self._runtime_value_identity(value) in self._seeded_runtime_value_ids:
                continue
            if isinstance(value, dict):
                close_workbook(value.get("_wb"))

    def _unique_key(self, base_name, display_pool, dedup_counters):
        base = str(base_name or "结果").strip() or "结果"
        key = base
        if key in display_pool:
            counter = dedup_counters.get(base, 1) + 1
            dedup_counters[base] = counter
            key = f"{base} ({counter})"
        return key

    def _should_publish_output(self, action, output):
        if action in PARAMETER_ACTIONS:
            return False
        return True

    def _publish_outputs_if_needed(self, action, node_id, display_pool, dedup_counters, ref_count, params=None):
        published_count = 0
        for output in self.runtime_store.outputs_for_node(node_id):
            if ref_count.get((node_id, output.output_id), 0) != 0 and not self.keep_intermediates:
                continue
            if not self._should_publish_output(action, output):
                continue
            key = self._unique_key(output.name, display_pool, dedup_counters)
            value = self._to_display_value(
                self.runtime_store.get_data(node_id, output.output_id),
                params,
            )
            display_pool[key] = value
            self._dedup_map.setdefault(node_id, key)
            self._output_key_map.setdefault(node_id, {})[output.output_id] = key
            published_count += 1
        return published_count

    def _log_outputs(self, node_id):
        outputs = self.runtime_store.outputs_for_node(node_id)
        if not outputs:
            return
        for output in outputs:
            self.log(f"    - 输出 {output.output_id}: {output.name}")
            try:
                value = self.runtime_store.get_data(node_id, output.output_id)
                if hasattr(value, "shape"):
                    rows, cols = value.shape
                    memory_mb = self._dataframe_memory_mb(value)
                    if memory_mb is None:
                        self.log(f"      数据规模: {rows} 行 x {cols} 列")
                    else:
                        self.log(f"      数据规模: {rows} 行 x {cols} 列, 约 {memory_mb:.2f} MB")
                elif isinstance(value, dict) and value.get("_wb") is not None:
                    self.log(f"      数据规模: {self._value_profile_text(value)}")
            except Exception:
                pass

    def _release_consumed_dependencies(self, params, ref_count):
        released_count = 0
        for item in params.get("inputs", []) or []:
            if not isinstance(item, dict) or not item.get("enabled", True):
                continue
            dep = str(item.get("source_node_id") or "")
            output_id = str(item.get("source_output_id") or "out_1")
            key = (dep, output_id)
            if key not in ref_count:
                continue
            ref_count[key] -= 1
            if not self.keep_intermediates and ref_count[key] <= 0:
                released = self.runtime_store.data_pool.pop(key, None) is not None
                if released:
                    released_count += 1
                    self.log(f"    - [内存优化] 中间输出已释放: {dep}/{output_id}")
        return released_count

    def _handle_parameter_action(self, action, params):
        if action != "advanced_param_mapping":
            return False
        config = params.get("rule_engine_config", {})
        param_count = len(config.get("parameters", []))
        rule_count = len(config.get("rules", []))
        self.log(f"    - 已加载参数输入: {param_count} 个参数, {rule_count} 条规则")
        return True

    def run(self):
        started_at = time.perf_counter()
        try:
            steps = self.workflow_config.get("steps", [])
            total_steps = len(steps)
            workflow_name = self.workflow_config.get("workflow_name", "未命名")
            runtime_parameters, parameter_mappings = self._collect_runtime_metadata(steps)
            self.runtime_parameters = runtime_parameters
            self.parameter_mappings = parameter_mappings
            self.runtime_state = dict(self.workflow_config.get("state") or {})
            self.global_code = str(self.workflow_config.get("global_code") or "")
            self.function_spaces = list(self.workflow_config.get("function_spaces") or [])

            self.runtime_store.reset()
            self._seed_runtime_store()
            display_pool = {}
            dedup_counters = {}
            self._dedup_map = {}
            self._output_key_map = {}
            self._output_meta = {}
            ref_count = self._build_ref_count(steps)

            self.log(f"开始执行工作流: {workflow_name} (共 {total_steps} 步)")
            self.log(
                f"    - [perf] keep_intermediates={self.keep_intermediates}, "
                f"profile_mode={self.profile_mode}"
            )

            self.progress_signal.emit(0, total_steps)
            for i, step in enumerate(steps):
                step_id = step.get("step_id", i + 1)
                node_id = step.get("node_id")
                action = step.get("action")

                prepare_started = time.perf_counter()
                params = self._prepare_params(step, runtime_parameters, parameter_mappings)
                prepare_elapsed = time.perf_counter() - prepare_started

                self.log(f"\n  [步骤 {step_id}/{total_steps}] 节点: {action}")

                try:
                    if self._handle_parameter_action(action, params):
                        self._log_step_profile(
                            action,
                            node_id,
                            {"prepare": prepare_elapsed, "run": 0.0, "publish": 0.0, "release": 0.0},
                            0,
                            0,
                        )
                        self.progress_signal.emit(i + 1, total_steps)
                        continue

                    run_started = time.perf_counter()
                    operator = create_operator(action)
                    inputs = self._inputs_from_params(params)
                    result = self.runtime_store.run_operator(node_id, operator, inputs, params)
                    run_elapsed = time.perf_counter() - run_started

                    log_started = time.perf_counter()
                    self._output_meta[node_id] = [
                        {
                            "output_id": output.output_id,
                            "name": output.name,
                            "data_type": output.data_type,
                        }
                        for output in self.runtime_store.outputs_for_node(node_id)
                    ]
                    for message in result.logs:
                        self.log(f"    - {message}")
                    self._log_outputs(node_id)
                    log_elapsed = time.perf_counter() - log_started

                    publish_started = time.perf_counter()
                    published_count = self._publish_outputs_if_needed(
                        action, node_id, display_pool, dedup_counters, ref_count, params
                    )
                    publish_elapsed = time.perf_counter() - publish_started

                    release_started = time.perf_counter()
                    released_count = self._release_consumed_dependencies(params, ref_count)
                    release_elapsed = time.perf_counter() - release_started

                    self._log_step_profile(
                        action,
                        node_id,
                        {
                            "prepare": prepare_elapsed,
                            "run": run_elapsed,
                            "log": log_elapsed,
                            "publish": publish_elapsed,
                            "release": release_elapsed,
                        },
                        published_count,
                        released_count,
                    )
                    self.progress_signal.emit(i + 1, total_steps)

                except Exception as step_e:
                    err_msg = traceback.format_exc()
                    self.log(
                        f"\n    X [步骤 {step_id}] 节点执行失败:\n原因: {step_e}\n{err_msg}"
                    )
                    self._close_workbooks()
                    self.finished_signal.emit(False, {})
                    return

            total_elapsed = time.perf_counter() - started_at
            self.log(f"\n成功，所有节点执行完毕。总耗时: {self._format_ms(total_elapsed)}")
            self.log(f"    - [perf] final display_pool outputs={len(display_pool)}")
            result_payload = {
                "data": display_pool,
                "dedup_map": self._dedup_map,
                "output_key_map": self._output_key_map,
                "output_meta": self._output_meta,
                "state": self.runtime_state,
            }
            if self.return_raw_outputs:
                result_payload["raw_data"] = dict(self.runtime_store.data_pool)
                result_payload["raw_output_meta"] = {
                    node_id: [
                        {
                            "output_id": output.output_id,
                            "name": output.name,
                            "data_type": output.data_type,
                        }
                        for output in outputs
                    ]
                    for node_id, outputs in self.runtime_store.output_meta.items()
                }
            self._close_workbooks_for_result(keep_returned_raw=self.return_raw_outputs)
            self.finished_signal.emit(True, result_payload)

        except Exception:
            err_msg = traceback.format_exc()
            self.log(f"\nX 致命错误: 引擎解析崩溃\n{err_msg}")
            self._close_workbooks()
            self.finished_signal.emit(False, {})
