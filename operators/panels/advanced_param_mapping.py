"""Advanced parameter mapping operator panel."""

import json
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
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
    MAPPING_OUTPUT_TYPES,
    build_rule_engine_config,
    coerce_parameter_rows,
    format_advanced_value,
    format_file_filters,
    normalize_mapping_groups,
    normalize_file_filters,
)
from operators.base_panel import BaseToolPanel, QLineEdit


class AdvancedMappingDialog(QDialog):
    SOURCE_MODES = [
        ("精确匹配", "exact"),
        ("范围匹配", "range"),
        ("枚举匹配", "enum"),
        ("表达式匹配", "expression"),
    ]
    TARGET_TYPES = MAPPING_OUTPUT_TYPES

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
    FILE_FILTER_PRESETS = [
        ("所有文件", ["*.*"]),
        ("Excel", ["*.xlsx", "*.xls", "*.xlsm"]),
        ("PDF", ["*.pdf"]),
        ("CSV", ["*.csv"]),
        ("Word", ["*.docx", "*.doc"]),
        ("图片", ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif"]),
        ("自定义", None),
    ]

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

    @staticmethod
    def _parameter_file_dialog_filter(filters):
        joined = " ".join(normalize_file_filters(filters))
        return f"可选文件 ({joined});;所有文件 (*.*)"

    @staticmethod
    def _start_dir_from_text(text):
        path = Path(str(text or "").strip())
        if path.is_dir():
            return str(path)
        if str(path) and path.parent and str(path.parent) != ".":
            return str(path.parent)
        return ""

    def _browse_parameter_path(self, row):
        type_combo = row.findChild(QComboBox, "data_type")
        value_input = row.findChild(QLineEdit, "input_value")
        filters_input = row.findChild(QLineEdit, "file_filters")
        if not type_combo or not value_input:
            return
        data_type = type_combo.currentText().strip()
        current = value_input.text().strip()
        if data_type == "Folder":
            path = QFileDialog.getExistingDirectory(self, "选择文件夹", current or self._start_dir_from_text(current))
        else:
            filter_text = self._parameter_file_dialog_filter(filters_input.text() if filters_input else "")
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择文件",
                self._start_dir_from_text(current),
                filter_text,
            )
        if path:
            value_input.setText(path)

    def _update_path_controls(self, row):
        type_combo = row.findChild(QComboBox, "data_type")
        value_input = row.findChild(QLineEdit, "input_value")
        browse_button = row.findChild(QPushButton, "path_browse_button")
        filters_box = row.findChild(QWidget, "file_filters_box")
        preset_combo = row.findChild(QComboBox, "file_filter_preset")
        data_type = type_combo.currentText().strip() if type_combo else "String"
        is_file = data_type == "File"
        is_folder = data_type == "Folder"
        if value_input:
            if is_file:
                value_input.setPlaceholderText("选择或输入文件路径")
            elif is_folder:
                value_input.setPlaceholderText("选择或输入文件夹路径")
            else:
                value_input.setPlaceholderText("如 1-3 / [1,2,3] / true")
        if browse_button:
            browse_button.setVisible(is_file or is_folder)
            browse_button.setText("选文件夹" if is_folder else "选文件")
        if filters_box:
            filters_box.setVisible(is_file)
        if preset_combo:
            preset_combo.setVisible(is_file)

    def _set_file_filter_preset(self, combo, filters):
        normalized = normalize_file_filters(filters)
        combo.blockSignals(True)
        for i in range(combo.count()):
            preset = combo.itemData(i)
            if preset is not None and normalize_file_filters(preset) == normalized:
                combo.setCurrentIndex(i)
                combo.blockSignals(False)
                return
        combo.setCurrentText("自定义")
        combo.blockSignals(False)

    def _on_filter_preset_changed(self, row):
        preset_combo = row.findChild(QComboBox, "file_filter_preset")
        filters_input = row.findChild(QLineEdit, "file_filters")
        if not preset_combo or not filters_input:
            return
        filters = preset_combo.currentData()
        if filters is not None:
            filters_input.setText(format_file_filters(filters))

    def _mark_custom_filter_preset(self, row):
        preset_combo = row.findChild(QComboBox, "file_filter_preset")
        if not preset_combo:
            return
        index = preset_combo.findText("自定义")
        if index >= 0:
            preset_combo.blockSignals(True)
            preset_combo.setCurrentIndex(index)
            preset_combo.blockSignals(False)

    def add_parameter_row(self, name="", data_type="String", value="", rules=None, filters=None):
        row = QFrame()
        row.setObjectName("param_input_row")
        row._mapping_rules = [dict(rule) for rule in (rules or []) if isinstance(rule, dict)]
        row.setStyleSheet("""
            QFrame#param_input_row {
                background: #F8FAFC;
                border: 1px solid #D9E2EC;
                border-radius: 8px;
            }
            QFrame#param_input_row:hover {
                border-color: #B6C5D4;
            }
            QLabel#param_row_title {
                color: #0F172A;
                font-size: 12px;
                font-weight: bold;
                border: none;
            }
            QLabel#mapping_summary {
                color: #64748B;
                font-size: 11px;
                border: none;
            }
            QLabel#param_field_label {
                color: #64748B;
                font-size: 11px;
                border: none;
            }
            QWidget#param_field_box {
                background: transparent;
                border: none;
            }
            QFrame#file_filters_box {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 7px;
            }
            QLineEdit, QComboBox {
                min-height: 30px;
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 4px 8px;
                color: #0F172A;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #607D8B;
                background: #FFFFFF;
            }
            QPushButton#mapping_button {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                color: #334155;
                padding: 4px 10px;
            }
            QPushButton#mapping_button:hover {
                background: #EEF2F6;
                border-color: #94A3B8;
            }
            QPushButton#param_delete_button {
                background: #FFF7F7;
                border: 1px solid #FED7D7;
                border-radius: 6px;
                color: #C53030;
                padding: 4px 10px;
            }
            QPushButton#param_delete_button:hover {
                background: #FFE4E6;
                border-color: #FDA4AF;
            }
            QPushButton#path_browse_button {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                color: #334155;
                padding: 4px 8px;
            }
            QPushButton#path_browse_button:hover {
                background: #EEF2F7;
                border-color: #94A3B8;
            }
        """)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(10, 9, 10, 10)
        layout.setSpacing(9)

        header_line = QHBoxLayout()
        header_line.setContentsMargins(0, 0, 0, 0)
        header_line.setSpacing(8)
        title = QLabel("输入参数")
        title.setObjectName("param_row_title")
        summary = QLabel("未配置映射")
        summary.setObjectName("mapping_summary")
        header_line.addWidget(title)
        header_line.addWidget(summary, stretch=1)

        name_input = QLineEdit(str(name))
        name_input.setObjectName("field_name")
        name_input.setPlaceholderText("如 report_month")
        # 这是参数源头定义，不允许再引用其他参数，避免形成隐式依赖链。
        if hasattr(name_input, "set_parameter_enabled"):
            name_input.set_parameter_enabled(False)

        type_combo = QComboBox()
        type_combo.setObjectName("data_type")
        type_combo.addItems(self.DATA_TYPES)
        type_combo.setFixedWidth(112)
        if data_type in self.DATA_TYPES:
            type_combo.setCurrentText(data_type)

        value_input = QLineEdit(str(value))
        value_input.setObjectName("input_value")
        value_input.setPlaceholderText("如 1-3 / [1,2,3] / true")
        # Input 同样是运行参数原始输入，不展示“引入参数”按钮。
        if hasattr(value_input, "set_parameter_enabled"):
            value_input.set_parameter_enabled(False)

        btn_browse = QPushButton("选文件")
        btn_browse.setObjectName("path_browse_button")
        btn_browse.setFixedWidth(96)
        btn_browse.setFixedHeight(30)
        btn_browse.clicked.connect(lambda checked=False, r=row: self._browse_parameter_path(r))

        value_box = QWidget()
        value_layout = QHBoxLayout(value_box)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(6)
        value_layout.addWidget(value_input, stretch=1)
        value_layout.addWidget(btn_browse)

        filters_input = QLineEdit(format_file_filters(filters))
        filters_input.setObjectName("file_filters")
        filters_input.setPlaceholderText("如 *.xlsx, *.pdf")
        if hasattr(filters_input, "set_parameter_enabled"):
            filters_input.set_parameter_enabled(False)

        preset_combo = QComboBox()
        preset_combo.setObjectName("file_filter_preset")
        for label, preset in self.FILE_FILTER_PRESETS:
            preset_combo.addItem(label, preset)
        preset_combo.setFixedWidth(118)
        self._set_file_filter_preset(preset_combo, filters_input.text())

        def make_field(label_text, widget):
            box = QWidget()
            box.setObjectName("param_field_box")
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
        btn_mapping.setFixedWidth(82)
        btn_mapping.setFixedHeight(28)
        btn_mapping.clicked.connect(lambda checked=False, r=row: self.open_mapping_dialog(r))
        btn_delete = QPushButton("删除")
        btn_delete.setObjectName("param_delete_button")
        btn_delete.setFixedWidth(58)
        btn_delete.setFixedHeight(28)
        btn_delete.clicked.connect(lambda checked=False, r=row: self.remove_dynamic_row(r))
        header_line.addWidget(btn_mapping)
        header_line.addWidget(btn_delete)
        layout.addLayout(header_line)

        field_line = QHBoxLayout()
        field_line.setContentsMargins(0, 0, 0, 0)
        field_line.setSpacing(8)
        field_line.addWidget(make_field("命名", name_input), stretch=1)
        field_line.addWidget(make_field("类型", type_combo), stretch=0)
        layout.addLayout(field_line)

        value_line = QHBoxLayout()
        value_line.setContentsMargins(0, 0, 0, 0)
        value_line.setSpacing(8)
        value_line.addWidget(make_field("默认输入", value_box), stretch=1)
        layout.addLayout(value_line)

        filters_box = QFrame()
        filters_box.setObjectName("file_filters_box")
        filters_layout = QHBoxLayout(filters_box)
        filters_layout.setContentsMargins(8, 7, 8, 8)
        filters_layout.setSpacing(8)
        filters_layout.addWidget(make_field("文件类型", preset_combo), stretch=0)
        filters_layout.addWidget(make_field("过滤器", filters_input), stretch=1)
        layout.addWidget(filters_box)
        type_combo.currentTextChanged.connect(lambda _text, r=row: self._update_path_controls(r))
        preset_combo.currentIndexChanged.connect(lambda _index, r=row: self._on_filter_preset_changed(r))
        filters_input.textEdited.connect(lambda _text, r=row: self._mark_custom_filter_preset(r))

        self.param_rows.addWidget(row)
        self._attach_parameter_action(name_input)
        self._attach_parameter_action(value_input)
        self._attach_parameter_action(filters_input)
        self._update_path_controls(row)
        self._update_mapping_button(row)
        self._refresh_parameter_titles()

    def _update_mapping_button(self, row):
        btn = row.findChild(QPushButton, "mapping_button")
        summary = row.findChild(QLabel, "mapping_summary")
        if not btn and not summary:
            return
        count = len(getattr(row, "_mapping_rules", []))
        case_count = sum(len(rule.get("cases", [])) for rule in getattr(row, "_mapping_rules", []))
        if count and case_count:
            if btn:
                btn.setText("映射")
            if summary:
                summary.setText(f"已配置 {count} 组 / {case_count} 条")
        else:
            if btn:
                btn.setText("映射")
            if summary:
                summary.setText("未配置映射")

    def _refresh_parameter_titles(self):
        visible_index = 1
        for i in range(self.param_rows.count()):
            row = self.param_rows.itemAt(i).widget()
            if not row or row.isHidden():
                continue
            title = row.findChild(QLabel, "param_row_title")
            if title:
                title.setText(f"参数 {visible_index}")
            visible_index += 1

    def remove_dynamic_row(self, row):
        super().remove_dynamic_row(row)
        self._refresh_parameter_titles()

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
            filters_input = row.findChild(QLineEdit, "file_filters")
            item = {
                "fieldName": name_input.text().strip() if name_input else "",
                "dataType": type_combo.currentText().strip() if type_combo else "String",
                "input": value_input.text().strip() if value_input else "",
                "rules": [dict(rule) for rule in getattr(row, "_mapping_rules", [])],
            }
            if item["dataType"] == "File":
                item["filters"] = normalize_file_filters(filters_input.text() if filters_input else "")
            ui_rows.append(item)
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
                    "filters": param.get("filters"),
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
                param.get("filters"),
            )

    def _validate(self):
        try:
            self.get_custom_params()
        except Exception as exc:
            QMessageBox.warning(self, "参数配置错误", str(exc))
            return False, None
        return True, None
