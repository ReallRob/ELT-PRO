"""Column selection operators."""

import pandas as pd

from core.dataframe_ops.columns import normalize_columns


def get_col_data(df, col_list, col_type="col_name", fill_value=None, col_names=None):
    actual_cols = normalize_columns(df, col_list, col_type)
    if not actual_cols:
        raise ValueError("找不到指定的列，请检查输入！")
    result = df[actual_cols].copy()
    if fill_value is not None:
        result = result.fillna(fill_value)
    if col_names is not None:
        col_names = col_names if isinstance(col_names, list) else [col_names]
        result.columns = col_names[: len(actual_cols)]
    return result


def sort_data(df, sort_rules, col_type="col_name"):
    """Sort rows by one or more columns, with optional custom order lists."""
    if not sort_rules:
        return df.copy()
    sort_cols = []
    asc_flags = []
    custom_orders_map = {}

    for rule in sort_rules:
        actual_cols = normalize_columns(df, [rule["col"]], col_type)
        if not actual_cols:
            raise ValueError(f"找不到排序指定的列: (原输入: {rule['col']})")
        col_name = actual_cols[0]

        custom_order = rule.get("custom_order", [])
        if custom_order:
            custom_order = [str(x).strip() for x in custom_order if str(x).strip()]
            if custom_order:
                custom_orders_map[col_name] = custom_order

        sort_cols.append(col_name)
        asc_flags.append(rule.get("ascending", True))

    if sort_cols:
        def sort_key_func(series):
            if series.name in custom_orders_map:
                categories = custom_orders_map[series.name]
                return pd.Categorical(series.astype(str), categories=categories, ordered=True)
            return series

        df = df.sort_values(
            by=sort_cols, ascending=asc_flags, na_position="last", key=sort_key_func
        )
    return df.reset_index(drop=True)
