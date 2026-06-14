"""Reusable pages for the design-mode configuration dialog."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


def _make_message_card(title, hint, word_wrap=False):
    """Build the shared centered message card used by config placeholder pages."""
    page = QWidget()
    page.setStyleSheet("background: #F3F6FA;")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.addStretch()

    card = QFrame()
    card.setStyleSheet("""
        QFrame {
            background: #FFFFFF;
            border: 1px solid #DFE5EC;
            border-radius: 8px;
        }
    """)
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(24, 22, 24, 22)
    card_layout.setSpacing(8)

    title_label = QLabel(title)
    title_label.setAlignment(Qt.AlignCenter)
    title_label.setStyleSheet(
        "color: #1F2933; font-size: 16px; font-weight: bold; border: none;"
    )
    hint_label = QLabel(hint)
    hint_label.setAlignment(Qt.AlignCenter)
    hint_label.setWordWrap(word_wrap)
    hint_label.setStyleSheet("color: #607D8B; font-size: 12px; border: none;")

    card_layout.addWidget(title_label)
    card_layout.addWidget(hint_label)
    layout.addWidget(card)
    layout.addStretch()
    return page, title_label, hint_label


def make_empty_config_page():
    page, _, _ = _make_message_card(
        "选择一个算子节点",
        "配置参数会在这里显示",
    )
    return page


def make_legacy_operator_page():
    page, title_label, hint_label = _make_message_card(
        "旧参数算子已合并",
        "请新建“参数高级映射”算子维护输入参数与映射规则。",
        word_wrap=True,
    )
    return page, title_label, hint_label
