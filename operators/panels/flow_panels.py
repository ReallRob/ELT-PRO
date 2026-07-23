"""Flow-aware operator panels.

These panels are the first UI step toward explicit input/output metadata. They keep
operator-specific rule UIs flexible, while the base class owns the shared data-flow
rules: inputs come from canvas edges, outputs are derived from enabled inputs, and
operator names are never treated as table names.
"""

from __future__ import annotations

import copy

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from core.dataframe_ops import normalize_columns
from operators.base_panel import BaseToolPanel, QLineEdit
from parameter_resolver import clone_resolved_runtime_value


class BatchMapFlowPanel(BaseToolPanel):
    """Base panel for operators that map one rule set over many table inputs."""

    use_df = False
    use_type = True
    use_out = False
    input_data_type = "table"
    output_data_type = "table"
    output_suffix = "结果"

    def init_custom_ui(self):
        self._incoming_outputs = []
        self._saved_flow_inputs = []
        self._saved_flow_outputs = []
        self._flow_input_rows = []
        self._flow_output_rows = []

        input_card, input_inner = self._make_card("输入数据")
        self.custom_layout.addWidget(input_card)
        self.flow_inputs_layout = QVBoxLayout()
        self.flow_inputs_layout.setContentsMargins(0, 0, 0, 0)
        self.flow_inputs_layout.setSpacing(6)
        input_inner.addLayout(self.flow_inputs_layout)
        input_inner.addWidget(self._make_hint_label("输入来自画布连线，可勾选本算子需要处理的上游输出。"))

        self.build_rule_ui()

        output_card, output_inner = self._make_card("输出配置")
        self.custom_layout.addWidget(output_card)
        self.flow_outputs_layout = QVBoxLayout()
        self.flow_outputs_layout.setContentsMargins(0, 0, 0, 0)
        self.flow_outputs_layout.setSpacing(6)
        output_inner.addLayout(self.flow_outputs_layout)

        self._rebuild_flow_rows()

    def build_rule_ui(self):
        """Subclasses build their own rule section here."""

    def set_incoming_outputs(self, incoming_outputs):
        self._incoming_outputs = self._normalize_incoming_outputs(incoming_outputs)
        self._rebuild_flow_rows()
        self._refresh_df_summary()
        self._refresh_col_combos()

    def update_combos(self, table_names):
        # Legacy callers still pass names only. Treat them as display-only outputs;
        # richer callers should use set_incoming_outputs().
        if table_names and isinstance(table_names[0], dict):
            self.set_incoming_outputs(table_names)
            return
        incoming = [
            {
                "source_node_id": "",
                "source_output_id": f"out_{index}",
                "name": str(name),
                "data_type": self.input_data_type,
            }
            for index, name in enumerate(table_names or [], start=1)
            if str(name or "").strip()
        ]
        self.set_incoming_outputs(incoming)

    def clear_ui(self):
        self.begin_panel_update()
        try:
            if hasattr(self, "operation_name_input"):
                self.operation_name_input.clear()
            self._saved_flow_inputs = []
            self._saved_flow_outputs = []
            self.clear_custom_ui()
            self._rebuild_flow_rows()
        finally:
            self.end_panel_update()

    def set_params(self, params):
        self.begin_panel_update()
        try:
            if hasattr(self, "operation_name_input"):
                self.operation_name_input.setText(str(params.get("operation_name") or ""))
            self._saved_flow_inputs = copy.deepcopy(params.get("inputs") or [])
            self._saved_flow_outputs = copy.deepcopy(params.get("outputs") or [])
            if self.use_type:
                type_map = {"col_name": "列名", "col_word": "字母", "col_index": "索引"}
                col_type = params.get("col_type", "")
                if col_type in type_map:
                    self.type_combo.setCurrentText(type_map[col_type])
            self.set_custom_params(params)
            self._rebuild_flow_rows()
        finally:
            self.end_panel_update()

    def get_params(self):
        params = {}
        if hasattr(self, "operation_name_input"):
            operation_name = self.operation_name_input.text().strip()
            if operation_name:
                params["operation_name"] = operation_name
        if self.use_type:
            type_map = {"列名": "col_name", "字母": "col_word", "索引": "col_index"}
            params["col_type"] = type_map.get(self.type_combo.currentText(), "col_name")
        inputs = self._collect_flow_inputs()
        outputs = self._collect_flow_outputs(inputs)
        params["io_prefs"] = {
            "inputs": self._input_prefs_for_save(inputs),
            "outputs": self._output_prefs_for_save(outputs),
        }
        params.update(self.get_custom_params())
        if self._resolve_params_on_get:
            self._last_raw_params = copy.deepcopy(params)
            return clone_resolved_runtime_value(
                params,
                self._runtime_parameters,
                self._parameter_mappings,
                strict=True,
            )
        return params

    def _validate(self):
        inputs = [item for item in self._collect_flow_inputs() if item.get("enabled", True)]
        if not inputs:
            QMessageBox.warning(self, "错误", "请先连接并勾选至少一个输入数据。")
            return False, None
        return True, None

    def _on_execute(self):
        if not self._emit_save_requested(show_error=True):
            return
        ok, _ = self._validate()
        if not ok:
            return
        try:
            params = self.get_params()
        except Exception as exc:
            QMessageBox.warning(self, "运行配置失败", str(exc))
            return
        self.run_requested.emit(self._panel_action_key or self.action_name, copy.deepcopy(params))

    def _normalize_incoming_outputs(self, incoming_outputs):
        rows = []
        for index, item in enumerate(incoming_outputs or [], start=1):
            if not isinstance(item, dict):
                name = str(item or "").strip()
                if not name:
                    continue
                item = {"name": name, "source_output_id": f"out_{index}", "data_type": self.input_data_type}
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            rows.append(
                {
                    "source_node_id": str(item.get("source_node_id") or ""),
                    "source_output_id": str(item.get("source_output_id") or f"out_{index}"),
                    "name": name,
                    "data_type": str(item.get("data_type") or self.input_data_type),
                    "data_key": str(item.get("data_key") or ""),
                }
            )
        return rows

    def _input_key(self, item):
        return (
            str(item.get("source_node_id") or ""),
            str(item.get("source_output_id") or ""),
            str(item.get("name") or ""),
        )

    def _saved_input_by_key(self):
        saved = {}
        for item in self._saved_flow_inputs or []:
            if isinstance(item, dict):
                saved[self._input_key(item)] = item
        return saved

    def _saved_output_name(self, input_item, input_id):
        for output in self._saved_flow_outputs or []:
            if not isinstance(output, dict):
                continue
            if output.get("from_input_id") == input_id:
                name = str(output.get("name") or "").strip()
                if name:
                    return name
            if (
                output.get("source_node_id") == input_item.get("source_node_id")
                and output.get("source_output_id") == input_item.get("source_output_id")
            ):
                name = str(output.get("name") or "").strip()
                if name:
                    return name
        return ""

    def _default_output_name(self, input_name):
        base = str(input_name or "输入表").strip() or "输入表"
        return f"{base}_{self.output_suffix}"

    def _merged_flow_inputs(self):
        saved_by_key = self._saved_input_by_key()
        rows = []
        for index, incoming in enumerate(self._incoming_outputs, start=1):
            saved = saved_by_key.get(self._input_key(incoming), {})
            rows.append(
                {
                    "input_id": f"in_{index}",
                    "source_node_id": incoming.get("source_node_id", ""),
                    "source_output_id": incoming.get("source_output_id", f"out_{index}"),
                    "name": incoming.get("name", ""),
                    "data_type": incoming.get("data_type", self.input_data_type),
                    "data_key": incoming.get("data_key", ""),
                    "enabled": bool(saved.get("enabled", True)),
                }
            )
        return rows

    def _rebuild_flow_rows(self):
        if not hasattr(self, "flow_inputs_layout"):
            return
        self.clear_dynamic_layout(self.flow_inputs_layout)
        self.clear_dynamic_layout(self.flow_outputs_layout)
        self._flow_input_rows = []
        self._flow_output_rows = []
        rows = self._merged_flow_inputs()
        if not rows:
            empty = QLabel("未连接输入。请从画布左侧连接上游输出。")
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #94A3B8; padding: 8px; border: 1px dashed #CBD5E1; border-radius: 6px;")
            self.flow_inputs_layout.addWidget(empty)
            self._refresh_df_summary()
            return

        for row in rows:
            self._add_input_row(row)
        self._sync_output_rows()
        self._refresh_df_summary()

    def _add_input_row(self, item):
        row = QWidget()
        row.setObjectName("flow_input_row")
        row.setProperty("source_node_id", item.get("source_node_id", ""))
        row.setProperty("source_output_id", item.get("source_output_id", ""))
        row.setProperty("data_type", item.get("data_type", self.input_data_type))
        row.setProperty("data_key", item.get("data_key", ""))
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        checkbox = QCheckBox()
        checkbox.setObjectName("enabled")
        checkbox.setChecked(item.get("enabled", True))
        checkbox.stateChanged.connect(lambda *_: self._sync_output_rows())
        name_label = QLabel(item.get("name", ""))
        name_label.setObjectName("name")
        name_label.setToolTip(item.get("name", ""))
        name_label.setStyleSheet("color: #334155; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 5px 7px;")
        source_label = QLabel(item.get("source_output_id", ""))
        source_label.setObjectName("source_output_id_label")
        source_label.setAlignment(Qt.AlignCenter)
        source_label.setFixedWidth(52)
        source_label.setStyleSheet("color: #64748B; border: none;")
        layout.addWidget(checkbox)
        layout.addWidget(source_label)
        layout.addWidget(name_label, stretch=1)
        self.flow_inputs_layout.addWidget(row)
        self._flow_input_rows.append(row)

    def _sync_output_rows(self):
        if not hasattr(self, "flow_outputs_layout"):
            return
        previous = self._collect_existing_output_rows()
        if previous:
            self._saved_flow_outputs = previous
        self.clear_dynamic_layout(self.flow_outputs_layout)
        self._flow_output_rows = []
        enabled_inputs = [item for item in self._collect_flow_inputs() if item.get("enabled", True)]
        if not enabled_inputs:
            empty = QLabel("未勾选输入，当前节点不会产生输出。")
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #94A3B8; padding: 8px; border: 1px dashed #CBD5E1; border-radius: 6px;")
            self.flow_outputs_layout.addWidget(empty)
            return
        for index, input_item in enumerate(enabled_inputs, start=1):
            self._add_output_row(index, input_item)
        self._refresh_col_combos()

    def _add_output_row(self, index, input_item):
        row = QWidget()
        row.setObjectName("flow_output_row")
        row.setProperty("from_input_id", input_item.get("input_id"))
        row.setProperty("source_node_id", input_item.get("source_node_id", ""))
        row.setProperty("source_output_id", input_item.get("source_output_id", ""))
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        source_label = QLabel(input_item.get("name", ""))
        source_label.setObjectName("input_name")
        source_label.setToolTip(input_item.get("name", ""))
        source_label.setStyleSheet("color: #64748B; border: none;")
        out_input = QLineEdit(
            self._saved_output_name(input_item, input_item.get("input_id"))
            or self._default_output_name(input_item.get("name"))
        )
        out_input.setObjectName("output_name")
        out_input.setPlaceholderText(self._default_output_name(input_item.get("name")))
        layout.addWidget(QLabel(f"out_{index}"))
        layout.addWidget(source_label, stretch=1)
        layout.addWidget(out_input, stretch=1)
        self.flow_outputs_layout.addWidget(row)
        self._flow_output_rows.append(row)

    def _collect_existing_output_rows(self):
        outputs = []
        for row in getattr(self, "_flow_output_rows", []):
            out_input = row.findChild(QLineEdit, "output_name")
            name = out_input.text().strip() if out_input else ""
            from_input_id = str(row.property("from_input_id") or "")
            if not from_input_id or not name:
                continue
            outputs.append(
                {
                    "from_input_id": from_input_id,
                    "name": name,
                    "source_node_id": str(row.property("source_node_id") or ""),
                    "source_output_id": str(row.property("source_output_id") or ""),
                    "data_type": self.output_data_type,
                }
            )
        return outputs

    def _collect_flow_inputs(self):
        rows = []
        for index, row in enumerate(getattr(self, "_flow_input_rows", []), start=1):
            name_label = row.findChild(QLabel, "name")
            checkbox = row.findChild(QCheckBox, "enabled")
            name = name_label.text().strip() if name_label else ""
            if not name:
                continue
            rows.append(
                {
                    "input_id": f"in_{index}",
                    "source_node_id": str(row.property("source_node_id") or ""),
                    "source_output_id": str(row.property("source_output_id") or f"out_{index}"),
                    "name": name,
                    "data_type": str(row.property("data_type") or self.input_data_type),
                    "data_key": str(row.property("data_key") or ""),
                    "enabled": checkbox.isChecked() if checkbox else True,
                }
            )
        return rows

    def _collect_flow_outputs(self, inputs=None):
        inputs = inputs or self._collect_flow_inputs()
        enabled_inputs = [item for item in inputs if item.get("enabled", True)]
        outputs = []
        output_rows = list(getattr(self, "_flow_output_rows", []))
        for index, input_item in enumerate(enabled_inputs, start=1):
            output_name = ""
            if index - 1 < len(output_rows):
                out_input = output_rows[index - 1].findChild(QLineEdit, "output_name")
                output_name = out_input.text().strip() if out_input else ""
            outputs.append(
                {
                    "output_id": f"out_{index}",
                    "name": output_name or self._default_output_name(input_item.get("name")),
                    "from_input_id": input_item.get("input_id"),
                    "source_node_id": input_item.get("source_node_id", ""),
                    "source_output_id": input_item.get("source_output_id", ""),
                    "data_type": self.output_data_type,
                }
            )
        return outputs

    def _input_prefs_for_save(self, inputs):
        prefs = []
        for item in inputs or []:
            if not isinstance(item, dict):
                continue
            prefs.append(
                {
                    "source_node_id": str(item.get("source_node_id") or ""),
                    "source_output_id": str(item.get("source_output_id") or "out_1"),
                    "name": str(item.get("name") or ""),
                    "data_type": str(item.get("data_type") or self.input_data_type),
                    "enabled": bool(item.get("enabled", True)),
                }
            )
        return prefs

    def _output_prefs_for_save(self, outputs):
        prefs = []
        for item in outputs or []:
            if not isinstance(item, dict):
                continue
            prefs.append(
                {
                    "name": str(item.get("name") or ""),
                    "source_node_id": str(item.get("source_node_id") or ""),
                    "source_output_id": str(item.get("source_output_id") or "out_1"),
                    "data_type": self.output_data_type,
                }
            )
        return prefs

    def _first_enabled_input_name(self):
        for item in self._collect_flow_inputs():
            if item.get("enabled", True):
                return item.get("name", "")
        return ""

    def _first_enabled_input(self):
        for item in self._collect_flow_inputs():
            if item.get("enabled", True):
                return item
        return None

    def _first_enabled_dataframe(self):
        item = self._first_enabled_input()
        if not item:
            return None
        for key in (item.get("data_key"), item.get("name")):
            key = str(key or "").strip()
            if key and key in self.data_pool:
                return self.data_pool.get(key)
        return None

    def _refresh_df_summary_now(self):
        count = len([item for item in self._collect_flow_inputs() if item.get("enabled", True)])
        if hasattr(self, "panel_hint"):
            self.panel_hint.setText(f"输入: {count} 个上游输出" if count else "未连接输入")

    def _refresh_col_combos_now(self):
        if not hasattr(self, "_col_combos"):
            return
        df = self._first_enabled_dataframe()
        self._refresh_col_combos_from_df(df)


