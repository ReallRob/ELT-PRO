import os
import sys
import pandas as pd
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QPushButton,
    QComboBox,
    QLineEdit,
    QLabel,
    QMessageBox,
    QFileDialog,
    QScrollArea,
)
from PyQt5.QtCore import Qt, pyqtSignal, QAbstractTableModel, QModelIndex
from PyQt5.QtGui import QColor, QFont

from xlsx_fun import (
    get_col_data,
    filter_data,
    group_calc,
    left_join,
    rank_col,
    sort_data,
    calc_col,
    clean_data,
    export_df,
    normalize_columns,
)


class PandasModel(QAbstractTableModel):
    def __init__(self, df=pd.DataFrame(), parent=None):
        super().__init__(parent)
        self._df = df

        # 懒加载核心：初始只加载前 200 行（足以填满屏幕），每次滚动触底再抓取 200 行
        self.batch_size = 200
        self._loaded_rows = min(len(df), self.batch_size)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            n = section + 1
            col_letter = ""
            while n > 0:
                n, rem = divmod(n - 1, 26)
                col_letter = chr(65 + rem) + col_letter
            return col_letter
        if orientation == Qt.Vertical:
            if section == 0:
                return "字段名"
            return str(self._df.index[section - 1])
        return None

    def rowCount(self, parent=None):
        # 视图行数 = 当前已加载的行数 + 1 (第一行作为字段名展示)
        return self._loaded_rows + 1

    def columnCount(self, parent=None):
        return len(self._df.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()

        if role == Qt.DisplayRole:
            if row == 0:
                return str(self._df.columns[col])
            try:
                # 性能优化：使用 iat 替代 iloc，提取单一标量速度极快
                val = self._df.iat[row - 1, col]
                return str(val) if pd.notna(val) else ""
            except Exception:
                return ""
        elif role == Qt.BackgroundRole and row == 0:
            return QColor("#FFF8E1")
        elif role == Qt.FontRole and row == 0:
            font = QFont()
            font.setBold(True)
            return font
        return None

    # ==========================================
    # 懒加载 (Lazy Loading) 核心接口实现
    # ==========================================
    def canFetchMore(self, parent=None):
        """告诉视图是否还有更多数据没有加载"""
        return self._loaded_rows < len(self._df)

    def fetchMore(self, parent=None):
        """视图滚动到底部时，自动调用此方法抓取下一批数据"""
        if self._loaded_rows < len(self._df):
            remainder = len(self._df) - self._loaded_rows
            items_to_fetch = min(remainder, self.batch_size)

            # 通知视图即将插入新行，Qt 会自动计算并更新滚动条的比例
            self.beginInsertRows(
                QModelIndex(), self._loaded_rows + 1, self._loaded_rows + items_to_fetch
            )
            self._loaded_rows += items_to_fetch
            self.endInsertRows()


class BaseToolPanel(QWidget):
    step_recorded = pyqtSignal(str, dict, object, str)

    use_df = True
    use_type = True
    use_out = True
    theme_color = "#2196F3"
    action_name = "未命名"

    def __init__(self, data_pool, parent=None):
        super().__init__(parent)
        self.data_pool = data_pool
        self.combo_boxes_to_update = []
        self._init_base_ui()

    def _init_base_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.setStyleSheet("""
            QComboBox QAbstractItemView {
                background-color: white; color: #333333;
                selection-background-color: #E0E0E0; selection-color: black;
            }
        """)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background-color: transparent; }")

        self.content_widget = QWidget()
        self.main_layout = QVBoxLayout(self.content_widget)
        self.main_layout.setContentsMargins(10, 10, 10, 10)

        self.top_form = QFormLayout()
        if self.use_df:
            self.df_combo = QComboBox()
            self.combo_boxes_to_update.append(self.df_combo)
            self.top_form.addRow("目标表:", self.df_combo)

        if self.use_type:
            self.type_combo = QComboBox()
            self.type_combo.addItems(
                ["col_name (列名)", "col_word (字母)", "col_index (索引)"]
            )
            self.top_form.addRow("匹配模式:", self.type_combo)

        self.main_layout.addLayout(self.top_form)

        self.custom_layout = QVBoxLayout()
        self.main_layout.addLayout(self.custom_layout)
        self.init_custom_ui()

        self.bottom_form = QFormLayout()
        if self.use_out:
            self.out_input = QLineEdit()
            self.out_input.setPlaceholderText(
                f"可选: 默认命名为 [目标表_{self.action_name}]"
            )
            self.bottom_form.addRow("结果命名:", self.out_input)
        self.main_layout.addLayout(self.bottom_form)

        self.main_layout.addStretch()
        self.scroll_area.setWidget(self.content_widget)
        outer_layout.addWidget(self.scroll_area)

        btn_layout = QVBoxLayout()
        btn_layout.setContentsMargins(10, 5, 10, 10)
        btn = QPushButton(f"单步执行并更新")
        btn.setStyleSheet(
            f"background-color: {self.theme_color}; color: white; height: 38px; font-weight: bold; border-radius: 4px; font-size: 13px;"
        )
        btn.clicked.connect(self.execute)
        btn_layout.addWidget(btn)

        outer_layout.addLayout(btn_layout)

    def set_params(self, p):
        if self.use_df and "df_name" in p:
            self.df_combo.setCurrentText(p["df_name"])
        if self.use_type:
            self._set_combo_by_prefix(self.type_combo, p.get("col_type"))
        if self.use_out and "out_name" in p:
            self.out_input.setText(p["out_name"])
        self.set_custom_params(p)

    def get_params(self):
        p = {}
        if self.use_df:
            p["df_name"] = self.df_combo.currentText()
        if self.use_type:
            p["col_type"] = self.type_combo.currentText().split(" ")[0]
        if self.use_out:
            p["out_name"] = self.out_input.text().strip()
        p.update(self.get_custom_params())
        return p

    def clear_ui(self):
        if self.use_out:
            self.out_input.clear()
        self.clear_custom_ui()

    def _set_combo_by_prefix(self, combo, prefix):
        if not prefix:
            return
        for i in range(combo.count()):
            if combo.itemText(i).startswith(prefix):
                return combo.setCurrentIndex(i)

    def clear_dynamic_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def update_combos(self, table_names):
        for combo in self.combo_boxes_to_update:
            current = combo.currentText()
            combo.clear()
            combo.addItems(table_names)
            if current in table_names:
                combo.setCurrentText(current)
            elif combo.count() > 0:
                combo.setCurrentIndex(0)

    def init_custom_ui(self):
        pass

    def set_custom_params(self, p):
        pass

    def get_custom_params(self):
        return {}

    def clear_custom_ui(self):
        pass

    def execute(self):
        pass


