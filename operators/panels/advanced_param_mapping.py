"""Advanced parameter mapping operator panel."""

import json

import pandas as pd
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.parameters.mapping_schema import (
    DATA_TYPES,
    build_rule_engine_config,
    coerce_parameter_rows,
    format_advanced_value,
    normalize_mapping_groups,
)
from operators.base_panel import BaseToolPanel, QLineEdit


class AdvancedMappingDialog(QDialog):
    SOURCE_MODES = [
        ("精确匹配", "exact"),
        ("范围匹配", "range"),
        ("枚举匹配", "enum"),
        ("表达式匹配", "expression"),
    ]
    TARGET_TYPES = DATA_TYPES

    def __init__(self, field_name="", rules=None, parent=None):
        super().__init__(parent)
        self.field_name = field_name or "参数"
        self.setWindowTitle(f"配置映射 - {self.field_name}")
        self.resize(900, 520)
        self.setMinimumSize(760, 420)
        self._rules = normalize_mapping_groups(rules or [])
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel("映射名相当于函数名；当前参数作为入参，规则按顺序判断并输出目标值。")
        hint.setStyleSheet("color: #607D8B; font-size: 12px;")
        layout.addWidget(hint)

        btn_add = QPushButton("+ 新增映射组")
        btn_add.clicked.connect(lambda: self.add_rule_group())
        layout.addWidget(btn_add, alignment=Qt.AlignLeft)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.rules_widget = QWidget()
        self.rules_layout = QVBoxLayout(self.rules_widget)
        self.rules_layout.setContentsMargins(0, 0, 0, 0)
        self.rules_layout.setSpacing(8)
        self.scroll.setWidget(self.rules_widget)
        layout.addWidget(self.scroll)

        for rule in self._rules:
            self.add_rule_group(rule)
        if self.rules_layout.count() == 0:
            self.add_rule_group()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setStyleSheet("""
            QDialog { background: #F3F6FA; }
            QFrame#mapping_rule_row {
                background: #FFFFFF;
                border: 1px solid #DFE5EC;
                border-radius: 8px;
            }
            QFrame#mapping_group_toolbar {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
            }
            QFrame#mapping_case_row {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
            }
            QLabel#mapping_arrow {
                color: #334155;
                font-size: 14px;
                font-weight: bold;
            }
            QLabel#mapping_param_label {
                color: #0F172A;
                font-size: 12px;
                font-weight: bold;
                padding: 0 2px;
            }
            QLineEdit, QComboBox {
                min-height: 28px;
                background: white;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 3px 8px;
            }
            QPushButton {
                min-height: 28px;
                border-radius: 6px;
                border: 1px solid #CBD5E1;
                background: #FFFFFF;
                padding: 4px 10px;
            }
            QPushButton:hover { background: #F8FAFC; }
        """)

    def _make_source_combo(self, value="exact"):
        combo = QComboBox()
        for label, data in self.SOURCE_MODES:
            combo.addItem(label, data)
        self._set_combo_data(combo, value)
        return combo

    def _make_target_combo(self, value="Array"):
        combo = QComboBox()
        combo.addItems(self.TARGET_TYPES)
        if value in self.TARGET_TYPES:
            combo.setCurrentText(value)
        return combo

    @staticmethod
    def _set_combo_data(combo, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value or combo.itemText(i) == value:
                combo.setCurrentIndex(i)
                return

    @staticmethod
    def _remove_dynamic_row(row):
        if row is None:
            return
        parent = row.parentWidget()
        if parent and parent.layout():
            parent.layout().removeWidget(row)
        row.hide()
        row.deleteLater()

    def add_rule_group(self, rule=None):
        rule = rule or {}
        row = QFrame()
        row.setObjectName("mapping_rule_row")
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        outer = QVBoxLayout(row)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)

        line1 = QHBoxLayout()
        line1.setSpacing(8)
        name_input = QLineEdit(str(rule.get("ruleName", rule.get("rule_name", ""))))
        name_input.setObjectName("rule_name")
        name_input.setPlaceholderText("函数名，如 季度转月份")
        strategy = QComboBox()
        strategy.setObjectName("evaluation_strategy")
        strategy.addItem("首个命中", "first_match")
        strategy.addItem("全部命中", "all_match")
        self._set_combo_data(strategy, rule.get("evaluationStrategy", "first_match"))
        btn_rm = QPushButton("删除")
        btn_rm.clicked.connect(lambda checked=False, r=row: self._remove_dynamic_row(r))
        line1.addWidget(QLabel("函数名:"))
        line1.addWidget(name_input, stretch=1)
        line1.addWidget(QLabel("命中策略:"))
        line1.addWidget(strategy)
        line1.addWidget(btn_rm)
        outer.addLayout(line1)

        toolbar_frame = QFrame()
        toolbar_frame.setObjectName("mapping_group_toolbar")
        toolbar_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        toolbar_frame.setMaximumHeight(42)
        toolbar = QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(8, 4, 8, 4)
        toolbar.setSpacing(6)
        match_mode = self._make_source_combo(rule.get("matchMode", "range"))
        match_mode.setObjectName("group_match_mode")
        match_mode.setFixedHeight(28)
        output_type = self._make_target_combo(rule.get("outputType", "Array"))
        output_type.setObjectName("group_output_type")
        output_type.setFixedHeight(28)
        mapping_strategy = QComboBox()
        mapping_strategy.setObjectName("group_mapping_strategy")
        mapping_strategy.setFixedHeight(28)
        mapping_strategy.addItem("条件命中输出整组目标", "broadcast")
        mapping_strategy.addItem("源与目标逐项配对", "pairwise")
        self._set_combo_data(mapping_strategy, rule.get("mappingStrategy", "broadcast"))
        toolbar.addWidget(QLabel("匹配模式:"))
        toolbar.addWidget(match_mode)
        toolbar.addWidget(QLabel("输出类型:"))
        toolbar.addWidget(output_type)
        toolbar.addWidget(QLabel("映射策略:"))
        toolbar.addWidget(mapping_strategy)
        toolbar.addStretch()
        outer.addWidget(toolbar_frame)

        cases_layout = QVBoxLayout()
        cases_layout.setObjectName("cases_layout")
        cases_layout.setContentsMargins(0, 0, 0, 0)
        cases_layout.setSpacing(5)
        outer.addLayout(cases_layout)

        btn_add_case = QPushButton("+ 新增条件分支")
        btn_add_case.clicked.connect(lambda checked=False, layout=cases_layout: self.add_case_row(layout))
        outer.addWidget(btn_add_case, alignment=Qt.AlignLeft)

        for case in rule.get("cases", []):
            self.add_case_row(cases_layout, case)
        if cases_layout.count() == 0:
            self.add_case_row(cases_layout)

        self.rules_layout.addWidget(row)

    def add_case_row(self, cases_layout, case=None):
        case = case or {}
        row = QFrame()
        row.setObjectName("mapping_case_row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)

        prefix = QLabel(f"▾ {self.field_name} >")
        prefix.setObjectName("mapping_param_label")
        prefix.setMinimumWidth(110)
        source_input = QLineEdit(str(case.get("source", "")))
        source_input.setObjectName("source_expr")
        source_input.setPlaceholderText("条件，如 1-3 或 1,2,3")
        arrow = QLabel("→")
        arrow.setObjectName("mapping_arrow")
        arrow.setAlignment(Qt.AlignCenter)
        target_input = QLineEdit(self._format_cell_value(case.get("target", "")))
        target_input.setObjectName("target_value")
        target_input.setPlaceholderText("目标，如 [1, 2, 3] 或 1-3")
        btn_rm = QPushButton("删除")
        btn_rm.clicked.connect(lambda checked=False, r=row: self._remove_dynamic_row(r))

        layout.addWidget(prefix)
        layout.addWidget(source_input, stretch=2)
        layout.addWidget(arrow)
        layout.addWidget(target_input, stretch=2)
        layout.addWidget(btn_rm)

        cases_layout.addWidget(row)

    @staticmethod
    def _format_cell_value(value):
        if isinstance(value, (dict, list, tuple, bool, int, float)):
            return json.dumps(value, ensure_ascii=False)
        return "" if value is None else str(value)

    def _collect_rules(self):
        rules = []
        for i in range(self.rules_layout.count()):
            row = self.rules_layout.itemAt(i).widget()
            if not row or row.isHidden():
                continue
            rule_name = row.findChild(QLineEdit, "rule_name").text().strip()
            strategy = row.findChild(QComboBox, "evaluation_strategy")
            group_match_mode = row.findChild(QComboBox, "group_match_mode")
            group_output_type = row.findChild(QComboBox, "group_output_type")
            group_mapping_strategy = row.findChild(QComboBox, "group_mapping_strategy")
            cases = []
            cases_layout = row.findChild(QVBoxLayout, "cases_layout")
            if cases_layout is None:
                continue
            for case_index in range(cases_layout.count()):
                case_row = cases_layout.itemAt(case_index).widget()
                if not case_row or case_row.isHidden():
                    continue
                source_expr = case_row.findChild(QLineEdit, "source_expr").text().strip()
                target_value = case_row.findChild(QLineEdit, "target_value").text().strip()
                if not any([source_expr, target_value]):
                    continue
                if not source_expr:
                    raise ValueError(f"第 {i + 1} 个映射组的第 {case_index + 1} 个分支缺少源匹配")
                cases.append({
                    "caseName": f"分支{case_index + 1}",
                    "source": source_expr,
                    "target": target_value,
                })
            if not rule_name and not cases:
                continue
            if not cases:
                raise ValueError(f"第 {i + 1} 个映射组没有有效分支规则")
            rules.append({
                "ruleName": rule_name or f"映射{i + 1}",
                "evaluationStrategy": strategy.currentData() if strategy else "first_match",
                "matchMode": group_match_mode.currentData() if group_match_mode else "range",
                "outputType": group_output_type.currentText().strip() if group_output_type else "Array",
                "mappingStrategy": group_mapping_strategy.currentData() if group_mapping_strategy else "broadcast",
                "cases": cases,
            })
        return rules

    def _accept_checked(self):
        try:
            self._rules = self._collect_rules()
        except Exception as exc:
            QMessageBox.warning(self, "映射配置错误", str(exc))
            return
        self.accept()

    def get_rules(self):
        return [dict(rule) for rule in self._rules]


class AdvancedParamMappingPanel(BaseToolPanel):
    use_df = False
    use_type = False
    use_out = False
    theme_color = "#455A64"
    action_name = "参数输入"
    DATA_TYPES = DATA_TYPES

    def init_custom_ui(self):
        card, inner = self._make_card("参数输入")
        self.custom_layout.addWidget(card)

        self.param_rows = QVBoxLayout()
        self.param_rows.setSpacing(8)
        inner.addLayout(self.param_rows)
        self.add_parameter_row()

        btn_add = self._make_add_button("+ 添加输入参数")
        btn_add.clicked.connect(lambda: self.add_parameter_row())
        inner.addWidget(btn_add)

    def add_parameter_row(self, name="", data_type="String", value="", rules=None):
        row = QFrame()
        row.setObjectName("param_input_row")
        row._mapping_rules = [dict(rule) for rule in (rules or []) if isinstance(rule, dict)]
        row.setStyleSheet("""
            QFrame#param_input_row {
                background: #FFFFFF;
                border: 1px solid #E3EAF2;
                border-radius: 8px;
            }
            QLabel#param_field_label {
                color: #64748B;
                font-size: 11px;
                border: none;
            }
            QPushButton#mapping_button {
                background: #EEF2F6;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                color: #374151;
                padding: 4px 10px;
            }
            QPushButton#mapping_button:hover {
                background: #E2E8F0;
                border-color: #94A3B8;
            }
            QPushButton#param_delete_button {
                background: #FFF5F5;
                border: 1px solid #FED7D7;
                border-radius: 6px;
                color: #C53030;
                padding: 4px 10px;
            }
            QPushButton#param_delete_button:hover {
                background: #FFE4E6;
                border-color: #FDA4AF;
            }
        """)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)

        field_line = QHBoxLayout()
        field_line.setContentsMargins(0, 0, 0, 0)
        field_line.setSpacing(8)

        name_input = QLineEdit(str(name))
        name_input.setObjectName("field_name")
        name_input.setPlaceholderText("如 report_month")
        # 这是参数源头定义，不允许再引用其他参数，避免形成隐式依赖链。
        if hasattr(name_input, "set_parameter_enabled"):
            name_input.set_parameter_enabled(False)

        type_combo = QComboBox()
        type_combo.setObjectName("data_type")
        type_combo.addItems(self.DATA_TYPES)
        type_combo.setMinimumWidth(86)
        type_combo.setMaximumWidth(112)
        if data_type in self.DATA_TYPES:
            type_combo.setCurrentText(data_type)

        value_input = QLineEdit(str(value))
        value_input.setObjectName("input_value")
        value_input.setPlaceholderText("如 1-3 / [1,2,3] / true")
        # Input 同样是运行参数原始输入，不展示“引入参数”按钮。
        if hasattr(value_input, "set_parameter_enabled"):
            value_input.set_parameter_enabled(False)

        def make_field(label_text, widget):
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(3)
            label = QLabel(label_text)
            label.setObjectName("param_field_label")
            box_layout.addWidget(label)
            box_layout.addWidget(widget)
            return box

        btn_mapping = QPushButton()
        btn_mapping.setObjectName("mapping_button")
        btn_mapping.setFixedWidth(96)
        btn_mapping.setFixedHeight(28)
        btn_mapping.clicked.connect(lambda checked=False, r=row: self.open_mapping_dialog(r))
        btn_delete = QPushButton("删除")
        btn_delete.setObjectName("param_delete_button")
        btn_delete.setFixedWidth(58)
        btn_delete.setFixedHeight(28)
        btn_delete.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))

        field_line.addWidget(make_field("命名", name_input), stretch=2)
        field_line.addWidget(make_field("类型", type_combo))
        field_line.addWidget(make_field("输入", value_input), stretch=2)
        layout.addLayout(field_line)

        action_line = QHBoxLayout()
        action_line.setContentsMargins(0, 0, 0, 0)
        action_line.setSpacing(6)
        action_line.addStretch(1)
        action_line.addWidget(btn_mapping)
        action_line.addWidget(btn_delete)
        layout.addLayout(action_line)

        self.param_rows.addWidget(row)
        self._attach_parameter_action(name_input)
        self._attach_parameter_action(value_input)
        self._update_mapping_button(row)

    def _update_mapping_button(self, row):
        btn = row.findChild(QPushButton, "mapping_button")
        if not btn:
            return
        count = len(getattr(row, "_mapping_rules", []))
        case_count = sum(len(rule.get("cases", [])) for rule in getattr(row, "_mapping_rules", []))
        if count and case_count:
            btn.setText(f"映射 {count}/{case_count}")
        else:
            btn.setText("映射")

    def open_mapping_dialog(self, row):
        name_input = row.findChild(QLineEdit, "field_name")
        field_name = name_input.text().strip() if name_input else ""
        dlg = AdvancedMappingDialog(field_name, getattr(row, "_mapping_rules", []), self)
        if dlg.exec_() == QDialog.Accepted:
            row._mapping_rules = dlg.get_rules()
            self._update_mapping_button(row)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.param_rows)
        self.add_parameter_row()

    def _collect_parameter_rows(self):
        ui_rows = []
        for i in range(self.param_rows.count()):
            row = self.param_rows.itemAt(i).widget()
            if not row or row.isHidden():
                continue
            name_input = row.findChild(QLineEdit, "field_name")
            type_combo = row.findChild(QComboBox, "data_type")
            value_input = row.findChild(QLineEdit, "input_value")
            ui_rows.append({
                "fieldName": name_input.text().strip() if name_input else "",
                "dataType": type_combo.currentText().strip() if type_combo else "String",
                "input": value_input.text().strip() if value_input else "",
                "rules": [dict(rule) for rule in getattr(row, "_mapping_rules", [])],
            })
        return coerce_parameter_rows(ui_rows)

    def get_custom_params(self):
        rows = self._collect_parameter_rows()
        config = build_rule_engine_config(rows)
        runtime_payload = config["runtime_payload"]
        return {
            "advanced_parameters": rows,
            "parameters": runtime_payload["raw_parameters"],
            "typed_parameters": runtime_payload["runtime_parameters"],
            "parameter_mappings": runtime_payload["parameter_mappings"],
            "rule_engine_config": config,
        }

    def set_custom_params(self, p):
        rows = p.get("advanced_parameters")
        if not rows and p.get("rule_engine_config"):
            rows = []
            config = p.get("rule_engine_config", {})
            rules_by_field = {}
            for rule in config.get("rules", []):
                field_name = rule.get("fieldName", "")
                if not field_name:
                    continue
                cases = []
                for case in rule.get("cases", []):
                    cases.append({
                        "caseName": case.get("caseName", ""),
                        "matchMode": case.get("sourceSelector", {}).get("matchMode", "exact"),
                        "source": case.get("sourceSelector", {}).get("expression", ""),
                        "outputType": case.get("targetTransformer", {}).get("outputType", "String"),
                        "target": case.get("targetTransformer", {}).get("value", ""),
                    })
                rules_by_field.setdefault(field_name, []).append({
                    "ruleName": rule.get("ruleName", ""),
                    "evaluationStrategy": rule.get("evaluationStrategy", "first_match"),
                    "matchMode": rule.get("matchMode", cases[0].get("matchMode", "range") if cases else "range"),
                    "outputType": rule.get("outputType", cases[0].get("outputType", "Array") if cases else "Array"),
                    "mappingStrategy": rule.get("mappingStrategy", cases[0].get("mappingStrategy", "broadcast") if cases else "broadcast"),
                    "cases": cases,
                })
            for param in config.get("parameters", []):
                field_name = param.get("fieldName", "")
                rows.append({
                    "fieldName": field_name,
                    "dataType": param.get("dataType", "String"),
                    "input": param.get("input", ""),
                    "rules": rules_by_field.get(field_name, []),
                })
        if not rows:
            return
        self.clear_dynamic_layout(self.param_rows)
        for param in rows:
            self.add_parameter_row(
                param.get("fieldName", ""),
                param.get("dataType", "String"),
                param.get("input", format_advanced_value(param.get("value", ""))),
                param.get("rules", []),
            )

    def _validate(self):
        try:
            self.get_custom_params()
        except Exception as exc:
            QMessageBox.warning(self, "参数配置错误", str(exc))
            return False, None
        return True, None

    def execute(self):
        try:
            p = self.get_params()
        except Exception as exc:
            return QMessageBox.warning(self, "参数配置错误", str(exc))
        rows = []
        for param in p.get("rule_engine_config", {}).get("parameters", []):
            rows.append({
                "类型": "输入参数",
                "名称": param.get("fieldName", ""),
                "数据类型": param.get("dataType", ""),
                "输入": param.get("input", ""),
                "解析值": format_advanced_value(param.get("value", "")),
            })
        for rule in p.get("rule_engine_config", {}).get("rules", []):
            for case in rule.get("cases", []):
                rows.append({
                    "类型": "映射分支",
                    "名称": f"{rule.get('ruleName', '')} / {case.get('caseName', '')}",
                    "数据类型": case.get("targetTransformer", {}).get("outputType", ""),
                    "输入": case.get("sourceSelector", {}).get("expression", ""),
                    "解析值": format_advanced_value(case.get("targetTransformer", {}).get("resolvedValue", "")),
                })
        df = pd.DataFrame(rows)
        self.step_recorded.emit("advanced_param_mapping", p, df, "参数输入")
