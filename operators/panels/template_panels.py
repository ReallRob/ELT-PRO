"""Operator panels for the template mainline workflow."""

import os

from PyQt5.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from operators.base_panel import BaseToolPanel, QLineEdit


TEMPLATE_PREVIEW_DEFAULT_ROWS = "5000"
TEMPLATE_PREVIEW_DEFAULT_COLS = "200"


class ImportTemplatePanel(BaseToolPanel):
    use_df = False
    use_type = False
    theme_color = "#795548"
    action_name = "加载模板"

    def _default_output_name(self):
        template_path = self.template_input.text().strip() if hasattr(self, "template_input") else ""
        if template_path:
            return f"模板_{os.path.splitext(os.path.basename(template_path))[0]}"
        return "加载模板"

    def set_incoming_outputs(self, incoming_outputs):
        self._incoming_outputs = []

    def init_custom_ui(self):
        card, inner = self._make_card("模板配置")
        self.custom_layout.addWidget(card)

        path_layout = QHBoxLayout()
        self.template_input = QLineEdit()
        self.template_input.set_parameter_enabled(False)
        self.template_input.setPlaceholderText("选择模板文件 (.xlsx)")
        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self._browse_template)
        path_layout.addWidget(self.template_input)
        path_layout.addWidget(btn_browse)

        fl = QFormLayout()
        fl.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        fl.setRowWrapPolicy(QFormLayout.WrapLongRows)
        fl.addRow("模板文件:", path_layout)
        inner.addLayout(fl)

        self.info_label = QLabel("选择模板后自动扫描结构")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
        inner.addWidget(self.info_label)

        preview_card, preview_inner = self._make_card("预览加载")
        self.custom_layout.addWidget(preview_card)
        preview_form = QFormLayout()
        preview_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        preview_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.preview_sheet_input = QLineEdit()
        self.preview_sheet_input.set_parameter_enabled(False)
        self.preview_sheet_input.setPlaceholderText("留空则预览全部工作表")
        preview_form.addRow("预览工作表:", self.preview_sheet_input)

        range_layout = QHBoxLayout()
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(6)
        self.preview_start_row_input = QLineEdit("1")
        self.preview_start_row_input.setPlaceholderText("起始行")
        self.preview_start_col_input = QLineEdit("1")
        self.preview_start_col_input.setPlaceholderText("起始列")
        self.preview_max_rows_input = QLineEdit(TEMPLATE_PREVIEW_DEFAULT_ROWS)
        self.preview_max_rows_input.setPlaceholderText("行数")
        self.preview_max_cols_input = QLineEdit(TEMPLATE_PREVIEW_DEFAULT_COLS)
        self.preview_max_cols_input.setPlaceholderText("列数")
        for widget in (
            self.preview_start_row_input,
            self.preview_start_col_input,
            self.preview_max_rows_input,
            self.preview_max_cols_input,
        ):
            widget.set_parameter_enabled(False)
            widget.setMaximumWidth(86)
            range_layout.addWidget(widget)
        preview_form.addRow("预览范围:", range_layout)
        preview_inner.addLayout(preview_form)
        preview_inner.addWidget(self._make_hint_label("加载模板只创建模板主线 wb；写入和保存请连接写入模板/保存模板。"))

    def _browse_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择模板文件", "", "Excel (*.xlsx)")
        if not path:
            return
        self.template_input.setText(path)
        try:
            from template_engine import close_workbook, load_template

            wb, meta = load_template(path)
            close_workbook(wb)
            lines = [f"文件: {os.path.basename(path)}"]
            for sn, info in meta["sheets"].items():
                lines.append(f"  Sheet [{sn}]: {info['max_row']} 行 x {info['max_col']} 列")
            if hasattr(self, "out_input") and not self.out_input.text().strip():
                self.out_input.setText(self._default_output_name())
            self.info_label.setText("\n".join(lines))
        except Exception as e:
            self.info_label.setText(f"加载失败: {e}")

    def clear_custom_ui(self):
        self.template_input.clear()
        self.info_label.setText("选择模板后自动扫描结构")
        self.preview_sheet_input.clear()
        self.preview_start_row_input.setText("1")
        self.preview_start_col_input.setText("1")
        self.preview_max_rows_input.setText(TEMPLATE_PREVIEW_DEFAULT_ROWS)
        self.preview_max_cols_input.setText(TEMPLATE_PREVIEW_DEFAULT_COLS)

    def get_custom_params(self):
        template_path = self.template_input.text().strip()
        output_name = self.out_input.text().strip() if hasattr(self, "out_input") else ""
        output_name = output_name or self._default_output_name()
        return {
            "template_path": template_path,
            "preview_sheet_name": self.preview_sheet_input.text().strip(),
            "preview_start_row": self.preview_start_row_input.text().strip() or "1",
            "preview_start_col": self.preview_start_col_input.text().strip() or "1",
            "preview_max_rows": self.preview_max_rows_input.text().strip() or TEMPLATE_PREVIEW_DEFAULT_ROWS,
            "preview_max_cols": self.preview_max_cols_input.text().strip() or TEMPLATE_PREVIEW_DEFAULT_COLS,
            "io_prefs": {"output_name": output_name, "output_data_type": "workbook"},
        }

    def set_custom_params(self, p):
        if "template_path" in p:
            self.template_input.setText(p["template_path"])
        self.preview_sheet_input.setText(str(p.get("preview_sheet_name") or ""))
        self.preview_start_row_input.setText(str(p.get("preview_start_row") or "1"))
        self.preview_start_col_input.setText(str(p.get("preview_start_col") or "1"))
        self.preview_max_rows_input.setText(str(p.get("preview_max_rows") or TEMPLATE_PREVIEW_DEFAULT_ROWS))
        self.preview_max_cols_input.setText(str(p.get("preview_max_cols") or TEMPLATE_PREVIEW_DEFAULT_COLS))


