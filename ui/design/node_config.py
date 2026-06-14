"""Node configuration and runtime-parameter synchronization for design mode."""

import copy

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QDialog

from node_editor import NodeItem
from parameter_resolver import normalize_parameter_mappings, normalize_runtime_parameters
from ui.design.settings_dialog import SettingsDialog


class NodeConfigMixin:
    def _on_edge_changed(self):
        """连线变更时刷新当前配置面板的列下拉。"""
        if self.current_selected_node and "action" in self.current_selected_node.params:
            action = self.current_selected_node.params["action"]
            panel = self.panel_instances.get(action)
            if panel:
                incoming = [
                    edge.source_node.params.get("out_name") or edge.source_node.title
                    for edge in self.current_selected_node.edges_in
                ]
                panel.update_combos(incoming)
                panel._refresh_col_combos()

    def _update_inspector_panel(self, node):
        if node and "action" in node.params:
            action = node.params["action"]
            active_panel = self.panel_instances.get(action)
            if active_panel:
                self.config_area.setCurrentWidget(active_panel)
                self.config_dialog.setWindowTitle(f"配置: {node.title}")
                if hasattr(active_panel, "set_panel_context"):
                    active_panel.set_panel_context(action, node.title)
                incoming = [
                    edge.source_node.params.get("out_name") or edge.source_node.title
                    for edge in node.edges_in
                ]
                active_panel.clear_ui()
                active_panel.update_combos(incoming)
                active_panel.set_params(node.params)
                active_panel._refresh_col_combos()
            else:
                self.config_area.setCurrentWidget(self.panel_instances["sys_legacy"])
                self.config_dialog.setWindowTitle(f"配置: {node.title}")
                if hasattr(self, "legacy_hint"):
                    self.legacy_hint.setText(
                        f"{action} 已不再提供独立配置面板，请改用“参数高级映射”算子。"
                    )
        else:
            self.config_area.setCurrentWidget(self.panel_instances["sys_empty"])
            self.config_dialog.setWindowTitle("算子配置")

    def save_current_node_draft(self):
        if self.current_selected_node and "action" in self.current_selected_node.params:
            action = self.current_selected_node.params["action"]
            active_panel = self.panel_instances.get(action)
            if active_panel and hasattr(active_panel, "get_params"):
                new_params = active_panel.get_params()
                if "out_name" in new_params and not str(new_params["out_name"]).strip():
                    new_params.pop("out_name")
                self.current_selected_node.params.update(new_params)

    def on_canvas_node_selected(self, node):
        # 点同一个节点不重复刷新面板，保留当前编辑中的配置。
        if node and self.current_selected_node == node:
            return

        if self.current_selected_node and self.current_selected_node != node:
            self.save_current_node_draft()
            self._sync_runtime_parameters()

        self.current_selected_node = node
        if self.config_dialog.isVisible():
            self._update_inspector_panel(node)

        if self.chk_auto_follow.isChecked():
            self._render_node_preview(node)

    def on_canvas_node_double_clicked(self, node):
        self.on_canvas_node_selected(node)
        if node:
            self._update_inspector_panel(node)
            # 延迟到当前鼠标事件结束后再显示，避免复杂面板被后续焦点/选择事件立刻隐藏。
            QTimer.singleShot(0, self._show_config_dialog)

    def _show_config_dialog(self):
        self.config_dialog.show()
        self.config_dialog.raise_()
        self.config_dialog.activateWindow()

    def on_tool_executed(self, action, params, result_df, out_name):
        node_id = self.current_selected_node.node_id if self.current_selected_node else None
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

        if self.current_selected_node:
            self.current_selected_node.params.update(params_to_store)
            self.current_selected_node.title = f"{final_name}"
            self.current_selected_node.is_dirty = False
            self.current_selected_node.update()
            if action == "advanced_param_mapping":
                self._sync_runtime_parameters()

        self._render_node_preview(self.current_selected_node)
        self.refresh_combo_list()
        self.config_dialog.hide()
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

    def _sync_runtime_parameters(self):
        parameters = normalize_runtime_parameters(self.runtime_parameters)
        mappings = dict(self.parameter_mappings or {})

        if hasattr(self, "canvas_scene"):
            for item in self.canvas_scene.items():
                if not isinstance(item, NodeItem):
                    continue
                if item.action_type == "input_param":
                    parameters.update(
                        normalize_runtime_parameters(item.params.get("parameters", {}))
                    )
                elif item.action_type == "param_mapping":
                    mapping_name = str(item.params.get("mapping_name", "")).strip()
                    if mapping_name:
                        mappings[mapping_name] = item.params.get("rules", [])
                elif item.action_type == "advanced_param_mapping":
                    typed_params = item.params.get("typed_parameters")
                    if isinstance(typed_params, dict):
                        parameters.update(copy.deepcopy(typed_params))
                    else:
                        parameters.update(
                            normalize_runtime_parameters(item.params.get("parameters", {}))
                        )
                    mappings.update(item.params.get("parameter_mappings", {}) or {})

        self.ctx.set_runtime_parameters(parameters, mappings)
        for panel in getattr(self, "panel_instances", {}).values():
            if hasattr(panel, "set_runtime_parameters"):
                panel.set_runtime_parameters(parameters, mappings)
        self._update_status_bar()
