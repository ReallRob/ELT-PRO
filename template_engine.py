import os
from copy import copy

import pandas as pd

try:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill
    from openpyxl.utils import column_index_from_string
except ImportError:
    openpyxl = None
    column_index_from_string = None


TEMPLATE_PREVIEW_MAX_ROWS = 5000
TEMPLATE_PREVIEW_MAX_COLS = 200


def build_template_metadata(wb, file_path=""):
    """根据 openpyxl Workbook 生成模板结构信息。"""
    sheets_info = {}
    for name in wb.sheetnames:
        ws = wb[name]
        sheets_info[name] = {
            "name": name,
            "max_row": ws.max_row or 1,
            "max_col": ws.max_column or 1,
        }

    return {
        "path": file_path,
        "sheets": sheets_info,
        "sheet_names": list(wb.sheetnames),
    }


def workbook_to_preview_data(wb, saved_path=""):
    """Convert an openpyxl workbook to a bounded multi-sheet preview payload."""
    sheets = {}
    for ws in wb.worksheets:
        max_row = min(ws.max_row or 0, TEMPLATE_PREVIEW_MAX_ROWS)
        max_col = min(ws.max_column or 0, TEMPLATE_PREVIEW_MAX_COLS)
        rows = list(
            ws.iter_rows(
                min_row=1,
                max_row=max_row,
                min_col=1,
                max_col=max_col,
                values_only=True,
            )
        )
        if not rows:
            sheets[ws.title] = pd.DataFrame()
            continue
        max_cols = max((len(row) for row in rows), default=0)
        normalized_rows = [
            list(row) + [None] * (max_cols - len(row))
            for row in rows
        ]
        columns = [f"{i + 1}" for i in range(max_cols)]
        preview_df = pd.DataFrame(normalized_rows, columns=columns)
        preview_df.index = range(1, len(preview_df) + 1)
        preview_df.attrs["_hide_column_names"] = True
        preview_df.attrs["_source_rows"] = ws.max_row or 0
        preview_df.attrs["_source_cols"] = ws.max_column or 0
        preview_df.attrs["_preview_limited"] = (
            (ws.max_row or 0) > TEMPLATE_PREVIEW_MAX_ROWS
            or (ws.max_column or 0) > TEMPLATE_PREVIEW_MAX_COLS
        )
        sheets[ws.title] = preview_df
    return {
        "_template_preview": True,
        "saved_path": saved_path,
        "sheets": sheets,
        "preview_limit": {
            "max_rows": TEMPLATE_PREVIEW_MAX_ROWS,
            "max_cols": TEMPLATE_PREVIEW_MAX_COLS,
        },
    }




