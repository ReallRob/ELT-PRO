"""Bottom status bar helpers for design mode."""

from PyQt5.QtWidgets import QHBoxLayout, QLabel

from node_editor import EdgeItem, NodeItem


def build_status_bar(owner):
    status_bar = QHBoxLayout()
    status_bar.setSpacing(15)

    owner.status_label = QLabel("就绪")
    owner.status_label.setStyleSheet("color: #666; font-size: 11px; padding: 2px 8px;")
    owner.status_node_count = QLabel("节点: 0")
    owner.status_node_count.setStyleSheet("color: #999; font-size: 11px;")
    owner.status_table_count = QLabel("内存表: 0")
    owner.status_table_count.setStyleSheet("color: #999; font-size: 11px;")

    status_bar.addWidget(owner.status_label)
    status_bar.addStretch(1)
    status_bar.addWidget(owner.status_node_count)
    status_bar.addWidget(owner.status_table_count)
    return status_bar


class StatusBarMixin:
    def _update_status_bar(self):
        nodes = [item for item in self.canvas_scene.items() if isinstance(item, NodeItem)]
        edges = [item for item in self.canvas_scene.items() if isinstance(item, EdgeItem)]
        self.status_node_count.setText(f"节点: {len(nodes)}  连线: {len(edges)}")
        self.status_table_count.setText(f"内存表: {len(self.ctx.data_pool)}")
        self.status_label.setText("点击节点查看数据 | 双击配置参数 | 右键添加节点")
