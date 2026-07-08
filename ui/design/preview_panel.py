"""Preview-panel behavior for the design mode."""

import os

import pandas as pd

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableView

from table_model import PandasModel
from template_engine import workbook_sheet_preview_data, workbook_to_preview_data

try:
    from openpyxl.workbook.workbook import Workbook
    from openpyxl.worksheet.worksheet import Worksheet
except ImportError:  # pragma: no cover - openpyxl is bundled for normal app usage.
    Workbook = None
    Worksheet = None

PREVIEW_ROW_LIMIT = 5000
PREVIEW_MODEL_CACHE_LIMIT = 16
EMPTY_PREVIEW_LABEL = "暂无数据"
LEGACY_TEMPLATE_PREVIEW_MAX_ROWS = "5000"
LEGACY_TEMPLATE_PREVIEW_MAX_COLS = "200"


def _is_template_preview(value):
    return (
        isinstance(value, dict)
        and value.get("_template_preview")
        and isinstance(value.get("sheets"), dict)
    )


def _is_workbook_entry(value):
    return isinstance(value, dict) and value.get("_wb") is not None


def _is_workbook_like(value):
    if _is_workbook_entry(value):
        return True
    if Workbook is not None and isinstance(value, Workbook):
        return True
    return Worksheet is not None and isinstance(value, Worksheet)


def _workbook_and_sheet_from_value(value):
    if _is_workbook_entry(value):
        wb = value.get("_wb")
        if Worksheet is not None and isinstance(wb, Worksheet):
            return getattr(wb, "parent", None), wb.title
        return wb, None
    if Workbook is not None and isinstance(value, Workbook):
        return value, None
    if Worksheet is not None and isinstance(value, Worksheet):
        return getattr(value, "parent", None), value.title
    return None, None


def _preview_limit_from_params(params, key, legacy_default=None):
    raw = (params or {}).get(key)
    text = str(raw or "").strip()
    if not text or (legacy_default is not None and text == str(legacy_default)):
        return None
    try:
        value = int(text)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _workbook_saved_path(value):
    if not isinstance(value, dict):
        return ""
    meta = value.get("_meta") if isinstance(value.get("_meta"), dict) else {}
    return str(
        value.get("_saved_path")
        or value.get("_template_path")
        or meta.get("path")
        or ""
    )


