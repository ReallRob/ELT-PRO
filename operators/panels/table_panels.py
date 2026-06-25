"""Operator panels: table_panels."""

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


class JoinPanel(BaseToolPanel):
    use_df = False
    theme_color = "#4CAF50"
    action_name = "连接"

    def _refresh_col_combos(self):
        """JoinPanel 使用右表(df2_combo)的列名"""
        if self._panel_update_depth:
            self._pending_col_combo_refresh = True
            return
        self._refresh_col_combos_now()

    def _refresh_col_combos_now(self):
        """JoinPanel 使用右表(df2_combo)的列名"""
        if not hasattr(self, "_col_combos"):
            return
        df_name = self.df2_combo.currentText() if hasattr(self, "df2_combo") else ""
        df = self.data_pool.get(df_name) if df_name else None
        self._refresh_col_combos_from_df(df)

    def init_custom_ui(self):
        self.df1_combo = QComboBox()
        self.df2_combo = QComboBox()
        self.df2_combo.currentTextChanged.connect(self._refresh_col_combos)
        self.combo_boxes_to_update.extend([self.df1_combo, self.df2_combo])
        self.top_form.insertRow(0, "主表 (左):", self.df1_combo)
        self.top_form.insertRow(1, "匹配表 (右):", self.df2_combo)
        self.l_key = QLineEdit()
        self.r_key = QLineEdit()
        self.top_form.addRow("左表匹配键:", self.l_key)
        self.top_form.addRow("右表匹配键:", self.r_key)
        card, inner = self._make_card("提取右表列及重命名")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = self._make_add_button("+ 添加提取列")
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)
        hint = self._make_hint_label("类似于 VLOOKUP，按匹配键把右表字段提取到主表。")
        inner.addWidget(hint)

    def clear_custom_ui(self):
        self.l_key.clear()
        self.r_key.clear()
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", rename=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(6)
        col_combo = self._make_col_combo("右表列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("重命名(可选)")
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
        l.addWidget(col_combo, stretch=1)
        l.addWidget(r_input, stretch=1)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def set_custom_params(self, p):
        if "df1_name" in p:
            self.df1_combo.setCurrentText(p["df1_name"])
        if "df2_name" in p:
            self.df2_combo.setCurrentText(p["df2_name"])
        if "l_key" in p:
            self.l_key.setText(p["l_key"])
        if "r_key" in p:
            self.r_key.setText(p["r_key"])
        get_cols, col_names = p.get("get_cols", []), p.get("col_names", [])
        if get_cols:
            self.clear_dynamic_layout(self.rules_layout)
            for i, c in enumerate(get_cols):
                r = col_names[i] if col_names and i < len(col_names) else ""
                self.add_rule_row(c, r)

    def get_custom_params(self):
        get_cols, col_names = [], []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c = self._get_col_name(w.findChild(QComboBox, "col"))
                r = w.findChild(QLineEdit, "rename").text().strip()
                if c:
                    get_cols.append(c)
                    col_names.append(r)
        return {
            "df1_name": self.df1_combo.currentText(),
            "df2_name": self.df2_combo.currentText(),
            "l_key": self.l_key.text().strip(),
            "r_key": self.r_key.text().strip(),
            "get_cols": get_cols,
            "col_names": col_names,
        }

    def execute(self):
        p = self.get_params()
        if not p["df1_name"] or not p["df2_name"]:
            return QMessageBox.warning(self, "错误", "请选择表")
        if not p["get_cols"]:
            return QMessageBox.warning(self, "错误", "请配置提取列")
        out_name = p["out_name"] or f"{p['df1_name']}_{self.action_name}"
        try:
            actual_cols = normalize_columns(
                self.data_pool[p["df2_name"]], p["get_cols"], p["col_type"]
            )
            final_names = [
                p["col_names"][i] if p["col_names"][i] else actual_cols[i]
                for i in range(len(actual_cols))
            ]
            df = left_join(
                self.data_pool[p["df1_name"]],
                self.data_pool[p["df2_name"]],
                p["l_key"],
                p["r_key"],
                p["get_cols"],
                key_type=p["col_type"],
                col_names=final_names,
            )
            self.step_recorded.emit("left_join", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class ConcatPanel(BaseToolPanel):
    use_df = False
    theme_color = "#5C6BC0"
    action_name = "纵向拼接"

    def init_custom_ui(self):
        self.df1_combo = QComboBox()
        self.df2_combo = QComboBox()
        self.combo_boxes_to_update.extend([self.df1_combo, self.df2_combo])
        self.top_form.insertRow(0, "表1 (上方):", self.df1_combo)
        self.top_form.insertRow(1, "表2 (下方):", self.df2_combo)
        self.ignore_idx_combo = QComboBox()
        self.ignore_idx_combo.addItems(["是 (重建索引)", "否 (保留原索引)"])
        self.top_form.addRow("重建索引:", self.ignore_idx_combo)

        hint_card, hint_inner = self._make_card()
        self.custom_layout.addWidget(hint_card)
        hint = self._make_hint_label("纵向拼接将两个表上下接起来，类似 SQL 的 UNION ALL。")
        hint_inner.addWidget(hint)

    def clear_custom_ui(self):
        pass

    def get_custom_params(self):
        return {
            "df1_name": self.df1_combo.currentText(),
            "df2_name": self.df2_combo.currentText(),
            "ignore_index": self.ignore_idx_combo.currentIndex() == 0,
        }

    def set_custom_params(self, p):
        if "df1_name" in p:
            self.df1_combo.setCurrentText(p["df1_name"])
        if "df2_name" in p:
            self.df2_combo.setCurrentText(p["df2_name"])
        if "ignore_index" in p:
            self.ignore_idx_combo.setCurrentIndex(0 if p["ignore_index"] else 1)

    def execute(self):
        p = self.get_params()
        if not p["df1_name"] or not p["df2_name"]:
            return QMessageBox.warning(self, "错误", "请选择两个表")
        out_name = p["out_name"] or f"{p['df1_name']}_拼接"
        try:
            df = concat_rows(self.data_pool[p["df1_name"]],
                self.data_pool[p["df2_name"]], p["ignore_index"])
            self.step_recorded.emit("concat_rows", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))
