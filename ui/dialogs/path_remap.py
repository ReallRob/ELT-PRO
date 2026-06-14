"""Dialog for remapping missing data source files."""

import os

from PyQt5.QtWidgets import (
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class PathRemapDialog(QDialog):
    def __init__(self, missing_files, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据源重映射")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self.missing_files = missing_files
        self.inputs = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        warn_lbl = QLabel(
            "注意：以下数据源已失效（文件不存在）。\n如果不需要替换，可留空，后续可手动配置。"
        )
        warn_lbl.setStyleSheet("color: #E65100; font-weight: bold;")
        layout.addWidget(warn_lbl)

        # 修复显示不全：增加滚动条容器处理超长文件列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        form = QFormLayout(scroll_content)

        for nid, old_path in self.missing_files.items():
            h = QHBoxLayout()
            line = QLineEdit()
            line.setPlaceholderText("请选择新的有效文件...")
            btn = QPushButton("浏览")
            btn.clicked.connect(lambda _, l=line: self.browse(l))
            h.addWidget(line)
            h.addWidget(btn)
            form.addRow(f"原路径: {os.path.basename(old_path)}", h)
            self.inputs[nid] = line

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def browse(self, line_edit):
        p, _ = QFileDialog.getOpenFileName(
            self, "选择有效文件", "", "Excel/CSV (*.xlsx *.xls *.csv)"
        )
        if p:
            line_edit.setText(p)

    def get_mapping(self):
        return {nid: line.text() for nid, line in self.inputs.items() if line.text()}
