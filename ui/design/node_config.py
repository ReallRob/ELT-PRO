"""Node configuration and runtime-parameter synchronization for design mode."""

import copy

try:
    from PyQt5 import sip
except ImportError:  # pragma: no cover - depends on PyQt packaging
    sip = None

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QVBoxLayout

from node_editor import NodeItem
from parameter_resolver import normalize_parameter_mappings, normalize_runtime_parameters
from ui.design.settings_dialog import SettingsDialog


class PublishSettingsDialog(QDialog):
    def __init__(self, crpa=None, parent=None):
        super().__init__(parent)
        crpa = crpa or {}
        self.setWindowTitle("发布信息")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.code_input = QLineEdit(str(crpa.get("code", "")))
        self.name_input = QLineEdit(str(crpa.get("name", "")))
        self.code_input.setPlaceholderText("例如 CRPA_001")
        self.name_input.setPlaceholderText("例如 网点月报生成")
        form.addRow("CRPA代码:", self.code_input)
        form.addRow("代号名称:", self.name_input)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_crpa(self):
        return {
            "code": self.code_input.text().strip(),
            "name": self.name_input.text().strip(),
        }


class NodeConfigMixin:
    def _is_deleted_qt_object(self, obj):
        if obj is None or sip is None:
            return False
        try:
            return sip.isdeleted(obj)
        except Exception:
            return False

    def _current_live_node(self):
        node = getattr(self, "current_selected_node", None)
        if self._is_deleted_qt_object(node):
            self.current_selected_node = None
            return None
        return node

    def _source_output_name(self, source_node):
        if source_node is None or self._is_deleted_qt_object(source_node):
            return ""
        actual_name = getattr(self.ctx, "dedup_map", {}).get(source_node.node_id)
        if actual_name:
            return actual_name
        return source_node.params.get("out_name") or source_node.title

    def _on_edge_changed(self):
        """连线变更时刷新当前配置面板的列下拉。"""
        node = self._current_live_node()
        if node is not None and "action" in node.params:
            action = node.params["action"]
            panel = self.panel_instances.get(action)
            if panel:
                incoming = [
                    self._source_output_name(edge.source_node)
                    for edge in node.edges_in
                ]
                panel.update_combos(incoming)

    def _update_inspector_panel(self, node):
        if self._is_deleted_qt_object(node):
            node = None
        self._ensure_config_panel_embedded()
        if node is not None and "action" in node.params:
            action = node.params["action"]
            active_panel = self.panel_instances.get(action)
            if active_panel:
                self.config_area.setCurrentWidget(active_panel)
                self.config_dialog.setToolTip(f"配置: {node.title}")
                if hasattr(active_panel, "set_panel_context"):
                    active_panel.set_panel_context(action, node.title)
                incoming = [
                    self._source_output_name(edge.source_node)
                    for edge in node.edges_in
                ]
                if hasattr(active_panel, "begin_panel_update"):
                    active_panel.begin_panel_update()
                try:
                    active_panel.clear_ui()
                    active_panel.update_combos(incoming)
                    active_panel.set_params(node.params)
                finally:
                    if hasattr(active_panel, "end_panel_update"):
                        active_panel.end_panel_update()
            else:
                self.config_area.setCurrentWidget(self.panel_instances["sys_empty"])
                self.config_dialog.setToolTip(f"未知算子: {action}")
        else:
            self.config_area.setCurrentWidget(self.panel_instances["sys_empty"])
            self.config_dialog.setToolTip("算子配置")

    def save_current_node_draft(self):
        node = self._current_live_node()
        if node is not None and "action" in node.params:
            action = node.params["action"]
            active_panel = self.panel_instances.get(action)
            if active_panel and hasattr(active_panel, "get_params"):
                new_params = active_panel.get_params()
                existing = copy.deepcopy(node.params)
                normalized = self._normalized_node_params(action, new_params)
                clears_out_name = (
                    "out_name" in new_params
                    and not str(new_params.get("out_name") or "").strip()
                    and "out_name" in existing
                )
                changed = any(existing.get(k) != v for k, v in normalized.items()) or clears_out_name
                self._store_node_params(
                    node,
                    action,
                    new_params,
                    mark_dirty=changed,
                )

    def _normalized_node_params(self, action, params):
        params_to_store = copy.deepcopy(params or {})
        if "out_name" in params_to_store and not str(params_to_store["out_name"]).strip():
            params_to_store.pop("out_name")
        params_to_store["action"] = action
        return params_to_store

    def _store_node_params(self, node, action, params, mark_dirty=True):
        if not node:
            return
        clears_out_name = (
            "out_name" in (params or {})
            and not str((params or {}).get("out_name") or "").strip()
        )
        params_to_store = self._normalized_node_params(action, params)
        if clears_out_name:
            node.params.pop("out_name", None)
            node.title = getattr(node, "operator_name", action)
        node.params.update(params_to_store)
        if "out_name" in params_to_store:
            node.title = str(params_to_store["out_name"])
        if mark_dirty:
            node.is_dirty = True
        node.update()

    def on_tool_saved(self, action, params):
        node = self._current_live_node()
        if node is None:
            return
        self._store_node_params(node, action, params, mark_dirty=True)
        if action == "advanced_param_mapping":
            self._sync_runtime_parameters()
        self._update_status_bar()
        if hasattr(self, "status_label"):
            self.status_label.setText("配置已应用，节点待运行")

    def on_canvas_node_selected(self, node):
        # 点同一个节点不重复刷新面板，保留当前编辑中的配置。
        if self._is_deleted_qt_object(node):
            node = None
        current = self._current_live_node()
        if node is not None and current is node:
            return

        if current is not None and current is not node:
            previous_action = current.params.get("action")
            self.save_current_node_draft()
            if previous_action == "advanced_param_mapping":
                self._sync_runtime_parameters()

        self.current_selected_node = node
        self._update_inspector_panel(node)

        if self.chk_auto_follow.isChecked():
            self._render_node_preview(node)

    def on_canvas_node_double_clicked(self, node):
        self.on_canvas_node_selected(node)
        if node is not None and not self._is_deleted_qt_object(node):
            self._update_inspector_panel(node)
            self._show_config_panel()

    def _ensure_config_panel_embedded(self):
        if not hasattr(self, "dock_config") or not hasattr(self, "dock_main"):
            return
        area = self.dock_main.dockWidgetArea(self.dock_config)
        if self.dock_config.isFloating() or area == Qt.NoDockWidgetArea:
            self.dock_config.setFloating(False)
            self.dock_main.addDockWidget(Qt.RightDockWidgetArea, self.dock_config)

    def _show_config_panel(self):
        self._ensure_config_panel_embedded()
        self.dock_config.show()

    def on_tool_executed(self, action, params, result_df, out_name):
        current_node = self._current_live_node()
        node_id = current_node.node_id if current_node is not None else None
        self.ctx.blockSignals(True)
        final_name = self.ctx.register_data(out_name, result_df, node_id)
        self.ctx.blockSignals(False)

        params_to_store = params
        active_panel = self.panel_instances.get(action)
        raw_params = getattr(active_panel, "_last_raw_params", None)
        if isinstance(raw_params, dict):
            params_to_store = copy.deepcopy(raw_params)
            active_panel._last_raw_params = None
        params_to_store["out_name"] = final_name
        if active_panel and hasattr(active_panel, "out_input"):
            active_panel.out_input.setText(final_name)
            active_panel._last_raw_params = None

        if current_node is not None:
            current_node.params.update(params_to_store)
            current_node.params["action"] = action
            current_node.title = f"{final_name}"
            current_node.is_dirty = False
            current_node.update()
            if action == "advanced_param_mapping":
                self._sync_runtime_parameters()

        self._render_node_preview(current_node)
        self.refresh_combo_list()
        self._update_status_bar()

    def open_operator_settings(self):
        dlg = SettingsDialog(
            self.hidden_toolbox,
            self.hidden_context_menu,
            self.naming_style,
            self.custom_names,
            self,
        )
        if dlg.exec_() == QDialog.Accepted:
            self.hidden_toolbox = dlg.get_hidden_toolbox()
            self.hidden_context_menu = dlg.get_hidden_context_menu()
            self.naming_style = dlg.get_naming_style()
            self.custom_names = dlg.get_custom_names()
            self.toolbox.set_hidden_operators(self.hidden_toolbox)
            self.toolbox.set_naming(self.naming_style, self.custom_names)
            self._save_app_settings()
            if hasattr(self, "status_label"):
                self.status_label.setText("设置已保存，右键菜单已更新")

    def open_publish_settings(self):
        dlg = PublishSettingsDialog(getattr(self, "crpa_metadata", {}), self)
        if dlg.exec_() == QDialog.Accepted:
            self.crpa_metadata = dlg.get_crpa()
            self._save_app_settings()
            if hasattr(self, "status_label"):
                name = self.crpa_metadata.get("name") or "未命名发布"
                self.status_label.setText(f"发布信息已保存: {name}")

    def _sync_runtime_parameters(self):
        parameters = {}
        mappings = {}

        if hasattr(self, "canvas_scene"):
            for item in self.canvas_scene.items():
                if not isinstance(item, NodeItem):
                    continue
                if item.action_type == "advanced_param_mapping":
                    typed_params = item.params.get("typed_parameters")
                    if isinstance(typed_params, dict):
                        parameters.update(copy.deepcopy(typed_params))
                    else:
                        parameters.update(
                            normalize_runtime_parameters(item.params.get("parameters", {}))
                        )
                    mappings.update(item.params.get("parameter_mappings", {}) or {})

        self.ctx.set_runtime_parameters(parameters, mappings)
        self.runtime_parameters = copy.deepcopy(parameters)
        self.parameter_mappings = copy.deepcopy(mappings)
        if (
            getattr(self, "_synced_runtime_parameters", None) == parameters
            and getattr(self, "_synced_parameter_mappings", None) == mappings
        ):
            return
        self._synced_runtime_parameters = copy.deepcopy(parameters)
        self._synced_parameter_mappings = copy.deepcopy(mappings)
        for panel in getattr(self, "panel_instances", {}).values():
            if hasattr(panel, "set_runtime_parameters"):
                panel.set_runtime_parameters(parameters, mappings)
        self._update_status_bar()
