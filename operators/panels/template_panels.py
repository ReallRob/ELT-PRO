"""Operator panels: template_panels."""

import os
import sys
import pandas as pd
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from operators.base_panel import BaseToolPanel, ParameterTextEdit, QLineEdit
from core.dataframe_ops import (
    calc_col,
    clean_data,
    concat_rows,
    cumsum_data,
    describe_data,
    drop_duplicates,
    export_df,
    filter_data,
    get_col_data,
    group_calc,
    left_join,
    melt_table,
    pct_change_data,
    pivot_table,
    rank_col,
    sample_data,
    sort_data,
    transpose_data,
)


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
        fl.addRow("模板文件:", path_layout)
        inner.addLayout(fl)

        self.info_label = QLabel("选择模板后自动扫描结构")
        self.info_label.setStyleSheet(
            "color: #888; font-size: 12px; padding: 8px; "
            "background: #FAFAFA; border-radius: 4px; border: none;"
        )
        inner.addWidget(self.info_label)

    def _browse_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择模板文件", "", "Excel (*.xlsx)")
        if not path:
            return
        self.template_input.setText(path)
        try:
            from template_engine import load_template
            _, meta = load_template(path)
            lines = [f"文件: {os.path.basename(path)}"]
            for sn, info in meta["sheets"].items():
                lines.append(f"  Sheet [{sn}]: {info['max_row']} 行 x {info['max_col']} 列")
            self.info_label.setText("\n".join(lines))
        except Exception as e:
            self.info_label.setText(f"加载失败: {e}")

    def clear_custom_ui(self):
        self.template_input.clear()
        self.info_label.setText("选择模板后自动扫描结构")

    def get_custom_params(self):
        return {"template_path": self.template_input.text().strip()}

    def set_custom_params(self, p):
        if "template_path" in p:
            self.template_input.setText(p["template_path"])

    def execute(self):
        p = self.get_params()
        if not p["template_path"] or not os.path.exists(p["template_path"]):
            return QMessageBox.warning(self, "错误", "请选择有效的模板文件！")
        try:
            from template_engine import load_template
            wb, meta = load_template(p["template_path"])
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
        self.template_combo = QComboBox()
        self.combo_boxes_to_update.append(self.template_combo)
        self.top_form.insertRow(0, "目标模板:", self.template_combo)
        self.sheet_combo = QComboBox()
        self.top_form.addRow("目标工作表:", self.sheet_combo)
        self.chk_header = QComboBox()
        self.chk_header.addItems(["是 (写入表头)", "否 (仅写数据)"])
        self.top_form.addRow("写入表头:", self.chk_header)

        pos_card, pos_inner = self._make_card("插入位置")
        self.custom_layout.addWidget(pos_card)
        pos_layout = QHBoxLayout()
        self.start_row_input = QLineEdit("max_row + 1")
        self.start_row_input.setPlaceholderText("如: max_row+1")
        self.start_row_input.setMinimumWidth(100)
        self.start_col_input = QLineEdit("1")
        self.start_col_input.setPlaceholderText("如: 1")
        self.start_col_input.setMinimumWidth(100)
        pos_layout.addWidget(QLabel("起始行:"))
        pos_layout.addWidget(self.start_row_input)
        pos_layout.addWidget(QLabel("起始列:"))
        pos_layout.addWidget(self.start_col_input)
        pos_inner.addLayout(pos_layout)
        hint = QLabel("可用变量: max_row, max_col。max_row+1=追加到末尾")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        pos_inner.addWidget(hint)

        col_card, col_inner = self._make_card("提取列及重命名")
        self.custom_layout.addWidget(col_card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        col_inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加提取列")
        btn_add.setStyleSheet(
            "QPushButton { background: #FFF3E0; border: 1px dashed #FFB74D; "
            "border-radius: 4px; padding: 6px; color: #E65100; font-size: 12px; }"
            "QPushButton:hover { background: #FFE0B2; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        col_inner.addWidget(btn_add)

    def _refresh_sheet_combo(self):
        self.sheet_combo.clear()
        tmpl_name = self.template_combo.currentText()
        if tmpl_name and tmpl_name in self.data_pool:
            entry = self.data_pool[tmpl_name]
            if hasattr(entry, "attrs") and entry.attrs.get("_is_template"):
                sheets = entry.attrs.get("_sheets", {})
                for sn in sheets:
                    self.sheet_combo.addItem(sn)

    def clear_custom_ui(self):
        self.start_row_input.setText("max_row + 1")
        self.start_col_input.setText("1")
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", rename=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("选择列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("重命名(可选)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(r_input)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def update_combos(self, table_names):
        super().update_combos(table_names)
        # 筛选模板类型的条目
        tmpl_names = []
        for name, entry in self.data_pool.items():
            if hasattr(entry, "attrs") and entry.attrs.get("_is_template"):
                tmpl_names.append(name)
        cur = self.template_combo.currentText()
        self.template_combo.clear()
        self.template_combo.addItems(tmpl_names)
        if cur in tmpl_names:
            self.template_combo.setCurrentText(cur)
        self._refresh_sheet_combo()

    def set_custom_params(self, p):
        if "template_name" in p:
            self.template_combo.setCurrentText(p["template_name"])
        if "sheet_name" in p:
            self.sheet_combo.setCurrentText(p["sheet_name"])
        if "start_row" in p:
            self.start_row_input.setText(str(p["start_row"]))
        if "start_col" in p:
            self.start_col_input.setText(str(p["start_col"]))
        if "write_header" in p:
            self.chk_header.setCurrentIndex(0 if p["write_header"] else 1)
        col_list, col_names = p.get("col_list", []), p.get("col_names", [])
        if col_list:
            self.clear_dynamic_layout(self.rules_layout)
            for i, c in enumerate(col_list):
                r = col_names[i] if col_names and i < len(col_names) else ""
                self.add_rule_row(c, r)

    def get_custom_params(self):
        clist, rlist = [], []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c = self._get_col_name(w.findChild(QComboBox, "col"))
                r = w.findChild(QLineEdit, "rename").text().strip()
                if c:
                    clist.append(c)
                    rlist.append(r)
        return {
            "template_name": self.template_combo.currentText(),
            "sheet_name": self.sheet_combo.currentText(),
            "start_row": self.start_row_input.text().strip(),
            "start_col": self.start_col_input.text().strip(),
            "write_header": self.chk_header.currentIndex() == 0,
            "col_list": clist,
            "col_names": rlist,
        }

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["template_name"]:
            return QMessageBox.warning(self, "错误", "请连接上游数据表和模板表")
        tmpl_entry = self.data_pool.get(p["template_name"])
        if tmpl_entry is None or not (hasattr(tmpl_entry, "attrs") and tmpl_entry.attrs.get("_is_template")):
            return QMessageBox.warning(self, "错误", "模板表无效")
        template_path = tmpl_entry.attrs.get("_template_path")
        if not template_path or not os.path.exists(template_path):
            return QMessageBox.warning(self, "错误", f"模板文件不存在: {template_path}")

        try:
            from template_engine import load_template, insert_into_template, save_template
            import pandas as pd

            wb, _ = load_template(template_path)
            df = self.data_pool[p["df_name"]]
            cols = p["col_list"] if p["col_list"] else ["*"]
            col_names = p["col_names"]

            # 列重命名
            if col_names and any(col_names):
                actual_cols = [c for c in cols if c != "*"]
                if actual_cols:
                    available = [c for c in actual_cols if c in df.columns]
                else:
                    available = list(df.columns)
                rename_map = {}
                for i, c in enumerate(available):
                    if i < len(col_names) and col_names[i]:
                        rename_map[c] = col_names[i]
                if rename_map:
                    df = df.rename(columns=rename_map)

            success, msg = insert_into_template(
                wb, df, p["sheet_name"], p["start_row"], p["start_col"],
                columns=cols, write_header=p["write_header"], inherit_style=True,
            )
            if not success:
                return QMessageBox.critical(self, "插入失败", msg)

            default_dir = (
                Path(sys.executable).parent
                if getattr(sys, "frozen", False)
                else Path(__file__).parent.absolute()
            )
            out_path = str(default_dir / f"template_filled_{p['out_name'] or 'result'}.xlsx")
            save_template(wb, out_path)

            QMessageBox.information(self, "完成", f"{msg}\n\n已保存至: {out_path}")
            self.step_recorded.emit("insert_block", p, df, p["out_name"] or "插入结果")
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))
