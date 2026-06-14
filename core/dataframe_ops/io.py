"""DataFrame input/output operators."""

import os
from pathlib import Path

import pandas as pd

CSV_SHEET_LABEL = "CSV (无工作表)"


def _coerce_int(value, default=None, minimum=None, field_name="参数"):
    if value is None or value == "":
        return default
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name}必须是整数")
    if minimum is not None and result < minimum:
        raise ValueError(f"{field_name}不能小于 {minimum}")
    return result


def _coerce_bool(value, default=True):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "是", "有", "有表头"}:
        return True
    if normalized in {"0", "false", "no", "n", "否", "无", "无表头", "没有"}:
        return False
    raise ValueError("是否有表头必须为是或否")


def _normalize_source_options(
    skiprows=0, nrows=None, start_col=1, ncols=None, has_header=True
):
    return {
        "skiprows": _coerce_int(skiprows, default=0, minimum=0, field_name="跳过行数"),
        "nrows": _coerce_int(nrows, default=None, minimum=0, field_name="读取行数"),
        "start_col": _coerce_int(start_col, default=1, minimum=1, field_name="起始列"),
        "ncols": _coerce_int(ncols, default=None, minimum=1, field_name="读取列数"),
        "has_header": _coerce_bool(has_header, default=True),
    }


def _slice_source_columns(df, start_col=1, ncols=None):
    start_index = start_col - 1
    total_cols = len(df.columns)
    if total_cols == 0:
        return df.copy()
    if start_index >= total_cols:
        raise ValueError(f"起始列超出文件列数：文件共有 {total_cols} 列")

    end_index = start_index + ncols if ncols is not None else None
    return df.iloc[:, start_index:end_index].copy()


def read_source_file(
    file_path,
    sheet_name=0,
    skiprows=0,
    nrows=None,
    start_col=1,
    ncols=None,
    has_header=True,
):
    """Read Excel/CSV data with consistent row, column, and header options."""
    if not file_path:
        raise ValueError("请选择数据源文件")

    path_text = str(file_path)
    if not os.path.exists(path_text):
        raise FileNotFoundError(f"数据源文件不存在: {path_text}")

    options = _normalize_source_options(skiprows, nrows, start_col, ncols, has_header)
    header = 0 if options["has_header"] else None
    read_kwargs = {
        "skiprows": options["skiprows"],
        "nrows": options["nrows"],
        "header": header,
    }

    if path_text.lower().endswith((".xlsx", ".xls")):
        sheet = sheet_name if sheet_name != CSV_SHEET_LABEL else 0
        df = pd.read_excel(path_text, sheet_name=sheet, **read_kwargs)
    else:
        df = pd.read_csv(path_text, **read_kwargs)

    # 列裁剪放在读取后，保证 Excel/CSV、有无表头模式使用同一套语义。
    df = _slice_source_columns(df, options["start_col"], options["ncols"])
    if not options["has_header"]:
        first_col = options["start_col"]
        df.columns = [f"列{first_col + i}" for i in range(len(df.columns))]
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
    except Exception:
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
