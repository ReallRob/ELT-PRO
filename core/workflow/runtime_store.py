"""Runtime storage for workflow execution.

The store keeps real outputs by explicit ``(node_id, output_id)`` references.
"""

from __future__ import annotations

from core.workflow.operator_model import OperatorContext, OperatorOutput, OperatorResult


class WorkflowRuntimeStore(OperatorContext):
    """Execution data store with explicit output refs."""

    def reset(self):
        self.data_pool.clear()
        self.node_outputs_index.clear()
        self.output_meta.clear()

    def release_node_data(self, node_id: str) -> bool:
        """Release stored data for a node while leaving output metadata intact."""
        released = False
        for output_id in self.node_outputs_index.get(node_id, []):
            released = self.data_pool.pop((node_id, output_id), None) is not None or released
        return released

    def get_data(self, node_id: str, output_id: str = "out_1"):
        key = (node_id, output_id or "out_1")
        if key in self.data_pool:
            return self.data_pool[key]
        raise ValueError(f"找不到运行数据: {node_id}/{output_id or 'out_1'}")

    def get_input_data(self, input_ref):
        output_id = getattr(input_ref, "source_output_id", "out_1") or "out_1"
        return self.get_data(input_ref.source_node_id, output_id)

    def publish_outputs(self, node_id: str, result: OperatorResult):
        self.clear_node_outputs(node_id)
        output_ids = []
        metas = []
        for output in result.outputs:
            output_id = output.output_id or f"out_{len(output_ids) + 1}"
            self.data_pool[(node_id, output_id)] = output.data
            output_ids.append(output_id)
            metas.append(
                OperatorOutput(
                    output_id=output_id,
                    name=output.name,
                    data_type=output.data_type,
                    from_input_id=output.from_input_id,
                    data=None,
                )
            )
        self.node_outputs_index[node_id] = output_ids
        self.output_meta[node_id] = metas

    def iter_all_data(self):
        seen = set()
        for value in self.data_pool.values():
            if id(value) in seen:
                continue
            seen.add(id(value))
            yield value
