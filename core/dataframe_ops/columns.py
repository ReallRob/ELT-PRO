"""Column selection helpers shared by DataFrame operators."""


def map_col(col_list):
    """Convert Excel-style column letters to zero-based indexes."""
    col_index_list = []
    for col in col_list:
        index = 0
        for char in str(col).upper():
            index = index * 26 + (ord(char) - 64)
        col_index_list.append(index - 1)
    return col_index_list


def normalize_columns(df, raw_cols, col_type):
    """Resolve UI column references into actual DataFrame column names."""
    if not isinstance(raw_cols, list):
        raw_cols = [raw_cols]

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
