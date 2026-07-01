"""Operator panels: table_panels."""

from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from operators.base_panel import BaseToolPanel, QLineEdit
from core.workflow.schema import action_suffix


class JoinPanel(BaseToolPanel):
    use_df = False
    theme_color = "#4CAF50"
    action_name = "连接"

    def set_incoming_outputs(self, incoming_outputs):
        self._incoming_outputs = [
            item
            for item in (incoming_outputs or [])
            if isinstance(item, dict)
            and str(item.get("name") or "").strip()
            and str(item.get("data_type") or "table") == "table"
        ]
        names = [item["name"] for item in self._incoming_outputs]
        for combo in (self.df1_combo, self.df2_combo):
            self._set_combo_items_preserving_text(combo, names)
            self._remember_combo_ref(combo)
        self._refresh_col_combos()

    def _input_ref_for_combo(self, combo):
        key = (
            str(combo.property("source_node_id") or "") if combo else "",
            str(combo.property("source_output_id") or "out_1") if combo else "out_1",
        )
        for item in getattr(self, "_incoming_outputs", []) or []:
            if self._input_key(item) == key:
                return item
        name = str(combo.currentText() if combo else "").strip()
        for item in getattr(self, "_incoming_outputs", []) or []:
            if str(item.get("name") or "").strip() == name:
                return item
        return None

    @staticmethod
    def _input_key(item):
        return (
            str((item or {}).get("source_node_id") or ""),
            str((item or {}).get("source_output_id") or "out_1"),
        )

    def _set_combo_from_input(self, combo, input_item):
        if combo is None or not isinstance(input_item, dict):
            return
        names = [item["name"] for item in getattr(self, "_incoming_outputs", []) or []]
        name = str(input_item.get("name") or "").strip()
        self._set_combo_items_preserving_text(combo, names, name)
        combo.setProperty("source_node_id", str(input_item.get("source_node_id") or ""))
        combo.setProperty("source_output_id", str(input_item.get("source_output_id") or "out_1"))

    def _remember_combo_ref(self, combo):
        if combo is None:
            return
        name = str(combo.currentText() or "").strip()
        ref = next(
            (
                item
                for item in getattr(self, "_incoming_outputs", []) or []
                if str(item.get("name") or "").strip() == name
            ),
            None,
        )
        combo.setProperty("source_node_id", str((ref or {}).get("source_node_id") or ""))
        combo.setProperty("source_output_id", str((ref or {}).get("source_output_id") or "out_1"))

    def _saved_input_by_role(self, params, role, fallback_index):
        inputs = [item for item in (params or {}).get("inputs") or [] if isinstance(item, dict)]
        for item in inputs:
            if item.get("role") == role:
                return item
        return inputs[fallback_index] if fallback_index < len(inputs) else None

    def _saved_output_name(self, params):
        outputs = [item for item in (params or {}).get("outputs") or [] if isinstance(item, dict)]
        return str((outputs[0] if outputs else {}).get("name") or "")

    def _set_binary_inputs_from_params(self, params):
        self._set_combo_from_input(self.df1_combo, self._saved_input_by_role(params, "left", 0))
        self._set_combo_from_input(self.df2_combo, self._saved_input_by_role(params, "right", 1))
        if hasattr(self, "out_input"):
            name = self._saved_output_name(params)
            if name:
                self.out_input.setText(name)

    def _flow_io_prefs(self):
        refs = [self._input_ref_for_combo(self.df1_combo), self._input_ref_for_combo(self.df2_combo)]
        roles = ["left", "right"]
        prefs_inputs = []
        for ref, role in zip(refs, roles):
            if not ref:
                continue
            prefs_inputs.append(
                {
                    "source_node_id": str(ref.get("source_node_id") or ""),
                    "source_output_id": str(ref.get("source_output_id") or "out_1"),
                    "name": str(ref.get("name") or ""),
                    "role": role,
                    "data_type": "table",
                    "enabled": True,
                }
            )
        out_name = self.out_input.text().strip() if hasattr(self, "out_input") else ""
        if not out_name and prefs_inputs:
            out_name = f"{prefs_inputs[0]['name']}_{action_suffix('left_join')}"
        return {"inputs": prefs_inputs, "output_name": out_name, "output_data_type": "table"}

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
        self.df1_combo.currentTextChanged.connect(lambda *_: self._remember_combo_ref(self.df1_combo))
        self.df2_combo.currentTextChanged.connect(self._refresh_col_combos)
        self.df2_combo.currentTextChanged.connect(lambda *_: self._remember_combo_ref(self.df2_combo))
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
        self._set_binary_inputs_from_params(p)
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
        io_prefs = self._flow_io_prefs()
        return {
            "l_key": self.l_key.text().strip(),
            "r_key": self.r_key.text().strip(),
            "get_cols": get_cols,
            "col_names": col_names,
            "io_prefs": io_prefs,
        }

