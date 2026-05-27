import json
import os
import sys
import uuid
import pandas as pd
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QTableView,
    QLineEdit,
    QLabel,
    QMessageBox,
    QStackedWidget,
    QFormLayout,
    QGroupBox,
    QDialog,
    QDialogButtonBox,
    QSplitter,
    QProgressDialog,
    QFrame,
    QTabWidget,
    QCheckBox,
    QComboBox,
    QMenu,
    QScrollArea,
    QApplication,
)
from PyQt5.QtCore import Qt, pyqtSignal, QPointF
from PyQt5.QtGui import QFont, QCursor

from workspace_context import WorkspaceContext
from ui_components import PandasModel, NODE_REGISTRY
from node_editor import NodeCanvasScene, NodeCanvasView, NodeItem, EdgeItem
import utils


class PathRemapDialog(QDialog):
    def __init__(self, missing_files, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据源重映射")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self.missing_files = missing_files
        self.inputs = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        warn_lbl = QLabel(
            "注意：以下数据源已失效（文件不存在）。\n如果不需要替换，可留空，后续可手动配置。"
        )
        warn_lbl.setStyleSheet("color: #E65100; font-weight: bold;")
        layout.addWidget(warn_lbl)

        # 修复显示不全：增加滚动条容器处理超长文件列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        form = QFormLayout(scroll_content)

        for nid, old_path in self.missing_files.items():
            h = QHBoxLayout()
            line = QLineEdit()
            line.setPlaceholderText("请选择新的有效文件...")
            btn = QPushButton("浏览")
            btn.clicked.connect(lambda _, l=line: self.browse(l))
            h.addWidget(line)
            h.addWidget(btn)
            form.addRow(f"原路径: {os.path.basename(old_path)}", h)
            self.inputs[nid] = line

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def browse(self, line_edit):
        p, _ = QFileDialog.getOpenFileName(
            self, "选择有效文件", "", "Excel/CSV (*.xlsx *.xls *.csv)"
        )
        if p:
            line_edit.setText(p)

    def get_mapping(self):
        return {nid: line.text() for nid, line in self.inputs.items() if line.text()}


class ToolboxWidget(QGroupBox):
    add_node_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setTitle("节点工具箱")
        self.setStyleSheet(
            "QGroupBox { border: 1px solid #ddd; background-color: #f8f9fa; border-radius: 4px; font-weight: bold; padding-top: 20px; }"
        )
        self.setMinimumWidth(140)
        self.setMaximumWidth(200)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("QScrollArea { background-color: transparent; }")

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        for action, config in NODE_REGISTRY.items():
            btn = QPushButton(f"  {config['title']}")
            btn.setFixedHeight(34)
            btn.setMinimumWidth(120)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: white; border: 1px solid #ddd; border-radius: 4px;
                    border-left: 4px solid {config['color']}; text-align: left; padding-left: 4px;
                    font-size: 12px;
                }}
                QPushButton:hover {{ background-color: {config['color']}; color: white; }}
            """)
            btn.clicked.connect(
                lambda checked, a=action: self.add_node_requested.emit(a)
            )
            layout.addWidget(btn)
        layout.addStretch(1)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)


class DesignModeWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.ctx = WorkspaceContext()
        self.ctx.workflow_finished.connect(self._on_full_run_finished)

        self.ctx.data_updated.connect(self.refresh_combo_list)
        self.ctx.workflow_finished.connect(lambda s, d: self.refresh_combo_list())

        self._spawn_counter = 0
        self.current_selected_node = None
        self._current_tab_shapes = {}
        self._is_updating_combo = False

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 4, 6, 4)
        main_layout.setSpacing(4)

        # === Top Toolbar ===
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        btn_import = QPushButton("导入模板")
        btn_export = QPushButton("导出模板")
        btn_clear = QPushButton("清空画布")
        io_btn_style = """
            QPushButton { background-color: white; border: 1px solid #ccc; padding: 5px 12px; border-radius: 4px; font-size: 12px; }
            QPushButton:hover { background-color: #f0f0f0; border-color: #999; }
        """
        for b in [btn_import, btn_export, btn_clear]:
            b.setStyleSheet(io_btn_style)
            b.setCursor(Qt.PointingHandCursor)

        btn_import.clicked.connect(self.import_workflow)
        btn_export.clicked.connect(self.export_workflow)
        btn_clear.clicked.connect(self.clear_canvas_logic)

        def create_sep():
            line = QFrame()
            line.setFrameShape(QFrame.VLine)
            line.setStyleSheet("color: #ddd;")
            return line

        self.btn_run_all = QPushButton("全量跑批执行")
        self.btn_run_all.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold; border-radius: 4px; padding: 5px 15px;"
        )
        self.btn_run_all.clicked.connect(self.run_full_workflow)

        self.btn_auto_layout = QPushButton("整理排版")
        self.btn_auto_layout.setStyleSheet(
            "background-color: #009688; color: white; font-weight: bold; border-radius: 4px; padding: 5px 15px;"
        )
        self.btn_auto_layout.clicked.connect(self.auto_layout_nodes)

        self.btn_delete_node = QPushButton("删除选中")
        self.btn_delete_node.setStyleSheet(
            "background-color: #f44336; color: white; font-weight: bold; border-radius: 4px; padding: 5px 12px;"
        )
        self.btn_delete_node.clicked.connect(self.delete_canvas_node)

        toolbar.addWidget(btn_import)
        toolbar.addWidget(btn_export)
        toolbar.addWidget(btn_clear)
        toolbar.addWidget(create_sep())
        toolbar.addWidget(self.btn_run_all)
        toolbar.addWidget(self.btn_auto_layout)
        toolbar.addWidget(create_sep())
        toolbar.addStretch(1)
        toolbar.addWidget(self.btn_delete_node)
        main_layout.addLayout(toolbar)

        # === Main Splitter: Toolbox | Canvas | Right Panel ===
        self.main_splitter = QSplitter(Qt.Horizontal)

        # Left: Toolbox
        self.toolbox = ToolboxWidget()
        self.toolbox.add_node_requested.connect(self.add_node_to_canvas)

        # Center: Canvas
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)

        self.canvas_scene = NodeCanvasScene()
        self.canvas_scene.node_selected.connect(self.on_canvas_node_selected)
        self.canvas_scene.node_double_clicked.connect(self.on_canvas_node_double_clicked)
        self.canvas_scene.right_clicked.connect(self.show_context_menu)

        self.canvas_view = NodeCanvasView(self.canvas_scene)
        canvas_layout.addWidget(self.canvas_view)

        # Right: Data Preview only
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        preview_header = QHBoxLayout()
        self.chk_auto_follow = QCheckBox("自动跟随")
        self.chk_auto_follow.setChecked(True)
        self.chk_auto_follow.setStyleSheet("font-weight: bold; color: #2196F3;")
        self.chk_auto_follow.stateChanged.connect(self._on_auto_follow_changed)

        self.combo_preview_tables = QComboBox()
        self.combo_preview_tables.setMinimumWidth(120)
        self.combo_preview_tables.addItem("暂无数据")
        self.combo_preview_tables.setStyleSheet("""
            QComboBox { background: white; border: 1px solid #ccc; border-radius: 3px; padding: 2px 5px; color: black; }
            QComboBox QAbstractItemView { background-color: white; color: black; selection-background-color: #E1F5FE; }
        """)
        self.combo_preview_tables.currentIndexChanged.connect(self._on_manual_combo_changed)

        self.preview_title = QLabel("未选择")
        self.preview_title.setStyleSheet("color: #888;")

        self.lbl_shape = QLabel("")
        preview_header.addWidget(self.chk_auto_follow)
        preview_header.addWidget(self.combo_preview_tables)
        preview_header.addWidget(self.preview_title, stretch=1)
        preview_header.addWidget(self.lbl_shape)

        self.preview_tabs = QTabWidget()
        self.preview_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #eee; background: white; }
            QTabBar::tab { background: #f5f5f5; border: 1px solid #ddd; padding: 4px 10px;
                border-top-left-radius: 3px; border-top-right-radius: 3px; margin-right: 1px; font-size: 11px; }
            QTabBar::tab:selected { background: #E1F5FE; color: #0277BD; border-bottom: none; }
        """)
        self.preview_tabs.currentChanged.connect(self._on_tab_changed)

        right_layout.addLayout(preview_header)
        right_layout.addWidget(self.preview_tabs)

        # Assemble splitter
        self.main_splitter.addWidget(self.toolbox)
        self.main_splitter.addWidget(canvas_container)
        self.main_splitter.addWidget(right_panel)
        self.main_splitter.setSizes([160, 700, 420])
        main_layout.addWidget(self.main_splitter, stretch=1)

        # === Config Dialog (card-style popup) ===
        self.config_dialog = QDialog(self)
        self.config_dialog.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.config_dialog.setWindowTitle("算子配置")
        self.config_dialog.setMinimumWidth(520)
        self.config_dialog.resize(560, 520)
        self.config_dialog.setStyleSheet("""
            QDialog { background: #fafafa; border: 1px solid #ccc; border-radius: 8px; }
        """)
        self.config_dialog.setAttribute(Qt.WA_TranslucentBackground, False)

        dialog_layout = QVBoxLayout(self.config_dialog)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        dialog_layout.setSpacing(0)

        self.config_area = QStackedWidget()
        self.panel_instances = {}

        for action, config in NODE_REGISTRY.items():
            panel = config["panel_class"](self.ctx.data_pool)
            panel.step_recorded.connect(self.on_tool_executed)
            self.config_area.addWidget(panel)
            self.panel_instances[action] = panel

        self.panel_empty = QWidget()
        empty_layout = QVBoxLayout(self.panel_empty)
        empty_lbl = QLabel("在画布中单击或双击节点\n进行参数配置")
        empty_lbl.setAlignment(Qt.AlignCenter)
        empty_lbl.setStyleSheet("color: #888; font-size: 13px;")
        empty_layout.addWidget(empty_lbl)
        self.config_area.addWidget(self.panel_empty)
        self.panel_instances["sys_empty"] = self.panel_empty

        dialog_layout.addWidget(self.config_area)

        # === Bottom Status Bar ===
        status_bar = QHBoxLayout()
        status_bar.setSpacing(15)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #666; font-size: 11px; padding: 2px 8px;")
        self.status_node_count = QLabel("节点: 0")
        self.status_node_count.setStyleSheet("color: #999; font-size: 11px;")
        self.status_table_count = QLabel("内存表: 0")
        self.status_table_count.setStyleSheet("color: #999; font-size: 11px;")
        status_bar.addWidget(self.status_label)
        status_bar.addStretch(1)
        status_bar.addWidget(self.status_node_count)
        status_bar.addWidget(self.status_table_count)
        main_layout.addLayout(status_bar)

    def show_context_menu(self, scene_pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: white; border: 1px solid #ccc; border-radius: 4px;}
            QMenu::item { padding: 8px 30px 8px 20px; font-size: 13px;}
            QMenu::item:selected { background-color: #E1F5FE; color: #0277BD; font-weight: bold;}
        """)

        for action, config in NODE_REGISTRY.items():
            qaction = menu.addAction(f"{config['title']}")
            qaction.triggered.connect(
                lambda checked, a=action, pos=scene_pos: self.add_node_at_pos(a, pos)
            )

        menu.exec_(QCursor.pos())

    def add_node_at_pos(self, action, scene_pos):
        config = NODE_REGISTRY[action]
        unique_id = f"node_{uuid.uuid4().hex[:8]}"

        node = NodeItem(
            unique_id,
            action,
            config["title"],
            config["color"],
            scene_pos.x(),
            scene_pos.y(),
        )
        node.params["action"] = action
        node.is_dirty = True
        self.canvas_scene.addItem(node)
        self.canvas_scene.clearSelection()
        node.setSelected(True)

        self.on_canvas_node_selected(node)
        self._update_status_bar()
        if action == "load_file":
            self.on_canvas_node_double_clicked(node)

    def refresh_combo_list(self, *args):
        self._is_updating_combo = True
        self.combo_preview_tables.blockSignals(True)

        current_text = self.combo_preview_tables.currentText()
        self.combo_preview_tables.clear()

        tables = list(self.ctx.data_pool.keys())
        if tables:
            self.combo_preview_tables.addItems(tables)
            if current_text in tables:
                self.combo_preview_tables.setCurrentText(current_text)
        else:
            self.combo_preview_tables.addItem("暂无数据")

        self.combo_preview_tables.blockSignals(False)
        self._is_updating_combo = False

    def _on_auto_follow_changed(self, state):
        if state == Qt.Checked:
            self.chk_auto_follow.setStyleSheet("font-weight: bold; color: #2196F3;")
            if self.current_selected_node:
                self._render_node_preview(self.current_selected_node)
        else:
            self.chk_auto_follow.setStyleSheet("font-weight: normal; color: #999;")
            if self.combo_preview_tables.currentText() != "暂无数据":
                self.preview_title.setText(
                    f"已锁定表: 【{self.combo_preview_tables.currentText()}】"
                )
                self.preview_title.setStyleSheet("color: #E65100; font-weight: bold;")

    def _on_manual_combo_changed(self, index):
        if self._is_updating_combo or index < 0:
            return

        table_name = self.combo_preview_tables.currentText()
        if table_name and table_name != "暂无数据":
            self.chk_auto_follow.blockSignals(True)
            self.chk_auto_follow.setChecked(False)
            self.chk_auto_follow.setStyleSheet("font-weight: normal; color: #999;")
            self.chk_auto_follow.blockSignals(False)
            self._render_specific_table(table_name)

    def _render_specific_table(self, table_name):
        self.preview_tabs.clear()
        self._current_tab_shapes.clear()

        if table_name in self.ctx.data_pool:
            df = self.ctx.get_data(table_name)
            self.preview_title.setText(f"已锁定表: 【{table_name}】 (点击画布不切表)")
            self.preview_title.setStyleSheet("color: #E65100; font-weight: bold;")
            self._add_preview_tab(f"锁定视图: {table_name}", df)
        else:
            self.preview_title.setText(f"锁定表: 【{table_name}】 (暂无数据)")
            self.lbl_shape.setText("(0 行, 0 列)")

    def _render_node_preview(self, node):
        self.preview_tabs.clear()
        self._current_tab_shapes.clear()

        if not node:
            self.preview_title.setText(
                "数据预览: 未选择节点\n(提示: 双击画布节点可配置参数)"
            )
            self.preview_title.setStyleSheet("color: black; font-weight: bold;")
            self.lbl_shape.setText("(0 行, 0 列)")
            return

        out_name = node.params.get("out_name")

        if out_name and out_name in self.ctx.data_pool:
            self._is_updating_combo = True
            if self.combo_preview_tables.findText(out_name) >= 0:
                self.combo_preview_tables.setCurrentText(out_name)
            self._is_updating_combo = False

            df = self.ctx.get_data(out_name)
            self.preview_title.setText(f"跟随节点: 【{out_name}】")
            self.preview_title.setStyleSheet("color: #2196F3; font-weight: bold;")
            self._add_preview_tab(f"当前输出: {out_name}", df)
        else:
            self.preview_title.setText(f"溯源模式: 【正在查看上游原材料】")
            self.preview_title.setStyleSheet("color: #673AB7; font-weight: bold;")

            upstream_nodes = [edge.source_node for edge in node.edges_in]
            valid_sources = 0
            for i, up_node in enumerate(upstream_nodes):
                up_name = up_node.params.get("out_name")
                if up_name and up_name in self.ctx.data_pool:
                    df = self.ctx.get_data(up_name)
                    prefix = (
                        "左表(主)"
                        if node.action_type == "left_join" and i == 0
                        else "右表(附)" if node.action_type == "left_join" else "来源表"
                    )
                    self._add_preview_tab(f"{prefix}: {up_name}", df)
                    valid_sources += 1

            if valid_sources == 0:
                self.preview_title.setText(f"溯源失败: 【连入的上游尚未产生数据】")
                self.lbl_shape.setText("(0 行, 0 列)")

    def _add_preview_tab(self, title, df):
        table = QTableView()
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableView { border: none; background-color: white; gridline-color: #eee; } "
            "QHeaderView::section { background-color: #E1F5FE; font-weight: bold; border: 1px solid #ccc; padding: 4px; }"
        )
        model = PandasModel(df)
        table.setModel(model)
        idx = self.preview_tabs.addTab(table, title)
        self._current_tab_shapes[idx] = (df.shape[0], df.shape[1])
        if idx == 0:
            self.lbl_shape.setText(f"({df.shape[0]} 行, {df.shape[1]} 列)")

    def _on_tab_changed(self, index):
        if index in self._current_tab_shapes:
            rows, cols = self._current_tab_shapes[index]
            self.lbl_shape.setText(f"({rows} 行, {cols} 列)")
        else:
            self.lbl_shape.setText("(0 行, 0 列)")

    def _update_inspector_panel(self, node):
        if node and "action" in node.params:
            action = node.params["action"]
            active_panel = self.panel_instances.get(action)
            if active_panel:
                self.config_area.setCurrentWidget(active_panel)
                self.config_dialog.setWindowTitle(f"配置: {node.title}")
                incoming = [
                    e.source_node.params.get("out_name") or e.source_node.title
                    for e in node.edges_in
                ]
                active_panel.clear_ui()
                active_panel.update_combos(incoming)
                active_panel.set_params(node.params)
                active_panel._refresh_col_combos()
        else:
            self.config_area.setCurrentWidget(self.panel_instances["sys_empty"])
            self.config_dialog.setWindowTitle("算子配置")

    def _update_status_bar(self):
        nodes = [item for item in self.canvas_scene.items() if isinstance(item, NodeItem)]
        edges = [item for item in self.canvas_scene.items() if isinstance(item, EdgeItem)]
        node_count = len(nodes)
        edge_count = len(edges)
        table_count = len(self.ctx.data_pool)
        self.status_node_count.setText(f"节点: {node_count}  连线: {edge_count}")
        self.status_table_count.setText(f"内存表: {table_count}")
        self.status_label.setText(
            "点击节点查看数据 | 双击配置参数 | 右键添加节点"
        )

    def save_current_node_draft(self):
        if self.current_selected_node and "action" in self.current_selected_node.params:
            action = self.current_selected_node.params["action"]
            active_panel = self.panel_instances.get(action)
            if active_panel and hasattr(active_panel, "get_params"):
                new_p = active_panel.get_params()
                if "out_name" in new_p and not str(new_p["out_name"]).strip():
                    new_p.pop("out_name")
                self.current_selected_node.params.update(new_p)

    def on_canvas_node_selected(self, node):
        if self.current_selected_node and self.current_selected_node != node:
            self.save_current_node_draft()

        self.current_selected_node = node
        self._update_inspector_panel(node)

        if self.chk_auto_follow.isChecked():
            self._render_node_preview(node)

    def on_canvas_node_double_clicked(self, node):
        self.on_canvas_node_selected(node)
        if node:
            self.config_dialog.show()
            self.config_dialog.raise_()
            self.config_dialog.activateWindow()

    def on_tool_executed(self, action, params, result_df, out_name):
        final_name = self.ctx.register_data(out_name, result_df)
        params["out_name"] = final_name

        if self.current_selected_node:
            self.current_selected_node.params.update(params)
            self.current_selected_node.title = f"{final_name}"
            self.current_selected_node.is_dirty = False
            self.current_selected_node.update()

        self.on_canvas_node_selected(self.current_selected_node)
        self.config_dialog.hide()
        self._update_status_bar()

    def clear_canvas_logic(self):
        nodes = [
            item for item in self.canvas_scene.items() if isinstance(item, NodeItem)
        ]
        if not nodes:
            return
        reply = QMessageBox.question(
            self,
            "确认操作",
            "确定要清空当前所有节点吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.canvas_scene.clear()
            self.ctx.clear_context()
            self.refresh_combo_list()
            self.chk_auto_follow.setChecked(True)

            self.preview_tabs.clear()
            self._current_tab_shapes.clear()
            self.preview_title.setText("未选择")
            self.preview_title.setStyleSheet("color: #888;")
            self.lbl_shape.setText("")
            self.current_selected_node = None
            self.config_area.setCurrentWidget(self.panel_instances["sys_empty"])
            self.config_dialog.hide()
            self._update_status_bar()

    def delete_canvas_node(self):
        self.canvas_scene.delete_selected_items()
        self._update_status_bar()

    def add_node_to_canvas(self, action):
        view_center = self.canvas_view.viewport().rect().center()
        scene_pos = self.canvas_view.mapToScene(view_center)
        self._spawn_counter += 1
        offset = (self._spawn_counter % 5) * 20
        self.add_node_at_pos(
            action, QPointF(scene_pos.x() - 80 + offset, scene_pos.y() - 30 + offset)
        )

    def run_full_workflow(self):
        self.save_current_node_draft()
        nodes = [
            item for item in self.canvas_scene.items() if isinstance(item, NodeItem)
        ]

        config = self.ctx.build_workflow_logic(nodes)
        if not config:
            QMessageBox.warning(self, "警告", "存在死循环连线，无法处理。")
            return

        total_steps = len(config["steps"])
        for step in config["steps"]:
            node_id = step["node_id"]
            node = next((n for n in nodes if n.node_id == node_id), None)
            if node:
                assigned_name = step["out_name"]
                if node.title == NODE_REGISTRY[node.action_type][
                    "title"
                ] or node.title.startswith("临时表_"):
                    node.title = assigned_name
                    node.update()

        self.progress = QProgressDialog("正在高速全量执行流水线...", None, 0, total_steps, self)
        self.progress.setWindowTitle("执行中")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setAutoClose(True)
        self.progress.show()
        self.ctx.run_full_workflow()
        if self.ctx.engine:
            self.ctx.engine.progress_signal.connect(self.progress.setValue)

    def _on_full_run_finished(self, success, result_pool):
        self.progress.close()
        self._update_status_bar()
        if success:
            for item in self.canvas_scene.items():
                if isinstance(item, NodeItem):
                    item.is_dirty = False
                    item.update()
            QMessageBox.information(self, "成功", "流水线跑批完毕！")
            if self.chk_auto_follow.isChecked() and self.current_selected_node:
                self.on_canvas_node_selected(self.current_selected_node)
            elif not self.chk_auto_follow.isChecked():
                table_name = self.combo_preview_tables.currentText()
                if table_name and table_name != "暂无数据":
                    self._render_specific_table(table_name)
        else:
            QMessageBox.critical(
                self, "错误", "执行出错，请检查数据完整性或查看执行模式下的日志信息。"
            )

    def auto_layout_nodes(self):
        nodes = [
            item for item in self.canvas_scene.items() if isinstance(item, NodeItem)
        ]
        if not nodes:
            return

        utils.topological_layout(
            nodes,
            get_outgoing=lambda n: [e.dest_node for e in n.edges_out],
            get_sort_key=lambda n: n.scenePos().y(),
            set_pos_func=lambda n, x, y: n.setPos(x, y),
        )

        for item in self.canvas_scene.items():
            if isinstance(item, EdgeItem):
                item.update_position()

        rect = self.canvas_scene.itemsBoundingRect()
        self.canvas_scene.setSceneRect(rect.adjusted(-200, -200, 200, 200))
        self.canvas_view.centerOn(rect.center())

    def export_workflow(self):
        self.save_current_node_draft()
        nodes = [
            item for item in self.canvas_scene.items() if isinstance(item, NodeItem)
        ]
        config = self.ctx.build_workflow_logic(nodes)

        if not config:
            QMessageBox.warning(self, "错误", "无法导出：可能存在异常连线结构。")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "保存工作流模板", "my_workflow.json", "JSON (*.json)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            QMessageBox.information(self, "成功", "工作流模板已保存。")

    def import_workflow(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入工作流模板", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                workflow = json.load(f)

            steps = workflow.get("steps", [])
            if not steps:
                return

            missing_files = {}
            for step in steps:
                if step.get("action") == "load_file":
                    fpath = step.get("params", {}).get("file_path")
                    if fpath and not os.path.exists(fpath):
                        missing_files[step.get("node_id")] = fpath

            if missing_files:
                dlg = PathRemapDialog(missing_files, self)
                if dlg.exec_() == QDialog.Accepted:
                    mapping = dlg.get_mapping()
                    for step in steps:
                        if step.get("node_id") in mapping:
                            step["params"]["file_path"] = mapping[step["node_id"]]
                else:
                    return

            self.canvas_scene.clear()
            self.ctx.clear_context()

            created_nodes = {}
            for i, step in enumerate(steps):
                node_id = step.get("node_id", f"legacy_{i}")
                action = step.get("action")
                out_name = step.get("out_name", f"Result_{i}")
                params = step.get("params", {})
                params["out_name"] = out_name
                params["action"] = action

                color = NODE_REGISTRY.get(action, {}).get("color", "#1976D2")
                title = f"{out_name}" if action != "load_file" else f"表: {out_name}"
                node = NodeItem(
                    node_id,
                    action,
                    title,
                    color,
                    step.get("x", 50),
                    step.get("y", 50 + i * 100),
                )
                node.params = params
                node.is_dirty = True
                self.canvas_scene.addItem(node)
                created_nodes[node_id] = node

            for step in steps:
                node = created_nodes.get(step.get("node_id"))
                if not node:
                    continue
                deps = []
                p = step.get("params", {})
                if node.action_type == "left_join":
                    if "df1_id" in p:
                        deps.append(p["df1_id"])
                    if "df2_id" in p:
                        deps.append(p["df2_id"])
                elif "df_id" in p:
                    deps.append(p["df_id"])

                for src_id in deps:
                    if src_id in created_nodes:
                        edge = EdgeItem(created_nodes[src_id], node)
                        self.canvas_scene.addItem(edge)
                        created_nodes[src_id].edges_out.append(edge)
                        node.edges_in.append(edge)

            self.auto_layout_nodes()
            reply = QMessageBox.question(
                self,
                "导入成功",
                "工作流模板装载完毕！\n是否立即执行流水线以加载预览？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.run_full_workflow()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取失败: {e}")
