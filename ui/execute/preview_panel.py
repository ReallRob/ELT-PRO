"""Result preview and export actions for execute mode."""

from PyQt5.QtWidgets import QFileDialog, QMessageBox

from table_model import PandasModel


class ExecutePreviewMixin:
    def on_node_clicked(self, table_name, is_action):
        if not table_name:
            return

        self.current_preview_table = table_name

        if table_name in self.final_pool:
            df = self.final_pool[table_name]
            self.preview_title.setText(
                f"当前预览: 【{table_name}】 ({df.shape[0]} 行, {df.shape[1]} 列)"
            )
            self.preview_title.setStyleSheet(
                "padding: 5px; color: #2196F3; font-weight: bold;"
            )

            model = PandasModel(df)
            self.result_table.setModel(model)
            self.btn_export_preview.show()
        else:
            self.preview_title.setText(
                f"表 【{table_name}】 无数据。可能是未执行或作为中间表内存已被释放。"
            )
            self.preview_title.setStyleSheet(
                "padding: 5px; color: #E91E63; font-weight: bold;"
            )
            self.result_table.setModel(None)
            self.btn_export_preview.hide()

    def export_current_table(self):
        if self.current_preview_table:
            self.export_single_table(self.current_preview_table)

    def export_single_table(self, table_name):
        if table_name not in self.final_pool:
            QMessageBox.warning(self, "错误", "该表尚无结果数据或内存已被释放。")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            f"导出 {table_name}",
            f"{table_name}.xlsx",
            "Excel (*.xlsx);;CSV (*.csv)",
        )
        if path:
            try:
                if path.endswith(".csv"):
                    self.final_pool[table_name].to_csv(
                        path, index=False, encoding="utf-8-sig"
                    )
                else:
                    self.final_pool[table_name].to_excel(path, index=False)
                self.log_print(f"[成功] 成功导出表格至: {path}")
                QMessageBox.information(self, "导出成功", f"文件已保存：\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", str(e))
