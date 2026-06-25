"""Column selection helpers shared by DataFrame operators."""

_UNRESOLVED = object()


def map_col(col_list):
    """Convert Excel-style column letters to zero-based indexes."""
    col_index_list = []
    for col in col_list:
        index = 0
        for char in str(col).upper():
            index = index * 26 + (ord(char) - 64)
        col_index_list.append(index - 1)
    return col_index_list


def stringify_column_name(column):
    """Return the display/storage name used for non-string DataFrame columns."""
    if isinstance(column, tuple):
        parts = [
            stringify_column_name(part)
            for part in column
            if part is not None and str(part).strip() != ""
        ]
        return "_".join(parts)
    if column is None:
        return ""
    return str(column)


def flatten_dataframe_columns(df):
    """Copy a DataFrame and convert all column labels to unique strings."""
    result = df.copy()
    seen = {}
    flat_columns = []
    for column in result.columns:
        base = stringify_column_name(column).strip() or "列"
        count = seen.get(base, 0) + 1
        seen[base] = count
        flat_columns.append(base if count == 1 else f"{base}_{count}")
    result.columns = flat_columns
    return result


def resolve_column(df, raw_col):
    """Resolve a user-facing column reference to the actual DataFrame column."""
    if raw_col in df.columns:
        return raw_col

    raw_text = stringify_column_name(raw_col)
    for column in df.columns:
        if stringify_column_name(column) == raw_text:
            return column
    return _UNRESOLVED


def normalize_columns(df, raw_cols, col_type):
    """Resolve UI column references into actual DataFrame column names."""
    if not isinstance(raw_cols, list):
        raw_cols = [raw_cols]

    if col_type == "col_name":
        actual_cols = []
        for col in raw_cols:
            actual = resolve_column(df, col)
            if actual is not _UNRESOLVED:
                actual_cols.append(actual)
    elif col_type == "col_index":
        actual_cols = []
        for col in raw_cols:
            try:
                index = int(col)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(df.columns):
                actual_cols.append(df.columns[index])
    elif col_type == "col_word":
        indices = map_col(raw_cols)
        actual_cols = [df.columns[i] for i in indices if 0 <= i < len(df.columns)]
    else:
        raise ValueError("col_type must be col_name, col_index or col_word")

    return actual_cols
