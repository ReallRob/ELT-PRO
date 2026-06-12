import os
import re
import pandas as pd
from pathlib import Path
from datetime import date, datetime


# ==========================================
# 基础辅助函数
# ==========================================
def map_col(col_list):
    """将 Excel 列字母映射为列索引 (0-based)"""
    col_index_list = []
    for col in col_list:
        index = 0
        for char in str(col).upper():
            index = index * 26 + (ord(char) - 64)
        col_index_list.append(index - 1)
    return col_index_list


def normalize_columns(df, raw_cols, col_type):
    if not isinstance(raw_cols, list):
        raw_cols = [raw_cols]

    actual_cols = []
    if col_type == "col_name":
        actual_cols = [c for c in raw_cols if c in df.columns]
    elif col_type == "col_index":
        actual_cols = [df.columns[int(c)] for c in raw_cols if int(c) < len(df.columns)]
    elif col_type == "col_word":
        indices = map_col(raw_cols)
        actual_cols = [df.columns[i] for i in indices if i < len(df.columns)]
    else:
        raise ValueError("col_type must be col_name, col_index or col_word")

    return actual_cols


# ==========================================
# 业务处理算子函数
# ==========================================
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


def rank_col(
    df, col_list, rank_list, col_type="col_name", method="max", ascending=True
):
    df = df.copy()
    actual_cols = normalize_columns(df, col_list, col_type)
    rank_list = rank_list if isinstance(rank_list, list) else [rank_list]

    for i, col_name in enumerate(actual_cols):
        new_col_name = (
            rank_list[i] if i < len(rank_list) and rank_list[i] else f"{col_name}_rank"
        )
        try:
            df[new_col_name] = df[col_name].rank(method=method, ascending=ascending)
        except TypeError:
            temp_series = pd.to_numeric(df[col_name], errors="coerce")
            if temp_series.notna().any():
                df[new_col_name] = temp_series.rank(method=method, ascending=ascending)
            else:
                df[new_col_name] = (
                    df[col_name].astype(str).rank(method=method, ascending=ascending)
                )
    return df


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
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if (
        not allow_compact_numeric
        and re.fullmatch(r"[-+]?\d+(\.\d+)?", text)
        and not re.fullmatch(r"\d{8}|\d{14}", text)
    ):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed)


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

    col_dates = pd.to_datetime(series, errors="coerce")
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
        col_dates, _, is_datetime = _coerce_filter_datetime_series(
            series, sample_value
        )
        if is_datetime:
            date_masks = []
            for value in raw_values:
                target = _parse_filter_datetime(value)
                if target is not None:
                    date_masks.append(
                        _apply_filter_datetime_compare(col_dates, target, "==", value)
                    )
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
            mask = series.astype("string").fillna("").str.contains(
                str(val), na=False, regex=False
            )
        elif op == "not_contains":
            mask = ~series.astype("string").fillna("").str.contains(
                str(val), na=False, regex=False
            )
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
                    mask = _apply_filter_datetime_compare(
                        col_dates, target_date, op, val
                    )
                else:
                    mask = pd.Series(False, index=df.index)
            else:
                col_dates, target_date, is_datetime = _coerce_filter_datetime_series(
                    series, val, force=force_datetime
                )
                if is_datetime:
                    mask = _apply_filter_datetime_compare(
                        col_dates, target_date, op, val
                    )
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
        else:
            if logic == "AND":
                result_mask = result_mask & mask
            else:
                result_mask = result_mask | mask

    if result_mask is None:
        return df
    return df[result_mask].copy()


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

    return grouped


def sort_data(df, sort_rules, col_type="col_name"):
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
                return pd.Categorical(
                    series.astype(str), categories=categories, ordered=True
                )
            return series

        df = df.sort_values(
            by=sort_cols, ascending=asc_flags, na_position="last", key=sort_key_func
        )
    return df.reset_index(drop=True)