class FilterFlowPanel(BatchMapFlowPanel):
    """Flow-aware filter panel used as the first migration target."""

    theme_color = "#E91E63"
    action_name = "筛选"
    output_suffix = "筛选"

    OP_MAP = {
        "大于": ">", "小于": "<", "大于等于": ">=", "小于等于": "<=",
        "等于": "==", "不等于": "!=",
        "包含": "contains", "不包含": "not_contains",
        "开头是": "startswith", "结尾是": "endswith",
        "为空": "isnull", "不为空": "notnull",
    }
    OP_REV = {v: k for k, v in OP_MAP.items()}

    def build_rule_ui(self):
        self.logic_combo = QComboBox()
        self.logic_combo.addItems(["AND (满足所有)", "OR (满足其一)"])
        self.top_form.addRow("条件逻辑:", self.logic_combo)

        card, inner = self._make_card("规则配置")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(6)
        inner.addLayout(self.rules_layout)
        self.add_rule()
        btn_add = self._make_add_button("+ 添加筛选条件")
        btn_add.clicked.connect(lambda: self.add_rule())
        inner.addWidget(btn_add)

    def clear_custom_ui(self):
        if hasattr(self, "rules_layout"):
            self.clear_dynamic_layout(self.rules_layout)
            self.add_rule()

    def add_rule(self, col="", op="等于", val=""):
        summary = f"{col or '?'} {op} {val}" if col or val else "新筛选条件"
        container, header_btn, body = self._make_collapsible_rule(summary)
        body.setObjectName("rule_body")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 8, 10, 10)
        body_layout.setSpacing(8)

        column_row = QHBoxLayout()
        column_row.setContentsMargins(0, 0, 0, 0)
        column_row.setSpacing(6)
        column_row.addWidget(self._inline_label("列"))
        col_combo = self._make_col_combo("筛选列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        col_combo.currentTextChanged.connect(lambda: self._update_filter_summary(container, header_btn))
        column_row.addWidget(col_combo, stretch=1)
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=container: self.remove_dynamic_row(r))
        column_row.addWidget(btn_rm)
        body_layout.addLayout(column_row)

        condition_row = QHBoxLayout()
        condition_row.setContentsMargins(0, 0, 0, 0)
        condition_row.setSpacing(6)
        condition_row.addWidget(self._inline_label("条件"))
        op_combo = QComboBox()
        op_combo.setObjectName("op")
        op_combo.addItems(list(self.OP_MAP.keys()))
        if op in self.OP_MAP:
            op_combo.setCurrentText(op)
        elif op in self.OP_REV:
            op_combo.setCurrentText(self.OP_REV[op])
        op_combo.currentTextChanged.connect(lambda: self._update_filter_summary(container, header_btn))
        condition_row.addWidget(op_combo)
        condition_row.addWidget(self._inline_label("值"))
        value_input = QLineEdit(str(val))
        value_input.setObjectName("val")
        value_input.setPlaceholderText("目标值")
        value_input.textChanged.connect(lambda: self._update_filter_summary(container, header_btn))
        condition_row.addWidget(value_input, stretch=1)
        body_layout.addLayout(condition_row)
        self.rules_layout.addWidget(container)

    def _update_filter_summary(self, container, header_btn):
        body = container.findChild(QWidget, "rule_body")
        if not body:
            return
        col_combo = body.findChild(QComboBox, "col")
        op_combo = body.findChild(QComboBox, "op")
        value_input = body.findChild(QLineEdit, "val")
        col = self._get_col_name(col_combo) if col_combo else "?"
        op = op_combo.currentText() if op_combo else "?"
        value = value_input.text() if value_input else ""
        summary = f"{col or '?'} {op} {value}" if (col or value) else "新筛选条件"
        self._update_rule_summary(header_btn, summary)

    def set_custom_params(self, params):
        self._set_combo_by_prefix(self.logic_combo, params.get("logic"))
        conditions = params.get("conditions", [])
        if conditions:
            self.clear_dynamic_layout(self.rules_layout)
            for condition in conditions:
                self.add_rule(condition.get("col"), condition.get("op"), condition.get("value"))

    def get_custom_params(self):
        conditions = []
        for index in range(self.rules_layout.count()):
            widget = self.rules_layout.itemAt(index).widget()
            if not widget:
                continue
            col = self._get_col_name(widget.findChild(QComboBox, "col"))
            op_cn = widget.findChild(QComboBox, "op").currentText()
            op = self.OP_MAP.get(op_cn, "==")
            value = widget.findChild(QLineEdit, "val").text().strip()
            if col:
                conditions.append({"col": col, "op": op, "value": value})
        return {"logic": self.logic_combo.currentText().split(" ")[0], "conditions": conditions}

    def _validate(self):
        ok, widget = super()._validate()
        if not ok:
            return ok, widget
        if not self.get_custom_params().get("conditions"):
            QMessageBox.warning(self, "错误", "缺少筛选条件")
            return False, None
        return True, None

