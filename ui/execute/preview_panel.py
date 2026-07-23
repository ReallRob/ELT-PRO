"""Result preview and export actions for execute mode."""

import os
import shutil

import pandas as pd
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QTableView

from table_model import PandasModel

PREVIEW_ROW_LIMIT = 5000
PREVIEW_MODEL_CACHE_LIMIT = 8


def _is_template_preview(value):
    return (
        isinstance(value, dict)
        and value.get("_template_preview")
        and isinstance(value.get("sheets"), dict)
    )


def _normalize_table_names(table_names):
    if isinstance(table_names, str):
        raw_names = [table_names]
    elif isinstance(table_names, (list, tuple, set)):
        raw_names = table_names
    else:
        raw_names = [table_names]

    names = []
    seen = set()
    for name in raw_names:
        text = str(name or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        names.append(text)
    return names


class ExecutePreviewMixin:
    def _preview_model_cache(self):
        cache = getattr(self, "_preview_model_cache_store", None)
        if cache is None:
            cache = {}
            self._preview_model_cache_store = cache
        return cache

    def _clear_preview_model_cache(self):
        cache = getattr(self, "_preview_model_cache_store", None)
        if cache is not None:
            cache.clear()

    def _model_for_preview(self, title, df):
        cache = self._preview_model_cache()
        key = PandasModel.cache_key(df, PREVIEW_ROW_LIMIT, title)
        model = cache.get(key)
        if model is not None:
            return model
        if len(cache) >= PREVIEW_MODEL_CACHE_LIMIT:
            cache.pop(next(iter(cache)))
        model = PandasModel(df, max_preview_rows=PREVIEW_ROW_LIMIT)
        cache[key] = model
        return model

    def _clear_preview_tabs(self):
        tabs = getattr(self, "result_preview_tabs", None)
        if tabs is not None:
            tabs.clear()
        table = getattr(self, "result_table", None)
        if table is not None:
            table.setModel(None)
        self.result_table = None
        self.current_preview_table = None
        self._current_preview_missing_count = 0

    def _preview_shape_text(self, rows, cols):
        suffix = ""
        if rows > PREVIEW_ROW_LIMIT:
            suffix = f"，仅预览前 {PREVIEW_ROW_LIMIT} 行"
        return f"{rows} 行, {cols} 列{suffix}"

    def _as_preview_dataframe(self, value):
        if hasattr(value, "shape"):
            return value
        return pd.DataFrame([{"值": value}])

    def _make_preview_table(self, title, df):
        table = QTableView()
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableView { border: none; background-color: white; gridline-color: #eee; } "
            "QHeaderView::section { background-color: #E1F5FE; font-weight: bold; "
            "border: 1px solid #ddd; padding: 3px; font-size: 11px; }"
        )
        table.setModel(self._model_for_preview(title, df))
        return table

    def _add_preview_tab(self, title, table_name, value, sheet_name=""):
        tabs = getattr(self, "result_preview_tabs", None)
        if tabs is None:
            return 0

        df = self._as_preview_dataframe(value)
        rows, cols = df.shape
        table = self._make_preview_table(title, df)
        table.setProperty("preview_table_name", table_name)
        table.setProperty("preview_sheet_name", sheet_name)
        table.setProperty("preview_rows", rows)
        table.setProperty("preview_cols", cols)

        index = tabs.addTab(table, title)
        if index == 0:
            self.result_table = table
        return 1

    def _add_preview_value(self, table_name, value):
        if _is_template_preview(value):
            sheets = value.get("sheets") or {}
            if not sheets:
                empty_df = pd.DataFrame([{"提示": "模板无可预览工作表"}])
                return self._add_preview_tab(table_name, table_name, empty_df)
            count = 0
            for sheet_name, df in sheets.items():
                title = f"{table_name} / {sheet_name}"
                count += self._add_preview_tab(title, table_name, df, sheet_name)
            return count
        return self._add_preview_tab(table_name, table_name, value)

    def _on_preview_tab_changed(self, index):
        tabs = getattr(self, "result_preview_tabs", None)
        if tabs is None or index < 0:
            return
        table = tabs.widget(index)
        if table is None:
            return

        table_name = str(table.property("preview_table_name") or "")
        sheet_name = str(table.property("preview_sheet_name") or "")
        rows = int(table.property("preview_rows") or 0)
        cols = int(table.property("preview_cols") or 0)
        self.current_preview_table = table_name
        self.result_table = table

        title = f"当前预览: 【{table_name}】"
        if sheet_name:
            title = f"当前预览: 【{table_name} / {sheet_name}】"

        parts = [self._preview_shape_text(rows, cols)]
        if tabs.count() > 1:
            parts.append(f"共 {tabs.count()} 个标签")
        missing_count = int(getattr(self, "_current_preview_missing_count", 0) or 0)
        if missing_count:
            parts.append(f"{missing_count} 个输出暂无数据")

        self.preview_title.setText(f"{title} ({'，'.join(parts)})")
        self.preview_title.setStyleSheet(
            "padding: 5px; color: #2196F3; font-weight: bold;"
        )
        self.btn_export_preview.setVisible(bool(table_name in self.final_pool))

    def on_node_clicked(self, table_names, is_action):
        names = _normalize_table_names(table_names)
        if not names:
            return

        self._clear_preview_tabs()
        missing = []
        added_count = 0
        for table_name in names:
            if table_name not in self.final_pool:
                missing.append(table_name)
                continue
            added_count += self._add_preview_value(table_name, self.final_pool[table_name])

        self._current_preview_missing_count = len(missing)
        tabs = getattr(self, "result_preview_tabs", None)
        if added_count and tabs is not None:
            tabs.setCurrentIndex(0)
            self._on_preview_tab_changed(tabs.currentIndex())
            return

        missing_text = "、".join(names[:3])
        if len(names) > 3:
            missing_text += "..."
        self.preview_title.setText(
            f"节点输出【{missing_text}】无数据。可能是未执行，或中间表内存已被释放。"
        )
        self.preview_title.setStyleSheet(
            "padding: 5px; color: #E91E63; font-weight: bold;"
        )
        self._clear_preview_model_cache()
        self.btn_export_preview.hide()

    def _selected_preview_table_name(self):
        tabs = getattr(self, "result_preview_tabs", None)
        if tabs is not None and tabs.count() > 0:
            table = tabs.currentWidget()
            if table is not None:
                table_name = str(table.property("preview_table_name") or "").strip()
                if table_name:
                    return table_name
        return self.current_preview_table

    def export_current_table(self):
        table_name = self._selected_preview_table_name()
        if table_name:
            self.export_single_table(table_name)

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
                        saved_path = str(value.get("saved_path") or "")
                        same_path = (
                            saved_path
                            and os.path.exists(saved_path)
                            and os.path.abspath(saved_path) == os.path.abspath(path)
                        )
                        if same_path:
                            pass
                        elif saved_path and os.path.exists(saved_path):
                            shutil.copyfile(saved_path, path)
                        else:
                            with __import__("pandas").ExcelWriter(path) as writer:
                                for sheet_name, df in value.get("sheets", {}).items():
                                    df.to_excel(
                                        writer,
                                        sheet_name=sheet_name[:31],
                                        index=False,
                                        header=False,
                                    )
                elif path.endswith(".csv"):
                    value.to_csv(path, index=False, encoding="utf-8-sig")
                else:
                    value.to_excel(path, index=False)
                self.log_print(f"[成功] 成功导出表格至: {path}")
                QMessageBox.information(self, "导出成功", f"文件已保存：\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", str(e))
