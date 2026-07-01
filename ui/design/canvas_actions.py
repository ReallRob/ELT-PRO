"""Canvas node actions for design mode."""

import copy
import uuid

try:
    from PyQt5 import sip
except ImportError:  # pragma: no cover - depends on PyQt packaging
    sip = None

from PyQt5.QtCore import QPointF, QTimer
from PyQt5.QtWidgets import QMessageBox

import utils
from node_editor import EdgeItem, NodeItem
from operator_registry import NODE_REGISTRY, get_operator_title

RUNTIME_DEPENDENCY_KEYS = {
    "inputs",
}


def _copied_title(title):
    text = str(title or "").strip()
    return f"{text} 副本" if text else "副本"


class CanvasActionsMixin:
    def _is_deleted_qt_object(self, obj):
        if obj is None or sip is None:
            return False
        try:
            return sip.isdeleted(obj)
        except Exception:
            return False

    def _delete_single_node(self, node):
        if hasattr(self, "_is_deleted_qt_object") and self._is_deleted_qt_object(node):
            return
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除节点 [{node.title}] 吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if getattr(self, "current_selected_node", None) is node:
            self.current_selected_node = None
            self.on_canvas_node_selected(None)
        for edge in list(node.edges_in):
            if self._is_deleted_qt_object(edge):
                continue
            if not self._is_deleted_qt_object(edge.source_node) and edge in edge.source_node.edges_out:
                edge.source_node.edges_out.remove(edge)
            self.canvas_scene.removeItem(edge)
        for edge in list(node.edges_out):
            if self._is_deleted_qt_object(edge):
                continue
            if not self._is_deleted_qt_object(edge.dest_node) and edge in edge.dest_node.edges_in:
                edge.dest_node.edges_in.remove(edge)
            self.canvas_scene.removeItem(edge)
        self.canvas_scene.removeItem(node)
        self._sync_runtime_parameters()
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
            operator_name=title,
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
            self._sync_runtime_parameters()
            self._update_status_bar()
            QTimer.singleShot(0, self.canvas_view.center_on_canvas)

    def delete_canvas_node(self):
        self.canvas_scene.delete_selected_items()
        self._sync_runtime_parameters()
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

    def _selected_nodes_for_copy(self):
        selected = [
            item for item in self.canvas_scene.selectedItems() if isinstance(item, NodeItem)
        ]
        if selected:
            return selected
        node = getattr(self, "current_selected_node", None)
        if node is not None and not self._is_deleted_qt_object(node):
            return [node]
        return []

    def _copyable_params(self, node):
        params = copy.deepcopy(getattr(node, "params", {}) or {})
        for key in RUNTIME_DEPENDENCY_KEYS:
            params.pop(key, None)
        params["action"] = node.action_type
        for output in params.get("outputs", []) or []:
            if isinstance(output, dict) and output.get("name"):
                output["name"] = _copied_title(output.get("name"))
        return params

    def copy_selected_nodes(self):
        self.save_current_node_draft()
        source_nodes = self._selected_nodes_for_copy()
        if not source_nodes:
            return

        source_nodes.sort(key=lambda node: (node.scenePos().y(), node.scenePos().x()))
        copied_nodes = []
        offset = QPointF(40, 40)

        for node in source_nodes:
            config = NODE_REGISTRY.get(node.action_type, {})
            copied = NodeItem(
                f"node_{uuid.uuid4().hex[:8]}",
                node.action_type,
                _copied_title(node.title),
                config.get("color", node.color),
                node.scenePos().x() + offset.x(),
                node.scenePos().y() + offset.y(),
                operator_name=get_operator_title(
                    node.action_type, self.naming_style, self.custom_names
                ),
            )
            copied.params = self._copyable_params(node)
            outputs = [item for item in copied.params.get("outputs", []) or [] if isinstance(item, dict)]
            if len(outputs) == 1:
                copied.title = str(outputs[0].get("name") or copied.title)
            elif len(outputs) > 1:
                copied.title = f"{len(outputs)} 个输出"
            copied.is_dirty = True
            self.canvas_scene.addItem(copied)
            copied_nodes.append(copied)

        copied_by_old_id = {
            old.node_id: new for old, new in zip(source_nodes, copied_nodes)
        }
        for old_node in source_nodes:
            new_source = copied_by_old_id.get(old_node.node_id)
            if new_source is None:
                continue
            for edge in old_node.edges_out:
                old_dest = edge.dest_node
                new_dest = copied_by_old_id.get(getattr(old_dest, "node_id", None))
                if new_dest is None:
                    continue
                new_edge = EdgeItem(new_source, new_dest)
                self.canvas_scene.addItem(new_edge)
                new_source.edges_out.append(new_edge)
                new_dest.edges_in.append(new_edge)

        self.canvas_scene.clearSelection()
        for node in copied_nodes:
            node.setSelected(True)
        self.on_canvas_node_selected(copied_nodes[-1])
        self._sync_runtime_parameters()
        self._update_status_bar()
        self.canvas_scene.edge_changed.emit()

    def _copy_single_node_from_menu(self, node):
        if self._is_deleted_qt_object(node):
            return
        self.canvas_scene.clearSelection()
        node.setSelected(True)
        self.on_canvas_node_selected(node)
        self.copy_selected_nodes()

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
