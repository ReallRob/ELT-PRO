"""Result preview and export actions for execute mode."""

from PyQt5.QtWidgets import QFileDialog, QMessageBox

from table_model import PandasModel

PREVIEW_ROW_LIMIT = 5000


def _is_template_preview(value):
    return (
        isinstance(value, dict)
        and value.get("_template_preview")
        and isinstance(value.get("sheets"), dict)
    )


class ExecutePreviewMixin:
    def on_node_clicked(self, table_name, is_action):
        if not table_name:
            return

        self.current_preview_table = table_name

        if table_name in self.final_pool:
            value = self.final_pool[table_name]
            if _is_template_preview(value):
                sheets = value.get("sheets") or {}
                sheet_name, df = next(iter(sheets.items()), ("", None))
                if df is None:
                    self.preview_title.setText(
                        f"当前预览: 【{table_name}】 (模板无可预览工作表)"
                    )
                    self.result_table.setModel(None)
                    self.btn_export_preview.hide()
                    return
                self.preview_title.setText(
                    f"当前预览: 【{table_name} / {sheet_name}】 "
                    f"({df.shape[0]} 行, {df.shape[1]} 列，共 {len(sheets)} 个工作表)"
                )
            else:
                df = value
                self.preview_title.setText(
                    f"当前预览: 【{table_name}】 ({df.shape[0]} 行, {df.shape[1]} 列)"
                )

            self.preview_title.setStyleSheet(
                "padding: 5px; color: #2196F3; font-weight: bold;"
            )
            model = PandasModel(df, max_preview_rows=PREVIEW_ROW_LIMIT)
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

        value = self.final_pool[table_name]
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"导出 {table_name}",
            f"{table_name}.xlsx",
            "Excel (*.xlsx);;CSV (*.csv)",
        )
        if path:
            try:
                if _is_template_preview(value):
                    if path.endswith(".csv"):
                        _, first_df = next(iter(value.get("sheets", {}).items()))
                        first_df.to_csv(path, index=False, header=False, encoding="utf-8-sig")
                    else:
                        with __import__("pandas").ExcelWriter(path) as writer:
                            for sheet_name, df in value.get("sheets", {}).items():
                                df.to_excel(writer, sheet_name=sheet_name[:31], index=False, header=False)
                elif path.endswith(".csv"):
                    value.to_csv(path, index=False, encoding="utf-8-sig")
                else:
                    value.to_excel(path, index=False)
                self.log_print(f"[成功] 成功导出表格至: {path}")
                QMessageBox.information(self, "导出成功", f"文件已保存：\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", str(e))
