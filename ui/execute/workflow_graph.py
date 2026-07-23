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
from core.workflow.schema import operation_display_name


def _dedupe_names(names, fallback=""):
    result = []
    seen = set()
    for name in names or []:
        text = str(name or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    fallback = str(fallback or "").strip()
    if not result and fallback:
        result.append(fallback)
    return result


class ExecuteNodeItem(QGraphicsPathItem):
    def __init__(self, table_name, text, action_type="", output_names=None, node_id=""):
        super().__init__()
        self.display_name = str(text or table_name or "")
        self.node_id = str(node_id or "")
        self.output_names = _dedupe_names(output_names, table_name or text)
        self.table_name = self.output_names[0] if self.output_names else str(table_name or "")
        self.available_output_names = []
        self.action_type = action_type
        self.status = "pending"
        self.has_data = False

        self.setFlag(QGraphicsPathItem.ItemIsSelectable)

        font = QFont("Microsoft YaHei", 9, QFont.Bold)
        metrics = QFontMetrics(font)
        text_width = metrics.boundingRect(text).width()
        self.width = min(max(160, text_width + 40), 350)
        self.height = 60
        self._refresh_tooltip()

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

    def _refresh_tooltip(self):
        output_text = "、".join(self.output_names)
        suffix = f"\n输出: {output_text}" if output_text else ""
        self.setToolTip(f"[{self.action_type}] {self.display_name}{suffix}")

    def set_output_names(self, output_names):
        names = _dedupe_names(output_names, self.display_name)
        self.output_names = names
        self.table_name = names[0] if names else self.display_name
        self.available_output_names = []
        self._refresh_tooltip()
        self.update()

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
            "error": ("#E53935", "#EF5350"),
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
        if self.action_type not in {"数据源导入", "加载模板", "参数输入"}:
            painter.drawEllipse(QPointF(0, self.height / 2), port_r, port_r)
        painter.drawEllipse(QPointF(self.width, self.height / 2), port_r, port_r)

        if self.status == "success":
            painter.setFont(QFont("Microsoft YaHei", 8))
            if self.has_data:
                painter.setPen(QPen(QColor("#4CAF50")))
                painter.drawText(
                    QRectF(self.width - 42, self.height - 18, 36, 16),
                    Qt.AlignRight | Qt.AlignVCenter,
                    "OK",
                )
            else:
                painter.setPen(QPen(QColor("#BDBDBD")))
                painter.drawText(
                    QRectF(self.width - 42, self.height - 18, 36, 16),
                    Qt.AlignRight | Qt.AlignVCenter,
                    "~",
                )


class WorkflowGraphView(QGraphicsView):
    node_clicked = pyqtSignal(object, bool)
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
            "import_template": "加载模板",
            "insert_block": "写入模板",
            "save_template": "保存模板",
            "code_block": "代码块",
        }

        unique_items = []
        item_edges_out = {}

        for step in steps:
            action = step.get("action")
            node_id = step.get("node_id")

            act_zh = action_names.get(action, action)
            display_name = operation_display_name(step, f"Result_{step.get('step_id')}")
            output_names = [
                str(output.get("name"))
                for output in (step.get("params", {}) or {}).get("outputs", []) or []
                if isinstance(output, dict) and output.get("name")
            ]
            preview_key = output_names[0] if output_names else display_name
            item = ExecuteNodeItem(preview_key, display_name, act_zh, output_names, node_id)
            self.scene.addItem(item)
            unique_items.append(item)

            self.node_items_dict[display_name] = item
            for output_name in output_names:
                self.node_items_dict[output_name] = item
            if node_id:
                self.node_items_dict[str(node_id)] = item

            item_edges_out[item] = []

        for step in steps:
            curr_id = str(step.get("node_id") or "")
            curr_item = self.node_items_dict.get(curr_id)
            if not curr_item:
                continue

            params = step.get("params", {})
            deps = []
            for input_item in params.get("inputs", []) or []:
                if isinstance(input_item, dict) and input_item.get("source_node_id"):
                    deps.append(str(input_item["source_node_id"]))

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
        for item in set(self.node_items_dict.values()):
            item.set_status(status)

    def update_node_output_names(self, output_key_map):
        if not isinstance(output_key_map, dict):
            return
        for node_id, outputs in output_key_map.items():
            node_id = str(node_id or "")
            item = self.node_items_dict.get(node_id)
            if not isinstance(item, ExecuteNodeItem) or not isinstance(outputs, dict):
                continue
            names = [name for name in outputs.values() if name]
            if not names:
                continue
            item.set_output_names(names)
            if item.node_id:
                self.node_items_dict[item.node_id] = item
            for name in names:
                self.node_items_dict[name] = item

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if isinstance(item, QGraphicsTextItem):
            item = item.parentItem()

        if isinstance(item, ExecuteNodeItem):
            self.node_clicked.emit(list(item.output_names or [item.table_name]), False)
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
            output_names = list(item.output_names or [item.table_name])
            available_names = set(getattr(item, "available_output_names", []) or [])

            if item.status == "success" and item.has_data:
                for output_name in output_names:
                    if output_name in available_names:
                        export_act = QAction(f"[导出] 保存节点数据: {output_name}", self)
                        export_act.triggered.connect(
                            lambda _checked=False, name=output_name: self.request_export.emit(name)
                        )
                    else:
                        export_act = QAction(f"[无数据] 内存已释放: {output_name}", self)
                        export_act.setEnabled(False)
                    menu.addAction(export_act)
            elif item.status == "success":
                export_act = QAction(f"[无数据] 内存已释放: {item.table_name}", self)
                export_act.setEnabled(False)
                menu.addAction(export_act)
            elif item.status == "pending" or item.status == "error":
                export_act = QAction(f"[未就绪] 暂无结果: {item.table_name}", self)
                export_act.setEnabled(False)
                menu.addAction(export_act)
            else:
                export_act = QAction(f"[导出] 保存此节点数据: {item.table_name}", self)
                export_act.triggered.connect(lambda: self.request_export.emit(item.table_name))
                menu.addAction(export_act)

            menu.exec_(event.globalPos())

    def wheelEvent(self, event):
        if event.modifiers() == Qt.ControlModifier:
            zoom = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(zoom, zoom)
        else:
            super().wheelEvent(event)
