"""Node configuration and runtime-parameter synchronization for design mode."""

import copy

try:
    from PyQt5 import sip
except ImportError:  # pragma: no cover - depends on PyQt packaging
    sip = None

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from node_editor import NodeItem
from core.workflow.schema import operation_display_name, normalize_action_params, normalize_output_refs
from parameter_resolver import normalize_runtime_parameters
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

    def _source_output_refs(self, source_node):
        """Return saved outputs only; operator titles are never data tables."""
        if source_node is None or self._is_deleted_qt_object(source_node):
            return []
        return normalize_output_refs(
            source_node.node_id,
            getattr(source_node, "params", {}) or {},
            getattr(source_node, "action_type", ""),
        )

    def _source_output_name(self, source_node):
        refs = self._source_output_refs(source_node)
        return refs[0]["name"] if refs else ""

    def _incoming_output_refs(self, node):
        refs = []
        for edge in getattr(node, "edges_in", []) or []:
            refs.extend(self._source_output_refs(edge.source_node))
        return refs

    def _panel_params_for_node(self, node):
        params = copy.deepcopy(getattr(node, "params", {}) or {})
        params["action"] = getattr(node, "action_type", "")
        return params

    def _node_title_from_params(self, node):
        return operation_display_name(
            {"params": node.params},
            getattr(node, "operator_name", node.action_type),
        )

    def _normalize_params_for_node(self, node, params, include_action=True):
        return normalize_action_params(
            node.action_type,
            params or {},
            self._incoming_output_refs(node),
            fallback_title=getattr(node, "title", "") or getattr(node, "operator_name", ""),
            include_action=include_action,
        )

    def _store_node_params(self, node, action, params, mark_dirty=True):
        if not node:
            return
        normalized = self._normalize_params_for_node(node, params, include_action=True)
        node.params = normalized
        node.title = self._node_title_from_params(node)
        if mark_dirty:
            node.is_dirty = True
        node.update()

    def _find_node_by_id(self, node_id):
        target = str(node_id or "")
        if not target or not hasattr(self, "canvas_scene"):
            return None
        for item in self.canvas_scene.items():
            if isinstance(item, NodeItem) and item.node_id == target:
                return item
        return None

    def _refresh_panel_inputs(self, panel, node):
        incoming_refs = self._incoming_output_refs(node)
        if hasattr(panel, "set_incoming_outputs"):
            panel.set_incoming_outputs(incoming_refs)
        else:
            panel.update_combos([item["name"] for item in incoming_refs])
        if hasattr(panel, "set_global_code"):
            panel.set_global_code(getattr(self, "global_code", ""))
        if hasattr(panel, "set_function_spaces"):
            panel.set_function_spaces(getattr(self, "function_spaces", []))
        if hasattr(panel, "set_bound_node_id"):
            panel.set_bound_node_id(getattr(node, "node_id", ""))

    def on_global_code_changed(self, global_code):
        self.global_code = str(global_code or "")
        if hasattr(self.ctx, "set_global_code"):
            self.ctx.set_global_code(self.global_code)
        for panel in getattr(self, "panel_instances", {}).values():
            if hasattr(panel, "set_global_code"):
                panel.set_global_code(self.global_code)
        if hasattr(self, "status_label"):
            self.status_label.setText("全局函数已更新，工作流待运行")

    def on_function_spaces_changed(self, function_spaces):
        self.function_spaces = copy.deepcopy(function_spaces or [])
        if hasattr(self.ctx, "set_function_spaces"):
            self.ctx.set_function_spaces(self.function_spaces)
        for panel in getattr(self, "panel_instances", {}).values():
            if hasattr(panel, "set_function_spaces"):
                panel.set_function_spaces(self.function_spaces)
        if hasattr(self, "status_label"):
            self.status_label.setText("函数库已更新，工作流待运行")

    def on_code_editor_saved(self, node_id, code, global_code):
        self.on_code_editor_saved_with_spaces(node_id, code, global_code, None)

    def on_code_editor_saved_with_spaces(self, node_id, code, global_code, function_spaces=None):
        node = self._find_node_by_id(node_id)
        if node is None or node.action_type != "code_block":
            return
        if function_spaces is not None:
            self.on_function_spaces_changed(function_spaces)
        params = self._params_for_code_editor_node(node, code)
        self._store_node_params(node, "code_block", params, mark_dirty=True)
        if self._current_live_node() is node:
            panel = self.panel_instances.get("code_block")
            if panel and hasattr(panel, "set_params"):
                panel.set_params(self._panel_params_for_node(node))
        self._update_status_bar()
        if hasattr(self, "status_label"):
            self.status_label.setText("代码已保存，节点待运行")

    def _params_for_code_editor_node(self, node, code):
        panel = self.panel_instances.get("code_block") if self._current_live_node() is node else None
        if panel and hasattr(panel, "get_params"):
            params = panel.get_params()
        else:
            params = copy.deepcopy(getattr(node, "params", {}) or {})
        params["code"] = str(code or "")
        return params

    def on_code_editor_run_requested(self, node_id, code, global_code):
        self.on_code_editor_run_requested_with_spaces(node_id, code, global_code, None)

    def on_code_editor_run_requested_with_spaces(self, node_id, code, global_code, function_spaces=None):
        node = self._find_node_by_id(node_id)
        if node is None or node.action_type != "code_block":
            return
        if function_spaces is None:
            self.on_global_code_changed(global_code)
        if function_spaces is not None:
            self.on_function_spaces_changed(function_spaces)
        params = self._params_for_code_editor_node(node, code)
        self._store_node_params(node, "code_block", params, mark_dirty=True)
        if self._current_live_node() is node:
            panel = self.panel_instances.get("code_block")
            if panel and hasattr(panel, "set_params"):
                panel.set_params(self._panel_params_for_node(node))
        self._run_node(node)

    def _on_edge_changed(self):
        """连线变更时刷新当前配置面板的输入列表和列下拉。"""
        node = self._current_live_node()
        if node is None or "action" not in node.params:
            return
        panel = self.panel_instances.get(node.params["action"])
        if panel:
            self._refresh_panel_inputs(panel, node)

    def _update_inspector_panel(self, node):
        if self._is_deleted_qt_object(node):
            node = None
        self._ensure_config_panel_embedded()
        if node is None or "action" not in node.params:
            self.config_area.setCurrentWidget(self.panel_instances["sys_empty"])
            self.config_dialog.setToolTip("算子配置")
            return

        action = node.params["action"]
        active_panel = self.panel_instances.get(action)
        if not active_panel:
            self.config_area.setCurrentWidget(self.panel_instances["sys_empty"])
            self.config_dialog.setToolTip(f"未知算子: {action}")
            return

        self.config_area.setCurrentWidget(active_panel)
        self.config_dialog.setToolTip(f"配置: {node.title}")
        if hasattr(active_panel, "set_panel_context"):
            active_panel.set_panel_context(action, node.title)
        if hasattr(active_panel, "begin_panel_update"):
            active_panel.begin_panel_update()
        try:
            active_panel.clear_ui()
            self._refresh_panel_inputs(active_panel, node)
            active_panel.set_params(self._panel_params_for_node(node))
        finally:
            if hasattr(active_panel, "end_panel_update"):
                active_panel.end_panel_update()

    def save_current_node_draft(self):
        node = self._current_live_node()
        if node is None or "action" not in node.params:
            return
        action = node.params["action"]
        active_panel = self.panel_instances.get(action)
        if active_panel and hasattr(active_panel, "get_params"):
            new_params = active_panel.get_params()
            normalized = self._normalize_params_for_node(node, new_params, include_action=True)
            changed = normalized != node.params
            self._store_node_params(node, action, new_params, mark_dirty=changed)

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

    def _ancestor_nodes_for(self, node):
        seen = set()
        ordered = []

        def visit(current):
            if current is None or current.node_id in seen:
                return
            for edge in getattr(current, "edges_in", []) or []:
                visit(edge.source_node)
            seen.add(current.node_id)
            ordered.append(current)

        visit(node)
        return ordered

    def _merge_engine_result(self, result_pool, nodes):
        node_ids = {node.node_id for node in nodes}
        data = result_pool.get("data", {}) if isinstance(result_pool, dict) else {}
        output_map = result_pool.get("output_key_map", {}) if isinstance(result_pool, dict) else {}
        dedup_map = result_pool.get("dedup_map", {}) if isinstance(result_pool, dict) else {}
        output_meta = result_pool.get("output_meta", {}) if isinstance(result_pool, dict) else {}
        updated_outputs = {}

        self.ctx.blockSignals(True)
        try:
            for node_id in node_ids:
                for old_key in self.ctx.output_key_map.get(node_id, {}).values():
                    self.ctx.data_pool.pop(old_key, None)
                self.ctx.output_key_map[node_id] = {}
                self.ctx.dedup_map.pop(node_id, None)

            for node_id, outputs in output_map.items():
                if node_id not in node_ids:
                    continue
                for output_id, key in outputs.items():
                    if key not in data:
                        continue
                    final_key = self.ctx.register_data(key, data[key], node_id=node_id, output_id=output_id)
                    if dedup_map.get(node_id) == key:
                        self.ctx.dedup_map[node_id] = final_key

            for item in nodes:
                metas = output_meta.get(item.node_id)
                if not metas:
                    continue
                params = copy.deepcopy(getattr(item, "params", {}) or {})
                existing = [row for row in params.get("outputs") or [] if isinstance(row, dict)]
                merged = []
                for index, meta in enumerate(metas, start=1):
                    saved = existing[index - 1] if index - 1 < len(existing) else {}
                    merged.append(
                        {
                            "output_id": str(meta.get("output_id") or saved.get("output_id") or f"out_{index}"),
                            "name": str(meta.get("name") or saved.get("name") or f"结果{index}"),
                            "data_type": str(meta.get("data_type") or saved.get("data_type") or "table"),
                        }
                    )
                params["outputs"] = merged
                prefs = copy.deepcopy(params.get("io_prefs") or {})
                prefs["outputs"] = [
                    {
                        "output_id": item["output_id"],
                        "name": item["name"],
                        "data_type": item["data_type"],
                    }
                    for item in merged
                ]
                params["io_prefs"] = prefs
                item.params = params
                updated_outputs[item.node_id] = copy.deepcopy(merged)
                panel = getattr(self, "panel_instances", {}).get(item.action_type)
                if panel and hasattr(panel, "set_runtime_outputs"):
                    panel.set_runtime_outputs(merged)
        finally:
            self.ctx.blockSignals(False)
        return updated_outputs

    def on_tool_run_requested(self, action, params):
        node = self._current_live_node()
        if node is None:
            return
        self._store_node_params(node, action, params, mark_dirty=True)
        if action == "advanced_param_mapping":
            self._sync_runtime_parameters()
            node.is_dirty = False
            node.update()
            if hasattr(self, "status_label"):
                self.status_label.setText("参数输入已保存")
            return

        self._run_node(node)

    def _run_node(self, node):
        active_panel = self.panel_instances.get(node.action_type) if node is not None else None

        def code_editor_log_callback(message):
            text = str(message or "")
            if not (
                text.startswith("代码块输出:")
                or text.startswith("代码块错误输出:")
            ):
                return
            if active_panel and hasattr(active_panel, "append_code_editor_log"):
                active_panel.append_code_editor_log(node.node_id, text)

        if active_panel and hasattr(active_panel, "set_code_editor_running"):
            active_panel.set_code_editor_running(node.node_id, "正在运行当前代码块...")
        if getattr(node, "action_type", "") == "code_block" and hasattr(self, "status_label"):
            self.status_label.setText("代码块运行中...")
            QApplication.processEvents()
        nodes_to_run = self._ancestor_nodes_for(node)
        config = self.ctx.build_workflow_logic(nodes_to_run)
        if not config:
            message = "当前节点上游存在循环连线，无法执行。"
            QMessageBox.warning(self, "运行失败", message)
            if active_panel and hasattr(active_panel, "set_code_editor_run_result"):
                active_panel.set_code_editor_run_result(node.node_id, False, message)
            return False, message

        result = self.ctx.run_workflow_sync(
            config,
            keep_intermediates=True,
            log_callback=code_editor_log_callback,
        )
        if not result.get("success"):
            logs = "\n".join(result.get("logs") or [])
            message = logs if logs else "节点执行失败"
            dialog_message = message[-2000:] if len(message) > 2000 else message
            QMessageBox.critical(self, "运行失败", dialog_message)
            if active_panel and hasattr(active_panel, "set_code_editor_run_result"):
                active_panel.set_code_editor_run_result(node.node_id, False, message)
            return False, message

        updated_outputs = self._merge_engine_result(result.get("pool", {}), nodes_to_run)
        for item in nodes_to_run:
            item.is_dirty = False
            item.title = self._node_title_from_params(item)
            item.update()

        self.refresh_combo_list()
        self._render_node_preview(node)
        self._update_status_bar()
        node_outputs = updated_outputs.get(node.node_id, [])
        output_count = len(node_outputs)
        if active_panel and hasattr(active_panel, "set_code_editor_run_result"):
            if output_count:
                names = "、".join(str(item.get("name") or item.get("output_id") or "结果") for item in node_outputs[:5])
                suffix = "..." if output_count > 5 else ""
                active_panel.set_code_editor_run_result(node.node_id, True, f"运行成功，输出 {output_count} 个结果：{names}{suffix}")
            else:
                active_panel.set_code_editor_run_result(node.node_id, True, "运行成功，未发布可预览输出")
        if hasattr(self, "status_label"):
            if node.action_type == "code_block":
                self.status_label.setText(f"代码块运行成功，输出 {output_count} 个结果")
            else:
                self.status_label.setText("当前节点已运行并更新预览")
        return True, "运行成功"

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
        if hasattr(self.ctx, "set_global_code"):
            self.ctx.set_global_code(getattr(self, "global_code", ""))
        if hasattr(self.ctx, "set_function_spaces"):
            self.ctx.set_function_spaces(getattr(self, "function_spaces", []))
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
