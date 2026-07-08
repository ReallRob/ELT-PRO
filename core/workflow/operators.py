"""Concrete operator classes for the new multi-output workflow model.

这些类先复用现有的 dataframe/template 处理函数，只负责把每个算子的输入、输出、
参数校验和运行方式表达清楚。旧 UI/JSON/执行器暂时不依赖这里，后续可以逐步接入。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.app_paths import get_exec_dir
from core.dataframe_ops import (
    calc_code,
    calc_col,
    clean_data,
    code_block,
    concat_rows,
    cumsum_data,
    describe_data,
    drop_duplicates,
    export_df,
    filter_data,
    get_col_data,
    group_calc,
    left_join,
    melt_table,
    normalize_columns,
    pct_change_data,
    pivot_table,
    rank_col,
    read_source_file,
    sample_data,
    sort_data,
    transpose_data,
)
from core.workflow.operator_model import (
    BaseOperator,
    BatchMapOperator,
    BinaryOperator,
    OperatorInput,
    OperatorOutput,
    OperatorResult,
    SourceOperator,
    TemplateOperator,
)
from template_engine import (
    apply_template_insert_payload,
    build_template_metadata,
    load_template,
    save_template,
)


class LoadFileOperator(SourceOperator):
    """数据源导入算子。"""

    action = "load_file"
    title = "数据源导入"
    category = "输入输出"
    output_suffix = "数据"

    def run(self, inputs: list[OperatorInput], params: dict[str, Any], context):
        self.validate(inputs, params)
        df = read_source_file(
            params.get("file_path"),
            sheet_name=params.get("sheet_name", 0),
            skiprows=params.get("skiprows", 0),
            nrows=params.get("nrows", None),
            start_col=params.get("start_col", 1),
            ncols=params.get("ncols", None),
            has_header=params.get("has_header", True),
        )
        return OperatorResult(outputs=[self.single_output(params, df, default_name="数据源")])


class SingleTableOperator(BaseOperator):
    """一入一出的表算子基类。"""

    output_suffix = "结果"

    def infer_outputs(self, inputs: list[OperatorInput], params: dict[str, Any]):
        default = f"{inputs[0].name}_{self.output_suffix}" if inputs else self.title
        return [self.single_output(params, default_name=default)]

    def run(self, inputs: list[OperatorInput], params: dict[str, Any], context):
        self.validate(inputs, params)
        source = inputs[0]
        result = self.apply_one(context.get_input_data(source), params)
        default = f"{source.name}_{self.output_suffix}"
        return OperatorResult(
            outputs=[self.single_output(params, result, default_name=default, from_input_id=source.input_id)]
        )

    def apply_one(self, df, params: dict[str, Any]):
        raise NotImplementedError



class FilterOperator(BatchMapOperator):
    """数据筛选算子：多张输入表使用同一套条件，并生成多张对应输出表。"""

    action = "filter_data"
    title = "数据筛选"
    category = "数据变换"
    output_suffix = "筛选"

    def validate(self, inputs, params: dict[str, Any]):
        super().validate(inputs, params)
        conditions = params.get("conditions") or []
        if not conditions:
            raise ValueError("数据筛选需要至少一条筛选条件")

    def apply_one(self, df, params: dict[str, Any]):
        return filter_data(
            df,
            params.get("conditions") or [],
            params.get("logic", "AND"),
            params.get("col_type", "col_name"),
        )


class CleanOperator(BatchMapOperator):
    """数据清洗算子：每个输入表按同一套清洗规则处理。"""

    action = "clean_data"
    title = "数据清洗"
    category = "数据变换"
    output_suffix = "清洗"

    def validate(self, inputs, params: dict[str, Any]):
        super().validate(inputs, params)
        if not (params.get("rules") or []):
            raise ValueError("数据清洗需要至少一条清洗规则")

    def apply_one(self, df, params: dict[str, Any]):
        return clean_data(
            df,
            params.get("rules") or [],
            params.get("col_type", "col_name"),
        )


class SortOperator(BatchMapOperator):
    """排序算子：每个输入表按同一套排序规则处理。"""

    action = "sort_data"
    title = "排序"
    category = "数据变换"
    output_suffix = "排序"

    def validate(self, inputs, params: dict[str, Any]):
        super().validate(inputs, params)
        if not (params.get("sort_rules") or []):
            raise ValueError("排序需要至少一条排序规则")

    def apply_one(self, df, params: dict[str, Any]):
        return sort_data(
            df,
            params.get("sort_rules") or [],
            params.get("col_type", "col_name"),
        )


class GroupOperator(BatchMapOperator):
    """分组汇总算子：每个输入表按同一套分组列和聚合规则处理。"""

    action = "group_calc"
    title = "分组汇总"
    category = "汇总统计"
    output_suffix = "汇总"

    def validate(self, inputs, params: dict[str, Any]):
        super().validate(inputs, params)
        if not (params.get("group_key") or []):
            raise ValueError("分组汇总需要至少一个分组列")
        if not (params.get("agg_rules") or []):
            raise ValueError("分组汇总需要至少一条聚合规则")

    def _build_col_dict(self, agg_rules: list[dict[str, Any]]):
        """把 UI 中的多行聚合规则整理成 groupby.agg 需要的字典。"""
        col_dict = {}
        for rule in agg_rules:
            col = rule.get("col")
            func = rule.get("func")
            if not col or not func:
                continue
            if col in col_dict:
                if isinstance(col_dict[col], list):
                    col_dict[col].append(func)
                else:
                    col_dict[col] = [col_dict[col], func]
            else:
                col_dict[col] = func
        return col_dict

    def _apply_renames(self, result_df, source_df, params: dict[str, Any]):
        """把用户在聚合规则里填写的重命名应用到聚合结果列。"""
        col_type = params.get("col_type", "col_name")
        rename_dict = {}
        for rule in params.get("agg_rules") or []:
            rename = str(rule.get("rename") or "").strip()
            if not rename:
                continue
            actual_cols = normalize_columns(source_df, [rule.get("col")], col_type)
            if actual_cols:
                rename_dict[f"{actual_cols[0]}_{rule.get('func')}"] = rename
        return result_df.rename(columns=rename_dict) if rename_dict else result_df

    def apply_one(self, df, params: dict[str, Any]):
        col_dict = self._build_col_dict(params.get("agg_rules") or [])
        result_df = group_calc(
            df,
            params.get("group_key") or [],
            col_dict,
            params.get("col_type", "col_name"),
        )
        return self._apply_renames(result_df, df, params)


class ExtractOperator(BatchMapOperator):
    action = "get_col_data"
    title = "提取列"
    category = "数据变换"
    output_suffix = "提取"

    def validate(self, inputs, params):
        super().validate(inputs, params)
        if not (params.get("col_list") or []):
            raise ValueError("提取列需要至少选择一列")

    def apply_one(self, df, params):
        col_list = params.get("col_list") or []
        col_names = params.get("col_names") or []
        col_type = params.get("col_type", "col_name")
        actual_cols = normalize_columns(df, col_list, col_type)
        final_names = [
            col_names[index] if index < len(col_names) and col_names[index] else actual_cols[index]
            for index in range(len(actual_cols))
        ]
        return get_col_data(df, col_list, col_type, params.get("fill_value"), final_names)


class DropDuplicatesOperator(BatchMapOperator):
    action = "drop_duplicates"
    title = "去重"
    category = "数据变换"
    output_suffix = "去重"

    def apply_one(self, df, params):
        return drop_duplicates(
            df,
            params.get("subset_cols") or [],
            params.get("keep", "first"),
            params.get("col_type", "col_name"),
        )


class SampleOperator(SingleTableOperator):
    action = "sample_data"
    title = "抽样"
    category = "数据变换"
    output_suffix = "抽样"

    def apply_one(self, df, params):
        return sample_data(df, params.get("n"), params.get("frac"), params.get("random_state"))


class TransposeOperator(BatchMapOperator):
    action = "transpose_data"
    title = "转置"
    category = "数据变换"
    output_suffix = "转置"

    def apply_one(self, df, params):
        return transpose_data(df)


class PivotOperator(BatchMapOperator):
    action = "pivot_table"
    title = "数据透视"
    category = "汇总统计"
    output_suffix = "透视"

    def apply_one(self, df, params):
        return pivot_table(
            df,
            params.get("index_cols") or [],
            params.get("columns_col", ""),
            params.get("values_col", ""),
            params.get("aggfunc", "sum"),
            params.get("fill_value", 0),
            params.get("margins", True),
            params.get("col_type", "col_name"),
        )


class MeltOperator(BatchMapOperator):
    action = "melt_table"
    title = "逆透视"
    category = "汇总统计"
    output_suffix = "逆透视"

    def apply_one(self, df, params):
        return melt_table(
            df,
            params.get("id_cols") or [],
            params.get("value_cols") or [],
            params.get("var_name", "变量"),
            params.get("value_name", "值"),
            params.get("col_type", "col_name"),
        )


class DescribeOperator(SingleTableOperator):
    action = "describe_data"
    title = "描述统计"
    category = "汇总统计"
    output_suffix = "描述统计"

    def apply_one(self, df, params):
        return describe_data(df, params.get("percentiles"))


class RankOperator(BatchMapOperator):
    action = "rank_col"
    title = "数据排名"
    category = "计算列"
    output_suffix = "排名"

    def apply_one(self, df, params):
        result = df
        col_type = params.get("col_type", "col_name")
        for rule in params.get("rules") or []:
            result = rank_col(
                result,
                [rule.get("col")],
                [rule.get("rename")] if rule.get("rename") else [],
                col_type=col_type,
                method=rule.get("method", "min"),
                ascending=rule.get("ascending", True),
            )
        return result


class CalcOperator(BatchMapOperator):
    action = "calc_col"
    title = "公式计算"
    category = "计算列"
    output_suffix = "计算"

    def apply_one(self, df, params):
        result = df
        for rule in params.get("rules") or []:
            if rule.get("mode") == "code":
                result = calc_code(
                    result,
                    rule.get("code", rule.get("formula", "")),
                    rule.get("new_col_name", ""),
                    params.get("runtime_parameters"),
                    params.get("parameter_mappings"),
                    rule.get("timeout_seconds", 10),
                )
            else:
                result = calc_col(result, rule.get("new_col_name", ""), rule.get("formula", ""))
        return result


class CumsumOperator(BatchMapOperator):
    action = "cumsum_data"
    title = "累加计算"
    category = "计算列"
    output_suffix = "累加"

    def apply_one(self, df, params):
        return cumsum_data(df, params.get("col_list") or [], params.get("col_type", "col_name"))


class PctChangeOperator(BatchMapOperator):
    action = "pct_change_data"
    title = "环比计算"
    category = "计算列"
    output_suffix = "环比"

    def apply_one(self, df, params):
        return pct_change_data(
            df,
            params.get("col_list") or [],
            params.get("periods", 1),
            params.get("col_type", "col_name"),
        )


class ExportOperator(SingleTableOperator):
    action = "export_df"
    title = "自动导出"
    category = "输入输出"
    output_suffix = "导出"

    def apply_one(self, df, params):
        fname = params.get("file_name", "Export_Result.xlsx")
        folder = str(params.get("folder_path") or "").strip()
        target_path = str(Path(folder) / fname) if folder else str(get_exec_dir() / fname)
        export_df(df, target_path, get_exec_dir())
        return df


class CodeBlockOperator(BaseOperator):
    action = "code_block"
    title = "代码块"
    category = "实验功能"
    output_suffix = "代码结果"

    def infer_outputs(self, inputs, params):
        outputs = [item for item in params.get("outputs") or [] if isinstance(item, dict)]
        if outputs:
            return [
                OperatorOutput(
                    output_id=str(item.get("output_id") or f"out_{index}"),
                    name=str(item.get("name") or f"代码块结果{index}"),
                    data_type=str(item.get("data_type") or "table"),
                )
                for index, item in enumerate(outputs, start=1)
            ]
        data_type = "workbook" if any(item.data_type == "workbook" for item in inputs) else "table"
        return [self.single_output(params, default_name="代码块结果", data_type=data_type)]

    def validate(self, inputs, params):
        allowed = {"table", "workbook"}
        for input_item in inputs:
            if input_item.data_type not in allowed:
                raise ValueError(f"代码块暂不支持 {input_item.data_type} 输入: {input_item.name}")

    def run(self, inputs, params, context):
        self.validate(inputs, params)
        tables = {}
        workbooks = {}
        table_index = 0
        workbook_index = 0
        for index, input_item in enumerate(inputs):
            if input_item.data_type == "workbook":
                alias = str(input_item.role or ("wb" if workbook_index == 0 else f"wb{workbook_index}")).strip()
                if alias == "current":
                    alias = "wb" if workbook_index == 0 else f"wb{workbook_index}"
                workbooks[alias] = context.get_input_data(input_item)
                workbook_index += 1
            else:
                alias = str(input_item.role or ("df" if table_index == 0 else f"df{table_index}")).strip()
                if alias == "current":
                    alias = "df" if table_index == 0 else f"df{table_index}"
                tables[alias] = context.get_input_data(input_item)
                table_index += 1
        if "df" not in tables and tables:
            tables["df"] = next(iter(tables.values()))
        configured_outputs = [item for item in params.get("outputs") or [] if isinstance(item, dict)]
        output_names = [str(item.get("name") or "") for item in configured_outputs]
        log_callback = getattr(context, "log", None)
        result = code_block(
            tables,
            params.get("code", ""),
            workbooks,
            None,
            params.get("global_code", ""),
            params.get("function_spaces") or [],
            params.get("state", {}),
            params.get("runtime_parameters"),
            params.get("parameter_mappings"),
            params.get("timeout_seconds", 10),
            output_names,
            log_callback=log_callback,
            execution_mode=params.get("execution_mode", "auto"),
        )
        if isinstance(params.get("state"), dict):
            params["state"].clear()
            params["state"].update(result.state)
        outputs = []
        for index, item in enumerate(result.outputs, start=1):
            saved = configured_outputs[index - 1] if index - 1 < len(configured_outputs) else {}
            outputs.append(
                OperatorOutput(
                    output_id=str(saved.get("output_id") or f"out_{index}"),
                    name=item.name or str(saved.get("name") or f"代码块结果{index}"),
                    data_type=item.data_type,
                    data=item.data,
                )
            )
        return OperatorResult(outputs=outputs, logs=["代码块输出 {0} 个结果".format(len(outputs))])


class JoinOperator(BinaryOperator):
    """左连接算子：左表保留全部行，按匹配键从右表提取字段。"""

    action = "left_join"
    title = "表连接"
    category = "表格组合"
    output_suffix = "连接"

    def validate(self, inputs: list[OperatorInput], params: dict[str, Any]):
        super().validate(inputs, params)
        if not params.get("l_key"):
            raise ValueError("表连接需要左表匹配键")
        if not params.get("r_key"):
            raise ValueError("表连接需要右表匹配键")
        if not (params.get("get_cols") or []):
            raise ValueError("表连接需要至少一个右表提取列")

    def apply_pair(self, left_df, right_df, params: dict[str, Any]):
        key_type = params.get("key_type") or params.get("col_type", "col_name")
        get_cols = params.get("get_cols") or []
        actual_cols = normalize_columns(right_df, get_cols, key_type)
        col_names = params.get("col_names") or []
        final_names = [
            col_names[index] if index < len(col_names) and col_names[index] else actual_col
            for index, actual_col in enumerate(actual_cols)
        ]
        return left_join(
            left_df,
            right_df,
            params.get("l_key"),
            params.get("r_key"),
            get_cols,
            key_type=key_type,
            col_names=final_names,
            mapping_dict=params.get("mapping_dict"),
        )


class ConcatOperator(BinaryOperator):
    """纵向拼接算子：把两张表上下追加。"""

    action = "concat_rows"
    title = "纵向拼接"
    category = "表格组合"
    output_suffix = "拼接"

    def apply_pair(self, left_df, right_df, params: dict[str, Any]):
        return concat_rows(left_df, right_df, params.get("ignore_index", True))


class InsertBlockOperator(BaseOperator):
    """模板主线写入算子：接收一个 workbook 和一个 table，原地写入同一个 workbook。"""

    action = "insert_block"
    title = "写入模板"
    category = "模板"
    allowed_input_types = ("table", "workbook")
    output_data_type = "workbook"

    def validate(self, inputs: list[OperatorInput], params: dict[str, Any]):
        super().validate(inputs, params)
        table_count = sum(1 for item in inputs if item.data_type == "table")
        workbook_count = sum(1 for item in inputs if item.data_type == "workbook")
        if table_count != 1:
            raise ValueError("写入模板需要且只需要一个数据表输入")
        if workbook_count != 1:
            raise ValueError("写入模板需要且只需要一个模板工作簿输入")
        mode = str(params.get("mode") or "area")
        if mode == "match_fill":
            match_keys = [row for row in params.get("match_keys") or [] if isinstance(row, dict)]
            valid_keys = [
                row
                for row in match_keys
                if str(row.get("df_col") or "").strip()
                and (str(row.get("template_field") or "").strip() or str(row.get("template_col") or "").strip())
            ]
            if not valid_keys:
                raise ValueError("匹配填充需要至少一个匹配键")
            write_mappings = [row for row in params.get("write_mappings") or [] if isinstance(row, dict)]
            if params.get("header_mode") == "manual_columns" and not write_mappings:
                raise ValueError("手动指定列模式下需要填写写入映射")
            if params.get("write_mode") == "manual" and not write_mappings:
                raise ValueError("手动写入映射模式下需要填写写入映射")
            return
        if not params.get("start_row") or not params.get("start_col"):
            raise ValueError("区域插入需要填写起始行和起始列")

    def _input_by_type(self, inputs: list[OperatorInput], data_type: str) -> OperatorInput | None:
        return next((item for item in inputs if item.data_type == data_type), None)

    def _prepare_dataframe(self, df, params: dict[str, Any]):
        """按参数选择要写入模板的列，并应用可选重命名。"""
        cols = params.get("col_list") or ["*"]
        col_names = params.get("col_names") or []
        if cols == "*" or cols == ["*"]:
            fill_df = df
        else:
            available = normalize_columns(df, cols, "col_name")
            if not available:
                raise ValueError(f"指定列在 DataFrame 中不存在: {cols}")
            fill_df = df[available]

        rename_map = {}
        for index, col in enumerate(fill_df.columns):
            if index < len(col_names) and col_names[index]:
                rename_map[col] = col_names[index]
        return fill_df.rename(columns=rename_map) if rename_map else fill_df

    def _build_payload(self, df, params: dict[str, Any]):
        return {
            "mode": "area",
            "df": self._prepare_dataframe(df, params),
            "sheet_name": params.get("sheet_name") or "",
            "start_row": params.get("start_row") or "max_row + 1",
            "end_row": params.get("end_row") or "",
            "start_col": params.get("start_col") or "1",
            "end_col": params.get("end_col") or "",
            "write_header": params.get("write_header", True),
        }

    def _build_match_fill_payload(self, df, params: dict[str, Any]):
        return {
            "mode": "match_fill",
            "df": df,
            "sheet_name": params.get("sheet_name") or "",
            "header_mode": params.get("header_mode") or "specified",
            "header_row": params.get("header_row") or "",
            "header_search_start_row": params.get("header_search_start_row") or "",
            "header_search_end_row": params.get("header_search_end_row") or "",
            "data_start_row": params.get("data_start_row") or "",
            "data_end_row": params.get("data_end_row") or "",
            "start_col": params.get("start_col") or "1",
            "end_col": params.get("end_col") or "",
            "match_keys": params.get("match_keys") or [],
            "write_mode": params.get("write_mode") or "auto_same_name",
            "write_mappings": params.get("write_mappings") or [],
            "on_missing": params.get("on_missing") or "skip",
            "on_duplicate": params.get("on_duplicate") or "first",
            "overwrite_formulas": bool(params.get("overwrite_formulas", False)),
        }

    def _apply_payload(self, wb, payload: dict[str, Any]) -> str:
        payload = dict(payload)
        payload["_template_insert"] = True
        success, message = apply_template_insert_payload(wb, payload)
        if not success:
            raise ValueError(message)
        return message

    def infer_outputs(self, inputs: list[OperatorInput], params: dict[str, Any]):
        return [self.single_output(params, default_name="写入模板", data_type="workbook")]

    def run(self, inputs: list[OperatorInput], params: dict[str, Any], context):
        self.validate(inputs, params)
        table_input = self._input_by_type(inputs, "table")
        workbook_input = self._input_by_type(inputs, "workbook")
        df = context.get_input_data(table_input)
        if str(params.get("mode") or "area") == "match_fill":
            payload = self._build_match_fill_payload(df, params)
        else:
            payload = self._build_payload(df, params)

        workbook_entry = context.get_input_data(workbook_input)
        wb = workbook_entry.get("_wb") if isinstance(workbook_entry, dict) else workbook_entry
        if wb is None:
            raise ValueError("模板工作簿输入无效")
        message = self._apply_payload(wb, payload)
        if isinstance(workbook_entry, dict):
            workbook_entry["_meta"] = build_template_metadata(
                wb, str(workbook_entry.get("_template_path") or "")
            )

        return OperatorResult(
            outputs=[
                self.single_output(
                    params,
                    workbook_entry,
                    default_name="写入模板",
                    data_type="workbook",
                    from_input_id=workbook_input.input_id,
                )
            ],
            logs=[message],
        )


class ImportTemplateOperator(SourceOperator):
    """加载模板算子：从 xlsx 文件创建模板主线 workbook。"""

    action = "import_template"
    title = "加载模板"
    category = "模板"
    output_data_type = "workbook"

    def validate(self, inputs: list[OperatorInput], params: dict[str, Any]):
        super().validate(inputs, params)
        template_path = str(params.get("template_path") or "").strip()
        if not template_path or not os.path.exists(template_path):
            raise ValueError(f"模板文件不存在: {template_path}")

    def infer_outputs(self, inputs: list[OperatorInput], params: dict[str, Any]):
        return [self.single_output(params, default_name="加载模板", data_type="workbook")]

    def run(self, inputs: list[OperatorInput], params: dict[str, Any], context):
        self.validate(inputs, params)
        template_path = str(params.get("template_path") or "").strip()
        wb, meta = load_template(template_path)
        workbook_entry = {
            "_wb": wb,
            "_meta": meta,
            "_template_path": template_path,
            "_saved_path": "",
            "_mutable": True,
        }

        return OperatorResult(
            outputs=[
                self.single_output(
                    params,
                    workbook_entry,
                    default_name="加载模板",
                    data_type="workbook",
                )
            ],
            logs=[f"模板加载成功: {template_path}"],
        )


class SaveTemplateOperator(TemplateOperator):
    """保存模板算子：接收模板主线 workbook 并保存到 xlsx。"""

    action = "save_template"
    title = "保存模板"
    category = "模板"
    allowed_input_types = ("workbook",)
    output_data_type = "workbook"

    def validate(self, inputs: list[OperatorInput], params: dict[str, Any]):
        super().validate(inputs, params)
        if len(inputs) != 1:
            raise ValueError("保存模板需要且只需要一个模板工作簿输入")

    def _target_path(self, params: dict[str, Any], workbook_entry: dict[str, Any] | None = None) -> str:
        explicit_path = str(params.get("output_path") or "").strip()
        if explicit_path:
            return explicit_path
        folder = str(params.get("folder_path") or "").strip()
        if folder:
            file_name = str(params.get("file_name") or "").strip()
            if not file_name:
                template_path = str((workbook_entry or {}).get("_template_path") or "").strip()
                stem = Path(template_path).stem if template_path else "template"
                file_name = f"{stem}_filled.xlsx"
            if not file_name.lower().endswith(".xlsx"):
                file_name += ".xlsx"
            return str(Path(folder) / file_name)
        file_name = str(params.get("file_name") or "").strip()
        if not file_name:
            template_path = str((workbook_entry or {}).get("_template_path") or "").strip()
            stem = Path(template_path).stem if template_path else "template"
            file_name = f"{stem}_filled.xlsx"
        if not file_name.lower().endswith(".xlsx"):
            file_name += ".xlsx"
        return str(get_exec_dir() / file_name)

    def run(self, inputs: list[OperatorInput], params: dict[str, Any], context):
        self.validate(inputs, params)
        workbook_entry = context.get_input_data(inputs[0])
        wb = workbook_entry.get("_wb") if isinstance(workbook_entry, dict) else workbook_entry
        if wb is None:
            raise ValueError("模板工作簿输入无效")
        target_path = self._target_path(params, workbook_entry if isinstance(workbook_entry, dict) else {})
        _, final_path = save_template(wb, target_path)
        if isinstance(workbook_entry, dict):
            workbook_entry["_saved_path"] = final_path
            workbook_entry["_meta"] = build_template_metadata(
                wb, str(workbook_entry.get("_template_path") or "")
            )
        return OperatorResult(
            outputs=[
                self.single_output(
                    params,
                    workbook_entry,
                    default_name="保存模板",
                    data_type="workbook",
                    from_input_id=inputs[0].input_id,
                )
            ],
            logs=[f"模板保存成功: {final_path}"],
        )


OPERATOR_CLASS_REGISTRY = {
    LoadFileOperator.action: LoadFileOperator,
    ExportOperator.action: ExportOperator,
    ExtractOperator.action: ExtractOperator,
    FilterOperator.action: FilterOperator,
    CleanOperator.action: CleanOperator,
    SortOperator.action: SortOperator,
    GroupOperator.action: GroupOperator,
    DropDuplicatesOperator.action: DropDuplicatesOperator,
    SampleOperator.action: SampleOperator,
    TransposeOperator.action: TransposeOperator,
    PivotOperator.action: PivotOperator,
    MeltOperator.action: MeltOperator,
    DescribeOperator.action: DescribeOperator,
    RankOperator.action: RankOperator,
    CalcOperator.action: CalcOperator,
    CumsumOperator.action: CumsumOperator,
    PctChangeOperator.action: PctChangeOperator,
    JoinOperator.action: JoinOperator,
    ConcatOperator.action: ConcatOperator,
    InsertBlockOperator.action: InsertBlockOperator,
    ImportTemplateOperator.action: ImportTemplateOperator,
    SaveTemplateOperator.action: SaveTemplateOperator,
    CodeBlockOperator.action: CodeBlockOperator,
}


def create_operator(action: str):
    operator_class = OPERATOR_CLASS_REGISTRY.get(action)
    if operator_class is None:
        raise ValueError(f"未知算子类: {action}")
    return operator_class()
