import json
import copy
from PyQt5.QtCore import QObject, pyqtSignal
from engine import WorkflowEngine


class WorkspaceContext(QObject):
    """
    工作区上下文：负责核心业务逻辑与状态管理，与任何 UI 组件完全解耦
    """

    data_updated = pyqtSignal(str)  # 当某个结果表更新时触发
    workflow_finished = pyqtSignal(bool, dict)  # 全量执行完成信号

    def __init__(self):
        super().__init__()
        # 统一管理所有 DataFrame，UI层的工具面板引用此字典
        self.data_pool = {}
        self.dedup_map = {}  # node_id → 实际存储 key（去重后名称）
        self.workflow_config = {}
        self.runtime_parameters = {}
        self.parameter_mappings = {}
        self.engine = None

    def register_data(self, out_name, df, node_id=None):
        """注册内存表数据。同节点二次运行会回收旧结果"""
        # 回收该节点上次的输出
        if node_id and node_id in self.dedup_map:
            old_key = self.dedup_map.pop(node_id)
            self.data_pool.pop(old_key, None)

        key = out_name
        counter = 1
        while key in self.data_pool:
            counter += 1
            key = f"{out_name} ({counter})"
        self.data_pool[key] = df.copy()
        if node_id:
            self.dedup_map[node_id] = key
        self.data_updated.emit(key)
        return key

    def get_data(self, key):
        """获取内存表"""
        return self.data_pool.get(key)

    def clear_context(self):
        """清空上下文状态"""
        self.data_pool.clear()
        self.dedup_map.clear()
        self.workflow_config = {}

    def set_runtime_parameters(self, parameters=None, mappings=None):
        self.runtime_parameters = copy.deepcopy(parameters or {})
        self.parameter_mappings = copy.deepcopy(mappings or {})

    def build_workflow_logic(self, nodes):
        """将画布节点转换为引擎可执行的 JSON 拓扑配置"""
        if not nodes:
            return None

        # 1. 统计入度与邻接表
        in_degree = {n: 0 for n in nodes}
        adj_list = {n: [] for n in nodes}
        for n in nodes:
            for edge in n.edges_out:
                if edge.dest_node in adj_list:
                    adj_list[n].append(edge.dest_node)
                    in_degree[edge.dest_node] += 1

        # 2. 拓扑排序 (防死循环)
        queue = [n for n in nodes if in_degree[n] == 0]
        sorted_nodes = []
        while queue:
            curr = queue.pop(0)
            sorted_nodes.append(curr)
            for neighbor in adj_list[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_nodes) != len(nodes):
            return None  # 存在环状结构，直接拦截

        # 3. 生成执行配置
        compiled_steps = []
        step_index = 1
        for n in sorted_nodes:
            compiled_params = n.params.copy()

            # 处理上游依赖注入
            if n.action_type != "load_file":
                incoming_nodes = [edge.source_node for edge in n.edges_in]
                if incoming_nodes:
                    if n.action_type in ("left_join", "concat_rows"):
                        # 用列表而非字典，避免同名覆盖
                        src_list = [
                            (edge.source_node.params.get("out_name") or edge.source_node.title,
                             edge.source_node.node_id)
                            for edge in n.edges_in
                        ]
                        df1_name = compiled_params.get("df1_name")
                        df2_name = compiled_params.get("df2_name")
                        match1 = next((nid for name, nid in src_list if name == df1_name), None)
                        match2 = next((nid for name, nid in src_list if name == df2_name), None)
                        compiled_params["df1_id"] = match1 or incoming_nodes[0].node_id
                        compiled_params["df2_id"] = match2 or (
                            incoming_nodes[1].node_id if len(incoming_nodes) > 1
                            else incoming_nodes[0].node_id
                        )
                    elif n.action_type == "insert_block":
                        src_list = [
                            (edge.source_node.params.get("out_name") or edge.source_node.title,
                             edge.source_node.node_id)
                            for edge in n.edges_in
                        ]
                        df_name = compiled_params.get("df_name")
                        tmpl_name = compiled_params.get("template_name")
                        match_df = next((nid for name, nid in src_list if name == df_name), None)
                        match_tmpl = next((nid for name, nid in src_list if name == tmpl_name), None)
                        compiled_params["df_id"] = match_df or (
                            incoming_nodes[0].node_id if incoming_nodes else ""
                        )
                        compiled_params["template_id"] = match_tmpl or (
                            incoming_nodes[1].node_id if len(incoming_nodes) > 1 else ""
                        )
                    else:
                        compiled_params["df_id"] = incoming_nodes[0].node_id

            compiled_params.pop("action", None)

            # 自动补齐临时命名
            assigned_out_name = n.params.get("out_name")
            if not assigned_out_name or str(assigned_out_name).strip() == "":
                assigned_out_name = f"临时表_{step_index}"
                n.params["out_name"] = assigned_out_name

            step = {
                "step_id": step_index,
                "node_id": n.node_id,
                "action": n.action_type,
                "out_name": assigned_out_name,
                "params": compiled_params,
                "x": n.scenePos().x(),
                "y": n.scenePos().y(),
            }
            compiled_steps.append(step)
            step_index += 1

        self.workflow_config = {
            "workflow_name": "UI_Draft",
            "runtime_parameters": copy.deepcopy(self.runtime_parameters),
            "parameter_mappings": copy.deepcopy(self.parameter_mappings),
            "steps": compiled_steps,
        }
        return self.workflow_config

    def run_full_workflow(self):
        """调用引擎进行全量后台跑批"""
        if not self.workflow_config:
            self.workflow_finished.emit(False, {})
            return

        self.engine = WorkflowEngine({}, self.workflow_config, keep_intermediates=True)
        self.engine.finished_signal.connect(self._on_engine_finished)
        self.engine.start()

    def _on_engine_finished(self, success, result_pool):
        """接收引擎结果并同步给所有UI"""
        if success:
            self.data_pool.clear()
            self.dedup_map.clear()
            if isinstance(result_pool, dict) and "data" in result_pool:
                self.data_pool.update(result_pool["data"])
                self.dedup_map.update(result_pool.get("dedup_map", {}))
            else:
                # 兼容旧格式
                self.data_pool.update(result_pool)
        self.workflow_finished.emit(success, result_pool)
