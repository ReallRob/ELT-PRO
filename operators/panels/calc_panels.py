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
from core.dataframe_ops.columns import stringify_column_name
from core.dataframe_ops import (
    calc_code,
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
        btn_add = self._make_add_button("+ 添加排名规则")
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)
        hint = self._make_hint_label("min 中国式排名；dense 密集排名；max、average、first 分别对应不同并列处理方式。")
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
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=container: self.remove_dynamic_row(r))
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
        card, inner = self._make_card("规则配置")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(6)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = self._make_add_button("+ 添加新公式列")
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)

        hint = self._make_hint_label("公式模式用 [列名]；代码模式中 df 为当前表，pd/np/re/math 已可用。")
        inner.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, new_col="", formula="", mode="formula", code="", timeout_seconds=10):
        mode = mode if mode in ("formula", "code") else "formula"
        summary = self._calc_rule_summary(new_col, code if mode == "code" else formula, mode)
        row, header_btn, body = self._make_collapsible_rule(summary)
        body.setObjectName("rule_body")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(6)
        option_row = QHBoxLayout()
        option_row.setContentsMargins(0, 0, 0, 0)
        option_row.setSpacing(6)
        n_input = QLineEdit(str(new_col))
        n_input.setObjectName("new_col")
        n_input.setPlaceholderText("输出列(代码模式可选)")
        n_input.textChanged.connect(lambda: self._update_calc_summary(row, header_btn))
        mode_combo = QComboBox()
        mode_combo.setObjectName("mode")
        mode_combo.addItem("公式", userData="formula")
        mode_combo.addItem("我写代码", userData="code")
        mode_combo.setMinimumWidth(88)
        mode_combo.setMaximumWidth(112)
        mode_combo.setCurrentIndex(1 if mode == "code" else 0)
        timeout_input = QLineEdit("10")
        timeout_input.setObjectName("timeout_seconds")
        timeout_input.setPlaceholderText("秒")
        timeout_input.setMaximumWidth(56)
        timeout_input.setText(str(timeout_seconds or 10))
        f_input = ParameterTextEdit(str(formula))
        f_input.setObjectName("formula")
        f_input.setPlaceholderText("表达式 (如: [销售额]*0.1)")
        f_input.setMinimumHeight(72)
        f_input.textChanged.connect(lambda: self._update_calc_summary(row, header_btn))
        c_input = ParameterTextEdit(str(code or ""))
        c_input.setObjectName("code")
        c_input.setPlaceholderText(self._default_code_placeholder(new_col))
        c_input.setMinimumHeight(176)
        c_input.textChanged.connect(lambda: self._update_calc_summary(row, header_btn))

        btn_insert = QPushButton("插入列")
        btn_insert.setFixedWidth(64)
        btn_insert.setToolTip("按当前模式插入列引用")
        btn_insert.setStyleSheet(
            "QPushButton { background: #E0F7FA; border: 1px solid #B2EBF2; "
            "border-radius: 3px; font-size: 12px; }"
            "QPushButton:hover { background: #B2EBF2; }"
        )
        btn_insert.clicked.connect(
            lambda checked, fi=f_input, ci=c_input, mc=mode_combo: self._show_col_menu(
                ci if mc.currentData() == "code" else fi,
                mc.currentData(),
            )
        )
        mode_combo.currentIndexChanged.connect(
            lambda _idx, fi=f_input, ci=c_input, r=row, h=header_btn: self._sync_calc_mode(fi, ci, r, h)
        )

        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
        name_row.addWidget(self._inline_label("列"))
        name_row.addWidget(n_input, stretch=1)
        name_row.addWidget(btn_rm)
        layout.addLayout(name_row)
        option_row.addWidget(self._inline_label("模式"))
        option_row.addWidget(mode_combo)
        option_row.addWidget(self._inline_label("超时"))
        option_row.addWidget(timeout_input)
        option_row.addWidget(btn_insert)
        option_row.addStretch(1)
        layout.addLayout(option_row)
        layout.addWidget(f_input)
        layout.addWidget(c_input)
        self._sync_calc_mode(f_input, c_input, row, header_btn)
        self.rules_layout.addWidget(row)

    def _calc_rule_summary(self, new_col, formula, mode="formula"):
        name = str(new_col or "").strip()
        expr = str(formula or "").strip()
        if name and expr:
            prefix = "代码" if mode == "code" else "公式"
            return f"{name} · {prefix} · {expr[:24]}"
        if expr and mode == "code":
            return f"代码 · {expr[:28]}"
        return name or "新公式列"

    def _default_code_placeholder(self, new_col=""):
        col = str(new_col or "结果").strip() or "结果"
        return (
            "df 为当前表，pd/np/re/math 已可用\n"
            "params['参数名'] 取参数，param('参数名', '映射名') 取映射值\n"
            "示例：\n"
            "end = pd.to_datetime(df['结束日期'])\n"
            "start = pd.to_datetime(df['开始日期'])\n"
            f"df[{col!r}] = (end - start).dt.days + 1"
        )

    def _sync_calc_mode(self, formula_input, code_input, row, header_btn):
        mode_combo = row.findChild(QComboBox, "mode")
        is_code = bool(mode_combo and mode_combo.currentData() == "code")
        formula_input.setVisible(not is_code)
        code_input.setVisible(is_code)
        self._update_calc_summary(row, header_btn)

    def _update_calc_summary(self, row, header_btn):
        name_input = row.findChild(QLineEdit, "new_col")
        formula_input = row.findChild(ParameterTextEdit, "formula")
        code_input = row.findChild(ParameterTextEdit, "code")
        mode_combo = row.findChild(QComboBox, "mode")
        mode = mode_combo.currentData() if mode_combo else "formula"
        name = name_input.text().strip() if name_input else ""
        if mode == "code" and code_input:
            formula = code_input.text().strip()
        else:
            formula = formula_input.text().strip() if formula_input else ""
        self._update_rule_summary(header_btn, self._calc_rule_summary(name, formula, mode))

    def _show_col_menu(self, target_input, mode="formula"):
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
            display_col = stringify_column_name(col)
            label = f"df[{display_col!r}]" if mode == "code" else f"[{display_col}]"
            action = menu.addAction(label)
            action.triggered.connect(
                lambda checked, c=display_col, fi=target_input, m=mode: self._insert_col_at_cursor(fi, c, m)
            )
        # show near the button
        menu.exec_(QCursor.pos())

    def _insert_col_at_cursor(self, line_edit, col_name, mode="formula"):
        text = line_edit.text()
        pos = line_edit.cursorPosition()
        insert = f"df[{col_name!r}]" if mode == "code" else f"[{col_name}]"
        new_text = text[:pos] + insert + text[pos:]
        line_edit.setText(new_text)
        line_edit.setCursorPosition(pos + len(insert))
        line_edit.setFocus()

    def _show_parameter_menu(self, line_edit):
        is_code = False
        try:
            is_code = line_edit.objectName() == "code"
        except Exception:
            is_code = False
        if not is_code:
            return super()._show_parameter_menu(line_edit)

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: white; border: 1px solid #CBD5E1; border-radius: 6px; }
            QMenu::item { padding: 7px 18px; font-size: 12px; }
            QMenu::item:selected { background: #E0F7FA; color: #006064; }
            QMenu::separator { height: 1px; background: #E5EAF0; margin: 4px 8px; }
        """)
        params = sorted((self._runtime_parameters or {}).keys())
        mappings = sorted((self._parameter_mappings or {}).keys())
        if params:
            for name in params:
                action = menu.addAction(f"params[{name!r}]")
                action.triggered.connect(
                    lambda checked=False, n=name: self._insert_text_at_cursor(
                        line_edit, f"params[{n!r}]"
                    )
                )
        else:
            action = menu.addAction("暂无可用参数")
            action.setEnabled(False)

        if params and mappings:
            menu.addSeparator()
            for mapping_name in mappings:
                for param_name in params:
                    label = f"param({param_name!r}, {mapping_name!r})"
                    action = menu.addAction(label)
                    action.triggered.connect(
                        lambda checked=False, p=param_name, m=mapping_name: self._insert_text_at_cursor(
                            line_edit, f"param({p!r}, {m!r})"
                        )
                    )
        menu.exec_(line_edit.mapToGlobal(line_edit.rect().bottomRight()))

    def set_custom_params(self, p):
        rules = p.get("rules", [])
        if not rules and "new_col_name" in p:
            rules = [{"new_col_name": p["new_col_name"], "formula": p["formula"]}]
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(
                    r.get("new_col_name", ""),
                    r.get("formula", ""),
                    r.get("mode", "formula"),
                    r.get("code", ""),
                    r.get("timeout_seconds", 10),
                )

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                name_input = w.findChild(QLineEdit, "new_col")
                mode_combo = w.findChild(QComboBox, "mode")
                formula_input = w.findChild(ParameterTextEdit, "formula") or w.findChild(QLineEdit, "formula")
                code_input = w.findChild(ParameterTextEdit, "code")
                timeout_input = w.findChild(QLineEdit, "timeout_seconds")
                n = name_input.text().strip() if name_input else ""
                mode = mode_combo.currentData() if mode_combo else "formula"
                if mode == "code":
                    code = code_input.text().strip() if code_input else ""
                    if code:
                        timeout_text = timeout_input.text().strip() if timeout_input else "10"
                        rules.append({
                            "new_col_name": n,
                            "mode": "code",
                            "code": code,
                            "timeout_seconds": timeout_text or "10",
                        })
                else:
                    f = formula_input.text().strip() if formula_input else ""
                    if n and f:
                        rules.append({"new_col_name": n, "formula": f, "mode": "formula"})
        return {"rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["rules"]:
            return QMessageBox.warning(self, "错误", "参数缺失")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = self.data_pool[p["df_name"]].copy()
            for rule in p["rules"]:
                if rule.get("mode") == "code":
                    df = calc_code(
                        df,
                        rule.get("code", rule.get("formula", "")),
                        rule.get("new_col_name", ""),
                        self._runtime_parameters,
                        self._parameter_mappings,
                        rule.get("timeout_seconds", 10),
                    )
                else:
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
        btn_add = self._make_add_button("+ 添加累加列")
        btn_add.clicked.connect(lambda: self.add_col_row())
        inner.addWidget(btn_add)

        hint = self._make_hint_label("累加计算逐行累计。新列名默认为原列名_累加。")
        inner.addWidget(hint)

    def add_col_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("累加列", dtype_filter="numeric")
        self._set_col_name(col_combo, str(col))
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
        l.addWidget(col_combo, stretch=1)
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
        btn_add = self._make_add_button("+ 添加环比列")
        btn_add.clicked.connect(lambda: self.add_col_row())
        inner.addWidget(btn_add)

        fl = QFormLayout()
        fl.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        fl.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.periods_input = QLineEdit("1")
        fl.addRow("间隔期数:", self.periods_input)
        inner.addLayout(fl)

        hint = self._make_hint_label("环比 = (当前值 - 上期值) / 上期值。间隔期数 1 为逐行对比，12 常用于月度同比。")
        inner.addWidget(hint)

    def add_col_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("环比列", dtype_filter="numeric")
        self._set_col_name(col_combo, str(col))
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
        l.addWidget(col_combo, stretch=1)
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
