"""Canvas node actions for design mode."""

import uuid

from PyQt5.QtCore import QPointF, QTimer
from PyQt5.QtWidgets import QMessageBox

import utils
from node_editor import EdgeItem, NodeItem
from operator_registry import NODE_REGISTRY, get_operator_title


class CanvasActionsMixin:
    def _delete_single_node(self, node):
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除节点 [{node.title}] 吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        for edge in list(node.edges_in):
            edge.source_node.edges_out.remove(edge)
            self.canvas_scene.removeItem(edge)
        for edge in list(node.edges_out):
            edge.dest_node.edges_in.remove(edge)
            self.canvas_scene.removeItem(edge)
        self.canvas_scene.removeItem(node)
        if self.current_selected_node == node:
            self.current_selected_node = None
        self._update_status_bar()

    def add_node_at_pos(self, action, scene_pos):
        config = NODE_REGISTRY[action]
        unique_id = f"node_{uuid.uuid4().hex[:8]}"
        title = get_operator_title(action, self.naming_style, self.custom_names)

        node = NodeItem(
            unique_id,
            action,
            title,
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
        # 新增节点只负责选中和准备配置页；弹窗统一由双击节点触发，避免点击工具箱时窗口闪现又被后续焦点事件关闭。

    def clear_canvas_logic(self):
        nodes = [item for item in self.canvas_scene.items() if isinstance(item, NodeItem)]
        if not nodes:
            QTimer.singleShot(0, self.canvas_view.center_on_canvas)
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
            QTimer.singleShot(0, self.canvas_view.center_on_canvas)

    def delete_canvas_node(self):
        self.canvas_scene.delete_selected_items()
        self._update_status_bar()

    def add_node_to_canvas(self, action):
        view_center = self.canvas_view.viewport().rect().center()
        scene_pos = self.canvas_view.mapToScene(view_center)
        self._spawn_counter += 1
        offset = (self._spawn_counter % 5) * 20
        self.add_node_at_pos(
            action,
            QPointF(scene_pos.x() - 80 + offset, scene_pos.y() - 30 + offset),
        )

    def auto_layout_nodes(self):
        nodes = [item for item in self.canvas_scene.items() if isinstance(item, NodeItem)]
        if not nodes:
            return

        utils.topological_layout(
            nodes,
            get_outgoing=lambda node: [edge.dest_node for edge in node.edges_out],
            get_sort_key=lambda node: node.scenePos().y(),
            set_pos_func=lambda node, x, y: node.setPos(x, y),
            layout_mode="alap",
        )

        for item in self.canvas_scene.items():
            if isinstance(item, EdgeItem):
                item.update_position()

        QTimer.singleShot(
            0,
            lambda: self.canvas_view.centerOn(
                self.canvas_scene.itemsBoundingRect().center()
            ),
        )
