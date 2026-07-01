"""PyQt launcher that builds a runtime form from workflow JSON."""

import json
import os
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from engine import WorkflowEngine
from crpa_launcher.manifest_runtime import (
    build_crpa_payload,
    build_runtime_workflow,
    collect_file_contexts,
    file_dialog_filter,
    load_excel_sheet_names,
    load_workflow_json,
    save_workflow_json,
)
from crpa_launcher.settings import set_last_workflow_path


class CrpaLauncher(QWidget):
    def __init__(self):
        super().__init__()
        self.workflow_path = ""
        self.workflow = None
        self.file_inputs = {}
        self.sheet_combos = {}
        self.param_inputs = {}
        self.sheet_sources = []
        self.advanced_sheet_card = None
        self.advanced_sheet_body = None
        self.advanced_sheet_toggle = None
        self.sheet_status_label = None
        self.engine = None
        self.setWindowTitle("CRPA JSON 运行器")
        self.resize(1120, 760)
        self.setMinimumSize(900, 620)
        self._init_ui()

    def _init_ui(self):
        self._apply_styles()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self._build_header(root)

        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.setChildrenCollapsible(False)
        root.addWidget(self.main_splitter, stretch=1)

        work_area = QWidget()
        work_layout = QHBoxLayout(work_area)
        work_layout.setContentsMargins(0, 0, 0, 0)
        work_layout.setSpacing(10)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setObjectName("formScroll")
        self.form_container = QWidget()
        self.form_container.setObjectName("formContainer")
        self.form_layout = QVBoxLayout(self.form_container)
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_layout.setSpacing(10)
        self.scroll.setWidget(self.form_container)
        work_layout.addWidget(self.scroll, stretch=1)

        work_layout.addWidget(self._build_run_panel())

        self.main_splitter.addWidget(work_area)
        self.main_splitter.addWidget(self._build_log_card())
        self.main_splitter.setSizes([470, 250])

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QWidget {
                color: #1F2937;
                font-size: 13px;
                background: #EEF2F5;
            }
            QWidget#formContainer,
            QWidget#pairRow {
                background: transparent;
            }
            QWidget#advancedBody {
                background: transparent;
            }
            QFrame#headerCard,
            QFrame#sectionCard,
            QFrame#runPanel,
            QFrame#logCard {
                background: #FFFFFF;
                border: 1px solid #D8E0E8;
                border-radius: 8px;
            }
            QFrame#metricFile {
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
                border-radius: 6px;
            }
            QFrame#metricSheet {
                background: #FFF7ED;
                border: 1px solid #FED7AA;
                border-radius: 6px;
            }
            QFrame#metricParam {
                background: #F0FDF4;
                border: 1px solid #BBF7D0;
                border-radius: 6px;
            }
            QLabel#pageTitle {
                font-size: 20px;
                font-weight: 700;
                color: #111827;
                background: transparent;
            }
            QLabel#badge {
                color: #14532D;
                background: #DCFCE7;
                border: 1px solid #BBF7D0;
                border-radius: 5px;
                padding: 3px 9px;
                font-weight: 600;
            }
            QLabel#sectionTitle,
            QLabel#sideTitle,
            QLabel#logTitle {
                color: #111827;
                background: transparent;
                font-weight: 700;
                font-size: 14px;
            }
            QLabel#formChip {
                color: #334155;
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 5px;
                padding: 3px 9px;
                font-weight: 700;
                font-size: 13px;
            }
            QLabel#statusLabel {
                color: #475569;
                background: transparent;
            }
            QLabel#sheetStatusOk {
                color: #166534;
                background: transparent;
            }
            QLabel#sheetStatusWarn {
                color: #B45309;
                background: transparent;
                font-weight: 600;
            }
            QLabel#fieldCaption,
            QLabel#metricLabel {
                color: #64748B;
                background: transparent;
                font-weight: 600;
            }
            QLabel#metricValue {
                color: #111827;
                background: transparent;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#metricFileValue {
                color: #1D4ED8;
                background: transparent;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#metricSheetValue {
                color: #C2410C;
                background: transparent;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#metricParamValue {
                color: #15803D;
                background: transparent;
                font-size: 18px;
                font-weight: 700;
            }
            QLineEdit,
            QComboBox {
                min-height: 30px;
                background: #FFFFFF;
                border: 1px solid #C9D3DD;
                border-radius: 5px;
                padding: 3px 8px;
                selection-background-color: #2563EB;
            }
            QLineEdit:focus,
            QComboBox:focus {
                border: 1px solid #2563EB;
            }
            QPushButton {
                min-height: 30px;
                background: #F8FAFC;
                border: 1px solid #C9D3DD;
                border-radius: 5px;
                padding: 0 14px;
                color: #1F2937;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #EEF2FF;
                border-color: #9DB4D6;
            }
            QPushButton#primaryRunButton {
                min-height: 38px;
                background: #2E7D32;
                color: white;
                border: 1px solid #27672B;
                padding: 0 22px;
                font-weight: 700;
            }
            QPushButton#primaryRunButton:hover {
                background: #256D2A;
            }
            QPushButton#primaryRunButton:disabled {
                background: #9CA3AF;
                border-color: #9CA3AF;
                color: #F3F4F6;
            }
            QToolButton#advancedToggle {
                background: transparent;
                border: none;
                color: #2563EB;
                font-weight: 700;
                padding: 0;
            }
            QCheckBox {
                background: transparent;
                color: #334155;
            }
            QProgressBar {
                height: 14px;
                border: 1px solid #C9D3DD;
                border-radius: 4px;
                background: #E5EAF0;
                text-align: center;
                color: #334155;
                font-size: 11px;
            }
            QProgressBar::chunk {
                border-radius: 3px;
                background: #2563EB;
            }
            QTextEdit#logOutput {
                background: #111827;
                color: #D1D5DB;
                border: 1px solid #111827;
                border-radius: 6px;
                font-family: Consolas, "Courier New";
                font-size: 12px;
                padding: 8px;
            }
            QScrollArea#formScroll {
                background: transparent;
                border: none;
            }
            """
        )

    def _build_header(self, root):
        header = QFrame()
        header.setObjectName("headerCard")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(10)

        self.workflow_name_label = QLabel("未加载 JSON")
        self.workflow_name_label.setObjectName("pageTitle")
        self.workflow_name_label.setMinimumWidth(180)
        self.crpa_label = QLabel("CRPA: 未填写")
        self.crpa_label.setObjectName("badge")

        json_label = QLabel("JSON")
        json_label.setObjectName("formChip")
        self.json_path_input = QLineEdit()
        self.json_path_input.setPlaceholderText("选择工作流 JSON")
        btn_browse = QPushButton("选择 JSON")
        btn_browse.setFixedWidth(96)
        btn_browse.clicked.connect(self.browse_json)

        header_layout.addWidget(self.workflow_name_label)
        header_layout.addWidget(self.crpa_label)
        header_layout.addSpacing(10)
        header_layout.addWidget(json_label)
        header_layout.addWidget(self.json_path_input, stretch=1)
        header_layout.addWidget(btn_browse)

        root.addWidget(header)

    def _build_run_panel(self):
        panel = QFrame()
        panel.setObjectName("runPanel")
        panel.setFixedWidth(300)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(12)

        title = QLabel("运行准备")
        title.setObjectName("sideTitle")
        layout.addWidget(title)

        self.status_label = QLabel("等待加载 JSON")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(8)
        self.file_count_label = self._make_metric("0", "文件", "File")
        self.sheet_count_label = self._make_metric("0", "Sheet", "Sheet")
        self.param_count_label = self._make_metric("0", "参数", "Param")
        stats_row.addWidget(self.file_count_label)
        stats_row.addWidget(self.sheet_count_label)
        stats_row.addWidget(self.param_count_label)
        layout.addLayout(stats_row)

        self.writeback_check = QCheckBox("运行前写回 JSON")
        self.writeback_check.setChecked(True)
        layout.addWidget(self.writeback_check)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        layout.addWidget(self.progress)

        layout.addStretch(1)

        self.btn_run = QPushButton("运行工作流")
        self.btn_run.setObjectName("primaryRunButton")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self.run_workflow)
        layout.addWidget(self.btn_run)

        return panel

    def _make_metric(self, value, label, variant):
        box = QFrame()
        box.setObjectName(f"metric{variant}")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(1)
        value_label = QLabel(value)
        value_label.setObjectName(f"metric{variant}Value")
        text_label = QLabel(label)
        text_label.setObjectName("metricLabel")
        layout.addWidget(value_label)
        layout.addWidget(text_label)
        box.value_label = value_label
        return box

    def _build_log_card(self):
        log_card = QFrame()
        log_card.setObjectName("logCard")
        layout = QVBoxLayout(log_card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        title = QLabel("运行日志")
        title.setObjectName("logTitle")
        layout.addWidget(title)

        self.log_output = QTextEdit()
        self.log_output.setObjectName("logOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(170)
        layout.addWidget(self.log_output, stretch=1)
        return log_card

    def log(self, text):
        self.log_output.append(str(text))

    def browse_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择工作流 JSON", "", "JSON (*.json)")
        if path:
            self.load_json(path)

    def load_json(self, path):
        try:
            workflow = load_workflow_json(path)
        except Exception as exc:
            QMessageBox.critical(self, "加载失败", str(exc))
            return
        self.workflow_path = path
        self.workflow = workflow
        set_last_workflow_path(path)
        self.json_path_input.setText(path)
        crpa = workflow.get("crpa") or {}
        workflow_name = crpa.get("name") or workflow.get("workflow_name", "未命名")
        crpa_code = crpa.get("code", "") or "未填写"
        self.workflow_name_label.setText(workflow_name)
        self.crpa_label.setText(f"CRPA: {crpa_code}")
        self._build_dynamic_form()
        self.btn_run.setEnabled(True)
        self.status_label.setText(f"已加载: {os.path.basename(path)}")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.log_output.clear()
        self.log(f"[加载] {os.path.basename(path)}")

    def _clear_form(self):
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.file_inputs.clear()
        self.sheet_combos.clear()
        self.param_inputs.clear()
        self.sheet_sources = []
        self.advanced_sheet_card = None
        self.advanced_sheet_body = None
        self.advanced_sheet_toggle = None
        self.sheet_status_label = None

    def _make_card(self, title):
        card = QFrame()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        layout.addWidget(label)
        return card, layout

    def _make_form(self):
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        return form

    def _make_form_label(self, text):
        label = QLabel(str(text or ""))
        label.setObjectName("formChip")
        label.setMinimumWidth(0)
        return label

    def _create_file_card(self, file_resources):
        if not file_resources:
            return None
        file_card, file_layout = self._make_card("文件资源")
        file_form = self._make_form()
        for resource in file_resources:
            key = resource.get("key")
            row = QHBoxLayout()
            row.setSpacing(8)
            line = QLineEdit(resource.get("path", ""))
            line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn = QPushButton("保存到" if resource.get("role") == "output" else "浏览")
            btn.setFixedWidth(82)
            btn.clicked.connect(lambda _=False, r=resource, l=line: self._browse_resource(r, l))
            row.addWidget(line, stretch=1)
            row.addWidget(btn)
            self.file_inputs[key] = line
            file_form.addRow(self._make_form_label(resource.get("label") or key), row)
        file_layout.addLayout(file_form)
        return file_card

    def _create_sheet_card(self, file_resources, contexts):
        sheet_rows = []
        for resource in file_resources:
            key = resource.get("key")
            if resource.get("type") != "excel":
                continue
            for source in contexts.get(key, []):
                sheet_rows.append((key, source))
        self.sheet_sources = sheet_rows
        if not sheet_rows:
            return None

        card = QFrame()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("高级设置")
        title.setObjectName("sectionTitle")
        self.sheet_status_label = QLabel(f"工作表已按模板预设 {len(sheet_rows)} 个")
        self.sheet_status_label.setObjectName("sheetStatusOk")
        self.advanced_sheet_toggle = QToolButton()
        self.advanced_sheet_toggle.setObjectName("advancedToggle")
        self.advanced_sheet_toggle.setCheckable(True)
        self.advanced_sheet_toggle.setChecked(False)
        self.advanced_sheet_toggle.setText("展开工作表映射")
        self.advanced_sheet_toggle.toggled.connect(self._set_sheet_mapping_visible)
        header.addWidget(title)
        header.addWidget(self.sheet_status_label, stretch=1)
        header.addWidget(self.advanced_sheet_toggle)
        layout.addLayout(header)

        self.advanced_sheet_body = QWidget()
        self.advanced_sheet_body.setObjectName("advancedBody")
        body_layout = QVBoxLayout(self.advanced_sheet_body)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(8)
        sheet_form = self._make_form()
        for file_key, source in sheet_rows:
            combo = QComboBox()
            combo.setEditable(True)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            combo.setProperty("file_key", file_key)
            combo.setProperty("source_key", source.get("key"))
            combo.setCurrentText(str(source.get("sheet") or ""))
            combo.currentTextChanged.connect(self._update_sheet_status)
            self.sheet_combos[source.get("key")] = combo
            sheet_form.addRow(self._make_form_label(source.get("label") or source.get("key")), combo)
        body_layout.addLayout(sheet_form)
        layout.addWidget(self.advanced_sheet_body)
        self.advanced_sheet_body.hide()
        self.advanced_sheet_card = card
        return card

    def _create_param_card(self, parameters):
        if not parameters:
            return None
        param_card, param_layout = self._make_card("运行参数")
        param_form = self._make_form()
        for param in parameters:
            widget = self._make_param_widget(param)
            self.param_inputs[param.get("key")] = widget
            param_form.addRow(self._make_form_label(param.get("label") or param.get("key")), widget)
        param_layout.addLayout(param_form)
        return param_card

    def _build_dynamic_form(self):
        self._clear_form()
        manifest = self.workflow.get("run_manifest") or {}
        contexts = collect_file_contexts(self.workflow)
        file_resources = manifest.get("file_resources", []) or []
        parameters = manifest.get("parameters", []) or []
        data_sources = manifest.get("data_sources", []) or []

        file_card = self._create_file_card(file_resources)
        sheet_card = self._create_sheet_card(file_resources, contexts)
        param_card = self._create_param_card(parameters)

        if file_card:
            self.form_layout.addWidget(file_card)

        if param_card:
            self.form_layout.addWidget(param_card)
        if sheet_card:
            self.form_layout.addWidget(sheet_card)

        self.form_layout.addStretch(1)
        if self.sheet_combos:
            self._refresh_all_sheet_combos()
            self._update_sheet_status()
        self._update_summary_counts(len(file_resources), len(data_sources), len(parameters))

    def _update_summary_counts(self, file_count, sheet_count, param_count):
        self.file_count_label.value_label.setText(str(file_count))
        self.sheet_count_label.value_label.setText(str(sheet_count))
        self.param_count_label.value_label.setText(str(param_count))

    def _set_sheet_mapping_visible(self, visible):
        if self.advanced_sheet_body is not None:
            self.advanced_sheet_body.setVisible(visible)
        if self.advanced_sheet_toggle is not None:
            self.advanced_sheet_toggle.setText("收起工作表映射" if visible else "展开工作表映射")

    def _show_sheet_mapping(self):
        if self.advanced_sheet_toggle is not None:
            self.advanced_sheet_toggle.setChecked(True)
        elif self.advanced_sheet_body is not None:
            self.advanced_sheet_body.show()

    def _sheet_validation_issues(self):
        issues = []
        for combo in self.sheet_combos.values():
            sheet = combo.currentText().strip()
            file_key = combo.property("file_key")
            source_key = combo.property("source_key")
            line = self.file_inputs.get(file_key)
            path = line.text().strip() if line is not None else ""
            if not path or not os.path.exists(path):
                continue
            sheets = load_excel_sheet_names(path)
            if sheet and sheets and sheet not in sheets:
                issues.append(f"{source_key}: {sheet}")
        return issues

    def _update_sheet_status(self):
        if self.sheet_status_label is None:
            return
        issues = self._sheet_validation_issues()
        if issues:
            self.sheet_status_label.setObjectName("sheetStatusWarn")
            self.sheet_status_label.setText("部分预设工作表未找到，请展开修正")
            self.sheet_status_label.style().unpolish(self.sheet_status_label)
            self.sheet_status_label.style().polish(self.sheet_status_label)
            self._show_sheet_mapping()
            self.status_label.setText("工作表需要确认")
        else:
            count = len(self.sheet_combos)
            self.sheet_status_label.setObjectName("sheetStatusOk")
            self.sheet_status_label.setText(f"工作表已按模板预设 {count} 个")
            self.sheet_status_label.style().unpolish(self.sheet_status_label)
            self.sheet_status_label.style().polish(self.sheet_status_label)

    def _make_param_widget(self, param):
        param_type = param.get("type", "text")
        default = param.get("default", "")
        if param_type == "bool":
            widget = QCheckBox()
            widget.setChecked(str(default).lower() in {"1", "true", "yes", "是"})
            return widget
        widget = QLineEdit(str(default))
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if param_type == "number":
            widget.setPlaceholderText("数字")
        elif param_type == "date":
            widget.setPlaceholderText("YYYY-MM-DD")
        return widget

    def _browse_resource(self, resource, line):
        start_dir = str(Path(line.text()).parent) if line.text() else ""
        if resource.get("role") == "output":
            default_name = line.text() or resource.get("path") or "output.xlsx"
            path, _ = QFileDialog.getSaveFileName(
                self,
                f"保存{resource.get('label') or '文件'}",
                default_name,
                file_dialog_filter(resource),
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                f"选择{resource.get('label') or '文件'}",
                start_dir,
                file_dialog_filter(resource),
            )
        if path:
            line.setText(path)
            self._refresh_sheet_combos_for_file(resource.get("key"), path)
            self._update_sheet_status()

    def _refresh_all_sheet_combos(self):
        for key, line in self.file_inputs.items():
            self._refresh_sheet_combos_for_file(key, line.text().strip())

    def _refresh_sheet_combos_for_file(self, file_key, path):
        sheets = load_excel_sheet_names(path)
        for combo in self.sheet_combos.values():
            if combo.property("file_key") != file_key:
                continue
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            if sheets:
                combo.addItems(sheets)
            if current:
                combo.setCurrentText(current)
            combo.blockSignals(False)

    def _collect_file_paths(self):
        return {key: line.text().strip() for key, line in self.file_inputs.items()}

    def _collect_data_sources(self):
        data = {}
        for key, combo in self.sheet_combos.items():
            data[key] = {"sheet": combo.currentText().strip()}
        return data

    def _collect_parameters(self):
        params = {}
        for key, widget in self.param_inputs.items():
            if isinstance(widget, QCheckBox):
                params[key] = widget.isChecked()
            else:
                params[key] = widget.text().strip()
        return params

    def _validate_inputs(self, file_paths):
        manifest = self.workflow.get("run_manifest") or {}
        for resource in manifest.get("file_resources", []) or []:
            if resource.get("required") and not file_paths.get(resource.get("key")):
                raise ValueError(f"请选择文件: {resource.get('label') or resource.get('key')}")
            path = file_paths.get(resource.get("key"), "")
            if resource.get("role") == "output":
                parent = Path(path).parent if path else None
                if path and str(parent) != "." and not parent.exists():
                    raise ValueError(f"输出目录不存在: {parent}")
                continue
            if path and not os.path.exists(path):
                raise ValueError(f"文件不存在: {path}")
        sheet_issues = self._sheet_validation_issues()
        if sheet_issues:
            self._show_sheet_mapping()
            raise ValueError("预设工作表在文件中不存在，请在高级设置中修正：" + "、".join(sheet_issues))

    def run_workflow(self):
        if not self.workflow:
            return
        try:
            file_paths = self._collect_file_paths()
            data_sources = self._collect_data_sources()
            parameters = self._collect_parameters()
            self._validate_inputs(file_paths)
            runtime_workflow = build_runtime_workflow(
                self.workflow, file_paths, data_sources, parameters
            )
            payload = build_crpa_payload(runtime_workflow, file_paths, data_sources, parameters)
            print("CRPA payload:", json.dumps(payload, ensure_ascii=False, indent=2))
            self.log("[CRPA] " + json.dumps({"code": payload["crpa_code"], "name": payload["crpa_name"]}, ensure_ascii=False))
            self.log("[运行] 开始执行工作流")
            if self.writeback_check.isChecked() and self.workflow_path:
                self.workflow = runtime_workflow
                save_workflow_json(self.workflow_path, runtime_workflow)
                self.log("[保存] 已写回 JSON 路径、Sheet 和参数")
            self._start_engine(runtime_workflow)
        except Exception as exc:
            self.status_label.setText("无法运行")
            QMessageBox.warning(self, "无法运行", str(exc))

    def _start_engine(self, workflow):
        self.btn_run.setEnabled(False)
        total_steps = len(workflow.get("steps", []))
        self.progress.setRange(0, total_steps if total_steps else 1)
        self.progress.setValue(0)
        self.progress.setFormat(f"%v / {total_steps}")
        self.status_label.setText("正在执行")
        self.engine = WorkflowEngine({}, workflow, keep_intermediates=False)
        self.engine.log_signal.connect(self.log)
        self.engine.progress_signal.connect(self._on_engine_progress)
        self.engine.finished_signal.connect(self._on_engine_finished)
        self.engine.start()

    def _on_engine_progress(self, current, total):
        if self.progress.maximum() != total:
            self.progress.setRange(0, total if total else 1)
            self.progress.setFormat(f"%v / {total}")
        self.progress.setValue(current)

    def _on_engine_finished(self, success, result_pool):
        self.btn_run.setEnabled(True)
        self.progress.setFormat("完成" if success else "失败")
        if success:
            self.status_label.setText("执行完成")
            self.log("[完成] 工作流执行完成")
            QMessageBox.information(self, "执行完成", "工作流执行完成。")
        else:
            self.status_label.setText("执行失败")
            self.log("[失败] 工作流执行失败")
            QMessageBox.critical(self, "执行失败", "工作流执行失败，请查看日志。")
