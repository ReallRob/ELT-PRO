import json

from PyQt5.QtCore import Qt, pyqtSignal, QRect
from PyQt5.QtGui import (
    QColor,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PyQt5.QtWidgets import (
    QLineEdit,
    QTextEdit,
    QToolButton,
    QStyle,
    QStyleOptionFrame,
)

from parameter_resolver import (
    PLACEHOLDER_RE,
    normalize_parameter_mappings,
    normalize_runtime_parameters,
    resolve_placeholder,
)


def _placeholder_state(expression, parameters, mappings):
    parts = [part.strip() for part in expression.split("|") if part.strip()]
    param_name = parts[0] if parts else ""
    mapping_name = ""
    for part in parts[1:]:
        if part.startswith("map:"):
            mapping_name = part[4:].strip()

    if param_name not in parameters:
        return "missing", f"未定义参数: {param_name}"
    if mapping_name and mapping_name not in mappings:
        return "missing", f"未定义映射: {mapping_name}"

    try:
        value = resolve_placeholder(expression, parameters, mappings, strict=True)
        if isinstance(value, (list, dict, tuple)):
            value = json.dumps(value, ensure_ascii=False)
        return "mapped" if mapping_name else "param", str(value)
    except Exception as exc:
        return "missing", str(exc)


def _placeholder_label(expression):
    parts = [part.strip() for part in expression.split("|") if part.strip()]
    if not parts:
        return expression
    param_name = parts[0]
    for part in parts[1:]:
        if part.startswith("map:"):
            return f"{param_name} -> {part[4:].strip()}"
    return param_name


def _placeholder_colors(state):
    if state == "missing":
        return QColor("#FFEBEE"), QColor("#B71C1C")
    if state == "mapped":
        return QColor("#F3E5F5"), QColor("#4A148C")
    return QColor("#E3F2FD"), QColor("#0D47A1")


def _preview_tooltip(text, parameters, mappings):
    rows = []
    for match in PLACEHOLDER_RE.finditer(text or ""):
        expr = match.group(1)
        label = _placeholder_label(expr)
        state, preview = _placeholder_state(expr, parameters, mappings)
        prefix = "!" if state == "missing" else "="
        rows.append(f"{label} {prefix} {preview}")
    return "\n".join(rows)


class PlaceholderHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.parameters = {}
        self.mappings = {}

    def set_context(self, parameters=None, mappings=None):
        self.parameters = normalize_runtime_parameters(parameters or {})
        self.mappings = normalize_parameter_mappings(mappings or {})
        self.rehighlight()

    def highlightBlock(self, text):
        for match in PLACEHOLDER_RE.finditer(text):
            expr = match.group(1)
            state, _ = _placeholder_state(expr, self.parameters, self.mappings)
            fmt = QTextCharFormat()
            fmt.setFontWeight(700)
            if state == "missing":
                fmt.setForeground(QColor("#B71C1C"))
                fmt.setBackground(QColor("#FFEBEE"))
            elif state == "mapped":
                fmt.setForeground(QColor("#4A148C"))
                fmt.setBackground(QColor("#F3E5F5"))
            else:
                fmt.setForeground(QColor("#0D47A1"))
                fmt.setBackground(QColor("#E3F2FD"))
            self.setFormat(match.start(), match.end() - match.start(), fmt)


class ParameterTextInput(QLineEdit):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._runtime_parameters = {}
        self._parameter_mappings = {}
        self._parameter_enabled = True
        self.textChanged.connect(self._refresh_parameter_tooltip)
        if text:
            self.setText(str(text))

    def set_parameter_enabled(self, enabled):
        self._parameter_enabled = bool(enabled)
        self.setProperty("_param_disabled", not self._parameter_enabled)
        if not self._parameter_enabled:
            self.setToolTip("")
        self.update()

    def parameter_enabled(self):
        return self._parameter_enabled

    def set_runtime_context(self, parameters=None, mappings=None):
        self._runtime_parameters = normalize_runtime_parameters(parameters or {})
        self._parameter_mappings = normalize_parameter_mappings(mappings or {})
        self._refresh_parameter_tooltip()
        self.update()

    def insert_text(self, text):
        pos = self.cursorPosition()
        old = self.text()
        self.setText(old[:pos] + text + old[pos:])
        self.setCursorPosition(pos + len(text))
        self.setFocus()

    def _refresh_parameter_tooltip(self):
        if not self._parameter_enabled:
            self.setToolTip("")
            return
        preview = _preview_tooltip(
            self.text(),
            self._runtime_parameters,
            self._parameter_mappings,
        )
        self.setToolTip(preview or "")

    def paintEvent(self, event):
        text = self.text()
        if self.hasFocus() or not self._parameter_enabled or not PLACEHOLDER_RE.search(text):
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        option = QStyleOptionFrame()
        self.initStyleOption(option)
        self.style().drawPrimitive(QStyle.PE_PanelLineEdit, option, painter, self)

        left, top, right, bottom = self.getTextMargins()
        clip = self.rect().adjusted(8 + left, 1 + top, -8 - right, -1 - bottom)
        painter.setClipRect(clip)

        metrics = self.fontMetrics()
        x = clip.left()
        baseline = int(clip.top() + (clip.height() + metrics.ascent() - metrics.descent()) / 2)
        token_h = max(18, min(clip.height() - 2, metrics.height() + 8))
        token_y = int(clip.top() + (clip.height() - token_h) / 2)

        pos = 0
        for match in PLACEHOLDER_RE.finditer(text):
            plain = text[pos:match.start()]
            if plain:
                painter.setPen(QColor("#1F2933"))
                painter.drawText(x, baseline, plain)
                x += metrics.horizontalAdvance(plain)

            expr = match.group(1)
            label = _placeholder_label(expr)
            state, _ = _placeholder_state(
                expr,
                self._runtime_parameters,
                self._parameter_mappings,
            )
            bg, fg = _placeholder_colors(state)

            remaining_w = clip.right() - x + 1
            if remaining_w <= 0:
                break
            token_w = metrics.horizontalAdvance(label) + 16
            token_w = min(token_w, max(48, min(220, remaining_w)))
            draw_label = metrics.elidedText(label, Qt.ElideRight, max(12, token_w - 16))
            rect = QRect(int(x), token_y, int(token_w), int(token_h))
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 7, 7)
            painter.setPen(fg)
            painter.drawText(rect, Qt.AlignCenter, draw_label)
            x += token_w + 4
            pos = match.end()

        tail = text[pos:]
        if tail:
            painter.setPen(QColor("#1F2933"))
            painter.drawText(x, baseline, tail)


