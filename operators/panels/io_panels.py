"""Operator panels for importing and exporting tabular data."""

import os

from core.workflow.schema import default_load_output_name

from PyQt5.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
)

from core.dataframe_ops import CSV_SHEET_LABEL
from operators.base_panel import BaseToolPanel, QLineEdit
from operators.panels.background_scanners import ExcelSheetScanThread


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
        self._last_auto_output_name = ""
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
        current = self.sheet_combo.currentText()
        path = str(path or "").strip()
        self._sheet_scan_generation = getattr(self, "_sheet_scan_generation", 0) + 1
        generation = self._sheet_scan_generation
        old_thread = getattr(self, "_sheet_scan_thread", None)
        if old_thread is not None:
            self._retain_sheet_scan_thread(old_thread)
            self._sheet_scan_thread = None
            self.sheet_combo.setEnabled(True)
        if not path:
            self._set_combo_items_preserving_text(self.sheet_combo, [], current)
            return
        if not path.lower().endswith((".xlsx", ".xls")):
            self._set_combo_items_preserving_text(self.sheet_combo, [CSV_SHEET_LABEL], current)
            self.auto_update_out_name(self.sheet_combo.currentText())
            return

        self._set_combo_items_preserving_text(self.sheet_combo, ["正在读取工作表..."], current)
        self.sheet_combo.setEnabled(False)
        thread = ExcelSheetScanThread(generation, path, self)
        self._sheet_scan_thread = thread
        thread.finished_signal.connect(self._on_sheet_scan_finished)
        thread.finished.connect(lambda t=thread: self._forget_sheet_scan_thread(t))
        thread.start()

    def _retain_sheet_scan_thread(self, thread):
        retained = getattr(self, "_retained_sheet_scan_threads", None)
        if retained is None:
            retained = []
            self._retained_sheet_scan_threads = retained
        if thread not in retained:
            retained.append(thread)

    def _forget_sheet_scan_thread(self, thread):
        if thread is getattr(self, "_sheet_scan_thread", None):
            self._sheet_scan_thread = None
            self.sheet_combo.setEnabled(True)
        try:
            self._retained_sheet_scan_threads.remove(thread)
        except (AttributeError, ValueError):
            pass

    def _on_sheet_scan_finished(self, generation, path, sheets, error):
        if generation != getattr(self, "_sheet_scan_generation", None):
            return
        if str(path or "") != self.path_input.text().strip():
            return
        current = self.sheet_combo.currentText()
        if current == "正在读取工作表...":
            current = ""
        if error:
            self._set_combo_items_preserving_text(self.sheet_combo, [], current)
            self.sheet_combo.setToolTip(f"读取工作表失败: {error}")
            return
        self.sheet_combo.setToolTip("")
        self._set_combo_items_preserving_text(self.sheet_combo, list(sheets or []), current)
        self.auto_update_out_name(self.sheet_combo.currentText())

    def auto_update_out_name(self, text):
        if not text:
            return
        auto_name = ""
        if text == CSV_SHEET_LABEL:
            if self.path_input.text():
                auto_name = os.path.basename(self.path_input.text()).split(".")[0]
        else:
            auto_name = str(text).strip()
        self._set_auto_output_name(auto_name)

    def _set_auto_output_name(self, auto_name):
        auto_name = str(auto_name or "").strip()
        if not auto_name or not hasattr(self, "out_input"):
            return
        current = self.out_input.text().strip()
        last_auto = str(getattr(self, "_last_auto_output_name", "") or "").strip()
        if current and current != last_auto and current != auto_name:
            return
        self.out_input.setText(auto_name)
        self._last_auto_output_name = auto_name

    def _load_output_name(self, params):
        explicit = self.out_input.text().strip() if hasattr(self, "out_input") else ""
        return explicit or default_load_output_name(params, "数据源")

    def get_custom_params(self):
        params = {
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
        output_name = self._load_output_name(params)
        if params["file_path"]:
            params["io_prefs"] = {
                "output_name": output_name,
                "output_data_type": "table",
            }
        return params

    def set_custom_params(self, p):
        saved_output = self._saved_output_for_basic_field(p)
        saved_output_name = str((saved_output or {}).get("name") or "").strip()
        if "file_path" in p:
            self.path_input.setText(p["file_path"])
            self.update_sheets(p["file_path"])
        if "sheet_name" in p:
            self._set_combo_items_preserving_text(
                self.sheet_combo,
                [self.sheet_combo.itemText(i) for i in range(self.sheet_combo.count())],
                str(p["sheet_name"]),
            )
        if saved_output_name and hasattr(self, "out_input"):
            self.out_input.setText(saved_output_name)
        default_output_name = default_load_output_name(p, "数据源")
        if saved_output_name and saved_output_name == default_output_name:
            self._last_auto_output_name = saved_output_name
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
        self._last_auto_output_name = ""
        self.path_input.clear()
        self.sheet_combo.clear()
        self.skip_input.setText("0")
        self.start_col_input.setText("1")
        self.ncols_input.clear()
        self.header_combo.setCurrentText("是")
        self.nrows_input.clear()

class ExportNodePanel(BaseToolPanel):
    use_type = False
    use_out = False
    theme_color = "#607D8B"
    action_name = "导出"

    def _default_output_name(self, input_name):
        return "导出记录"

    def init_custom_ui(self):
        card, inner = self._make_card("导出配置")
        self.custom_layout.addWidget(card)

        fl = QFormLayout()
        fl.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        fl.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.fname_input = QLineEdit("Export_Result.xlsx")
        fl.addRow("导出文件名:", self.fname_input)

        self.export_mode_combo = QComboBox()
        self.export_mode_combo.addItem("导出为多个 sheet", "multi_sheet")
        self.export_mode_combo.addItem("合并为一个 sheet", "single_sheet")
        fl.addRow("导出方式:", self.export_mode_combo)

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

        hint = self._make_hint_label("支持 .xlsx 和 .csv 格式。多个 sheet 模式会自动使用 .xlsx。")
        inner.addWidget(hint)

    def browse_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择保存目录", "")
        if folder:
            self.dir_input.setText(folder)

    def clear_custom_ui(self):
        self.fname_input.setText("Export_Result.xlsx")
        self.export_mode_combo.setCurrentIndex(0)
        self.dir_input.clear()

    def set_custom_params(self, p):
        if "file_name" in p:
            self.fname_input.setText(p["file_name"])
        if "folder_path" in p:
            self.dir_input.setText(p["folder_path"])
        mode = str(p.get("export_mode") or "multi_sheet")
        index = self.export_mode_combo.findData(mode)
        self.export_mode_combo.setCurrentIndex(index if index >= 0 else 0)

    def get_custom_params(self):
        return {
            "file_name": self.fname_input.text().strip(),
            "folder_path": self.dir_input.text().strip(),
            "export_mode": self.export_mode_combo.currentData() or "multi_sheet",
        }
