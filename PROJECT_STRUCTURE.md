# 项目文件结构说明

本文档用于说明当前工程的文件职责、已完成的重构边界，以及后续建议的演进方向。

## 当前结构

```text
文档处理助手/
├── main.py                         # 应用入口，装配设计模式和执行模式主界面
├── engine.py                       # 工作流线程、参数解析、内存池生命周期和 handler 调度
├── workspace_context.py            # 设计态上下文，管理内存表、工作流配置和全量执行
├── operator_registry.py            # 算子注册表，决定工具箱/右键菜单可用算子和配置面板
├── node_editor.py                  # 设计态画布节点、连线和连线规则
├── template_engine.py              # Excel 模板导入、块写入、模板保存逻辑
├── parameter_resolver.py           # 运行参数、占位符、高级映射规则解析
├── parameter_input.py              # 支持 ${参数} 高亮和插入菜单的输入框组件
├── table_model.py                  # pandas DataFrame 到 Qt 表格模型的适配
├── utils.py                        # 画布连线、网格、布局等通用图形工具
├── core/
│   ├── app_paths.py               # 程序运行目录等路径工具，供 UI 和执行引擎复用
│   ├── dataframe_ops/
│   │   ├── columns.py              # 列名/列序号/Excel 字母列统一解析
│   │   ├── dates.py                # 日期值和日期列统一解析，减少 pandas 推断警告
│   │   ├── select.py               # 选列、提取列、排序算子
│   │   ├── filter.py               # 类型感知筛选算子
│   │   ├── clean.py                # 清洗、去重、抽样算子
│   │   ├── aggregate.py            # 分组、透视、逆透视、描述统计算子
│   │   ├── table.py                # 表连接、纵向拼接、转置算子
│   │   ├── calc.py                 # 排名、公式列、累加、环比算子
│   │   └── io.py                   # 数据源读取、列范围下推和 DataFrame 导出算子
│   ├── parameters/
│   │   └── mapping_schema.py       # 参数高级映射 schema 构造与强类型转换
│   └── workflow/
│       └── action_handlers.py      # action handler 注册表、依赖提取和算子执行函数
├── ui/
│   ├── design/
│   │   ├── design_mode.py          # 设计模式主入口，负责初始化状态并装配 UI/mixin
│   │   ├── app_state.py            # 设计态配置路径、工作区状态读写和恢复
│   │   ├── canvas_actions.py       # 创建、删除、清空节点和自动排版
│   │   ├── config_pages.py         # 右侧配置面板空状态页
│   │   ├── context_menu.py         # 设计态画布右键菜单
│   │   ├── dock_controls.py        # Dock 显示、浮动标题栏和置顶控制
│   │   ├── import_export_ui.py     # 工作流导入/导出文件选择、路径修复和提示
│   │   ├── layout_builder.py       # Dock、画布、预览区和右侧配置区装配
│   │   ├── node_config.py          # 节点配置面板切换、草稿保存和参数同步
│   │   ├── preview_panel.py        # 设计态数据预览、自动跟随和预览标签
│   │   ├── run_controls.py         # 设计态全量执行进度和完成回调
│   │   ├── settings_dialog.py      # 算子显示、右键菜单和命名风格设置
│   │   ├── status_bar.py           # 设计态底部状态栏构建和统计刷新
│   │   ├── toolbar.py              # 设计态顶部工具栏构建
│   │   ├── toolbox.py              # 工具箱与可折叠算子分类
│   │   └── workflow_io.py          # 工作流 JSON 读写、缺失文件检查和画布还原
│   ├── execute/
│   │   ├── execute_mode.py         # 执行模式主入口，负责初始化状态并装配 UI/mixin
│   │   ├── layout_builder.py       # 执行态信息栏、流程图、预览区、日志区和底部状态栏
│   │   ├── logging_panel.py        # 执行日志渲染和颜色分级
│   │   ├── preview_panel.py        # 结果表预览与单表导出
│   │   ├── run_controls.py         # 执行引擎启动、按钮状态、完成/失败回调
│   │   ├── styles.py               # 执行态按钮和工具栏共享样式
│   │   ├── toolbar.py              # 执行态顶部工具栏构建
│   │   ├── workflow_file.py        # 工作流 JSON 加载、数据源映射和执行态状态恢复
│   │   └── workflow_graph.py       # 执行态工作流监控图、节点状态和右键导出入口
│   └── dialogs/
│       ├── data_source_mapping.py  # 执行态数据源路径重映射弹窗
│       └── path_remap.py           # 设计态导入模板时的缺失路径重映射弹窗
├── operators/
│   ├── base_panel.py               # BaseToolPanel 及参数输入别名
│   └── panels/
│       ├── advanced_param_mapping.py # 参数输入 UI 面板与分支规则弹窗
│       ├── aggregate_panels.py       # 分组、透视、逆透视、描述统计面板
│       ├── calc_panels.py            # 排名、计算列、累加、环比面板
│       ├── io_panels.py              # 导入/导出面板
│       ├── table_panels.py           # 表连接、纵向拼接面板
│       ├── template_panels.py        # 模板导入、模板写入面板
│       └── transform_panels.py       # 提取、筛选、排序、清洗、去重、抽样、转置面板
├── config/
│   └── workspace_config.json       # UI 状态、最近工作流、执行模式状态
├── my_workflow.json                # 示例/当前工作流文件
└── README.md                       # 项目简介
```

