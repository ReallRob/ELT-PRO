from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parameter_resolver import (
    expand_mapping_inputs,
    normalize_parameter_mappings,
    normalize_runtime_parameters,
    parse_parameter_literal,
)


class RuntimeParametersDialog(QDialog):
    def __init__(self, parameters=None, mappings=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("运行参数")
        self.resize(720, 520)
        self.setMinimumSize(620, 420)
        self._parameters = normalize_runtime_parameters(parameters)
        self._mappings = mappings or {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel("在算子参数中可写 ${参数名} 或 ${参数名|map:映射名}；映射输入/输出支持 1,2,3、[1,2,3]、1-3、1月份-3月份")
        hint.setStyleSheet("color: #607D8B; font-size: 12px;")
        layout.addWidget(hint)

        self.tabs = QTabWidget()
        self.params_table = self._make_table(["参数名", "当前值"])
        self.maps_table = self._make_table(["映射名", "输入值/范围/集合", "输出值/范围/集合"])

        self.tabs.addTab(self._make_table_page(self.params_table), "参数")
        self.tabs.addTab(self._make_table_page(self.maps_table), "映射")
        layout.addWidget(self.tabs)

        self._load_parameters()
        self._load_mappings()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _make_table(self, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setStyleSheet("""
            QTableWidget {
                background: white;
                border: 1px solid #DFE5EC;
                border-radius: 6px;
                gridline-color: #EEF2F6;
            }
            QHeaderView::section {
                background: #F7FAFC;
                border: none;
                border-bottom: 1px solid #DFE5EC;
                padding: 6px;
                font-weight: bold;
            }
        """)
        return table

    def _make_table_page(self, table):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("添加")
        btn_delete = QPushButton("删除选中")
        btn_add.clicked.connect(lambda: self._add_row(table))
        btn_delete.clicked.connect(lambda: self._delete_selected_rows(table))
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_delete)
        btn_row.addStretch()

        layout.addLayout(btn_row)
        layout.addWidget(table)
        return page

    @staticmethod
    def _cell_text(table, row, col):
        item = table.item(row, col)
        return item.text().strip() if item else ""

    def _add_row(self, table, values=None):
        row = table.rowCount()
        table.insertRow(row)
        values = values or []
        for col in range(table.columnCount()):
            table.setItem(row, col, QTableWidgetItem(str(values[col]) if col < len(values) else ""))
        return row

    def _delete_selected_rows(self, table):
        rows = sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True)
        for row in rows:
            table.removeRow(row)

    def _load_parameters(self):
        for key, value in self._parameters.items():
            self._add_row(self.params_table, [key, self._format_value(value)])
        if self.params_table.rowCount() == 0:
            self._add_row(self.params_table)

    def _load_mappings(self):
        for map_name, mapping in self._mappings.items():
            if isinstance(mapping, list):
                for row in mapping:
                    if isinstance(row, dict):
                        self._add_row(
                            self.maps_table,
                            [map_name, row.get("from", ""), self._format_value(row.get("to", ""))],
                        )
            elif isinstance(mapping, dict):
                for key, value in mapping.items():
                    self._add_row(self.maps_table, [map_name, key, self._format_value(value)])
        if self.maps_table.rowCount() == 0:
            self._add_row(self.maps_table)

    @staticmethod
    def _format_value(value):
        if isinstance(value, (dict, list, tuple, bool, int, float)):
            import json

            return json.dumps(value, ensure_ascii=False)
        return "" if value is None else str(value)

    def _collect_parameters(self):
        params = {}
        for row in range(self.params_table.rowCount()):
            name = self._cell_text(self.params_table, row, 0)
            value = self._cell_text(self.params_table, row, 1)
            if not name and not value:
                continue
            if not name:
                raise ValueError(f"第 {row + 1} 行参数名为空")
            params[name] = parse_parameter_literal(value)
        return normalize_runtime_parameters(params)

    def _collect_mappings(self):
        mappings = {}
        expanded_seen = {}
        for row in range(self.maps_table.rowCount()):
            map_name = self._cell_text(self.maps_table, row, 0)
            from_value = self._cell_text(self.maps_table, row, 1)
            to_value = self._cell_text(self.maps_table, row, 2)
            if not map_name and not from_value and not to_value:
                continue
            if not map_name:
                raise ValueError(f"第 {row + 1} 行映射名为空")
            if not from_value:
                raise ValueError(f"第 {row + 1} 行映射输入值为空")
            for input_value in expand_mapping_inputs(from_value):
                key = (map_name, str(parse_parameter_literal(input_value)))
                if key in expanded_seen:
                    raise ValueError(
                        f"映射 {map_name} 的输入值 {key[1]} 在第 {expanded_seen[key]} 行和第 {row + 1} 行重复"
                    )
                expanded_seen[key] = row + 1
            mappings.setdefault(map_name, []).append({
                "from": from_value,
                "to": to_value,
            })
        normalize_parameter_mappings(mappings)
        return mappings

    def _accept_checked(self):
        try:
            self._parameters = self._collect_parameters()
            self._mappings = self._collect_mappings()
        except Exception as exc:
            QMessageBox.warning(self, "参数错误", str(exc))
            return
        self.accept()

    def get_parameters(self):
        return dict(self._parameters)

    def get_mappings(self):
        return {
            name: [dict(row) for row in rows] if isinstance(rows, list) else dict(rows)
            for name, rows in self._mappings.items()
        }
