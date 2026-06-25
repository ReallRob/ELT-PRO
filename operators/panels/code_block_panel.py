"""Panel for the experimental multi-input code block operator."""

import keyword
import re

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
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
    QVBoxLayout,
    QWidget,
)

from core.dataframe_ops.code_block import code_block
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
    "params",
    "mappings",
    "param",
    "dfs",
    "result",
}

LARGE_INPUT_ROWS = 300000
LARGE_INPUT_CELLS = 5000000


def _valid_alias(alias):
    text = str(alias or "").strip()
    return bool(
        text
        and _ALIAS_RE.match(text)
        and not keyword.iskeyword(text)
        and text not in _RESERVED_ALIASES
    )


class CodeEditorDialog(QDialog):
    def __init__(self, code="", parameters=None, mappings=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑代码")
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
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #64748B; font-size: 12px;")

        toolbar.addWidget(btn_param)
        toolbar.addWidget(btn_template)
        toolbar.addStretch(1)
        toolbar.addWidget(self.summary_label)
        layout.addLayout(toolbar)

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(str(code or ""))
        self.editor.setPlaceholderText(
            "df 为第一个输入表；df1/df2 或自定义别名为其他输入表\n"
            "pd、np、re、math、datetime/date/timedelta 已可用\n"
            "把结果赋给 result，或直接修改 df"
        )
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.Monospace)
        self.editor.setFont(font)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.textChanged.connect(self._refresh_summary)
        self.editor.setStyleSheet(
            "QPlainTextEdit { background: #0F172A; color: #E5E7EB; "
            "border: 1px solid #334155; border-radius: 6px; padding: 8px; }"
        )
        layout.addWidget(self.editor, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_summary()

    def code(self):
        return self.editor.toPlainText()

    def _refresh_summary(self):
        code = self.editor.toPlainText()
        lines = 0 if not code else len(code.splitlines())
        self.summary_label.setText(f"{lines} 行 · {len(code)} 字符")

    def _insert_text(self, text):
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _insert_example(self):
        self._insert_text("result = df\n")

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

        input_card, input_inner = self._make_card("输入表配置")
        self.custom_layout.addWidget(input_card)
        self.bindings_layout = QVBoxLayout()
        self.bindings_layout.setSpacing(6)
        input_inner.addLayout(self.bindings_layout)
        self.input_hint = self._make_hint_label("按连线顺序生成 df、df1、df2；变量名可改为 summary、branch 等英文标识。")
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
            self._make_hint_label("代码中默认可用：df、dfs、pd、np、re、math、datetime、date、timedelta、params、mappings、param()。")
        )

        self.code_text = ""
        self._incoming_tables = []
        self._rebuild_binding_rows([])
        self._refresh_code_summary()

    def update_combos(self, table_names):
        self._incoming_tables = list(table_names or [])
        saved = self._collect_input_bindings()
        self._rebuild_binding_rows(self._merge_bindings(self._incoming_tables, saved))

    def clear_custom_ui(self):
        self.timeout_input.setText("10")
        self.code_text = ""
        self._rebuild_binding_rows(self._merge_bindings(self._incoming_tables, []))
        self._refresh_code_summary()

    def set_custom_params(self, p):
        if "timeout_seconds" in p:
            self.timeout_input.setText(str(p.get("timeout_seconds") or "10"))
        self.code_text = str(p.get("code") or "")
        bindings = p.get("input_bindings") or []
        self._rebuild_binding_rows(self._merge_bindings(self._incoming_tables, bindings))
        self._refresh_code_summary()

    def get_custom_params(self):
        return {
            "input_bindings": self._collect_input_bindings(),
            "code": self.code_text,
            "timeout_seconds": self.timeout_input.text().strip() or "10",
        }

    def _default_alias(self, index):
        return "df" if index == 0 else f"df{index}"

    def _merge_bindings(self, table_names, saved_bindings):
        by_table = {}
        for item in saved_bindings or []:
            table_name = str(item.get("table_name") or item.get("df_name") or "").strip()
            if table_name:
                by_table[table_name] = item

        result = []
        for i, table_name in enumerate(table_names or []):
            saved = by_table.get(table_name, {})
            alias = str(saved.get("alias") or self._default_alias(i)).strip()
            result.append(
                {
                    "table_name": table_name,
                    "alias": alias,
                    "primary": i == 0,
                }
            )
        return result

    def _rebuild_binding_rows(self, bindings):
        self.clear_dynamic_layout(self.bindings_layout)
        if not bindings:
            label = QLabel("请先从画布左侧连接至少一个上游数据表。")
            label.setObjectName("empty_inputs")
            label.setWordWrap(True)
            label.setStyleSheet("color: #94A3B8; padding: 8px; border: 1px dashed #CBD5E1; border-radius: 6px;")
            self.bindings_layout.addWidget(label)
            return
        for i, binding in enumerate(bindings):
            self._add_binding_row(i, binding.get("table_name", ""), binding.get("alias", self._default_alias(i)))

    def _add_binding_row(self, index, table_name, alias):
        row = QWidget()
        row.setObjectName("binding_row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        table_label = QLabel(str(table_name or ""))
        table_label.setObjectName("table_name")
        table_label.setToolTip(str(table_name or ""))
        table_label.setStyleSheet("color: #334155; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 5px 7px;")
        alias_input = QLineEdit(str(alias or self._default_alias(index)))
        alias_input.setObjectName("alias")
        alias_input.setPlaceholderText(self._default_alias(index))
        alias_input.setMaximumWidth(120)
        alias_input.setProperty("_param_disabled", True)
        if hasattr(alias_input, "set_parameter_enabled"):
            alias_input.set_parameter_enabled(False)

        tag = QLabel("主表" if index == 0 else "连接表")
        tag.setStyleSheet("color: #64748B; font-size: 11px; border: none;")

        layout.addWidget(tag)
        layout.addWidget(table_label, stretch=1)
        layout.addWidget(QLabel("变量"))
        layout.addWidget(alias_input)
        self.bindings_layout.addWidget(row)

    def _collect_input_bindings(self):
        bindings = []
        for i in range(self.bindings_layout.count()):
            row = self.bindings_layout.itemAt(i).widget()
            if not row or row.objectName() != "binding_row":
                continue
            table_label = row.findChild(QLabel, "table_name")
            alias_input = row.findChild(QLineEdit, "alias")
            table_name = table_label.text().strip() if table_label else ""
            alias = alias_input.text().strip() if alias_input else self._default_alias(i)
            if table_name:
                bindings.append({"table_name": table_name, "alias": alias, "primary": len(bindings) == 0})
        return bindings

    def _refresh_code_summary(self):
        code = self.code_text or ""
        if not code.strip():
            self.code_summary.setText("未编写代码")
            return
        lines = len(code.splitlines())
        self.code_summary.setText(f"已编写 {lines} 行 · {len(code)} 字符")

    def _open_code_editor(self):
        dlg = CodeEditorDialog(
            self.code_text,
            parameters=self._runtime_parameters,
            mappings=self._parameter_mappings,
            parent=self,
        )
        if dlg.exec_() == QDialog.Accepted:
            self.code_text = dlg.code()
            self._refresh_code_summary()

    def _validate(self):
        ok, widget = super()._validate()
        if not ok:
            return ok, widget
        bindings = self._collect_input_bindings()
        if not bindings:
            QMessageBox.warning(self, "参数缺失", "请至少连接一个输入表。")
            return False, None
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
        if "df" not in aliases:
            QMessageBox.warning(self, "缺少 df", "请保留一个输入变量名为 df，作为当前表。")
            return False, None
        if not self.code_text.strip():
            QMessageBox.warning(self, "代码为空", "请先点击“编辑代码”编写代码。")
            return False, None
        return True, None

    def _confirm_large_input(self, tables):
        total_rows = sum(len(df) for df in tables.values())
        total_cells = sum(df.shape[0] * df.shape[1] for df in tables.values())
        if total_rows <= LARGE_INPUT_ROWS and total_cells <= LARGE_INPUT_CELLS:
            return True
        reply = QMessageBox.question(
            self,
            "代码块输入较大",
            "代码块会把输入表发送到独立 Python 进程执行。\n"
            f"当前输入约 {total_rows:,} 行、{total_cells:,} 个单元格，可能明显变慢并占用更多内存。\n\n"
            "是否继续执行？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def execute(self):
        p = self.get_params()
        ok, _ = self._validate()
        if not ok:
            return
        out_name = p.get("out_name") or "代码块结果"
        try:
            tables = {}
            for binding in p["input_bindings"]:
                table_name = binding.get("table_name")
                alias = binding.get("alias")
                if table_name not in self.data_pool:
                    raise ValueError(f"输入表不存在: {table_name}")
                tables[alias] = self.data_pool[table_name]
            if not self._confirm_large_input(tables):
                return
            df = code_block(
                tables,
                p.get("code", ""),
                self._runtime_parameters,
                self._parameter_mappings,
                p.get("timeout_seconds", 10),
            )
            self.step_recorded.emit("code_block", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))
