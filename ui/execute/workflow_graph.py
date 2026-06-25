"""Execution workflow graph preview widgets."""

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QBrush, QFont, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import (
    QAction,
    QGraphicsDropShadowEffect,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QMenu,
)

import utils


class ExecuteNodeItem(QGraphicsPathItem):
    def __init__(self, table_name, text, action_type=""):
        super().__init__()
        self.table_name = table_name
        self.action_type = action_type
        self.status = "pending"
        self.has_data = False

        self.setFlag(QGraphicsPathItem.ItemIsSelectable)

        font = QFont("Microsoft YaHei", 9, QFont.Bold)
        metrics = QFontMetrics(font)
        text_width = metrics.boundingRect(text).width()
        self.width = min(max(160, text_width + 40), 350)
        self.height = 60
        self.setToolTip(f"[{action_type}] {text}")

        self.setAcceptHoverEvents(True)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(8)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(2, 2)
        self.setGraphicsEffect(shadow)

        self.text_item = QGraphicsTextItem(text, self)
        self.text_item.setFont(font)
        self.text_item.setDefaultTextColor(Qt.black)
        self.text_item.setPos(5, 25)

        self.type_item = QGraphicsTextItem(action_type, self)
        self.type_item.setFont(QFont("Arial", 8, QFont.Bold))
        self.type_item.setDefaultTextColor(Qt.white)
        self.type_item.setPos(5, 2)

    def set_status(self, status):
        self.status = status
        self.update()

    def boundingRect(self):
        return QRectF(-5, -5, self.width + 10, self.height + 10)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)

        status_colors = {
            "pending": ("#607D8B", "#B0BEC5"),
            "success": ("#43A047", "#66BB6A"),
            "error":   ("#E53935", "#EF5350"),
        }
        header_color, border_color = status_colors.get(self.status, status_colors["pending"])

        if self.isSelected():
            pen = QPen(QColor("#2196F3"), 3)
        else:
            pen = QPen(QColor(border_color), 2)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor("white")))
        rect = QRectF(0, 0, self.width, self.height)
        painter.drawRoundedRect(rect, 6, 6)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(header_color)))
        header_rect = QRectF(0, 0, self.width, 22)
        painter.drawRoundedRect(header_rect, 6, 6)
        painter.drawRect(QRectF(0, 11, self.width, 11))

        painter.setBrush(QBrush(QColor("#BDBDBD")))
        painter.setPen(QPen(QColor("#757575"), 1))
        port_r = 4
        if self.action_type != "数据源导入":
            painter.drawEllipse(QPointF(0, self.height / 2), port_r, port_r)
        painter.drawEllipse(QPointF(self.width, self.height / 2), port_r, port_r)

        if self.status == "success":
            painter.setFont(QFont("Microsoft YaHei", 8))
            if self.has_data:
                painter.setPen(QPen(QColor("#4CAF50")))
                painter.drawText(
                    QRectF(self.width - 42, self.height - 18, 36, 16),
                    Qt.AlignRight | Qt.AlignVCenter, "OK"
                )
            else:
                painter.setPen(QPen(QColor("#BDBDBD")))
                painter.drawText(
                    QRectF(self.width - 42, self.height - 18, 36, 16),
                    Qt.AlignRight | Qt.AlignVCenter, "~"
                )