## 已完成的重构

1. 参数算子合并
   - 旧的「输入参数」和「参数映射」可见算子已从注册/UI 中移除。
   - `advanced_param_mapping` 是唯一的参数输入算子。
   - 研发期不保留旧参数工作流兼容路径，结构问题直接暴露。

2. 参数高级映射结构升级
   - 输入参数和映射规则被整合为一个算子。
   - 一个映射组内可以有多条 case 分支，表达类似 `if / elif / else` 或 `switch` 的规则。
   - 公共配置放在组级别：`matchMode`、`outputType`、`mappingStrategy`、`evaluationStrategy`。
   - 分支只保留业务名、源匹配值和目标值，避免每行重复配置。

3. 算子面板拆分
   - `BaseToolPanel` 迁移到 `operators/base_panel.py`。
   - 普通算子面板按业务域拆到 `operators/panels/`。
   - 参数映射 schema 生成逻辑放到 `core/parameters/mapping_schema.py`。

4. 设计模式 UI 拆分
   - `ui/design/design_mode.py` 只负责状态初始化和模块装配。
   - 工具栏、Dock 布局、右侧配置区、预览、运行控制、节点配置、导入导出、右键菜单等已拆为独立模块。

5. 执行模式 UI 拆分
   - `ui/execute/execute_mode.py` 只负责执行态状态初始化和模块装配。
   - 工具栏、主布局、日志、结果预览、引擎运行、工作流文件加载和数据源映射已拆为独立模块。

6. 执行引擎分发拆分
   - `engine.py` 不再维护长 `if / elif` 算子执行分支。
   - 具体 action 通过 `core/workflow/action_handlers.py` 的 `ACTION_HANDLERS` 注册表调度。
   - 引擎统一负责引用计数、输出发布、去重映射和中间表释放。

7. DataFrame 操作拆分
   - 旧的 `xlsx_fun.py` 兼容导出层已移除。
   - 真实算子实现按领域迁移到 `core/dataframe_ops/`。
   - 日期解析集中到 `core/dataframe_ops/dates.py`，优先按明确格式解析，减少 pandas 日期推断警告。

8. 历史包袱清理
   - 项目主入口已直接导入 `ui.design.design_mode` 和 `ui.execute.execute_mode`。
   - 引擎 handler 和算子面板已直接导入 `core.dataframe_ops`。
   - `ui_components.py`、`ui_design.py`、`ui_execute.py` 和 `xlsx_fun.py` 均已删除。
   - 旧参数算子、旧模板导出节点和旧字段兜底已移除。

## 当前职责边界

### 核心执行层
- `engine.py` 负责工作流线程、参数解析、内存池生命周期和 handler 调度。
- `core/workflow/action_handlers.py` 负责 action handler 注册、依赖提取和具体算子执行。
- `core/dataframe_ops/*` 提供具体 DataFrame 数据处理函数。
- `template_engine.py` 提供模板写入能力。
- `parameter_resolver.py` 负责运行时参数、占位符和映射解析。
- `core/parameters/mapping_schema.py` 负责高级参数映射配置生成。

### UI 设计层
- `ui/design/*` 负责设计态界面、画布、算子配置、预览和模板导入导出。
- `node_editor.py` 专注画布节点与连线。
- `operators/base_panel.py` 提供面板公共 UI 框架。
- `operators/panels/*` 提供具体算子配置面板。

### UI 执行层
- `ui/execute/*` 负责工作流加载、数据源重映射、执行、日志、流程图状态和结果预览。
- `ui/dialogs/data_source_mapping.py` 管理数据源路径重映射。
- `ui/dialogs/path_remap.py` 管理设计态导入模板时的缺失文件重映射。

### 参数/规则层
- `parameter_resolver.py` 是运行期解析内核。
- `parameter_input.py` 是支持参数引用的输入控件。
- `core/parameters/mapping_schema.py` 是规则配置生成器。
- `operators/panels/advanced_param_mapping.py` 只负责参数输入 UI 采集和预览展示。

## 后续建议

当前没有保留顶层兼容入口。后续新增数据处理能力时，直接放入 `core/dataframe_ops/` 并通过 `core.dataframe_ops.__init__` 暴露公共函数。

## 注释约定

1. 注释解释“为什么这样做”，避免解释显而易见的语句。
2. 强类型转换、规则引擎 schema、UI 与运行时桥接处必须加短注释。
3. 复杂函数开头写简短 docstring，说明输入、输出和关键约束。
4. 面板类建议按区域分段：UI 构建、数据收集、配置生成、执行预览。
5. 方案变化后删除过期注释，避免文档和代码互相误导。

## 当前约定

- 新算子面板放入 `operators/panels/`。
- 面板公共能力放入 `operators/base_panel.py`。
- 非 UI 的参数/规则逻辑放入 `core/parameters/`。
- 顶层不再保留 UI 兼容入口；UI 代码直接从 `ui/design/`、`ui/execute/`、`ui/dialogs/` 导入。
- 每次迁移后至少运行一次 `py_compile` 和一次基础 UI 实例化验证。
