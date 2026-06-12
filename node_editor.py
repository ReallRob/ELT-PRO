from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QGraphicsPathItem,
    QMessageBox,
)
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QPen,
    QBrush,
    QFont,
    QPainterPath,
    QPainter,
    QPainterPathStroker,
    QFontMetrics,
)

import utils


METADATA_NODE_TYPES = ("input_param", "param_mapping")


class NodeItem(QGraphicsItem):
    def __init__(self, node_id, action_type, title, color="#1976D2", x=0, y=0):
        super().__init__()
        self.node_id = node_id
        self.action_type = action_type
        self.title = title
        self.color = color

        # 修复显示不全：动态计算文本宽度，自适应节点大小
        font = QFont("Microsoft YaHei", 9)
        metrics = QFontMetrics(font)
        text_width = metrics.boundingRect(self.title).width()
        # 保证基础宽度 160，最大不超过 350
        self.width = min(max(160, text_width + 40), 350)
        self.height = 60

        # 增加悬浮提示，确保任何情况下都能看全
        self.setToolTip(f"[{action_type}] {title}")

        # 节点生成时自动吸附网格 (20像素对齐)
        self.setPos(round(x / 20) * 20, round(y / 20) * 20)

        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.edges_in = []
        self.edges_out = []
        self.params = {}
        self.is_dirty = False
        self.setZValue(1)

    def boundingRect(self):
        return QRectF(-10, -10, self.width + 20, self.height + 20)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制主节点框
        if self.isSelected():
            pen = QPen(QColor("#4CAF50"), 3)
        elif self.is_dirty:
            pen = QPen(QColor("#FFC107"), 3)
        else:
            pen = QPen(QColor(self.color), 2)

        painter.setPen(pen)
        painter.setBrush(QBrush(QColor("white")))
        rect = QRectF(0, 0, self.width, self.height)
        painter.drawRoundedRect(rect, 5, 5)

        # 绘制标题栏背景
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(self.color)))
        header_rect = QRectF(0, 0, self.width, 20)
        painter.drawRoundedRect(header_rect, 5, 5)
        painter.drawRect(QRectF(0, 10, self.width, 10))

        # 绘制算子类型文字
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.drawText(header_rect, Qt.AlignCenter, self.action_type)

        # 绘制动态名称文字
        painter.setPen(QColor("black"))
        font = QFont("Microsoft YaHei", 9)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        elided_title = metrics.elidedText(
            self.title, Qt.ElideRight, int(self.width - 15)
        )
        painter.drawText(
            QRectF(5, 25, self.width - 10, 30),
            Qt.AlignCenter,
            elided_title,
        )

        # 将连接引脚（端口）横向分布在左右两侧
        painter.setBrush(QBrush(QColor("#ccc")))
        painter.setPen(QPen(QColor("#666"), 1))

        # 左侧输入端口 (剔除不需要输入的源头节点)
        if self.action_type not in ("load_file", "import_template") + METADATA_NODE_TYPES:
            painter.drawEllipse(QPointF(0, self.height / 2), 5, 5)

        # 右侧输出端口
        if self.action_type not in METADATA_NODE_TYPES:
            painter.drawEllipse(QPointF(self.width, self.height / 2), 5, 5)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            new_pos = value
            x = round(new_pos.x() / 20) * 20
            y = round(new_pos.y() / 20) * 20
            if x != new_pos.x() or y != new_pos.y():
                self.setPos(x, y)
                return QPointF(x, y)

            for edge in self.edges_in + self.edges_out:
                edge.update_position()
        return super().itemChange(change, value)