class WorkflowGraphView(QGraphicsView):
    node_clicked = pyqtSignal(str, bool)
    request_export = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)

        self.setStyleSheet("background-color: #f0f2f5; border: none;")
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.node_items_dict = {}

    def drawBackground(self, painter, rect):
        utils.draw_grid_background(painter, rect)

    def render_workflow(self, workflow_config):
        self.scene.clear()
        self.node_items_dict.clear()
        if not workflow_config:
            return

        steps = workflow_config.get("steps", [])

        action_names = {
            "advanced_param_mapping": "参数输入",
            "load_file": "数据源导入",
            "get_col_data": "提取列",
            "filter_data": "数据筛选",
            "group_calc": "分组汇总",
            "left_join": "表连接",
            "rank_col": "数据排名",
            "sort_data": "多级排序",
            "calc_col": "公式计算",
            "clean_data": "数据清洗",
            "export_df": "自动导出",
            "import_template": "导入模板",
            "insert_block": "插入模板",
            "code_block": "代码块",
        }

        unique_items = []
        item_edges_out = {}

        for step in steps:
            action = step.get("action")
            out_name = step.get("out_name", f"Result_{step.get('step_id')}")
            node_id = step.get("node_id")

            act_zh = action_names.get(action, action)
            item = ExecuteNodeItem(out_name, out_name, act_zh)
            self.scene.addItem(item)
            unique_items.append(item)

            self.node_items_dict[out_name] = item
            if node_id:
                self.node_items_dict[node_id] = item

            item_edges_out[item] = []

        for step in steps:
            curr_id = step.get("node_id")
            curr_out = step.get("out_name")
            curr_item = self.node_items_dict.get(curr_id) or self.node_items_dict.get(
                curr_out
            )
            if not curr_item:
                continue

            params = step.get("params", {})
            deps = []

            if "df1_id" in params:
                deps.append(params["df1_id"])
            if "df2_id" in params:
                deps.append(params["df2_id"])
            if "df_id" in params:
                deps.append(params["df_id"])
            if "template_id" in params:
                deps.append(params["template_id"])
            for insert_id in params.get("insert_block_ids", []) or []:
                deps.append(insert_id)
            for binding in params.get("input_bindings", []) or []:
                if isinstance(binding, dict) and binding.get("df_id"):
                    deps.append(binding["df_id"])

            if not deps:
                if "df1_name" in params:
                    deps.append(params["df1_name"])
                if "df2_name" in params:
                    deps.append(params["df2_name"])
                if "df_name" in params:
                    deps.append(params["df_name"])

            for dep in deps:
                dep_item = self.node_items_dict.get(dep)
                if dep_item:
                    item_edges_out[dep_item].append(curr_item)

        utils.topological_layout(
            unique_items,
            get_outgoing=lambda n: item_edges_out.get(n, []),
            get_sort_key=lambda n: n.table_name,
            set_pos_func=lambda n, x, y: n.setPos(x, y),
            start_x=50,
            start_y=100,
        )

        for src, dests in item_edges_out.items():
            for dest in dests:
                self.draw_edge(src, dest)

        rect = self.scene.itemsBoundingRect()
        self.scene.setSceneRect(rect.adjusted(-200, -200, 200, 200))
        self.centerOn(rect.center())

    def draw_edge(self, start_item, end_item):
        sp = start_item.pos() + QPointF(start_item.width, start_item.height / 2)
        ep = end_item.pos() + QPointF(0, end_item.height / 2)

        edge = self.scene.addPath(
            utils.bezier_edge_path(sp, ep), QPen(QColor("#B0BEC5"), 2)
        )
        edge.setZValue(-1)

        arrow_item = self.scene.addPolygon(
            utils.arrow_polygon(ep, size=8),
            QPen(Qt.NoPen),
            QBrush(QColor("#B0BEC5")),
        )
        arrow_item.setZValue(-1)

    def set_all_nodes_status(self, status):
        for item in self.node_items_dict.values():
            item.set_status(status)

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if isinstance(item, QGraphicsTextItem):
            item = item.parentItem()

        if isinstance(item, ExecuteNodeItem):
            self.node_clicked.emit(item.table_name, False)
        elif event.button() == Qt.MiddleButton:
            self._is_panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if hasattr(self, "_is_panning") and self._is_panning:
            delta = event.pos() - self._pan_start
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            self._pan_start = event.pos()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if isinstance(item, QGraphicsTextItem):
            item = item.parentItem()

        if isinstance(item, ExecuteNodeItem) and item.table_name:
            menu = QMenu()

            if item.status == "success" and not item.has_data:
                export_act = QAction(f"[无数据] 内存已释放: {item.table_name}", self)
                export_act.setEnabled(False)
            elif item.status == "pending" or item.status == "error":
                export_act = QAction(f"[未就绪] 暂无结果: {item.table_name}", self)
                export_act.setEnabled(False)
            else:
                export_act = QAction(f"[导出] 保存此节点数据: {item.table_name}", self)
                export_act.triggered.connect(
                    lambda: self.request_export.emit(item.table_name)
                )

            menu.addAction(export_act)
            menu.exec_(event.globalPos())

    def wheelEvent(self, event):
        if event.modifiers() == Qt.ControlModifier:
            zoom = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(zoom, zoom)
        else:
            super().wheelEvent(event)
