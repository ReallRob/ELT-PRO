import copy

from PyQt5.QtCore import QObject, pyqtSignal
from engine import WorkflowEngine
from core.workflow.schema import normalize_action_params, normalize_output_refs


class WorkspaceContext(QObject):
    """Runtime state shared by design-mode UI and workflow execution."""

    data_updated = pyqtSignal(str)
    workflow_finished = pyqtSignal(bool, dict)

    def __init__(self):
        super().__init__()
        self.data_pool = {}
        self.dedup_map = {}
        self.output_key_map = {}
        self.raw_data_pool = {}
        self.raw_output_meta = {}
        self.workflow_config = {}
        self.runtime_parameters = {}
        self.parameter_mappings = {}
        self.global_code = ""
        self.function_spaces = []
        self.engine = None
        self._run_generation = 0
        self._discarded_engines = []

    def register_data(self, out_name, value, node_id=None, output_id="out_1"):
        """Register a design-time preview value under a user-facing output name."""
        if node_id:
            old_key = self.output_key_map.get(node_id, {}).pop(output_id, None)
            if old_key:
                self.data_pool.pop(old_key, None)
            if node_id in self.dedup_map and self.dedup_map[node_id] == old_key:
                self.dedup_map.pop(node_id, None)

        base = str(out_name or "结果").strip() or "结果"
        key = base
        counter = 1
        while key in self.data_pool:
            counter += 1
            key = f"{base} ({counter})"
        self.data_pool[key] = value
        if node_id:
            self.output_key_map.setdefault(node_id, {})[output_id or "out_1"] = key
            self.dedup_map.setdefault(node_id, key)
        self.data_updated.emit(key)
        return key

    def get_data(self, key):
        return self.data_pool.get(key)

    def _close_raw_value(self, value):
        if isinstance(value, dict) and value.get("_wb") is not None:
            close = getattr(value.get("_wb"), "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def clear_raw_node_outputs(self, node_id):
        node_id = str(node_id or "")
        if not node_id or not hasattr(self, "raw_data_pool"):
            return
        for key in [key for key in self.raw_data_pool if key[0] == node_id]:
            self._close_raw_value(self.raw_data_pool.pop(key, None))
        self.raw_output_meta.pop(node_id, None)

    def clear_raw_outputs(self):
        for value in list(getattr(self, "raw_data_pool", {}).values()):
            self._close_raw_value(value)
        self.raw_data_pool = {}
        self.raw_output_meta = {}

    def update_raw_outputs(self, raw_data=None, raw_output_meta=None, node_ids=None):
        node_filter = {str(node_id) for node_id in (node_ids or []) if str(node_id or "")}
        if node_filter:
            for node_id in node_filter:
                self.clear_raw_node_outputs(node_id)
        for raw_key, value in (raw_data or {}).items():
            if not isinstance(raw_key, tuple) or len(raw_key) != 2:
                continue
            node_id, output_id = str(raw_key[0] or ""), str(raw_key[1] or "out_1")
            if not node_id or (node_filter and node_id not in node_filter):
                continue
            self.raw_data_pool[(node_id, output_id)] = value
        for node_id, outputs in (raw_output_meta or {}).items():
            node_id = str(node_id or "")
            if not node_id or (node_filter and node_id not in node_filter):
                continue
            self.raw_output_meta[node_id] = list(outputs or [])

    def raw_node_output_refs(self, node_id):
        return list(getattr(self, "raw_output_meta", {}).get(str(node_id or ""), []) or [])

    def has_raw_output(self, node_id, output_id="out_1"):
        return (str(node_id or ""), str(output_id or "out_1")) in getattr(self, "raw_data_pool", {})

    def clear_context(self):
        """Clear all workflow runtime state and invalidate any in-flight run."""
        self.data_pool.clear()
        self.dedup_map.clear()
        self.output_key_map.clear()
        self.clear_raw_outputs()
        self.workflow_config = {}
        self.runtime_parameters = {}
        self.parameter_mappings = {}
        self.global_code = ""
        self.function_spaces = []
        self._run_generation += 1
        self._discard_current_engine()

    def set_runtime_parameters(self, parameters=None, mappings=None):
        self.runtime_parameters = dict(parameters or {})
        self.parameter_mappings = dict(mappings or {})

    def set_global_code(self, global_code=""):
        self.global_code = str(global_code or "")

    def set_function_spaces(self, function_spaces=None):
        self.function_spaces = copy.deepcopy(function_spaces or [])

    def _node_output_refs(self, node):
        return normalize_output_refs(
            node.node_id,
            getattr(node, "params", {}) or {},
            getattr(node, "action_type", ""),
        )

    def incoming_output_refs(self, node):
        refs = []
        for edge in getattr(node, "edges_in", []) or []:
            refs.extend(self._node_output_refs(edge.source_node))
        return refs

    def normalize_node_params(self, node):
        return normalize_action_params(
            node.action_type,
            getattr(node, "params", {}) or {},
            self.incoming_output_refs(node),
            fallback_title=getattr(node, "title", "") or getattr(node, "operator_name", ""),
            include_action=True,
        )

    def _topological_sort(self, nodes):
        in_degree = {node: 0 for node in nodes}
        adj_list = {node: [] for node in nodes}
        for node in nodes:
            for edge in getattr(node, "edges_out", []) or []:
                if edge.dest_node in adj_list:
                    adj_list[node].append(edge.dest_node)
                    in_degree[edge.dest_node] += 1

        queue = [node for node in nodes if in_degree[node] == 0]
        sorted_nodes = []
        while queue:
            curr = queue.pop(0)
            sorted_nodes.append(curr)
            for neighbor in adj_list[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        return sorted_nodes if len(sorted_nodes) == len(nodes) else None

    def _step_for_node(self, step_index, node, params):
        return {
            "step_id": step_index,
            "node_id": node.node_id,
            "design_node_id": node.node_id,
            "design_dependencies": [edge.source_node.node_id for edge in getattr(node, "edges_in", []) or []],
            "action": node.action_type,
            "params": params,
            "x": node.scenePos().x(),
            "y": node.scenePos().y(),
        }

    def build_workflow_logic(self, nodes):
        """Build executable workflow JSON from canvas nodes using explicit IO refs."""
        if not nodes:
            return None

        sorted_nodes = self._topological_sort(nodes)
        if sorted_nodes is None:
            return None

        compiled_steps = []
        for step_index, node in enumerate(sorted_nodes, start=1):
            params = self.normalize_node_params(node)
            node_params = copy.deepcopy(params)
            node.params = node_params
            step_params = dict(node_params)
            step_params.pop("action", None)
            compiled_steps.append(self._step_for_node(step_index, node, step_params))

        self.workflow_config = {
            "workflow_name": "UI_Draft",
            "global_code": self.global_code,
            "function_spaces": copy.deepcopy(self.function_spaces),
            "runtime_parameters": dict(self.runtime_parameters),
            "parameter_mappings": dict(self.parameter_mappings),
            "state": {"run_status": "ready"},
            "steps": compiled_steps,
        }
        return self.workflow_config

    def run_full_workflow(self):
        """Run the current workflow in a background engine."""
        if not self.workflow_config:
            self.workflow_finished.emit(False, {})
            return

        self._discard_current_engine()
        self._run_generation += 1
        generation = self._run_generation
        workflow_snapshot = copy.deepcopy(self.workflow_config)
        self.engine = WorkflowEngine({}, workflow_snapshot, keep_intermediates=True)
        self.engine.return_raw_outputs = True
        self.engine.finished_signal.connect(
            lambda success, result_pool, gen=generation: self._on_engine_finished(
                success, result_pool, gen
            )
        )
        self.engine.start()

    def _discard_current_engine(self):
        engine = self.engine
        self.engine = None
        if engine is None:
            return
        try:
            if engine.isRunning():
                self._discarded_engines.append(engine)
                engine.finished.connect(
                    lambda e=engine: self._forget_discarded_engine(e)
                )
        except RuntimeError:
            pass

    def _forget_discarded_engine(self, engine):
        try:
            self._discarded_engines.remove(engine)
        except ValueError:
            pass

    def discarded_engine_running(self):
        running = []
        for engine in list(self._discarded_engines):
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
        """Stop callbacks and release runtime objects before Qt destroys the UI."""
        self._run_generation += 1
        engines = []
        if self.engine is not None:
            engines.append(self.engine)
        engines.extend(list(getattr(self, "_discarded_engines", []) or []))
        for engine in engines:
            if not self._wait_engine_stopped(engine, timeout_ms):
                return False
        self.engine = None
        self._discarded_engines = []
        self.clear_raw_outputs()
        return True

    def _on_engine_finished(self, success, result_pool, generation=None):
        """Receive engine results, ignoring stale runs from a previous workflow."""
        if generation is not None and generation != self._run_generation:
            return

        if success:
            self.clear_raw_outputs()
            self.data_pool.clear()
            self.dedup_map.clear()
            self.output_key_map.clear()
            if isinstance(result_pool, dict) and "data" in result_pool:
                self.data_pool.update(result_pool["data"])
                self.dedup_map.update(result_pool.get("dedup_map", {}))
                self.output_key_map.update(result_pool.get("output_key_map", {}))
                self.update_raw_outputs(
                    result_pool.get("raw_data", {}),
                    result_pool.get("raw_output_meta", {}),
                )
            elif isinstance(result_pool, dict):
                self.data_pool.update(result_pool)
        self.workflow_finished.emit(success, result_pool)
