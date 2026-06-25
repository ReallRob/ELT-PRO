"""Calculated-column operators."""

import re

import pandas as pd

from core.dataframe_ops.code_exec import (
    DEFAULT_CODE_TIMEOUT_SECONDS,
    coerce_timeout_seconds,
    run_dataframe_code,
)
from core.dataframe_ops.columns import (
    _UNRESOLVED,
    flatten_dataframe_columns,
    normalize_columns,
    resolve_column,
    stringify_column_name,
)


def rank_col(df, col_list, rank_list, col_type="col_name", method="max", ascending=True):
    df = df.copy()
    actual_cols = normalize_columns(df, col_list, col_type)
    rank_list = rank_list if isinstance(rank_list, list) else [rank_list]

    for i, col_name in enumerate(actual_cols):
        new_col_name = rank_list[i] if i < len(rank_list) and rank_list[i] else f"{col_name}_rank"
        try:
            df[new_col_name] = df[col_name].rank(method=method, ascending=ascending)
        except TypeError:
            temp_series = pd.to_numeric(df[col_name], errors="coerce")
            if temp_series.notna().any():
                df[new_col_name] = temp_series.rank(method=method, ascending=ascending)
            else:
                df[new_col_name] = df[col_name].astype(str).rank(method=method, ascending=ascending)
    return df


def calc_col(df, new_col_name, formula):
    """Formula calculation using [column name] references."""
    df = df.copy()
    eval_df = flatten_dataframe_columns(df)
    if formula.startswith("="):
        formula = formula[1:]

    def replace_func(match):
        col_name = match.group(1).strip()
        actual_col = resolve_column(df, col_name)
        if actual_col is _UNRESOLVED:
            raise KeyError(f"数据表中不存在列: 【{col_name}】")
        flat_col = stringify_column_name(actual_col).strip()
        if flat_col not in eval_df.columns:
            raise KeyError(f"数据表中不存在列: 【{col_name}】")
        return f"`{flat_col}`"

    try:
        safe_formula = re.sub(r"\[([^\]]+)\]", replace_func, formula)
        if safe_formula == formula:
            raise SyntaxError(
                "公式中未检测到任何 [列名] 格式的列引用，请用中括号包裹列名，如：[销售额]*0.1"
            )
        df[new_col_name] = eval_df.eval(safe_formula)
    except KeyError as ke:
        raise ke
    except SyntaxError as se:
        raise se
    except Exception as e:
        raise ValueError(
            f"公式计算失败：【{formula}】\n"
            f"可能原因：1) 列名未用[]包裹  2) 运算符非英文输入法  3) 语法错误  4) 字段类型不支持该运算，请先使用数据清洗/类型转换处理\n"
            f"内部报错: {str(e)}"
        )

    return df


def calc_code(
    df,
    code,
    new_col_name="",
    runtime_parameters=None,
    parameter_mappings=None,
    timeout_seconds=DEFAULT_CODE_TIMEOUT_SECONDS,
):
    """Run explicit pandas code with df as the current table, with timeout protection."""
    return run_dataframe_code(
        {"df": df},
        code,
        runtime_parameters=runtime_parameters,
        parameter_mappings=parameter_mappings,
        timeout_seconds=coerce_timeout_seconds(timeout_seconds),
        result_name="",
        fallback_alias="df",
        target_col=new_col_name,
        error_prefix="代码计算",
    )


def cumsum_data(df, col_list, col_type="col_name"):
    """Calculate cumulative sum for selected columns."""
    df = df.copy()
    if not col_list:
        raise ValueError("请指定累加列")
    actual = normalize_columns(df, col_list, col_type)
    if not actual:
        raise ValueError(f"累加列未找到: {col_list}")
    for col in actual:
        df[f"{col}_累加"] = pd.to_numeric(df[col], errors="coerce").cumsum()
    return df


def pct_change_data(df, col_list, periods=1, col_type="col_name"):
    """Calculate percentage change for selected columns."""
    df = df.copy()
    if not col_list:
        raise ValueError("请指定环比列")
    actual = normalize_columns(df, col_list, col_type)
    if not actual:
        raise ValueError(f"环比列未找到: {col_list}")
    for col in actual:
        suffix = f"环比({periods}期)" if periods != 1 else "环比"
        df[f"{col}_{suffix}"] = pd.to_numeric(df[col], errors="coerce").pct_change(periods=periods)
    return df
