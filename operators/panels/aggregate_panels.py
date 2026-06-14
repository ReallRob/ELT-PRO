"""Operator panels: aggregate_panels."""

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
    normalize_columns,
    pct_change_data,
    pivot_table,
    rank_col,
    sample_data,
    sort_data,
    transpose_data,
)


class GroupPanel(BaseToolPanel):
    theme_color = "#673AB7"
    action_name = "汇总"

    def init_custom_ui(self):
        card1, inner1 = self._make_card("分组依据列")
        self.custom_layout.addWidget(card1)
        self.group_keys_layout = QVBoxLayout()
        self.group_keys_layout.setSpacing(4)
        inner1.addLayout(self.group_keys_layout)
        self.add_group_key_row()
        btn_add_key = QPushButton("+ 添加分组列")
        btn_add_key.setStyleSheet(
            "QPushButton { background: #EDE7F6; border: 1px dashed #B39DDB; "
            "border-radius: 4px; padding: 6px; color: #4527A0; font-size: 12px; }"
            "QPushButton:hover { background: #D1C4E9; }"
        )
        btn_add_key.clicked.connect(lambda: self.add_group_key_row())
        inner1.addWidget(btn_add_key)

        card2, inner2 = self._make_card("聚合统计规则")
        self.custom_layout.addWidget(card2)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner2.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加聚合规则")
        btn_add.setStyleSheet(
            "QPushButton { background: #EDE7F6; border: 1px dashed #B39DDB; "
            "border-radius: 4px; padding: 6px; color: #4527A0; font-size: 12px; }"
            "QPushButton:hover { background: #D1C4E9; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner2.addWidget(btn_add)
        hint = QLabel("sum(求和), mean(平均), max, min, count(计数), first(取第一行)")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        inner2.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.group_keys_layout)
        self.add_group_key_row()
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_group_key_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("分组列")
        col_combo.setObjectName("group_col")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.group_keys_layout.addWidget(row)

    def add_rule_row(self, col="", func="sum", rename=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("运算列", dtype_filter="numeric")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        f_combo = QComboBox()
        f_combo.setObjectName("func")
        f_combo.addItems(["sum", "mean", "max", "min", "count", "first"])
        f_combo.setCurrentText(func)
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("重命名(可选)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(f_combo)
        l.addWidget(r_input)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def set_custom_params(self, p):
        g_keys = p.get("group_key", [])
        if g_keys:
            self.clear_dynamic_layout(self.group_keys_layout)
            for k in g_keys:
                self.add_group_key_row(k)
        rules = p.get("agg_rules", [])
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(r.get("col"), r.get("func"), r.get("rename"))

    def get_custom_params(self):
        g_keys = []
        for i in range(self.group_keys_layout.count()):
            w = self.group_keys_layout.itemAt(i).widget()
            if w:
                combo = w.findChild(QComboBox, "group_col")
                if combo:
                    c = self._get_col_name(combo)
                    if c:
                        g_keys.append(c)
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c = self._get_col_name(w.findChild(QComboBox, "col"))
                f = w.findChild(QComboBox, "func").currentText()
                r = w.findChild(QLineEdit, "rename").text().strip()
                if c:
                    rules.append({"col": c, "func": f, "rename": r})
        return {"group_key": g_keys, "agg_rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["group_key"]:
            return QMessageBox.warning(self, "错误", "缺少必要参数")
        col_dict = {}
        for r in p["agg_rules"]:
            c, f = r["col"], r["func"]
            if c in col_dict:
                (
                    col_dict[c].append(f)
                    if isinstance(col_dict[c], list)
                    else col_dict.update({c: [col_dict[c], f]})
                )
            else:
                col_dict[c] = f
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = group_calc(
                self.data_pool[p["df_name"]], p["group_key"], col_dict, p["col_type"]
            )
            rename_dict = {}
            for rule in p["agg_rules"]:
                if rule["rename"]:
                    actual_cols = normalize_columns(
                        self.data_pool[p["df_name"]], [rule["col"]], p["col_type"]
                    )
                    if actual_cols:
                        rename_dict[f"{actual_cols[0]}_{rule['func']}"] = rule["rename"]
            if rename_dict:
                df = df.rename(columns=rename_dict)
            self.step_recorded.emit("group_calc", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class PivotPanel(BaseToolPanel):
    theme_color = "#8E24AA"
    action_name = "数据透视"

    def init_custom_ui(self):
        card, inner = self._make_card("透视配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("行标签 (可多个):"))
        self.index_layout = QVBoxLayout()
        self.index_layout.setSpacing(4)
        inner.addLayout(self.index_layout)
        self.add_index_row()
        btn_add_idx = QPushButton("+ 添加行标签")
        btn_add_idx.setStyleSheet(
            "QPushButton { background: #F3E5F5; border: 1px dashed #CE93D8; "
            "border-radius: 4px; padding: 6px; color: #7B1FA2; font-size: 12px; }"
            "QPushButton:hover { background: #E1BEE7; }"
        )
        btn_add_idx.clicked.connect(lambda: self.add_index_row())
        inner.addWidget(btn_add_idx)

        inner.addWidget(QLabel("列标签:"))
        self.col_combo = self._make_col_combo("选择列标签列")
        inner.addWidget(self.col_combo)

        inner.addWidget(QLabel("统计值:"))
        self.val_combo = self._make_col_combo("选择统计值列", dtype_filter="numeric")
        inner.addWidget(self.val_combo)

        inner.addWidget(QLabel("聚合方式:"))
        self.agg_combo = QComboBox()
        self.agg_combo.addItems(["sum", "mean", "max", "min", "count", "median"])
        inner.addWidget(self.agg_combo)

        fl = QFormLayout()
        self.fill_input = QLineEdit("0")
        fl.addRow("空值填充:", self.fill_input)
        self.margin_combo = QComboBox()
        self.margin_combo.addItems(["是 (含汇总行列)", "否 (不含汇总)"])
        fl.addRow("汇总行列:", self.margin_combo)
        inner.addLayout(fl)

    def add_index_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("行标签列")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.index_layout.addWidget(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.index_layout)
        self.add_index_row()
        self.fill_input.setText("0")

    def get_custom_params(self):
        idx_cols = []
        for i in range(self.index_layout.count()):
            w = self.index_layout.itemAt(i).widget()
            if w:
                combo = w.findChild(QComboBox)
                if combo:
                    c = self._get_col_name(combo)
                    if c:
                        idx_cols.append(c)
        return {
            "index_cols": idx_cols,
            "columns_col": self._get_col_name(self.col_combo),
            "values_col": self._get_col_name(self.val_combo),
            "aggfunc": self.agg_combo.currentText(),
            "fill_value": (float(self.fill_input.text()) if self.fill_input.text() else 0),
            "margins": self.margin_combo.currentIndex() == 0,
        }

    def set_custom_params(self, p):
        if "index_cols" in p:
            self.clear_dynamic_layout(self.index_layout)
            for c in p["index_cols"]:
                self.add_index_row(c)
        if "columns_col" in p:
            self._set_col_name(self.col_combo, p["columns_col"])
        if "values_col" in p:
            self._set_col_name(self.val_combo, p["values_col"])
        if "aggfunc" in p:
            self.agg_combo.setCurrentText(p["aggfunc"])
        if "fill_value" in p:
            self.fill_input.setText(str(p["fill_value"]))
        if "margins" in p:
            self.margin_combo.setCurrentIndex(0 if p["margins"] else 1)

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["index_cols"] or not p["columns_col"] or not p["values_col"]:
            return QMessageBox.warning(self, "错误", "请填写行标签、列标签和统计值")
        out_name = p["out_name"] or f"{p['df_name']}_透视"
        try:
            df = pivot_table(self.data_pool[p["df_name"]],
                p["index_cols"], p["columns_col"], p["values_col"],
                p["aggfunc"], p["fill_value"], p["margins"], p["col_type"])
            self.step_recorded.emit("pivot_table", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class MeltPanel(BaseToolPanel):
    theme_color = "#26A69A"
    action_name = "逆透视"

    def init_custom_ui(self):
        card, inner = self._make_card("逆透视配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("保留列 (留空=自动使用非融合列):"))
        self.id_layout = QVBoxLayout()
        self.id_layout.setSpacing(4)
        inner.addLayout(self.id_layout)
        self.add_id_row()
        btn_add_id = QPushButton("+ 添加保留列")
        btn_add_id.setStyleSheet(
            "QPushButton { background: #E0F2F1; border: 1px dashed #80CBC4; "
            "border-radius: 4px; padding: 6px; color: #00695C; font-size: 12px; }"
            "QPushButton:hover { background: #B2DFDB; }"
        )
        btn_add_id.clicked.connect(lambda: self.add_id_row())
        inner.addWidget(btn_add_id)

        inner.addWidget(QLabel("融合列 (宽表变长表，这些列的值会汇入一列):"))
        self.val_layout = QVBoxLayout()
        self.val_layout.setSpacing(4)
        inner.addLayout(self.val_layout)
        self.add_val_row()
        btn_add_val = QPushButton("+ 添加融合列")
        btn_add_val.setStyleSheet(
            "QPushButton { background: #E0F2F1; border: 1px dashed #80CBC4; "
            "border-radius: 4px; padding: 6px; color: #00695C; font-size: 12px; }"
            "QPushButton:hover { background: #B2DFDB; }"
        )
        btn_add_val.clicked.connect(lambda: self.add_val_row())
        inner.addWidget(btn_add_val)

        fl = QFormLayout()
        self.var_input = QLineEdit("变量")
        fl.addRow("新列名(变量):", self.var_input)
        self.val_name_input = QLineEdit("值")
        fl.addRow("新列名(值):", self.val_name_input)
        inner.addLayout(fl)

    def add_id_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("保留列")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.id_layout.addWidget(row)

    def add_val_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("融合列")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.val_layout.addWidget(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.id_layout)
        self.add_id_row()
        self.clear_dynamic_layout(self.val_layout)
        self.add_val_row()
        self.var_input.setText("变量")
        self.val_name_input.setText("值")

    def _gather_cols(self, layout):
        cols = []
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w:
                combo = w.findChild(QComboBox)
                if combo:
                    c = self._get_col_name(combo)
                    if c:
                        cols.append(c)
        return cols

    def get_custom_params(self):
        return {
            "id_cols": self._gather_cols(self.id_layout),
            "value_cols": self._gather_cols(self.val_layout),
            "var_name": self.var_input.text().strip() or "变量",
            "value_name": self.val_name_input.text().strip() or "值",
        }

    def set_custom_params(self, p):
        if "id_cols" in p:
            self.clear_dynamic_layout(self.id_layout)
            for c in p["id_cols"]:
                self.add_id_row(c)
        if "value_cols" in p:
            self.clear_dynamic_layout(self.val_layout)
            for c in p["value_cols"]:
                self.add_val_row(c)
        if "var_name" in p:
            self.var_input.setText(p["var_name"])
        if "value_name" in p:
            self.val_name_input.setText(p["value_name"])

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["value_cols"]:
            return QMessageBox.warning(self, "错误", "请填写融合列")
        out_name = p["out_name"] or f"{p['df_name']}_逆透视"
        try:
            df = melt_table(self.data_pool[p["df_name"]],
                p["id_cols"], p["value_cols"], p["var_name"], p["value_name"], p["col_type"])
            self.step_recorded.emit("melt_table", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class DescribePanel(BaseToolPanel):
    use_type = False
    theme_color = "#3F51B5"
    action_name = "描述统计"

    def init_custom_ui(self):
        card, inner = self._make_card("分位数设置")
        self.custom_layout.addWidget(card)
        self.pct_layout = QVBoxLayout()
        self.pct_layout.setSpacing(4)
        inner.addLayout(self.pct_layout)
        self.add_pct_row("0.25")
        self.add_pct_row("0.5")
        self.add_pct_row("0.75")
        btn_add = QPushButton("+ 添加分位数")
        btn_add.setStyleSheet(
            "QPushButton { background: #E8EAF6; border: 1px dashed #9FA8DA; "
            "border-radius: 4px; padding: 6px; color: #283593; font-size: 12px; }"
            "QPushButton:hover { background: #C5CAE9; }"
        )
        btn_add.clicked.connect(lambda: self.add_pct_row())
        inner.addWidget(btn_add)

        hint_card, hint_inner = self._make_card()
        self.custom_layout.addWidget(hint_card)
        hint = QLabel("输出均值/标准差/最大最小/分位数等统计信息。")
        hint.setStyleSheet("color: #888; font-size: 11px; border: none;")
        hint.setWordWrap(True)
        hint_inner.addWidget(hint)

    def add_pct_row(self, val=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        inp = QLineEdit(str(val))
        inp.setObjectName("pct_val")
        inp.setPlaceholderText("如: 0.25")
        inp.setMinimumWidth(80)
        rm = QPushButton("×")
        rm.setFixedWidth(25)
        rm.clicked.connect(row.deleteLater)
        l.addWidget(inp)
        l.addWidget(rm)
        l.addStretch()
        self.pct_layout.addWidget(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.pct_layout)
        self.add_pct_row("0.25")
        self.add_pct_row("0.5")
        self.add_pct_row("0.75")

    def get_custom_params(self):
        pcts = []
        for i in range(self.pct_layout.count()):
            w = self.pct_layout.itemAt(i).widget()
            if w:
                inp = w.findChild(QLineEdit, "pct_val")
                if inp:
                    t = inp.text().strip()
                    if t:
                        try:
                            pcts.append(float(t))
                        except ValueError:
                            pass
        return {"percentiles": pcts if pcts else None}

    def set_custom_params(self, p):
        if "percentiles" in p and p["percentiles"]:
            self.pct_input.setText(", ".join(str(x) for x in p["percentiles"]))

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "缺少目标表")
        out_name = p["out_name"] or f"{p['df_name']}_描述"
        try:
            df = describe_data(self.data_pool[p["df_name"]], p.get("percentiles"))
            self.step_recorded.emit("describe_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))
