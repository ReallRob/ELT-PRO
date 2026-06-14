"""Table composition operators."""

import pandas as pd

from core.dataframe_ops.columns import normalize_columns


def left_join(
    df1,
    df2,
    left_key,
    right_key,
    get_col,
    key_type="col_name",
    fill_value=None,
    col_names=None,
    mapping_dict=None,
):
    df1 = df1.copy()
    left_key_col = normalize_columns(df1, [left_key], key_type)[0]
    right_key_col = normalize_columns(df2, [right_key], key_type)[0]
    get_col_list = normalize_columns(df2, get_col, key_type)

    actual_right_key = right_key_col
    if mapping_dict:
        tmp_col = f"__v_join_{right_key_col}__"
        df2[tmp_col] = df2[right_key_col].map(mapping_dict).fillna(df2[right_key_col])
        actual_right_key = tmp_col

    dup_suffix = "_dup_drop_me"
    result = df1.merge(
        df2[[actual_right_key] + get_col_list],
        left_on=left_key_col,
        right_on=actual_right_key,
        how="left",
        suffixes=("", dup_suffix),
    )

    cols_to_drop = [c for c in result.columns if str(c).endswith(dup_suffix)]
    if cols_to_drop:
        result = result.drop(columns=cols_to_drop)

    if left_key_col != actual_right_key and actual_right_key in result.columns:
        result = result.drop(columns=[actual_right_key])

    if fill_value is not None:
        existing_cols = [col for col in get_col_list if col in result.columns]
        if existing_cols:
            result[existing_cols] = result[existing_cols].fillna(fill_value)

    if col_names is not None:
        col_names = col_names if isinstance(col_names, list) else [col_names]
        rename_dict = {
            old: new
            for old, new in zip(get_col_list, col_names)
            if old in result.columns
        }
        result = result.rename(columns=rename_dict)

    return result


def concat_rows(df1, df2, ignore_index=True):
    """Append two tables vertically."""
    result = pd.concat([df1, df2], axis=0, ignore_index=ignore_index)
    return result


def transpose_data(df):
    """Transpose rows and columns."""
    result = df.T.reset_index()
    result.columns = [
        f"列{i + 1}" if str(c).startswith("列") else str(c)
        for i, c in enumerate(result.columns)
    ]
    return result