class ConcatPanel(BaseToolPanel):
    use_df = False
    theme_color = "#5C6BC0"
    action_name = "纵向拼接"

    def set_incoming_outputs(self, incoming_outputs):
        self._incoming_outputs = [
            item
            for item in (incoming_outputs or [])
            if isinstance(item, dict)
            and str(item.get("name") or "").strip()
            and str(item.get("data_type") or "table") == "table"
        ]
        names = [item["name"] for item in self._incoming_outputs]
        for combo in (self.df1_combo, self.df2_combo):
            self._set_combo_items_preserving_text(combo, names)
            self._remember_combo_ref(combo)

    def _input_ref_for_combo(self, combo):
        key = (
            str(combo.property("source_node_id") or "") if combo else "",
            str(combo.property("source_output_id") or "out_1") if combo else "out_1",
        )
        for item in getattr(self, "_incoming_outputs", []) or []:
            if self._input_key(item) == key:
                return item
        name = str(combo.currentText() if combo else "").strip()
        for item in getattr(self, "_incoming_outputs", []) or []:
            if str(item.get("name") or "").strip() == name:
                return item
        return None

    @staticmethod
    def _input_key(item):
        return (
            str((item or {}).get("source_node_id") or ""),
            str((item or {}).get("source_output_id") or "out_1"),
        )

    def _set_combo_from_input(self, combo, input_item):
        if combo is None or not isinstance(input_item, dict):
            return
        names = [item["name"] for item in getattr(self, "_incoming_outputs", []) or []]
        name = str(input_item.get("name") or "").strip()
        self._set_combo_items_preserving_text(combo, names, name)
        combo.setProperty("source_node_id", str(input_item.get("source_node_id") or ""))
        combo.setProperty("source_output_id", str(input_item.get("source_output_id") or "out_1"))

    def _remember_combo_ref(self, combo):
        if combo is None:
            return
        name = str(combo.currentText() or "").strip()
        ref = next(
            (
                item
                for item in getattr(self, "_incoming_outputs", []) or []
                if str(item.get("name") or "").strip() == name
            ),
            None,
        )
        combo.setProperty("source_node_id", str((ref or {}).get("source_node_id") or ""))
        combo.setProperty("source_output_id", str((ref or {}).get("source_output_id") or "out_1"))

    def _saved_input_by_role(self, params, role, fallback_index):
        inputs = [item for item in (params or {}).get("inputs") or [] if isinstance(item, dict)]
        for item in inputs:
            if item.get("role") == role:
                return item
        return inputs[fallback_index] if fallback_index < len(inputs) else None

    def _saved_output_name(self, params):
        outputs = [item for item in (params or {}).get("outputs") or [] if isinstance(item, dict)]
        return str((outputs[0] if outputs else {}).get("name") or "")

    def _set_binary_inputs_from_params(self, params):
        self._set_combo_from_input(self.df1_combo, self._saved_input_by_role(params, "left", 0))
        self._set_combo_from_input(self.df2_combo, self._saved_input_by_role(params, "right", 1))
        if hasattr(self, "out_input"):
            name = self._saved_output_name(params)
            if name:
                self.out_input.setText(name)

    def _flow_io_prefs(self):
        refs = [self._input_ref_for_combo(self.df1_combo), self._input_ref_for_combo(self.df2_combo)]
        roles = ["left", "right"]
        prefs_inputs = []
        for ref, role in zip(refs, roles):
            if not ref:
                continue
            prefs_inputs.append(
                {
                    "source_node_id": str(ref.get("source_node_id") or ""),
                    "source_output_id": str(ref.get("source_output_id") or "out_1"),
                    "name": str(ref.get("name") or ""),
                    "role": role,
                    "data_type": "table",
                    "enabled": True,
                }
            )
        out_name = self.out_input.text().strip() if hasattr(self, "out_input") else ""
        if not out_name and prefs_inputs:
            out_name = f"{prefs_inputs[0]['name']}_{action_suffix('concat_rows')}"
        return {"inputs": prefs_inputs, "output_name": out_name, "output_data_type": "table"}

    def init_custom_ui(self):
        self.df1_combo = QComboBox()
        self.df2_combo = QComboBox()
        self.df1_combo.currentTextChanged.connect(lambda *_: self._remember_combo_ref(self.df1_combo))
        self.df2_combo.currentTextChanged.connect(lambda *_: self._remember_combo_ref(self.df2_combo))
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
        io_prefs = self._flow_io_prefs()
        return {
            "ignore_index": self.ignore_idx_combo.currentIndex() == 0,
            "io_prefs": io_prefs,
        }

    def set_custom_params(self, p):
        self._set_binary_inputs_from_params(p)
        if "ignore_index" in p:
            self.ignore_idx_combo.setCurrentIndex(0 if p["ignore_index"] else 1)
