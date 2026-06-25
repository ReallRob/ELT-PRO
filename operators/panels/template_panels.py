"""Operator panels: template_panels."""

import os
import pandas as pd
from PyQt5.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
)

from operators.base_panel import BaseToolPanel, QLineEdit


class ImportTemplatePanel(BaseToolPanel):
    use_df = False
    use_type = False
    theme_color = "#795548"
    action_name = "导入模板"

    def init_custom_ui(self):
        card, inner = self._make_card("模板配置")
        self.custom_layout.addWidget(card)

        path_layout = QHBoxLayout()
        self.template_input = QLineEdit()
        self.template_input.set_parameter_enabled(False)
        self.template_input.setPlaceholderText("选择模板文件 (.xlsx)")
        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self._browse_template)
        path_layout.addWidget(self.template_input)
        path_layout.addWidget(btn_browse)

        fl = QFormLayout()
        fl.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        fl.setRowWrapPolicy(QFormLayout.WrapLongRows)
        fl.addRow("模板文件:", path_layout)

        save_layout = QHBoxLayout()
        self.output_path_input = QLineEdit()
        self.output_path_input.setPlaceholderText("可选，留空则有插入区域时自动保存到运行目录")
        btn_save = QPushButton("保存到")
        btn_save.clicked.connect(self._browse_output_path)
        save_layout.addWidget(self.output_path_input)
        save_layout.addWidget(btn_save)
        fl.addRow("输出文件:", save_layout)
        inner.addLayout(fl)

        self.info_label = QLabel("选择模板后自动扫描结构")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
        inner.addWidget(self.info_label)

    def _browse_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择模板文件", "", "Excel (*.xlsx)")
        if not path:
            return
        self.template_input.setText(path)
        try:
            from template_engine import close_workbook, load_template
            wb, meta = load_template(path)
            close_workbook(wb)
            lines = [f"文件: {os.path.basename(path)}"]
            for sn, info in meta["sheets"].items():
                lines.append(f"  Sheet [{sn}]: {info['max_row']} 行 x {info['max_col']} 列")
            self.info_label.setText("\n".join(lines))
        except Exception as e:
            self.info_label.setText(f"加载失败: {e}")

    def _browse_output_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存填充后的模板", "template_filled.xlsx", "Excel (*.xlsx)"
        )
        if path:
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            self.output_path_input.setText(path)

    def clear_custom_ui(self):
        self.template_input.clear()
        self.output_path_input.clear()
        self.info_label.setText("选择模板后自动扫描结构")

    def get_custom_params(self):
        return {
            "template_path": self.template_input.text().strip(),
            "output_path": self.output_path_input.text().strip(),
        }

    def set_custom_params(self, p):
        if "template_path" in p:
            self.template_input.setText(p["template_path"])
        if "output_path" in p:
            self.output_path_input.setText(p["output_path"])

    def execute(self):
        p = self.get_params()
        if not p["template_path"] or not os.path.exists(p["template_path"]):
            return QMessageBox.warning(self, "错误", "请选择有效的模板文件！")
        try:
            from template_engine import close_workbook, load_template
            wb, meta = load_template(p["template_path"])
            close_workbook(wb)
            out_name = p["out_name"] or f"模板_{os.path.basename(p['template_path']).split('.')[0]}"
            # 存储 metadata DataFrame 供预览 + 标记 _is_template
            import pandas as pd
            rows = []
            for sn, info in meta["sheets"].items():
                rows.append({"工作表": sn, "行数": info["max_row"], "列数": info["max_col"]})
            df = pd.DataFrame(rows)
            df.attrs["_is_template"] = True
            df.attrs["_template_path"] = p["template_path"]
            df.attrs["_sheets"] = meta["sheets"]
            self.step_recorded.emit("import_template", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))