class PreviewPanelMixin:
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

    def refresh_combo_list(self, *args):
        self._is_updating_combo = True
        self.combo_preview_tables.blockSignals(True)

        current_text = self.combo_preview_tables.currentText()
        self.combo_preview_tables.clear()

        tables = list(self.ctx.data_pool.keys())
        if not tables:
            self._clear_preview_model_cache()
        if tables:
            self.combo_preview_tables.addItems(tables)
            if current_text in tables:
                self.combo_preview_tables.setCurrentText(current_text)
        else:
            self.combo_preview_tables.addItem(EMPTY_PREVIEW_LABEL)

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
            if self.combo_preview_tables.currentText() != EMPTY_PREVIEW_LABEL:
                self.preview_title.setText(
                    f"已锁定表: 【{self.combo_preview_tables.currentText()}】"
                )
                self.preview_title.setStyleSheet("color: #E65100; font-weight: bold;")

    def _on_manual_combo_changed(self, index):
        if self._is_updating_combo or index < 0:
            return

        table_name = self.combo_preview_tables.currentText()
        if table_name and table_name != EMPTY_PREVIEW_LABEL:
            self.chk_auto_follow.blockSignals(True)
            self.chk_auto_follow.setChecked(False)
            self.chk_auto_follow.setStyleSheet("font-weight: normal; color: #999;")
            self.chk_auto_follow.blockSignals(False)
            self._render_specific_table(table_name)

    def _render_specific_table(self, table_name):
        self.preview_tabs.clear()
        self._current_tab_shapes.clear()

        if table_name in self.ctx.data_pool:
            value = self.ctx.get_data(table_name)
            self.preview_title.setText(f"已锁定表: 【{table_name}】")
            self.preview_title.setStyleSheet("color: #E65100; font-weight: bold;")
            self._add_preview_value(f"锁定视图: {table_name}", value)
        else:
            self.preview_title.setText(f"锁定表【{table_name}】暂无数据")
            self.lbl_shape.setText("(0 行, 0 列)")

    def _node_preview_refs(self, node):
        node_id = str(getattr(node, "node_id", ""))
        refs = []
        seen = set()

        def add_ref(output_id, name=""):
            output_id = str(output_id or "out_1")
            if output_id in seen:
                return
            seen.add(output_id)
            refs.append((output_id, str(name or output_id)))

        for output in node.params.get("outputs") or []:
            if isinstance(output, dict):
                add_ref(output.get("output_id"), output.get("name"))
        for output in getattr(self.ctx, "raw_node_output_refs", lambda _node_id: [])(node_id):
            if isinstance(output, dict):
                add_ref(output.get("output_id"), output.get("name"))
        for output_id, key in getattr(self.ctx, "output_key_map", {}).get(node_id, {}).items():
            add_ref(output_id, key)
        for raw_node_id, output_id in getattr(self.ctx, "raw_data_pool", {}):
            if raw_node_id == node_id:
                add_ref(output_id)
        return refs

    def _node_preview_outputs(self, node):
        node_id = str(getattr(node, "node_id", ""))
        output_keys = getattr(self.ctx, "output_key_map", {}).get(node_id, {})
        data_pool = getattr(self.ctx, "data_pool", {})
        raw_data_pool = getattr(self.ctx, "raw_data_pool", {})
        rows = []
        used_output_ids = set()

        for output_id, fallback_name in self._node_preview_refs(node):
            raw_key = (node_id, output_id)
            if raw_key in raw_data_pool and _is_workbook_like(raw_data_pool[raw_key]):
                rows.append((output_id, fallback_name, raw_data_pool[raw_key]))
                used_output_ids.add(output_id)
                continue
            key = output_keys.get(output_id)
            if key and key in data_pool:
                rows.append((output_id, key, self.ctx.get_data(key)))
                used_output_ids.add(output_id)
                continue
            if raw_key in raw_data_pool:
                rows.append((output_id, fallback_name, raw_data_pool[raw_key]))
                used_output_ids.add(output_id)

        for output_id, key in output_keys.items():
            if output_id in used_output_ids or key not in data_pool:
                continue
            rows.append((output_id, key, self.ctx.get_data(key)))
            used_output_ids.add(output_id)

        for raw_node_id, output_id in raw_data_pool:
            if raw_node_id != node_id or output_id in used_output_ids:
                continue
            rows.append((output_id, output_id, raw_data_pool[(raw_node_id, output_id)]))
            used_output_ids.add(output_id)
        return rows

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
            self.lbl_shape.setText("(0 行, 0 列)")
            return

        outputs = self._node_preview_outputs(node)
        if outputs:
            first_key = outputs[0][1]
            self._is_updating_combo = True
            if self.combo_preview_tables.findText(first_key) >= 0:
                self.combo_preview_tables.setCurrentText(first_key)
            self._is_updating_combo = False

            suffix = f" | {len(outputs)} 个输出" if len(outputs) > 1 else ""
            self.preview_title.setText(f"跟随节点: 【{node.title}】{suffix}")
            self.preview_title.setStyleSheet("color: #2196F3; font-weight: bold;")
            for _output_id, key, value in outputs:
                self._add_preview_value(key, value, node.params)
            return

        if node.action_type == "import_template" and self._render_import_template_preview(node):
            return

        self.preview_title.setText("源模式: 正在查看上游原始数据")
        self.preview_title.setStyleSheet("color: #673AB7; font-weight: bold;")

        valid_sources = 0
        for i, edge in enumerate(node.edges_in):
            up_node = edge.source_node
            if hasattr(self, "_is_deleted_qt_object") and self._is_deleted_qt_object(up_node):
                continue
            for _output_id, up_name, value in self._node_preview_outputs(up_node):
                if node.action_type == "left_join" and i == 0:
                    prefix = "左表"
                elif node.action_type == "left_join":
                    prefix = "右表"
                else:
                    prefix = "来源表"
                self._add_preview_value(f"{prefix}: {up_name}", value, up_node.params)
                valid_sources += 1

        if valid_sources == 0:
            self.preview_title.setText("源模式失败: 连接的上游尚未产生数据")
            self.lbl_shape.setText("(0 行, 0 列)")

    def _render_import_template_preview(self, node):
        template_path = str(node.params.get("template_path") or "").strip()
        if not template_path:
            self.preview_title.setText("加载模板预览：请先选择模板文件")
        else:
            file_name = os.path.basename(template_path) or template_path
            self.preview_title.setText(f"加载模板预览：{file_name} 尚未运行")
        self.preview_title.setStyleSheet("color: #64748B; font-weight: bold;")
        self.lbl_shape.setText("运行加载模板节点后，将使用内存中的工作簿生成预览")
        return True

    def _workbook_preview_data(self, value, params=None):
        wb, forced_sheet = _workbook_and_sheet_from_value(value)
        if wb is None:
            raise ValueError("Workbook 对象为空，无法生成预览")
        params = params or {}
        preview_kwargs = {
            "start_row": params.get("preview_start_row") or 1,
            "start_col": params.get("preview_start_col") or 1,
        }
        max_rows = _preview_limit_from_params(
            params,
            "preview_max_rows",
            LEGACY_TEMPLATE_PREVIEW_MAX_ROWS,
        )
        max_cols = _preview_limit_from_params(
            params,
            "preview_max_cols",
            LEGACY_TEMPLATE_PREVIEW_MAX_COLS,
        )
        if max_rows is not None:
            preview_kwargs["max_rows"] = max_rows
        if max_cols is not None:
            preview_kwargs["max_cols"] = max_cols
        if forced_sheet:
            return workbook_sheet_preview_data(
                wb,
                forced_sheet,
                _workbook_saved_path(value),
                **preview_kwargs,
            )
        return workbook_to_preview_data(
            wb,
            _workbook_saved_path(value),
            max_sheets=None,
            **preview_kwargs,
        )

    def _add_workbook_preview_value(self, title, value, params=None):
        try:
            preview = self._workbook_preview_data(value, params)
        except Exception as exc:
            self._add_preview_tab(title, pd.DataFrame([{"预览错误": str(exc)}]))
            return
        self._add_template_preview_value(preview)

    def _add_template_preview_value(self, value):
        for sheet_name, df in value.get("sheets", {}).items():
            self._add_preview_tab(sheet_name, df)
        if not value.get("sheets"):
            self.lbl_shape.setText("(0 行, 0 列)")

    def _add_preview_value(self, title, value, params=None):
        if _is_workbook_like(value):
            self._add_workbook_preview_value(title, value, params)
            return
        if _is_template_preview(value):
            self._add_template_preview_value(value)
            return
        self._add_preview_tab(title, value)

    def _preview_shape_text(self, rows, cols):
        suffix = ""
        if rows > PREVIEW_ROW_LIMIT:
            suffix = f"，仅预览前 {PREVIEW_ROW_LIMIT} 行"
        return f"({rows} 行, {cols} 列{suffix})"

    def _add_preview_tab(self, title, df):
        if not hasattr(df, "shape"):
            df = pd.DataFrame([{"值": df}])
        table = QTableView()
        table.setProperty("preview_title", title)
        table.setProperty("is_template_preview", bool(getattr(df, "attrs", {}).get("_hide_column_names")))
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableView { border: none; background-color: white; gridline-color: #eee; } "
            "QHeaderView::section { background-color: #E1F5FE; font-weight: bold; border: 1px solid #ccc; padding: 4px; }"
        )
        rows, cols = df.shape
        model = self._model_for_preview(title, df)
        table.setModel(model)
        table.selectionModel().selectionChanged.connect(
            lambda selected, _deselected, view=table: self._on_preview_cell_selected(view)
        )
        idx = self.preview_tabs.addTab(table, title)
        self._current_tab_shapes[idx] = (rows, cols)
        if idx == 0:
            self.lbl_shape.setText(self._preview_shape_text(rows, cols))

    def _on_preview_cell_selected(self, table):
        if not bool(table.property("is_template_preview")):
            return
        index = table.currentIndex()
        if not index.isValid():
            return
        model = table.model()
        df = getattr(model, "_df", None)
        if df is None:
            return
        try:
            excel_row = int(df.index[index.row()])
        except Exception:
            excel_row = index.row() + 1
        try:
            excel_col = int(df.columns[index.column()])
        except Exception:
            start_col = getattr(df, "attrs", {}).get("_range_start_col") or 1
            try:
                start_col = int(start_col)
            except Exception:
                start_col = 1
            excel_col = start_col + index.column()
        sheet_name = str(table.property("preview_title") or "")
        self._selected_template_cell = {
            "sheet_name": sheet_name,
            "row": excel_row,
            "col": excel_col,
        }
        self.lbl_shape.setText(f"选中: {sheet_name}!R{excel_row}C{excel_col}")
        node = self._current_live_node() if hasattr(self, "_current_live_node") else getattr(self, "current_selected_node", None)
        if node is None or getattr(node, "action_type", "") != "import_template":
            return
        panel = getattr(self, "panel_instances", {}).get("import_template")
        if panel and hasattr(panel, "_selected_template_cell"):
            panel._selected_template_cell = dict(self._selected_template_cell)
            if hasattr(panel, "set_selected_template_cell"):
                panel.set_selected_template_cell(sheet_name, excel_row, excel_col)

    def _on_tab_changed(self, index):
        if index in self._current_tab_shapes:
            rows, cols = self._current_tab_shapes[index]
            self.lbl_shape.setText(self._preview_shape_text(rows, cols))
        else:
            self.lbl_shape.setText("(0 行, 0 列)")
