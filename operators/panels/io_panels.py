"""Operator panels for importing and exporting tabular data."""

import os
from pathlib import Path

from PyQt5.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
)

from core.app_paths import get_exec_dir
from core.dataframe_ops import CSV_SHEET_LABEL, export_df, read_source_file
from operators.base_panel import BaseToolPanel, QLineEdit


class LoadFilePanel(BaseToolPanel):
    use_df = False
    use_type = False
    theme_color = "#1976D2"
    action_name = "导入"

    @staticmethod
    def _number_or_token(text, default=None):
        """保留运行参数表达式，普通数字则规范为 int。"""
        value = str(text or "").strip()
        if not value:
            return default
        try:
            return int(value)
        except ValueError:
            return value

    def init_custom_ui(self):
        card, inner = self._make_card("数据源配置")
        self.custom_layout.addWidget(card)

        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.set_parameter_enabled(False)
        self.path_input.setPlaceholderText("选择源文件 (.xlsx / .csv)")
        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self.browse_path)
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(btn_browse)

        fl = QFormLayout()
        fl.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        fl.setRowWrapPolicy(QFormLayout.WrapLongRows)
        fl.addRow("文件路径:", path_layout)
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentTextChanged.connect(self.auto_update_out_name)
        fl.addRow("工作表(Excel):", self.sheet_combo)

        self.skip_input = QLineEdit("0")
        fl.addRow("跳过前N行:", self.skip_input)

        self.start_col_input = QLineEdit("1")
        self.start_col_input.setPlaceholderText("1 表示从第一列开始")
        fl.addRow("从第几列开始:", self.start_col_input)

        self.ncols_input = QLineEdit()
        self.ncols_input.setPlaceholderText("读取列数 (留空为到最后一列)")
        fl.addRow("读取多少列:", self.ncols_input)

        self.header_combo = QComboBox()
        self.header_combo.addItems(["是", "否"])
        fl.addRow("是否有表头:", self.header_combo)

        self.nrows_input = QLineEdit()
        self.nrows_input.setPlaceholderText("读取行数 (留空为全部)")
        fl.addRow("限制行数:", self.nrows_input)
        inner.addLayout(fl)

    def browse_path(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择数据源", "", "Excel/CSV (*.xlsx *.xls *.csv)"
        )
        if path:
            self.path_input.setText(path)
            self.update_sheets(path)

    def update_sheets(self, path):
        self.sheet_combo.clear()
        if path.endswith((".xlsx", ".xls")):
            try:
                import pandas as pd

                with pd.ExcelFile(path) as excel:
                    sheets = list(excel.sheet_names)
                self.sheet_combo.addItems(sheets)
            except Exception:
                pass
        else:
            self.sheet_combo.addItem(CSV_SHEET_LABEL)

    def auto_update_out_name(self, text):
        if not text:
            return
        if text == CSV_SHEET_LABEL:
            if self.path_input.text():
                base_name = os.path.basename(self.path_input.text()).split(".")[0]
                self.out_input.setText(base_name)
        else:
            self.out_input.setText(text)

    def get_custom_params(self):
        return {
            "file_path": self.path_input.text().strip(),
            "sheet_name": (
                self.sheet_combo.currentText() if self.sheet_combo.count() > 0 else 0
            ),
            "skiprows": self._number_or_token(self.skip_input.text(), 0),
            "nrows": self._number_or_token(self.nrows_input.text(), None),
            "start_col": self._number_or_token(self.start_col_input.text(), 1),
            "ncols": self._number_or_token(self.ncols_input.text(), None),
            "has_header": self.header_combo.currentText() == "是",
        }

    def set_custom_params(self, p):
        if "file_path" in p:
            self.path_input.setText(p["file_path"])
            self.update_sheets(p["file_path"])
        if "sheet_name" in p:
            self.sheet_combo.setCurrentText(str(p["sheet_name"]))
        if "skiprows" in p:
            self.skip_input.setText(str(p["skiprows"]))
        if "start_col" in p:
            self.start_col_input.setText(str(p["start_col"]))
        if "ncols" in p and p["ncols"] is not None:
            self.ncols_input.setText(str(p["ncols"]))
        if "has_header" in p:
            self.header_combo.setCurrentText("是" if p.get("has_header") else "否")
        if "nrows" in p and p["nrows"] is not None:
            self.nrows_input.setText(str(p["nrows"]))

    def clear_custom_ui(self):
        self.path_input.clear()
        self.sheet_combo.clear()
        self.skip_input.setText("0")
        self.start_col_input.setText("1")
        self.ncols_input.clear()
        self.header_combo.setCurrentText("是")
        self.nrows_input.clear()

    def execute(self):
        p = self.get_params()
        if not p["file_path"] or not os.path.exists(p["file_path"]):
            return QMessageBox.warning(self, "错误", "请选择有效的文件路径！")

        out_name = p["out_name"] or os.path.basename(p["file_path"]).split(".")[0]
        try:
            df = read_source_file(
                p["file_path"],
                sheet_name=p.get("sheet_name", 0),
                skiprows=p.get("skiprows", 0),
                nrows=p.get("nrows"),
                start_col=p.get("start_col", 1),
                ncols=p.get("ncols"),
                has_header=p.get("has_header", True),
            )
            self.step_recorded.emit("load_file", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))