class SortFlowPanel(BatchMapFlowPanel):
    """Flow-aware multi-table sort panel."""

    theme_color = "#FF9800"
    action_name = "排序"
    output_suffix = "排序"

    def build_rule_ui(self):
        card, inner = self._make_card("规则配置")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(6)
        inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = self._make_add_button("+ 添加排序规则")
        btn_add.clicked.connect(lambda: self.add_rule_row())
        inner.addWidget(btn_add)
        inner.addWidget(self._make_hint_label("升序从小到大，降序从大到小；自定义用于高、中、低等业务顺序。"))

    def clear_custom_ui(self):
        if hasattr(self, "rules_layout"):
            self.clear_dynamic_layout(self.rules_layout)
            self.add_rule_row()

    def add_rule_row(self, col="", asc=True, custom_order=None):
        custom_order = custom_order or []
        order_text = "自定义" if custom_order else ("升序" if asc else "降序")
        summary = f"{col or '?'} · {order_text}" if col else "新排序规则"
        container, header_btn, body = self._make_collapsible_rule(summary)
        body.setObjectName("rule_body")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 8, 10, 10)
        body_layout.setSpacing(8)

        col_row = QHBoxLayout()
        col_row.setContentsMargins(0, 0, 0, 0)
        col_row.setSpacing(6)
        col_row.addWidget(self._inline_label("列"))
        col_combo = self._make_col_combo("排序列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        col_combo.currentTextChanged.connect(lambda: self._update_sort_summary(container, header_btn))
        col_row.addWidget(col_combo, stretch=1)
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=container: self.remove_dynamic_row(r))
        col_row.addWidget(btn_rm)
        body_layout.addLayout(col_row)

        order_row = QHBoxLayout()
        order_row.setContentsMargins(0, 0, 0, 0)
        order_row.setSpacing(6)
        order_row.addWidget(self._inline_label("顺序"))
        asc_combo = QComboBox()
        asc_combo.setObjectName("asc")
        asc_combo.addItems(["升序", "降序", "自定义"])
        asc_combo.currentTextChanged.connect(lambda: self._update_sort_summary(container, header_btn))
        order_row.addWidget(asc_combo)
        order_row.addStretch(1)
        body_layout.addLayout(order_row)

        custom_area = QWidget()
        custom_area.setObjectName("custom_area")
        custom_layout = QVBoxLayout(custom_area)
        custom_layout.setContentsMargins(12, 4, 0, 0)
        custom_layout.setSpacing(3)

        def add_custom_row(value=""):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            inp = QLineEdit(str(value))
            inp.setObjectName("custom_val")
            inp.setPlaceholderText("排序值")
            rm = self._make_delete_button()
            rm.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
            row_layout.addWidget(inp)
            row_layout.addWidget(rm)
            row_layout.addStretch()
            custom_layout.addWidget(row)

        for value in custom_order:
            add_custom_row(value)
        btn_add_custom = self._make_add_button("+ 添加排序值")
        btn_add_custom.clicked.connect(lambda: add_custom_row())
        custom_layout.addWidget(btn_add_custom)
        asc_combo.setCurrentIndex(2 if custom_order else (0 if asc else 1))
        asc_combo.currentIndexChanged.connect(lambda idx, area=custom_area: area.setVisible(idx == 2))
        custom_area.setVisible(asc_combo.currentIndex() == 2)
        body_layout.addWidget(custom_area)
        self.rules_layout.addWidget(container)

    def _update_sort_summary(self, container, header_btn):
        body = container.findChild(QWidget, "rule_body")
        if not body:
            return
        col_combo = body.findChild(QComboBox, "col")
        asc_combo = body.findChild(QComboBox, "asc")
        col = self._get_col_name(col_combo) if col_combo else ""
        order = asc_combo.currentText() if asc_combo else "?"
        self._update_rule_summary(header_btn, f"{col or '?'} · {order}" if col else "新排序规则")

    def set_custom_params(self, params):
        rules = params.get("sort_rules", [])
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for rule in rules:
                self.add_rule_row(rule.get("col"), rule.get("ascending", True), rule.get("custom_order", []))

    def get_custom_params(self):
        rules = []
        for index in range(self.rules_layout.count()):
            widget = self.rules_layout.itemAt(index).widget()
            if not widget:
                continue
            col = self._get_col_name(widget.findChild(QComboBox, "col"))
            asc_idx = widget.findChild(QComboBox, "asc").currentIndex()
            custom_values = []
            if asc_idx == 2:
                custom_area = widget.findChild(QWidget, "custom_area")
                if custom_area:
                    for inp in custom_area.findChildren(QLineEdit, "custom_val"):
                        value = inp.text().strip()
                        if value:
                            custom_values.append(value)
            if col:
                rules.append({"col": col, "ascending": True if asc_idx == 2 else asc_idx == 0, "custom_order": custom_values})
        return {"sort_rules": rules}

    def _validate(self):
        ok, widget = super()._validate()
        if not ok:
            return ok, widget
        if not self.get_custom_params().get("sort_rules"):
            QMessageBox.warning(self, "错误", "缺少排序规则")
            return False, None
        return True, None

