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
        title_name = field_name or "未命名参数"
        self.setWindowTitle(f"配置映射 - {title_name}")
        self.resize(900, 560)
        self.setMinimumSize(820, 460)
        self._rules = normalize_mapping_groups(rules or [])
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel("源参数固定为当前输入；映射组统一设置匹配模式和输出类型，分支只维护条件与目标值。")
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
                background: #F8FAFC;
                border: none;
                border-bottom: 1px solid #E2E8F0;
                border-radius: 0px;
            }
            QLabel#case_header {
                color: #64748B;
                font-size: 11px;
                font-weight: bold;
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

    def add_rule_group(self, rule=None):
        rule = rule or {}
        row = QFrame()
        row.setObjectName("mapping_rule_row")
        outer = QVBoxLayout(row)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        line1 = QHBoxLayout()
        line1.setSpacing(8)
        name_input = QLineEdit(str(rule.get("ruleName", rule.get("rule_name", ""))))
        name_input.setObjectName("rule_name")
        name_input.setPlaceholderText("规则命名，如 季度转月份")
        strategy = QComboBox()
        strategy.setObjectName("evaluation_strategy")
        strategy.addItem("首个命中", "first_match")
        strategy.addItem("全部命中", "all_match")
        self._set_combo_data(strategy, rule.get("evaluationStrategy", "first_match"))
        btn_rm = QPushButton("删除")
        btn_rm.clicked.connect(row.deleteLater)
        line1.addWidget(QLabel("映射命名:"))
        line1.addWidget(name_input, stretch=1)
        line1.addWidget(QLabel("命中策略:"))
        line1.addWidget(strategy)
        line1.addWidget(btn_rm)
        outer.addLayout(line1)

        toolbar_frame = QFrame()
        toolbar_frame.setObjectName("mapping_group_toolbar")
        toolbar = QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(10, 8, 10, 8)
        toolbar.setSpacing(8)
        match_mode = self._make_source_combo(rule.get("matchMode", "range"))
        match_mode.setObjectName("group_match_mode")
        output_type = self._make_target_combo(rule.get("outputType", "Array"))
        output_type.setObjectName("group_output_type")
        mapping_strategy = QComboBox()
        mapping_strategy.setObjectName("group_mapping_strategy")
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

        header = QHBoxLayout()
        header.setContentsMargins(8, 2, 8, 0)
        header.setSpacing(8)
        for text, stretch in [("分支", 1), ("条件", 2), ("目标", 2), ("", 0)]:
            label = QLabel(text)
            label.setObjectName("case_header")
            if stretch:
                header.addWidget(label, stretch=stretch)
            else:
                header.addWidget(label)
        outer.addLayout(header)

        cases_layout = QVBoxLayout()
        cases_layout.setObjectName("cases_layout")
        cases_layout.setContentsMargins(0, 0, 0, 0)
        cases_layout.setSpacing(6)
        outer.addLayout(cases_layout)

        btn_add_case = QPushButton("+ 新增分支规则")
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
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        case_name = QLineEdit(str(case.get("caseName", "")))
        case_name.setObjectName("case_name")
        case_name.setPlaceholderText("分支名，如 1-3月")
        source_input = QLineEdit(str(case.get("source", "")))
        source_input.setObjectName("source_expr")
        source_input.setPlaceholderText("如 1-3 或 1,2,3")
        target_input = QLineEdit(self._format_cell_value(case.get("target", "")))
        target_input.setObjectName("target_value")
        target_input.setPlaceholderText("如 [1, 2, 3] 或 1-3")
        btn_rm = QPushButton("删除")
        btn_rm.clicked.connect(row.deleteLater)

        layout.addWidget(case_name, stretch=1)
        layout.addWidget(source_input, stretch=2)
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
            if not row:
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
                if not case_row:
                    continue
                case_name = case_row.findChild(QLineEdit, "case_name").text().strip()
                source_expr = case_row.findChild(QLineEdit, "source_expr").text().strip()
                target_value = case_row.findChild(QLineEdit, "target_value").text().strip()
                if not any([case_name, source_expr, target_value]):
                    continue
                if not source_expr:
                    raise ValueError(f"第 {i + 1} 个映射组的第 {case_index + 1} 个分支缺少源匹配")
                cases.append({
                    "caseName": case_name or f"分支{case_index + 1}",
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
    action_name = "参数高级映射"
    DATA_TYPES = DATA_TYPES

    def init_custom_ui(self):
        card, inner = self._make_card("输入参数与映射规则")
        self.custom_layout.addWidget(card)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        btn_add = QPushButton("+ 新增输入")
        btn_add.setFixedHeight(32)
        btn_add.setStyleSheet(
            "QPushButton { background: #F8FAFC; border: 1px solid #CBD5E1; "
            "border-radius: 6px; padding: 4px 12px; color: #263238; }"
            "QPushButton:hover { background: #EEF2F6; }"
        )
        btn_add.clicked.connect(lambda: self.add_parameter_row())
        top.addStretch(1)
        top.addWidget(btn_add)
        inner.addLayout(top)

        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 0)
        for text, stretch in [("命名", 2), ("类型", 1), ("输入", 2), ("映射", 1)]:
            label = QLabel(text)
            label.setStyleSheet("color: #455A64; font-size: 11px; font-weight: bold; border: none;")
            header.addWidget(label, stretch=stretch)
        inner.addLayout(header)

        self.param_rows = QVBoxLayout()
        self.param_rows.setSpacing(6)
        inner.addLayout(self.param_rows)
        self.add_parameter_row()

    def add_parameter_row(self, name="", data_type="String", value="", rules=None):
        row = QWidget()
        row._mapping_rules = [dict(rule) for rule in (rules or []) if isinstance(rule, dict)]
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        name_input = QLineEdit(str(name))
        name_input.setObjectName("field_name")
        name_input.setPlaceholderText("如 report_month")
        # 这是参数源头定义，不允许再引用其他参数，避免形成隐式依赖链。
        if hasattr(name_input, "set_parameter_enabled"):
            name_input.set_parameter_enabled(False)

        type_combo = QComboBox()
        type_combo.setObjectName("data_type")
        type_combo.addItems(self.DATA_TYPES)
        type_combo.setMinimumWidth(92)
        if data_type in self.DATA_TYPES:
            type_combo.setCurrentText(data_type)

        value_input = QLineEdit(str(value))
        value_input.setObjectName("input_value")
        value_input.setPlaceholderText("如 1-3 / [1,2,3] / true")
        # Input 同样是运行参数原始输入，不展示“引入参数”按钮。
        if hasattr(value_input, "set_parameter_enabled"):
            value_input.set_parameter_enabled(False)

        btn_mapping = QPushButton()
        btn_mapping.setObjectName("mapping_button")
        btn_mapping.setFixedWidth(72)
        btn_mapping.clicked.connect(lambda checked=False, r=row: self.open_mapping_dialog(r))
        btn_delete = QPushButton("删")
        btn_delete.setFixedWidth(44)
        btn_delete.clicked.connect(row.deleteLater)

        layout.addWidget(name_input, stretch=2)
        layout.addWidget(type_combo, stretch=1)
        layout.addWidget(value_input, stretch=2)
        layout.addWidget(btn_mapping)
        layout.addWidget(btn_delete)

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
            if not row:
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
        return {
            "advanced_parameters": rows,
            "parameters": config["compatibility"]["raw_parameters"],
            "typed_parameters": config["compatibility"]["runtime_parameters"],
            "parameter_mappings": config["compatibility"]["parameter_mappings"],
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
                # 兼容旧版扁平 rule_engine_config。
                if not cases and rule.get("sourceSelector"):
                    cases.append({
                        "caseName": rule.get("ruleName", ""),
                        "matchMode": rule.get("sourceSelector", {}).get("matchMode", "exact"),
                        "source": rule.get("sourceSelector", {}).get("expression", ""),
                        "outputType": rule.get("targetTransformer", {}).get("outputType", "String"),
                        "target": rule.get("targetTransformer", {}).get("value", ""),
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
        self.step_recorded.emit("advanced_param_mapping", p, df, "参数高级映射")