def close_workbook(wb):
    if wb is None:
        return
    close = getattr(wb, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def load_template(file_path):
    """
    加载模板文件，返回 (workbook, metadata_dict)。

    metadata 结构:
    {
        "path": "D:/templates/月报.xlsx",
        "sheets": {
            "Sheet1": {"name": "Sheet1", "max_row": 50, "max_col": 10},
            "Sheet2": {"name": "Sheet2", "max_row": 30, "max_col": 8}
        },
        "sheet_names": ["Sheet1", "Sheet2"]
    }
    """
    if openpyxl is None:
        raise ImportError("缺少 openpyxl 依赖，请执行: pip install openpyxl")

    wb = openpyxl.load_workbook(file_path)
    return wb, build_template_metadata(wb, file_path)


def _is_blank(expr):
    return expr is None or str(expr).strip() == ""


def _eval_position(expr, max_row, max_col, label="位置", allow_column_letters=False):
    """安全计算位置表达式，可用变量: max_row, max_col。"""
    if isinstance(expr, (int, float)):
        return int(expr)

    text = str(expr).strip()
    if not text:
        raise ValueError(f"{label}不能为空")

    if allow_column_letters:
        column_text = text.replace("$", "")
        if column_text.isalpha() and column_index_from_string is not None:
            return column_index_from_string(column_text.upper())

    allowed = {"max_row": max_row, "max_col": max_col}
    try:
        result = eval(text, {"__builtins__": {}}, allowed)
        return int(result)
    except Exception:
        raise ValueError(
            f"无法解析{label}表达式: {expr} "
            f"(可用变量: max_row={max_row}, max_col={max_col})"
        )


def _eval_optional_position(expr, max_row, max_col, label="位置", allow_column_letters=False):
    if _is_blank(expr):
        return None
    return _eval_position(expr, max_row, max_col, label, allow_column_letters)


def _style_from_cell(cell):
    return {
        "font": copy(cell.font) if cell.font else Font(),
        "border": copy(cell.border) if cell.border else Border(),
        "fill": copy(cell.fill) if cell.fill else PatternFill(),
        "number_format": cell.number_format,
        "alignment": copy(cell.alignment) if cell.alignment else Alignment(),
    }


def _apply_style(cell, style):
    cell.font = copy(style["font"])
    cell.border = copy(style["border"])
    cell.fill = copy(style["fill"])
    cell.number_format = style["number_format"]
    cell.alignment = copy(style["alignment"])


def _is_formula(value):
    return isinstance(value, str) and value.startswith("=")


def _select_columns(df, columns):
    if columns is None or columns == ["*"] or columns == "*" or columns == []:
        return df.copy()

    available = [c for c in columns if c in df.columns]
    if not available:
        raise ValueError(f"指定列在 DataFrame 中不存在: {columns}")
    return df[available].copy()


def insert_into_template(
    wb,
    df,
    sheet_name,
    start_row_expr,
    start_col_expr,
    columns=None,
    write_header=True,
    inherit_style=False,
    end_row_expr=None,
    end_col_expr=None,
):
    """
    将 DataFrame 写入到模板工作表的指定区域。

    参数:
        wb:              openpyxl Workbook 对象
        df:              要写入的 DataFrame
        sheet_name:      目标工作表名称
        start_row_expr:  起始行表达式，如 "max_row+1"、"5"
        start_col_expr:  起始列表达式，如 "1"、"A"、"max_col+1"
        columns:         要写入的列列表，None、[] 或 ["*"] 表示全部列
        write_header:    是否写入表头
        inherit_style:   是否继承上一行同列的样式，默认关闭以保留模板目标区域原样式
        end_row_expr:    可选，结束行表达式；填写后会限制写入高度
        end_col_expr:    可选，结束列表达式；填写后会限制写入宽度

    返回:
        (success, message)
    """
    if openpyxl is None:
        return False, "缺少 openpyxl 依赖"

    if sheet_name not in wb.sheetnames:
        return False, f"工作表 [{sheet_name}] 不存在"

    ws = wb[sheet_name]
    max_row = ws.max_row or 1
    max_col = ws.max_column or 1

    try:
        start_row = _eval_position(start_row_expr, max_row, max_col, "起始行")
        start_col = _eval_position(
            start_col_expr, max_row, max_col, "起始列", allow_column_letters=True
        )
        end_row = _eval_optional_position(end_row_expr, max_row, max_col, "结束行")
        end_col = _eval_optional_position(
            end_col_expr, max_row, max_col, "结束列", allow_column_letters=True
        )
        fill_df = _select_columns(df, columns)
    except ValueError as exc:
        return False, str(exc)

    start_row = max(1, start_row)
    start_col = max(1, start_col)

    if end_row is not None:
        end_row = max(1, end_row)
        if end_row < start_row:
            return False, f"结束行不能小于起始行: {end_row} < {start_row}"
    if end_col is not None:
        end_col = max(1, end_col)
        if end_col < start_col:
            return False, f"结束列不能小于起始列: {end_col} < {start_col}"

    notes = []

    if end_col is not None:
        max_write_cols = end_col - start_col + 1
        if max_write_cols <= 0:
            return False, "可写入列数为 0，请检查起止列"
        if fill_df.shape[1] > max_write_cols:
            fill_df = fill_df.iloc[:, :max_write_cols].copy()
            notes.append(f"数据列已按结束列截断为 {max_write_cols} 列")

    if fill_df.shape[1] == 0:
        return False, "没有可写入的列"

    if end_row is not None:
        max_area_rows = end_row - start_row + 1
        header_rows = 1 if write_header else 0
        max_data_rows = max(0, max_area_rows - header_rows)
        if len(fill_df) > max_data_rows:
            fill_df = fill_df.iloc[:max_data_rows, :].copy()
            notes.append(f"数据行已按结束行截断为 {max_data_rows} 行")

    num_rows = len(fill_df)
    num_cols = len(fill_df.columns)
    row_offset = 1 if write_header else 0
    total_rows = row_offset + num_rows

    styles = []
    if inherit_style:
        ref_row = max(1, start_row - 1)
        for j in range(num_cols):
            styles.append(_style_from_cell(ws.cell(row=ref_row, column=start_col + j)))

    protected = set()
    for r in range(start_row, start_row + total_rows):
        for c in range(start_col, start_col + num_cols):
            if _is_formula(ws.cell(row=r, column=c).value):
                protected.add((r, c))

    if write_header:
        for j, col_name in enumerate(fill_df.columns):
            row_idx = start_row
            col_idx = start_col + j
            if (row_idx, col_idx) in protected:
                continue
            cell = ws.cell(row=row_idx, column=col_idx, value=str(col_name))
            if inherit_style and j < len(styles):
                _apply_style(cell, styles[j])

    for i in range(num_rows):
        row_idx = start_row + row_offset + i
        for j in range(num_cols):
            col_idx = start_col + j
            if (row_idx, col_idx) in protected:
                continue
            val = fill_df.iat[i, j]
            if pd.isna(val):
                val = ""
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            if inherit_style and j < len(styles):
                _apply_style(cell, styles[j])

    if end_row is not None or end_col is not None:
        area = (
            f"范围: 行{start_row}-{end_row if end_row is not None else start_row + total_rows - 1}, "
            f"列{start_col}-{end_col if end_col is not None else start_col + num_cols - 1}"
        )
    else:
        area = f"起始: 行{start_row}, 列{start_col}"

    msg = f"已写入 {num_rows} 行 x {num_cols} 列 到 {sheet_name} ({area})"
    if notes:
        msg += "；" + "；".join(notes)
    return True, msg


def save_template(wb, output_path):
    """保存模板到文件。"""
    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    wb.save(output_path)
    return True, output_path