class LoadFilePanel(BaseToolPanel):
    use_df = False
    use_type = False
    theme_color = "#1976D2"
    action_name = "导入"

    def init_custom_ui(self):
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("选择源文件 (.xlsx / .csv)")
        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self.browse_path)
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(btn_browse)
        self.top_form.addRow("文件路径:", path_layout)

        self.sheet_combo = QComboBox()
        self.sheet_combo.currentTextChanged.connect(self.auto_update_out_name)
        self.top_form.addRow("工作表(Excel):", self.sheet_combo)

        self.skip_input = QLineEdit("0")
        self.top_form.addRow("跳过前N行:", self.skip_input)

        self.nrows_input = QLineEdit()
        self.nrows_input.setPlaceholderText("读取行数 (留空为全部)")
        self.top_form.addRow("限制行数:", self.nrows_input)

    def browse_path(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择数据源", "", "Excel/CSV (*.xlsx *.xls *.csv)"
        )
        if path:
            self.path_input.setText(path)
            self.update_sheets(path)

    def update_sheets(self, path):
        self.sheet_combo.clear()
        if path.endswith((".xlsx", ".xls")):
            try:
                sheets = pd.ExcelFile(path).sheet_names
                self.sheet_combo.addItems(sheets)
            except:
                pass
        else:
            self.sheet_combo.addItem("CSV (无工作表)")

    def auto_update_out_name(self, text):
        if not text:
            return
        if text == "CSV (无工作表)":
            if self.path_input.text():
                base_name = os.path.basename(self.path_input.text()).split(".")[0]
                self.out_input.setText(base_name)
        else:
            self.out_input.setText(text)

    def get_custom_params(self):
        return {
            "file_path": self.path_input.text().strip(),
            "sheet_name": (
                self.sheet_combo.currentText() if self.sheet_combo.count() > 0 else 0
            ),
            "skiprows": int(self.skip_input.text() or 0),
            "nrows": (
                int(self.nrows_input.text())
                if self.nrows_input.text().strip()
                else None
            ),
        }

    def set_custom_params(self, p):
        if "file_path" in p:
            self.path_input.setText(p["file_path"])
            self.update_sheets(p["file_path"])
        if "sheet_name" in p:
            self.sheet_combo.setCurrentText(str(p["sheet_name"]))
        if "skiprows" in p:
            self.skip_input.setText(str(p["skiprows"]))
        if "nrows" in p and p["nrows"] is not None:
            self.nrows_input.setText(str(p["nrows"]))

    def execute(self):
        p = self.get_params()
        if not p["file_path"] or not os.path.exists(p["file_path"]):
            return QMessageBox.warning(self, "错误", "请选择有效的文件路径！")

        out_name = p["out_name"] or os.path.basename(p["file_path"]).split(".")[0]
        try:
            if p["file_path"].endswith((".xlsx", ".xls")):
                sheet = p["sheet_name"] if p["sheet_name"] != "CSV (无工作表)" else 0
                df = pd.read_excel(
                    p["file_path"],
                    sheet_name=sheet,
                    skiprows=p["skiprows"],
                    nrows=p["nrows"],
                )
            else:
                df = pd.read_csv(
                    p["file_path"], skiprows=p["skiprows"], nrows=p["nrows"]
                )
            self.step_recorded.emit("load_file", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))


