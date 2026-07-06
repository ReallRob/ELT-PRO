# 项目文件结构说明

本文档用于说明当前工程的文件职责、已完成的重构边界，以及后续建议的演进方向。项目仍处于研发阶段，当前文档以最新代码结构为准，不再描述旧兼容入口。

## 当前结构

```text
文档处理助手/
├── main.py                         # 应用入口，装配设计模式和执行模式主界面
├── engine.py                       # 工作流执行线程，负责参数解析、运行存储、输出发布和内存释放
├── workspace_context.py            # 设计态上下文，管理画布运行、节点输出、预览数据和工作流构建
├── operator_registry.py            # 算子注册表，决定工具箱/右键菜单算子、分类和配置面板
├── node_editor.py                  # 设计态画布节点、连线、节点显示和连线规则
├── template_engine.py              # Excel 模板加载、预览、单元格编辑、区域插入、匹配填充和保存
├── parameter_resolver.py           # 运行参数、占位符、高级映射规则解析
├── parameter_input.py              # 支持 ${参数} 高亮和插入菜单的输入框组件
├── table_model.py                  # pandas DataFrame 到 Qt 表格模型的适配
├── utils.py                        # 画布连线、网格、布局等通用图形工具
├── core/
│   ├── app_paths.py                # 程序运行目录等路径工具
│   ├── manifest_builder.py         # 从工作流 JSON 生成/补全 CRPA run_manifest 和 file_resources
│   ├── qt_wheel_guard.py           # Qt 下拉框滚轮误触保护
│   ├── dataframe_ops/
│   │   ├── __init__.py             # 对外暴露 DataFrame 算子函数
│   │   ├── columns.py              # 列名/列序号/Excel 字母列统一解析
│   │   ├── dates.py                # 日期值和日期列统一解析
│   │   ├── select.py               # 选列、提取列、排序算子
│   │   ├── filter.py               # 类型感知筛选算子
│   │   ├── clean.py                # 清洗、去重、抽样算子
│   │   ├── aggregate.py            # 分组、透视、逆透视、描述统计算子
│   │   ├── table.py                # 表连接、纵向拼接、转置算子
│   │   ├── calc.py                 # 排名、公式列、累加、环比算子
│   │   ├── code_exec.py            # 用户代码执行沙箱、子进程和超时控制
│   │   ├── code_block.py           # 多表代码块算子运行封装
│   │   └── io.py                   # 数据源读取、列范围下推和 DataFrame 导出算子
│   ├── parameters/
│   │   └── mapping_schema.py       # 参数高级映射 schema 构造与强类型转换
│   └── workflow/
│       ├── operator_model.py       # 显式输入/输出模型、BaseOperator、BatchMap/Binary/Source 基类
│       ├── operators.py            # 具体算子类注册和运行实现
│       ├── runtime_store.py        # 运行时数据存储，按 (node_id, output_id) 保存真实输出
│       └── schema.py               # 工作流 JSON inputs/outputs 规范化、默认输出名和显示名
├── ui/
│   ├── design/
│   │   ├── design_mode.py          # 设计模式主入口，负责初始化状态并装配 UI/mixin
│   │   ├── app_state.py            # 设计态配置路径、工作区状态读写和恢复
│   │   ├── canvas_actions.py       # 创建、删除、清空节点和自动排版
│   │   ├── config_pages.py         # 右侧配置面板空状态页
│   │   ├── context_menu.py         # 设计态画布右键菜单
│   │   ├── dock_controls.py        # Dock 显示、浮动标题栏和置顶控制
│   │   ├── import_export_ui.py     # 工作流导入/导出文件选择、路径修复和提示
│   │   ├── layout_builder.py       # 左工具箱、中画布、右配置、底预览布局装配
│   │   ├── node_config.py          # 节点配置面板切换、草稿保存、运行/保存按钮桥接
│   │   ├── preview_panel.py        # 设计态数据预览、模板预览、自动跟随和预览标签
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
│   │   ├── preview_panel.py        # 结果表/模板预览与单表导出
│   │   ├── run_controls.py         # 执行引擎启动、按钮状态、完成/失败回调
│   │   ├── styles.py               # 执行态按钮和工具栏共享样式
│   │   ├── toolbar.py              # 执行态顶部工具栏构建
│   │   ├── workflow_file.py        # 工作流 JSON 加载、数据源映射和执行态状态恢复
│   │   └── workflow_graph.py       # 执行态工作流监控图、节点状态和右键导出入口
│   └── dialogs/
│       ├── data_source_mapping.py  # 执行态数据源路径重映射弹窗
│       └── path_remap.py           # 设计态导入模板时的缺失路径重映射弹窗
├── operators/
│   ├── base_panel.py               # BaseToolPanel，公共配置、参数引用、列下拉、运行/保存按钮
│   └── panels/
│       ├── advanced_param_mapping.py # 参数输入 UI 面板与映射规则配置
│       ├── aggregate_panels.py       # 分组、透视、逆透视、描述统计旧/专用面板
│       ├── calc_panels.py            # 排名、公式计算、累加、环比面板
│       ├── code_block_panel.py       # 多输入代码块面板
│       ├── flow_panels.py            # 新显式输入/输出批量面板，筛选/清洗/排序/分组样板
│       ├── io_panels.py              # 导入/导出面板
│       ├── table_panels.py           # 表连接、纵向拼接面板
│       ├── template_panels.py        # 导入模板、插入模板、单元格编辑和匹配填充面板
│       └── transform_panels.py       # 提取、筛选、排序、清洗、去重、抽样、转置旧/专用面板
├── crpa_launcher/
│   ├── main.py                     # 独立 CRPA JSON 运行器入口
│   ├── app.py                      # 运行器界面，根据 run_manifest 生成文件选择和参数输入
│   ├── manifest_runtime.py         # 从 run_manifest 读取资源、工作表、参数并执行工作流
│   └── settings.py                 # 运行器本地状态与配置
├── config/
│   ├── workspace_config.json       # 主程序 UI 状态、最近工作流、执行模式状态，本地配置不应提交
│   └── crpa_launcher_config.json   # CRPA JSON 运行器本地状态，本地配置不应提交
├── README.md                       # 项目简介、运行方式和业务功能说明
└── PROJECT_STRUCTURE.md            # 当前项目结构说明
```