class EdgeItem(QGraphicsPathItem):
    def __init__(self, source_node, dest_node):
        super().__init__()
        self.source_node = source_node
        self.dest_node = dest_node
        self.setZValue(0)
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsFocusable)
        self.update_position()

    def shape(self):
        path = self.path()
        stroker = QPainterPathStroker()
        stroker.setWidth(15)
        return stroker.createStroke(path)

    def update_position(self):
        if not self.source_node or not self.dest_node:
            return

        sp = self.source_node.pos() + QPointF(
            self.source_node.width, self.source_node.height / 2
        )
        ep = self.dest_node.pos() + QPointF(0, self.dest_node.height / 2)

        self.setPath(utils.bezier_edge_path(sp, ep))

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
        if self.isSelected():
            line_color = QColor("#f44336")
            line_width = 3
        else:
            line_color = QColor("#999999")
            line_width = 2

        painter.setPen(
            QPen(line_color, line_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.drawPath(self.path())

        # 箭头方向改为向右
        if self.dest_node:
            ep = self.dest_node.pos() + QPointF(0, self.dest_node.height / 2)
            painter.setBrush(QBrush(line_color))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(utils.arrow_polygon(ep))


class NodeCanvasScene(QGraphicsScene):
    CANVAS_HALF_SIZE = 25000
    node_selected = pyqtSignal(object)
    node_double_clicked = pyqtSignal(object)
    right_clicked = pyqtSignal(QPointF)
    edge_changed = pyqtSignal()  # 连线变更，通知面板刷新列

    def __init__(self):
        super().__init__()
        self.setSceneRect(
            -self.CANVAS_HALF_SIZE,
            -self.CANVAS_HALF_SIZE,
            self.CANVAS_HALF_SIZE * 2,
            self.CANVAS_HALF_SIZE * 2,
        )
        self.drawing_edge = False
        self.temp_edge = None
        self.start_node = None

    def drawBackground(self, painter, rect):
        utils.draw_grid_background(painter, rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.right_clicked.emit(event.scenePos())
            super().mousePressEvent(event)
            return

        item = self.itemAt(event.scenePos(), self.views()[0].transform())
        if event.button() == Qt.LeftButton:
            if isinstance(item, NodeItem) and item.action_type not in METADATA_NODE_TYPES:
                if event.scenePos().x() > item.scenePos().x() + item.width - 25:
                    self.start_node = item
                    self.drawing_edge = True
                    self.temp_edge = QGraphicsPathItem()
                    self.temp_edge.setPen(QPen(QColor("#2196F3"), 2, Qt.DashLine))
                    self.addItem(self.temp_edge)
                    return

            if isinstance(item, NodeItem):
                self.node_selected.emit(item)
            else:
                self.node_selected.emit(None)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.scenePos(), self.views()[0].transform())
        if event.button() == Qt.LeftButton and isinstance(item, NodeItem):
            self.node_double_clicked.emit(item)
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        if self.drawing_edge and self.temp_edge and self.start_node:
            sp = self.start_node.pos() + QPointF(
                self.start_node.width, self.start_node.height / 2
            )
            ep = event.scenePos()
            self.temp_edge.setPath(utils.bezier_edge_path(sp, ep))
        else:
            super().mouseMoveEvent(event)

    @staticmethod
    def _max_inputs(node):
        """返回节点允许的最大输入连线数"""
        if node.action_type in ("load_file", "import_template") + METADATA_NODE_TYPES:
            return 0
        if node.action_type in ("left_join", "concat_rows", "insert_block"):
            return 2
        return 1

    def _can_accept_input(self, node):
        """检查节点是否还能接受新的输入连线"""
        max_in = self._max_inputs(node)
        return max_in > 0 and len(node.edges_in) < max_in

    def _would_create_cycle(self, start_node, end_node):
        visited = set()
        stack = [end_node]
        while stack:
            curr = stack.pop()
            if curr == start_node:
                return True
            if curr not in visited:
                visited.add(curr)
                for edge in curr.edges_out:
                    stack.append(edge.dest_node)
        return False

    def mouseReleaseEvent(self, event):
        if self.drawing_edge:
            self.drawing_edge = False
            if self.temp_edge:
                self.removeItem(self.temp_edge)
            end_item = self.itemAt(event.scenePos(), self.views()[0].transform())
            if (
                isinstance(end_item, NodeItem)
                and end_item != self.start_node
                and end_item.action_type != "load_file"
            ):
                existing_edges = [
                    edge
                    for edge in self.start_node.edges_out
                    if edge.dest_node == end_item
                ]
                if not existing_edges:
                    if self._would_create_cycle(self.start_node, end_item):
                        QMessageBox.warning(None, "连线被拒绝", "非法操作：死循环！")
                    elif not self._can_accept_input(end_item):
                        QMessageBox.warning(
                            None, "连线被拒绝",
                            f"该算子只接受 {self._max_inputs(end_item)} 个输入"
                        )
                    else:
                        edge = EdgeItem(self.start_node, end_item)
                        self.addItem(edge)
                        self.start_node.edges_out.append(edge)
                        end_item.edges_in.append(edge)
                        self.edge_changed.emit()
            self.start_node = None
        super().mouseReleaseEvent(event)

    def delete_selected_items(self):
        for item in self.selectedItems():
            if isinstance(item, NodeItem):
                for edge in list(item.edges_in):
                    if edge in edge.source_node.edges_out:
                        edge.source_node.edges_out.remove(edge)
                    self.removeItem(edge)
                for edge in list(item.edges_out):
                    if edge in edge.dest_node.edges_in:
                        edge.dest_node.edges_in.remove(edge)
                    self.removeItem(edge)
                self.removeItem(item)
            elif isinstance(item, EdgeItem):
                if item in item.source_node.edges_out:
                    item.source_node.edges_out.remove(item)
                if item.dest_node and item in item.dest_node.edges_in:
                    item.dest_node.edges_in.remove(item)
                self.removeItem(item)
        self.edge_changed.emit()
        self.node_selected.emit(None)


class NodeCanvasView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._is_panning = False

    def center_on_canvas(self):
        self.centerOn(QPointF(0, 0))

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._is_panning = True
            self._pan_start_x = event.x()
            self._pan_start_y = event.y()
            self.setCursor(Qt.ClosedHandCursor)
            return

        item = self.itemAt(event.pos())
        if item is None and event.button() == Qt.LeftButton:
            self.setDragMode(QGraphicsView.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.NoDrag)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning:
            dx = event.x() - self._pan_start_x
            dy = event.y() - self._pan_start_y
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - dx)
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - dy)
            self._pan_start_x = event.x()
            self._pan_start_y = event.y()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return

        super().mouseReleaseEvent(event)
        self.setDragMode(QGraphicsView.NoDrag)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.scene().delete_selected_items()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta()
        if event.modifiers() == Qt.ControlModifier:
            factor = 1.15 if delta.y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
        elif event.modifiers() == Qt.ShiftModifier:
            amount = delta.x() if delta.x() else delta.y()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - amount)
            event.accept()
        else:
            if delta.y():
                self.verticalScrollBar().setValue(
                    self.verticalScrollBar().value() - delta.y())
            if delta.x():
                self.horizontalScrollBar().setValue(
                    self.horizontalScrollBar().value() - delta.x())
            event.accept()
