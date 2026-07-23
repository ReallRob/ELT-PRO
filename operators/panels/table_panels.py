"""Operator panels: table_panels."""

from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
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
            self._set_input_combo_items(combo, self._incoming_outputs)
            self._remember_combo_ref(combo)
        self._refresh_col_combos()

    def _input_ref_for_combo(self, combo):
        combo_ref = self._combo_input_ref(combo)
        if combo_ref:
            return combo_ref
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

    def _dataframe_for_combo(self, combo):
        ref = self._input_ref_for_combo(combo)
        candidates = []
        if ref:
            candidates.extend([ref.get("data_key"), ref.get("name")])
        if combo is not None:
            candidates.extend([combo.property("data_key"), combo.currentText()])
        for key in candidates:
            key = str(key or "").strip()
            if key and key in self.data_pool:
                return self.data_pool.get(key)
        return None

    def _set_combo_from_input(self, combo, input_item):
        if combo is None or not isinstance(input_item, dict):
            return
        names = [item["name"] for item in getattr(self, "_incoming_outputs", []) or []]
        name = str(input_item.get("name") or "").strip()
        combo.setProperty("source_node_id", str(input_item.get("source_node_id") or ""))
        combo.setProperty("source_output_id", str(input_item.get("source_output_id") or "out_1"))
        self._set_input_combo_items(combo, getattr(self, "_incoming_outputs", []) or [], name)
        self._remember_combo_ref(combo)

    def _remember_combo_ref(self, combo):
        if combo is None:
            return
        name = str(combo.currentText() or "").strip()
        ref = self._combo_input_ref(combo)
        if not ref:
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
        combo.setProperty("data_key", str((ref or {}).get("data_key") or (ref or {}).get("name") or ""))

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
            self._refresh_key_combos_now()
            return
        self._refresh_key_combos_now()
        df = self._dataframe_for_combo(self.df2_combo) if hasattr(self, "df2_combo") else None
        self._refresh_col_combos_from_df(df)

    def _refresh_key_combos(self):
        if self._panel_update_depth:
            self._pending_col_combo_refresh = True
            return
        self._refresh_key_combos_now()

    def _refresh_key_combos_now(self):
        if not hasattr(self, "_key_rows"):
            return
        left_df = self._dataframe_for_combo(self.df1_combo) if hasattr(self, "df1_combo") else None
        right_df = self._dataframe_for_combo(self.df2_combo) if hasattr(self, "df2_combo") else None
        for row in list(self._key_rows):
            try:
                row.objectName()
            except RuntimeError:
                self._key_rows.remove(row)
                continue
            self._populate_key_combo(row.findChild(QComboBox, "left_key"), left_df)
            self._populate_key_combo(row.findChild(QComboBox, "right_key"), right_df)

    def _populate_key_combo(self, combo, df):
        if combo is None:
            return
        was_empty = not combo.currentText().strip()
        self._populate_col_combo(combo, list(enumerate(df.columns)) if df is not None else [])
        if was_empty:
            combo.setCurrentText("")

    def _make_key_combo(self, placeholder):
        combo = QComboBox()
        combo.setEditable(True)
        self._set_combo_placeholder(combo, placeholder)
        combo.setMinimumWidth(96)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        return combo

    def init_custom_ui(self):
        self.df1_combo = QComboBox()
        self.df2_combo = QComboBox()
        self.df1_combo.currentTextChanged.connect(lambda *_: self._remember_combo_ref(self.df1_combo))
        self.df1_combo.currentIndexChanged.connect(lambda *_: self._remember_combo_ref(self.df1_combo))
        self.df1_combo.currentTextChanged.connect(self._refresh_key_combos)
        self.df1_combo.currentIndexChanged.connect(self._refresh_key_combos)
        self.df2_combo.currentTextChanged.connect(self._refresh_col_combos)
        self.df2_combo.currentTextChanged.connect(lambda *_: self._remember_combo_ref(self.df2_combo))
        self.df2_combo.currentIndexChanged.connect(self._refresh_col_combos)
        self.df2_combo.currentIndexChanged.connect(lambda *_: self._remember_combo_ref(self.df2_combo))
        self.combo_boxes_to_update.extend([self.df1_combo, self.df2_combo])
        self.top_form.insertRow(0, "主表 (左):", self.df1_combo)
        self.top_form.insertRow(1, "匹配表 (右):", self.df2_combo)
        if hasattr(self, "type_combo"):
            self.type_combo.currentTextChanged.connect(self._refresh_key_combos)

        key_card, key_inner = self._make_card("匹配键映射")
        self.custom_layout.addWidget(key_card)
        self.key_layout = QVBoxLayout()
        self.key_layout.setSpacing(6)
        key_inner.addLayout(self.key_layout)
        btn_add_key = self._make_add_button("+ 添加匹配键")
        btn_add_key.clicked.connect(lambda: self.add_key_row())
        key_inner.addWidget(btn_add_key)
        self._key_rows = []
        self.add_key_row()
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
        self.clear_dynamic_layout(self.key_layout)
        self._key_rows = []
        self.add_key_row()
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    @staticmethod
    def _key_list(value):
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item or "").strip()]
        text = str(value or "").strip()
        return [text] if text else []

    def _key_pairs_from_params(self, params):
        pairs = []
        for row in params.get("join_keys") or []:
            if not isinstance(row, dict):
                continue
            left = str(row.get("left") or row.get("left_key") or row.get("l_key") or "").strip()
            right = str(row.get("right") or row.get("right_key") or row.get("r_key") or "").strip()
            if left or right:
                pairs.append((left, right))
        if pairs:
            return pairs
        left_keys = self._key_list(
            params.get("l_key")
            if "l_key" in params
            else params.get("left_keys") or params.get("left_key")
        )
        right_keys = self._key_list(
            params.get("r_key")
            if "r_key" in params
            else params.get("right_keys") or params.get("right_key")
        )
        return list(zip(left_keys, right_keys))

    def add_key_row(self, left_key="", right_key=""):
        row = QWidget()
        row.setObjectName("join_key_row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        left_combo = self._make_key_combo("左表列")
        left_combo.setObjectName("left_key")
        right_combo = self._make_key_combo("右表列")
        right_combo.setObjectName("right_key")
        arrow = QLabel("→")
        arrow.setStyleSheet("color: #64748B; border: none; font-weight: bold;")
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=row: self._remove_key_row(r))
        layout.addWidget(left_combo, stretch=1)
        layout.addWidget(arrow)
        layout.addWidget(right_combo, stretch=1)
        layout.addWidget(btn_rm)
        self.key_layout.addWidget(row)
        self._key_rows.append(row)
        self._refresh_key_combos_now()
        self._set_col_name(left_combo, left_key)
        self._set_col_name(right_combo, right_key)
        return row

    def _remove_key_row(self, row):
        if row in getattr(self, "_key_rows", []):
            self._key_rows.remove(row)
        self.remove_dynamic_row(row)
        if not getattr(self, "_key_rows", []):
            self.add_key_row()

    def _collect_key_rows(self):
        pairs = []
        valid_rows = []
        for row in getattr(self, "_key_rows", []) or []:
            try:
                left_combo = row.findChild(QComboBox, "left_key")
                right_combo = row.findChild(QComboBox, "right_key")
            except RuntimeError:
                continue
            valid_rows.append(row)
            left = self._get_col_name(left_combo)
            right = self._get_col_name(right_combo)
            if left or right:
                pairs.append({"left": left, "right": right})
        self._key_rows = valid_rows
        return pairs

    def _set_key_rows(self, pairs):
        self.clear_dynamic_layout(self.key_layout)
        self._key_rows = []
        for left, right in pairs or []:
            self.add_key_row(left, right)
        if not self._key_rows:
            self.add_key_row()

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
        self._set_key_rows(self._key_pairs_from_params(p))
        get_cols, col_names = p.get("get_cols", []), p.get("col_names", [])
        if get_cols:
            self.clear_dynamic_layout(self.rules_layout)
            for i, c in enumerate(get_cols):
                r = col_names[i] if col_names and i < len(col_names) else ""
                self.add_rule_row(c, r)

    @staticmethod
    def _compact_key_value(values):
        values = [str(value or "").strip() for value in values or [] if str(value or "").strip()]
        if len(values) == 1:
            return values[0]
        return values

    def get_custom_params(self):
        join_keys = self._collect_key_rows()
        left_keys = [row.get("left", "") for row in join_keys]
        right_keys = [row.get("right", "") for row in join_keys]
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
            "l_key": self._compact_key_value(left_keys),
            "r_key": self._compact_key_value(right_keys),
            "join_keys": join_keys,
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
            self._set_input_combo_items(combo, self._incoming_outputs)
            self._remember_combo_ref(combo)

    def _input_ref_for_combo(self, combo):
        combo_ref = self._combo_input_ref(combo)
        if combo_ref:
            return combo_ref
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
        combo.setProperty("source_node_id", str(input_item.get("source_node_id") or ""))
        combo.setProperty("source_output_id", str(input_item.get("source_output_id") or "out_1"))
        self._set_input_combo_items(combo, getattr(self, "_incoming_outputs", []) or [], name)
        self._remember_combo_ref(combo)

    def _remember_combo_ref(self, combo):
        if combo is None:
            return
        name = str(combo.currentText() or "").strip()
        ref = self._combo_input_ref(combo)
        if not ref:
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
        combo.setProperty("data_key", str((ref or {}).get("data_key") or (ref or {}).get("name") or ""))

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
        self.df1_combo.currentIndexChanged.connect(lambda *_: self._remember_combo_ref(self.df1_combo))
        self.df2_combo.currentTextChanged.connect(lambda *_: self._remember_combo_ref(self.df2_combo))
        self.df2_combo.currentIndexChanged.connect(lambda *_: self._remember_combo_ref(self.df2_combo))
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
