import traceback
import sys
import os
from pathlib import Path
import pandas as pd
from PyQt5.QtCore import QThread, pyqtSignal

from xlsx_fun import (
    get_col_data,
    filter_data,
    group_calc,
    left_join,
    rank_col,
    sort_data,
    calc_col,
    clean_data,
    export_df,
    normalize_columns,
    pivot_table,
    melt_table,
    concat_rows,
    drop_duplicates,
    sample_data,
    describe_data,
    transpose_data,
    cumsum_data,
    pct_change_data,
)
from template_engine import load_template, insert_into_template, save_template
from parameter_resolver import (
    clone_resolved_runtime_value,
    normalize_runtime_parameters,
)


def get_exec_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.absolute()


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

    def _get_df(self, df_id):
        df = self.data_pool.get(df_id)
        if df is None:
            raise ValueError(f"无法在内存中找到上游输入表，请检查连线！(ID: {df_id})")
        return df

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

        parameters.update(
            normalize_runtime_parameters(
                self.workflow_config.get("runtime_parameters", {})
            )
        )
        mappings.update(self.workflow_config.get("parameter_mappings", {}) or {})
        return parameters, mappings

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

            ref_count = {}
            for step in steps:
                p = step.get("params", {})
                action = step.get("action")
                deps = []
                if action == "import_template":
                    deps = []
                elif action == "insert_block":
                    deps = [p.get("df_id"), p.get("template_id")]
                    deps = [d for d in deps if d]
                elif action in ("left_join", "concat_rows"):
                    deps = [p.get("df1_id"), p.get("df2_id")]
                elif "df_id" in p:
                    deps = [p.get("df_id")]

                for dep in deps:
                    if dep:
                        ref_count[dep] = ref_count.get(dep, 0) + 1

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
                p = clone_resolved_runtime_value(
                    step.get("params", {}),
                    runtime_parameters,
                    parameter_mappings,
                    strict=True,
                )

                self.log(
                    f"\n  [步骤 {step_id}/{total_steps}] 节点: {action} -> 输出表: {out_name}"
                )

                try:
                    if action == "input_param":
                        count = len(p.get("parameters", {}))
                        self.log(f"    - 已加载运行参数: {count} 个")
                        continue

                    elif action == "param_mapping":
                        mapping_name = p.get("mapping_name", "未命名映射")
                        rules = p.get("rules", [])
                        self.log(f"    - 已加载参数映射: {mapping_name} ({len(rules)} 条规则)")
                        continue

                    if action == "load_file":
                        orig_path = p.get("file_path")
                        actual_path = self.file_mapping.get(orig_path, orig_path)
                        sheet_name = p.get("sheet_name", 0)
                        skiprows = p.get("skiprows", 0)
                        nrows = p.get("nrows", None)

                        self.log(f"    - 正在读取文件: {actual_path}")
                        if actual_path.endswith((".xlsx", ".xls")):
                            df = pd.read_excel(
                                actual_path,
                                sheet_name=sheet_name,
                                skiprows=skiprows,
                                nrows=nrows,
                            )
                        else:
                            df = pd.read_csv(
                                actual_path, skiprows=skiprows, nrows=nrows
                            )
                        self.data_pool[node_id] = df

                    elif action == "get_col_data":
                        df = self._get_df(p.get("df_id"))
                        col_list = p.get("col_list", [])
                        col_names = p.get("col_names", [])
                        col_type = p.get("col_type", "col_name")
                        actual_cols = normalize_columns(df, col_list, col_type)
                        final_names = [
                            (
                                col_names[j]
                                if j < len(col_names) and col_names[j]
                                else actual_cols[j]
                            )
                            for j in range(len(actual_cols))
                        ]
                        self.data_pool[node_id] = get_col_data(
                            df, col_list, col_type, p.get("fill_value"), final_names
                        )

                    elif action == "filter_data":
                        df = self._get_df(p.get("df_id"))
                        self.data_pool[node_id] = filter_data(
                            df,
                            p.get("conditions", []),
                            p.get("logic", "AND"),
                            p.get("col_type", "col_name"),
                        )

                    elif action == "group_calc":
                        df = self._get_df(p.get("df_id"))
                        col_type = p.get("col_type", "col_name")
                        agg_rules = p.get("agg_rules", [])
                        col_dict = {}
                        for r in agg_rules:
                            c, f = r["col"], r["func"]
                            if c in col_dict:
                                if isinstance(col_dict[c], list):
                                    col_dict[c].append(f)
                                else:
                                    col_dict[c] = [col_dict[c], f]
                            else:
                                col_dict[c] = f
                        group_df = group_calc(
                            df, p.get("group_key", []), col_dict, col_type
                        )
                        if agg_rules:
                            rename_dict = {}
                            for rule in agg_rules:
                                if rule.get("rename"):
                                    actual_cols = normalize_columns(
                                        df, [rule["col"]], col_type
                                    )
                                    if actual_cols:
                                        rename_dict[
                                            f"{actual_cols[0]}_{rule['func']}"
                                        ] = rule["rename"]
                            if rename_dict:
                                group_df = group_df.rename(columns=rename_dict)
                        self.data_pool[node_id] = group_df

                    elif action == "left_join":
                        df1 = self._get_df(p.get("df1_id"))
                        df2 = self._get_df(p.get("df2_id"))
                        get_cols = p.get("get_cols", [])
                        col_names = p.get("col_names", [])
                        key_type = p.get("key_type", "col_name")
                        actual_cols = normalize_columns(df2, get_cols, key_type)
                        final_names = [
                            (
                                col_names[j]
                                if j < len(col_names) and col_names[j]
                                else actual_cols[j]
                            )
                            for j in range(len(actual_cols))
                        ]
                        self.data_pool[node_id] = left_join(
                            df1,
                            df2,
                            p["l_key"],
                            p["r_key"],
                            get_cols,
                            key_type=key_type,
                            col_names=final_names,
                        )

                    elif action == "rank_col":
                        df = self._get_df(p.get("df_id"))
                        col_type = p.get("col_type", "col_name")
                        rules = p.get("rules", [])
                        for rule in rules:
                            df = rank_col(
                                df,
                                [rule["col"]],
                                [rule["rename"]] if rule.get("rename") else [],
                                col_type=col_type,
                                method=rule.get("method", "min"),
                                ascending=rule.get("ascending", True),
                            )
                        self.data_pool[node_id] = df

                    elif action == "sort_data":
                        df = self._get_df(p.get("df_id"))
                        self.data_pool[node_id] = sort_data(
                            df, p.get("sort_rules", []), p.get("col_type", "col_name")
                        )

                    elif action == "calc_col":
                        df = self._get_df(p.get("df_id"))
                        rules = p.get("rules", [])
                        for rule in rules:
                            df = calc_col(df, rule["new_col_name"], rule["formula"])
                        self.data_pool[node_id] = df

                    elif action == "clean_data":
                        df = self._get_df(p.get("df_id"))
                        self.data_pool[node_id] = clean_data(
                            df, p.get("rules", []), p.get("col_type", "col_name")
                        )

                    elif action == "pivot_table":
                        df = self._get_df(p.get("df_id"))
                        col_type = p.get("col_type", "col_name")
                        result = pivot_table(
                            df, p.get("index_cols", []), p.get("columns_col", ""),
                            p.get("values_col", ""), p.get("aggfunc", "sum"),
                            p.get("fill_value", 0), p.get("margins", True), col_type,
                        )
                        self.data_pool[node_id] = result
                        self.log(
                            f"    - 透视完成: {result.shape[0]} 行 x {result.shape[1]} 列"
                        )

                    elif action == "melt_table":
                        df = self._get_df(p.get("df_id"))
                        col_type = p.get("col_type", "col_name")
                        result = melt_table(
                            df, p.get("id_cols", []), p.get("value_cols", []),
                            p.get("var_name", "变量"), p.get("value_name", "值"), col_type,
                        )
                        self.data_pool[node_id] = result

                    elif action == "concat_rows":
                        df1 = self._get_df(p.get("df1_id"))
                        df2 = self._get_df(p.get("df2_id"))
                        result = concat_rows(df1, df2, p.get("ignore_index", True))
                        self.data_pool[node_id] = result

                    elif action == "drop_duplicates":
                        df = self._get_df(p.get("df_id"))
                        col_type = p.get("col_type", "col_name")
                        result = drop_duplicates(
                            df, p.get("subset_cols", []), p.get("keep", "first"), col_type,
                        )
                        self.data_pool[node_id] = result
                        self.log(
                            f"    - 去重完成: {result.shape[0]} 行 (原始: {df.shape[0]} 行)"
                        )

                    elif action == "sample_data":
                        df = self._get_df(p.get("df_id"))
                        result = sample_data(
                            df, p.get("n"), p.get("frac"), p.get("random_state"),
                        )
                        self.data_pool[node_id] = result
                        self.log(
                            f"    - 抽样完成: {result.shape[0]} 行 (原始: {df.shape[0]} 行)"
                        )

                    elif action == "describe_data":
                        df = self._get_df(p.get("df_id"))
                        result = describe_data(df, p.get("percentiles"))
                        self.data_pool[node_id] = result

                    elif action == "transpose_data":
                        df = self._get_df(p.get("df_id"))
                        result = transpose_data(df)
                        self.data_pool[node_id] = result
                        self.log(
                            f"    - 转置完成: {result.shape[0]} 行 x {result.shape[1]} 列"
                        )

                    elif action == "cumsum_data":
                        df = self._get_df(p.get("df_id"))
                        col_type = p.get("col_type", "col_name")
                        result = cumsum_data(df, p.get("col_list", []), col_type)
                        self.data_pool[node_id] = result

                    elif action == "pct_change_data":
                        df = self._get_df(p.get("df_id"))
                        col_type = p.get("col_type", "col_name")
                        result = pct_change_data(
                            df, p.get("col_list", []), p.get("periods", 1), col_type,
                        )
                        self.data_pool[node_id] = result

                    # ==========================================
                    # 修改后的导出执行逻辑
                    # ==========================================
                    elif action == "export_df":
                        df = self._get_df(p.get("df_id"))
                        default_run_dir = get_exec_dir()

                        fname = p.get("file_name", "Export_Result.xlsx")
                        fdir = p.get("folder_path", "").strip()

                        # 路径合成逻辑
                        if not fdir:
                            target_path = str(default_run_dir / fname)
                        else:
                            target_path = str(Path(fdir) / fname)

                        success, final_path = export_df(
                            df, target_path, default_run_dir
                        )
                        if success:
                            self.log(f"    - [导出成功] 文件已保存至: {final_path}")
                        else:
                            self.log(
                                f"    - [路径修正] 原路径无法保存，已转存至: {final_path}"
                            )
                        self.data_pool[node_id] = df

                    elif action == "import_template":
                        template_path = p.get("template_path")
                        if not template_path or not os.path.exists(template_path):
                            raise ValueError(f"模板文件不存在: {template_path}")
                        wb, meta = load_template(template_path)
                        self.data_pool[node_id] = {"_wb": wb, "_meta": meta}
                        self.log(
                            f"    - 模板已加载: {os.path.basename(template_path)}"
                            f" ({len(meta['sheet_names'])} 个工作表)"
                        )

                    elif action == "insert_block":
                        df = self._get_df(p.get("df_id"))
                        template_id = p.get("template_id")
                        if not template_id or template_id not in self.data_pool:
                            raise ValueError(f"模板表未找到: {template_id}")
                        tmpl_entry = self.data_pool[template_id]
                        wb = tmpl_entry.get("_wb")
                        if wb is None:
                            raise ValueError("模板数据无效，请检查上游导入模板节点")

                        sheet_name = p.get("sheet_name", wb.sheetnames[0])
                        start_row = p.get("start_row", "max_row + 1")
                        start_col = p.get("start_col", "1")
                        cols = p.get("col_list", ["*"])
                        col_names = p.get("col_names", [])

                        # 列重命名
                        df_fill = df.copy()
                        if col_names and any(col_names):
                            actual_cols = [c for c in cols if c != "*"]
                            if actual_cols:
                                available = [c for c in actual_cols if c in df.columns]
                            else:
                                available = list(df.columns)
                            rename_map = {}
                            for i, c in enumerate(available):
                                if i < len(col_names) and col_names[i]:
                                    rename_map[c] = col_names[i]
                            if rename_map:
                                df_fill = df_fill.rename(columns=rename_map)

                        success, msg = insert_into_template(
                            wb, df_fill, sheet_name, start_row, start_col,
                            columns=cols,
                            write_header=p.get("write_header", True),
                            inherit_style=True,
                        )
                        if not success:
                            raise ValueError(msg)

                        self.log(f"    - [插入成功] {msg}")
                        # 保存填充结果到临时文件（供后续插入或最终导出使用）
                        self.data_pool[node_id] = tmpl_entry

                    if action not in ("template_export", "import_template", "insert_block"):
                        self.log(
                            f"    - 完成. 数据规模: {self.data_pool[node_id].shape[0]} 行, {self.data_pool[node_id].shape[1]} 列"
                        )

                    if action not in ("template_export", "import_template", "insert_block") and (
                        ref_count.get(node_id, 0) == 0 or self.keep_intermediates
                    ):
                        # 去重: 同名追加后缀
                        key = out_name
                        if key in display_pool:
                            cnt = dedup_counters.get(out_name, 1) + 1
                            dedup_counters[out_name] = cnt
                            key = f"{out_name} ({cnt})"
                        display_pool[key] = self.data_pool[node_id]
                        # 记录实际使用的 key，供 UI 同步节点参数
                        if not hasattr(self, '_dedup_map'):
                            self._dedup_map = {}
                        self._dedup_map[node_id] = key

                    deps = []
                    if action == "insert_block":
                        deps = [p.get("df_id"), p.get("template_id")]
                        deps = [d for d in deps if d]
                    elif action == "import_template":
                        deps = []
                    elif action in ("left_join", "concat_rows"):
                        deps = [p.get("df1_id"), p.get("df2_id")]
                    elif "df_id" in p:
                        deps = [p.get("df_id")]

                    for dep in deps:
                        if dep and dep in ref_count:
                            ref_count[dep] -= 1
                            if (
                                not self.keep_intermediates
                                and ref_count[dep] <= 0
                                and dep in self.data_pool
                            ):
                                del self.data_pool[dep]
                                self.log(f"    - [内存优化] 中间表已释放 (ID: {dep})")

                except Exception as step_e:
                    err_msg = traceback.format_exc()
                    self.log(
                        f"\n    × [步骤 {step_id}] 节点执行失败！\n原因: {str(step_e)}\n{err_msg}"
                    )
                    self.finished_signal.emit(False, {})
                    return

            self.log(f"\n成功！所有节点执行完毕。")
            self.finished_signal.emit(True, {
                "data": display_pool,
                "dedup_map": getattr(self, '_dedup_map', {}),
            })

        except Exception as e:
            err_msg = traceback.format_exc()
            self.log(f"\n× 致命错误: 引擎解析崩溃\n{err_msg}")
            self.finished_signal.emit(False, {})
