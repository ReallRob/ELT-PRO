"""Panel for the experimental multi-input code block operator."""

import copy
import traceback
import keyword
import re

from PyQt5.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.dataframe_ops.code_exec import PRESET_IMPORT_SNIPPET
from core.packaging.dependency_manifest import bundled_import_roots_text
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
    "should_cancel",
    "check_cancel",
}
def _valid_alias(alias):
    text = str(alias or "").strip()
    return bool(
        text
        and _ALIAS_RE.match(text)
        and not keyword.iskeyword(text)
        and text not in _RESERVED_ALIASES
    )


def _valid_function_reference_name(alias):
    text = str(alias or "").strip()
    return _valid_alias(text)


def _default_function_space(code=""):
    return {
        "id": "legacy_global",
        "name": "旧全局函数",
        "namespace": "global_funcs",
        "enabled": True,
        "expose_globals": True,
        "code": str(code or ""),
    }


def _new_function_space(index=1):
    return {
        "id": f"space_{index}",
        "name": f"函数空间{index}",
        "namespace": f"funcs{index}",
        "enabled": True,
        "expose_globals": False,
        "code": "",
    }


def _normalize_function_spaces(function_spaces=None, legacy_global_code=""):
    spaces = []
    for index, item in enumerate(function_spaces or [], start=1):
        if not isinstance(item, dict):
            continue
        namespace = str(item.get("namespace") or item.get("id") or f"funcs{index}").strip()
        if not namespace or not _valid_function_reference_name(namespace):
            namespace = f"funcs{index}"
        spaces.append(
            {
                "id": str(item.get("id") or namespace or f"space_{index}"),
                "name": str(item.get("name") or namespace or f"函数空间{index}"),
                "namespace": namespace,
                "enabled": bool(item.get("enabled", True)),
                "expose_globals": bool(item.get("expose_globals", False)),
                "code": str(item.get("code") or ""),
            }
        )
    if not spaces and str(legacy_global_code or "").strip():
        spaces.append(_default_function_space(legacy_global_code))
    if not spaces:
        spaces.append(_new_function_space(1))
    return spaces


def _function_names_from_code(code):
    return re.findall(r"^\s*def\s+([A-Za-z_]\w*)\s*\(", str(code or ""), flags=re.MULTILINE)


