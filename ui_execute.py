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
    QFrame,
    QMessageBox,
    QSplitter,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsTextItem,
    QMenu,
    QTableView,
    QGraphicsPathItem,
    QAction,
    QProgressBar,
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QGraphicsDropShadowEffect,
)
from PyQt5.QtCore import Qt, QPointF, pyqtSignal, QRectF

import utils
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
from table_model import PandasModel
from parameter_dialog import RuntimeParametersDialog


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
            "input_param": "输入参数",
            "param_mapping": "参数映射",
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
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # === Top Toolbar ===
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.btn_load_json = QPushButton("导入工作流")
        self.btn_load_json.setFixedHeight(32)
        self.btn_load_json.setCursor(Qt.PointingHandCursor)
        self.btn_load_json.setStyleSheet(
            "QPushButton { background: white; border: 1px solid #ccc; border-radius: 4px; padding: 4px 14px; font-weight: bold; }"
            "QPushButton:hover { background: #f0f0f0; }"
        )
        self.btn_load_json.clicked.connect(self.load_workflow_config)

        self.btn_mapping = QPushButton("数据源映射")
        self.btn_mapping.setFixedHeight(32)
        self.btn_mapping.setCursor(Qt.PointingHandCursor)
        self.btn_mapping.setStyleSheet(
            "QPushButton { background: white; border: 1px solid #ccc; border-radius: 4px; padding: 4px 14px; color: #E65100; font-weight: bold; }"
            "QPushButton:hover { background: #FFF3E0; }"
        )
        self.btn_mapping.clicked.connect(self.show_mapping_dialog)
        self.btn_mapping.setEnabled(False)

        self.btn_params = QPushButton("运行参数")
        self.btn_params.setFixedHeight(32)
        self.btn_params.setCursor(Qt.PointingHandCursor)
        self.btn_params.setStyleSheet(
            "QPushButton { background: white; border: 1px solid #ccc; border-radius: 4px; padding: 4px 14px; color: #1565C0; font-weight: bold; }"
            "QPushButton:hover { background: #E3F2FD; }"
        )
        self.btn_params.clicked.connect(self.show_runtime_parameters_dialog)
        self.btn_params.setEnabled(False)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("color: #ddd;")

        self.btn_run = QPushButton("▶ 运行引擎")
        self.btn_run.setFixedHeight(32)
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.setStyleSheet(
            "background-color: #E91E63; color: white; font-weight: bold; padding: 4px 20px; border-radius: 4px;"
        )
        self.btn_run.clicked.connect(self.run_engine)
        self.btn_run.setEnabled(False)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #ddd;")

        self.cb_debug = QCheckBox("保留中间表")
        self.cb_debug.setStyleSheet("font-weight: bold; color: #1976D2;")
        self.cb_debug.setToolTip("开启后引擎保留所有节点的中间数据以便预览。")

        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet("color: #666; font-weight: bold; font-size: 12px;")

        toolbar.addWidget(self.btn_load_json)
        toolbar.addWidget(self.btn_mapping)
        toolbar.addWidget(self.btn_params)
        toolbar.addWidget(sep1)
        toolbar.addWidget(self.btn_run)
        toolbar.addWidget(sep2)
        toolbar.addWidget(self.cb_debug)
        toolbar.addStretch(1)
        toolbar.addWidget(self.lbl_status)
        layout.addLayout(toolbar)

        # === Main Content: Info Panel | Graph + Bottom ===
        self.main_splitter = QSplitter(Qt.Horizontal)

        # -- Left: Workflow Info Panel --
        info_panel = QWidget()
        info_panel.setMaximumWidth(220)
        info_panel.setMinimumWidth(140)
        info_panel.setStyleSheet("background: #f8f9fa; border: 1px solid #ddd; border-radius: 4px;")
        info_layout = QVBoxLayout(info_panel)
        info_layout.setContentsMargins(8, 8, 8, 8)
        info_layout.setSpacing(6)

        info_title = QLabel("工作流信息")
        info_title.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        info_title.setStyleSheet("border: none;")

        self.info_name = QLabel("未加载")
        self.info_name.setWordWrap(True)
        self.info_name.setStyleSheet("border: none; color: #333; font-size: 11px;")

        self.info_steps = QLabel("步骤: —")
        self.info_steps.setStyleSheet("border: none; color: #666; font-size: 11px;")

        self.info_files_label = QLabel("数据源:")
        self.info_files_label.setStyleSheet("border: none; color: #666; font-size: 10px; font-weight: bold;")
        self.info_files = QLabel("—")
        self.info_files.setWordWrap(True)
        self.info_files.setStyleSheet("border: none; color: #999; font-size: 10px;")

        info_layout.addWidget(info_title)
        info_layout.addWidget(self.info_name)
        info_layout.addWidget(self.info_steps)
        info_layout.addWidget(self.info_files_label)
        info_layout.addWidget(self.info_files)
        info_layout.addStretch(1)

        # -- Right: Graph + Bottom Content --
        right_splitter = QSplitter(Qt.Vertical)

        graph_panel = QWidget()
        graph_layout = QVBoxLayout(graph_panel)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.setSpacing(2)
        lbl_graph = QLabel(" 监控大盘 (中键漫游 | Ctrl+滚轮缩放 | 右键导出)")
        lbl_graph.setFont(QFont("Arial", 9, QFont.Bold))
        lbl_graph.setStyleSheet("color: #666; padding: 2px;")

        self.graph_view = WorkflowGraphView()
        self.graph_view.node_clicked.connect(self.on_node_clicked)
        self.graph_view.request_export.connect(self.export_single_table)

        graph_layout.addWidget(lbl_graph)
        graph_layout.addWidget(self.graph_view)

        # -- Bottom: Preview | Logs (side by side) --
        bottom_splitter = QSplitter(Qt.Horizontal)

        # Preview
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(4, 4, 4, 4)
        preview_layout.setSpacing(2)

        preview_header = QHBoxLayout()
        self.preview_title = QLabel("点击画布节点预览数据")
        self.preview_title.setStyleSheet("padding: 3px; color: gray; font-size: 11px;")

        self.btn_export_preview = QPushButton("导出")
        self.btn_export_preview.setFixedHeight(24)
        self.btn_export_preview.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold; padding: 2px 12px; border-radius: 3px; font-size: 11px;"
        )
        self.btn_export_preview.hide()
        self.btn_export_preview.clicked.connect(self.export_current_table)

        preview_header.addWidget(self.preview_title, stretch=1)
        preview_header.addWidget(self.btn_export_preview)

        self.result_table = QTableView()
        self.result_table.setStyleSheet(
            "QTableView { border: 1px solid #eee; gridline-color: #f0f0f0; } "
            "QHeaderView::section { background-color: #E1F5FE; font-weight: bold; border: 1px solid #ddd; padding: 3px; font-size: 11px; }"
        )
        self.result_table.setAlternatingRowColors(True)

        preview_layout.addLayout(preview_header)
        preview_layout.addWidget(self.result_table)

        # Logs
        logs_panel = QWidget()
        logs_layout = QVBoxLayout(logs_panel)
        logs_layout.setContentsMargins(4, 4, 4, 4)
        logs_layout.setSpacing(2)
        logs_label = QLabel(" 运行日志")
        logs_label.setFont(QFont("Consolas", 9, QFont.Bold))
        logs_label.setStyleSheet("color: #888; padding: 2px;")

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet(
            "background-color: #1E1E1E; color: #D4D4D4; font-family: Consolas; border: 1px solid #333; padding: 6px; font-size: 12px;"
        )

        logs_layout.addWidget(logs_label)
        logs_layout.addWidget(self.log_output)

        bottom_splitter.addWidget(preview_panel)
        bottom_splitter.addWidget(logs_panel)
        bottom_splitter.setSizes([600, 400])

        right_splitter.addWidget(graph_panel)
        right_splitter.addWidget(bottom_splitter)
        right_splitter.setStretchFactor(0, 6)
        right_splitter.setStretchFactor(1, 4)

        self.main_splitter.addWidget(info_panel)
        self.main_splitter.addWidget(right_splitter)
        self.main_splitter.setSizes([180, 1100])

        layout.addWidget(self.main_splitter, stretch=1)

        # === Bottom Status Bar ===
        status_bar = QHBoxLayout()
        status_bar.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m 步")
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #ccc; border-radius: 8px; background-color: #f0f0f0; text-align: center; font-size: 11px; }
            QProgressBar::chunk { background-color: #4CAF50; border-radius: 8px; }
        """)

        self.status_detail = QLabel("")
        self.status_detail.setStyleSheet("color: #999; font-size: 11px;")

        status_bar.addWidget(self.progress_bar, stretch=1)
        status_bar.addWidget(self.status_detail)
        layout.addLayout(status_bar)

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

    def show_runtime_parameters_dialog(self):
        if not self.workflow_config:
            return
        dlg = RuntimeParametersDialog(
            self.workflow_config.get("runtime_parameters", {}),
            self.workflow_config.get("parameter_mappings", {}),
            self,
        )
        if dlg.exec_() == QDialog.Accepted:
            self.workflow_config["runtime_parameters"] = dlg.get_parameters()
            self.workflow_config["parameter_mappings"] = dlg.get_mappings()
            self._update_runtime_parameter_info()

    def _update_runtime_parameter_info(self):
        if not self.workflow_config:
            return
        params = self.workflow_config.get("runtime_parameters", {})
        mappings = self.workflow_config.get("parameter_mappings", {})
        self.log_print(
            f"[系统] 运行参数: {len(params)} 个，参数映射: {len(mappings)} 组"
        )

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
        self.btn_params.setEnabled(True)
        self.btn_run.setEnabled(True)
        self.btn_run.setStyleSheet(
            "background-color: #E91E63; color: white; font-weight: bold; padding: 4px 20px; border-radius: 4px;"
        )
        self.btn_run.setText("▶ 运行引擎")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m 步")
        self.lbl_status.setText("等待执行...")
        self.btn_export_preview.hide()

        wf_name = self.workflow_config.get("workflow_name", "未命名")
        steps_count = len(self.workflow_config.get("steps", []))
        self.log_print(f"[成功] 成功加载工作流: {wf_name} (共 {steps_count} 个节点)")
        self._update_runtime_parameter_info()

        # Update info panel
        self.info_name.setText(wf_name)
        self.info_steps.setText(f"步骤: {steps_count}")
        files = [s["params"].get("file_path", "?") for s in self.workflow_config.get("steps", [])
                 if s.get("action") == "load_file"]
        if files:
            self.info_files.setText("\n".join(os.path.basename(f) for f in files))
        else:
            self.info_files.setText("(无数据源)")

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

        self.log_output.clear()

        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳ 执行中...")
        self.btn_run.setStyleSheet(
            "background-color: #9E9E9E; color: white; font-weight: bold; padding: 4px 20px; border-radius: 4px;"
        )
        self.btn_load_json.setEnabled(False)
        self.btn_mapping.setEnabled(False)
        self.btn_params.setEnabled(False)
        self.cb_debug.setEnabled(False)

        total_steps = len(self.workflow_config.get("steps", []))
        self.progress_bar.setRange(0, total_steps)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"%v / {total_steps} 步")
        self.lbl_status.setText("正在跑批计算...")
        self.lbl_status.setStyleSheet("color: #E65100; font-weight: bold;")
        self.status_detail.setText("")

        for item in self.graph_view.node_items_dict.values():
            item.has_data = False
            item.set_status("pending")

        keep_mem = self.cb_debug.isChecked()
        self.engine_thread = WorkflowEngine(
            self.file_mapping, self.workflow_config, keep_intermediates=keep_mem
        )

        self.engine_thread.log_signal.connect(self.log_print)
        self.engine_thread.progress_signal.connect(self.progress_bar.setValue)
        self.engine_thread.finished_signal.connect(self.on_engine_finished)
        self.engine_thread.start()

    def on_engine_finished(self, success, pool):
        self.btn_run.setEnabled(True)
        self.btn_run.setText("▶ 运行引擎")
        self.btn_run.setStyleSheet(
            "background-color: #E91E63; color: white; font-weight: bold; padding: 4px 20px; border-radius: 4px;"
        )
        self.btn_load_json.setEnabled(True)
        self.btn_mapping.setEnabled(True)
        self.btn_params.setEnabled(True)
        self.cb_debug.setEnabled(True)

        if success:
            self.progress_bar.setValue(self.progress_bar.maximum())
            self.progress_bar.setFormat("完成")
            self.lbl_status.setText("执行完毕")
            self.lbl_status.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.status_detail.setText(f"输出 {len(pool)} 张结果表")

            self.graph_view.set_all_nodes_status("success")
            self.final_pool = pool

            for item in set(self.graph_view.node_items_dict.values()):
                if item.status == "success":
                    item.has_data = item.table_name in self.final_pool
                item.update()

            QMessageBox.information(
                self, "成功", "工作流执行完毕！\n请在下方数据预览区域点击节点查看结果。"
            )
        else:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("失败")
            self.lbl_status.setText("执行中断")
            self.lbl_status.setStyleSheet("color: #F44336; font-weight: bold;")
            self.status_detail.setText("请查看运行日志定位问题")

            self.graph_view.set_all_nodes_status("error")

            QMessageBox.critical(
                self, "执行失败", "工作流执行遇到错误，请查看右侧运行日志定位问题节点。"
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
