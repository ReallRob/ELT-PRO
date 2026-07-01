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
        self.workflow_config = {}
        self.runtime_parameters = {}
        self.parameter_mappings = {}
        self.global_code = ""
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

    def register_node_outputs(self, node_id, outputs):
        """Replace all preview outputs for a node without touching its saved params."""
        if node_id:
            for old_key in self.output_key_map.get(node_id, {}).values():
                self.data_pool.pop(old_key, None)
            self.output_key_map[node_id] = {}
            self.dedup_map.pop(node_id, None)

        final_keys = []
        for output in outputs or []:
            key = self.register_data(
                output.get("name"),
                output.get("data"),
                node_id=node_id,
                output_id=output.get("output_id") or "out_1",
            )
            final_keys.append(key)
        return final_keys

    def get_data(self, key):
        return self.data_pool.get(key)

    def get_node_output_value(self, node_id, output_id="out_1"):
        key = self.output_key_map.get(node_id, {}).get(output_id or "out_1")
        if key:
            return self.data_pool.get(key)
        return None

    def clear_context(self):
        """Clear all workflow runtime state and invalidate any in-flight run."""
        self.data_pool.clear()
        self.dedup_map.clear()
        self.output_key_map.clear()
        self.workflow_config = {}
        self.runtime_parameters = {}
        self.parameter_mappings = {}
        self.global_code = ""
        self._run_generation += 1
        self._discard_current_engine()

    def set_runtime_parameters(self, parameters=None, mappings=None):
        self.runtime_parameters = dict(parameters or {})
        self.parameter_mappings = dict(mappings or {})

    def set_global_code(self, global_code=""):
        self.global_code = str(global_code or "")

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
            "runtime_parameters": dict(self.runtime_parameters),
            "parameter_mappings": dict(self.parameter_mappings),
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
        self.engine.finished_signal.connect(
            lambda success, result_pool, gen=generation: self._on_engine_finished(
                success, result_pool, gen
            )
        )
        self.engine.start()

    def run_workflow_sync(self, workflow_config, keep_intermediates=True):
        """Run a small workflow synchronously for design-time single-node execution."""
        engine = WorkflowEngine({}, workflow_config, keep_intermediates=keep_intermediates)
        messages = []
        result_holder = {"success": False, "pool": {}}
        engine.log_signal.connect(messages.append)
        engine.finished_signal.connect(
            lambda success, pool: result_holder.update({"success": success, "pool": pool})
        )
        engine.run()
        result_holder["logs"] = messages
        return result_holder

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

    def _on_engine_finished(self, success, result_pool, generation=None):
        """Receive engine results, ignoring stale runs from a previous workflow."""
        if generation is not None and generation != self._run_generation:
            return

        if success:
            self.data_pool.clear()
            self.dedup_map.clear()
            self.output_key_map.clear()
            if isinstance(result_pool, dict) and "data" in result_pool:
                self.data_pool.update(result_pool["data"])
                self.dedup_map.update(result_pool.get("dedup_map", {}))
                self.output_key_map.update(result_pool.get("output_key_map", {}))
            elif isinstance(result_pool, dict):
                self.data_pool.update(result_pool)
        self.workflow_finished.emit(success, result_pool)
