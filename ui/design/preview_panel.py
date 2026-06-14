"""Preview-panel behavior for the design mode."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableView

from table_model import PandasModel


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

        # 优先用 dedup 后的实际 key，回退到原始 out_name。
        out_name = self.ctx.dedup_map.get(node.node_id) or node.params.get("out_name")

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
            self.preview_title.setText("溯源模式: 【正在查看上游原材料】")
            self.preview_title.setStyleSheet("color: #673AB7; font-weight: bold;")

            upstream_nodes = [edge.source_node for edge in node.edges_in]
            valid_sources = 0
            for i, up_node in enumerate(upstream_nodes):
                up_name = self.ctx.dedup_map.get(up_node.node_id) or up_node.params.get("out_name")
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
                self.preview_title.setText("溯源失败: 【连入的上游尚未产生数据】")
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