## 当前执行模型

1. 工作流 JSON 中每个节点使用显式 `inputs` 和 `outputs`。
2. 输入引用使用 `source_node_id + source_output_id`，不再依赖表名猜测。
3. 运行时真实数据由 `WorkflowRuntimeStore` 按 `(node_id, output_id)` 保存。
4. 算子二次运行会先清除本节点旧输出，并清理下游旧输出，但不会清除节点配置参数。
5. `engine.py` 负责调度、日志、参数解析、输出发布和中间结果释放；具体业务逻辑放在 `core/workflow/operators.py` 和 `core/dataframe_ops/`。
6. 多输出算子通过 `BatchMapOperator` 或等价面板结构实现，输入和输出一一对应。

## 已完成的重构

1. 显式输入/输出模型
   - 新增 `core/workflow/operator_model.py`、`operators.py`、`runtime_store.py`、`schema.py`。
   - 旧的 `core/workflow/action_handlers.py` 已删除。
   - 工作流运行不再通过长 `if / elif` handler 分支，而是通过算子类注册表创建和运行算子。

2. 多输入批量算子面板
   - `operators/panels/flow_panels.py` 提供 `BatchMapFlowPanel`。
   - 筛选、清洗、排序、分组已具备按多个输入生成多个输出的结构基础。
   - 操作命名只用于描述节点用途，不再被当成表名。

3. 设计态布局统一
   - 主界面采用左工具箱 + 中央画布 + 右配置 + 底部预览。
   - 配置面板切换时会保存当前节点草稿，避免点击空白或切换节点时丢配置。
   - 下拉框列名刷新优先保留旧值，减少上游未运行时配置被清空的问题。

4. 参数算子合并
   - 旧的「输入参数」和「参数映射」可见算子已从注册/UI 中移除。
   - `advanced_param_mapping` 是唯一的参数输入算子。
   - 输入参数和映射规则整合在一个面板中，运行时由 `parameter_resolver.py` 解析。

5. DataFrame 操作拆分
   - 真实算子实现按领域迁移到 `core/dataframe_ops/`。
   - 日期解析集中到 `dates.py`，列解析集中到 `columns.py`。
   - 用户代码执行拆到 `code_exec.py`，支持子进程和超时控制。

6. 模板能力升级
   - 模板读写统一使用 openpyxl。
   - `template_engine.py` 支持模板结构预览、单元格编辑、区域插入、匹配填充和保存完整 xlsx。
   - 插入模板现在支持两种模式：区域插入、匹配填充。
   - 匹配填充支持指定表头行、自动查找表头、手动指定模板列。
   - 匹配键必填，写入映射可手动配置，也可按模板表头和 DataFrame 同名字段自动写入。

7. CRPA 运行器
   - `core/manifest_builder.py` 负责把工作流需要的文件、参数和 CRPA 元信息整理成 `run_manifest`。
   - `crpa_launcher/` 是独立运行器目录，与主程序隔离。
   - 运行器面向业务人员，只展示 JSON 导入、文件选择、必要参数输入和运行结果。

8. 历史包袱清理
   - 项目主入口直接导入 `ui.design.design_mode` 和 `ui.execute.execute_mode`。
   - `ui_components.py`、`ui_design.py`、`ui_execute.py`、`xlsx_fun.py` 等顶层兼容入口已移除。
   - 研发期不保留旧 JSON/旧算子兼容路径，结构问题直接暴露并修正。

## 当前职责边界

