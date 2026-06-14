"""Data cleaning operators."""

import pandas as pd

from core.dataframe_ops.columns import normalize_columns
from core.dataframe_ops.dates import parse_datetime_series


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
            elif action == "to_int":
                df_cleaned[col] = pd.to_numeric(df_cleaned[col], errors="coerce").astype("Int64")
            elif action == "to_float":
                df_cleaned[col] = pd.to_numeric(df_cleaned[col], errors="coerce").astype(float)
            elif action == "to_datetime":
                out_fmt = fill_val if fill_val else None
                result = parse_datetime_series(df_cleaned[col])
                if out_fmt:
                    df_cleaned[col] = result.dt.strftime(out_fmt)
                else:
                    df_cleaned[col] = result.dt.normalize()
            elif action == "strip_space":
                mask = df_cleaned[col].notna()
                df_cleaned.loc[mask, col] = df_cleaned.loc[mask, col].astype(str).str.strip().values
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


def drop_duplicates(df, subset_cols, keep="first", col_type="col_name"):
    """Remove duplicate rows."""
    if not subset_cols:
        result = df.drop_duplicates(keep=keep)
    else:
        actual = normalize_columns(df, subset_cols, col_type)
        if not actual:
            raise ValueError(f"去重列未找到: {subset_cols}")
        result = df.drop_duplicates(subset=actual, keep=keep)
    return result.reset_index(drop=True)


def sample_data(df, n=None, frac=None, random_state=None):
    """Randomly sample rows."""
    if frac is not None:
        return df.sample(frac=frac, random_state=random_state).reset_index(drop=True)
    if n is not None and n > 0:
        return df.sample(n=min(n, len(df)), random_state=random_state).reset_index(drop=True)
    return df