class CleanFlowPanel(BatchMapFlowPanel):
    """Flow-aware multi-table cleaning panel."""

    theme_color = "#FF5722"
    action_name = "清洗"
    output_suffix = "清洗"

    ACT_CN_MAP = {
        "转数字": "to_numeric", "转文本": "to_string", "转整数": "to_int",
        "转浮点": "to_float", "转日期": "to_datetime",
        "去空格": "strip_space", "填空值": "fill_na", "删空行": "drop_na",
        "文本替换": "replace", "转大写": "upper_case", "转小写": "lower_case",
        "四舍五入": "round_val", "裁剪范围": "clip",
    }
    ACT_EN_MAP = {value: key for key, value in ACT_CN_MAP.items()}
    ACT_PARAM_SPECS = {
        "填空值": [("param_val", "填充值")],
        "文本替换": [("param_val", "旧文本→新文本")],
        "四舍五入": [("param_val", "小数位")],
        "裁剪范围": [("param_val", "最小值,最大值")],
        "转日期": [("param_val", "@date")],
    }
    DATE_FORMATS = [
        ("自动识别", ""), ("YYYY-MM-DD", "%Y-%m-%d"),
        ("YYYY/MM/DD", "%Y/%m/%d"), ("YYYY年MM月DD日", "%Y年%m月%d日"),
        ("DD/MM/YYYY", "%d/%m/%Y"), ("MM/DD/YYYY", "%m/%d/%Y"),
        ("YYYYMMDD", "%Y%m%d"), ("自定义...", "__custom__"),
    ]

    def build_rule_ui(self):
        card, inner = self._make_card("规则配置")
        self.custom_layout.addWidget(card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(6)
        inner.addLayout(self.rules_layout)
        self.add_rule()
        btn_add = self._make_add_button("+ 添加清洗规则")
        btn_add.clicked.connect(lambda: self.add_rule())
        inner.addWidget(btn_add)

    def clear_custom_ui(self):
        if hasattr(self, "rules_layout"):
            self.clear_dynamic_layout(self.rules_layout)
            self.add_rule()

    def add_rule(self, col="", action="to_numeric", fill_val=""):
        cn_action = self.ACT_EN_MAP.get(action, action)
        summary = f"{col or '?'} -> {cn_action}" if col else "新清洗规则"
        container, header_btn, body = self._make_collapsible_rule(summary)
        body.setObjectName("rule_body")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 8, 10, 10)
        body_layout.setSpacing(8)

        col_row = QHBoxLayout()
        col_row.setContentsMargins(0, 0, 0, 0)
        col_row.setSpacing(6)
        col_row.addWidget(self._inline_label("列"))
        col_combo = self._make_col_combo("清洗列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        col_combo.currentTextChanged.connect(lambda: self._update_clean_summary(container, header_btn))
        col_row.addWidget(col_combo, stretch=1)
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=container: self.remove_dynamic_row(r))
        col_row.addWidget(btn_rm)
        body_layout.addLayout(col_row)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)
        action_row.addWidget(self._inline_label("操作"))
        action_combo = QComboBox()
        action_combo.setObjectName("action")
        action_combo.addItems(list(self.ACT_CN_MAP.keys()))
        action_combo.setCurrentText(cn_action)
        action_combo.currentTextChanged.connect(
            lambda text, c=container, h=header_btn: (self._update_clean_summary(c, h), self._build_clean_params(c, text))
        )
        action_row.addWidget(action_combo)
        action_row.addStretch(1)
        body_layout.addLayout(action_row)
        self._build_clean_params(container, cn_action, fill_val)
        self.rules_layout.addWidget(container)

    def _build_clean_params(self, container, cn_action, fill_val=""):
        old = container.findChild(QWidget, "param_area")
        if old:
            container.layout().removeWidget(old)
            self.remove_dynamic_row(old)
        specs = self.ACT_PARAM_SPECS.get(cn_action)
        if not specs:
            return
        area = QWidget()
        area.setObjectName("param_area")
        area_layout = QVBoxLayout(area)
        area_layout.setContentsMargins(0, 4, 0, 0)
        area_layout.setSpacing(6)
        for _obj_name, placeholder in specs:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(self._inline_label("参数"))
            if placeholder == "@date":
                fmt_combo = QComboBox()
                fmt_combo.setObjectName("fill")
                for label, code in self.DATE_FORMATS:
                    fmt_combo.addItem(label, userData=code)
                if fill_val:
                    idx = fmt_combo.findData(fill_val)
                    fmt_combo.setCurrentIndex(idx if idx >= 0 else len(self.DATE_FORMATS) - 1)
                custom_input = QLineEdit()
                custom_input.setObjectName("fill_custom")
                custom_input.setPlaceholderText("自定义格式...")
                custom_input.setVisible(fmt_combo.currentData() == "__custom__")
                if custom_input.isVisible() and fill_val:
                    custom_input.setText(fill_val)
                fmt_combo.currentTextChanged.connect(lambda _t, ci=custom_input, fc=fmt_combo: ci.setVisible(fc.currentData() == "__custom__"))
                row.addWidget(fmt_combo, stretch=1)
                row.addWidget(custom_input, stretch=1)
            else:
                inp = QLineEdit()
                inp.setObjectName("fill")
                inp.setPlaceholderText(placeholder)
                if fill_val:
                    inp.setText(str(fill_val))
                row.addWidget(inp, stretch=1)
            area_layout.addLayout(row)
        container.layout().addWidget(area)

    def _update_clean_summary(self, container, header_btn):
        body = container.findChild(QWidget, "rule_body")
        if not body:
            return
        col_combo = body.findChild(QComboBox, "col")
        action_combo = body.findChild(QComboBox, "action")
        col = self._get_col_name(col_combo) if col_combo else "?"
        action = action_combo.currentText() if action_combo else "?"
        self._update_rule_summary(header_btn, f"{col} -> {action}" if col != "?" else "新清洗规则")

    def set_custom_params(self, params):
        self.clear_dynamic_layout(self.rules_layout)
        rules = params.get("rules", [])
        if rules:
            for rule in rules:
                self.add_rule(rule.get("cols"), rule.get("action"), rule.get("fill_value"))
        else:
            self.add_rule()

    def get_custom_params(self):
        rules = []
        for index in range(self.rules_layout.count()):
            widget = self.rules_layout.itemAt(index).widget()
            if not widget:
                continue
            body = widget.findChild(QWidget, "rule_body")
            if not body:
                continue
            col = self._get_col_name(body.findChild(QComboBox, "col"))
            action_combo = body.findChild(QComboBox, "action")
            action = self.ACT_CN_MAP.get(action_combo.currentText(), action_combo.currentText()) if action_combo else ""
            if not col:
                continue
            fill_val = ""
            area = widget.findChild(QWidget, "param_area")
            if area:
                fmt_combo = area.findChild(QComboBox, "fill")
                if fmt_combo:
                    code = fmt_combo.currentData()
                    if code == "__custom__":
                        custom_input = area.findChild(QLineEdit, "fill_custom")
                        fill_val = custom_input.text().strip() if custom_input else ""
                    else:
                        fill_val = code
                else:
                    plain = area.findChild(QLineEdit, "fill")
                    fill_val = plain.text().strip() if plain else ""
            rules.append({"cols": col, "action": action, "fill_value": fill_val})
        return {"rules": rules}

    def _validate(self):
        ok, widget = super()._validate()
        if not ok:
            return ok, widget
        if not self.get_custom_params().get("rules"):
            QMessageBox.warning(self, "错误", "缺少清洗规则")
            return False, None
        return True, None

