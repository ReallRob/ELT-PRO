"""Filtering operators with type-aware comparisons."""

import re
from datetime import date, datetime

import pandas as pd

from core.dataframe_ops.columns import normalize_columns
from core.dataframe_ops.dates import parse_datetime_series, parse_datetime_value

_FILTER_DATE_OPS = {
    "date_=": "==",
    "date_!=": "!=",
    "date_>": ">",
    "date_<": "<",
    "date_>=": ">=",
    "date_<=": "<=",
}
_FILTER_COMPARE_OPS = {">", "<", ">=", "<=", "==", "!="}
_BOOL_TRUE_VALUES = {"true", "1", "yes", "y", "是", "对", "真"}
_BOOL_FALSE_VALUES = {"false", "0", "no", "n", "否", "错", "假"}


def _filter_non_blank_mask(series):
    text = series.astype("string").str.strip()
    return series.notna() & text.ne("")


def _parse_filter_number(value):
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    is_percent = text.endswith("%")
    if is_percent:
        text = text[:-1].strip()
    text = text.replace(",", "")
    try:
        num = float(text)
    except (TypeError, ValueError):
        return None
    return num / 100 if is_percent else num


def _coerce_filter_numeric_series(series):
    if pd.api.types.is_bool_dtype(series):
        return pd.to_numeric(series, errors="coerce"), 0.0, False

    if pd.api.types.is_numeric_dtype(series):
        nums = pd.to_numeric(series, errors="coerce")
        return nums, 1.0, True

    text = series.astype("string").str.strip()
    percent_mask = text.str.endswith("%", na=False)
    numeric_text = text.str.rstrip("%").str.replace(",", "", regex=False)
    nums = pd.to_numeric(numeric_text, errors="coerce")
    nums.loc[percent_mask] = nums.loc[percent_mask] / 100

    non_blank = _filter_non_blank_mask(series)
    if not non_blank.any():
        return nums, 0.0, False
    ratio = nums.loc[non_blank].notna().mean()
    return nums, ratio, ratio >= 0.7


def _parse_filter_bool(value):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _BOOL_TRUE_VALUES:
        return True
    if text in _BOOL_FALSE_VALUES:
        return False
    return None


def _coerce_filter_bool_series(series):
    if pd.api.types.is_bool_dtype(series):
        return series.astype("boolean"), True

    text = series.astype("string").str.strip().str.lower()
    mapped = text.map({
        **{v: True for v in _BOOL_TRUE_VALUES},
        **{v: False for v in _BOOL_FALSE_VALUES},
    })
    non_blank = _filter_non_blank_mask(series)
    if not non_blank.any():
        return mapped.astype("boolean"), False
    return mapped.astype("boolean"), mapped.loc[non_blank].notna().mean() >= 0.7


def _value_looks_like_date(value):
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return True
    text = str(value).strip()
    if not text:
        return False
    if re.fullmatch(r"[-+]?\d+(\.\d+)?", text):
        return bool(re.fullmatch(r"\d{8}|\d{14}", text))
    return bool(
        re.search(r"\d{4}\s*[-/.年]\s*\d{1,2}", text)
        or re.search(r"\d{1,2}\s*[-/.月]\s*\d{1,2}\s*[-/.月]\s*\d{2,4}", text)
    )


def _parse_filter_datetime(value, allow_compact_numeric=False):
    return parse_datetime_value(value, allow_compact_numeric=allow_compact_numeric)


def _coerce_filter_datetime_series(series, value, force=False):
    is_datetime_col = pd.api.types.is_datetime64_any_dtype(series)
    if (
        pd.api.types.is_numeric_dtype(series)
        and not pd.api.types.is_bool_dtype(series)
        and not force
        and not is_datetime_col
    ):
        return None, None, False
    if not (force or is_datetime_col or _value_looks_like_date(value)):
        return None, None, False

    target = _parse_filter_datetime(
        value,
        allow_compact_numeric=force or is_datetime_col,
    )
    if target is None:
        return None, None, False

    col_dates = parse_datetime_series(series)
    if is_datetime_col:
        return col_dates, target, True

    non_blank = _filter_non_blank_mask(series)
    if not non_blank.any():
        return col_dates, target, False
    return col_dates, target, col_dates.loc[non_blank].notna().mean() >= 0.6


def _filter_value_is_date_only(value):
    if isinstance(value, datetime):
        return (
            value.hour == 0
            and value.minute == 0
            and value.second == 0
            and value.microsecond == 0
        )
    if isinstance(value, date) and not isinstance(value, datetime):
        return True
    text = str(value).strip()
    return not bool(re.search(r"(\d{1,2}:\d{2})|T\d{1,2}", text))


def _apply_filter_compare(left, right, op):
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    return pd.Series(True, index=left.index)


def _apply_filter_datetime_compare(col_dates, target_date, op, raw_value):
    if _filter_value_is_date_only(raw_value):
        start = target_date.normalize()
        end = start + pd.Timedelta(days=1)
        if op == "==":
            return (col_dates >= start) & (col_dates < end)
        if op == "!=":
            return (col_dates < start) | (col_dates >= end)
        if op == ">":
            return col_dates >= end
        if op == "<":
            return col_dates < start
        if op == ">=":
            return col_dates >= start
        if op == "<=":
            return col_dates < end
    return _apply_filter_compare(col_dates, target_date, op)