class ParameterTextEdit(QTextEdit):
    parameterMenuRequested = pyqtSignal(object)

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._runtime_parameters = {}
        self._parameter_mappings = {}
        self.setAcceptRichText(False)
        self.setMinimumHeight(72)
        self.setPlaceholderText("输入表达式...")
        self.setViewportMargins(0, 0, 28, 0)
        self.highlighter = PlaceholderHighlighter(self.document())
        self.textChanged.connect(self._refresh_parameter_tooltip)

        self.param_button = QToolButton(self)
        self.param_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.param_button.setToolTip("引入参数")
        self.param_button.setCursor(Qt.PointingHandCursor)
        self.param_button.clicked.connect(lambda: self.parameterMenuRequested.emit(self))
        self.param_button.setFixedSize(24, 24)
        self.param_button.setStyleSheet(
            "QToolButton { background: #F8FAFC; border: 1px solid #CBD5E1; "
            "border-radius: 5px; padding: 2px; }"
            "QToolButton:hover { background: #EEF2F7; border-color: #94A3B8; }"
        )

        if text:
            self.setPlainText(str(text))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.param_button.move(self.width() - 28, 4)

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText("" if text is None else str(text))

    def cursorPosition(self):
        return self.textCursor().position()

    def setCursorPosition(self, pos):
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(pos, len(self.toPlainText()))))
        self.setTextCursor(cursor)

    def insert_text(self, text):
        cursor = self.textCursor()
        cursor.insertText(text)
        self.setTextCursor(cursor)
        self.setFocus()

    def set_runtime_context(self, parameters=None, mappings=None):
        self._runtime_parameters = normalize_runtime_parameters(parameters or {})
        self._parameter_mappings = normalize_parameter_mappings(mappings or {})
        self.highlighter.set_context(self._runtime_parameters, self._parameter_mappings)
        self._refresh_parameter_tooltip()

    def _refresh_parameter_tooltip(self):
        preview = _preview_tooltip(
            self.toPlainText(),
            self._runtime_parameters,
            self._parameter_mappings,
        )
        self.setToolTip(preview or "")
