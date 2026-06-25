import pandas as pd
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex
from PyQt5.QtGui import QColor, QFont


class PandasModel(QAbstractTableModel):
    def __init__(self, df=pd.DataFrame(), parent=None, max_preview_rows=None):
        super().__init__(parent)
        self._source_rows = len(df)
        if max_preview_rows is not None and len(df) > max_preview_rows:
            df = df.iloc[:max_preview_rows]
        self._df = df
        self._hide_column_names = bool(getattr(df, "attrs", {}).get("_hide_column_names"))
        self.batch_size = 200
        self._loaded_rows = min(len(df), self.batch_size)
        self._col_letters = self._build_col_letters(len(df.columns))

    @staticmethod
    def _build_col_letters(n_cols):
        letters = []
        for i in range(n_cols):
            n = i + 1
            s = ""
            while n > 0:
                n, rem = divmod(n - 1, 26)
                s = chr(65 + rem) + s
            letters.append(s)
        return letters

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if section < len(self._col_letters):
                return self._col_letters[section]
            return ""
        if orientation == Qt.Vertical:
            if not self._hide_column_names and section == 0:
                return "字段名"
            source_row = section if self._hide_column_names else section - 1
            return str(self._df.index[source_row])
        return None

    def rowCount(self, parent=None):
        return self._loaded_rows if self._hide_column_names else self._loaded_rows + 1

    def columnCount(self, parent=None):
        return len(self._df.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()

        if role == Qt.DisplayRole:
            if not self._hide_column_names and row == 0:
                return str(self._df.columns[col])
            try:
                row_offset = 0 if self._hide_column_names else 1
                val = self._df.iat[row - row_offset, col]
                return str(val) if pd.notna(val) else ""
            except Exception:
                return ""
        elif role == Qt.BackgroundRole and not self._hide_column_names and row == 0:
            return QColor("#FFF8E1")
        elif role == Qt.FontRole and not self._hide_column_names and row == 0:
            font = QFont()
            font.setBold(True)
            return font
        return None

    def canFetchMore(self, parent=None):
        return self._loaded_rows < len(self._df)

    def fetchMore(self, parent=None):
        if self._loaded_rows < len(self._df):
            remainder = len(self._df) - self._loaded_rows
            items_to_fetch = min(remainder, self.batch_size)
            row_offset = 0 if self._hide_column_names else 1
            self.beginInsertRows(
                QModelIndex(),
                self._loaded_rows + row_offset,
                self._loaded_rows + row_offset + items_to_fetch - 1,
            )
            self._loaded_rows += items_to_fetch
            self.endInsertRows()
