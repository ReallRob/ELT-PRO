from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QGraphicsPathItem,
    QMessageBox,
)
try:
    from PyQt5 import sip
except ImportError:  # pragma: no cover - depends on PyQt packaging
    sip = None
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
from core.workflow.schema import BATCH_MAP_ACTIONS


METADATA_NODE_TYPES = ("advanced_param_mapping",)


class NodeItem(QGraphicsItem):
    def __init__(
        self,
        node_id,
        action_type,
        title,
        color="#1976D2",
        x=0,
        y=0,
        operator_name="",
    ):
        super().__init__()
        self.node_id = node_id
        self.action_type = action_type
        self.title = title
        self.color = color
        self.operator_name = operator_name or action_type

        # 修复显示不全：动态计算文本宽度，自适应节点大小
        font = QFont("Microsoft YaHei", 9)
        metrics = QFontMetrics(font)
        title_width = metrics.boundingRect(self.title).width()
        op_width = QFontMetrics(QFont("Microsoft YaHei", 10, QFont.Bold)).boundingRect(
            self.operator_name
        ).width()
        # 保证基础宽度 160，最大不超过 350
        self.width = min(max(170, max(title_width, op_width) + 44), 360)
        self.height = 64

        # 增加悬浮提示，确保任何情况下都能看全
        self.setToolTip(f"[{self.operator_name}] {title}")

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

    def has_input_port(self):
        return self.action_type not in ("load_file", "import_template") + METADATA_NODE_TYPES

    def has_output_port(self):
        return self.action_type not in METADATA_NODE_TYPES

    def boundingRect(self):
        return QRectF(-10, -10, self.width + 20, self.height + 20)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制主节点框
        if self.isSelected():
            pen = QPen(QColor("#0284C7"), 3)
        elif self.is_dirty:
            pen = QPen(QColor("#FFC107"), 3)
        else:
            pen = QPen(QColor(self.color), 2)

        painter.setPen(pen)
        rect = QRectF(0, 0, self.width, self.height)
        if self.isSelected():
            painter.setPen(QPen(QColor(14, 165, 233, 85), 8))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), 8, 8)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor("#EFF6FF")))
        else:
            painter.setBrush(QBrush(QColor("white")))
        painter.drawRoundedRect(rect, 5, 5)

        # 绘制标题栏背景
        painter.setPen(Qt.NoPen)
        header_color = QColor("#0284C7") if self.isSelected() else QColor(self.color)
        painter.setBrush(QBrush(header_color))
        header_rect = QRectF(0, 0, self.width, 24)
        painter.drawRoundedRect(header_rect, 5, 5)
        painter.drawRect(QRectF(0, 12, self.width, 12))

        # 绘制算子类型文字
        painter.setPen(QColor("white"))
        op_font = QFont("Microsoft YaHei", 10, QFont.Bold)
        painter.setFont(op_font)
        op_metrics = QFontMetrics(op_font)
        elided_op = op_metrics.elidedText(
            self.operator_name, Qt.ElideRight, int(self.width - 16)
        )
        painter.drawText(header_rect, Qt.AlignCenter, elided_op)

        # 绘制动态名称文字
        painter.setPen(QColor("#1F2933"))
        font = QFont("Microsoft YaHei", 8)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        elided_title = metrics.elidedText(
            self.title, Qt.ElideRight, int(self.width - 18)
        )
        painter.drawText(
            QRectF(8, 28, self.width - 16, 28),
            Qt.AlignCenter,
            elided_title,
        )

        # 将连接引脚（端口）横向分布在左右两侧
        port_fill = QColor("#38BDF8") if self.isSelected() else QColor("#ccc")
        port_border = QColor("#0369A1") if self.isSelected() else QColor("#666")
        painter.setBrush(QBrush(port_fill))
        painter.setPen(QPen(port_border, 1))

        # 左侧输入端口 (剔除不需要输入的源头节点)
        if self.has_input_port():
            painter.drawEllipse(QPointF(0, self.height / 2), 5, 5)

        # 右侧输出端口
        if self.has_output_port():
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
            line_width = 4
        else:
            line_color = QColor("#999999")
            line_width = 2

        if self.isSelected():
            painter.setPen(
                QPen(QColor(244, 67, 54, 70), 9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            )
            painter.drawPath(self.path())

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
    @staticmethod
    def _is_deleted_qt_object(obj):
        if obj is None or sip is None:
            return False
        try:
            return sip.isdeleted(obj)
        except Exception:
            return False

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
            if isinstance(item, NodeItem) and item.has_output_port():
                if event.scenePos().x() > item.scenePos().x() + item.width - 25:
                    self.start_node = item
                    self.drawing_edge = True
                    self.temp_edge = QGraphicsPathItem()
                    self.temp_edge.setPen(QPen(QColor("#2196F3"), 2, Qt.DashLine))
                    self.addItem(self.temp_edge)
                    return

            if isinstance(item, NodeItem):
                self.node_selected.emit(item)
            elif item is None:
                self.node_selected.emit(None)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.scenePos(), self.views()[0].transform())
        if event.button() == Qt.LeftButton and isinstance(item, NodeItem):
            self.node_double_clicked.emit(item)
            event.accept()
            return
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
        if node.action_type in ("load_file",) + METADATA_NODE_TYPES:
            return 0
        if node.action_type == "import_template":
            return 0
        if node.action_type == "code_block":
            return 10000
        if node.action_type == "insert_block":
            return 2
        if node.action_type == "save_template":
            return 1
        if node.action_type in BATCH_MAP_ACTIONS:
            return 10000
        if node.action_type in ("left_join", "concat_rows"):
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

    def _is_semantic_edge_allowed(self, start_node, end_node):
        if end_node.action_type == "import_template":
            QMessageBox.warning(None, "连线被拒绝", "加载模板是模板主线源头，不接收上游输入。")
            return False
        if end_node.action_type == "save_template" and start_node.action_type not in {"import_template", "insert_block", "code_block"}:
            QMessageBox.warning(None, "连线被拒绝", "保存模板只接收模板主线 workbook。")
            return False
        return True

    def mouseReleaseEvent(self, event):
        if self.drawing_edge:
            self.drawing_edge = False
            if self.temp_edge:
                self.removeItem(self.temp_edge)
            end_item = self.itemAt(event.scenePos(), self.views()[0].transform())
            if (
                isinstance(end_item, NodeItem)
                and end_item != self.start_node
                and end_item.has_input_port()
            ):
                existing_edges = [
                    edge
                    for edge in self.start_node.edges_out
                    if edge.dest_node == end_item
                ]
                if not existing_edges:
                    if self._would_create_cycle(self.start_node, end_item):
                        QMessageBox.warning(None, "连线被拒绝", "非法操作：死循环！")
                    elif not self._is_semantic_edge_allowed(self.start_node, end_item):
                        pass
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
        selected = list(self.selectedItems())
        if any(isinstance(item, NodeItem) for item in selected):
            self.node_selected.emit(None)
        for item in selected:
            if self._is_deleted_qt_object(item):
                continue
            if isinstance(item, NodeItem):
                for edge in list(item.edges_in):
                    if self._is_deleted_qt_object(edge):
                        continue
                    if not self._is_deleted_qt_object(edge.source_node) and edge in edge.source_node.edges_out:
                        edge.source_node.edges_out.remove(edge)
                    self.removeItem(edge)
                for edge in list(item.edges_out):
                    if self._is_deleted_qt_object(edge):
                        continue
                    if not self._is_deleted_qt_object(edge.dest_node) and edge in edge.dest_node.edges_in:
                        edge.dest_node.edges_in.remove(edge)
                    self.removeItem(edge)
                self.removeItem(item)
            elif isinstance(item, EdgeItem):
                if self._is_deleted_qt_object(item):
                    continue
                if not self._is_deleted_qt_object(item.source_node) and item in item.source_node.edges_out:
                    item.source_node.edges_out.remove(item)
                if (
                    item.dest_node is not None
                    and not self._is_deleted_qt_object(item.dest_node)
                    and item in item.dest_node.edges_in
                ):
                    item.dest_node.edges_in.remove(item)
                self.removeItem(item)
        self.edge_changed.emit()


