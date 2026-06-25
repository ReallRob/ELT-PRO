"""Workflow file loading and data-source remapping for execute mode."""

import json
import os

from PyQt5.QtWidgets import QFileDialog, QMessageBox, QDialog

from ui.dialogs.data_source_mapping import DataSourceMappingDialog
from ui.execute.styles import RUN_BUTTON_ACTIVE_STYLE
from ui.design.workflow_io import validate_workflow_config


class ExecuteWorkflowFileMixin:
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
            changed_paths = {}
            for step in self.workflow_config.get("steps", []):
                if step["action"] in ("load_file", "import_template"):
                    p = step["params"]
                    path_key = "template_path" if step["action"] == "import_template" else "file_path"
                    old_path = p.get(path_key)
                    if old_path in self.file_mapping:
                        new_path = self.file_mapping[old_path]
                        p[path_key] = new_path
                        changed_paths[old_path] = new_path

            manifest = self.workflow_config.get("run_manifest") or {}
            for resource in manifest.get("file_resources", []) or []:
                path = resource.get("path")
                if path in changed_paths:
                    resource["path"] = changed_paths[path]

            with open(self.current_workflow_path, "w", encoding="utf-8") as f:
                json.dump(self.workflow_config, f, ensure_ascii=False, indent=4)

            self.log_print(
                f"[系统] 路径配置已永久保存至：{os.path.basename(self.current_workflow_path)}"
            )

            self._load_workflow_from_path(self.current_workflow_path)

        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法回写配置文件：\n{str(e)}")

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
        validate_workflow_config(self.workflow_config)

        self.current_workflow_path = file_path
        self._rebuild_file_mappings(saved_mappings)
        self.graph_view.render_workflow(self.workflow_config)
        self._reset_after_workflow_loaded()
        self._render_workflow_info_panel()

    def _rebuild_file_mappings(self, saved_mappings=None):
        """Collect load_file nodes into the remapping table used before execution."""
        self.file_mapping.clear()
        self.file_context.clear()

        for step in self.workflow_config.get("steps", []):
            if step["action"] not in ("load_file", "import_template"):
                continue

            params = step["params"]
            orig_path = params.get("file_path") or params.get("template_path")
            out_name = step.get("out_name", "未知节点")
            sheet_name = params.get("sheet_name", "模板" if step["action"] == "import_template" else "默认")

            if not orig_path:
                continue

            if orig_path not in self.file_mapping:
                actual_path = saved_mappings.get(orig_path, orig_path) if saved_mappings else orig_path
                self.file_mapping[orig_path] = actual_path

            context_str = f"[{out_name} - Sheet: {sheet_name}]"
            self.file_context.setdefault(orig_path, []).append(context_str)

    def _reset_after_workflow_loaded(self):
        self.btn_mapping.setEnabled(True)
        self.btn_run.setEnabled(True)
        self.btn_run.setStyleSheet(RUN_BUTTON_ACTIVE_STYLE)
        self.btn_run.setText("▶ 运行引擎")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m 步")
        self.lbl_status.setText("等待执行...")
        self.btn_export_preview.hide()

    def _render_workflow_info_panel(self):
        wf_name = self.workflow_config.get("workflow_name", "未命名")
        steps_count = len(self.workflow_config.get("steps", []))
        self.log_print(f"[成功] 成功加载工作流: {wf_name} (共 {steps_count} 个节点)")
        self._update_runtime_parameter_info()

        self.info_name.setText(wf_name)
        self.info_steps.setText(f"步骤: {steps_count}")
        files = [
            s["params"].get("file_path") or s["params"].get("template_path", "?")
            for s in self.workflow_config.get("steps", [])
            if s.get("action") in ("load_file", "import_template")
        ]
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