class GroupFlowPanel(BatchMapFlowPanel):
    """Flow-aware multi-table group aggregation panel."""

    theme_color = "#673AB7"
    action_name = "汇总"
    output_suffix = "汇总"
    AGG_FUNCS = ["sum", "mean", "max", "min", "count", "first"]

    def build_rule_ui(self):
        key_card, key_inner = self._make_card("分组依据")
        self.custom_layout.addWidget(key_card)
        self.group_keys_layout = QVBoxLayout()
        self.group_keys_layout.setSpacing(6)
        key_inner.addLayout(self.group_keys_layout)
        self.add_group_key_row()
        btn_add_key = self._make_add_button("+ 添加分组列")
        btn_add_key.clicked.connect(lambda: self.add_group_key_row())
        key_inner.addWidget(btn_add_key)

        rule_card, rule_inner = self._make_card("聚合统计规则")
        self.custom_layout.addWidget(rule_card)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(6)
        rule_inner.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = self._make_add_button("+ 添加聚合规则")
        btn_add.clicked.connect(lambda: self.add_rule_row())
        rule_inner.addWidget(btn_add)
        rule_inner.addWidget(self._make_hint_label("sum 求和，mean 平均，max/min 最大最小，count 计数，first 取第一行。"))

    def clear_custom_ui(self):
        if hasattr(self, "group_keys_layout"):
            self.clear_dynamic_layout(self.group_keys_layout)
            self.add_group_key_row()
        if hasattr(self, "rules_layout"):
            self.clear_dynamic_layout(self.rules_layout)
            self.add_rule_row()

    def add_group_key_row(self, col=""):
        row = QWidget()
        row.setObjectName("group_key_row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._inline_label("列"))
        col_combo = self._make_col_combo("分组列")
        col_combo.setObjectName("group_col")
        self._set_col_name(col_combo, str(col))
        layout.addWidget(col_combo, stretch=1)
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
        layout.addWidget(btn_rm)
        self.group_keys_layout.addWidget(row)

    def add_rule_row(self, col="", func="sum", rename=""):
        func = func if func in self.AGG_FUNCS else "sum"
        summary = self._group_rule_summary(col, func, rename)
        container, header_btn, body = self._make_collapsible_rule(summary)
        body.setObjectName("rule_body")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 8, 10, 10)
        body_layout.setSpacing(8)

        col_row = QHBoxLayout()
        col_row.setContentsMargins(0, 0, 0, 0)
        col_row.setSpacing(6)
        col_row.addWidget(self._inline_label("列"))
        col_combo = self._make_col_combo("运算列")
        col_combo.setObjectName("col")
        self._set_col_name(col_combo, str(col))
        col_combo.currentTextChanged.connect(lambda: self._update_group_rule_summary(container, header_btn))
        col_row.addWidget(col_combo, stretch=1)
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=container: self.remove_dynamic_row(r))
        col_row.addWidget(btn_rm)
        body_layout.addLayout(col_row)

        option_row = QHBoxLayout()
        option_row.setContentsMargins(0, 0, 0, 0)
        option_row.setSpacing(6)
        option_row.addWidget(self._inline_label("方式"))
        func_combo = QComboBox()
        func_combo.setObjectName("func")
        func_combo.addItems(self.AGG_FUNCS)
        func_combo.setCurrentText(func)
        func_combo.currentTextChanged.connect(lambda: self._update_group_rule_summary(container, header_btn))
        option_row.addWidget(func_combo)
        option_row.addWidget(self._inline_label("命名"))
        rename_input = QLineEdit(str(rename or ""))
        rename_input.setObjectName("rename")
        rename_input.setPlaceholderText("可选")
        rename_input.textChanged.connect(lambda: self._update_group_rule_summary(container, header_btn))
        option_row.addWidget(rename_input, stretch=1)
        body_layout.addLayout(option_row)
        self.rules_layout.addWidget(container)

    def _group_rule_summary(self, col, func, rename):
        if not col:
            return "新聚合规则"
        suffix = f" -> {rename}" if rename else ""
        return f"{col} · {func}{suffix}"

    def _update_group_rule_summary(self, container, header_btn):
        body = container.findChild(QWidget, "rule_body")
        if not body:
            return
        col = self._get_col_name(body.findChild(QComboBox, "col"))
        func_combo = body.findChild(QComboBox, "func")
        rename_input = body.findChild(QLineEdit, "rename")
        func = func_combo.currentText() if func_combo else "sum"
        rename = rename_input.text().strip() if rename_input else ""
        self._update_rule_summary(header_btn, self._group_rule_summary(col, func, rename))

    def set_custom_params(self, params):
        self.clear_dynamic_layout(self.group_keys_layout)
        group_keys = params.get("group_key", [])
        if group_keys:
            for key in group_keys:
                self.add_group_key_row(key)
        else:
            self.add_group_key_row()

        self.clear_dynamic_layout(self.rules_layout)
        rules = params.get("agg_rules", [])
        if rules:
            for rule in rules:
                self.add_rule_row(rule.get("col"), rule.get("func", "sum"), rule.get("rename"))
        else:
            self.add_rule_row()

    def get_custom_params(self):
        group_keys = []
        for index in range(self.group_keys_layout.count()):
            widget = self.group_keys_layout.itemAt(index).widget()
            if not widget:
                continue
            col = self._get_col_name(widget.findChild(QComboBox, "group_col"))
            if col:
                group_keys.append(col)

        rules = []
        for index in range(self.rules_layout.count()):
            widget = self.rules_layout.itemAt(index).widget()
            if not widget:
                continue
            body = widget.findChild(QWidget, "rule_body")
            if not body:
                continue
            col = self._get_col_name(body.findChild(QComboBox, "col"))
            func_combo = body.findChild(QComboBox, "func")
            rename_input = body.findChild(QLineEdit, "rename")
            func = func_combo.currentText() if func_combo else "sum"
            rename = rename_input.text().strip() if rename_input else ""
            if col:
                rules.append({"col": col, "func": func, "rename": rename})
        return {"group_key": group_keys, "agg_rules": rules}

    def _validate(self):
        ok, widget = super()._validate()
        if not ok:
            return ok, widget
        custom_params = self.get_custom_params()
        if not custom_params.get("group_key"):
            QMessageBox.warning(self, "错误", "缺少分组列")
            return False, None
        if not custom_params.get("agg_rules"):
            QMessageBox.warning(self, "错误", "缺少聚合规则")
            return False, None
        return True, None

    def _build_col_dict(self, rules):
        col_dict = {}
        for rule in rules:
            col = rule.get("col")
            func = rule.get("func") or "sum"
            if not col:
                continue
            if col in col_dict:
                if isinstance(col_dict[col], list):
                    col_dict[col].append(func)
                else:
                    col_dict[col] = [col_dict[col], func]
            else:
                col_dict[col] = func
        return col_dict

    def _apply_renames(self, df, source_df, rules, col_type):
        rename_dict = {}
        for rule in rules:
            rename = str(rule.get("rename") or "").strip()
            if not rename:
                continue
            actual_cols = normalize_columns(source_df, [rule.get("col")], col_type)
            if actual_cols:
                rename_dict[f"{actual_cols[0]}_{rule.get('func', 'sum')}"] = rename
        return df.rename(columns=rename_dict) if rename_dict else df
