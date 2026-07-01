"""Aggregation and reshape operators."""

import pandas as pd

from core.dataframe_ops.columns import flatten_dataframe_columns, normalize_columns


def group_calc(df, group_key, col_dict, col_type="col_name"):
    group_cols = normalize_columns(df, group_key, col_type)
    if not group_cols:
        raise ValueError(f"分组列未找到: {group_key}")

    mapped_agg_dict = {}
    for col, funcs in col_dict.items():
        real_cols = normalize_columns(df, [col], col_type)
        if not real_cols:
            raise ValueError(f"计算列未找到: (原输入: {col})")
        mapped_agg_dict[real_cols[0]] = funcs

    try:
        grouped = df.groupby(group_cols).agg(mapped_agg_dict).reset_index()
    except Exception as e:
        raise ValueError(f"聚合失败 (请检查是否对文本列求和): {str(e)}")

    if isinstance(grouped.columns, pd.MultiIndex):
        new_cols = [
            f"{col[0]}_{col[1]}" if col[1] else col[0] for col in grouped.columns
        ]
        grouped.columns = new_cols
    else:
        rename_mapping = {
            real_col: f"{real_col}_{funcs}"
            for real_col, funcs in mapped_agg_dict.items()
            if isinstance(funcs, str)
        }
        grouped = grouped.rename(columns=rename_mapping)

    return flatten_dataframe_columns(grouped)


def pivot_table(df, index_cols, columns_col, values_col, aggfunc="sum",
                fill_value=0, margins=True, col_type="col_name"):
    """Cross-tab style pivot aggregation."""
    idx = normalize_columns(df, index_cols, col_type)
    cols = normalize_columns(df, [columns_col], col_type)
    vals = normalize_columns(df, [values_col], col_type)
    if not idx:
        raise ValueError(f"行标签列未找到: {index_cols}")
    if not cols:
        raise ValueError(f"列标签列未找到: {columns_col}")
    if not vals:
        raise ValueError(f"值列未找到: {values_col}")

    result = pd.pivot_table(
        df, index=idx, columns=cols[0], values=vals[0],
        aggfunc=aggfunc, fill_value=fill_value, margins=margins,
        margins_name="总计" if margins else "",
    )
    return flatten_dataframe_columns(result.reset_index())


def melt_table(df, id_cols, value_cols, var_name="变量", value_name="值",
               col_type="col_name"):
    """Unpivot wide columns into long rows."""
    ids = normalize_columns(df, id_cols, col_type)
    vals = normalize_columns(df, value_cols, col_type)
    if not vals:
        raise ValueError(f"值列未找到: {value_cols}")
    if not ids:
        ids = [c for c in df.columns if c not in vals]
    result = pd.melt(df, id_vars=ids, value_vars=vals,
                     var_name=var_name, value_name=value_name)
    return flatten_dataframe_columns(result)


def describe_data(df, percentiles=None):
    """Descriptive statistics."""
    if percentiles is None:
        percentiles = [0.25, 0.5, 0.75]
    result = df.describe(percentiles=percentiles)
    return flatten_dataframe_columns(result.reset_index())
