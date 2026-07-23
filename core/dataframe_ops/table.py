"""Table composition operators."""

import pandas as pd

from core.dataframe_ops.columns import flatten_dataframe_columns

from core.dataframe_ops.columns import normalize_columns


def _as_key_list(value):
    if isinstance(value, list):
        return [item for item in value if str(item or "").strip()]
    if isinstance(value, tuple):
        return [item for item in value if str(item or "").strip()]
    return [value] if str(value or "").strip() else []


def _unique_columns(columns):
    result = []
    for column in columns or []:
        if column not in result:
            result.append(column)
    return result


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
    df2_work = df2.copy() if mapping_dict else df2
    left_key_refs = _as_key_list(left_key)
    right_key_refs = _as_key_list(right_key)
    if not left_key_refs:
        raise ValueError("表连接需要左表匹配键")
    if not right_key_refs:
        raise ValueError("表连接需要右表匹配键")
    if len(left_key_refs) != len(right_key_refs):
        raise ValueError("左右表匹配键数量必须一致")
    left_keys = normalize_columns(df1, left_key_refs, key_type)
    right_keys = normalize_columns(df2_work, right_key_refs, key_type)
    get_col_list = normalize_columns(df2_work, get_col, key_type)
    if len(left_keys) != len(left_key_refs):
        raise ValueError(f"左表关联键不存在: {left_key}")
    if len(right_keys) != len(right_key_refs):
        raise ValueError(f"右表关联键不存在: {right_key}")
    if get_col and not get_col_list:
        raise ValueError(f"右表提取列不存在: {get_col}")

    actual_right_keys = list(right_keys)
    if mapping_dict:
        right_key_col = right_keys[0]
        tmp_col = f"__v_join_{right_key_col}__"
        df2_work[tmp_col] = df2_work[right_key_col].map(mapping_dict).fillna(df2_work[right_key_col])
        actual_right_keys[0] = tmp_col

    dup_suffix = "_dup_drop_me"
    right_merge_cols = _unique_columns(actual_right_keys + get_col_list)
    result = df1.merge(
        df2_work[right_merge_cols],
        left_on=left_keys,
        right_on=actual_right_keys,
        how="left",
        suffixes=("", dup_suffix),
    )

    cols_to_drop = [c for c in result.columns if str(c).endswith(dup_suffix)]
    if cols_to_drop:
        result = result.drop(columns=cols_to_drop)

    merge_key_drops = [
        right_col
        for left_col, right_col in zip(left_keys, actual_right_keys)
        if left_col != right_col and right_col in result.columns
    ]
    if merge_key_drops:
        result = result.drop(columns=_unique_columns(merge_key_drops))

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
    return flatten_dataframe_columns(result)


def transpose_data(df):
    """Transpose rows and columns."""
    transposed = df.T.reset_index()
    if transposed.empty:
        return flatten_dataframe_columns(transposed)

    header = transposed.iloc[0].tolist()
    result = transposed.iloc[1:].reset_index(drop=True)
    result.columns = header
    return flatten_dataframe_columns(result)
