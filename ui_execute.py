import os
import json
import pandas as pd
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QHeaderView,
    QGroupBox,
    QMessageBox,
    QSplitter,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsTextItem,
    QMenu,
    QTableView,
    QGraphicsPathItem,
    QTabWidget,
    QAction,
    QProgressBar,
    QDialog,
    QDialogButtonBox,
    QCheckBox,
)
from PyQt5.QtCore import Qt, QPointF, pyqtSignal, QRectF, QLineF
from PyQt5.QtGui import (
    QFont,
    QColor,
    QPen,
    QBrush,
    QPainterPath,
    QPolygonF,
    QPainter,
    QFontMetrics,
)

from engine import WorkflowEngine
from ui_components import PandasModel


class DataSourceMappingDialog(QDialog):
    def __init__(self, file_mapping, file_context, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据源路径管理")
        self.setMinimumSize(700, 350)
        self.file_mapping = file_mapping
        self.file_context = file_context
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        lbl_info = QLabel("提示：双击下方的【当前文件路径】可重新关联本地文件。")
        lbl_info.setStyleSheet("color: #666; font-size: 12px; font-weight: bold;")
        layout.addWidget(lbl_info)

        self.table = QTableWidget(0, 2)
        self.table.setStyleSheet("border: 1px solid #ddd; background-color: white;")
        self.table.setHorizontalHeaderLabels(["当前文件路径", "所属节点 / Sheet"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )

        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.change_mapping_file)
        layout.addWidget(self.table)

        self.refresh_table()

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def refresh_table(self):
        self.table.setRowCount(0)
        for orig_path, actual_path in self.file_mapping.items():
            row = self.table.rowCount()
            self.table.insertRow(row)

            item_path = QTableWidgetItem(actual_path)
            item_path.setData(Qt.UserRole, orig_path)
            if actual_path != orig_path:
                item_path.setBackground(QColor("#E8F5E9"))
                item_path.setToolTip(f"原始定义: {orig_path}")

            contexts = self.file_context.get(orig_path, [])
            item_context = QTableWidgetItem(" | ".join(contexts))
            item_context.setForeground(QColor("#1565C0"))

            self.table.setItem(row, 0, item_path)
            self.table.setItem(row, 1, item_context)

    def change_mapping_file(self, row, col):
        if col == 0:
            current_item = self.table.item(row, 0)
            orig_path = current_item.data(Qt.UserRole)

            new_path, _ = QFileDialog.getOpenFileName(
                self, "重新关联数据源", "", "数据文件 (*.xlsx *.xls *.csv)"
            )
            if new_path:
                self.file_mapping[orig_path] = new_path
                self.refresh_table()


class ExecuteNodeItem(QGraphicsPathItem):
    def __init__(self, table_name, text, action_type=""):
        super().__init__()
        self.table_name = table_name
        self.action_type = action_type
        self.status = "pending"
        self.has_data = False

        self.setFlag(QGraphicsPathItem.ItemIsSelectable)

        # 修复显示不全：动态计算节点物理宽度并增加悬浮提示
        font = QFont("Microsoft YaHei", 9, QFont.Bold)
        metrics = QFontMetrics(font)
        text_width = metrics.boundingRect(text).width()
        self.width = min(max(160, text_width + 40), 350)
        self.height = 60
        self.setToolTip(f"[{action_type}] {text}")

        self.text_item = QGraphicsTextItem(text, self)
        self.text_item.setFont(font)
        self.text_item.setDefaultTextColor(Qt.black)
        self.text_item.setPos(5, 25)

        self.type_item = QGraphicsTextItem(action_type, self)
        self.type_item.setFont(QFont("Arial", 8, QFont.Bold))
        self.type_item.setDefaultTextColor(Qt.white)
        self.type_item.setPos(5, 0)

    def set_status(self, status):
        self.status = status
        self.update()

    def boundingRect(self):
        return QRectF(-5, -5, self.width + 10, self.height + 10)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)

        if self.isSelected():
            pen = QPen(QColor("#2196F3"), 3)
        elif self.status == "success":
            pen = QPen(QColor("#4CAF50"), 3)
        elif self.status == "error":
            pen = QPen(QColor("#F44336"), 3)
        else:
            pen = QPen(QColor("#9E9E9E"), 2)

        painter.setPen(pen)
        painter.setBrush(QBrush(QColor("white")))
        rect = QRectF(0, 0, self.width, self.height)
        painter.drawRoundedRect(rect, 5, 5)

        header_color = "#607D8B"
        if self.status == "success":
            header_color = "#4CAF50"
        if self.status == "error":
            header_color = "#F44336"

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(header_color)))
        header_rect = QRectF(0, 0, self.width, 20)
        painter.drawRoundedRect(header_rect, 5, 5)
        painter.drawRect(QRectF(0, 10, self.width, 10))

        painter.setBrush(QBrush(QColor("#ccc")))
        painter.setPen(QPen(QColor("#666"), 1))
        if self.action_type != "数据源导入":
            painter.drawEllipse(QPointF(0, self.height / 2), 4, 4)
        painter.drawEllipse(QPointF(self.width, self.height / 2), 4, 4)

        if self.status == "success":
            painter.setFont(QFont("Microsoft YaHei", 8))
            if self.has_data:
                painter.setPen(QPen(QColor("#4CAF50")))
                painter.drawText(
                    QRectF(self.width - 45, self.height - 20, 40, 20),
                    Qt.AlignRight | Qt.AlignVCenter,
                    "[保留]",
                )
            else:
                painter.setPen(QPen(QColor("#9E9E9E")))
                painter.drawText(
                    QRectF(self.width - 45, self.height - 20, 40, 20),
                    Qt.AlignRight | Qt.AlignVCenter,
                    "[释放]",
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
        painter.fillRect(rect, QColor("#f0f2f5"))
        grid_size = 20
        left = int(rect.left()) - (int(rect.left()) % grid_size)
        top = int(rect.top()) - (int(rect.top()) % grid_size)
        lines = []
        for x in range(left, int(rect.right()), grid_size):
            lines.append(QLineF(x, rect.top(), x, rect.bottom()))
        for y in range(top, int(rect.bottom()), grid_size):
            lines.append(QLineF(rect.left(), y, rect.right(), y))
        painter.setPen(QPen(QColor("#e0e4e8"), 1))
        painter.drawLines(lines)

    def render_workflow(self, workflow_config):
        self.scene.clear()
        self.node_items_dict.clear()
        if not workflow_config:
            return

        steps = workflow_config.get("steps", [])

        action_names = {
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

        undirected_adj = {n: [] for n in unique_items}
        for n in unique_items:
            for dest in item_edges_out[n]:
                undirected_adj[n].append(dest)
                undirected_adj[dest].append(n)

        visited = set()
        components = []
        for n in unique_items:
            if n not in visited:
                comp = []
                q = [n]
                visited.add(n)
                while q:
                    curr = q.pop(0)
                    comp.append(curr)
                    for neighbor in undirected_adj[curr]:
                        if neighbor not in visited:
                            visited.add(neighbor)
                            q.append(neighbor)
                components.append(comp)

        x_spacing = 320
        y_spacing = 140
        current_base_y = 100

        for comp_nodes in components:
            in_degree = {n: 0 for n in comp_nodes}
            adj_list = {n: [] for n in comp_nodes}
            for n in comp_nodes:
                for dest in item_edges_out[n]:
                    adj_list[n].append(dest)
                    in_degree[dest] += 1

            queue = [n for n in comp_nodes if in_degree[n] == 0]
            layer_map = {n: 0 for n in queue}

            while queue:
                curr = queue.pop(0)
                for neighbor in adj_list[curr]:
                    layer_map[neighbor] = max(
                        layer_map.get(neighbor, 0), layer_map[curr] + 1
                    )
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

            layers = {}
            for n in comp_nodes:
                l = layer_map.get(n, 0)
                if l not in layers:
                    layers[l] = []
                layers[l].append(n)

            for l in layers:
                layers[l].sort(key=lambda n: n.table_name)

            max_nodes_in_layer = (
                max([len(lst) for lst in layers.values()]) if layers else 1
            )
            comp_height = (max_nodes_in_layer - 1) * y_spacing
            comp_center_y = current_base_y + comp_height / 2

            for l_idx in sorted(layers.keys()):
                layer_nodes = layers[l_idx]
                num_nodes = len(layer_nodes)
                layer_height = (num_nodes - 1) * y_spacing
                start_y = comp_center_y - layer_height / 2

                stagger_offset = (y_spacing * 0.5) if (l_idx % 2 != 0) else 0

                for i, node in enumerate(layer_nodes):
                    x = 50 + l_idx * x_spacing
                    y = start_y + i * y_spacing + stagger_offset
                    node.setPos(x, y)

            current_base_y += comp_height + y_spacing * 2.0

        for src, dests in item_edges_out.items():
            for dest in dests:
                self.draw_edge(src, dest)

        rect = self.scene.itemsBoundingRect()
        self.scene.setSceneRect(rect.adjusted(-200, -200, 200, 200))
        self.centerOn(rect.center())

    def draw_edge(self, start_item, end_item):
        sp = start_item.pos() + QPointF(start_item.width, start_item.height / 2)
        ep = end_item.pos() + QPointF(0, end_item.height / 2)

        path = QPainterPath()
        path.moveTo(sp)
        dist = min(max(abs(ep.x() - sp.x()) * 0.4, 60), 200)
        ctrl1 = QPointF(sp.x() + dist, sp.y())
        ctrl2 = QPointF(ep.x() - dist, ep.y())
        path.cubicTo(ctrl1, ctrl2, ep)

        edge = self.scene.addPath(path, QPen(QColor("#B0BEC5"), 2))
        edge.setZValue(-1)

        arrow_size = 8
        polygon = QPolygonF(
            [
                ep,
                ep + QPointF(-arrow_size, -arrow_size / 2),
                ep + QPointF(-arrow_size, arrow_size / 2),
            ]
        )
        arrow_item = self.scene.addPolygon(
            polygon, QPen(Qt.NoPen), QBrush(QColor("#B0BEC5"))
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


class ExecuteModeWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.workflow_config = None
        self.current_workflow_path = None
        self.file_mapping = {}
        self.file_context = {}
        self.final_pool = {}
        self.current_preview_table = None
        self.engine_thread = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 10)

        top_group = QGroupBox()
        top_group.setFixedHeight(65)
        top_group.setStyleSheet(
            "QGroupBox { border: 1px solid #ddd; background-color: white; border-radius: 4px; }"
        )
        top_layout = QHBoxLayout(top_group)
        top_layout.setContentsMargins(15, 0, 15, 0)

        self.btn_load_json = QPushButton("[导入] 工作流配置")
        self.btn_load_json.setFixedHeight(35)
        self.btn_load_json.clicked.connect(self.load_workflow_config)

        self.btn_mapping = QPushButton("[设置] 数据源映射")
        self.btn_mapping.setFixedHeight(35)
        self.btn_mapping.setStyleSheet("color: #E65100; font-weight: bold;")
        self.btn_mapping.clicked.connect(self.show_mapping_dialog)
        self.btn_mapping.setEnabled(False)

        self.cb_debug = QCheckBox("调试模式 (保留所有过程表)")
        self.cb_debug.setStyleSheet("font-weight: bold; color: #1976D2;")
        self.cb_debug.setToolTip(
            "开启后，引擎将保留所有节点的中间数据以便随时点击预览。\n注意：大数据量下会消耗更多内存！"
        )

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #ccc; border-radius: 10px; background-color: #f0f0f0; }
            QProgressBar::chunk { background-color: #4CAF50; border-radius: 10px; }
        """)

        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet(
            "color: #666; font-weight: bold; min-width: 150px;"
        )

        self.btn_run = QPushButton("[启动] 执行引擎")
        self.btn_run.setFixedHeight(35)
        self.btn_run.setStyleSheet(
            "background-color: #E91E63; color: white; font-weight: bold; padding: 0 30px; border-radius: 4px;"
        )
        self.btn_run.clicked.connect(self.run_engine)
        self.btn_run.setEnabled(False)

        top_layout.addWidget(self.btn_load_json)
        top_layout.addWidget(self.btn_mapping)
        top_layout.addSpacing(20)
        top_layout.addWidget(self.cb_debug)
        top_layout.addSpacing(20)
        top_layout.addWidget(self.progress_bar, stretch=1)
        top_layout.addSpacing(10)
        top_layout.addWidget(self.lbl_status)
        top_layout.addWidget(self.btn_run)

        layout.addWidget(top_group)

        self.main_splitter = QSplitter(Qt.Vertical)

        canvas_panel = QWidget()
        canvas_layout = QVBoxLayout(canvas_panel)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        lbl_canvas = QLabel(" 监控大盘 (按住中键漫游 / 滚轮缩放 / 右键导出)")
        lbl_canvas.setFont(QFont("Arial", 10, QFont.Bold))

        self.graph_view = WorkflowGraphView()
        self.graph_view.node_clicked.connect(self.on_node_clicked)
        self.graph_view.request_export.connect(self.export_single_table)

        canvas_layout.addWidget(lbl_canvas)
        canvas_layout.addWidget(self.graph_view)

        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.setStyleSheet("""
            QTabBar::tab { padding: 8px 15px; font-weight: bold; background: #e0e0e0; border: 1px solid #ccc; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; }
            QTabBar::tab:selected { background: white; color: #2196F3; }
            QTabWidget::pane { border: 1px solid #ccc; background: white; }
        """)

        self.tab_preview = QWidget()
        preview_layout = QVBoxLayout(self.tab_preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        preview_header = QHBoxLayout()
        self.preview_title = QLabel("请在上方画布中点击任意节点进行预览")
        self.preview_title.setStyleSheet("padding: 5px; color: gray;")

        self.btn_export_preview = QPushButton("[导出] 当前表")
        self.btn_export_preview.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold; padding: 4px 15px; border-radius: 4px;"
        )
        self.btn_export_preview.hide()
        self.btn_export_preview.clicked.connect(self.export_current_table)

        preview_header.addWidget(self.preview_title)
        preview_header.addStretch(1)
        preview_header.addWidget(self.btn_export_preview)

        self.result_table = QTableView()
        self.result_table.setStyleSheet(
            "QTableView { border: none; gridline-color: #eee; } QHeaderView::section { background-color: #E1F5FE; font-weight: bold; border: 1px solid #ccc; padding: 4px; }"
        )
        self.result_table.setAlternatingRowColors(True)

        preview_layout.addLayout(preview_header)
        preview_layout.addWidget(self.result_table)

        self.tab_logs = QWidget()
        logs_layout = QVBoxLayout(self.tab_logs)
        logs_layout.setContentsMargins(0, 0, 0, 0)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet(
            "background-color: #1E1E1E; color: #D4D4D4; font-family: Consolas; border: none; padding: 8px; font-size: 13px;"
        )
        logs_layout.addWidget(self.log_output)

        self.bottom_tabs.addTab(self.tab_preview, "数据预览")
        self.bottom_tabs.addTab(self.tab_logs, "运行日志")

        self.main_splitter.addWidget(canvas_panel)
        self.main_splitter.addWidget(self.bottom_tabs)
        self.main_splitter.setStretchFactor(0, 6)
        self.main_splitter.setStretchFactor(1, 4)

        layout.addWidget(self.main_splitter)

    def show_mapping_dialog(self):
        dlg = DataSourceMappingDialog(self.file_mapping, self.file_context, self)
        if dlg.exec_() == QDialog.Accepted:
            has_changes = any(k != v for k, v in self.file_mapping.items())
            if has_changes:
                reply = QMessageBox.question(
                    self,
                    "同步配置",
                    "检测到路径已变更，是否将新路径永久更新并覆盖当前 JSON 配置文件？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    self.save_config_to_json()

            self.graph_view.render_workflow(self.workflow_config)

    def save_config_to_json(self):
        if not self.current_workflow_path or not self.workflow_config:
            return

        try:
            for step in self.workflow_config.get("steps", []):
                if step["action"] == "load_file":
                    p = step["params"]
                    old_path = p.get("file_path")
                    if old_path in self.file_mapping:
                        p["file_path"] = self.file_mapping[old_path]

            with open(self.current_workflow_path, "w", encoding="utf-8") as f:
                json.dump(self.workflow_config, f, ensure_ascii=False, indent=4)

            self.log_print(
                f"[系统] 路径配置已永久保存至：{os.path.basename(self.current_workflow_path)}"
            )

            self._load_workflow_from_path(self.current_workflow_path)

        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法回写配置文件：\n{str(e)}")

    def log_print(self, text):
        if "成功" in text:
            color = "#4CAF50"
        elif "失败" in text or "错误" in text:
            color = "#F44336"
        elif "===" in text:
            color = "#2196F3"
        else:
            color = "#D4D4D4"

        self.log_output.append(f'<span style="color:{color};">{text}</span>')
        self.log_output.verticalScrollBar().setValue(
            self.log_output.verticalScrollBar().maximum()
        )

    def load_workflow_config(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "加载工作流", "", "JSON (*.json)"
        )
        if not file_path:
            return
        self._load_workflow_from_path(file_path, saved_mappings=None)

    def _load_workflow_from_path(self, file_path, saved_mappings=None):
        if not os.path.exists(file_path):
            self.log_print(f"[错误] 工作流文件丢失，无法加载: {file_path}")
            return

        with open(file_path, "r", encoding="utf-8") as f:
            self.workflow_config = json.load(f)

        self.current_workflow_path = file_path
        self.file_mapping.clear()
        self.file_context.clear()

        for step in self.workflow_config.get("steps", []):
            if step["action"] == "load_file":
                orig_path = step["params"].get("file_path")
                out_name = step.get("out_name", "未知节点")
                sheet_name = step["params"].get("sheet_name", "默认")

                if orig_path:
                    if orig_path not in self.file_mapping:
                        actual_path = orig_path
                        if saved_mappings and orig_path in saved_mappings:
                            actual_path = saved_mappings[orig_path]
                        self.file_mapping[orig_path] = actual_path

                    context_str = f"[{out_name} - Sheet: {sheet_name}]"
                    if orig_path not in self.file_context:
                        self.file_context[orig_path] = []
                    self.file_context[orig_path].append(context_str)

        self.graph_view.render_workflow(self.workflow_config)

        self.btn_mapping.setEnabled(True)
        self.btn_run.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("等待执行...")
        self.btn_export_preview.hide()

        wf_name = self.workflow_config.get("workflow_name", "未命名")
        steps_count = len(self.workflow_config.get("steps", []))
        self.log_print(f"[成功] 成功加载工作流: {wf_name} (共 {steps_count} 个节点)")

    def get_state(self):
        return {
            "last_workflow_path": self.current_workflow_path,
            "file_mappings": self.file_mapping,
        }

    def restore_state(self, workflow_path, saved_mappings):
        if workflow_path:
            self._load_workflow_from_path(workflow_path, saved_mappings)

    def on_node_clicked(self, table_name, is_action):
        if not table_name:
            return

        self.bottom_tabs.setCurrentIndex(0)
        self.current_preview_table = table_name

        if table_name in self.final_pool:
            df = self.final_pool[table_name]
            self.preview_title.setText(
                f"当前预览: 【{table_name}】 ({df.shape[0]} 行, {df.shape[1]} 列)"
            )
            self.preview_title.setStyleSheet(
                "padding: 5px; color: #2196F3; font-weight: bold;"
            )

            model = PandasModel(df)
            self.result_table.setModel(model)
            self.btn_export_preview.show()
        else:
            self.preview_title.setText(
                f"表 【{table_name}】 无数据。可能是未执行或作为中间表内存已被释放。"
            )
            self.preview_title.setStyleSheet(
                "padding: 5px; color: #E91E63; font-weight: bold;"
            )
            self.result_table.setModel(None)
            self.btn_export_preview.hide()

    def run_engine(self):
        if not self.workflow_config:
            return

        self.bottom_tabs.setCurrentIndex(1)
        self.log_output.clear()

        self.btn_run.setEnabled(False)
        self.btn_run.setText("引擎运转中...")
        self.btn_run.setStyleSheet(
            "background-color: #9E9E9E; color: white; font-weight: bold; padding: 0 30px; border-radius: 4px;"
        )
        self.btn_load_json.setEnabled(False)
        self.btn_mapping.setEnabled(False)
        self.cb_debug.setEnabled(False)

        self.progress_bar.setRange(0, 0)
        self.lbl_status.setText("正在跑批计算...")
        self.lbl_status.setStyleSheet("color: #E65100; font-weight: bold;")

        for item in self.graph_view.node_items_dict.values():
            item.has_data = False
            item.set_status("pending")

        keep_mem = self.cb_debug.isChecked()
        self.engine_thread = WorkflowEngine(
            self.file_mapping, self.workflow_config, keep_intermediates=keep_mem
        )

        self.engine_thread.log_signal.connect(self.log_print)
        self.engine_thread.finished_signal.connect(self.on_engine_finished)
        self.engine_thread.start()

    def on_engine_finished(self, success, pool):
        self.btn_run.setEnabled(True)
        self.btn_run.setText("[运行] 再次执行")
        self.btn_run.setStyleSheet(
            "background-color: #E91E63; color: white; font-weight: bold; padding: 0 30px; border-radius: 4px;"
        )
        self.btn_load_json.setEnabled(True)
        self.btn_mapping.setEnabled(True)
        self.cb_debug.setEnabled(True)

        self.progress_bar.setRange(0, 100)

        if success:
            self.progress_bar.setValue(100)
            self.lbl_status.setText("[成功] 执行完毕")
            self.lbl_status.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.graph_view.set_all_nodes_status("success")

            self.final_pool = pool

            for item in set(self.graph_view.node_items_dict.values()):
                if item.status == "success":
                    item.has_data = item.table_name in self.final_pool
                item.update()

            QMessageBox.information(
                self, "成功", "工作流执行完毕！\n请点击下方【数据预览】标签查看结果。"
            )
        else:
            self.progress_bar.setValue(0)
            self.lbl_status.setText("[失败] 执行中断")
            self.lbl_status.setStyleSheet("color: #F44336; font-weight: bold;")
            self.graph_view.set_all_nodes_status("error")

            QMessageBox.critical(
                self, "执行失败", "工作流执行遇到错误，请查看【运行日志】定位问题节点。"
            )

    def export_current_table(self):
        if self.current_preview_table:
            self.export_single_table(self.current_preview_table)

    def export_single_table(self, table_name):
        if table_name not in self.final_pool:
            QMessageBox.warning(self, "错误", "该表尚无结果数据或内存已被释放。")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            f"导出 {table_name}",
            f"{table_name}.xlsx",
            "Excel (*.xlsx);;CSV (*.csv)",
        )
        if path:
            try:
                if path.endswith(".csv"):
                    self.final_pool[table_name].to_csv(
                        path, index=False, encoding="utf-8-sig"
                    )
                else:
                    self.final_pool[table_name].to_excel(path, index=False)
                self.log_print(f"[成功] 成功导出表格至: {path}")
                QMessageBox.information(self, "导出成功", f"文件已保存：\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", str(e))
