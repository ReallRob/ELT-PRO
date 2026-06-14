"""Operator panels: transform_panels."""

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


class ExtractPanel(BaseToolPanel):
    theme_color = "#009688"
    action_name = "提取"

    def init_custom_ui(self):
        self.fill_input = QLineEdit()
        self.fill_input.setPlaceholderText("可选: 缺失值填充...")
        self.top_form.addRow("填充空值:", self.fill_input)

        card, inner = self._make_card("提取列及重命名")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加提取列")
        btn_add.setStyleSheet(
            "QPushButton { background: #E0F2F1; border: 1px dashed #80CBC4; "
            "border-radius: 4px; padding: 6px; color: #00695C; font-size: 12px; }"
            "QPushButton:hover { background: #B2DFDB; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)

    def clear_custom_ui(self):
        self.fill_input.clear()
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

    def set_custom_params(self, p):
        if "fill_value" in p:
            self.fill_input.setText(str(p["fill_value"] or ""))
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
            "col_list": clist,
            "col_names": rlist,
            "fill_value": self.fill_input.text() or None,
        }

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["col_list"]:
            return QMessageBox.warning(self, "错误", "缺少参数")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            actual_cols = normalize_columns(
                self.data_pool[p["df_name"]], p["col_list"], p["col_type"]
            )
            final_cols = [
                p["col_names"][i] if p["col_names"][i] else actual_cols[i]
                for i in range(len(actual_cols))
            ]
            df = get_col_data(
                self.data_pool[p["df_name"]],
                p["col_list"],
                p["col_type"],
                p["fill_value"],
                final_cols,
            )
            self.step_recorded.emit("get_col_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class FilterPanel(BaseToolPanel):
    theme_color = "#E91E63"
    action_name = "筛选"

    OP_MAP = {
        "大于": ">", "小于": "<", "大于等于": ">=", "小于等于": "<=",
        "等于": "==", "不等于": "!=",
        "包含": "contains", "不包含": "not_contains",
        "开头是": "startswith", "结尾是": "endswith",
        "为空": "isnull", "不为空": "notnull",
    }
    OP_REV = {v: k for k, v in OP_MAP.items()}

    def init_custom_ui(self):
        self.logic_combo = QComboBox()
        self.logic_combo.addItems(["AND (满足所有)", "OR (满足其一)"])
        self.top_form.addRow("条件逻辑:", self.logic_combo)

        card, inner = self._make_card("筛选条件")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule()
        btn_add = QPushButton("+ 添加筛选条件")
        btn_add.setStyleSheet(
            "QPushButton { background: #FCE4EC; border: 1px dashed #F48FB1; "
            "border-radius: 4px; padding: 6px; color: #880E4F; font-size: 12px; }"
            "QPushButton:hover { background: #F8BBD0; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule())
        inner.addWidget(btn_add)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule()

    def add_rule(self, col="", op="等于", val=""):
        summary = f"{col or '?'} {op} {val}" if col or val else "新筛选条件"
        container, header_btn, body = self._make_collapsible_rule(summary)

        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.setSpacing(6)
        body_layout.addWidget(self._inline_label("列"))
        col_combo = self._make_col_combo("排查列")
        col_combo.setObjectName("col")
        col_combo.setMinimumWidth(150)
        self._set_col_name(col_combo, str(col))
        col_combo.currentTextChanged.connect(
            lambda: self._update_filter_summary(container, header_btn)
        )
        body_layout.addWidget(col_combo, stretch=2)
        body_layout.addWidget(self._inline_label("条件"))
        op_combo = QComboBox()
        op_combo.setObjectName("op")
        op_combo.addItems(list(self.OP_MAP.keys()))
        op_combo.setMinimumWidth(96)
        if op in self.OP_MAP:
            op_combo.setCurrentText(op)
        elif op in self.OP_REV:
            op_combo.setCurrentText(self.OP_REV[op])
        op_combo.currentTextChanged.connect(
            lambda: self._update_filter_summary(container, header_btn)
        )
        body_layout.addWidget(op_combo)
        body_layout.addWidget(self._inline_label("值"))
        v_input = QLineEdit(str(val))
        v_input.setObjectName("val")
        v_input.setPlaceholderText("目标值")
        v_input.textChanged.connect(
            lambda: self._update_filter_summary(container, header_btn)
        )
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(container.deleteLater)
        body_layout.addWidget(v_input, stretch=1)
        body_layout.addWidget(btn_rm)

        # assign objectNames to body widgets too for get_custom_params
        body.setObjectName("rule_body")

        self.rules_layout.addWidget(container)

    def _update_filter_summary(self, container, header_btn):
        body = container.findChild(QWidget, "rule_body")
        if not body:
            return
        col_combo = body.findChild(QComboBox, "col")
        op_combo = body.findChild(QComboBox, "op")
        v_input = body.findChild(QLineEdit, "val")
        c = self._get_col_name(col_combo) if col_combo else "?"
        o = op_combo.currentText() if op_combo else "?"
        v = v_input.text() if v_input else ""
        summary = f"{c or '?'} {o} {v}" if (c or v) else "新筛选条件"
        self._update_rule_summary(header_btn, summary)

    def set_custom_params(self, p):
        self._set_combo_by_prefix(self.logic_combo, p.get("logic"))
        conds = p.get("conditions", [])
        if conds:
            self.clear_dynamic_layout(self.rules_layout)
            for c in conds:
                self.add_rule(c.get("col"), c.get("op"), c.get("value"))

    def get_custom_params(self):
        conds = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c = self._get_col_name(w.findChild(QComboBox, "col"))
                op_cn = w.findChild(QComboBox, "op").currentText()
                op = self.OP_MAP.get(op_cn, "==")
                v = w.findChild(QLineEdit, "val").text().strip()
                if c:
                    conds.append({"col": c, "op": op, "value": v})
        return {
            "logic": self.logic_combo.currentText().split(" ")[0],
            "conditions": conds,
        }

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "缺少目标表")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = filter_data(
                self.data_pool[p["df_name"]], p["conditions"], p["logic"], p["col_type"]
            )
            self.step_recorded.emit("filter_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class SortPanel(BaseToolPanel):
    theme_color = "#FF9800"
    action_name = "排序"

    def init_custom_ui(self):
        card, inner = self._make_card("排序规则 (从上到下优先级递减)")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加排序规则")
        btn_add.setStyleSheet(
            "QPushButton { background: #FFF3E0; border: 1px dashed #FFB74D; "
            "border-radius: 4px; padding: 6px; color: #E65100; font-size: 12px; }"
            "QPushButton:hover { background: #FFE0B2; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)
        hint = QLabel("升序(从小到大), 降序(从大到小), 自定义(手写词典如: 高,中,低)")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")
        inner.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", asc=True, custom_order=None):
        if custom_order is None:
            custom_order = []
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 8)
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("排序列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        asc_combo = QComboBox()
        asc_combo.setObjectName("asc")
        asc_combo.addItems(["升序", "降序", "自定义"])
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(container.deleteLater)
        h.addWidget(col_combo)
        h.addWidget(asc_combo)
        h.addWidget(btn_rm)
        v.addLayout(h)

        # 自定义排序区域（动态行）
        cus_area = QWidget()
        cus_area.setObjectName("custom_area")
        cl = QVBoxLayout(cus_area)
        cl.setContentsMargins(12, 4, 0, 0)
        cl.setSpacing(3)

        def _add_cus_row(val=""):
            cr = QWidget()
            rl = QHBoxLayout(cr)
            rl.setContentsMargins(0, 0, 0, 0)
            inp = QLineEdit(str(val))
            inp.setObjectName("custom_val")
            inp.setPlaceholderText("排序值")
            inp.setMinimumWidth(80)
            rm = QPushButton("×")
            rm.setFixedWidth(22)
            rm.clicked.connect(cr.deleteLater)
            rl.addWidget(inp)
            rl.addWidget(rm)
            rl.addStretch()
            cl.addWidget(cr)

        for val in custom_order:
            _add_cus_row(val)

        btn_add_cus = QPushButton("+ 添加排序值")
        btn_add_cus.setStyleSheet(
            "QPushButton { background: #FFF8E1; border: 1px dashed #FFB300; "
            "border-radius: 3px; padding: 3px 8px; font-size: 11px; color: #E65100; }"
            "QPushButton:hover { background: #FFECB3; }"
        )
        btn_add_cus.clicked.connect(lambda: _add_cus_row())
        cl.addWidget(btn_add_cus)

        cus_area.setVisible(asc_combo.currentIndex() == 2)
        if custom_order:
            asc_combo.setCurrentIndex(2)
        else:
            asc_combo.setCurrentIndex(0 if asc else 1)
        asc_combo.currentIndexChanged.connect(
            lambda idx, ca=cus_area: ca.setVisible(idx == 2)
        )
        v.addWidget(cus_area)
        self.rules_layout.addWidget(container)

    def set_custom_params(self, p):
        rules = p.get("sort_rules", [])
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(
                    r.get("col"), r.get("ascending"), r.get("custom_order", [])
                )

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if not w:
                continue
            col_combo = w.findChild(QComboBox, "col")
            c = self._get_col_name(col_combo) if col_combo else ""
            asc_idx = w.findChild(QComboBox, "asc").currentIndex()
            cus_vals = []
            if asc_idx == 2:
                ca = w.findChild(QWidget, "custom_area")
                if ca:
                    for inp in ca.findChildren(QLineEdit, "custom_val"):
                        v = inp.text().strip()
                        if v:
                            cus_vals.append(v)
            if c:
                rules.append({
                    "col": c,
                    "ascending": True if asc_idx == 2 else asc_idx == 0,
                    "custom_order": cus_vals,
                })
        return {"sort_rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["sort_rules"]:
            return QMessageBox.warning(self, "错误", "参数缺失")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = sort_data(
                self.data_pool[p["df_name"]], p["sort_rules"], col_type=p["col_type"]
            )
            self.step_recorded.emit("sort_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class CleanPanel(BaseToolPanel):
    theme_color = "#FF5722"
    action_name = "清洗"

    ACT_CN_MAP = {
        "转数字": "to_numeric", "转文本": "to_string", "转整数": "to_int",
        "转浮点": "to_float", "转日期": "to_datetime",
        "去空格": "strip_space", "填空值": "fill_na", "删空行": "drop_na",
        "文本替换": "replace", "转大写": "upper_case", "转小写": "lower_case",
        "四舍五入": "round_val", "裁剪范围": "clip",
    }
    ACT_EN_MAP = {v: k for k, v in ACT_CN_MAP.items()}
    ACT_PARAM_SPECS = {
        "填空值":   [("param_val", "填充值")],
        "文本替换": [("param_val", "旧文本→新文本")],
        "四舍五入": [("param_val", "小数位")],
        "裁剪范围": [("param_val", "最小值,最大值")],
        "转日期":   [("param_val", "@date")],
    }
    DATE_FORMATS = [
        ("自动识别", ""), ("YYYY-MM-DD", "%Y-%m-%d"),
        ("YYYY/MM/DD", "%Y/%m/%d"), ("YYYY年MM月DD日", "%Y年%m月%d日"),
        ("DD/MM/YYYY", "%d/%m/%Y"), ("MM/DD/YYYY", "%m/%d/%Y"),
        ("YYYYMMDD", "%Y%m%d"), ("自定义...", "__custom__"),
    ]

    def init_custom_ui(self):
        card, inner = self._make_card("清洗规则 (从上到下执行)")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule()
        btn_add = QPushButton("+ 添加清洗规则")
        btn_add.setStyleSheet(
            "QPushButton { background: #FBE9E7; border: 1px dashed #FFAB91; "
            "border-radius: 4px; padding: 6px; color: #BF360C; font-size: 12px; }"
            "QPushButton:hover { background: #FFCCBC; }"
        )
        btn_add.clicked.connect(lambda: self.add_rule())
        inner.addWidget(btn_add)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)

    def add_rule(self, col="", action="to_numeric", fill_val=""):
        cn_action = self.ACT_EN_MAP.get(action, action)
        summary = f"{col or '?'} -> {cn_action}" if col else "新清洗规则"
        container, header_btn, body = self._make_collapsible_rule(summary)
        body.setObjectName("rule_body")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.setSpacing(4)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(self._inline_label("列"))
        col_combo = self._make_col_combo("清洗列")
        col_combo.setObjectName("col")
        col_combo.setMinimumWidth(160)
        self._set_col_name(col_combo, str(col))
        col_combo.currentTextChanged.connect(
            lambda: self._update_clean_summary(container, header_btn))
        row1.addWidget(col_combo, stretch=2)
        row1.addWidget(self._inline_label("操作"))
        action_combo = QComboBox()
        action_combo.setObjectName("action")
        action_combo.addItems(list(self.ACT_CN_MAP.keys()))
        action_combo.setMinimumWidth(104)
        action_combo.setCurrentText(cn_action)
        action_combo.currentTextChanged.connect(
            lambda t, c=container, h=header_btn:
                (self._update_clean_summary(c, h), self._build_clean_params(c, t)))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(container.deleteLater)
        row1.addWidget(action_combo)
        row1.addWidget(btn_rm)
        body_layout.addLayout(row1)
        self._build_clean_params(container, cn_action, fill_val)
        self.rules_layout.addWidget(container)

    def _build_clean_params(self, container, cn_action, fill_val=""):
        old = container.findChild(QWidget, "param_area")
        if old:
            container.layout().removeWidget(old)
            old.deleteLater()
        specs = self.ACT_PARAM_SPECS.get(cn_action)
        if not specs:
            return
        area = QWidget()
        area.setObjectName("param_area")
        al = QHBoxLayout(area)
        al.setContentsMargins(0, 4, 0, 0)
        al.setSpacing(6)
        for obj_name, placeholder in specs:
            if placeholder == "@date":
                al.addWidget(self._inline_label("参数"))
                fmt_combo = QComboBox()
                fmt_combo.setObjectName("fill")
                for label, code in self.DATE_FORMATS:
                    fmt_combo.addItem(label, userData=code)
                fmt_combo.setMinimumWidth(140)
                if fill_val:
                    idx = fmt_combo.findData(fill_val)
                    fmt_combo.setCurrentIndex(idx if idx >= 0 else len(self.DATE_FORMATS)-1)
                else:
                    fmt_combo.setCurrentIndex(0)
                custom_input = QLineEdit()
                custom_input.setObjectName("fill_custom")
                custom_input.setPlaceholderText("自定义格式...")
                custom_input.setMinimumWidth(100)
                custom_input.setVisible(
                    fmt_combo.currentData() == "__custom__")
                if custom_input.isVisible() and fill_val:
                    custom_input.setText(fill_val)
                fmt_combo.currentTextChanged.connect(
                    lambda t, ci=custom_input, fc=fmt_combo:
                        ci.setVisible(fc.currentData() == "__custom__"))
                al.addWidget(fmt_combo)
                al.addWidget(custom_input)
            else:
                al.addWidget(self._inline_label("参数"))
                inp = QLineEdit()
                inp.setObjectName("fill")
                inp.setPlaceholderText(placeholder)
                inp.setMinimumWidth(160)
                if fill_val:
                    inp.setText(str(fill_val))
                al.addWidget(inp)
        al.addStretch()
        container.layout().addWidget(area)

    def _update_clean_summary(self, container, header_btn):
        body = container.findChild(QWidget, "rule_body")
        if not body: return
        col_combo = body.findChild(QComboBox, "col")
        action_combo = body.findChild(QComboBox, "action")
        c = self._get_col_name(col_combo) if col_combo else "?"
        a = action_combo.currentText() if action_combo else "?"
        self._update_rule_summary(header_btn, f"{c} -> {a}" if c != "?" else "新清洗规则")

    def set_custom_params(self, p):
        rules = p.get("rules", [])
        self.clear_dynamic_layout(self.rules_layout)
        if rules:
            for r in rules:
                self.add_rule(r.get("cols"), r.get("action"), r.get("fill_value"))
        else:
            self.add_rule()

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if not w: continue
            body = w.findChild(QWidget, "rule_body")
            if not body: continue
            col_combo = body.findChild(QComboBox, "col")
            c = self._get_col_name(col_combo) if col_combo else ""
            cn = body.findChild(QComboBox, "action").currentText()
            a = self.ACT_CN_MAP.get(cn, cn)
            if not c: continue
            fill_val = ""
            area = w.findChild(QWidget, "param_area")
            if area:
                fmt_combo = area.findChild(QComboBox, "fill")
                if fmt_combo:
                    code = fmt_combo.currentData()
                    if code == "__custom__":
                        ci = area.findChild(QLineEdit, "fill_custom")
                        fill_val = ci.text().strip() if ci else ""
                    else:
                        fill_val = code
                else:
                    plain = area.findChild(QLineEdit, "fill")
                    if plain: fill_val = plain.text().strip()
            rules.append({"cols": c, "action": a, "fill_value": fill_val})
        return {"rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["rules"]:
            return QMessageBox.warning(self, "错误", "参数缺失")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = clean_data(self.data_pool[p["df_name"]], p["rules"], p["col_type"])
            self.step_recorded.emit("clean_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class DedupPanel(BaseToolPanel):
    theme_color = "#EF5350"
    action_name = "去重"

    def init_custom_ui(self):
        card, inner = self._make_card("去重配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("去重依据列 (留空=所有列完全相同才去重):"))
        self.subset_layout = QVBoxLayout()
        self.subset_layout.setSpacing(4)
        inner.addLayout(self.subset_layout)
        self.add_subset_row()
        btn_add = QPushButton("+ 添加去重列")
        btn_add.setStyleSheet(
            "QPushButton { background: #FFEBEE; border: 1px dashed #EF9A9A; "
            "border-radius: 4px; padding: 6px; color: #C62828; font-size: 12px; }"
            "QPushButton:hover { background: #FFCDD2; }"
        )
        btn_add.clicked.connect(lambda: self.add_subset_row())
        inner.addWidget(btn_add)

        inner.addWidget(QLabel("保留策略:"))
        self.keep_combo = QComboBox()
        self.keep_combo.addItems(["first (保留第一条)", "last (保留最后一条)", "False (全删)"])
        inner.addWidget(self.keep_combo)

    def add_subset_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("去重列")
        self._set_col_name(col_combo, str(col))
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(col_combo)
        l.addWidget(btn_rm)
        self.subset_layout.addWidget(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.subset_layout)
        self.add_subset_row()

    def get_custom_params(self):
        cols = []
        for i in range(self.subset_layout.count()):
            w = self.subset_layout.itemAt(i).widget()
            if w:
                combo = w.findChild(QComboBox)
                if combo:
                    c = self._get_col_name(combo)
                    if c:
                        cols.append(c)
        keep_map = {0: "first", 1: "last", 2: False}
        return {
            "subset_cols": cols,
            "keep": keep_map.get(self.keep_combo.currentIndex(), "first"),
        }

    def set_custom_params(self, p):
        if "subset_cols" in p:
            self.clear_dynamic_layout(self.subset_layout)
            for c in p["subset_cols"]:
                self.add_subset_row(c)
        if "keep" in p:
            k = p["keep"]
            if k == "last":
                self.keep_combo.setCurrentIndex(1)
            elif k is False:
                self.keep_combo.setCurrentIndex(2)
            else:
                self.keep_combo.setCurrentIndex(0)

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "缺少目标表")
        out_name = p["out_name"] or f"{p['df_name']}_去重"
        try:
            df = drop_duplicates(self.data_pool[p["df_name"]],
                p["subset_cols"], p["keep"], p["col_type"])
            self.step_recorded.emit("drop_duplicates", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class SamplePanel(BaseToolPanel):
    use_type = False
    theme_color = "#78909C"
    action_name = "抽样"

    def init_custom_ui(self):
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["按数量抽取", "按比例抽取"])
        self.top_form.addRow("抽样方式:", self.mode_combo)

        self.n_input = QLineEdit("100")
        self.n_input.setPlaceholderText("抽取行数")
        self.top_form.addRow("数量/比例:", self.n_input)

        self.seed_input = QLineEdit()
        self.seed_input.setPlaceholderText("随机种子 (留空=每次不同)")
        self.top_form.addRow("随机种子:", self.seed_input)

        hint_card, hint_inner = self._make_card()
        self.custom_layout.addWidget(hint_card)
        hint = QLabel("抽样从大数据集中随机抽取子集用于快速测试。种子固定时可复现相同结果。")
        hint.setStyleSheet("color: #888; font-size: 11px; border: none;")
        hint.setWordWrap(True)
        hint_inner.addWidget(hint)

    def clear_custom_ui(self):
        self.n_input.setText("100")
        self.seed_input.clear()

    def get_custom_params(self):
        seed = int(self.seed_input.text()) if self.seed_input.text().strip() else None
        p = {"random_state": seed}
        if self.mode_combo.currentIndex() == 0:
            p["n"] = int(self.n_input.text() or 100)
        else:
            p["frac"] = float(self.n_input.text() or 0.1)
        return p

    def set_custom_params(self, p):
        if "n" in p and p["n"]:
            self.mode_combo.setCurrentIndex(0)
            self.n_input.setText(str(p["n"]))
        elif "frac" in p and p["frac"]:
            self.mode_combo.setCurrentIndex(1)
            self.n_input.setText(str(p["frac"]))
        if "random_state" in p and p["random_state"] is not None:
            self.seed_input.setText(str(p["random_state"]))

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "缺少目标表")
        out_name = p["out_name"] or f"{p['df_name']}_抽样"
        try:
            df = sample_data(self.data_pool[p["df_name"]],
                p.get("n"), p.get("frac"), p.get("random_state"))
            self.step_recorded.emit("sample_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class TransposePanel(BaseToolPanel):
    use_type = False
    theme_color = "#9E9E9E"
    action_name = "转置"

    def init_custom_ui(self):
        hint_card, hint_inner = self._make_card()
        self.custom_layout.addWidget(hint_card)
        hint = QLabel("转置将行列互换。原列名变为第一列，原行变为列。适合需要行列翻转的场景。")
        hint.setStyleSheet("color: #888; font-size: 11px; border: none;")
        hint.setWordWrap(True)
        hint_inner.addWidget(hint)

    def clear_custom_ui(self):
        pass

    def get_custom_params(self):
        return {}

    def set_custom_params(self, p):
        pass

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "缺少目标表")
        out_name = p["out_name"] or f"{p['df_name']}_转置"
        try:
            df = transpose_data(self.data_pool[p["df_name"]])
            self.step_recorded.emit("transpose_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))