def _apply_filter_string_compare(series, value, op):
    text = series.astype("string").fillna("")
    target = "" if value is None else str(value)
    return _apply_filter_compare(text, target, op)


def _is_filter_list_value(value):
    return isinstance(value, (list, tuple, set, pd.Index, pd.Series))


def _apply_filter_membership(series, values, op):
    raw_values = list(values)
    if len(raw_values) == 0:
        mask = pd.Series(False, index=series.index)
    else:
        sample_value = next((v for v in raw_values if v not in ("", None)), None)
        col_dates, _, is_datetime = _coerce_filter_datetime_series(series, sample_value)
        if is_datetime:
            date_masks = []
            for value in raw_values:
                target = _parse_filter_datetime(value)
                if target is not None:
                    date_masks.append(_apply_filter_datetime_compare(col_dates, target, "==", value))
            mask = (
                pd.concat(date_masks, axis=1).any(axis=1)
                if date_masks
                else pd.Series(False, index=series.index)
            )
        else:
            numeric_values = [
                num for num in (_parse_filter_number(v) for v in raw_values)
                if num is not None
            ]
            col_nums, numeric_ratio, is_numeric = _coerce_filter_numeric_series(series)
            if numeric_values and (is_numeric or numeric_ratio >= 0.7):
                mask = col_nums.isin(numeric_values)
            else:
                value_set = {str(v) for v in raw_values}
                mask = series.astype("string").fillna("").isin(value_set)

    if op == "!=":
        mask = ~mask
    return mask


def filter_data(df, conditions, logic="AND", col_type="col_name"):
    if not conditions:
        return df.copy()
    result_mask = None

    for cond in conditions:
        op, val = cond["op"], cond.get("value", "")
        force_datetime = False
        if op in _FILTER_DATE_OPS:
            op = _FILTER_DATE_OPS[op]
            force_datetime = True

        actual_cols = normalize_columns(df, [cond["col"]], col_type)
        if not actual_cols:
            raise ValueError(f"找不到列: (原输入: {cond['col']})")
        col_name = actual_cols[0]
        series = df[col_name]

        if op == "isnull":
            mask = series.isna() | series.astype("string").str.strip().eq("").fillna(False)
        elif op == "notnull":
            mask = series.notna() & series.astype("string").str.strip().ne("").fillna(False)
        elif op == "contains":
            mask = series.astype("string").fillna("").str.contains(str(val), na=False, regex=False)
        elif op == "not_contains":
            mask = ~series.astype("string").fillna("").str.contains(str(val), na=False, regex=False)
        elif op == "startswith":
            mask = series.astype("string").fillna("").str.startswith(str(val), na=False)
        elif op == "endswith":
            mask = series.astype("string").fillna("").str.endswith(str(val), na=False)
        elif op in _FILTER_COMPARE_OPS:
            if op in ("==", "!=") and _is_filter_list_value(val):
                mask = _apply_filter_membership(series, val, op)
            elif force_datetime or pd.api.types.is_datetime64_any_dtype(series):
                col_dates, target_date, is_datetime = _coerce_filter_datetime_series(
                    series, val, force=force_datetime
                )
                if is_datetime:
                    mask = _apply_filter_datetime_compare(col_dates, target_date, op, val)
                else:
                    mask = pd.Series(False, index=df.index)
            else:
                col_dates, target_date, is_datetime = _coerce_filter_datetime_series(
                    series, val, force=force_datetime
                )
                if is_datetime:
                    mask = _apply_filter_datetime_compare(col_dates, target_date, op, val)
                else:
                    bool_val = _parse_filter_bool(val)
                    bool_series, is_bool = _coerce_filter_bool_series(series)
                    if op in ("==", "!=") and is_bool and bool_val is not None:
                        mask = bool_series == bool_val
                        if op == "!=":
                            mask = ~mask
                    else:
                        val_num = _parse_filter_number(val)
                        col_nums, numeric_ratio, is_numeric = _coerce_filter_numeric_series(series)
                        use_numeric = (
                            val_num is not None
                            and (
                                is_numeric
                                or op in (">", "<", ">=", "<=")
                                or numeric_ratio >= 0.7
                            )
                        )
                        if use_numeric:
                            mask = _apply_filter_compare(col_nums, val_num, op)
                        elif (
                            op in (">", "<", ">=", "<=")
                            and pd.api.types.is_numeric_dtype(series)
                            and not pd.api.types.is_bool_dtype(series)
                        ):
                            mask = pd.Series(False, index=df.index)
                        else:
                            mask = _apply_filter_string_compare(series, val, op)
        else:
            mask = pd.Series(True, index=df.index)

        mask = pd.Series(mask, index=df.index).fillna(False).astype(bool)

        if result_mask is None:
            result_mask = mask
        elif logic == "AND":
            result_mask = result_mask & mask
        else:
            result_mask = result_mask | mask

    if result_mask is None:
        return df
    return df[result_mask].copy()
