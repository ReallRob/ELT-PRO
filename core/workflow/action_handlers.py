"""Action handlers used by the workflow engine.

Each handler receives the engine instance, the resolved parameter dict, and the
current node id. The engine keeps ownership of shared state such as the data
pool and logging signals; handlers only implement one operator's business work.
"""

import os
import sys
from pathlib import Path

from template_engine import insert_into_template, load_template, save_template
from core.dataframe_ops import (
    calc_col,
    clean_data,
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

PARAMETER_ACTIONS = {"input_param", "param_mapping", "advanced_param_mapping"}
TEMPLATE_ACTIONS = {"template_export", "import_template", "insert_block"}


def get_exec_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def collect_action_dependencies(action, params):
    """Return upstream node ids consumed by an action.

    The engine uses this for reference counting and memory release. Keeping the
    rules here prevents dependency logic and handler dispatch from drifting.
    """
    if action == "import_template":
        return []
    if action == "insert_block":
        return [d for d in [params.get("df_id"), params.get("template_id")] if d]
    if action in ("left_join", "concat_rows"):
        return [params.get("df1_id"), params.get("df2_id")]
    if "df_id" in params:
        return [params.get("df_id")]
    return []


def should_log_dataframe_shape(action):
    return action not in TEMPLATE_ACTIONS and action not in PARAMETER_ACTIONS


def should_publish_output(action):
    return action not in TEMPLATE_ACTIONS and action not in PARAMETER_ACTIONS


def handle_parameter_action(engine, action, params):
    """Log parameter-only actions; they update runtime metadata before execution."""
    if action == "input_param":
        count = len(params.get("parameters", {}))
        engine.log(f"    - 已加载运行参数: {count} 个")
        return True

    if action == "param_mapping":
        mapping_name = params.get("mapping_name", "未命名映射")
        rules = params.get("rules", [])
        engine.log(f"    - 已加载参数映射: {mapping_name} ({len(rules)} 条规则)")
        return True

    if action == "advanced_param_mapping":
        config = params.get("rule_engine_config", {})
        param_count = len(config.get("parameters", []))
        rule_count = len(config.get("rules", []))
        engine.log(f"    - 已加载参数高级映射: {param_count} 个参数，{rule_count} 条规则")
        return True

    return False


def run_load_file(engine, params, node_id):
    orig_path = params.get("file_path")
    actual_path = engine.file_mapping.get(orig_path, orig_path)
    sheet_name = params.get("sheet_name", 0)
    skiprows = params.get("skiprows", 0)
    nrows = params.get("nrows", None)
    start_col = params.get("start_col", 1)
    ncols = params.get("ncols", None)
    has_header = params.get("has_header", True)

    engine.log(f"    - 正在读取文件: {actual_path}")
    df = read_source_file(
        actual_path,
        sheet_name=sheet_name,
        skiprows=skiprows,
        nrows=nrows,
        start_col=start_col,
        ncols=ncols,
        has_header=has_header,
    )
    engine.data_pool[node_id] = df


def run_get_col_data(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    col_list = params.get("col_list", [])
    col_names = params.get("col_names", [])
    col_type = params.get("col_type", "col_name")
    actual_cols = normalize_columns(df, col_list, col_type)
    final_names = [
        col_names[j] if j < len(col_names) and col_names[j] else actual_cols[j]
        for j in range(len(actual_cols))
    ]
    engine.data_pool[node_id] = get_col_data(
        df, col_list, col_type, params.get("fill_value"), final_names
    )


def run_filter_data(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    engine.data_pool[node_id] = filter_data(
        df,
        params.get("conditions", []),
        params.get("logic", "AND"),
        params.get("col_type", "col_name"),
    )


def run_group_calc(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    col_type = params.get("col_type", "col_name")
    agg_rules = params.get("agg_rules", [])
    col_dict = {}
    for rule in agg_rules:
        col, func = rule["col"], rule["func"]
        if col in col_dict:
            if isinstance(col_dict[col], list):
                col_dict[col].append(func)
            else:
                col_dict[col] = [col_dict[col], func]
        else:
            col_dict[col] = func

    group_df = group_calc(df, params.get("group_key", []), col_dict, col_type)
    if agg_rules:
        rename_dict = {}
        for rule in agg_rules:
            if rule.get("rename"):
                actual_cols = normalize_columns(df, [rule["col"]], col_type)
                if actual_cols:
                    rename_dict[f"{actual_cols[0]}_{rule['func']}"] = rule["rename"]
        if rename_dict:
            group_df = group_df.rename(columns=rename_dict)
    engine.data_pool[node_id] = group_df


def run_left_join(engine, params, node_id):
    df1 = engine.get_df(params.get("df1_id"))
    df2 = engine.get_df(params.get("df2_id"))
    get_cols = params.get("get_cols", [])
    col_names = params.get("col_names", [])
    key_type = params.get("key_type", "col_name")
    actual_cols = normalize_columns(df2, get_cols, key_type)
    final_names = [
        col_names[j] if j < len(col_names) and col_names[j] else actual_cols[j]
        for j in range(len(actual_cols))
    ]
    engine.data_pool[node_id] = left_join(
        df1,
        df2,
        params["l_key"],
        params["r_key"],
        get_cols,
        key_type=key_type,
        col_names=final_names,
    )


def run_rank_col(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    col_type = params.get("col_type", "col_name")
    for rule in params.get("rules", []):
        df = rank_col(
            df,
            [rule["col"]],
            [rule["rename"]] if rule.get("rename") else [],
            col_type=col_type,
            method=rule.get("method", "min"),
            ascending=rule.get("ascending", True),
        )
    engine.data_pool[node_id] = df


def run_sort_data(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    engine.data_pool[node_id] = sort_data(
        df, params.get("sort_rules", []), params.get("col_type", "col_name")
    )


def run_calc_col(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    for rule in params.get("rules", []):
        df = calc_col(df, rule["new_col_name"], rule["formula"])
    engine.data_pool[node_id] = df


def run_clean_data(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    engine.data_pool[node_id] = clean_data(
        df, params.get("rules", []), params.get("col_type", "col_name")
    )


def run_pivot_table(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    col_type = params.get("col_type", "col_name")
    result = pivot_table(
        df,
        params.get("index_cols", []),
        params.get("columns_col", ""),
        params.get("values_col", ""),
        params.get("aggfunc", "sum"),
        params.get("fill_value", 0),
        params.get("margins", True),
        col_type,
    )
    engine.data_pool[node_id] = result
    engine.log(f"    - 透视完成: {result.shape[0]} 行 x {result.shape[1]} 列")


def run_melt_table(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    col_type = params.get("col_type", "col_name")
    engine.data_pool[node_id] = melt_table(
        df,
        params.get("id_cols", []),
        params.get("value_cols", []),
        params.get("var_name", "变量"),
        params.get("value_name", "值"),
        col_type,
    )


def run_concat_rows(engine, params, node_id):
    df1 = engine.get_df(params.get("df1_id"))
    df2 = engine.get_df(params.get("df2_id"))
    engine.data_pool[node_id] = concat_rows(df1, df2, params.get("ignore_index", True))


def run_drop_duplicates(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    col_type = params.get("col_type", "col_name")
    result = drop_duplicates(
        df, params.get("subset_cols", []), params.get("keep", "first"), col_type
    )
    engine.data_pool[node_id] = result
    engine.log(f"    - 去重完成: {result.shape[0]} 行 (原始: {df.shape[0]} 行)")


def run_sample_data(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    result = sample_data(df, params.get("n"), params.get("frac"), params.get("random_state"))
    engine.data_pool[node_id] = result
    engine.log(f"    - 抽样完成: {result.shape[0]} 行 (原始: {df.shape[0]} 行)")


def run_describe_data(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    engine.data_pool[node_id] = describe_data(df, params.get("percentiles"))


def run_transpose_data(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    result = transpose_data(df)
    engine.data_pool[node_id] = result
    engine.log(f"    - 转置完成: {result.shape[0]} 行 x {result.shape[1]} 列")


def run_cumsum_data(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    col_type = params.get("col_type", "col_name")
    engine.data_pool[node_id] = cumsum_data(df, params.get("col_list", []), col_type)


def run_pct_change_data(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    col_type = params.get("col_type", "col_name")
    engine.data_pool[node_id] = pct_change_data(
        df, params.get("col_list", []), params.get("periods", 1), col_type
    )


def run_export_df(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    default_run_dir = get_exec_dir()

    fname = params.get("file_name", "Export_Result.xlsx")
    fdir = params.get("folder_path", "").strip()
    target_path = str(default_run_dir / fname) if not fdir else str(Path(fdir) / fname)

    success, final_path = export_df(df, target_path, default_run_dir)
    if success:
        engine.log(f"    - [导出成功] 文件已保存至: {final_path}")
    else:
        engine.log(f"    - [路径修正] 原路径无法保存，已转存至: {final_path}")
    engine.data_pool[node_id] = df


def run_import_template(engine, params, node_id):
    template_path = params.get("template_path")
    if not template_path or not os.path.exists(template_path):
        raise ValueError(f"模板文件不存在: {template_path}")
    wb, meta = load_template(template_path)
    engine.data_pool[node_id] = {"_wb": wb, "_meta": meta}
    engine.log(
        f"    - 模板已加载: {os.path.basename(template_path)}"
        f" ({len(meta['sheet_names'])} 个工作表)"
    )


def run_insert_block(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    template_id = params.get("template_id")
    if not template_id or template_id not in engine.data_pool:
        raise ValueError(f"模板表未找到: {template_id}")

    tmpl_entry = engine.data_pool[template_id]
    wb = tmpl_entry.get("_wb")
    if wb is None:
        raise ValueError("模板数据无效，请检查上游导入模板节点")

    sheet_name = params.get("sheet_name", wb.sheetnames[0])
    start_row = params.get("start_row", "max_row + 1")
    start_col = params.get("start_col", "1")
    cols = params.get("col_list", ["*"])
    col_names = params.get("col_names", [])

    df_fill = df.copy()
    if col_names and any(col_names):
        actual_cols = [c for c in cols if c != "*"]
        available = [c for c in actual_cols if c in df.columns] if actual_cols else list(df.columns)
        rename_map = {}
        for i, col in enumerate(available):
            if i < len(col_names) and col_names[i]:
                rename_map[col] = col_names[i]
        if rename_map:
            df_fill = df_fill.rename(columns=rename_map)

    success, msg = insert_into_template(
        wb,
        df_fill,
        sheet_name,
        start_row,
        start_col,
        columns=cols,
        write_header=params.get("write_header", True),
        inherit_style=True,
    )
    if not success:
        raise ValueError(msg)

    engine.log(f"    - [插入成功] {msg}")
    # 模板对象需要继续向下游传递，因此输出仍是同一个模板 entry。
    engine.data_pool[node_id] = tmpl_entry


def run_template_export(engine, params, node_id):
    """Best-effort compatibility for historical template export nodes."""
    template_id = params.get("template_id") or params.get("df_id")
    if not template_id or template_id not in engine.data_pool:
        engine.log("    - [兼容] 未找到模板输出对象，跳过旧版模板导出节点")
        return

    tmpl_entry = engine.data_pool[template_id]
    wb = tmpl_entry.get("_wb") if isinstance(tmpl_entry, dict) else None
    if wb is None:
        engine.log("    - [兼容] 模板输出对象无效，跳过旧版模板导出节点")
        return

    output_path = params.get("output_path") or params.get("file_path") or params.get("save_path")
    if not output_path:
        engine.log("    - [兼容] 旧版模板导出节点未配置保存路径，已跳过")
        return

    _, final_path = save_template(wb, output_path)
    engine.log(f"    - [模板导出成功] 文件已保存至: {final_path}")
    engine.data_pool[node_id] = tmpl_entry


ACTION_HANDLERS = {
    "load_file": run_load_file,
    "get_col_data": run_get_col_data,
    "filter_data": run_filter_data,
    "group_calc": run_group_calc,
    "left_join": run_left_join,
    "rank_col": run_rank_col,
    "sort_data": run_sort_data,
    "calc_col": run_calc_col,
    "clean_data": run_clean_data,
    "pivot_table": run_pivot_table,
    "melt_table": run_melt_table,
    "concat_rows": run_concat_rows,
    "drop_duplicates": run_drop_duplicates,
    "sample_data": run_sample_data,
    "describe_data": run_describe_data,
    "transpose_data": run_transpose_data,
    "cumsum_data": run_cumsum_data,
    "pct_change_data": run_pct_change_data,
    "export_df": run_export_df,
    "import_template": run_import_template,
    "insert_block": run_insert_block,
    "template_export": run_template_export,
}


def run_action(engine, action, params, node_id):
    handler = ACTION_HANDLERS.get(action)
    if not handler:
        raise ValueError(f"未知算子 action: {action}")
    handler(engine, params, node_id)
