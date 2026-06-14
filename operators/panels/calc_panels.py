"""Operator panels: calc_panels."""

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


class RankPanel(BaseToolPanel):
    theme_color = "#2196F3"
    action_name = "排名"

    def init_custom_ui(self):
        card, inner = self._make_card("排名规则")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(6)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加排名规则")
        btn_add.setStyleSheet(
            "QPushButton { background: #E3F2FD; border: 1px dashed #90CAF9; "
            "border-radius: 4px; padding: 6px; color: #0D47A1; font-size: 12px; }"
            "QPushButton:hover { background: #BBDEFB; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)
        hint = QLabel(
            "min(中国式1,2,2,4) | dense(密集1,2,2,3) | max(1,3,3,4) | average | first(顺延)"
        )
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        inner.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", method="min", asc=True, rename=""):
        container = QWidget()
        container.setStyleSheet(
            "background-color: #F8F9FA; border: 1px solid #E0E0E0; border-radius: 4px;"
        )
        v_layout = QVBoxLayout(container)
        v_layout.setContentsMargins(5, 5, 5, 5)
        v_layout.setSpacing(4)
        h1 = QHBoxLayout()
        h1.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("排序列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("新列名 (必填)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.setStyleSheet("border:none; color: red;")
        btn_rm.clicked.connect(container.deleteLater)
        h1.addWidget(col_combo)
        h1.addWidget(QLabel("->"))
        h1.addWidget(r_input)
        h1.addWidget(btn_rm)
        h2 = QHBoxLayout()
        h2.setContentsMargins(0, 0, 0, 0)
        m_combo = QComboBox()
        m_combo.setObjectName("method")
        m_combo.addItems(["min", "dense", "max", "average", "first"])
        self._set_combo_by_prefix(m_combo, method.split(" ")[0])
        asc_combo = QComboBox()
        asc_combo.setObjectName("asc")
        asc_combo.addItems(["升序", "降序"])
        asc_combo.setCurrentIndex(0 if asc else 1)
        h2.addWidget(m_combo)
        h2.addWidget(asc_combo)
        v_layout.addLayout(h1)
        v_layout.addLayout(h2)
        self.rules_layout.addWidget(container)

    def set_custom_params(self, p):
        rules = p.get("rules", [])
        if not rules and "rank_cols" in p:
            for c in p.get("rank_cols", []):
                rules.append(
                    {
                        "col": c,
                        "method": "min",
                        "ascending": p.get("ascending", True),
                        "rename": "",
                    }
                )
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(
                    r.get("col"),
                    r.get("method", "min"),
                    r.get("ascending", True),
                    r.get("rename", ""),
                )

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                col_combo = w.findChild(QComboBox, "col")
                c = self._get_col_name(col_combo) if col_combo else ""
                r = w.findChild(QLineEdit, "rename").text().strip()
                m, asc = (
                    w.findChild(QComboBox, "method").currentText(),
                    w.findChild(QComboBox, "asc").currentIndex() == 0,
                )
                if c:
                    rules.append({"col": c, "method": m, "ascending": asc, "rename": r})
        return {"rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["rules"]:
            return QMessageBox.warning(self, "错误", "参数不完整")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = self.data_pool[p["df_name"]].copy()
            for rule in p["rules"]:
                df = rank_col(
                    df,
                    [rule["col"]],
                    [rule["rename"]] if rule["rename"] else [],
                    col_type=p["col_type"],
                    method=rule["method"],
                    ascending=rule["ascending"],
                )
            self.step_recorded.emit("rank_col", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class CalcPanel(BaseToolPanel):
    use_type = False
    theme_color = "#00BCD4"
    action_name = "计算"

    def init_custom_ui(self):
        card, inner = self._make_card("计算公式")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加新公式列")
        btn_add.setStyleSheet(
            "QPushButton { background: #E0F7FA; border: 1px dashed #4DD0E1; "
            "border-radius: 4px; padding: 6px; color: #006064; font-size: 12px; }"
            "QPushButton:hover { background: #B2EBF2; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)

        hint = QLabel("列名务必用中括号包裹。如: ([销售额] - [成本]) * 0.1")
        hint.setStyleSheet(
            "color: #E65100; font-size: 11px; font-weight: bold; "
            "background: #FFF8E1; border-radius: 4px; padding: 6px; border: none;"
        )
        inner.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, new_col="", formula=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        n_input = QLineEdit(str(new_col))
        n_input.setObjectName("new_col")
        n_input.setPlaceholderText("新列名")
        f_input = ParameterTextEdit(str(formula))
        f_input.setObjectName("formula")
        f_input.setPlaceholderText("表达式 (如: [销售额]*0.1)")
        f_input.setMinimumHeight(72)

        btn_insert = QPushButton("📥")
        btn_insert.setFixedWidth(28)
        btn_insert.setToolTip("插入列名到公式")
        btn_insert.setStyleSheet(
            "QPushButton { background: #E0F7FA; border: 1px solid #B2EBF2; "
            "border-radius: 3px; font-size: 12px; }"
            "QPushButton:hover { background: #B2EBF2; }"
        )
        btn_insert.clicked.connect(lambda checked, fi=f_input: self._show_col_menu(fi))

        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(n_input)
        l.addWidget(f_input)
        l.addWidget(btn_insert)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def _show_col_menu(self, target_input):
        df_name = self.df_combo.currentText() if self.use_df else ""
        cols = []
        if df_name and df_name in self.data_pool:
            cols = list(self.data_pool[df_name].columns)
        if not cols:
            QMessageBox.information(self, "提示", "当前目标表无可用列，请先选择数据源。")
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: white; border: 1px solid #DDD; border-radius: 4px; }
            QMenu::item { padding: 6px 16px; font-size: 12px; font-family: monospace; }
            QMenu::item:selected { background: #E0F7FA; color: #006064; }
        """)
        for col in cols:
            action = menu.addAction(f"[{col}]")
            action.triggered.connect(
                lambda checked, c=col, fi=target_input: self._insert_col_at_cursor(fi, c)
            )
        # show near the button
        menu.exec_(QCursor.pos())

    def _insert_col_at_cursor(self, line_edit, col_name):
        text = line_edit.text()
        pos = line_edit.cursorPosition()
        insert = f"[{col_name}]"
        new_text = text[:pos] + insert + text[pos:]
        line_edit.setText(new_text)
        line_edit.setCursorPosition(pos + len(insert))
        line_edit.setFocus()

    def set_custom_params(self, p):
        rules = p.get("rules", [])
        if not rules and "new_col_name" in p:
            rules = [{"new_col_name": p["new_col_name"], "formula": p["formula"]}]
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(r.get("new_col_name"), r.get("formula"))

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                n, f = (
                    w.findChild(QLineEdit, "new_col").text().strip(),
                    (w.findChild(ParameterTextEdit, "formula") or w.findChild(QLineEdit, "formula")).text().strip(),
                )
                if n and f:
                    rules.append({"new_col_name": n, "formula": f})
        return {"rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["rules"]:
            return QMessageBox.warning(self, "错误", "参数缺失")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = self.data_pool[p["df_name"]].copy()
            for rule in p["rules"]:
                df = calc_col(df, rule["new_col_name"], rule["formula"])
            self.step_recorded.emit("calc_col", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class CumsumPanel(BaseToolPanel):
    theme_color = "#00897B"
    action_name = "累加"

    def init_custom_ui(self):
        card, inner = self._make_card("累加配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("累加列 (从第一行开始逐行累计):"))
        self.col_layout = QVBoxLayout()
        self.col_layout.setSpacing(4)
        inner.addLayout(self.col_layout)
        self.add_col_row()
        btn_add = QPushButton("+ 添加累加列")
        btn_add.setStyleSheet(
            "QPushButton { background: #E0F2F1; border: 1px dashed #80CBC4; "
            "border-radius: 4px; padding: 6px; color: #00695C; font-size: 12px; }"
            "QPushButton:hover { background: #B2DFDB; }"
        )
        btn_add.clicked.connect(lambda: self.add_col_row())
        inner.addWidget(btn_add)

        hint = QLabel("累加计算逐行累计。新列名 = 原列名_累加。适合做累计销售额、累计数量等。")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        inner.addWidget(hint)

    def add_col_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("累加列", dtype_filter="numeric")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.col_layout.addWidget(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.col_layout)
        self.add_col_row()

    def get_custom_params(self):
        cols = []
        for i in range(self.col_layout.count()):
            w = self.col_layout.itemAt(i).widget()
            if w:
                combo = w.findChild(QComboBox)
                if combo:
                    c = self._get_col_name(combo)
                    if c:
                        cols.append(c)
        return {"col_list": cols}

    def set_custom_params(self, p):
        if "col_list" in p:
            self.clear_dynamic_layout(self.col_layout)
            for c in p["col_list"]:
                self.add_col_row(c)

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["col_list"]:
            return QMessageBox.warning(self, "错误", "请填写累加列")
        out_name = p["out_name"] or f"{p['df_name']}_累加"
        try:
            df = cumsum_data(self.data_pool[p["df_name"]], p["col_list"], p["col_type"])
            self.step_recorded.emit("cumsum_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class PctChangePanel(BaseToolPanel):
    theme_color = "#F4511E"
    action_name = "环比"

    def init_custom_ui(self):
        card, inner = self._make_card("环比配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("环比列 (对指定列计算变化率):"))
        self.col_layout = QVBoxLayout()
        self.col_layout.setSpacing(4)
        inner.addLayout(self.col_layout)
        self.add_col_row()
        btn_add = QPushButton("+ 添加环比列")
        btn_add.setStyleSheet(
            "QPushButton { background: #FBE9E7; border: 1px dashed #FFAB91; "
            "border-radius: 4px; padding: 6px; color: #BF360C; font-size: 12px; }"
            "QPushButton:hover { background: #FFCCBC; }"
        )
        btn_add.clicked.connect(lambda: self.add_col_row())
        inner.addWidget(btn_add)

        fl = QFormLayout()
        self.periods_input = QLineEdit("1")
        fl.addRow("间隔期数:", self.periods_input)
        inner.addLayout(fl)

        hint = QLabel("环比 = (当前值 - 上期值) / 上期值。间隔期数: 1=逐行对比, 12=同比(月度数据)")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        inner.addWidget(hint)

    def add_col_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("环比列", dtype_filter="numeric")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.col_layout.addWidget(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.col_layout)
        self.add_col_row()
        self.periods_input.setText("1")

    def get_custom_params(self):
        cols = []
        for i in range(self.col_layout.count()):
            w = self.col_layout.itemAt(i).widget()
            if w:
                combo = w.findChild(QComboBox)
                if combo:
                    c = self._get_col_name(combo)
                    if c:
                        cols.append(c)
        return {
            "col_list": cols,
            "periods": int(self.periods_input.text() or 1),
        }

    def set_custom_params(self, p):
        if "col_list" in p:
            self.clear_dynamic_layout(self.col_layout)
            for c in p["col_list"]:
                self.add_col_row(c)
        if "periods" in p:
            self.periods_input.setText(str(p["periods"]))

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["col_list"]:
            return QMessageBox.warning(self, "错误", "请填写环比列")
        out_name = p["out_name"] or f"{p['df_name']}_环比"
        try:
            df = pct_change_data(self.data_pool[p["df_name"]],
                p["col_list"], p["periods"], p["col_type"])
            self.step_recorded.emit("pct_change_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))
