import copy

from PyQt5.QtCore import QObject, pyqtSignal

from engine import WorkflowEngine


class WorkspaceContext(QObject):
    """Runtime state shared by design-mode UI and workflow execution."""

    data_updated = pyqtSignal(str)
    workflow_finished = pyqtSignal(bool, dict)

    def __init__(self):
        super().__init__()
        self.data_pool = {}
        self.dedup_map = {}
        self.workflow_config = {}
        self.runtime_parameters = {}
        self.parameter_mappings = {}
        self.engine = None
        self._run_generation = 0
        self._discarded_engines = []

    def register_data(self, out_name, df, node_id=None):
        """Register a preview table and recycle the previous output of the same node."""
        if node_id and node_id in self.dedup_map:
            old_key = self.dedup_map.pop(node_id)
            self.data_pool.pop(old_key, None)

        key = out_name
        counter = 1
        while key in self.data_pool:
            counter += 1
            key = f"{out_name} ({counter})"
        self.data_pool[key] = df
        if node_id:
            self.dedup_map[node_id] = key
        self.data_updated.emit(key)
        return key

    def get_data(self, key):
        return self.data_pool.get(key)

    def clear_context(self):
        """Clear all workflow runtime state and invalidate any in-flight run."""
        self.data_pool.clear()
        self.dedup_map.clear()
        self.workflow_config = {}
        self.runtime_parameters = {}
        self.parameter_mappings = {}
        self._run_generation += 1
        self._discard_current_engine()

    def set_runtime_parameters(self, parameters=None, mappings=None):
        self.runtime_parameters = copy.deepcopy(parameters or {})
        self.parameter_mappings = copy.deepcopy(mappings or {})

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

    def build_workflow_logic(self, nodes):
        """Build executable workflow JSON from canvas nodes."""
        if not nodes:
            return None

        in_degree = {node: 0 for node in nodes}
        adj_list = {node: [] for node in nodes}
        for node in nodes:
            for edge in node.edges_out:
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

        if len(sorted_nodes) != len(nodes):
            return None

        compiled_steps = []
        step_index = 1
        for node in sorted_nodes:
            compiled_params = node.params.copy()

            if node.action_type != "load_file":
                incoming_nodes = [edge.source_node for edge in node.edges_in]
                if incoming_nodes:
                    if node.action_type == "import_template":
                        compiled_params["insert_block_ids"] = [
                            edge.source_node.node_id
                            for edge in node.edges_in
                            if edge.source_node.action_type == "insert_block"
                        ]
                    elif node.action_type in ("left_join", "concat_rows"):
                        if len(incoming_nodes) < 2:
                            raise ValueError(
                                f"{node.action_type} 需要连接两个上游输入表，当前只有 {len(incoming_nodes)} 个"
                            )
                        src_list = [
                            (
                                edge.source_node.params.get("out_name")
                                or edge.source_node.title,
                                edge.source_node.node_id,
                            )
                            for edge in node.edges_in
                        ]
                        df1_name = compiled_params.get("df1_name")
                        df2_name = compiled_params.get("df2_name")
                        match1 = next(
                            (node_id for name, node_id in src_list if name == df1_name),
                            None,
                        )
                        match2 = next(
                            (node_id for name, node_id in src_list if name == df2_name),
                            None,
                        )
                        compiled_params["df1_id"] = match1 or incoming_nodes[0].node_id
                        compiled_params["df2_id"] = match2 or incoming_nodes[1].node_id
                    elif node.action_type == "insert_block":
                        src_list = [
                            (
                                edge.source_node.params.get("out_name")
                                or edge.source_node.title,
                                edge.source_node.node_id,
                            )
                            for edge in node.edges_in
                        ]
                        df_name = compiled_params.get("df_name")
                        tmpl_name = compiled_params.get("template_name")
                        match_df = next(
                            (node_id for name, node_id in src_list if name == df_name),
                            None,
                        )
                        match_tmpl = next(
                            (node_id for name, node_id in src_list if name == tmpl_name),
                            None,
                        )
                        incoming_template = next(
                            (
                                src.node_id
                                for src in incoming_nodes
                                if src.action_type == "import_template"
                            ),
                            None,
                        )
                        compiled_params["df_id"] = match_df or next(
                            (
                                src.node_id
                                for src in incoming_nodes
                                if src.action_type != "import_template"
                            ),
                            incoming_nodes[0].node_id if incoming_nodes else "",
                        )
                        if match_tmpl or incoming_template:
                            compiled_params["template_id"] = match_tmpl or incoming_template
                        else:
                            compiled_params.pop("template_id", None)
                    elif node.action_type == "code_block":
                        saved_bindings = compiled_params.get("input_bindings") or []
                        saved_by_table = {
                            str(item.get("table_name") or ""): item
                            for item in saved_bindings
                            if isinstance(item, dict)
                        }
                        bindings = []
                        for i, src in enumerate(incoming_nodes):
                            table_name = src.params.get("out_name") or src.title
                            saved = saved_by_table.get(str(table_name), {})
                            alias = str(
                                saved.get("alias") or ("df" if i == 0 else f"df{i}")
                            ).strip()
                            bindings.append(
                                {
                                    "df_id": src.node_id,
                                    "table_name": table_name,
                                    "alias": alias,
                                    "primary": i == 0,
                                }
                            )
                        compiled_params["input_bindings"] = bindings
                    else:
                        compiled_params["df_id"] = incoming_nodes[0].node_id

            compiled_params.pop("action", None)

            assigned_out_name = node.params.get("out_name")
            if not assigned_out_name or str(assigned_out_name).strip() == "":
                assigned_out_name = f"临时表_{step_index}"
                node.params["out_name"] = assigned_out_name

            compiled_steps.append(
                {
                    "step_id": step_index,
                    "node_id": node.node_id,
                    "action": node.action_type,
                    "out_name": assigned_out_name,
                    "params": compiled_params,
                    "x": node.scenePos().x(),
                    "y": node.scenePos().y(),
                }
            )
            step_index += 1

        self.workflow_config = {
            "workflow_name": "UI_Draft",
            "runtime_parameters": copy.deepcopy(self.runtime_parameters),
            "parameter_mappings": copy.deepcopy(self.parameter_mappings),
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
        self.engine = WorkflowEngine({}, self.workflow_config, keep_intermediates=True)
        self.engine.finished_signal.connect(
            lambda success, result_pool, gen=generation: self._on_engine_finished(
                success, result_pool, gen
            )
        )
        self.engine.start()

    def _on_engine_finished(self, success, result_pool, generation=None):
        """Receive engine results, ignoring stale runs from a previous workflow."""
        if generation is not None and generation != self._run_generation:
            return

        if success:
            self.data_pool.clear()
            self.dedup_map.clear()
            if isinstance(result_pool, dict) and "data" in result_pool:
                self.data_pool.update(result_pool["data"])
                self.dedup_map.update(result_pool.get("dedup_map", {}))
            else:
                self.data_pool.update(result_pool)
        self.workflow_finished.emit(success, result_pool)
