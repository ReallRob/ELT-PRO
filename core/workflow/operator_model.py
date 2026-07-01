"""Operator class model for multi-input and multi-output workflow nodes.

这个模块只描述“算子应该如何表达输入、输出、运行结果和运行上下文”。
它先独立于现有 JSON/UI/旧执行器，便于逐步迁移。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable


@dataclass
class OperatorInput:
    """一个算子当前接收到的一个输入。

    input_id: 当前算子内部的输入编号，例如 in_1。
    source_node_id: 这个输入来自哪个上游节点。
    source_output_id: 这个输入来自上游节点的哪个输出。
    name: 给用户看的输入名称，例如“网点表”。
    role: 当前输入在本算子里的角色，例如 current/left/right/template。
    data_type: 输入对象类型，例如 table/workbook。
    """

    input_id: str
    source_node_id: str
    source_output_id: str
    name: str
    role: str = "current"
    data_type: str = "table"


@dataclass
class OperatorOutput:
    """一个算子产生的一个输出。

    output_id: 当前算子内部的输出编号，例如 out_1。
    name: 给用户看的输出名称，例如“网点表_筛选”。
    data_type: 输出对象类型，例如 table/workbook。
    from_input_id: 如果这个输出由某个输入一一产生，则记录来源 input_id。
    data: 运行后真实数据；未运行或只做推导时为 None。
    """

    output_id: str
    name: str
    data_type: str = "table"
    from_input_id: str | None = None
    data: Any = None


@dataclass
class OperatorResult:
    """一次算子运行后的结果集合。"""

    outputs: list[OperatorOutput] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


class OperatorContext:
    """运行时数据仓库。

    data_pool 使用 (node_id, output_id) 作为 key，使一个节点可以安全保存多个输出。
    node_outputs_index 记录每个节点上一次发布了哪些 output_id，便于二次运行前清旧输出。
    output_meta 保存不含真实 data 的输出元信息，供下游推导 inputs 使用。
    """

    def __init__(self):
        self.data_pool: dict[tuple[str, str], Any] = {}
        self.node_outputs_index: dict[str, list[str]] = {}
        self.output_meta: dict[str, list[OperatorOutput]] = {}

    def clear_node_outputs(self, node_id: str):
        """清除某个节点上一次运行产生的所有输出数据，但不碰节点配置。"""
        for output_id in self.node_outputs_index.get(node_id, []):
            self.data_pool.pop((node_id, output_id), None)
        self.node_outputs_index[node_id] = []
        self.output_meta[node_id] = []

    def clear_downstream_outputs(self, node_id: str, downstream_map: dict[str, list[str]] | None = None):
        """清除下游节点旧输出；只清运行结果，不清任何 params/规则配置。"""
        if not downstream_map:
            return
        seen = set()
        stack = list(downstream_map.get(node_id, []))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            self.clear_node_outputs(current)
            stack.extend(downstream_map.get(current, []))

    def get_input_data(self, input_ref: OperatorInput):
        """按输入引用读取真实数据。"""
        key = (input_ref.source_node_id, input_ref.source_output_id)
        if key not in self.data_pool:
            raise ValueError(
                f"找不到输入数据: {input_ref.name} "
                f"({input_ref.source_node_id}/{input_ref.source_output_id})"
            )
        return self.data_pool[key]

    def publish_outputs(self, node_id: str, result: OperatorResult):
        """注册本次运行的新输出。调用前会先替换该节点旧输出。"""
        self.clear_node_outputs(node_id)
        output_ids = []
        metas = []
        for output in result.outputs:
            self.data_pool[(node_id, output.output_id)] = output.data
            output_ids.append(output.output_id)
            metas.append(replace(output, data=None))
        self.node_outputs_index[node_id] = output_ids
        self.output_meta[node_id] = metas

    def run_operator(
        self,
        node_id: str,
        operator: "BaseOperator",
        inputs: list[OperatorInput],
        params: dict[str, Any],
        downstream_map: dict[str, list[str]] | None = None,
    ) -> OperatorResult:
        """执行一个节点：清旧输出 -> 清下游旧输出 -> 运行 -> 发布新输出。"""
        self.clear_node_outputs(node_id)
        self.clear_downstream_outputs(node_id, downstream_map)
        operator.validate(inputs, params)
        result = operator.run(inputs, params, self)
        self.publish_outputs(node_id, result)
        return result

    def outputs_for_node(self, node_id: str) -> list[OperatorOutput]:
        """返回某个节点的输出元信息，不包含真实 data。"""
        return list(self.output_meta.get(node_id, []))

    def inputs_from_outputs(
        self,
        source_node_id: str,
        outputs: Iterable[OperatorOutput],
        role: str = "current",
    ) -> list[OperatorInput]:
        """把同一个上游节点的 outputs 列表转换成下游 inputs 列表。"""
        return self.inputs_from_connected_outputs(
            [(source_node_id, output) for output in outputs], role=role
        )

    def inputs_from_connected_outputs(
        self,
        incoming_outputs: Iterable[tuple[str, OperatorOutput]],
        role: str = "current",
    ) -> list[OperatorInput]:
        """把多条上游连线的输出统一编号成当前算子的 inputs。"""
        inputs = []
        for index, (source_node_id, output) in enumerate(incoming_outputs, start=1):
            inputs.append(
                OperatorInput(
                    input_id=f"in_{index}",
                    source_node_id=source_node_id,
                    source_output_id=output.output_id,
                    name=output.name,
                    role=role,
                    data_type=output.data_type,
                )
            )
        return inputs


class BaseOperator:
    """所有算子的基类。"""

    action = ""
    title = ""
    category = ""
    input_data_type = "table"
    output_data_type = "table"
    allowed_input_types: tuple[str, ...] | None = None
    output_suffix = "结果"

    def saved_output(self, params: dict[str, Any], index: int = 1):
        outputs = [item for item in params.get("outputs") or [] if isinstance(item, dict)]
        if index - 1 < len(outputs):
            return outputs[index - 1]
        return {}

    def single_output(
        self,
        params: dict[str, Any],
        data: Any = None,
        default_name: str = "",
        data_type: str | None = None,
        from_input_id: str | None = None,
    ) -> OperatorOutput:
        saved = self.saved_output(params, 1)
        return OperatorOutput(
            output_id=str(saved.get("output_id") or "out_1"),
            name=str(saved.get("name") or default_name or self.title or self.action),
            data_type=str(saved.get("data_type") or data_type or self.output_data_type),
            from_input_id=from_input_id,
            data=data,
        )

    def infer_inputs(self, incoming_outputs: list[tuple[str, OperatorOutput]], params: dict[str, Any]):
        inputs = []
        for index, (source_node_id, output) in enumerate(incoming_outputs, start=1):
            inputs.append(
                OperatorInput(
                    input_id=f"in_{index}",
                    source_node_id=source_node_id,
                    source_output_id=output.output_id,
                    name=output.name,
                    role="current",
                    data_type=output.data_type,
                )
            )
        return inputs

    def infer_outputs(self, inputs: list[OperatorInput], params: dict[str, Any]):
        return [self.single_output(params)]

    def _allowed_input_types(self) -> tuple[str, ...]:
        """返回当前算子允许接收的数据类型。"""
        if self.allowed_input_types is not None:
            return self.allowed_input_types
        return (self.input_data_type,)

    def validate(self, inputs: list[OperatorInput], params: dict[str, Any]):
        if not inputs:
            raise ValueError(f"{self.title or self.action} 至少需要一个输入")
        allowed = self._allowed_input_types()
        for input_item in inputs:
            if input_item.data_type not in allowed:
                allowed_text = "/".join(allowed)
                raise ValueError(
                    f"{self.title or self.action} 需要 {allowed_text} 输入，"
                    f"但收到 {input_item.data_type}: {input_item.name}"
                )

    def run(self, inputs: list[OperatorInput], params: dict[str, Any], context: OperatorContext):
        raise NotImplementedError


class BatchMapOperator(BaseOperator):
    """批量映射算子：多输入、多输出，输入和输出一一对应。"""

    output_suffix = "结果"

    def saved_output_for_input(self, input_item: OperatorInput, params: dict[str, Any], index: int):
        for item in params.get("outputs") or []:
            if not isinstance(item, dict):
                continue
            matches_input = item.get("from_input_id") == input_item.input_id
            matches_source = (
                item.get("source_node_id") == input_item.source_node_id
                and item.get("source_output_id") == input_item.source_output_id
            )
            if matches_input or matches_source:
                return item
        return {"output_id": f"out_{index}", "name": f"{input_item.name}_{self.output_suffix}"}

    def make_output_name(self, input_item: OperatorInput, params: dict[str, Any], index: int):
        saved_output = self.saved_output_for_input(input_item, params, index)
        out_name = str(saved_output.get("name") or "").strip()
        if out_name:
            return out_name
        return f"{input_item.name}_{self.output_suffix}"

    def infer_outputs(self, inputs: list[OperatorInput], params: dict[str, Any]):
        outputs = []
        for index, input_item in enumerate(inputs, start=1):
            saved_output = self.saved_output_for_input(input_item, params, index)
            outputs.append(
                OperatorOutput(
                    output_id=str(saved_output.get("output_id") or f"out_{index}"),
                    name=self.make_output_name(input_item, params, index),
                    data_type=self.output_data_type,
                    from_input_id=input_item.input_id,
                )
            )
        return outputs

    def run(self, inputs: list[OperatorInput], params: dict[str, Any], context: OperatorContext):
        self.validate(inputs, params)
        outputs = []
        for index, input_item in enumerate(inputs, start=1):
            saved_output = self.saved_output_for_input(input_item, params, index)
            df = context.get_input_data(input_item)
            result_df = self.apply_one(df, params)
            outputs.append(
                OperatorOutput(
                    output_id=str(saved_output.get("output_id") or f"out_{index}"),
                    name=self.make_output_name(input_item, params, index),
                    data_type=self.output_data_type,
                    from_input_id=input_item.input_id,
                    data=result_df,
                )
            )
        return OperatorResult(outputs=outputs)

    def apply_one(self, df, params: dict[str, Any]):
        raise NotImplementedError


class SourceOperator(BaseOperator):
    """无输入的数据源类算子。"""

    def validate(self, inputs: list[OperatorInput], params: dict[str, Any]):
        if inputs:
            raise ValueError(f"{self.title or self.action} 不接收上游输入")

    def infer_outputs(self, inputs: list[OperatorInput], params: dict[str, Any]):
        return [self.single_output(params)]


class BinaryOperator(BaseOperator):
    """双输入算子基类，例如表连接和纵向拼接。"""

    input_roles = ("left", "right")
    output_suffix = "结果"

    def input_by_role(
        self,
        inputs: list[OperatorInput],
        role: str,
        fallback_index: int,
    ) -> OperatorInput:
        """按角色取输入；旧连线没有角色时，用接入顺序兜底。"""
        for input_item in inputs:
            if input_item.role == role:
                return input_item
        return inputs[fallback_index]

    def make_output_name(
        self,
        left_input: OperatorInput,
        right_input: OperatorInput,
        params: dict[str, Any],
    ) -> str:
        """双输入算子默认只产生一个输出，名称来自显式 outputs。"""
        saved = self.saved_output(params, 1)
        out_name = str(saved.get("name") or "").strip()
        if out_name:
            return out_name
        return f"{left_input.name}_{self.output_suffix}"

    def validate(self, inputs: list[OperatorInput], params: dict[str, Any]):
        if len(inputs) != 2:
            raise ValueError(f"{self.title or self.action} 需要两个输入")
        super().validate(inputs, params)

    def infer_outputs(self, inputs: list[OperatorInput], params: dict[str, Any]):
        if len(inputs) < 2:
            return []
        left_input = self.input_by_role(inputs, self.input_roles[0], 0)
        right_input = self.input_by_role(inputs, self.input_roles[1], 1)
        return [
            OperatorOutput(
                output_id=str(self.saved_output(params, 1).get("output_id") or "out_1"),
                name=self.make_output_name(left_input, right_input, params),
                data_type=self.output_data_type,
            )
        ]

    def run(self, inputs: list[OperatorInput], params: dict[str, Any], context: OperatorContext):
        self.validate(inputs, params)
        left_input = self.input_by_role(inputs, self.input_roles[0], 0)
        right_input = self.input_by_role(inputs, self.input_roles[1], 1)
        left_data = context.get_input_data(left_input)
        right_data = context.get_input_data(right_input)
        result_data = self.apply_pair(left_data, right_data, params)
        return OperatorResult(
            outputs=[
                OperatorOutput(
                    output_id=str(self.saved_output(params, 1).get("output_id") or "out_1"),
                    name=self.make_output_name(left_input, right_input, params),
                    data_type=self.output_data_type,
                    data=result_data,
                )
            ]
        )

    def apply_pair(self, left_data, right_data, params: dict[str, Any]):
        raise NotImplementedError


class TemplateOperator(BaseOperator):
    """模板主线算子基类，输入输出都围绕 workbook 传递。"""

    input_data_type = "workbook"
    output_data_type = "workbook"


class ParameterOperator(BaseOperator):
    """参数类算子基类。"""

    input_data_type = "parameter"
    output_data_type = "parameter"