# ==========================================
# 基于正则的严格 AST 公式解析
# ==========================================
def calc_col(df, new_col_name, formula):
    """公式列计算。强制使用方括号 [列名] 标识变量，避免歧义。"""
    df = df.copy()
    if formula.startswith("="):
        formula = formula[1:]

    def replace_func(match):
        col_name = match.group(1).strip()
        if col_name not in df.columns:
            raise KeyError(f"数据表中不存在列: 【{col_name}】")
        return f"`{col_name}`"

    try:
        safe_formula = re.sub(r"\[([^\]]+)\]", replace_func, formula)
        if safe_formula == formula:
            raise SyntaxError(
                "公式中未检测到任何 [列名] 格式的列引用，请用中括号包裹列名，如：[销售额]*0.1"
            )
        df[new_col_name] = df.eval(safe_formula)
    except KeyError as ke:
        raise ke
    except SyntaxError as se:
        raise se
    except Exception as e:
        raise ValueError(
            f"公式计算失败：【{formula}】\n"
            f"可能原因：1) 列名未用[]包裹  2) 运算符非英文输入法  3) 语法错误\n"
            f"内部报错: {str(e)}"
        )

    return df


def clean_data(df, rules, col_type="col_name"):
    if not rules:
        return df.copy()
    df_cleaned = df.copy()
    for rule in rules:
        raw_cols = [c.strip() for c in rule.get("cols", "").split(",") if c.strip()]
        action = rule.get("action")
        fill_val = rule.get("fill_value")
        param2 = rule.get("param2", "")

        actual_cols = normalize_columns(df_cleaned, raw_cols, col_type)
        if not actual_cols:
            continue

        for col in actual_cols:
            if action == "to_numeric":
                df_cleaned[col] = pd.to_numeric(df_cleaned[col], errors="coerce")
            elif action == "to_string":
                df_cleaned[col] = df_cleaned[col].astype(str)
            elif action == "to_int":
                df_cleaned[col] = pd.to_numeric(df_cleaned[col], errors="coerce").astype("Int64")
            elif action == "to_float":
                df_cleaned[col] = pd.to_numeric(df_cleaned[col], errors="coerce").astype(float)
            elif action == "to_datetime":
                out_fmt = fill_val if fill_val else None
                result = pd.to_datetime(df_cleaned[col], errors="coerce")
                if out_fmt:
                    df_cleaned[col] = result.dt.strftime(out_fmt)
                else:
                    df_cleaned[col] = result.dt.normalize()
            elif action == "strip_space":
                mask = df_cleaned[col].notna()
                df_cleaned.loc[mask, col] = (
                    df_cleaned.loc[mask, col].astype(str).str.strip().values
                )
            elif action == "fill_na":
                if fill_val is not None and fill_val != "":
                    df_cleaned[col] = df_cleaned[col].fillna(fill_val)
            elif action == "drop_na":
                df_cleaned = df_cleaned.dropna(subset=[col])
            elif action == "replace":
                if fill_val and "→" in fill_val:
                    old, new = fill_val.split("→", 1)
                    df_cleaned[col] = df_cleaned[col].astype(str).str.replace(
                        old.strip(), new.strip(), regex=False
                    )
            elif action == "upper_case":
                mask = df_cleaned[col].notna()
                df_cleaned.loc[mask, col] = df_cleaned.loc[mask, col].astype(str).str.upper().values
            elif action == "lower_case":
                mask = df_cleaned[col].notna()
                df_cleaned.loc[mask, col] = df_cleaned.loc[mask, col].astype(str).str.lower().values
            elif action == "round_val":
                try:
                    decimals = int(fill_val) if fill_val and str(fill_val).isdigit() else 0
                except (ValueError, TypeError):
                    decimals = 0
                df_cleaned[col] = pd.to_numeric(df_cleaned[col], errors="coerce").round(decimals)
            elif action == "clip":
                if fill_val and str(fill_val).strip():
                    try:
                        parts = [x.strip() for x in str(fill_val).split(",")]
                        lo = float(parts[0]) if parts[0] else None
                        hi = float(parts[1]) if len(parts) > 1 and parts[1] else None
                        df_cleaned[col] = pd.to_numeric(df_cleaned[col], errors="coerce").clip(lo, hi)
                    except (ValueError, IndexError, TypeError):
                        pass
    return df_cleaned