class NodeCanvasView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.copy_requested = None
        self.setRenderHint(QPainter.Antialiasing)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._is_panning = False
        self._pan_button = None

    def center_on_canvas(self):
        self.centerOn(QPointF(0, 0))

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if item is None and event.button() == Qt.LeftButton:
            if event.modifiers() == Qt.ShiftModifier:
                self.setDragMode(QGraphicsView.RubberBandDrag)
            else:
                self.scene().clearSelection()
                if hasattr(self.scene(), "node_selected"):
                    self.scene().node_selected.emit(None)
                self.setDragMode(QGraphicsView.NoDrag)
                self._start_panning(event, Qt.LeftButton)
                return
        else:
            self.setDragMode(QGraphicsView.NoDrag)

        super().mousePressEvent(event)

    def _start_panning(self, event, button):
        self._is_panning = True
        self._pan_button = button
        self._pan_start_x = event.x()
        self._pan_start_y = event.y()
        self.setCursor(Qt.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._is_panning:
            dx = event.x() - self._pan_start_x
            dy = event.y() - self._pan_start_y
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - dx)
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - dy)
            self._pan_start_x = event.x()
            self._pan_start_y = event.y()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_panning and event.button() == self._pan_button:
            self._is_panning = False
            self._pan_button = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return

        super().mouseReleaseEvent(event)
        self.setDragMode(QGraphicsView.NoDrag)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.scene().delete_selected_items()
        elif event.modifiers() == Qt.ControlModifier and event.key() in (Qt.Key_C, Qt.Key_D):
            if self.copy_requested is not None:
                self.copy_requested()
                event.accept()
            else:
                super().keyPressEvent(event)
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
