import os

try:
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Border, Alignment
    from openpyxl.utils import get_column_letter
except ImportError:
    openpyxl = None


def load_template(file_path):
    """
    加载模板文件，返回 (workbook, metadata_dict)

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
    sheets_info = {}
    for name in wb.sheetnames:
        ws = wb[name]
        sheets_info[name] = {
            "name": name,
            "max_row": ws.max_row or 1,
            "max_col": ws.max_column or 1,
        }

    metadata = {
        "path": file_path,
        "sheets": sheets_info,
        "sheet_names": list(wb.sheetnames),
    }
    return wb, metadata


def _eval_position(expr, max_row, max_col):
    """安全计算位置表达式，可用变量: max_row, max_col"""
    if isinstance(expr, (int, float)):
        return int(expr)
    allowed = {"max_row": max_row, "max_col": max_col}
    try:
        result = eval(str(expr), {"__builtins__": {}}, allowed)
        return int(result)
    except Exception:
        raise ValueError(f"无法解析位置表达式: {expr} (可用变量: max_row={max_row}, max_col={max_col})")


def _copy_cell_style(src_cell, dst_cell):
    if src_cell.has_style:
        dst_cell.font = src_cell.font.copy()
        dst_cell.border = src_cell.border.copy()
        dst_cell.fill = src_cell.fill.copy()
        dst_cell.number_format = src_cell.number_format
        dst_cell.alignment = src_cell.alignment.copy()


def _is_formula(value):
    return isinstance(value, str) and value.startswith("=")


def insert_into_template(wb, df, sheet_name, start_row_expr, start_col_expr,
                          columns=None, write_header=True, inherit_style=True):
    """
    将 DataFrame 插入到模板工作表的指定位置

    参数:
        wb:              openpyxl Workbook 对象
        df:              要插入的 DataFrame
        sheet_name:      目标工作表名称
        start_row_expr:  起始行表达式 (如 "max_row+1", "5", "max_row-1")
        start_col_expr:  起始列表达式 (如 "1", "max_col+1")
        columns:         要插入的列列表, None 或 ["*"] 表示全部列
        write_header:    是否写入表头
        inherit_style:   是否继承相邻行的样式

    返回:
        (success, message, updated_workbook)
    """
    if openpyxl is None:
        return False, "缺少 openpyxl 依赖"

    if sheet_name not in wb.sheetnames:
        return False, f"工作表 [{sheet_name}] 不存在"

    ws = wb[sheet_name]
    max_row = ws.max_row or 1
    max_col = ws.max_column or 1

    # 计算起始位置
    try:
        start_row = _eval_position(start_row_expr, max_row, max_col)
        start_col = _eval_position(start_col_expr, max_row, max_col)
    except ValueError as e:
        return False, str(e)

    if start_row < 1:
        start_row = 1
    if start_col < 1:
        start_col = 1

    # 处理列选择
    if columns is None or columns == ["*"] or columns == "*":
        fill_df = df.copy()
    else:
        available = [c for c in columns if c in df.columns]
        if not available:
            return False, f"指定列在 DataFrame 中不存在: {columns}"
        fill_df = df[available].copy()

    num_rows = len(fill_df)
    num_cols = len(fill_df.columns)

    # 继承样式
    if inherit_style:
        ref_row = max(1, start_row - 1) if write_header else start_row - 1
        styles = []
        for j in range(num_cols):
            ref_cell = ws.cell(row=ref_row, column=start_col + j)
            styles.append({
                "font": ref_cell.font.copy() if ref_cell.font else Font(),
                "border": ref_cell.border.copy() if ref_cell.border else Border(),
                "fill": ref_cell.fill.copy() if ref_cell.fill else PatternFill(),
                "number_format": ref_cell.number_format,
                "alignment": ref_cell.alignment.copy() if ref_cell.alignment else Alignment(),
            })

    # 保护公式单元格
    protected = set()
    for r in range(start_row, start_row + num_rows + 1):
        for c in range(start_col, start_col + num_cols):
            cell = ws.cell(row=r, column=c)
            if _is_formula(cell.value):
                protected.add((r, c))

    # 写入表头
    row_offset = 0
    if write_header:
        for j, col_name in enumerate(fill_df.columns):
            cell = ws.cell(row=start_row, column=start_col + j, value=str(col_name))
            if inherit_style and j < len(styles):
                cell.font = styles[j]["font"]
                cell.border = styles[j]["border"]
                cell.fill = styles[j]["fill"]
                cell.number_format = styles[j]["number_format"]
                cell.alignment = styles[j]["alignment"]
        row_offset = 1

    # 写入数据
    import pandas as pd
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
                cell.font = styles[j]["font"]
                cell.border = styles[j]["border"]
                cell.fill = styles[j]["fill"]
                cell.number_format = styles[j]["number_format"]
                cell.alignment = styles[j]["alignment"]

    return True, f"已插入 {num_rows} 行 x {num_cols} 列 到 {sheet_name} (起始: 行{start_row}, 列{start_col})"


def save_template(wb, output_path):
    """保存模板到文件"""
    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    wb.save(output_path)
    return True, output_path
