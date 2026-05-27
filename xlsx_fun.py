import os
import re
import pandas as pd
from pathlib import Path


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
    df2 = df2.copy()
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


def filter_data(df, conditions, logic="AND", col_type="col_name"):
    if not conditions:
        return df.copy()
    df_filtered = df.copy()
    result_mask = None

    for cond in conditions:
        op, val = cond["op"], cond["value"]
        actual_cols = normalize_columns(df_filtered, [cond["col"]], col_type)
        if not actual_cols:
            raise ValueError(f"找不到列: (原输入: {cond['col']})")
        col_name = actual_cols[0]

        mask = None
        if op.startswith("date_"):
            try:
                target_date = pd.to_datetime(val)
                col_dates = pd.to_datetime(df_filtered[col_name], errors="coerce")
                if op == "date_=":
                    mask = col_dates == target_date
                elif op == "date_!=":
                    mask = col_dates != target_date
                elif op == "date_>":
                    mask = col_dates > target_date
                elif op == "date_<":
                    mask = col_dates < target_date
                elif op == "date_>=":
                    mask = col_dates >= target_date
                elif op == "date_<=":
                    mask = col_dates <= target_date
            except Exception:
                mask = pd.Series(False, index=df_filtered.index)
        else:
            is_numeric = False
            val_num = 0
            if op in [">", "<", ">=", "<=", "==", "!="]:
                try:
                    val_num = float(val)
                    is_numeric = True
                except (ValueError, TypeError):
                    is_numeric = False

            if op == "==":
                mask = (
                    (df_filtered[col_name] == val_num)
                    | (df_filtered[col_name].astype(str) == str(val))
                    if is_numeric
                    else df_filtered[col_name].astype(str) == str(val)
                )
            elif op == "!=":
                mask = (
                    (df_filtered[col_name] != val_num)
                    & (df_filtered[col_name].astype(str) != str(val))
                    if is_numeric
                    else df_filtered[col_name].astype(str) != str(val)
                )
            elif op == ">":
                mask = pd.to_numeric(df_filtered[col_name], errors="coerce") > val_num
            elif op == "<":
                mask = pd.to_numeric(df_filtered[col_name], errors="coerce") < val_num
            elif op == ">=":
                mask = pd.to_numeric(df_filtered[col_name], errors="coerce") >= val_num
            elif op == "<=":
                mask = pd.to_numeric(df_filtered[col_name], errors="coerce") <= val_num
            elif op == "contains":
                mask = (
                    df_filtered[col_name]
                    .astype(str)
                    .str.contains(str(val), na=False, regex=False)
                )
            elif op == "not_contains":
                mask = (
                    ~df_filtered[col_name]
                    .astype(str)
                    .str.contains(str(val), na=False, regex=False)
                )
            elif op == "startswith":
                mask = (
                    df_filtered[col_name].astype(str).str.startswith(str(val), na=False)
                )
            elif op == "endswith":
                mask = (
                    df_filtered[col_name].astype(str).str.endswith(str(val), na=False)
                )
            elif op == "isnull":
                mask = df_filtered[col_name].isna()
            elif op == "notnull":
                mask = df_filtered[col_name].notna()
            else:
                mask = pd.Series(True, index=df_filtered.index)

        if result_mask is None:
            result_mask = mask
        else:
            if logic == "AND":
                result_mask = result_mask & mask
            else:
                result_mask = result_mask | mask

    if result_mask is None:
        return df_filtered
    return df_filtered[result_mask].copy()


def group_calc(df, group_key, col_dict, col_type="col_name"):
    df = df.copy()
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
    df_sorted = df.copy()
    sort_cols = []
    asc_flags = []
    custom_orders_map = {}

    for rule in sort_rules:
        actual_cols = normalize_columns(df_sorted, [rule["col"]], col_type)
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

        df_sorted = df_sorted.sort_values(
            by=sort_cols, ascending=asc_flags, na_position="last", key=sort_key_func
        )
    return df_sorted.reset_index(drop=True)


# ==========================================
# 基于正则的严格 AST 公式解析
# ==========================================
def calc_col(df, new_col_name, formula):
    """
    智能公式列计算。强制使用方括号标识变量 [列名]，杜绝长短字符串替换导致的脏数据。
    """
    df = df.copy()
    if formula.startswith("="):
        formula = formula[1:]

    try:
        df[new_col_name] = df.eval(formula)
    except Exception:
        try:
            # 严格正则匹配被 [ ] 包裹的变量名
            def replace_func(match):
                col_name = match.group(1).strip()
                if col_name not in df.columns:
                    raise ValueError(f"数据表中不存在列: 【{col_name}】")
                # 转义为 Pandas Eval 能安全识别的格式
                return f"`{col_name}`"

            # 将 "[销售额] * [提成]" 转换为 "`销售额` * `提成`"
            safe_formula = re.sub(r"\[([^\]]+)\]", replace_func, formula)
            df[new_col_name] = df.eval(safe_formula)

        except ValueError as ve:
            # 捕获列名不存在异常
            raise ve
        except Exception as e:
            raise ValueError(
                f"公式解析失败！请检查：\n1. 公式务必使用中括号包裹列名，如：[销售额] * 0.1\n2. 四则运算符号(+-*/)需为英文输入法下打出。\n内部报错: {str(e)}"
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

        actual_cols = normalize_columns(df_cleaned, raw_cols, col_type)
        if not actual_cols:
            continue

        for col in actual_cols:
            if action == "to_numeric":
                df_cleaned[col] = pd.to_numeric(df_cleaned[col], errors="coerce")
            elif action == "to_string":
                df_cleaned[col] = df_cleaned[col].astype(str)
            elif action == "strip_space":
                mask = df_cleaned[col].notna()
                df_cleaned.loc[mask, col] = (
                    df_cleaned.loc[mask, col].astype(str).str.strip()
                )
            elif action == "fill_na":
                if fill_val is not None and fill_val != "":
                    df_cleaned[col] = df_cleaned[col].fillna(fill_val)
            elif action == "drop_na":
                df_cleaned = df_cleaned.dropna(subset=[col])
    return df_cleaned


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
