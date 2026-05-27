import json
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
        self.workflow_config = {}
        self.engine = None

    def register_data(self, out_name, df):
        """注册或更新内存表数据"""
        self.data_pool[out_name] = df.copy()
        self.data_updated.emit(out_name)
        return out_name

    def get_data(self, out_name):
        """获取内存表"""
        return self.data_pool.get(out_name)

    def clear_context(self):
        """清空上下文状态"""
        self.data_pool.clear()
        self.workflow_config = {}

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
                    if n.action_type == "left_join":
                        src_map = {
                            edge.source_node.params.get("out_name")
                            or edge.source_node.title: edge.source_node.node_id
                            for edge in n.edges_in
                        }
                        df1_name = compiled_params.get("df1_name")
                        df2_name = compiled_params.get("df2_name")
                        compiled_params["df1_id"] = src_map.get(
                            df1_name, incoming_nodes[0].node_id
                        )
                        compiled_params["df2_id"] = src_map.get(
                            df2_name,
                            (
                                incoming_nodes[1].node_id
                                if len(incoming_nodes) > 1
                                else incoming_nodes[0].node_id
                            ),
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

        self.workflow_config = {"workflow_name": "UI_Draft", "steps": compiled_steps}
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
            self.data_pool.update(result_pool)
        self.workflow_finished.emit(success, result_pool)