class ExtractPanel(BaseToolPanel):
    theme_color = "#009688"
    action_name = "提取"

    def init_custom_ui(self):
        self.fill_input = QLineEdit()
        self.fill_input.setPlaceholderText("可选: 缺失值填充...")
        self.top_form.addRow("填充空值:", self.fill_input)
        self.custom_layout.addWidget(QLabel("提取列及重命名配置:"))
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        self.custom_layout.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加提取列")
        btn_add.setStyleSheet("background-color: #EEEEEE; padding: 5px;")
        btn_add.clicked.connect(lambda: self.add_rule_row())
        self.custom_layout.addWidget(btn_add)
        hint = QLabel("提示：如果不填重命名，会自动保留提取列的原中文表头。")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        self.custom_layout.addWidget(hint)

    def clear_custom_ui(self):
        self.fill_input.clear()
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", rename=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        c_input = QLineEdit(str(col))
        c_input.setObjectName("col")
        c_input.setPlaceholderText("要提取的列")
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("重命名为(可选)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(c_input)
        l.addWidget(r_input)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def set_custom_params(self, p):
        if "fill_value" in p:
            self.fill_input.setText(str(p["fill_value"] or ""))
        col_list, col_names = p.get("col_list", []), p.get("col_names", [])
        if col_list:
            self.clear_dynamic_layout(self.rules_layout)
            for i, c in enumerate(col_list):
                r = col_names[i] if col_names and i < len(col_names) else ""
                self.add_rule_row(c, r)

    def get_custom_params(self):
        clist, rlist = [], []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c = w.findChild(QLineEdit, "col").text().strip()
                r = w.findChild(QLineEdit, "rename").text().strip()
                if c:
                    clist.append(c)
                    rlist.append(r)
        return {
            "col_list": clist,
            "col_names": rlist,
            "fill_value": self.fill_input.text() or None,
        }

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["col_list"]:
            return QMessageBox.warning(self, "错误", "缺少参数")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            actual_cols = normalize_columns(
                self.data_pool[p["df_name"]], p["col_list"], p["col_type"]
            )
            final_cols = [
                p["col_names"][i] if p["col_names"][i] else actual_cols[i]
                for i in range(len(actual_cols))
            ]
            df = get_col_data(
                self.data_pool[p["df_name"]],
                p["col_list"],
                p["col_type"],
                p["fill_value"],
                final_cols,
            )
            self.step_recorded.emit("get_col_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class FilterPanel(BaseToolPanel):
    theme_color = "#E91E63"
    action_name = "筛选"

    def init_custom_ui(self):
        self.logic_combo = QComboBox()
        self.logic_combo.addItems(["AND (满足所有)", "OR (满足其一)"])
        self.top_form.addRow("条件逻辑:", self.logic_combo)
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        self.custom_layout.addLayout(self.rules_layout)
        self.add_rule()
        btn_add = QPushButton("+ 添加筛选条件")
        btn_add.setStyleSheet("background-color: #EEEEEE; padding: 5px;")
        btn_add.clicked.connect(lambda: self.add_rule())
        self.custom_layout.addWidget(btn_add)
        hint = QLabel(
            "提示: isnull(找空值), notnull(排除空值), contains(包含文字)。"
        )
        hint.setStyleSheet("color: #666; font-size: 11px;")
        self.custom_layout.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule()

    def add_rule(self, col="", op="==", val=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        c_input = QLineEdit(str(col))
        c_input.setObjectName("col")
        c_input.setPlaceholderText("排查列")
        op_combo = QComboBox()
        op_combo.setObjectName("op")
        op_combo.addItems(
            [
                ">",
                "<",
                ">=",
                "<=",
                "==",
                "!=",
                "contains",
                "not_contains",
                "startswith",
                "endswith",
                "isnull",
                "notnull",
            ]
        )
        op_combo.setCurrentText(op)
        v_input = QLineEdit(str(val))
        v_input.setObjectName("val")
        v_input.setPlaceholderText("目标值")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(c_input)
        l.addWidget(op_combo)
        l.addWidget(v_input)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def set_custom_params(self, p):
        self._set_combo_by_prefix(self.logic_combo, p.get("logic"))
        conds = p.get("conditions", [])
        if conds:
            self.clear_dynamic_layout(self.rules_layout)
            for c in conds:
                self.add_rule(c.get("col"), c.get("op"), c.get("value"))

    def get_custom_params(self):
        conds = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c, op, v = (
                    w.findChild(QLineEdit, "col").text().strip(),
                    w.findChild(QComboBox, "op").currentText(),
                    w.findChild(QLineEdit, "val").text().strip(),
                )
                if c:
                    conds.append({"col": c, "op": op, "value": v})
        return {
            "logic": self.logic_combo.currentText().split(" ")[0],
            "conditions": conds,
        }

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "缺少目标表")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = filter_data(
                self.data_pool[p["df_name"]], p["conditions"], p["logic"], p["col_type"]
            )
            self.step_recorded.emit("filter_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class GroupPanel(BaseToolPanel):
    theme_color = "#673AB7"
    action_name = "汇总"

    def init_custom_ui(self):
        self.group_keys = QLineEdit()
        self.group_keys.setPlaceholderText("例: 部门, 岗位 / A, B")
        self.top_form.addRow("分组依据列:", self.group_keys)
        self.custom_layout.addWidget(QLabel("聚合统计规则:"))
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        self.custom_layout.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加聚合规则")
        btn_add.setStyleSheet("background-color: #EEEEEE; padding: 5px;")
        btn_add.clicked.connect(lambda: self.add_rule_row())
        self.custom_layout.addWidget(btn_add)
        hint = QLabel("提示: sum(求和), mean(平均), count(计数), first(取第一行)。")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        self.custom_layout.addWidget(hint)

    def clear_custom_ui(self):
        self.group_keys.clear()
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", func="sum", rename=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        c_input = QLineEdit(str(col))
        c_input.setObjectName("col")
        c_input.setPlaceholderText("运算列")
        f_combo = QComboBox()
        f_combo.setObjectName("func")
        f_combo.addItems(["sum", "mean", "max", "min", "count", "first"])
        f_combo.setCurrentText(func)
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("重命名(可选)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(c_input)
        l.addWidget(f_combo)
        l.addWidget(r_input)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def set_custom_params(self, p):
        if "group_key" in p:
            self.group_keys.setText(",".join(p["group_key"]))
        rules = p.get("agg_rules", [])
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(r.get("col"), r.get("func"), r.get("rename"))

    def get_custom_params(self):
        g_keys = [k.strip() for k in self.group_keys.text().split(",") if k.strip()]
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c, f, r = (
                    w.findChild(QLineEdit, "col").text().strip(),
                    w.findChild(QComboBox, "func").currentText(),
                    w.findChild(QLineEdit, "rename").text().strip(),
                )
                if c:
                    rules.append({"col": c, "func": f, "rename": r})
        return {"group_key": g_keys, "agg_rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["group_key"]:
            return QMessageBox.warning(self, "错误", "缺少必要参数")
        col_dict = {}
        for r in p["agg_rules"]:
            c, f = r["col"], r["func"]
            if c in col_dict:
                (
                    col_dict[c].append(f)
                    if isinstance(col_dict[c], list)
                    else col_dict.update({c: [col_dict[c], f]})
                )
            else:
                col_dict[c] = f
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = group_calc(
                self.data_pool[p["df_name"]], p["group_key"], col_dict, p["col_type"]
            )
            rename_dict = {}
            for rule in p["agg_rules"]:
                if rule["rename"]:
                    actual_cols = normalize_columns(
                        self.data_pool[p["df_name"]], [rule["col"]], p["col_type"]
                    )
                    if actual_cols:
                        rename_dict[f"{actual_cols[0]}_{rule['func']}"] = rule["rename"]
            if rename_dict:
                df = df.rename(columns=rename_dict)
            self.step_recorded.emit("group_calc", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class JoinPanel(BaseToolPanel):
    use_df = False
    theme_color = "#4CAF50"
    action_name = "连接"

    def init_custom_ui(self):
        self.df1_combo = QComboBox()
        self.df2_combo = QComboBox()
        self.combo_boxes_to_update.extend([self.df1_combo, self.df2_combo])
        self.top_form.insertRow(0, "主表 (左):", self.df1_combo)
        self.top_form.insertRow(1, "匹配表 (右):", self.df2_combo)
        self.l_key = QLineEdit()
        self.r_key = QLineEdit()
        self.top_form.addRow("左表匹配键:", self.l_key)
        self.top_form.addRow("右表匹配键:", self.r_key)
        self.custom_layout.addWidget(QLabel("提取右表列及重命名:"))
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        self.custom_layout.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加提取列")
        btn_add.setStyleSheet("background-color: #EEEEEE; padding: 5px;")
        btn_add.clicked.connect(lambda: self.add_rule_row())
        self.custom_layout.addWidget(btn_add)
        hint = QLabel("提示: 类似于 VLOOKUP，提取右表的列放入左表。")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        self.custom_layout.addWidget(hint)

    def clear_custom_ui(self):
        self.l_key.clear()
        self.r_key.clear()
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", rename=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        c_input = QLineEdit(str(col))
        c_input.setObjectName("col")
        c_input.setPlaceholderText("右表列")
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("重命名(可选)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(c_input)
        l.addWidget(r_input)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def set_custom_params(self, p):
        if "df1_name" in p:
            self.df1_combo.setCurrentText(p["df1_name"])
        if "df2_name" in p:
            self.df2_combo.setCurrentText(p["df2_name"])
        if "l_key" in p:
            self.l_key.setText(p["l_key"])
        if "r_key" in p:
            self.r_key.setText(p["r_key"])
        get_cols, col_names = p.get("get_cols", []), p.get("col_names", [])
        if get_cols:
            self.clear_dynamic_layout(self.rules_layout)
            for i, c in enumerate(get_cols):
                r = col_names[i] if col_names and i < len(col_names) else ""
                self.add_rule_row(c, r)

    def get_custom_params(self):
        get_cols, col_names = [], []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c, r = (
                    w.findChild(QLineEdit, "col").text().strip(),
                    w.findChild(QLineEdit, "rename").text().strip(),
                )
                if c:
                    get_cols.append(c)
                    col_names.append(r)
        return {
            "df1_name": self.df1_combo.currentText(),
            "df2_name": self.df2_combo.currentText(),
            "l_key": self.l_key.text().strip(),
            "r_key": self.r_key.text().strip(),
            "get_cols": get_cols,
            "col_names": col_names,
        }

    def execute(self):
        p = self.get_params()
        if not p["df1_name"] or not p["df2_name"]:
            return QMessageBox.warning(self, "错误", "请选择表")
        if not p["get_cols"]:
            return QMessageBox.warning(self, "错误", "请配置提取列")
        out_name = p["out_name"] or f"{p['df1_name']}_{self.action_name}"
        try:
            actual_cols = normalize_columns(
                self.data_pool[p["df2_name"]], p["get_cols"], p["col_type"]
            )
            final_names = [
                p["col_names"][i] if p["col_names"][i] else actual_cols[i]
                for i in range(len(actual_cols))
            ]
            df = left_join(
                self.data_pool[p["df1_name"]],
                self.data_pool[p["df2_name"]],
                p["l_key"],
                p["r_key"],
                p["get_cols"],
                key_type=p["col_type"],
                col_names=final_names,
            )
            self.step_recorded.emit("left_join", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class RankPanel(BaseToolPanel):
    theme_color = "#2196F3"
    action_name = "排名"

    def init_custom_ui(self):
        self.custom_layout.addWidget(QLabel("排名配置:"))
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(6)
        self.custom_layout.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加排名规则")
        btn_add.setStyleSheet("background-color: #EEEEEE; padding: 5px;")
        btn_add.clicked.connect(lambda: self.add_rule_row())
        self.custom_layout.addWidget(btn_add)
        hint = QLabel(
            "说明: min(中国式1,2,2,4) | dense(密集1,2,2,3) | max(1,3,3,4) | average | first(顺延)。"
        )
        hint.setStyleSheet("color: #666; font-size: 11px;")
        self.custom_layout.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", method="min", asc=True, rename=""):
        container = QWidget()
        container.setStyleSheet(
            "background-color: #F8F9FA; border: 1px solid #E0E0E0; border-radius: 4px;"
        )
        v_layout = QVBoxLayout(container)
        v_layout.setContentsMargins(5, 5, 5, 5)
        v_layout.setSpacing(4)
        h1 = QHBoxLayout()
        h1.setContentsMargins(0, 0, 0, 0)
        c_input = QLineEdit(str(col))
        c_input.setObjectName("col")
        c_input.setPlaceholderText("要排名的列")
        r_input = QLineEdit(str(rename))
        r_input.setObjectName("rename")
        r_input.setPlaceholderText("新列名 (必填)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.setStyleSheet("border:none; color: red;")
        btn_rm.clicked.connect(container.deleteLater)
        h1.addWidget(c_input)
        h1.addWidget(QLabel("->"))
        h1.addWidget(r_input)
        h1.addWidget(btn_rm)
        h2 = QHBoxLayout()
        h2.setContentsMargins(0, 0, 0, 0)
        m_combo = QComboBox()
        m_combo.setObjectName("method")
        m_combo.addItems(["min", "dense", "max", "average", "first"])
        self._set_combo_by_prefix(m_combo, method.split(" ")[0])
        asc_combo = QComboBox()
        asc_combo.setObjectName("asc")
        asc_combo.addItems(["升序", "降序"])
        asc_combo.setCurrentIndex(0 if asc else 1)
        h2.addWidget(m_combo)
        h2.addWidget(asc_combo)
        v_layout.addLayout(h1)
        v_layout.addLayout(h2)
        self.rules_layout.addWidget(container)

    def set_custom_params(self, p):
        rules = p.get("rules", [])
        if not rules and "rank_cols" in p:
            for c in p.get("rank_cols", []):
                rules.append(
                    {
                        "col": c,
                        "method": "min",
                        "ascending": p.get("ascending", True),
                        "rename": "",
                    }
                )
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(
                    r.get("col"),
                    r.get("method", "min"),
                    r.get("ascending", True),
                    r.get("rename", ""),
                )

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c, r = (
                    w.findChild(QLineEdit, "col").text().strip(),
                    w.findChild(QLineEdit, "rename").text().strip(),
                )
                m, asc = (
                    w.findChild(QComboBox, "method").currentText(),
                    w.findChild(QComboBox, "asc").currentIndex() == 0,
                )
                if c:
                    rules.append({"col": c, "method": m, "ascending": asc, "rename": r})
        return {"rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["rules"]:
            return QMessageBox.warning(self, "错误", "参数不完整")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = self.data_pool[p["df_name"]].copy()
            for rule in p["rules"]:
                df = rank_col(
                    df,
                    [rule["col"]],
                    [rule["rename"]] if rule["rename"] else [],
                    col_type=p["col_type"],
                    method=rule["method"],
                    ascending=rule["ascending"],
                )
            self.step_recorded.emit("rank_col", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class SortPanel(BaseToolPanel):
    theme_color = "#FF9800"
    action_name = "排序"

    def init_custom_ui(self):
        self.custom_layout.addWidget(QLabel("排序规则 (从上到下优先级递减):"))
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        self.custom_layout.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加排序规则")
        btn_add.setStyleSheet("background-color: #EEEEEE; padding: 5px;")
        btn_add.clicked.connect(lambda: self.add_rule_row())
        self.custom_layout.addWidget(btn_add)
        hint = QLabel(
            "说明: 升序(从小到大), 降序(从大到小), 自定义(手写词典如: 高,中,低)。"
        )
        hint.setStyleSheet("color: #666; font-size: 11px;")
        self.custom_layout.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", asc=True, custom_order=None):
        if custom_order is None:
            custom_order = []
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 8)
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        c_input = QLineEdit(str(col))
        c_input.setObjectName("col")
        c_input.setPlaceholderText("排序列")
        asc_combo = QComboBox()
        asc_combo.setObjectName("asc")
        asc_combo.addItems(["升序", "降序", "自定义"])
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(container.deleteLater)
        h.addWidget(c_input)
        h.addWidget(asc_combo)
        h.addWidget(btn_rm)
        cus_input = QLineEdit(",".join(custom_order))
        cus_input.setObjectName("custom")
        cus_input.setPlaceholderText("例: 一级, 二级, 三级")
        cus_input.setStyleSheet(
            "background-color: #FFF8E1; border: 1px dashed #FFB300; padding: 2px 5px;"
        )
        if custom_order:
            asc_combo.setCurrentIndex(2)
            cus_input.setVisible(True)
        else:
            asc_combo.setCurrentIndex(0 if asc else 1)
            cus_input.setVisible(False)
        asc_combo.currentIndexChanged.connect(
            lambda idx, i=cus_input: i.setVisible(idx == 2)
        )
        v.addLayout(h)
        v.addWidget(cus_input)
        self.rules_layout.addWidget(container)

    def set_custom_params(self, p):
        rules = p.get("sort_rules", [])
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(
                    r.get("col"), r.get("ascending"), r.get("custom_order", [])
                )

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c = w.findChild(QLineEdit, "col").text().strip()
                asc_idx = w.findChild(QComboBox, "asc").currentIndex()
                cus_str = w.findChild(QLineEdit, "custom").text().strip()
                if c:
                    rules.append(
                        {
                            "col": c,
                            "ascending": True if asc_idx == 2 else asc_idx == 0,
                            "custom_order": (
                                [x.strip() for x in cus_str.split(",")]
                                if asc_idx == 2 and cus_str
                                else []
                            ),
                        }
                    )
        return {"sort_rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["sort_rules"]:
            return QMessageBox.warning(self, "错误", "参数缺失")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = sort_data(
                self.data_pool[p["df_name"]], p["sort_rules"], col_type=p["col_type"]
            )
            self.step_recorded.emit("sort_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class CalcPanel(BaseToolPanel):
    use_type = False
    theme_color = "#00BCD4"
    action_name = "计算"

    def init_custom_ui(self):
        self.custom_layout.addWidget(QLabel("多重计算公式:"))
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        self.custom_layout.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加新公式列")
        btn_add.setStyleSheet("background-color: #EEEEEE; padding: 5px;")
        btn_add.clicked.connect(lambda: self.add_rule_row())
        self.custom_layout.addWidget(btn_add)

        hint = QLabel(
            "强规范说明: 列名务必用中括号包裹。如: ([销售额] - [成本]) * 0.1"
        )
        hint.setStyleSheet("color: #E65100; font-size: 11px; font-weight: bold;")
        self.custom_layout.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, new_col="", formula=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        n_input = QLineEdit(str(new_col))
        n_input.setObjectName("new_col")
        n_input.setPlaceholderText("新列名")
        f_input = QLineEdit(str(formula))
        f_input.setObjectName("formula")
        f_input.setPlaceholderText("表达式 (如: [销售额]*0.1)")
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(n_input)
        l.addWidget(f_input)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def set_custom_params(self, p):
        rules = p.get("rules", [])
        if not rules and "new_col_name" in p:
            rules = [{"new_col_name": p["new_col_name"], "formula": p["formula"]}]
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(r.get("new_col_name"), r.get("formula"))

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                n, f = (
                    w.findChild(QLineEdit, "new_col").text().strip(),
                    w.findChild(QLineEdit, "formula").text().strip(),
                )
                if n and f:
                    rules.append({"new_col_name": n, "formula": f})
        return {"rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["rules"]:
            return QMessageBox.warning(self, "错误", "参数缺失")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = self.data_pool[p["df_name"]].copy()
            for rule in p["rules"]:
                df = calc_col(df, rule["new_col_name"], rule["formula"])
            self.step_recorded.emit("calc_col", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class CleanPanel(BaseToolPanel):
    theme_color = "#FF5722"
    action_name = "清洗"

    def init_custom_ui(self):
        self.custom_layout.addWidget(QLabel("清洗规则 (从上到下执行):"))
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(4)
        self.custom_layout.addLayout(self.rules_layout)
        self.add_rule_row()
        btn_add = QPushButton("+ 添加清洗规则")
        btn_add.setStyleSheet("background-color: #EEEEEE; padding: 5px;")
        btn_add.clicked.connect(lambda: self.add_rule_row())
        self.custom_layout.addWidget(btn_add)
        hint = QLabel(
            "说明: to_numeric(转数字), to_string(转文本), strip_space(去空格), fill_na(填空), drop_na(删空行)"
        )
        hint.setStyleSheet("color: #666; font-size: 11px;")
        hint.setWordWrap(True)
        self.custom_layout.addWidget(hint)

    def clear_custom_ui(self):
        self.clear_dynamic_layout(self.rules_layout)
        self.add_rule_row()

    def add_rule_row(self, col="", action="to_numeric", fill_val=""):
        row = QWidget()
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        c_input = QLineEdit(str(col))
        c_input.setObjectName("col")
        c_input.setPlaceholderText("清洗列")
        action_combo = QComboBox()
        action_combo.setObjectName("action")
        action_combo.addItems(
            ["to_numeric", "to_string", "strip_space", "fill_na", "drop_na"]
        )
        self._set_combo_by_prefix(action_combo, action)
        f_input = QLineEdit(str(fill_val))
        f_input.setObjectName("fill")
        f_input.setPlaceholderText("填充值...")
        f_input.setEnabled("fill_na" in action_combo.currentText())
        action_combo.currentTextChanged.connect(
            lambda t, i=f_input: i.setEnabled("fill_na" in t)
        )
        btn_rm = QPushButton("×")
        btn_rm.setFixedWidth(25)
        btn_rm.clicked.connect(row.deleteLater)
        l.addWidget(c_input)
        l.addWidget(action_combo)
        l.addWidget(f_input)
        l.addWidget(btn_rm)
        self.rules_layout.addWidget(row)

    def set_custom_params(self, p):
        rules = p.get("rules", [])
        if rules:
            self.clear_dynamic_layout(self.rules_layout)
            for r in rules:
                self.add_rule_row(r.get("cols"), r.get("action"), r.get("fill_value"))

    def get_custom_params(self):
        rules = []
        for i in range(self.rules_layout.count()):
            w = self.rules_layout.itemAt(i).widget()
            if w:
                c = w.findChild(QLineEdit, "col").text().strip()
                a = w.findChild(QComboBox, "action").currentText()
                f = w.findChild(QLineEdit, "fill").text().strip()
                if c:
                    rules.append({"cols": c, "action": a, "fill_value": f})
        return {"rules": rules}

    def execute(self):
        p = self.get_params()
        if not p["df_name"] or not p["rules"]:
            return QMessageBox.warning(self, "错误", "参数缺失")
        out_name = p["out_name"] or f"{p['df_name']}_{self.action_name}"
        try:
            df = clean_data(self.data_pool[p["df_name"]], p["rules"], p["col_type"])
            self.step_recorded.emit("clean_data", p, df, out_name)
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


class ExportNodePanel(BaseToolPanel):
    use_type = False
    use_out = False
    theme_color = "#607D8B"

    def init_custom_ui(self):
        self.fname_input = QLineEdit("Export_Result.xlsx")
        self.top_form.addRow("导出文件名:", self.fname_input)

        path_layout = QHBoxLayout()
        self.dir_input = QLineEdit()
        self.dir_input.setPlaceholderText("留空默认为程序运行目录")
        btn_browse = QPushButton("浏览目录")
        btn_browse.clicked.connect(self.browse_dir)
        path_layout.addWidget(self.dir_input)
        path_layout.addWidget(btn_browse)
        self.top_form.addRow("保存至目录:", path_layout)

        hint = QLabel(
            "逻辑说明:\n- 文件夹若不存在会自动创建。\n- 目录留空则保存至程序根目录。\n- 支持 .xlsx 和 .csv 格式扩展名。"
        )
        hint.setStyleSheet("color: #666; font-size: 11px;")
        self.custom_layout.addWidget(hint)

    def browse_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择保存目录", "")
        if folder:
            self.dir_input.setText(folder)

    def clear_custom_ui(self):
        self.fname_input.setText("Export_Result.xlsx")
        self.dir_input.clear()

    def set_custom_params(self, p):
        if "file_name" in p:
            self.fname_input.setText(p["file_name"])
        if "folder_path" in p:
            self.dir_input.setText(p["folder_path"])
        if "target_path" in p and not p.get("file_name"):
            full_path = p["target_path"]
            self.fname_input.setText(os.path.basename(full_path))
            self.dir_input.setText(os.path.dirname(full_path))

    def get_custom_params(self):
        return {
            "file_name": self.fname_input.text().strip(),
            "folder_path": self.dir_input.text().strip(),
            "out_name": "Export_Point",
        }

    def execute(self):
        p = self.get_params()
        if not p["df_name"]:
            return QMessageBox.warning(self, "错误", "未选择导出表")

        default_dir = (
            Path(sys.executable).parent
            if getattr(sys, "frozen", False)
            else Path(__file__).parent.absolute()
        )
        fname = p.get("file_name") or "Result.xlsx"
        fdir = p.get("folder_path", "").strip()

        if not fdir:
            target_path = str(default_dir / fname)
        else:
            target_path = str(Path(fdir) / fname)

        try:
            success, final_path = export_df(
                self.data_pool[p["df_name"]], target_path, default_dir
            )
            if success:
                QMessageBox.information(self, "成功", f"文件已保存至：\n{final_path}")
            else:
                QMessageBox.warning(
                    self, "路径重定向", f"由于权限或路径问题，已转存至：\n{final_path}"
                )
            self.step_recorded.emit(
                "export_df", p, self.data_pool[p["df_name"]], "导出记录"
            )
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))


NODE_REGISTRY = {
    "load_file": {
        "title": "数据源导入",
        "color": "#1976D2",
        "panel_class": LoadFilePanel,
    },
    "get_col_data": {
        "title": "提取列",
        "color": "#009688",
        "panel_class": ExtractPanel,
    },
    "filter_data": {
        "title": "数据筛选",
        "color": "#E91E63",
        "panel_class": FilterPanel,
    },
    "group_calc": {"title": "分组汇总", "color": "#673AB7", "panel_class": GroupPanel},
    "left_join": {"title": "表连接", "color": "#4CAF50", "panel_class": JoinPanel},
    "rank_col": {"title": "数据排名", "color": "#2196F3", "panel_class": RankPanel},
    "sort_data": {"title": "多级排序", "color": "#FF9800", "panel_class": SortPanel},
    "calc_col": {"title": "公式计算", "color": "#00BCD4", "panel_class": CalcPanel},
    "clean_data": {"title": "数据清洗", "color": "#FF5722", "panel_class": CleanPanel},
    "export_df": {
        "title": "自动导出",
        "color": "#607D8B",
        "panel_class": ExportNodePanel,
    },
}