class InsertBlockPanel(BaseToolPanel):
    use_df = False
    use_type = False
    theme_color = "#FF6F00"
    action_name = "写入模板"

    def set_incoming_outputs(self, incoming_outputs):
        self._incoming_outputs = [
            item
            for item in (incoming_outputs or [])
            if isinstance(item, dict)
            and str(item.get("name") or "").strip()
            and str(item.get("data_type") or "table") in {"table", "workbook"}
        ]
        self._refresh_input_summary()

    def init_custom_ui(self):
        input_card, input_inner = self._make_card("输入")
        self.custom_layout.addWidget(input_card)
        self.input_summary = QLabel("请连接一条模板主线和一个数据表。")
        self.input_summary.setWordWrap(True)
        self.input_summary.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
        input_inner.addWidget(self.input_summary)

        self.sheet_input = QLineEdit()
        self.sheet_input.setPlaceholderText("留空则写入模板第一个工作表")
        self.top_form.addRow("目标工作表:", self.sheet_input)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["区域插入", "匹配填充"])
        self.mode_combo.currentIndexChanged.connect(self._update_mode_visibility)
        self.top_form.addRow("插入方式:", self.mode_combo)

        self._build_area_ui()
        self._build_match_fill_ui()
        self._update_mode_visibility()

    def _make_compact_form(self):
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        return form

    def _build_area_ui(self):
        self.area_card, area_inner = self._make_card("区域插入")
        self.custom_layout.addWidget(self.area_card)
        area_form = self._make_compact_form()

        self.chk_header = QComboBox()
        self.chk_header.addItems(["是 (写入表头)", "否 (仅写数据)"])
        self.start_row_input = QLineEdit()
        self.start_row_input.setPlaceholderText("必填，如 5")
        self.start_col_input = QLineEdit()
        self.start_col_input.setPlaceholderText("必填，如 A")
        self.end_row_input = QLineEdit()
        self.end_row_input.setPlaceholderText("可选，如 20")
        self.end_col_input = QLineEdit()
        self.end_col_input.setPlaceholderText("可选，如 D")

        area_form.addRow("写入表头:", self.chk_header)
        area_form.addRow("起始行:", self.start_row_input)
        area_form.addRow("起始列:", self.start_col_input)
        area_form.addRow("结束行:", self.end_row_input)
        area_form.addRow("结束列:", self.end_col_input)
        area_inner.addLayout(area_form)
        area_inner.addWidget(self._make_hint_label("把输入表按矩形区域写入模板主线；只写 value，不继承上一行样式。"))

    def _build_match_fill_ui(self):
        self.match_card, match_inner = self._make_card("匹配填充")
        self.custom_layout.addWidget(self.match_card)
        match_form = self._make_compact_form()

        self.header_mode_combo = QComboBox()
        self.header_mode_combo.addItems(["指定表头行", "自动查找表头", "手动指定列"])
        self.header_mode_combo.currentIndexChanged.connect(self._update_header_mode_visibility)

        self.header_row_input = QLineEdit()
        self.header_row_input.setPlaceholderText("如 3")
        self.header_search_start_input = QLineEdit()
        self.header_search_start_input.setPlaceholderText("默认 1")
        self.header_search_end_input = QLineEdit()
        self.header_search_end_input.setPlaceholderText("默认 50")
        self.data_start_row_input = QLineEdit()
        self.data_start_row_input.setPlaceholderText("默认表头下一行")
        self.data_end_row_input = QLineEdit()
        self.data_end_row_input.setPlaceholderText("默认 max_row")
        self.match_start_col_input = QLineEdit()
        self.match_start_col_input.setPlaceholderText("默认 A")
        self.match_end_col_input = QLineEdit()
        self.match_end_col_input.setPlaceholderText("默认 max_col")

        self.on_missing_combo = QComboBox()
        self.on_missing_combo.addItems(["找不到则跳过", "找不到则报错"])
        self.on_duplicate_combo = QComboBox()
        self.on_duplicate_combo.addItems(["重复取第一条", "重复则报错"])
        self.write_mode_combo = QComboBox()
        self.write_mode_combo.addItems(["自动同名写入", "手动指定映射"])

        match_form.addRow("表头方式:", self.header_mode_combo)
        self.header_row_label = QLabel("表头行:")
        self.header_search_start_label = QLabel("查找起始行:")
        self.header_search_end_label = QLabel("查找结束行:")
        match_form.addRow(self.header_row_label, self.header_row_input)
        match_form.addRow(self.header_search_start_label, self.header_search_start_input)
        match_form.addRow(self.header_search_end_label, self.header_search_end_input)
        match_form.addRow("数据起始行:", self.data_start_row_input)
        match_form.addRow("数据结束行:", self.data_end_row_input)
        match_form.addRow("起始列:", self.match_start_col_input)
        match_form.addRow("结束列:", self.match_end_col_input)
        match_form.addRow("缺失处理:", self.on_missing_combo)
        match_form.addRow("重复处理:", self.on_duplicate_combo)
        match_form.addRow("写入方式:", self.write_mode_combo)
        match_inner.addLayout(match_form)
        match_inner.addWidget(self._make_hint_label("匹配键必填；写入映射可留空，留空时按模板表头和数据列同名自动写入。"))

        self.match_keys_layout = QVBoxLayout()
        self.match_keys_layout.setSpacing(6)
        match_inner.addWidget(QLabel("匹配键"))
        match_inner.addLayout(self.match_keys_layout)
        btn_add_key = self._make_add_button("+ 添加匹配键")
        btn_add_key.clicked.connect(lambda: self.add_mapping_row(self.match_keys_layout))
        match_inner.addWidget(btn_add_key)

        self.write_mappings_layout = QVBoxLayout()
        self.write_mappings_layout.setSpacing(6)
        match_inner.addWidget(QLabel("写入映射"))
        match_inner.addLayout(self.write_mappings_layout)
        btn_add_mapping = self._make_add_button("+ 添加写入映射")
        btn_add_mapping.clicked.connect(lambda: self.add_mapping_row(self.write_mappings_layout))
        match_inner.addWidget(btn_add_mapping)

        self.add_mapping_row(self.match_keys_layout)
        self._update_header_mode_visibility()

    def add_mapping_row(self, target_layout, template_value="", df_col="", template_col=""):
        row_widget = QWidget()
        row_widget.setObjectName("template_mapping_row")
        layout = QHBoxLayout(row_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        template_input = QLineEdit(str(template_col or template_value or ""))
        template_input.setObjectName("template_ref")
        template_input.setPlaceholderText("模板字段/列")
        df_input = self._make_col_combo("数据字段")
        df_input.setObjectName("df_col")
        if df_col:
            self._set_col_name(df_input, df_col)
        arrow = QLabel("←")
        arrow.setStyleSheet("color: #64748B; border: none; font-weight: bold;")
        btn_rm = self._make_delete_button()
        btn_rm.clicked.connect(lambda checked=False, r=row_widget: self.remove_dynamic_row(r))

        layout.addWidget(template_input, stretch=1)
        layout.addWidget(arrow)
        layout.addWidget(df_input, stretch=1)
        layout.addWidget(btn_rm)
        target_layout.addWidget(row_widget)
        return row_widget

    def _template_ref(self):
        return next((item for item in getattr(self, "_incoming_outputs", []) if item.get("data_type") == "workbook"), None)

    def _table_ref(self):
        return next((item for item in getattr(self, "_incoming_outputs", []) if item.get("data_type", "table") == "table"), None)

    def _refresh_input_summary(self):
        if not hasattr(self, "input_summary"):
            return
        template_ref = self._template_ref()
        table_ref = self._table_ref()
        template_text = str((template_ref or {}).get("name") or "未连接模板主线")
        table_text = str((table_ref or {}).get("name") or "未连接数据表")
        self.input_summary.setText(f"模板输入: {template_text}\n数据输入: {table_text}")

    def _io_prefs(self):
        refs = []
        template_ref = self._template_ref()
        table_ref = self._table_ref()
        if template_ref:
            refs.append((template_ref, "workbook", "workbook"))
        if table_ref:
            refs.append((table_ref, "table", "table"))
        inputs = []
        for index, (ref, role, data_type) in enumerate(refs, start=1):
            inputs.append(
                {
                    "source_node_id": str(ref.get("source_node_id") or ""),
                    "source_output_id": str(ref.get("source_output_id") or f"out_{index}"),
                    "name": str(ref.get("name") or ""),
                    "role": role,
                    "data_type": data_type,
                    "enabled": True,
                }
            )
        return {"inputs": inputs, "output_name": "写入模板", "output_data_type": "workbook"}

    def _update_mode_visibility(self):
        is_match = self._current_mode() == "match_fill"
        self.area_card.setVisible(not is_match)
        self.match_card.setVisible(is_match)
        self._update_header_mode_visibility()

    def _update_header_mode_visibility(self):
        if not hasattr(self, "header_mode_combo"):
            return
        mode = self._current_header_mode()
        specified = mode == "specified"
        auto_find = mode == "auto_find"
        self.header_row_input.setVisible(specified)
        self.header_row_label.setVisible(specified)
        self.header_search_start_input.setVisible(auto_find)
        self.header_search_start_label.setVisible(auto_find)
        self.header_search_end_input.setVisible(auto_find)
        self.header_search_end_label.setVisible(auto_find)

    def _current_mode(self):
        return "match_fill" if self.mode_combo.currentText() == "匹配填充" else "area"

    def _current_header_mode(self):
        text = self.header_mode_combo.currentText()
        if text == "自动查找表头":
            return "auto_find"
        if text == "手动指定列":
            return "manual_columns"
        return "specified"

    def _set_header_mode(self, mode):
        index_map = {"specified": 0, "auto_find": 1, "manual_columns": 2}
        self.header_mode_combo.setCurrentIndex(index_map.get(str(mode or "specified"), 0))

    def _collect_mapping_rows(self, layout):
        rows = []
        header_mode = self._current_header_mode()
        for i in range(layout.count()):
            row = layout.itemAt(i).widget()
            if not row or row.objectName() != "template_mapping_row":
                continue
            template_ref = row.findChild(QLineEdit, "template_ref").text().strip()
            df_combo = row.findChild(QComboBox, "df_col")
            df_col = self._get_col_name(df_combo)
            if not template_ref and not df_col:
                continue
            item = {"df_col": df_col}
            if header_mode == "manual_columns":
                item["template_col"] = template_ref
            else:
                item["template_field"] = template_ref
            rows.append(item)
        return rows

    def _set_mapping_rows(self, layout, rows, keep_one_empty=False):
        self.clear_dynamic_layout(layout)
        has_rows = False
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            template_ref = row.get("template_col") or row.get("template_field") or ""
            self.add_mapping_row(layout, template_value=template_ref, df_col=row.get("df_col") or "")
            has_rows = True
        if keep_one_empty and not has_rows:
            self.add_mapping_row(layout)

    def clear_custom_ui(self):
        self.sheet_input.clear()
        self.mode_combo.setCurrentIndex(0)
        self.chk_header.setCurrentIndex(0)
        self.start_row_input.clear()
        self.start_col_input.clear()
        self.end_row_input.clear()
        self.end_col_input.clear()
        self.header_mode_combo.setCurrentIndex(0)
        self.header_row_input.clear()
        self.header_search_start_input.clear()
        self.header_search_end_input.clear()
        self.data_start_row_input.clear()
        self.data_end_row_input.clear()
        self.match_start_col_input.clear()
        self.match_end_col_input.clear()
        self.on_missing_combo.setCurrentIndex(0)
        self.on_duplicate_combo.setCurrentIndex(0)
        self.write_mode_combo.setCurrentIndex(0)
        self._set_mapping_rows(self.match_keys_layout, [], keep_one_empty=True)
        self._set_mapping_rows(self.write_mappings_layout, [])
        self._update_mode_visibility()
        self._refresh_input_summary()

    def set_custom_params(self, p):
        mode = str(p.get("mode") or "area")
        self.mode_combo.setCurrentIndex(1 if mode == "match_fill" else 0)
        if "sheet_name" in p:
            self.sheet_input.setText(p["sheet_name"])

        if "write_header" in p:
            self.chk_header.setCurrentIndex(0 if p["write_header"] else 1)
        if mode == "match_fill":
            self.match_start_col_input.setText(str(p.get("start_col") or ""))
            self.match_end_col_input.setText(str(p.get("end_col") or ""))
        else:
            self.start_row_input.setText(str(p.get("start_row") or ""))
            self.end_row_input.setText(str(p.get("end_row") or ""))
            self.start_col_input.setText(str(p.get("start_col") or ""))
            self.end_col_input.setText(str(p.get("end_col") or ""))

        self._set_header_mode(p.get("header_mode") or "specified")
        self.header_row_input.setText(str(p.get("header_row") or ""))
        self.header_search_start_input.setText(str(p.get("header_search_start_row") or ""))
        self.header_search_end_input.setText(str(p.get("header_search_end_row") or ""))
        self.data_start_row_input.setText(str(p.get("data_start_row") or ""))
        self.data_end_row_input.setText(str(p.get("data_end_row") or ""))
        self.on_missing_combo.setCurrentIndex(1 if p.get("on_missing") == "error" else 0)
        self.on_duplicate_combo.setCurrentIndex(1 if p.get("on_duplicate") == "error" else 0)
        self.write_mode_combo.setCurrentIndex(1 if p.get("write_mode") == "manual" else 0)
        self._set_mapping_rows(self.match_keys_layout, p.get("match_keys") or [], keep_one_empty=True)
        self._set_mapping_rows(self.write_mappings_layout, p.get("write_mappings") or [])
        self._update_mode_visibility()
        self._refresh_input_summary()

    def get_custom_params(self):
        mode = self._current_mode()
        params = {
            "mode": mode,
            "sheet_name": self.sheet_input.text().strip(),
            "io_prefs": self._io_prefs(),
        }
        if mode != "match_fill":
            params.update(
                {
                    "start_row": self.start_row_input.text().strip(),
                    "end_row": self.end_row_input.text().strip(),
                    "start_col": self.start_col_input.text().strip(),
                    "end_col": self.end_col_input.text().strip(),
                    "write_header": self.chk_header.currentIndex() == 0,
                }
            )
            return params

        params.update(
            {
                "header_mode": self._current_header_mode(),
                "header_row": self.header_row_input.text().strip(),
                "header_search_start_row": self.header_search_start_input.text().strip(),
                "header_search_end_row": self.header_search_end_input.text().strip(),
                "data_start_row": self.data_start_row_input.text().strip(),
                "data_end_row": self.data_end_row_input.text().strip(),
                "start_col": self.match_start_col_input.text().strip(),
                "end_col": self.match_end_col_input.text().strip(),
                "match_keys": self._collect_mapping_rows(self.match_keys_layout),
                "write_mode": "manual" if self.write_mode_combo.currentIndex() == 1 else "auto_same_name",
                "write_mappings": self._collect_mapping_rows(self.write_mappings_layout),
                "on_missing": "error" if self.on_missing_combo.currentIndex() == 1 else "skip",
                "on_duplicate": "error" if self.on_duplicate_combo.currentIndex() == 1 else "first",
                "overwrite_formulas": False,
            }
        )
        return params


class SaveTemplatePanel(BaseToolPanel):
    use_df = False
    use_type = False
    use_out = False
    theme_color = "#607D8B"
    action_name = "保存模板"

    def set_incoming_outputs(self, incoming_outputs):
        self._incoming_outputs = [
            item
            for item in (incoming_outputs or [])
            if isinstance(item, dict)
            and str(item.get("name") or "").strip()
            and str(item.get("data_type") or "") == "workbook"
        ]
        self._refresh_input_summary()

    def init_custom_ui(self):
        input_card, input_inner = self._make_card("输入")
        self.custom_layout.addWidget(input_card)
        self.input_summary = QLabel("请连接模板主线。")
        self.input_summary.setWordWrap(True)
        self.input_summary.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
        input_inner.addWidget(self.input_summary)

        card, inner = self._make_card("保存配置")
        self.custom_layout.addWidget(card)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)

        self.output_path_input = QLineEdit()
        self.output_path_input.set_parameter_enabled(False)
        self.output_path_input.setPlaceholderText("可选，留空则保存到运行目录")
        btn_save = QPushButton("保存到")
        btn_save.clicked.connect(self._browse_output_path)
        row = QHBoxLayout()
        row.addWidget(self.output_path_input)
        row.addWidget(btn_save)
        form.addRow("输出文件:", row)

        self.file_name_input = QLineEdit("template_filled.xlsx")
        self.file_name_input.setPlaceholderText("留空时按模板名自动生成")
        form.addRow("默认文件名:", self.file_name_input)
        inner.addLayout(form)
        inner.addWidget(self._make_hint_label("建议在模板主线最后保存一次，避免代码块中手动 wb.save。"))

    def _workbook_ref(self):
        return next((item for item in getattr(self, "_incoming_outputs", []) if item.get("data_type") == "workbook"), None)

    def _refresh_input_summary(self):
        if not hasattr(self, "input_summary"):
            return
        ref = self._workbook_ref()
        self.input_summary.setText(f"模板输入: {str((ref or {}).get('name') or '未连接模板主线')}")

    def _browse_output_path(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存模板", "template_filled.xlsx", "Excel (*.xlsx)")
        if path:
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            self.output_path_input.setText(path)

    def clear_custom_ui(self):
        self.output_path_input.clear()
        self.file_name_input.setText("template_filled.xlsx")
        self._refresh_input_summary()

    def get_custom_params(self):
        ref = self._workbook_ref()
        inputs = []
        if ref:
            inputs.append(
                {
                    "source_node_id": str(ref.get("source_node_id") or ""),
                    "source_output_id": str(ref.get("source_output_id") or "out_1"),
                    "name": str(ref.get("name") or ""),
                    "role": "workbook",
                    "data_type": "workbook",
                    "enabled": True,
                }
            )
        return {
            "output_path": self.output_path_input.text().strip(),
            "file_name": self.file_name_input.text().strip(),
            "io_prefs": {"inputs": inputs, "output_name": "保存模板", "output_data_type": "workbook"},
        }

    def set_custom_params(self, p):
        self.output_path_input.setText(str(p.get("output_path") or ""))
        self.file_name_input.setText(str(p.get("file_name") or "template_filled.xlsx"))
        self._refresh_input_summary()
