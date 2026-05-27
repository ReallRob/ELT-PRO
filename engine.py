import traceback
import gc
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
)


def get_exec_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.absolute()


class WorkflowEngine(QThread):
    log_signal = pyqtSignal(str)
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

    def run(self):
        try:
            steps = self.workflow_config.get("steps", [])
            total_steps = len(steps)
            workflow_name = self.workflow_config.get("workflow_name", "未命名")

            self.data_pool = {}
            display_pool = {}

            ref_count = {}
            for step in steps:
                p = step.get("params", {})
                action = step.get("action")
                deps = []
                if action == "left_join":
                    deps = [p.get("df1_id"), p.get("df2_id")]
                elif "df_id" in p:
                    deps = [p.get("df_id")]

                for dep in deps:
                    if dep:
                        ref_count[dep] = ref_count.get(dep, 0) + 1

            self.log(f"开始执行工作流: {workflow_name} (共 {total_steps} 步)")

            for i, step in enumerate(steps):
                step_id = step.get("step_id", i + 1)
                node_id = step.get("node_id")
                action = step.get("action")
                out_name = step.get("out_name", f"Result_{step_id}")
                p = step.get("params", {})

                self.log(
                    f"\n  [步骤 {step_id}/{total_steps}] 节点: {action} -> 输出表: {out_name}"
                )

                try:
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
                        df = self._get_df(p.get("df_id")).copy()
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
                        df = self._get_df(p.get("df_id")).copy()
                        rules = p.get("rules", [])
                        for rule in rules:
                            df = calc_col(df, rule["new_col_name"], rule["formula"])
                        self.data_pool[node_id] = df

                    elif action == "clean_data":
                        df = self._get_df(p.get("df_id"))
                        self.data_pool[node_id] = clean_data(
                            df, p.get("rules", []), p.get("col_type", "col_name")
                        )

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

                    self.log(
                        f"    - 完成. 数据规模: {self.data_pool[node_id].shape[0]} 行, {self.data_pool[node_id].shape[1]} 列"
                    )

                    if ref_count.get(node_id, 0) == 0 or self.keep_intermediates:
                        display_pool[out_name] = self.data_pool[node_id]

                    deps = []
                    if action == "left_join":
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
                                gc.collect()
                                self.log(f"    - [内存优化] 中间表已释放 (ID: {dep})")

                except Exception as step_e:
                    err_msg = traceback.format_exc()
                    self.log(
                        f"\n    × [步骤 {step_id}] 节点执行失败！\n原因: {str(step_e)}\n{err_msg}"
                    )
                    self.finished_signal.emit(False, {})
                    return

            self.log(f"\n成功！所有节点执行完毕。")
            self.finished_signal.emit(True, display_pool)

        except Exception as e:
            err_msg = traceback.format_exc()
            self.log(f"\n× 致命错误: 引擎解析崩溃\n{err_msg}")
            self.finished_signal.emit(False, {})