### 核心执行层
- `engine.py`：线程、参数解析、文件路径映射、运行存储、日志、输出发布和中间结果释放。
- `core/workflow/operator_model.py`：算子基类、输入输出数据结构和运行上下文抽象。
- `core/workflow/operators.py`：具体算子类实现和注册表。
- `core/workflow/runtime_store.py`：真实运行数据和输出元信息存储。
- `core/workflow/schema.py`：工作流 JSON 输入/输出规范化。
- `core/dataframe_ops/*`：具体 DataFrame 数据处理函数。

### 模板层
- `template_engine.py`：只负责 openpyxl workbook 的加载、预览、写入和保存。
- `InsertBlockOperator`：把 DataFrame 和写入配置打包成 `template_insert` payload。
- `ImportTemplateOperator`：加载模板 workbook，按接入顺序应用多个 `template_insert` payload，最后输出完整 xlsx。
- 模板写入不继承上一行样式，默认保留模板目标区域已有格式。

### UI 设计层
- `ui/design/*`：设计态界面、画布、工具箱、右配置、底预览、导入导出和全量执行。
- `node_editor.py`：画布节点与连线。
- `operators/base_panel.py`：配置面板公共能力。
- `operators/panels/*`：具体算子配置面板。

### UI 执行层
- `ui/execute/*`：工作流加载、路径重映射、执行控制、日志、流程图状态和结果预览。
- `ui/dialogs/data_source_mapping.py`：执行态数据源路径重映射。
- `ui/dialogs/path_remap.py`：设计态导入模板时的缺失文件重映射。

### 参数/规则层
- `parameter_resolver.py`：运行期参数、占位符和映射解析内核。
- `parameter_input.py`：支持参数引用的输入控件。
- `core/parameters/mapping_schema.py`：高级参数映射配置生成器。
- `operators/panels/advanced_param_mapping.py`：参数输入和映射规则 UI。

### CRPA 运行层
- `core/manifest_builder.py`：构建 JSON 中的 `crpa`、`run_manifest`、`file_resources`。
- `crpa_launcher/manifest_runtime.py`：读取 manifest，生成运行所需资源。
- `crpa_launcher/app.py`：面向业务人员的轻量运行界面。

## JSON 结构约定

工作流 JSON 顶层建议包含：

```json
{
  "workflow_name": "示例流程",
  "crpa": {
    "code": "9999",
    "name": "代号名称"
  },
  "runtime_parameters": {},
  "parameter_mappings": {},
  "run_manifest": {
    "file_resources": [],
    "data_sources": [],
    "parameters": []
  },
  "steps": []
}
```

每个步骤的 `params.inputs` / `params.outputs` 是当前数据流的核心结构。不要再通过操作名、表名或 UI 显示名推断真实数据来源。

## 模板写入约定

### 区域插入
- 配置目标工作表、起始行、起始列、可选结束行/结束列。
- 可选择是否写入表头。
- 按矩形区域顺序写入 DataFrame。

### 匹配填充
- 模板是 openpyxl workbook，数据是 pandas DataFrame。
- 匹配键必填：`模板字段/模板列 ← df字段`。
- 写入映射可选：
  - 有模板表头时，留空表示按同名字段自动写入。
  - 手动指定列模式下必须填写写入映射。
- 模板表头可以在任意行：指定表头行、自动查找表头或手动指定列。
- DataFrame 列顺序和模板列顺序可以不同，写入只按字段/列映射定位。

## 后续建议

1. 继续把旧/专用面板迁移到显式 inputs/outputs 面板基座。
2. 双输入算子继续补端口角色，避免左右表依赖连线顺序。
3. 模板算子后续可以继续拆成：单元格编辑、区域插入、匹配填充、模板清空策略。
4. 大数据场景继续减少无意义 DataFrame copy，并对代码块输入规模给出 UI 提示。
5. 工作流 JSON 后续应增加明确版本号和 schema 校验/迁移层。

## 注释约定

1. 注释解释“为什么这样做”，避免解释显而易见的语句。
2. 强类型转换、规则引擎 schema、UI 与运行时桥接处必须加短注释。
3. 复杂函数开头写简短 docstring，说明输入、输出和关键约束。
4. 面板类建议按区域分段：UI 构建、数据收集、配置生成、执行预览。
5. 方案变化后删除过期注释，避免文档和代码互相误导。

## 当前约定

- 新算子业务逻辑优先放入 `core/dataframe_ops/` 或 `core/workflow/operators.py`。
- 新算子面板放入 `operators/panels/`。
- 面板公共能力放入 `operators/base_panel.py`。
- 非 UI 的参数/规则逻辑放入 `core/parameters/`。
- 顶层不再保留 UI 兼容入口；UI 代码直接从 `ui/design/`、`ui/execute/`、`ui/dialogs/` 导入。
- 本地配置、临时 JSON、导出结果和运行产物不应提交。
- 每次结构迁移后至少运行一次 `py_compile` 和一次基础功能验证。