class InsertBlockPanel(BaseToolPanel):
    use_type = False
    theme_color = "#FF6F00"
    action_name = "插入模板"

    def init_custom_ui(self):
        self.sheet_input = QLineEdit()
        self.sheet_input.setPlaceholderText("留空则写入模板第一个工作表")
        self.top_form.addRow("目标工作表:", self.sheet_input)
        self.chk_header = QComboBox()
        self.chk_header.addItems(["是 (写入表头)", "否 (仅写数据)"])
        self.top_form.addRow("写入表头:", self.chk_header)

        pos_card, pos_inner = self._make_card("插入位置")
        self.custom_layout.addWidget(pos_card)
        pos_form = QFormLayout()
        pos_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        pos_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        pos_form.setHorizontalSpacing(8)
        pos_form.setVerticalSpacing(8)
        self.start_row_input = QLineEdit()
        self.start_row_input.setPlaceholderText("必填，如 5")
        self.start_row_input.setMinimumWidth(72)
        self.start_col_input = QLineEdit()
        self.start_col_input.setPlaceholderText("必填，如 A")
        self.start_col_input.setMinimumWidth(72)
        self.end_row_input = QLineEdit()
        self.end_row_input.setPlaceholderText("可选，如 20")
        self.end_row_input.setMinimumWidth(72)
        self.end_col_input = QLineEdit()
        self.end_col_input.setPlaceholderText("可选，如 D")
        self.end_col_input.setMinimumWidth(72)
        pos_form.addRow("起始行:", self.start_row_input)
        pos_form.addRow("起始列:", self.start_col_input)
        pos_form.addRow("结束行:", self.end_row_input)
        pos_form.addRow("结束列:", self.end_col_input)
        pos_inner.addLayout(pos_form)

    def clear_custom_ui(self):
        self.sheet_input.clear()
        self.start_row_input.clear()
        self.start_col_input.clear()
        self.end_row_input.clear()
        self.end_col_input.clear()

    def update_combos(self, table_names):
        super().update_combos(table_names)
        self._suggest_sheet_from_loaded_templates()

    def _suggest_sheet_from_loaded_templates(self):
        if self.sheet_input.text().strip():
            return
        for entry in self.data_pool.values():
            if hasattr(entry, "attrs") and entry.attrs.get("_is_template"):
                sheets = entry.attrs.get("_sheets", {})
                first_sheet = next(iter(sheets), "")
                if first_sheet:
                    self.sheet_input.setText(first_sheet)
                    return

    def set_custom_params(self, p):
        if "sheet_name" in p:
            self.sheet_input.setText(p["sheet_name"])
        if "start_row" in p:
            self.start_row_input.setText(str(p["start_row"]))
        if "end_row" in p:
            self.end_row_input.setText(str(p["end_row"]))
        if "start_col" in p:
            self.start_col_input.setText(str(p["start_col"]))
        if "end_col" in p:
            self.end_col_input.setText(str(p["end_col"]))
        if "write_header" in p:
            self.chk_header.setCurrentIndex(0 if p["write_header"] else 1)

    def get_custom_params(self):
        return {
            "sheet_name": self.sheet_input.text().strip(),
            "start_row": self.start_row_input.text().strip(),
            "end_row": self.end_row_input.text().strip(),
            "start_col": self.start_col_input.text().strip(),
            "end_col": self.end_col_input.text().strip(),
            "write_header": self.chk_header.currentIndex() == 0,
        }

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "请从左侧连接上游数据表")
        if not p["start_row"] or not p["start_col"]:
            return QMessageBox.warning(self, "错误", "请填写插入开始行和开始列")
        try:
            df = self.data_pool[p["df_name"]]
            preview_df = pd.DataFrame(
                [
                    {
                        "工作表": p.get("sheet_name") or "模板首个工作表",
                        "开始行": p.get("start_row"),
                        "结束行": p.get("end_row") or "按数据大小",
                        "开始列": p.get("start_col"),
                        "结束列": p.get("end_col") or "按数据大小",
                        "写入表头": "是" if p.get("write_header") else "否",
                        "数据行数": len(df),
                        "数据列数": len(df.columns),
                    }
                ]
            )
            QMessageBox.information(
                self,
                "已准备",
                "插入区域已记录。全量执行时，请将此节点右侧连接到导入模板节点。"
            )
            self.step_recorded.emit("insert_block", p, preview_df, p["out_name"] or "插入区域")
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))
