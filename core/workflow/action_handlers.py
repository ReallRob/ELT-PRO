"""Action handlers used by the workflow engine.

Each handler receives the engine instance, the resolved parameter dict, and the
current node id. The engine keeps ownership of shared state such as the data
pool and logging signals; handlers only implement one operator's business work.
"""

import os
from pathlib import Path

from core.app_paths import get_exec_dir
from template_engine import (
    build_template_metadata,
    insert_into_template,
    load_template,
    save_template,
)
from core.dataframe_ops import (
    calc_code,
    calc_col,
    code_block,
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

PARAMETER_ACTIONS = {"advanced_param_mapping"}
TEMPLATE_ACTIONS = {"import_template", "insert_block"}


def collect_action_dependencies(action, params):
    """Return upstream node ids consumed by an action.

    The engine uses this for reference counting and memory release. Keeping the
    rules here prevents dependency logic and handler dispatch from drifting.
    """
    if action == "import_template":
        return [d for d in params.get("insert_block_ids", []) if d]
    if action == "insert_block":
        return [d for d in [params.get("df_id"), params.get("template_id")] if d]
    if action == "code_block":
        return [
            item.get("df_id")
            for item in params.get("input_bindings", [])
            if isinstance(item, dict) and item.get("df_id")
        ]
    if action in ("left_join", "concat_rows"):
        return [params.get("df1_id"), params.get("df2_id")]
    if "df_id" in params:
        return [params.get("df_id")]
    return []


def should_log_dataframe_shape(action):
    return action not in TEMPLATE_ACTIONS and action not in PARAMETER_ACTIONS


def should_publish_output(action):
    return (
        action == "import_template"
        or (action not in TEMPLATE_ACTIONS and action not in PARAMETER_ACTIONS)
    )


def handle_parameter_action(engine, action, params):
    """Log parameter-only actions; they update runtime metadata before execution."""
    if action == "advanced_param_mapping":
        config = params.get("rule_engine_config", {})
        param_count = len(config.get("parameters", []))
        rule_count = len(config.get("rules", []))
        engine.log(f"    - 已加载参数输入: {param_count} 个参数，{rule_count} 条规则")
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
        if rule.get("mode") == "code":
            df = calc_code(
                df,
                rule.get("code", rule.get("formula", "")),
                rule.get("new_col_name", ""),
                getattr(engine, "runtime_parameters", {}),
                getattr(engine, "parameter_mappings", {}),
                rule.get("timeout_seconds", 10),
            )
        else:
            df = calc_col(df, rule["new_col_name"], rule["formula"])
    engine.data_pool[node_id] = df


def run_code_block(engine, params, node_id):
    bindings = params.get("input_bindings") or []
    if not bindings:
        raise ValueError("代码块至少需要连接一个输入表")
    tables = {}
    for i, binding in enumerate(bindings):
        if not isinstance(binding, dict):
            continue
        df_id = binding.get("df_id")
        alias = str(binding.get("alias") or ("df" if i == 0 else f"df{i}")).strip()
        if not df_id:
            raise ValueError(f"代码块输入缺少上游节点 ID: {binding.get('table_name', '')}")
        if alias in tables:
            raise ValueError(f"代码块输入变量名重复: {alias}")
        tables[alias] = engine.get_df(df_id)
    if "df" not in tables and tables:
        first_alias = next(iter(tables))
        tables["df"] = tables[first_alias]
    engine.data_pool[node_id] = code_block(
        tables,
        params.get("code", ""),
        getattr(engine, "runtime_parameters", {}),
        getattr(engine, "parameter_mappings", {}),
        params.get("timeout_seconds", 10),
    )


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


def _safe_template_output_name(name):
    text = str(name or "").strip() or "result"
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text


def _resolve_template_output_path(params, template_path, has_insert_blocks=False):
    explicit_path = params.get("output_path")
    if explicit_path:
        return explicit_path
    if not has_insert_blocks:
        return ""

    stem = Path(template_path).stem if template_path else "template"
    out_name = _safe_template_output_name(params.get("out_name") or stem)
    return str(get_exec_dir() / f"template_filled_{out_name}.xlsx")


def _prepare_insert_dataframe(df, params):
    cols = params.get("col_list") or ["*"]
    col_names = params.get("col_names") or []

    if cols == "*" or cols == ["*"]:
        fill_df = df.copy()
    else:
        available = normalize_columns(df, cols, "col_name")
        if not available:
            raise ValueError(f"指定列在 DataFrame 中不存在: {cols}")
        fill_df = df[available].copy()

    rename_map = {}
    if col_names and any(col_names):
        for i, col in enumerate(fill_df.columns):
            if i < len(col_names) and col_names[i]:
                rename_map[col] = col_names[i]
    if rename_map:
        fill_df = fill_df.rename(columns=rename_map)

    return fill_df


def _build_insert_block_payload(engine, params, node_id):
    df = engine.get_df(params.get("df_id"))
    fill_df = _prepare_insert_dataframe(df, params)
    return {
        "_template_insert": True,
        "node_id": node_id,
        "df": fill_df,
        "sheet_name": params.get("sheet_name") or "",
        "start_row": params.get("start_row") or "max_row + 1",
        "end_row": params.get("end_row") or "",
        "start_col": params.get("start_col") or "1",
        "end_col": params.get("end_col") or "",
        "write_header": params.get("write_header", True),
    }


def _apply_insert_payload(wb, payload):
    sheet_name = payload.get("sheet_name") or wb.sheetnames[0]
    success, msg = insert_into_template(
        wb,
        payload["df"],
        sheet_name,
        payload.get("start_row") or "max_row + 1",
        payload.get("start_col") or "1",
        columns=["*"],
        write_header=payload.get("write_header", True),
        inherit_style=False,
        end_row_expr=payload.get("end_row") or None,
        end_col_expr=payload.get("end_col") or None,
    )
    if not success:
        raise ValueError(msg)
    return msg


def run_import_template(engine, params, node_id):
    template_path = params.get("template_path")
    actual_path = engine.file_mapping.get(template_path, template_path)
    if not actual_path or not os.path.exists(actual_path):
        raise ValueError(f"模板文件不存在: {actual_path}")

    wb, meta = load_template(actual_path)
    insert_block_ids = params.get("insert_block_ids", []) or []
    engine.log(
        f"    - 模板已加载: {os.path.basename(actual_path)}"
        f" ({len(meta['sheet_names'])} 个工作表)"
    )

    for index, insert_id in enumerate(insert_block_ids, start=1):
        payload = engine.data_pool.get(insert_id)
        if not isinstance(payload, dict) or not payload.get("_template_insert"):
            raise ValueError(f"插入模板节点输出无效: {insert_id}")
        msg = _apply_insert_payload(wb, payload)
        engine.log(f"    - [区域 {index}] {msg}")

    meta = build_template_metadata(wb, actual_path)
    tmpl_entry = {"_wb": wb, "_meta": meta, "_template_path": actual_path}

    output_path = _resolve_template_output_path(
        params, actual_path, has_insert_blocks=bool(insert_block_ids)
    )
    if output_path:
        _, final_path = save_template(wb, output_path)
        tmpl_entry["_saved_path"] = final_path
        engine.log(f"    - [模板保存成功] 文件已保存至: {final_path}")

    engine.data_pool[node_id] = tmpl_entry


def run_insert_block(engine, params, node_id):
    payload = _build_insert_block_payload(engine, params, node_id)
    template_id = params.get("template_id")

    if template_id:
        if template_id not in engine.data_pool:
            raise ValueError(f"模板表未找到: {template_id}")
        tmpl_entry = engine.data_pool[template_id]
        wb = tmpl_entry.get("_wb") if isinstance(tmpl_entry, dict) else None
        if wb is None:
            raise ValueError("模板数据无效，请检查上游导入模板节点")
        msg = _apply_insert_payload(wb, payload)
        engine.log(f"    - [插入成功] {msg}")
        engine.data_pool[node_id] = tmpl_entry
        return

    engine.data_pool[node_id] = payload
    engine.log(
        "    - 已准备模板写入区域: "
        f"{payload.get('sheet_name') or '首个工作表'} "
        f"行{payload.get('start_row')}:{payload.get('end_row') or '*'} "
        f"列{payload.get('start_col')}:{payload.get('end_col') or '*'}"
    )


ACTION_HANDLERS = {
    "load_file": run_load_file,
    "get_col_data": run_get_col_data,
    "filter_data": run_filter_data,
    "group_calc": run_group_calc,
    "left_join": run_left_join,
    "rank_col": run_rank_col,
    "sort_data": run_sort_data,
    "calc_col": run_calc_col,
    "code_block": run_code_block,
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
}


def run_action(engine, action, params, node_id):
    handler = ACTION_HANDLERS.get(action)
    if not handler:
        raise ValueError(f"未知算子 action: {action}")
    handler(engine, params, node_id)
