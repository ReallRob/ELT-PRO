"""算子注册表：面板注册、分类顺序、命名风格"""

from operators.panels.aggregate_panels import DescribePanel, GroupPanel, MeltPanel, PivotPanel
from operators.panels.calc_panels import CalcPanel, CumsumPanel, PctChangePanel, RankPanel
from operators.panels.io_panels import ExportNodePanel, LoadFilePanel
from operators.panels.table_panels import ConcatPanel, JoinPanel
from operators.panels.template_panels import ImportTemplatePanel, InsertBlockPanel
from operators.panels.transform_panels import (
    CleanPanel,
    DedupPanel,
    ExtractPanel,
    FilterPanel,
    SamplePanel,
    SortPanel,
    TransposePanel,
)
from operators.panels.advanced_param_mapping import AdvancedParamMappingPanel

NODE_REGISTRY = {
    "advanced_param_mapping": {"title": "参数高级映射", "color": "#455A64", "panel_class": AdvancedParamMappingPanel, "category": "参数控制"},
    "load_file":       {"title": "数据源导入", "color": "#1976D2", "panel_class": LoadFilePanel,       "category": "输入输出"},
    "export_df":       {"title": "自动导出",   "color": "#607D8B", "panel_class": ExportNodePanel,      "category": "输入输出"},
    "get_col_data":    {"title": "提取列",     "color": "#009688", "panel_class": ExtractPanel,         "category": "数据变换"},
    "filter_data":     {"title": "数据筛选",   "color": "#E91E63", "panel_class": FilterPanel,          "category": "数据变换"},
    "sort_data":       {"title": "多级排序",   "color": "#FF9800", "panel_class": SortPanel,            "category": "数据变换"},
    "clean_data":      {"title": "数据清洗",   "color": "#FF5722", "panel_class": CleanPanel,           "category": "数据变换"},
    "drop_duplicates": {"title": "去重",       "color": "#EF5350", "panel_class": DedupPanel,           "category": "数据变换"},
    "sample_data":     {"title": "抽样",       "color": "#78909C", "panel_class": SamplePanel,          "category": "数据变换"},
    "transpose_data":  {"title": "转置",       "color": "#9E9E9E", "panel_class": TransposePanel,       "category": "数据变换"},
    "group_calc":      {"title": "分组汇总",   "color": "#673AB7", "panel_class": GroupPanel,           "category": "汇总统计"},
    "pivot_table":     {"title": "数据透视",   "color": "#8E24AA", "panel_class": PivotPanel,           "category": "汇总统计"},
    "melt_table":      {"title": "逆透视",     "color": "#26A69A", "panel_class": MeltPanel,            "category": "汇总统计"},
    "describe_data":   {"title": "描述统计",   "color": "#3F51B5", "panel_class": DescribePanel,        "category": "汇总统计"},
    "left_join":       {"title": "表连接",     "color": "#4CAF50", "panel_class": JoinPanel,            "category": "表操作"},
    "concat_rows":     {"title": "纵向拼接",   "color": "#5C6BC0", "panel_class": ConcatPanel,          "category": "表操作"},
    "rank_col":        {"title": "数据排名",   "color": "#2196F3", "panel_class": RankPanel,            "category": "计算列"},
    "calc_col":        {"title": "公式计算",   "color": "#00BCD4", "panel_class": CalcPanel,            "category": "计算列"},
    "cumsum_data":     {"title": "累加计算",   "color": "#00897B", "panel_class": CumsumPanel,          "category": "计算列"},
    "pct_change_data": {"title": "环比计算",   "color": "#F4511E", "panel_class": PctChangePanel,       "category": "计算列"},
    "import_template": {"title": "导入模板",   "color": "#795548", "panel_class": ImportTemplatePanel,  "category": "实验功能"},
    "insert_block":    {"title": "插入模板",   "color": "#FF6F00", "panel_class": InsertBlockPanel,     "category": "实验功能"},
}

CATEGORY_ORDER = ["参数控制", "输入输出", "数据变换", "汇总统计", "表操作", "计算列", "实验功能"]

OPERATOR_NAME_STYLES = {
    "默认": {},
    "Excel 风格": {
        "load_file": "导入数据",
        "get_col_data": "选择列",
        "filter_data": "条件筛选",
        "sort_data": "排序",
        "clean_data": "数据清洗",
        "drop_duplicates": "删除重复项",
        "sample_data": "随机抽样",
        "transpose_data": "转置",
        "group_calc": "分类汇总",
        "pivot_table": "数据透视表",
        "melt_table": "逆透视",
        "describe_data": "描述统计",
        "left_join": "VLOOKUP 连接",
        "concat_rows": "追加合并",
        "rank_col": "排名",
        "calc_col": "公式列",
        "cumsum_data": "累计求和",
        "pct_change_data": "环比增长",
        "export_df": "导出文件",
        "import_template": "导入模板",
        "insert_block": "填充模板",
    },
    "WPS 风格": {
        "load_file": "导入数据表",
        "get_col_data": "提取列数据",
        "filter_data": "高级筛选",
        "sort_data": "自定义排序",
        "clean_data": "智能清洗",
        "drop_duplicates": "去重处理",
        "sample_data": "抽样调查",
        "transpose_data": "行列互换",
        "group_calc": "汇总统计",
        "pivot_table": "交叉分析",
        "melt_table": "数据展开",
        "describe_data": "统计描述",
        "left_join": "智能匹配",
        "concat_rows": "合并表格",
        "rank_col": "排名计算",
        "calc_col": "计算字段",
        "cumsum_data": "滚动汇总",
        "pct_change_data": "同比环比",
        "export_df": "输出文件",
        "import_template": "加载模板",
        "insert_block": "写入模板",
    },
}


def get_operator_title(action, style="默认", custom_names=None):
    """根据风格返回算子显示名称"""
    if custom_names and action in custom_names:
        return custom_names[action]
    style_names = OPERATOR_NAME_STYLES.get(style, {})
    if action in style_names and style_names[action]:
        return style_names[action]
    return NODE_REGISTRY.get(action, {}).get("title", action)