class PythonSyntaxHighlighter(QSyntaxHighlighter):
    """Lightweight Python syntax highlighting for code block editors."""

    _KEYWORDS = (
        "and", "as", "assert", "async", "await", "break", "class", "continue",
        "def", "del", "elif", "else", "except", "finally", "for", "from", "global",
        "if", "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass",
        "raise", "return", "try", "while", "with", "yield",
    )
    _BUILTINS = (
        "abs", "all", "any", "bool", "callable", "dict", "enumerate", "filter",
        "float", "getattr", "hasattr", "int", "isinstance", "len", "list", "map",
        "max", "min", "next", "object", "print", "range", "repr", "round", "set",
        "sorted", "str", "sum", "tuple", "type", "zip",
    )
    _EXCEPTIONS = (
        "AssertionError", "AttributeError", "Exception", "ImportError", "IndexError",
        "KeyError", "NameError", "RuntimeError", "SyntaxError", "TypeError", "ValueError",
    )
    _PRESET_NAMES = (
        "pd", "np", "re", "math", "datetime", "date", "timedelta", "openpyxl",
        "copy", "deepcopy", "get_column_letter", "params", "mappings", "param", "state",
        "dfs", "df", "wbs", "wb", "wss", "ws", "should_cancel", "check_cancel",
    )
    _COMMENT_RE = re.compile(r"#.*")
    _SINGLE_QUOTED_STRING_RE = re.compile(r"'(?:\\.|[^'\\\n])*'")
    _DOUBLE_QUOTED_STRING_RE = re.compile(r'"(?:\\.|[^"\\\n])*"')
    _NUMBER_RE = re.compile(
        r"(?<![\w.])(?:0[xX][0-9A-Fa-f]+|0[bB][01]+|0[oO][0-7]+|(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?j?)(?!\w)"
    )
    _DECORATOR_RE = re.compile(r"(?<!\w)@[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
    _FUNCTION_NAME_RE = re.compile(r"\bdef\s+([A-Za-z_]\w*)")
    _CLASS_NAME_RE = re.compile(r"\bclass\s+([A-Za-z_]\w*)")

    def __init__(self, document):
        super().__init__(document)
        self._formats = {
            "keyword": self._make_format("#C084FC", bold=True),
            "builtin": self._make_format("#67E8F9"),
            "exception": self._make_format("#FCA5A5"),
            "preset": self._make_format("#7DD3FC"),
            "string": self._make_format("#A7F3D0"),
            "comment": self._make_format("#94A3B8", italic=True),
            "number": self._make_format("#FCD34D"),
            "decorator": self._make_format("#F9A8D4"),
            "definition": self._make_format("#93C5FD", bold=True),
            "constant": self._make_format("#FDE68A", bold=True),
        }
        self._word_rules = (
            (self._compile_words(self._KEYWORDS), self._formats["keyword"]),
            (self._compile_words(self._BUILTINS), self._formats["builtin"]),
            (self._compile_words(self._EXCEPTIONS), self._formats["exception"]),
            (self._compile_words(self._PRESET_NAMES), self._formats["preset"]),
            (re.compile(r"\b(?:True|False|None)\b"), self._formats["constant"]),
        )

    @staticmethod
    def _make_format(color, bold=False, italic=False):
        text_format = QTextCharFormat()
        text_format.setForeground(QColor(color))
        if bold:
            text_format.setFontWeight(QFont.Bold)
        if italic:
            text_format.setFontItalic(True)
        return text_format

    @staticmethod
    def _compile_words(words):
        return re.compile(r"\b(?:" + "|".join(re.escape(word) for word in words) + r")\b")

    def _apply_matches(self, pattern, text, text_format, group=0):
        for match in pattern.finditer(text):
            start, end = match.span(group)
            self.setFormat(start, end - start, text_format)

    def _highlight_multiline_string(self, text, delimiter, state):
        if self.previousBlockState() == state:
            start = 0
        else:
            start = text.find(delimiter)

        while start >= 0:
            end = text.find(delimiter, start + len(delimiter))
            if end < 0:
                self.setCurrentBlockState(state)
                self.setFormat(start, len(text) - start, self._formats["string"])
                return
            end += len(delimiter)
            self.setFormat(start, end - start, self._formats["string"])
            start = text.find(delimiter, end)

    def highlightBlock(self, text):
        self.setCurrentBlockState(0)
        for pattern, text_format in self._word_rules:
            self._apply_matches(pattern, text, text_format)
        self._apply_matches(self._NUMBER_RE, text, self._formats["number"])
        self._apply_matches(self._DECORATOR_RE, text, self._formats["decorator"])
        self._apply_matches(self._FUNCTION_NAME_RE, text, self._formats["definition"], group=1)
        self._apply_matches(self._CLASS_NAME_RE, text, self._formats["definition"], group=1)

        # Comments are formatted before strings so a hash inside a string remains a string.
        self._apply_matches(self._COMMENT_RE, text, self._formats["comment"])
        self._apply_matches(self._SINGLE_QUOTED_STRING_RE, text, self._formats["string"])
        self._apply_matches(self._DOUBLE_QUOTED_STRING_RE, text, self._formats["string"])

        if self.previousBlockState() == 1:
            self._highlight_multiline_string(text, "'''", 1)
        elif self.previousBlockState() == 2:
            self._highlight_multiline_string(text, '\"\"\"', 2)
        else:
            self._highlight_multiline_string(text, "'''", 1)
            if self.currentBlockState() != 1:
                self._highlight_multiline_string(text, '\"\"\"', 2)


class _CodeLineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor._paint_line_number_area(event)


class PythonCodeEditor(QPlainTextEdit):
    INDENT = "    "

    def __init__(self, parent=None):
        super().__init__(parent)
        self.syntax_highlighter = PythonSyntaxHighlighter(self.document())
        self._line_number_area = _CodeLineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_area_width(0)

    def line_number_area_width(self):
        digits = max(1, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().width("9") * digits

    def setFont(self, font):
        super().setFont(font)
        if hasattr(self, "_line_number_area"):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(contents.left(), contents.top(), self.line_number_area_width(), contents.height())
        )

    def _update_line_number_area_width(self, _block_count):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def _paint_line_number_area(self, event):
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#111827"))
        painter.setPen(QColor("#94A3B8"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        line_height = self.fontMetrics().height()
        width = self._line_number_area.width() - 6

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(0, top, width, line_height, Qt.AlignRight, str(block_number + 1))
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

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
    def __init__(
        self,
        code="",
        global_code="",
        function_spaces=None,
        input_refs=None,
        parameters=None,
        mappings=None,
        execution_mode="inline",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("编辑代码")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setSizeGripEnabled(True)
        self.resize(1080, 640)
        self._runtime_parameters = parameters or {}
        self._parameter_mappings = mappings or {}
        self._input_refs = [item for item in (input_refs or []) if isinstance(item, dict)]
        self._function_spaces = _normalize_function_spaces(function_spaces, global_code)
        self._execution_mode = "process" if str(execution_mode or "").strip().lower() == "process" else "inline"
        self._current_space_index = 0
        self._loading_space = False

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
        btn_check = QPushButton("检查函数库")
        btn_check.clicked.connect(self._check_function_spaces)
        self.process_mode_checkbox = QCheckBox("独立进程运行")
        self.process_mode_checkbox.setChecked(self._execution_mode == "process")
        self.process_mode_checkbox.setToolTip(
            "适合 PyQt 窗口或阻塞脚本。独立进程可读取参数，但不支持内存 Workbook 输入。"
        )
        self.btn_run = QPushButton("运行")
        self.btn_run.setObjectName("primary_execute")
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #64748B; font-size: 12px;")
        self.run_status_label = QLabel("")
        self.run_status_label.setWordWrap(True)
        self.run_status_label.setMinimumHeight(20)
        self.run_status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.run_status_label.hide()
        self._last_run_detail = ""
        self.run_status_container = self._build_run_status_container()
 
        toolbar.addWidget(btn_param)
        toolbar.addWidget(btn_template)
        toolbar.addWidget(btn_check)
        toolbar.addWidget(self.process_mode_checkbox)
        toolbar.addWidget(self.btn_run)
        toolbar.addWidget(self.btn_stop)
        toolbar.addStretch(1)
        toolbar.addWidget(self.summary_label)
        layout.addLayout(toolbar)
        layout.addWidget(self.run_status_container)

        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.Monospace)
        self.tabs = QTabWidget()
        self.editor = self._make_editor(
            code,
            "当前代码块可以直接写脚本；只有显式 return 才会产生正式输出。\n"
            "推荐：return df 或 return {'明细表': df}\n"
            "没有 return 时允许运行，但不会给下游节点提供输出。"
        )
        self.editor.setFont(font)
        self.current_page = self._build_current_code_page()
        self.function_page = self._build_function_page(font)
        self.help_page = self._build_help_page()
        self.tabs.addTab(self.current_page, "当前代码")
        self.tabs.addTab(self.function_page, "函数库")
        self.tabs.addTab(self.help_page, "说明")
        self.tabs.setCurrentWidget(self.current_page)
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
        return ""

    def function_spaces(self):
        self._save_current_space()
        return copy.deepcopy(self._function_spaces)

    def execution_mode(self):
        return "process" if self.process_mode_checkbox.isChecked() else "inline"

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

    def _make_readonly_panel(self, text):
        panel = QPlainTextEdit(str(text or ""))
        panel.setReadOnly(True)
        panel.setLineWrapMode(QPlainTextEdit.NoWrap)
        panel.setStyleSheet(
            "QPlainTextEdit { background: #F8FAFC; color: #334155; "
            "border: 1px solid #E2E8F0; border-radius: 6px; padding: 8px; font-size: 12px; }"
        )
        return panel

    def _build_help_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget()
        layout = QHBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        output_examples = (
            "return df\n"
            "return {'明细': df, '汇总': summary_df}\n"
            "return wb\n"
            "return {'模板': wb}\n"
            "return {'总数': len(df), '状态': '完成'}"
        )
        runtime_status_examples = (
            "# state 是代码块自动提供的运行状态\n"
            "# 可读取 state['run_status']，通常为 'running' 或 'stopped'\n"
            "\n"
            "for item in rows:\n"
            "    if should_cancel():\n"
            "        return\n"
            "    process(item)\n"
            "\n"
            "# 长循环内也可直接调用：\n"
            "check_cancel()  # 已停止时立即中断代码块\n"
            "\n"
            "# 运行状态由系统维护，请不要修改 state['run_status']"
        )
        left_layout.addWidget(
            self._assist_group(
                "当前输入",
                self._input_info_text(),
                insertable=False,
                min_height=110,
                max_height=180,
            )
        )
        left_layout.addWidget(
            self._assist_group(
                "输出写法",
                output_examples,
                insertable=True,
                min_height=120,
                max_height=190,
            )
        )
        left_layout.addWidget(
            self._assist_group(
                "运行状态",
                runtime_status_examples,
                insertable=True,
                min_height=150,
                max_height=220,
            )
        )
        left_layout.addStretch(1)

        right_layout.addWidget(
            self._assist_group(
                "已预置库",
                PRESET_IMPORT_SNIPPET,
                insertable=True,
                min_height=160,
                max_height=230,
            )
        )
        right_layout.addWidget(
            self._assist_group(
                "打包预收集库",
                bundled_import_roots_text(),
                insertable=False,
                min_height=120,
                max_height=190,
            )
        )
        right_layout.addWidget(
            self._assist_group(
                "函数库导入",
                "将函数空间的“引用名称”填写为 fun 后：\n\n"
                "from fun import *\n"
                "# 或 import fun as helpers",
                insertable=True,
                min_height=100,
                max_height=150,
            )
        )
        right_layout.addStretch(1)

        layout.addWidget(left, stretch=1)
        layout.addWidget(right, stretch=1)
        scroll.setWidget(content)
        return scroll

    def _assist_group(self, title, text, insertable=False, min_height=78, max_height=150):
        box = QFrame()
        box.setObjectName("assist_group")
        box.setStyleSheet(
            "QFrame#assist_group { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; }"
            "QLabel#assist_title { color: #334155; font-weight: bold; border: none; }"
            "QPushButton { padding: 3px 8px; min-height: 22px; }"
        )
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title_label = QLabel(title)
        title_label.setObjectName("assist_title")
        header.addWidget(title_label)
        header.addStretch(1)
        if insertable:
            btn_insert = QPushButton("插入")
            btn_insert.clicked.connect(lambda checked=False, value=text: self._insert_text(str(value) + "\n"))
            header.addWidget(btn_insert)
        btn_copy = QPushButton("复制")
        btn_copy.clicked.connect(lambda checked=False, value=text: QApplication.clipboard().setText(str(value)))
        header.addWidget(btn_copy)
        layout.addLayout(header)
        body = QPlainTextEdit(str(text or ""))
        body.setReadOnly(True)
        body.setLineWrapMode(QPlainTextEdit.NoWrap)
        body.setMinimumHeight(min_height)
        body.setMaximumHeight(max_height)
        body.setStyleSheet(
            "QPlainTextEdit { background: #FFFFFF; color: #1F2937; "
            "border: 1px solid #E5E7EB; border-radius: 5px; padding: 6px; font-family: Consolas; }"
        )
        layout.addWidget(body)
        return box

    def _input_info_text(self):
        lines = []
        for item in self._input_refs:
            name = str(item.get("name") or "输入")
            role = str(item.get("role") or "")
            data_type = str(item.get("data_type") or "table")
            alias = role or ("wb" if data_type == "workbook" else "df")
            type_label = "Workbook" if data_type == "workbook" else "DataFrame"
            lines.append(f"{alias}  # {type_label}: {name}")
        if lines:
            return "\n".join(lines)
        return "暂无输入\n可以只运行脚本；需要给下游节点时，请显式 return DataFrame/Workbook 或普通值。"

    def _build_current_code_page(self):
        return self.editor

    def _build_function_page(self, font):
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        self.space_list = QListWidget()
        self.space_list.currentRowChanged.connect(self._on_space_selected)
        btn_add = QPushButton("新建空间")
        btn_add.clicked.connect(self._add_space)
        btn_delete = QPushButton("删除空间")
        btn_delete.clicked.connect(self._delete_space)
        left_layout.addWidget(self.space_list, stretch=1)
        left_layout.addWidget(btn_add)
        left_layout.addWidget(btn_delete)

        middle = QWidget()
        mid_layout = QVBoxLayout(middle)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        mid_layout.setSpacing(6)
        form = QFormLayout()
        self.space_name_input = QLineEdit()
        self.space_namespace_input = QLineEdit()
        self.space_namespace_input.setPlaceholderText("例如 fun 或 text_utils")
        self.space_namespace_input.setToolTip(
            "用于引用函数空间。填写 fun 后，可写 from fun import * 或 fun.函数名(...)。"
        )
        self.space_enabled_checkbox = QCheckBox("启用")
        self.space_expose_checkbox = QCheckBox("允许直接调用函数")
        self.space_expose_checkbox.setToolTip(
            "启用后可在当前代码中直接写函数名(...)；关闭后请使用引用名称调用。"
        )
        self.space_name_input.textChanged.connect(self._on_space_meta_changed)
        self.space_namespace_input.textChanged.connect(self._on_space_meta_changed)
        self.space_enabled_checkbox.toggled.connect(self._on_space_meta_changed)
        self.space_expose_checkbox.toggled.connect(self._on_space_meta_changed)
        form.addRow("空间名称:", self.space_name_input)
        form.addRow("引用名称:", self.space_namespace_input)
        form.addRow("状态:", self.space_enabled_checkbox)
        form.addRow("直接引用:", self.space_expose_checkbox)
        self.space_editor = self._make_editor("", "在这里编写当前函数空间的函数。函数内部可以 return，顶层不要直接 return。")
        self.space_editor.setFont(font)
        self.space_editor.textChanged.connect(self._refresh_function_list)
        self.global_editor = self.space_editor
        mid_layout.addLayout(form)
        mid_layout.addWidget(self.space_editor, stretch=1)

        self.function_list_panel = self._make_readonly_panel("")
        outer.addWidget(left, stretch=1)
        outer.addWidget(middle, stretch=3)
        outer.addWidget(self.function_list_panel, stretch=1)
        self._refresh_space_list()
        return page

    def _refresh_summary(self):
        code = self.editor.toPlainText()
        code_lines = 0 if not code else len(code.splitlines())
        space_lines = sum(len(str(space.get("code") or "").splitlines()) for space in getattr(self, "_function_spaces", []) or [])
        space_count = len(getattr(self, "_function_spaces", []) or [])
        self.summary_label.setText(f"函数空间 {space_count} 个 / {space_lines} 行 · 当前 {code_lines} 行")

    def _space_label(self, space):
        enabled = "✓" if space.get("enabled", True) else "○"
        name = str(space.get("name") or "函数空间")
        namespace = str(space.get("namespace") or "")
        return f"{enabled} {name}\n{namespace}"

    def _refresh_space_list(self):
        if not hasattr(self, "space_list"):
            return
        current = max(0, min(self._current_space_index, len(self._function_spaces) - 1))
        self.space_list.blockSignals(True)
        self.space_list.clear()
        for space in self._function_spaces:
            item = QListWidgetItem(self._space_label(space))
            item.setToolTip(str(space.get("namespace") or ""))
            self.space_list.addItem(item)
        self.space_list.setCurrentRow(current if self._function_spaces else -1)
        self.space_list.blockSignals(False)
        self._load_space(current)

    def _save_current_space(self):
        if self._loading_space or not hasattr(self, "space_editor"):
            return
        if not self._function_spaces:
            return
        index = max(0, min(self._current_space_index, len(self._function_spaces) - 1))
        space = self._function_spaces[index]
        namespace = self.space_namespace_input.text().strip() or str(space.get("namespace") or f"funcs{index + 1}")
        if not _valid_function_reference_name(namespace):
            namespace = str(space.get("namespace") or f"funcs{index + 1}")
        if not _valid_function_reference_name(namespace):
            namespace = f"funcs{index + 1}"
        space["name"] = self.space_name_input.text().strip() or f"函数空间{index + 1}"
        space["namespace"] = namespace
        space["enabled"] = self.space_enabled_checkbox.isChecked()
        space["expose_globals"] = self.space_expose_checkbox.isChecked()
        space["code"] = self.space_editor.toPlainText()

    def _load_space(self, index):
        if not self._function_spaces or not hasattr(self, "space_editor"):
            return
        index = max(0, min(index, len(self._function_spaces) - 1))
        self._current_space_index = index
        space = self._function_spaces[index]
        self._loading_space = True
        self.space_name_input.setText(str(space.get("name") or f"函数空间{index + 1}"))
        self.space_namespace_input.setText(str(space.get("namespace") or f"funcs{index + 1}"))
        self.space_enabled_checkbox.setChecked(bool(space.get("enabled", True)))
        self.space_expose_checkbox.setChecked(bool(space.get("expose_globals", False)))
        self.space_editor.setPlainText(str(space.get("code") or ""))
        self.space_editor.document().setModified(False)
        self._loading_space = False
        self._refresh_function_list()

    def _on_space_selected(self, index):
        if index < 0 or self._loading_space:
            return
        self._save_current_space()
        self._load_space(index)

    def _on_space_meta_changed(self):
        if self._loading_space:
            return
        self._save_current_space()
        row = self.space_list.currentRow() if hasattr(self, "space_list") else -1
        if row >= 0 and row < self.space_list.count():
            self.space_list.item(row).setText(self._space_label(self._function_spaces[row]))
        self._refresh_summary()

    def _add_space(self):
        self._save_current_space()
        self._function_spaces.append(_new_function_space(len(self._function_spaces) + 1))
        self._current_space_index = len(self._function_spaces) - 1
        self._refresh_space_list()
        self._refresh_summary()

    def _delete_space(self):
        if len(self._function_spaces) <= 1:
            QMessageBox.information(self, "无法删除", "至少保留一个函数空间。")
            return
        row = self.space_list.currentRow() if hasattr(self, "space_list") else self._current_space_index
        row = max(0, min(row, len(self._function_spaces) - 1))
        self._function_spaces.pop(row)
        self._current_space_index = max(0, row - 1)
        self._refresh_space_list()
        self._refresh_summary()

    def _refresh_function_list(self):
        if self._loading_space:
            return
        self._save_current_space()
        if not hasattr(self, "function_list_panel"):
            return
        index = max(0, min(self._current_space_index, len(self._function_spaces) - 1))
        space = self._function_spaces[index] if self._function_spaces else {}
        namespace = str(space.get("namespace") or "funcs")
        names = _function_names_from_code(space.get("code") or "")
        lines = ["函数列表"]
        if names:
            lines.extend(f"{namespace}.{name}(...)" for name in names)
        else:
            lines.append("暂无 def 函数")
        lines.append("\n调用建议")
        lines.append(f"{namespace}.函数名(...)")
        lines.append(f"from {namespace} import *")
        self.function_list_panel.setPlainText("\n".join(lines))
        self._refresh_summary()

    def _check_function_spaces(self):
        self._save_current_space()
        errors = []
        namespaces = set()
        for index, space in enumerate(self._function_spaces or [], start=1):
            namespace = str(space.get("namespace") or "").strip()
            label = str(space.get("name") or f"函数空间{index}")
            if not _valid_function_reference_name(namespace):
                errors.append(f"{label}: 引用名称无效 {namespace!r}")
            elif namespace in namespaces:
                errors.append(f"{label}: 命名空间重复 {namespace}")
            namespaces.add(namespace)
            code = str(space.get("code") or "")
            if code.strip():
                try:
                    compile(code, f"<函数空间:{namespace or index}>", "exec")
                except Exception:
                    errors.append(f"{label}:\n{traceback.format_exc(limit=1).strip()}")
        if errors:
            self.set_run_status("error", "函数库检查失败：\n" + "\n".join(errors))
        else:
            self.set_run_status("success", f"函数库检查通过，共 {len(self._function_spaces or [])} 个空间。")

    def _build_run_status_container(self):
        container = QFrame()
        container.setVisible(False)
        container.setObjectName("run_status_container")
        container.setMinimumHeight(36)
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(6)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.run_status_label, stretch=1)
        self.btn_toggle_error = QPushButton("详情")
        self.btn_toggle_error.clicked.connect(self._toggle_error_detail)
        self.btn_copy_error = QPushButton("复制详情")
        self.btn_copy_error.clicked.connect(self._copy_error_detail)
        row.addWidget(self.btn_toggle_error)
        row.addWidget(self.btn_copy_error)
        layout.addLayout(row)
        self.error_detail_box = QPlainTextEdit()
        self.error_detail_box.setReadOnly(True)
        self.error_detail_box.setMaximumHeight(280)
        self.error_detail_box.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.error_detail_box.setVisible(False)
        self.error_detail_box.setStyleSheet(
            "QPlainTextEdit { background: #FFF7F7; color: #991B1B; "
            "border: 1px solid #FECACA; border-radius: 6px; padding: 8px; font-family: Consolas; }"
        )
        layout.addWidget(self.error_detail_box)
        self.run_log_box = QPlainTextEdit()
        self.run_log_box.setReadOnly(True)
        self.run_log_box.setMaximumHeight(240)
        self.run_log_box.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.run_log_box.setPlaceholderText("print 输出会实时显示在这里")
        self.run_log_box.setVisible(False)
        self.run_log_box.setStyleSheet(
            "QPlainTextEdit { background: #0F172A; color: #D1FAE5; "
            "border: 1px solid #334155; border-radius: 6px; padding: 8px; font-family: Consolas; }"
        )
        layout.addWidget(self.run_log_box)
        self.btn_toggle_error.hide()
        self.btn_copy_error.hide()
        return container

    def _error_summary(self, detail):
        lines = [line.strip() for line in str(detail or "").splitlines() if line.strip()]
        if not lines:
            return "运行失败"
        for line in reversed(lines):
            if re.match(r"^[A-Za-z_][\w.]*Error[:：]", line) or line.startswith(("NameError", "ValueError", "TypeError", "SyntaxError")):
                return line
        return lines[-1] if len(lines[-1]) <= 160 else lines[-1][:157] + "..."

    def _toggle_error_detail(self):
        visible = not self.error_detail_box.isVisible()
        self.error_detail_box.setVisible(visible)
        self.btn_toggle_error.setText("收起" if visible else "详情")

    def _copy_error_detail(self):
        QApplication.clipboard().setText(self._last_run_detail or self.run_status_label.text())

    def clear_run_log(self):
        if not hasattr(self, "run_log_box"):
            return
        self.run_log_box.clear()
        self.run_log_box.setVisible(False)

    def append_run_log(self, message):
        if not hasattr(self, "run_log_box"):
            return
        text = str(message or "")
        if not text:
            return
        self.run_status_container.setVisible(True)
        self.run_log_box.setVisible(True)
        self.run_log_box.appendPlainText(text)
        cursor = self.run_log_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.run_log_box.setTextCursor(cursor)
        self.run_log_box.updateGeometry()
        self.run_status_container.updateGeometry()

    def set_run_status(self, status, message=""):
        text = str(message or "").strip()
        styles = {
            "running": (
                "QFrame#run_status_container { background: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 6px; }"
                "QLabel { color: #1D4ED8; border: none; background: transparent; }"
            ),
            "stopping": (
                "QFrame#run_status_container { background: #FFFBEB; border: 1px solid #FDE68A; border-radius: 6px; }"
                "QLabel { color: #92400E; border: none; background: transparent; }"
            ),
            "stopped": (
                "QFrame#run_status_container { background: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; }"
                "QLabel { color: #475569; border: none; background: transparent; }"
            ),
            "success": (
                "QFrame#run_status_container { background: #ECFDF5; border: 1px solid #A7F3D0; border-radius: 6px; }"
                "QLabel { color: #047857; border: none; background: transparent; }"
            ),
            "error": (
                "QFrame#run_status_container { background: #FEF2F2; border: 1px solid #FECACA; border-radius: 6px; }"
                "QLabel { color: #B91C1C; border: none; background: transparent; }"
            ),
            "info": (
                "QFrame#run_status_container { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; }"
                "QLabel { color: #475569; border: none; background: transparent; }"
            ),
        }
        status = str(status or "info")
        if status == "running":
            self.clear_run_log()
        is_error = status == "error"
        self._last_run_detail = text if is_error else ""
        display_text = self._error_summary(text) if is_error else text
        has_log = hasattr(self, "run_log_box") and bool(self.run_log_box.toPlainText())
        self.run_status_container.setVisible(bool(text) or has_log)
        self.run_status_label.setVisible(bool(text))
        self.run_status_label.setText(display_text)
        self.run_status_container.setStyleSheet(styles.get(str(status or "info"), styles["info"]))
        self.btn_toggle_error.setVisible(is_error and bool(text))
        self.btn_copy_error.setVisible(is_error and bool(text))
        self.error_detail_box.setPlainText(text)
        detail_visible = is_error and bool(text)
        self.error_detail_box.setVisible(detail_visible)
        self.btn_toggle_error.setText("收起" if detail_visible else "详情")
        is_running = status == "running"
        is_stopping = status == "stopping"
        self.btn_run.setEnabled(not (is_running or is_stopping))
        if hasattr(self, "btn_stop"):
            self.btn_stop.setEnabled(is_running)
        self.run_status_label.updateGeometry()
        self.run_status_container.updateGeometry()

    def _insert_text(self, text):
        editor = self.space_editor if hasattr(self, "tabs") and self.tabs.currentWidget() is getattr(self, "function_page", None) else self.editor
        cursor = editor.textCursor()
        cursor.insertText(text)
        editor.setTextCursor(cursor)
        editor.setFocus()

    def _insert_example(self):
        if self.tabs.currentWidget() is getattr(self, "function_page", None):
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
        if params:
            for name in params:
                action = menu.addAction(f"params[{name!r}]")
                action.triggered.connect(lambda checked=False, n=name: self._insert_text(f"params[{n!r}]"))
        else:
            action = menu.addAction("暂无可用参数")
            action.setEnabled(False)
        menu.exec_(self.mapToGlobal(self.rect().topLeft()))


class CodeBlockPanel(BaseToolPanel):
    global_code_changed = pyqtSignal(str)
    function_spaces_changed = pyqtSignal(object)
    code_editor_saved = pyqtSignal(str, str, str)
    code_editor_saved_with_spaces = pyqtSignal(str, str, str, object, str)
    code_editor_run_requested = pyqtSignal(str, str, str)
    code_editor_run_requested_with_spaces = pyqtSignal(str, str, str, object, str)
    code_editor_stop_requested = pyqtSignal(str)
    use_df = False
    use_type = False
    theme_color = "#7C3AED"
    action_name = "代码块"

    def init_custom_ui(self):
        self.timeout_input = QLineEdit("10")
        self.timeout_input.hide()
        self.execution_mode = "inline"

        input_card, input_inner = self._make_card("输入配置")
        self.custom_layout.addWidget(input_card)
        self.bindings_layout = QVBoxLayout()
        self.bindings_layout.setSpacing(6)
        input_inner.addLayout(self.bindings_layout)
        self.input_hint = self._make_hint_label(
            "输入彼此同级；数据表默认生成 df、df1，模板默认生成 wb、wb1。"
            "需要工作表时可在代码中写 ws = wb.active 或 ws = wb['Sheet名']；"
            "代码块在线程内执行，停止按钮会将 state['run_status'] 设为 'stopped'；"
            "长循环请判断 state.get('run_status') 或定期调用 check_cancel()；有下游节点时必须显式 return。"
        )
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
        btn_edit.setObjectName("edit_code_button")
        btn_edit.setMinimumHeight(32)
        btn_edit.setToolTip("打开代码编辑窗口")
        btn_edit.setStyleSheet(
            "QPushButton#edit_code_button { background: #2563EB; color: #FFFFFF; "
            "border: 1px solid #2563EB; border-radius: 6px; padding: 5px 14px; font-weight: 600; }"
            "QPushButton#edit_code_button:hover { background: #1D4ED8; border-color: #1D4ED8; }"
            "QPushButton#edit_code_button:pressed { background: #1E40AF; border-color: #1E40AF; }"
            "QPushButton#edit_code_button:disabled { background: #CBD5E1; border-color: #CBD5E1; color: #64748B; }"
        )
        btn_edit.clicked.connect(self._open_code_editor)
        row.addWidget(self.code_summary, stretch=1)
        row.addWidget(btn_edit)
        code_inner.addLayout(row)
        code_inner.addWidget(
            self._make_hint_label("代码编辑窗口的“说明”页会显示当前输入、已预置库、支持 import 和输出写法。只有显式 return 会成为正式输出。")
        )

        outputs_card, outputs_inner = self._make_card("输出摘要")
        self.custom_layout.addWidget(outputs_card)
        self.outputs_layout = QVBoxLayout()
        self.outputs_layout.setSpacing(6)
        outputs_inner.addLayout(self.outputs_layout)
        outputs_inner.addWidget(
            self._make_hint_label("运行后会显示真实输出列表；多输出时可在这里修改每个输出显示名称。")
        )
 
        self.code_text = ""
        self.global_code_text = ""
        self.function_spaces_data = []
        self._saved_outputs = []
        self._incoming_tables = []
        self._incoming_items = []
        self._incoming_outputs = []
        self._bound_node_id = ""
        self._code_editor_dialogs = {}
        self._rebuild_binding_rows([])
        self._rebuild_output_rows([])
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
        self.execution_mode = "inline"
        self.code_text = ""
        self._saved_outputs = []
        self._rebuild_output_rows([])
        self._rebuild_binding_rows(self._merge_bindings(self._incoming_items, []))
        self._refresh_code_summary()

    def set_global_code(self, global_code=""):
        self.global_code_text = str(global_code or "")
        if not self.function_spaces_data and self.global_code_text.strip():
            self.function_spaces_data = _normalize_function_spaces([], self.global_code_text)
        for dialog in list(getattr(self, "_code_editor_dialogs", {}).values()):
            if dialog is None or not dialog.isVisible():
                continue
            # Open dialogs keep their own unsaved edits until Save/Run.
        self._refresh_code_summary()

    def set_function_spaces(self, function_spaces=None):
        self.function_spaces_data = _normalize_function_spaces(function_spaces, self.global_code_text)
        self._refresh_code_summary()

    def set_bound_node_id(self, node_id=""):
        self._bound_node_id = str(node_id or "")

    def set_custom_params(self, p):
        if "timeout_seconds" in p:
            self.timeout_input.setText(str(p.get("timeout_seconds") or "10"))
        self.execution_mode = "process" if str(p.get("execution_mode") or "").strip().lower() == "process" else "inline"
        self.code_text = str(p.get("code") or "")
        self._saved_outputs = copy.deepcopy([item for item in p.get("outputs") or [] if isinstance(item, dict)])
        self._rebuild_output_rows(self._saved_outputs)
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
            "execution_mode": self.execution_mode,
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
        row_outputs = self._collect_output_rows()
        if len(row_outputs) > 1:
            return row_outputs
        if len(self._saved_outputs) > 1:
            return row_outputs or copy.deepcopy(self._saved_outputs)
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
        self._rebuild_output_rows(self._saved_outputs)
        self._refresh_code_summary()

    def _collect_output_rows(self):
        outputs = []
        if not hasattr(self, "outputs_layout"):
            return outputs
        for index in range(self.outputs_layout.count()):
            row = self.outputs_layout.itemAt(index).widget()
            if not row or row.objectName() != "output_row":
                continue
            name_input = row.findChild(QLineEdit, "output_name")
            output_id = str(row.property("output_id") or f"out_{len(outputs) + 1}")
            data_type = str(row.property("data_type") or "table")
            name = name_input.text().strip() if name_input else ""
            outputs.append({"output_id": output_id, "name": name or f"代码块结果{len(outputs) + 1}", "data_type": data_type})
        return outputs

    def _rebuild_output_rows(self, outputs):
        if not hasattr(self, "outputs_layout"):
            return
        self.clear_dynamic_layout(self.outputs_layout)
        normalized = [item for item in outputs or [] if isinstance(item, dict)]
        if not normalized:
            label = QLabel("尚未运行，暂未识别真实输出。")
            label.setWordWrap(True)
            label.setStyleSheet("color: #94A3B8; padding: 8px; border: 1px dashed #CBD5E1; border-radius: 6px;")
            self.outputs_layout.addWidget(label)
            return
        for index, output in enumerate(normalized, start=1):
            row = QWidget()
            row.setObjectName("output_row")
            row.setProperty("output_id", str(output.get("output_id") or f"out_{index}"))
            row.setProperty("data_type", str(output.get("data_type") or "table"))
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(6)
            tag = QLabel(f"{row.property('output_id')} · {row.property('data_type')}")
            tag.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
            name_input = QLineEdit(str(output.get("name") or f"代码块结果{index}"))
            name_input.setObjectName("output_name")
            name_input.setPlaceholderText(f"代码块结果{index}")
            name_input.setProperty("_param_disabled", True)
            if hasattr(name_input, "set_parameter_enabled"):
                name_input.set_parameter_enabled(False)
            line.addWidget(tag)
            line.addWidget(name_input, stretch=1)
            self.outputs_layout.addWidget(row)

    def _default_alias(self, index):
        return "df" if index == 0 else f"df{index}"

    def _default_alias_for_type(self, data_type, index_by_type):
        if data_type == "workbook":
            return "wb" if index_by_type == 0 else f"wb{index_by_type}"
        return "df" if index_by_type == 0 else f"df{index_by_type}"

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
            result.append(
                {
                    "table_name": table_name,
                    "alias": alias,
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
            table_name = table_label.text().strip() if table_label else ""
            if not table_name:
                continue
            alias = alias_input.text().strip() if alias_input else self._default_alias(i)
            bindings.append(
                {
                    "table_name": table_name,
                    "alias": alias,
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
                }
            )
        return inputs

    def _refresh_code_summary(self):
        code = self.code_text or ""
        global_code = self.global_code_text or ""
        code_lines = len(code.splitlines()) if code.strip() else 0
        global_lines = len(global_code.splitlines()) if global_code.strip() else 0
        space_count = len(self.function_spaces_data or [])
        space_lines = sum(len(str(item.get("code") or "").splitlines()) for item in self.function_spaces_data or [])
        if not code_lines and not global_lines and not space_lines:
            self.code_summary.setText("未编写代码")
            return
        output_count = len(getattr(self, "_saved_outputs", []) or [])
        output_text = f" · 输出 {output_count} 个" if output_count > 1 else ""
        self.code_summary.setText(f"函数空间 {space_count} 个/{space_lines} 行 · 当前 {code_lines} 行{output_text}")

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
            self.function_spaces_data,
            self._collect_flow_inputs(),
            parameters=self._runtime_parameters,
            mappings=self._parameter_mappings,
            execution_mode=self.execution_mode,
            parent=self.window(),
        )
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._code_editor_dialogs[node_id] = dlg
        dlg.btn_run.clicked.connect(lambda checked=False, nid=node_id, dialog=dlg: self._run_code_editor(nid, dialog))
        dlg.btn_stop.clicked.connect(lambda checked=False, nid=node_id, dialog=dlg: self._stop_code_editor(nid, dialog))
        dlg.accepted.connect(lambda nid=node_id, dialog=dlg: self._apply_code_editor_result(nid, dialog))
        dlg.finished.connect(lambda _result, nid=node_id, dialog=dlg: self._on_code_editor_closed(nid, dialog))
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _apply_code_editor_result(self, node_id, dialog):
        code = dialog.code()
        global_code = dialog.global_code()
        function_spaces = dialog.function_spaces()
        execution_mode = dialog.execution_mode()
        if str(node_id or "") == str(self._bound_node_id or ""):
            self.code_text = code
            self.global_code_text = global_code
            self.function_spaces_data = copy.deepcopy(function_spaces)
            self.execution_mode = execution_mode
            self._refresh_code_summary()
        self.function_spaces_changed.emit(function_spaces)
        self.code_editor_saved_with_spaces.emit(
            str(node_id or ""), code, global_code, function_spaces, execution_mode
        )

    def _run_code_editor(self, node_id, dialog):
        code = dialog.code()
        global_code = dialog.global_code()
        function_spaces = dialog.function_spaces()
        execution_mode = dialog.execution_mode()
        dialog.set_run_status("running", "正在运行当前代码块...")
        if str(node_id or "") == str(self._bound_node_id or ""):
            self.code_text = code
            self.global_code_text = global_code
            self.function_spaces_data = copy.deepcopy(function_spaces)
            self.execution_mode = execution_mode
            self._refresh_code_summary()
        self.function_spaces_changed.emit(function_spaces)
        self.code_editor_run_requested_with_spaces.emit(
            str(node_id or ""), code, global_code, function_spaces, execution_mode
        )

    def _stop_code_editor(self, node_id, dialog):
        if dialog is not None and dialog.isVisible():
            dialog.set_run_status("stopping", "已请求停止，正在等待代码块自行退出...")
        self.code_editor_stop_requested.emit(str(node_id or ""))

    def _on_code_editor_closed(self, node_id, dialog):
        if self._code_editor_dialogs.get(node_id) is dialog:
            self._code_editor_dialogs.pop(node_id, None)

    def set_code_editor_running(self, node_id, message="正在运行当前代码块..."):
        dialog = self._code_editor_dialogs.get(str(node_id or ""))
        if dialog is not None and dialog.isVisible():
            dialog.set_run_status("running", message)
        self.code_summary.setText("代码块运行中...")

    def set_code_editor_stopping(self, node_id, message="已请求停止，等待代码块自行退出..."):
        dialog = self._code_editor_dialogs.get(str(node_id or ""))
        if dialog is not None and dialog.isVisible():
            dialog.set_run_status("stopping", message)
        self.code_summary.setText("代码块停止中...")

    def set_code_editor_stopped(self, node_id, message="代码块已停止"):
        dialog = self._code_editor_dialogs.get(str(node_id or ""))
        if dialog is not None and dialog.isVisible():
            dialog.set_run_status("stopped", message)
        self.code_summary.setText("代码块已停止")

    def append_code_editor_log(self, node_id, message):
        dialog = self._code_editor_dialogs.get(str(node_id or ""))
        if dialog is not None and dialog.isVisible():
            dialog.append_run_log(message)

    def set_code_editor_run_result(self, node_id, success, message=""):
        status = "success" if success else "error"
        dialog = self._code_editor_dialogs.get(str(node_id or ""))
        if dialog is not None and dialog.isVisible():
            dialog.set_run_status(status, message)
        if success:
            self._refresh_code_summary()
        elif message:
            self.code_summary.setText("运行失败")

    def _function_space_errors(self):
        errors = []
        namespaces = set()
        for index, space in enumerate(self.function_spaces_data or [], start=1):
            namespace = str(space.get("namespace") or "").strip()
            label = str(space.get("name") or f"函数空间{index}")
            if not _valid_function_reference_name(namespace):
                errors.append(f"{label}: 引用名称无效 {namespace!r}")
            elif namespace in namespaces:
                errors.append(f"{label}: 命名空间重复 {namespace}")
            namespaces.add(namespace)
            code = str(space.get("code") or "")
            if not code.strip():
                continue
            try:
                compile(code, f"<函数空间:{namespace or index}>", "exec")
            except Exception as exc:
                errors.append(f"{label}: {exc}")
        return errors

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
        if not self.code_text.strip():
            QMessageBox.warning(self, "代码为空", "请先点击“编辑代码”编写代码。")
            return False, None
        function_errors = self._function_space_errors()
        if function_errors:
            QMessageBox.warning(self, "函数库无效", "\n".join(function_errors[:8]))
            return False, None
        return True, None
