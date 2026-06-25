"""Preview-panel behavior for the design mode."""

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableView

from table_model import PandasModel
from template_engine import (
    close_workbook,
    insert_into_template,
    load_template,
    workbook_to_preview_data,
)

PREVIEW_ROW_LIMIT = 5000


def _is_template_preview(value):
    return (
        isinstance(value, dict)
        and value.get("_template_preview")
        and isinstance(value.get("sheets"), dict)
    )


class PreviewPanelMixin:
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
            node = (
                self._current_live_node()
                if hasattr(self, "_current_live_node")
                else self.current_selected_node
            )
            if node is not None:
                self._render_node_preview(node)
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
            self._add_preview_value(f"锁定视图: {table_name}", df)
        else:
            self.preview_title.setText(f"锁定表: 【{table_name}】 (暂无数据)")
            self.lbl_shape.setText("(0 行 0 列)")

    def _render_node_preview(self, node):
        self.preview_tabs.clear()
        self._current_tab_shapes.clear()

        if hasattr(self, "_is_deleted_qt_object") and self._is_deleted_qt_object(node):
            node = None

        if node is None:
            self.preview_title.setText(
                "数据预览: 未选择节点\n(提示: 双击画布节点可配置参数)"
            )
            self.preview_title.setStyleSheet("color: black; font-weight: bold;")
            self.lbl_shape.setText("(0 行 0 列)")
            return

        if node.action_type == "import_template" and self._render_import_template_preview(node):
            return

        out_name = self.ctx.dedup_map.get(node.node_id) or node.params.get("out_name")

        if out_name and out_name in self.ctx.data_pool:
            self._is_updating_combo = True
            if self.combo_preview_tables.findText(out_name) >= 0:
                self.combo_preview_tables.setCurrentText(out_name)
            self._is_updating_combo = False

            value = self.ctx.get_data(out_name)
            if _is_template_preview(value):
                saved_path = value.get("saved_path") or "未保存"
                self.preview_title.setText(
                    f"跟随节点: 【{out_name}】 · 模板预览 · {saved_path}"
                )
            else:
                self.preview_title.setText(f"跟随节点: 【{out_name}】")
            self.preview_title.setStyleSheet("color: #2196F3; font-weight: bold;")
            self._add_preview_value(f"当前输出: {out_name}", value)
        else:
            self.preview_title.setText("溯源模式: 【正在查看上游原材料】")
            self.preview_title.setStyleSheet("color: #673AB7; font-weight: bold;")

            valid_sources = 0
            for i, edge in enumerate(node.edges_in):
                up_node = edge.source_node
                if hasattr(self, "_is_deleted_qt_object") and self._is_deleted_qt_object(up_node):
                    continue
                up_name = self.ctx.dedup_map.get(up_node.node_id) or up_node.params.get("out_name")
                if up_name and up_name in self.ctx.data_pool:
                    df = self.ctx.get_data(up_name)
                    prefix = (
                        "左表(主)"
                        if node.action_type == "left_join" and i == 0
                        else "右表(附)" if node.action_type == "left_join" else "来源表"
                    )
                    self._add_preview_value(f"{prefix}: {up_name}", df)
                    valid_sources += 1

            if valid_sources == 0:
                self.preview_title.setText("溯源失败: 【连入的上游尚未产生数据】")
                self.lbl_shape.setText("(0 行 0 列)")

    def _render_import_template_preview(self, node):
        template_path = str(node.params.get("template_path") or "").strip()
        if not template_path or not os.path.exists(template_path):
            return False

        wb = None
        try:
            wb, _ = load_template(template_path)
            applied = 0
            for edge in node.edges_in:
                insert_node = edge.source_node
                if hasattr(self, "_is_deleted_qt_object") and self._is_deleted_qt_object(insert_node):
                    continue
                if insert_node.action_type != "insert_block":
                    continue

                data_node = next(
                    (
                        incoming.source_node
                        for incoming in insert_node.edges_in
                        if incoming.source_node.action_type != "import_template"
                    ),
                    None,
                )
                if data_node is None:
                    continue

                data_name = self.ctx.dedup_map.get(data_node.node_id) or data_node.params.get("out_name")
                if not data_name or data_name not in self.ctx.data_pool:
                    continue

                params = insert_node.params
                success, msg = insert_into_template(
                    wb,
                    self.ctx.get_data(data_name),
                    params.get("sheet_name") or wb.sheetnames[0],
                    params.get("start_row") or "max_row + 1",
                    params.get("start_col") or "1",
                    columns=["*"],
                    write_header=params.get("write_header", True),
                    inherit_style=False,
                    end_row_expr=params.get("end_row") or None,
                    end_col_expr=params.get("end_col") or None,
                )
                if not success:
                    self.preview_title.setText(f"模板预览失败: {msg}")
                    self.preview_title.setStyleSheet("color: #B91C1C; font-weight: bold;")
                    self.lbl_shape.setText("(0 行 0 列)")
                    return True
                applied += 1

            value = workbook_to_preview_data(wb, node.params.get("output_path") or "未保存")
            self.preview_title.setText(f"导入模板预览: 已应用 {applied} 个插入区域")
            self.preview_title.setStyleSheet("color: #2196F3; font-weight: bold;")
            self._add_preview_value("模板预览", value)
            return True
        except Exception as exc:
            self.preview_title.setText(f"模板预览失败: {exc}")
            self.preview_title.setStyleSheet("color: #B91C1C; font-weight: bold;")
            self.lbl_shape.setText("(0 行 0 列)")
            return True
        finally:
            close_workbook(wb)

    def _add_preview_value(self, title, value):
        if _is_template_preview(value):
            for sheet_name, df in value.get("sheets", {}).items():
                self._add_preview_tab(sheet_name, df)
            if not value.get("sheets"):
                self.lbl_shape.setText("(0 行 0 列)")
            return
        self._add_preview_tab(title, value)

    def _preview_shape_text(self, rows, cols):
        suffix = ""
        if rows > PREVIEW_ROW_LIMIT:
            suffix = f"，仅预览前 {PREVIEW_ROW_LIMIT} 行"
        return f"({rows} 行 {cols} 列{suffix})"

    def _add_preview_tab(self, title, df):
        table = QTableView()
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableView { border: none; background-color: white; gridline-color: #eee; } "
            "QHeaderView::section { background-color: #E1F5FE; font-weight: bold; border: 1px solid #ccc; padding: 4px; }"
        )
        rows, cols = df.shape
        model = PandasModel(df, max_preview_rows=PREVIEW_ROW_LIMIT)
        table.setModel(model)
        idx = self.preview_tabs.addTab(table, title)
        self._current_tab_shapes[idx] = (rows, cols)
        if idx == 0:
            self.lbl_shape.setText(self._preview_shape_text(rows, cols))

    def _on_tab_changed(self, index):
        if index in self._current_tab_shapes:
            rows, cols = self._current_tab_shapes[index]
            self.lbl_shape.setText(self._preview_shape_text(rows, cols))
        else:
            self.lbl_shape.setText("(0 行 0 列)")