class ExportNodePanel(BaseToolPanel):
    use_type = False
    use_out = False
    theme_color = "#607D8B"

    def init_custom_ui(self):
        card, inner = self._make_card("导出配置")
        self.custom_layout.addWidget(card)

        fl = QFormLayout()
        fl.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        fl.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.fname_input = QLineEdit("Export_Result.xlsx")
        fl.addRow("导出文件名:", self.fname_input)

        path_layout = QHBoxLayout()
        self.dir_input = QLineEdit()
        self.dir_input.set_parameter_enabled(False)
        self.dir_input.setPlaceholderText("留空默认为程序运行目录")
        btn_browse = QPushButton("浏览目录")
        btn_browse.clicked.connect(self.browse_dir)
        path_layout.addWidget(self.dir_input)
        path_layout.addWidget(btn_browse)
        fl.addRow("保存至目录:", path_layout)
        inner.addLayout(fl)

        hint = self._make_hint_label("支持 .xlsx 和 .csv 格式。目录留空则保存至程序根目录。")
        inner.addWidget(hint)

    def browse_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择保存目录", "")
        if folder:
            self.dir_input.setText(folder)

    def clear_custom_ui(self):
        self.fname_input.setText("Export_Result.xlsx")
        self.dir_input.clear()

    def set_custom_params(self, p):
        if "file_name" in p:
            self.fname_input.setText(p["file_name"])
        if "folder_path" in p:
            self.dir_input.setText(p["folder_path"])

    def get_custom_params(self):
        return {
            "file_name": self.fname_input.text().strip(),
            "folder_path": self.dir_input.text().strip(),
            "out_name": "Export_Point",
        }

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "未选择导出表")

        default_dir = get_exec_dir()
        fname = p.get("file_name") or "Result.xlsx"
        fdir = p.get("folder_path", "").strip()

        if not fdir:
            target_path = str(default_dir / fname)
        else:
            target_path = str(Path(fdir) / fname)

        try:
            success, final_path = export_df(
                self.data_pool[p["df_name"]], target_path, default_dir
            )
            if success:
                QMessageBox.information(self, "成功", f"文件已保存至：\n{final_path}")
            else:
                QMessageBox.warning(
                    self, "路径重定向", f"由于权限或路径问题，已转存至：\n{final_path}"
                )
            self.step_recorded.emit(
                "export_df", p, self.data_pool[p["df_name"]], "导出记录"
            )
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))
