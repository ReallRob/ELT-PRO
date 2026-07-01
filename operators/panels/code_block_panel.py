"""Panel for the experimental multi-input code block operator."""

import copy
import keyword
import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from operators.base_panel import BaseToolPanel, QLineEdit


_ALIAS_RE = re.compile(r"^[A-Za-z_]\w*$")
_RESERVED_ALIASES = {
    "pd",
    "np",
    "re",
    "math",
    "datetime",
    "date",
    "timedelta",
    "openpyxl",
    "copy",
    "deepcopy",
    "get_column_letter",
    "params",
    "mappings",
    "param",
    "state",
    "dfs",
    "result",
    "wbs",
    "wss",
    "locals",
}

def _valid_alias(alias):
    text = str(alias or "").strip()
    return bool(
        text
        and _ALIAS_RE.match(text)
        and not keyword.iskeyword(text)
        and text not in _RESERVED_ALIASES
    )


class PythonCodeEditor(QPlainTextEdit):
    INDENT = "    "

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._insert_newline_with_indent()
            return
        if key == Qt.Key_Tab and not (modifiers & Qt.ShiftModifier):
            if self.textCursor().hasSelection():
                self._indent_selected_blocks()
            else:
                self.insertPlainText(self.INDENT)
            return
        if key == Qt.Key_Backtab or (key == Qt.Key_Tab and modifiers & Qt.ShiftModifier):
            self._unindent_selected_blocks()
            return
        if key == Qt.Key_Backspace and self._try_backspace_indent():
            return
        super().keyPressEvent(event)

    def _insert_newline_with_indent(self):
        cursor = self.textCursor()
        block_text = cursor.block().text()
        before_cursor = block_text[:cursor.positionInBlock()]
        indent = re.match(r"[ \t]*", before_cursor).group(0)
        if before_cursor.strip().endswith(":"):
            indent += self.INDENT
        self.insertPlainText("\n" + indent)

    def _try_backspace_indent(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False
        pos = cursor.positionInBlock()
        if pos == 0:
            return False
        before_cursor = cursor.block().text()[:pos]
        if before_cursor.strip():
            return False
        remove_count = pos % len(self.INDENT) or len(self.INDENT)
        remove_count = min(remove_count, pos)
        cursor.setPosition(cursor.position() - remove_count, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        return True

    def _selected_block_range(self):
        cursor = self.textCursor()
        doc = self.document()
        start = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        end = cursor.selectionEnd() if cursor.hasSelection() else cursor.position()
        start_cursor = QTextCursor(doc)
        start_cursor.setPosition(start)
        end_cursor = QTextCursor(doc)
        end_cursor.setPosition(end)
        start_block = start_cursor.blockNumber()
        end_block = end_cursor.blockNumber()
        if cursor.hasSelection() and end_cursor.positionInBlock() == 0 and end > start:
            end_block = max(start_block, end_block - 1)
        return start_block, end_block

    def _indent_selected_blocks(self):
        cursor = self.textCursor()
        doc = self.document()
        start_block, end_block = self._selected_block_range()
        cursor.beginEditBlock()
        for block_number in range(start_block, end_block + 1):
            block = doc.findBlockByNumber(block_number)
            if not block.isValid():
                continue
            line_cursor = QTextCursor(block)
            line_cursor.insertText(self.INDENT)
        cursor.endEditBlock()

    def _unindent_selected_blocks(self):
        cursor = self.textCursor()
        doc = self.document()
        start_block, end_block = self._selected_block_range()
        cursor.beginEditBlock()
        for block_number in range(start_block, end_block + 1):
            block = doc.findBlockByNumber(block_number)
            if not block.isValid():
                continue
            text = block.text()
            remove_count = 0
            if text.startswith(self.INDENT):
                remove_count = len(self.INDENT)
            elif text.startswith("\t"):
                remove_count = 1
            else:
                leading_spaces = len(text) - len(text.lstrip(" "))
                remove_count = min(leading_spaces, len(self.INDENT))
            if remove_count:
                line_cursor = QTextCursor(block)
                line_cursor.setPosition(block.position() + remove_count, QTextCursor.KeepAnchor)
                line_cursor.removeSelectedText()
        cursor.endEditBlock()


class CodeEditorDialog(QDialog):
    def __init__(self, code="", global_code="", parameters=None, mappings=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑代码")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.resize(820, 560)
        self._runtime_parameters = parameters or {}
        self._parameter_mappings = mappings or {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)

        btn_param = QPushButton("引用参数")
        btn_param.clicked.connect(self._show_parameter_menu)
        btn_template = QPushButton("插入示例")
        btn_template.clicked.connect(self._insert_example)
        self.btn_run = QPushButton("运行")
        self.btn_run.setObjectName("primary_execute")
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #64748B; font-size: 12px;")
        self.run_status_label = QLabel("")
        self.run_status_label.setWordWrap(True)
        self.run_status_label.hide()

        toolbar.addWidget(btn_param)
        toolbar.addWidget(btn_template)
        toolbar.addWidget(self.btn_run)
        toolbar.addStretch(1)
        toolbar.addWidget(self.summary_label)
        layout.addLayout(toolbar)
        layout.addWidget(self.run_status_label)

        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.Monospace)
        self.tabs = QTabWidget()
        self.global_editor = self._make_editor(
            global_code,
            "定义所有代码块可复用的函数和常量。函数内部可以 return，顶层不要直接 return。\n"
            "可用：pd、np、re、math、datetime/date/timedelta、openpyxl、copy/deepcopy、params、state、param()。\n"
            "允许 import 已打包库：pandas、numpy、openpyxl、re、math、datetime、copy。"
        )
        self.editor = self._make_editor(
            code,
            "当前代码块的主函数体，可直接 return。\n"
            "推荐：return {'明细表': df}\n"
            "没有 return 时：优先 result；接入模板则默认输出 wb；否则输出 df。"
        )
        self.global_editor.setFont(font)
        self.editor.setFont(font)
        self.tabs.addTab(self.editor, "当前代码")
        self.tabs.addTab(self.global_editor, "全局函数")
        self.tabs.setCurrentWidget(self.editor)
        layout.addWidget(self.tabs, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_summary()

    def code(self):
        return self.editor.toPlainText()

    def global_code(self):
        return self.global_editor.toPlainText()

    def _make_editor(self, text, placeholder):
        editor = PythonCodeEditor()
        editor.setPlainText(str(text or ""))
        editor.document().setModified(False)
        editor.setPlaceholderText(placeholder)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        editor.textChanged.connect(self._refresh_summary)
        editor.setStyleSheet(
            "QPlainTextEdit { background: #0F172A; color: #E5E7EB; "
            "border: 1px solid #334155; border-radius: 6px; padding: 8px; }"
        )
        return editor

    def _refresh_summary(self):
        code = self.editor.toPlainText()
        global_code = self.global_editor.toPlainText() if hasattr(self, "global_editor") else ""
        code_lines = 0 if not code else len(code.splitlines())
        global_lines = 0 if not global_code else len(global_code.splitlines())
        self.summary_label.setText(f"全局 {global_lines} 行 · 当前 {code_lines} 行")

    def set_run_status(self, status, message=""):
        text = str(message or "").strip()
        self.run_status_label.setVisible(bool(text))
        self.run_status_label.setText(text)
        styles = {
            "running": "color: #1D4ED8; background: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 6px; padding: 7px 8px;",
            "success": "color: #047857; background: #ECFDF5; border: 1px solid #A7F3D0; border-radius: 6px; padding: 7px 8px;",
            "error": "color: #B91C1C; background: #FEF2F2; border: 1px solid #FECACA; border-radius: 6px; padding: 7px 8px;",
            "info": "color: #475569; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 7px 8px;",
        }
        self.run_status_label.setStyleSheet(styles.get(str(status or "info"), styles["info"]))
        self.btn_run.setEnabled(str(status or "") != "running")

    def _insert_text(self, text):
        editor = self.tabs.currentWidget() if hasattr(self, "tabs") else self.editor
        cursor = editor.textCursor()
        cursor.insertText(text)
        editor.setTextCursor(cursor)
        editor.setFocus()

    def _insert_example(self):
        if self.tabs.currentWidget() is self.global_editor:
            self._insert_text("def normalize_date(value):\n    return pd.to_datetime(value, errors='coerce')\n")
        else:
            self._insert_text("return {'代码块结果': df}\n")

    def _show_parameter_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: white; border: 1px solid #CBD5E1; border-radius: 6px; }
            QMenu::item { padding: 7px 18px; font-size: 12px; }
            QMenu::item:selected { background: #EEF2FF; color: #3730A3; }
            QMenu::separator { height: 1px; background: #E5EAF0; margin: 4px 8px; }
        """)
        params = sorted((self._runtime_parameters or {}).keys())
        mappings = sorted((self._parameter_mappings or {}).keys())
        if params:
            for name in params:
                action = menu.addAction(f"params[{name!r}]")
                action.triggered.connect(lambda checked=False, n=name: self._insert_text(f"params[{n!r}]"))
        else:
            action = menu.addAction("暂无可用参数")
            action.setEnabled(False)

        if params and mappings:
            menu.addSeparator()
            for mapping_name in mappings:
                for param_name in params:
                    label = f"param({param_name!r}, {mapping_name!r})"
                    action = menu.addAction(label)
                    action.triggered.connect(
                        lambda checked=False, p=param_name, m=mapping_name: self._insert_text(
                            f"param({p!r}, {m!r})"
                        )
                    )
        menu.exec_(self.mapToGlobal(self.rect().topLeft()))


class CodeBlockPanel(BaseToolPanel):
    global_code_changed = pyqtSignal(str)
    code_editor_saved = pyqtSignal(str, str, str)
    code_editor_run_requested = pyqtSignal(str, str, str)
    use_df = False
    use_type = False
    theme_color = "#7C3AED"
    action_name = "代码块"

    def init_custom_ui(self):
        basic_card, basic_inner = self._make_card("基础配置")
        self.custom_layout.addWidget(basic_card)
        basic_form = QFormLayout()
        basic_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        basic_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        basic_form.setHorizontalSpacing(12)
        basic_form.setVerticalSpacing(8)
        self.timeout_input = QLineEdit("10")
        self.timeout_input.setMaximumWidth(96)
        self.timeout_input.setPlaceholderText("秒")
        basic_form.addRow("超时:", self.timeout_input)
        basic_inner.addLayout(basic_form)

        input_card, input_inner = self._make_card("输入配置")
        self.custom_layout.addWidget(input_card)
        self.bindings_layout = QVBoxLayout()
        self.bindings_layout.setSpacing(6)
        input_inner.addLayout(self.bindings_layout)
        self.input_hint = self._make_hint_label("输入彼此同级；数据表默认生成 df、df1，模板默认生成 wb、wb1。没有输入也可以运行，只要代码 return 或设置 result/df。需要工作表变量时填写 Sheet。")
        input_inner.addWidget(self.input_hint)

        code_card, code_inner = self._make_card("代码")
        self.custom_layout.addWidget(code_card)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.code_summary = QLabel("未编写代码")
        self.code_summary.setStyleSheet(
            "color: #334155; background: #F8FAFC; border: 1px solid #E2E8F0; "
            "border-radius: 6px; padding: 7px 8px;"
        )
        self.code_summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_edit = QPushButton("编辑代码")
        btn_edit.setObjectName("primary_execute")
        btn_edit.setMinimumHeight(32)
        btn_edit.clicked.connect(self._open_code_editor)
        row.addWidget(self.code_summary, stretch=1)
        row.addWidget(btn_edit)
        code_inner.addLayout(row)
        code_inner.addWidget(
            self._make_hint_label("默认可用：df/dfs、wb/wbs、pd、np、re、math、datetime、openpyxl、copy/deepcopy、params、state、param()。输入都是同级变量名；允许 import 已打包库，如 from openpyxl.styles import Font；推荐 return {'输出名': df}。")
        )

        self.code_text = ""
        self.global_code_text = ""
        self._saved_outputs = []
        self._incoming_tables = []
        self._incoming_items = []
        self._incoming_outputs = []
        self._bound_node_id = ""
        self._code_editor_dialogs = {}
        self._rebuild_binding_rows([])
        self._refresh_code_summary()

    def update_combos(self, table_names):
        incoming = [
            {
                "source_node_id": "",
                "source_output_id": f"out_{index}",
                "name": str(name),
                "data_type": "table",
            }
            for index, name in enumerate(table_names or [], start=1)
            if str(name or "").strip()
        ]
        self.set_incoming_outputs(incoming)

    def set_incoming_outputs(self, incoming_outputs):
        self._incoming_outputs = [
            item
            for item in (incoming_outputs or [])
            if isinstance(item, dict)
            and str(item.get("name") or "").strip()
            and str(item.get("data_type") or "table") in ("table", "workbook")
        ]
        self._incoming_tables = [item["name"] for item in self._incoming_outputs]
        self._incoming_items = list(self._incoming_outputs)
        saved = self._collect_binding_rows()
        self._rebuild_binding_rows(self._merge_bindings(self._incoming_outputs, saved))

    def clear_custom_ui(self):
        self.timeout_input.setText("10")
        self.code_text = ""
        self._saved_outputs = []
        self._rebuild_binding_rows(self._merge_bindings(self._incoming_items, []))
        self._refresh_code_summary()

    def set_global_code(self, global_code=""):
        self.global_code_text = str(global_code or "")
        for dialog in list(getattr(self, "_code_editor_dialogs", {}).values()):
            if dialog is None or not dialog.isVisible():
                continue
            if dialog.global_editor.document().isModified():
                continue
            dialog.global_editor.setPlainText(self.global_code_text)
            dialog.global_editor.document().setModified(False)
        self._refresh_code_summary()

    def set_bound_node_id(self, node_id=""):
        self._bound_node_id = str(node_id or "")

    def set_custom_params(self, p):
        if "timeout_seconds" in p:
            self.timeout_input.setText(str(p.get("timeout_seconds") or "10"))
        self.code_text = str(p.get("code") or "")
        self._saved_outputs = copy.deepcopy([item for item in p.get("outputs") or [] if isinstance(item, dict)])
        bindings = self._bindings_from_inputs(p.get("inputs") or [])
        self._rebuild_binding_rows(self._merge_bindings(self._incoming_outputs, bindings))
        self._refresh_code_summary()

    def get_custom_params(self):
        inputs = self._collect_flow_inputs()
        outputs = self._collect_outputs_for_save(inputs)
        return {
            "io_prefs": {"bindings": self._input_prefs_for_save(inputs), "outputs": self._output_prefs_for_save(outputs)},
            "code": self.code_text,
            "timeout_seconds": self.timeout_input.text().strip() or "10",
        }

    def _input_prefs_for_save(self, inputs):
        prefs = []
        for item in inputs or []:
            if not isinstance(item, dict):
                continue
            pref = copy.deepcopy(item)
            pref.pop("input_id", None)
            prefs.append(pref)
        return prefs

    def _output_prefs_for_save(self, outputs):
        prefs = []
        for item in outputs or []:
            if not isinstance(item, dict):
                continue
            prefs.append(
                {
                    "output_id": str(item.get("output_id") or f"out_{len(prefs) + 1}"),
                    "name": str(item.get("name") or ""),
                    "data_type": str(item.get("data_type") or "table"),
                }
            )
        return prefs

    def _collect_outputs_for_save(self, inputs):
        if len(self._saved_outputs) > 1:
            return copy.deepcopy(self._saved_outputs)
        name = self.out_input.text().strip() if hasattr(self, "out_input") else ""
        if not name and self._saved_outputs:
            name = str(self._saved_outputs[0].get("name") or "")
        output_type = "workbook" if any(item.get("data_type") == "workbook" for item in inputs) else "table"
        return [{
            "output_id": "out_1",
            "name": name or "代码块结果",
            "data_type": output_type,
        }]

    def set_runtime_outputs(self, outputs):
        self._saved_outputs = copy.deepcopy([item for item in outputs or [] if isinstance(item, dict)])
        if len(self._saved_outputs) == 1 and hasattr(self, "out_input"):
            self.out_input.setText(str(self._saved_outputs[0].get("name") or ""))
        self._refresh_code_summary()

    def _default_alias(self, index):
        return "df" if index == 0 else f"df{index}"

    def _default_alias_for_type(self, data_type, index_by_type):
        if data_type == "workbook":
            return "wb" if index_by_type == 0 else f"wb{index_by_type}"
        return "df" if index_by_type == 0 else f"df{index_by_type}"

    def _default_ws_alias(self, workbook_alias):
        text = str(workbook_alias or "wb").strip()
        if text == "wb":
            return "ws"
        if text.startswith("wb"):
            return "ws" + text[2:]
        return f"{text}_ws"

    def _binding_key(self, item):
        source_node_id = str(item.get("source_node_id") or "").strip()
        source_output_id = str(item.get("source_output_id") or "out_1").strip() or "out_1"
        if source_node_id:
            return (source_node_id, source_output_id)
        return None

    def _merge_bindings(self, table_names, saved_bindings):
        by_source = {}
        by_table = {}
        for item in saved_bindings or []:
            table_name = str(item.get("table_name") or "").strip()
            key = self._binding_key(item)
            if key:
                by_source[key] = item
            elif table_name:
                by_table.setdefault(table_name, []).append(item)
        consumed_names = {}

        result = []
        type_counts = {"table": 0, "workbook": 0}
        for i, source in enumerate(table_names or []):
            if isinstance(source, dict):
                table_name = str(source.get("name") or "").strip()
                source_node_id = str(source.get("source_node_id") or "")
                source_output_id = str(source.get("source_output_id") or f"out_{i + 1}")
                data_type = str(source.get("data_type") or "table")
            else:
                table_name = str(source or "").strip()
                source_node_id = ""
                source_output_id = f"out_{i + 1}"
                data_type = "table"
            if not table_name:
                continue
            key = self._binding_key(
                {
                    "source_node_id": source_node_id,
                    "source_output_id": source_output_id,
                }
            )
            saved = by_source.get(key, {}) if key else {}
            if not saved:
                candidates = by_table.get(table_name, [])
                consumed = consumed_names.get(table_name, 0)
                saved = candidates[consumed] if consumed < len(candidates) else {}
                if candidates:
                    consumed_names[table_name] = consumed + 1
            type_index = type_counts.get(data_type, 0)
            type_counts[data_type] = type_index + 1
            alias = str(saved.get("alias") or self._default_alias_for_type(data_type, type_index)).strip()
            sheet_name = str(saved.get("sheet_name") or "").strip()
            ws_alias = str(saved.get("ws_alias") or "").strip()
            result.append(
                {
                    "table_name": table_name,
                    "alias": alias,
                    "sheet_name": sheet_name,
                    "ws_alias": ws_alias,
                    "source_node_id": source_node_id,
                    "source_output_id": source_output_id,
                    "data_type": data_type,
                }
            )
        return result

    def _rebuild_binding_rows(self, bindings):
        self.clear_dynamic_layout(self.bindings_layout)
        if not bindings:
            label = QLabel("暂无上游输入。代码块可独立运行，也可连接数据表或模板后在这里设置变量名。")
            label.setObjectName("empty_inputs")
            label.setWordWrap(True)
            label.setStyleSheet("color: #94A3B8; padding: 8px; border: 1px dashed #CBD5E1; border-radius: 6px;")
            self.bindings_layout.addWidget(label)
            return
        for i, binding in enumerate(bindings):
            self._add_binding_row(
                i,
                binding.get("table_name", ""),
                binding.get("alias", self._default_alias(i)),
                binding,
            )

    def _add_binding_row(self, index, table_name, alias, source=None):
        row = QWidget()
        row.setObjectName("binding_row")
        source = source or next(
            (
                item for item in getattr(self, "_incoming_outputs", [])
                if str(item.get("name") or "") == str(table_name or "")
            ),
            {},
        )
        row.setProperty("source_node_id", str(source.get("source_node_id") or ""))
        row.setProperty("source_output_id", str(source.get("source_output_id") or f"out_{index + 1}"))
        row.setProperty("data_type", str(source.get("data_type") or "table"))
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(5)
        main_line = QHBoxLayout()
        main_line.setContentsMargins(0, 0, 0, 0)
        main_line.setSpacing(6)

        table_label = QLabel(str(table_name or ""))
        table_label.setObjectName("table_name")
        table_label.setToolTip(str(table_name or ""))
        table_label.setStyleSheet("color: #334155; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 5px 7px;")
        table_label.setMinimumWidth(0)
        table_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        alias_input = QLineEdit(str(alias or self._default_alias(index)))
        alias_input.setObjectName("alias")
        alias_input.setPlaceholderText(self._default_alias(index))
        alias_input.setMaximumWidth(96)
        alias_input.setMinimumWidth(72)
        alias_input.setProperty("_param_disabled", True)
        if hasattr(alias_input, "set_parameter_enabled"):
            alias_input.set_parameter_enabled(False)

        data_type = str(source.get("data_type") or "table")
        type_text = "模板" if data_type == "workbook" else "数据表"
        tag_text = f"输入 {index + 1} · {type_text}"
        tag = QLabel(tag_text)
        tag.setStyleSheet("color: #64748B; font-size: 11px; border: none;")

        main_line.addWidget(tag)
        main_line.addWidget(table_label, stretch=1)
        main_line.addWidget(QLabel("变量名"))
        main_line.addWidget(alias_input)
        layout.addLayout(main_line)
        if data_type == "workbook":
            sheet_line = QHBoxLayout()
            sheet_line.setContentsMargins(0, 0, 0, 0)
            sheet_line.setSpacing(6)
            sheet_input = QLineEdit(str(source.get("sheet_name") or ""))
            sheet_input.setObjectName("sheet_name")
            sheet_input.setPlaceholderText("工作表/留空active")
            sheet_input.setMinimumWidth(96)
            sheet_input.setProperty("_param_disabled", True)
            if hasattr(sheet_input, "set_parameter_enabled"):
                sheet_input.set_parameter_enabled(False)
            ws_alias_input = QLineEdit(str(source.get("ws_alias") or ""))
            ws_alias_input.setObjectName("ws_alias")
            ws_alias_input.setPlaceholderText(self._default_ws_alias(alias_input.text()))
            ws_alias_input.setMaximumWidth(96)
            ws_alias_input.setMinimumWidth(72)
            ws_alias_input.setProperty("_param_disabled", True)
            if hasattr(ws_alias_input, "set_parameter_enabled"):
                ws_alias_input.set_parameter_enabled(False)
            sheet_line.addSpacing(34)
            sheet_line.addWidget(QLabel("Sheet"))
            sheet_line.addWidget(sheet_input, stretch=1)
            sheet_line.addWidget(QLabel("WS变量"))
            sheet_line.addWidget(ws_alias_input)
            layout.addLayout(sheet_line)
        self.bindings_layout.addWidget(row)

    def _bindings_from_inputs(self, inputs):
        bindings = []
        for index, item in enumerate(inputs or []):
            if not isinstance(item, dict):
                continue
            alias = str(item.get("role") or self._default_alias(index)).strip()
            if alias == "current":
                alias = self._default_alias(index)
            bindings.append(
                {
                    "table_name": str(item.get("name") or ""),
                    "alias": alias,
                    "sheet_name": str(item.get("sheet_name") or ""),
                    "ws_alias": str(item.get("ws_alias") or ""),
                    "source_node_id": str(item.get("source_node_id") or ""),
                    "source_output_id": str(item.get("source_output_id") or "out_1"),
                    "data_type": str(item.get("data_type") or "table"),
                }
            )
        return bindings

    def _collect_binding_rows(self):
        bindings = []
        for i in range(self.bindings_layout.count()):
            row = self.bindings_layout.itemAt(i).widget()
            if not row or row.objectName() != "binding_row":
                continue
            table_label = row.findChild(QLabel, "table_name")
            alias_input = row.findChild(QLineEdit, "alias")
            sheet_input = row.findChild(QLineEdit, "sheet_name")
            ws_alias_input = row.findChild(QLineEdit, "ws_alias")
            table_name = table_label.text().strip() if table_label else ""
            if not table_name:
                continue
            alias = alias_input.text().strip() if alias_input else self._default_alias(i)
            sheet_name = sheet_input.text().strip() if sheet_input else ""
            ws_alias = ws_alias_input.text().strip() if ws_alias_input else ""
            if sheet_name and not ws_alias:
                ws_alias = self._default_ws_alias(alias)
            bindings.append(
                {
                    "table_name": table_name,
                    "alias": alias,
                    "sheet_name": sheet_name,
                    "ws_alias": ws_alias,
                    "source_node_id": str(row.property("source_node_id") or ""),
                    "source_output_id": str(row.property("source_output_id") or f"out_{i + 1}"),
                    "data_type": str(row.property("data_type") or "table"),
                }
            )
        return bindings

    def _collect_flow_inputs(self):
        inputs = []
        for index, binding in enumerate(self._collect_binding_rows(), start=1):
            inputs.append(
                {
                    "input_id": f"in_{index}",
                    "source_node_id": binding.get("source_node_id", ""),
                    "source_output_id": binding.get("source_output_id", "out_1"),
                    "name": binding.get("table_name", ""),
                    "role": binding.get("alias") or self._default_alias(index - 1),
                    "data_type": binding.get("data_type", "table"),
                    "enabled": True,
                    "sheet_name": binding.get("sheet_name", ""),
                    "ws_alias": binding.get("ws_alias", ""),
                }
            )
        return inputs

    def _refresh_code_summary(self):
        code = self.code_text or ""
        global_code = self.global_code_text or ""
        code_lines = len(code.splitlines()) if code.strip() else 0
        global_lines = len(global_code.splitlines()) if global_code.strip() else 0
        if not code_lines and not global_lines:
            self.code_summary.setText("未编写代码")
            return
        output_count = len(getattr(self, "_saved_outputs", []) or [])
        output_text = f" · 输出 {output_count} 个" if output_count > 1 else ""
        self.code_summary.setText(f"全局 {global_lines} 行 · 当前 {code_lines} 行{output_text}")

    def _open_code_editor(self):
        node_id = self._bound_node_id or str(self.property("_node_id") or "")
        existing = self._code_editor_dialogs.get(node_id)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dlg = CodeEditorDialog(
            self.code_text,
            self.global_code_text,
            parameters=self._runtime_parameters,
            mappings=self._parameter_mappings,
            parent=self.window(),
        )
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._code_editor_dialogs[node_id] = dlg
        dlg.btn_run.clicked.connect(lambda checked=False, nid=node_id, dialog=dlg: self._run_code_editor(nid, dialog))
        dlg.accepted.connect(lambda nid=node_id, dialog=dlg: self._apply_code_editor_result(nid, dialog))
        dlg.finished.connect(lambda _result, nid=node_id, dialog=dlg: self._on_code_editor_closed(nid, dialog))
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _apply_code_editor_result(self, node_id, dialog):
        code = dialog.code()
        global_code = dialog.global_code()
        if str(node_id or "") == str(self._bound_node_id or ""):
            self.code_text = code
            self.global_code_text = global_code
            self._refresh_code_summary()
        self.global_code_changed.emit(global_code)
        self.code_editor_saved.emit(str(node_id or ""), code, global_code)

    def _run_code_editor(self, node_id, dialog):
        code = dialog.code()
        global_code = dialog.global_code()
        dialog.set_run_status("running", "正在运行当前代码块...")
        if str(node_id or "") == str(self._bound_node_id or ""):
            self.code_text = code
            self.global_code_text = global_code
            self._refresh_code_summary()
        self.global_code_changed.emit(global_code)
        self.code_editor_run_requested.emit(str(node_id or ""), code, global_code)

    def _on_code_editor_closed(self, node_id, dialog):
        if self._code_editor_dialogs.get(node_id) is dialog:
            self._code_editor_dialogs.pop(node_id, None)

    def set_code_editor_running(self, node_id, message="正在运行当前代码块..."):
        dialog = self._code_editor_dialogs.get(str(node_id or ""))
        if dialog is not None and dialog.isVisible():
            dialog.set_run_status("running", message)
        self.code_summary.setText("代码块运行中...")

    def set_code_editor_run_result(self, node_id, success, message=""):
        status = "success" if success else "error"
        dialog = self._code_editor_dialogs.get(str(node_id or ""))
        if dialog is not None and dialog.isVisible():
            dialog.set_run_status(status, message)
        if success:
            self._refresh_code_summary()
        elif message:
            self.code_summary.setText("运行失败")

    def _validate(self):
        ok, widget = super()._validate()
        if not ok:
            return ok, widget
        bindings = self._collect_binding_rows()
        aliases = []
        for binding in bindings:
            alias = binding.get("alias", "")
            if not _valid_alias(alias):
                QMessageBox.warning(
                    self,
                    "变量名无效",
                    f"变量名只能使用英文、数字和下划线，不能以数字开头，也不能使用内置名：{alias}",
                )
                return False, None
            if alias in aliases:
                QMessageBox.warning(self, "变量名重复", f"变量名重复：{alias}")
                return False, None
            aliases.append(alias)
            if binding.get("data_type") == "workbook":
                ws_alias = binding.get("ws_alias", "")
                if binding.get("sheet_name") and not ws_alias:
                    ws_alias = self._default_ws_alias(alias)
                if not ws_alias:
                    continue
                if not _valid_alias(ws_alias):
                    QMessageBox.warning(
                        self,
                        "变量名无效",
                        f"工作表变量名只能使用英文、数字和下划线，不能以数字开头，也不能使用内置名：{ws_alias}",
                    )
                    return False, None
                if ws_alias in aliases:
                    QMessageBox.warning(self, "变量名重复", f"变量名重复：{ws_alias}")
                    return False, None
                aliases.append(ws_alias)
        if not self.code_text.strip():
            QMessageBox.warning(self, "代码为空", "请先点击“编辑代码”编写代码。")
            return False, None
        return True, None