def pivot_table(df, index_cols, columns_col, values_col, aggfunc="sum",
                fill_value=0, margins=True, col_type="col_name"):
    """数据透视：横向展开交叉汇总"""
    df = df.copy()
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
    return result.reset_index()


def melt_table(df, id_cols, value_cols, var_name="变量", value_name="值",
               col_type="col_name"):
    """逆透视：宽表→长表，把多列融合成多行"""
    df = df.copy()
    ids = normalize_columns(df, id_cols, col_type)
    vals = normalize_columns(df, value_cols, col_type)
    if not vals:
        raise ValueError(f"值列未找到: {value_cols}")
    # 如果没有指定 id 列，使用未被选中的列
    if not ids:
        ids = [c for c in df.columns if c not in vals]
    result = pd.melt(df, id_vars=ids, value_vars=vals,
                     var_name=var_name, value_name=value_name)
    return result


def concat_rows(df1, df2, ignore_index=True):
    """纵向拼接：两个表上下接起来"""
    result = pd.concat([df1, df2], axis=0, ignore_index=ignore_index)
    return result


def drop_duplicates(df, subset_cols, keep="first", col_type="col_name"):
    """去重：删除重复行"""
    if not subset_cols:
        result = df.drop_duplicates(keep=keep)
    else:
        actual = normalize_columns(df, subset_cols, col_type)
        if not actual:
            raise ValueError(f"去重列未找到: {subset_cols}")
        result = df.drop_duplicates(subset=actual, keep=keep)
    return result.reset_index(drop=True)


def sample_data(df, n=None, frac=None, random_state=None):
    """随机抽样"""
    if frac is not None:
        return df.sample(frac=frac, random_state=random_state).reset_index(drop=True)
    if n is not None and n > 0:
        return df.sample(n=min(n, len(df)), random_state=random_state).reset_index(drop=True)
    return df


def describe_data(df, percentiles=None):
    """描述统计：均值/标准差/最大最小等"""
    if percentiles is None:
        percentiles = [0.25, 0.5, 0.75]
    result = df.describe(percentiles=percentiles)
    return result.reset_index()


def transpose_data(df):
    """转置：行列互换"""
    result = df.T.reset_index()
    result.columns = [f"列{i+1}" if str(c).startswith("列") else str(c) for i, c in enumerate(result.columns)]
    return result


def cumsum_data(df, col_list, col_type="col_name"):
    """累加计算：对指定列计算累计值"""
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
    """环比计算：对指定列计算变化率"""
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


def export_df(df, target_path, default_dir):
    save_p = Path(target_path)
    actual_path = target_path
    success = False
    try:
        if save_p.parent.exists():
            if str(target_path).lower().endswith(".csv"):
                df.to_csv(target_path, index=False, encoding="utf-8-sig")
            else:
                df.to_excel(target_path, index=False)
            success = True
        else:
            success = False
    except Exception as e:
        success = False

    if not success:
        fname = save_p.name if save_p.name else "自动导出结果.xlsx"
        if not fname.endswith((".xlsx", ".csv")):
            fname += ".xlsx"
        fallback_path = Path(default_dir) / fname

        if str(fallback_path).lower().endswith(".csv"):
            df.to_csv(fallback_path, index=False, encoding="utf-8-sig")
        else:
            df.to_excel(fallback_path, index=False)
        actual_path = str(fallback_path)

    return success, actual_path
