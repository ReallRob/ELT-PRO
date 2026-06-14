"""Canvas context menu behavior for design mode."""

from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QMenu

from node_editor import NodeItem
from operator_registry import NODE_REGISTRY, get_operator_title


class CanvasContextMenuMixin:
    def show_context_menu(self, scene_pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: white; border: 1px solid #ccc; border-radius: 4px;}
            QMenu::item { padding: 8px 30px 8px 20px; font-size: 13px;}
            QMenu::item:selected { background-color: #E1F5FE; color: #0277BD; font-weight: bold;}
            QMenu::separator { height: 1px; background: #E0E0E0; margin: 4px 10px; }
        """)

        hit_item = self.canvas_scene.itemAt(scene_pos, self.canvas_view.transform())
        clicked_node = None
        if isinstance(hit_item, NodeItem):
            clicked_node = hit_item
        elif hit_item and hit_item.parentItem() and isinstance(hit_item.parentItem(), NodeItem):
            clicked_node = hit_item.parentItem()

        if clicked_node:
            delete_action = menu.addAction("删除此节点")
            delete_action.triggered.connect(
                lambda checked, node=clicked_node: self._delete_single_node(node)
            )
        else:
            for action, config in NODE_REGISTRY.items():
                if action in self.hidden_context_menu:
                    continue
                title = get_operator_title(action, self.naming_style, self.custom_names)
                add_action = menu.addAction(title)
                add_action.triggered.connect(
                    lambda checked, a=action, pos=scene_pos: self.add_node_at_pos(a, pos)
                )

        menu.exec_(QCursor.pos())
