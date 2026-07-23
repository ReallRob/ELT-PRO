"""DataFrame input/output operators."""

import csv
import os
from pathlib import Path

import pandas as pd

from core.dataframe_ops.columns import stringify_column_name

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


def _source_usecols(start_col, ncols, total_cols):
    start_index = start_col - 1
    if total_cols == 0:
        return []
    if start_index >= total_cols:
        raise ValueError(f"起始列超出文件列数：文件共有 {total_cols} 列")
    end_index = start_index + ncols if ncols is not None else total_cols
    return list(range(start_index, min(end_index, total_cols)))


def _read_source_header(path_text, sheet_name, header, skiprows):
    read_kwargs = {"skiprows": skiprows, "nrows": 0, "header": header}
    if path_text.lower().endswith((".xlsx", ".xls", ".xlsm")):
        sheet = sheet_name if sheet_name != CSV_SHEET_LABEL else 0
        return pd.read_excel(path_text, sheet_name=sheet, **read_kwargs)
    return pd.read_csv(path_text, **read_kwargs)


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
    needs_column_subset = options["start_col"] != 1 or options["ncols"] is not None
    if needs_column_subset:
        header_df = _read_source_header(
            path_text, sheet_name, header, options["skiprows"]
        )
        read_kwargs["usecols"] = _source_usecols(
            options["start_col"], options["ncols"], len(header_df.columns)
        )

    if path_text.lower().endswith((".xlsx", ".xls", ".xlsm")):
        sheet = sheet_name if sheet_name != CSV_SHEET_LABEL else 0
        df = pd.read_excel(path_text, sheet_name=sheet, **read_kwargs)
    else:
        df = pd.read_csv(path_text, **read_kwargs)
    if not options["has_header"]:
        first_col = options["start_col"]
        df.columns = [f"列{first_col + i}" for i in range(len(df.columns))]
    return df


def _text_cell_value(value):
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    if not isinstance(value, bool):
        is_integer = getattr(value, "is_integer", None)
        if callable(is_integer):
            try:
                if is_integer():
                    return str(int(value))
                return format(value, "f").rstrip("0").rstrip(".")
            except (OverflowError, TypeError, ValueError):
                pass
    return str(value)


def _text_dataframe(df):
    if df is None:
        return pd.DataFrame()
    result = df.copy()
    result.columns = [stringify_column_name(column) for column in result.columns]
    return result.apply(lambda column: column.map(_text_cell_value))


def export_df(df, target_path, default_dir):
    """Export one table. Values are written as text by default."""
    save_p = Path(target_path)

    def write_file(path):
        if str(path).lower().endswith(".csv"):
            _text_dataframe(df).to_csv(
                path,
                index=False,
                encoding="utf-8-sig",
                quoting=csv.QUOTE_ALL,
            )
        else:
            _text_dataframe(df).to_excel(path, index=False)

    if save_p.parent.exists():
        try:
            write_file(target_path)
        except Exception as exc:
            raise RuntimeError(f"导出失败: {target_path}\n原因: {exc}") from exc
        return True, target_path

    fname = save_p.name if save_p.name else "自动导出结果.xlsx"
    if not fname.endswith((".xlsx", ".csv")):
        fname += ".xlsx"
    fallback_path = Path(default_dir) / fname
    try:
        write_file(fallback_path)
    except Exception as exc:
        raise RuntimeError(
            f"目标目录不存在，已尝试降级到默认目录但仍导出失败。\n"
            f"原路径: {target_path}\n降级路径: {fallback_path}\n原因: {exc}"
        ) from exc
    return False, str(fallback_path)


def _safe_sheet_name(name, used_names):
    text = str(name or "Sheet").strip() or "Sheet"
    for char in '[]:*?/\\':
        text = text.replace(char, "_")
    text = text[:31] or "Sheet"
    base = text
    index = 2
    while text in used_names:
        suffix = f"_{index}"
        text = f"{base[:31 - len(suffix)]}{suffix}"
        index += 1
    used_names.add(text)
    return text


def _xlsx_target_path(target_path):
    path = Path(target_path)
    if path.suffix.lower() != ".xlsx":
        name = path.stem or "自动导出结果"
        path = path.with_name(f"{name}.xlsx")
    return path


def export_tables(tables, target_path, default_dir, mode="multi_sheet"):
    entries = [(str(name or f"表{index}"), df) for index, (name, df) in enumerate(tables or [], start=1)]
    if not entries:
        raise ValueError("导出失败: 没有可导出的表")
    mode = str(mode or "multi_sheet").strip()
    if mode not in {"multi_sheet", "single_sheet"}:
        mode = "multi_sheet"
    save_p = _xlsx_target_path(target_path) if mode == "multi_sheet" else Path(target_path)

    def write_file(path):
        if mode == "single_sheet":
            merged = pd.concat([df for _name, df in entries], ignore_index=True, sort=False)
            if str(path).lower().endswith(".csv"):
                _text_dataframe(merged).to_csv(
                    path,
                    index=False,
                    encoding="utf-8-sig",
                    quoting=csv.QUOTE_ALL,
                )
            else:
                _text_dataframe(merged).to_excel(path, index=False)
            return merged

        used_names = set()
        with pd.ExcelWriter(path) as writer:
            for name, df in entries:
                _text_dataframe(df).to_excel(
                    writer,
                    sheet_name=_safe_sheet_name(name, used_names),
                    index=False,
                )
        return entries[0][1]

    if save_p.parent.exists():
        try:
            result = write_file(save_p)
        except Exception as exc:
            raise RuntimeError(f"导出失败: {save_p}\n原因: {exc}") from exc
        return True, str(save_p), result

    fname = save_p.name if save_p.name else "自动导出结果.xlsx"
    if mode == "multi_sheet" and not fname.lower().endswith(".xlsx"):
        fname = f"{Path(fname).stem or '自动导出结果'}.xlsx"
    elif mode != "multi_sheet" and not fname.endswith((".xlsx", ".csv")):
        fname += ".xlsx"
    fallback_path = Path(default_dir) / fname
    try:
        result = write_file(fallback_path)
    except Exception as exc:
        raise RuntimeError(
            f"目标目录不存在，已尝试降级到默认目录但仍导出失败。\n"
            f"原路径: {save_p}\n降级路径: {fallback_path}\n原因: {exc}"
        ) from exc
    return False, str(fallback_path), result
