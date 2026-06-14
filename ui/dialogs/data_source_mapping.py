"""Dialog for remapping workflow data source paths."""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class DataSourceMappingDialog(QDialog):
    def __init__(self, file_mapping, file_context, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据源路径管理")
        self.setMinimumSize(700, 350)
        self.file_mapping = file_mapping
        self.file_context = file_context
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        lbl_info = QLabel("提示：双击下方的【当前文件路径】可重新关联本地文件。")
        lbl_info.setStyleSheet("color: #666; font-size: 12px; font-weight: bold;")
        layout.addWidget(lbl_info)

        self.table = QTableWidget(0, 2)
        self.table.setStyleSheet("border: 1px solid #ddd; background-color: white;")
        self.table.setHorizontalHeaderLabels(["当前文件路径", "所属节点 / Sheet"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )

        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.change_mapping_file)
        layout.addWidget(self.table)

        self.refresh_table()

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def refresh_table(self):
        self.table.setRowCount(0)
        for orig_path, actual_path in self.file_mapping.items():
            row = self.table.rowCount()
            self.table.insertRow(row)

            item_path = QTableWidgetItem(actual_path)
            item_path.setData(Qt.UserRole, orig_path)
            if actual_path != orig_path:
                item_path.setBackground(QColor("#E8F5E9"))
                item_path.setToolTip(f"原始定义: {orig_path}")

            contexts = self.file_context.get(orig_path, [])
            item_context = QTableWidgetItem(" | ".join(contexts))
            item_context.setForeground(QColor("#1565C0"))

            self.table.setItem(row, 0, item_path)
            self.table.setItem(row, 1, item_context)

    def change_mapping_file(self, row, col):
        if col == 0:
            current_item = self.table.item(row, 0)
            orig_path = current_item.data(Qt.UserRole)

            new_path, _ = QFileDialog.getOpenFileName(
                self, "重新关联数据源", "", "数据文件 (*.xlsx *.xls *.csv)"
            )
            if new_path:
                self.file_mapping[orig_path] = new_path
                self.refresh_table()
