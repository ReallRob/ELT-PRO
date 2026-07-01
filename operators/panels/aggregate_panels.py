"""Operator panels: aggregate_panels."""

from PyQt5.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from operators.base_panel import BaseToolPanel, QLineEdit
from operators.panels.flow_panels import BatchMapFlowPanel


class PivotPanel(BatchMapFlowPanel):
    theme_color = "#8E24AA"
    action_name = "数据透视"
    output_suffix = "透视"

    def build_rule_ui(self):
        card, inner = self._make_card("透视配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("行标签 (可多个):"))
        self.index_layout = QVBoxLayout()
        self.index_layout.setSpacing(4)
        inner.addLayout(self.index_layout)
        self.add_index_row()
        btn_add_idx = self._make_add_button("+ 添加行标签")
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
        fl.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        fl.setRowWrapPolicy(QFormLayout.WrapLongRows)
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
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
        l.addWidget(col_combo, stretch=1)
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


class MeltPanel(BatchMapFlowPanel):
    theme_color = "#26A69A"
    action_name = "逆透视"
    output_suffix = "逆透视"

    def build_rule_ui(self):
        card, inner = self._make_card("逆透视配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("保留列 (留空=自动使用非融合列):"))
        self.id_layout = QVBoxLayout()
        self.id_layout.setSpacing(4)
        inner.addLayout(self.id_layout)
        self.add_id_row()
        btn_add_id = self._make_add_button("+ 添加保留列")
        btn_add_id.clicked.connect(lambda: self.add_id_row())
        inner.addWidget(btn_add_id)

        inner.addWidget(QLabel("融合列 (宽表变长表，这些列的值会汇入一列):"))
        self.val_layout = QVBoxLayout()
        self.val_layout.setSpacing(4)
        inner.addLayout(self.val_layout)
        self.add_val_row()
        btn_add_val = self._make_add_button("+ 添加融合列")
        btn_add_val.clicked.connect(lambda: self.add_val_row())
        inner.addWidget(btn_add_val)

        fl = QFormLayout()
        fl.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        fl.setRowWrapPolicy(QFormLayout.WrapLongRows)
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
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
        l.addWidget(col_combo, stretch=1)
        l.addWidget(btn_rm)
        self.id_layout.addWidget(row)

    def add_val_row(self, col=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        col_combo = self._make_col_combo("融合列")
        self._set_col_name(col_combo, str(col))
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
        l.addWidget(col_combo, stretch=1)
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
        btn_add = self._make_add_button("+ 添加分位数")
        btn_add.clicked.connect(lambda: self.add_pct_row())
        inner.addWidget(btn_add)

        hint_card, hint_inner = self._make_card()
        self.custom_layout.addWidget(hint_card)
        hint = self._make_hint_label("输出均值、标准差、最大最小、分位数等统计信息。")
        hint_inner.addWidget(hint)

    def add_pct_row(self, val=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        inp = QLineEdit(str(val))
        inp.setObjectName("pct_val")
        inp.setPlaceholderText("如: 0.25")
        inp.setMinimumWidth(80)
        rm = self._make_delete_button()
        rm.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
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
            self.clear_dynamic_layout(self.pct_layout)
            for value in p["percentiles"]:
                self.add_pct_row(str(value))
