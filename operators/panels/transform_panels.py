"""Operator panels: transform_panels."""

from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from operators.base_panel import BaseToolPanel, QLineEdit
from operators.panels.flow_panels import BatchMapFlowPanel


class ExtractPanel(BatchMapFlowPanel):
    theme_color = "#009688"
    action_name = "提取"
    output_suffix = "提取"

    def build_rule_ui(self):
        self.fill_input = QLineEdit()
        self.fill_input.setPlaceholderText("可选: 缺失值填充...")
        self.top_form.addRow("填充空值:", self.fill_input)

        card, inner = self._make_card("提取列及重命名")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = self._make_add_button("+ 添加提取列")
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
        l.setSpacing(6)
        col_combo = self._make_col_combo("选择列")
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


class DedupPanel(BatchMapFlowPanel):
    theme_color = "#EF5350"
    action_name = "去重"
    output_suffix = "去重"

    def build_rule_ui(self):
        card, inner = self._make_card("去重配置")
        self.custom_layout.addWidget(card)

        inner.addWidget(QLabel("去重依据列 (留空=所有列完全相同才去重):"))
        self.subset_layout = QVBoxLayout()
        self.subset_layout.setSpacing(4)
        inner.addLayout(self.subset_layout)
        self.add_subset_row()
        btn_add = self._make_add_button("+ 添加去重列")
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
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
        l.addWidget(col_combo, stretch=1)
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
        hint = self._make_hint_label("抽样从大数据集中随机抽取子集用于快速测试。种子固定时可复现相同结果。")
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


class TransposePanel(BatchMapFlowPanel):
    use_type = False
    theme_color = "#9E9E9E"
    action_name = "转置"
    output_suffix = "转置"

    def build_rule_ui(self):
        hint_card, hint_inner = self._make_card()
        self.custom_layout.addWidget(hint_card)
        hint = self._make_hint_label("转置将行列互换。原列名变为第一列，原行变为列。适合需要行列翻转的场景。")
        hint_inner.addWidget(hint)

    def clear_custom_ui(self):
        pass

    def get_custom_params(self):
        return {}

    def set_custom_params(self, p):
        pass
