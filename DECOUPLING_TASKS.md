# 解耦任务记录

本文档记录当前工作流参数模型和架构解耦的完成情况。

## 已完成

### 旧参数兼容收口

- 已新增旧 JSON 迁移入口 `migrate_workflow_config()`。
- 旧字段会在加载时迁移为标准 `inputs/outputs`：
  - `df_name`
  - `out_name`
  - `df1_name`
  - `df2_name`
  - `template_name`
  - `df_id`
  - `df1_id`
  - `df2_id`
  - `template_id`
  - `input_bindings`
- 旧字段兼容保留在 `core/workflow/schema.py`，不再作为 UI 和执行层的常规参数流转。
- 已修复迁移时误删 step 顶层 `action` 的问题。
- 已避免对纯新格式 JSON 反复重算 `inputs/outputs`。

### 加载和保存入口迁移

- 设计模式加载工作流时会自动迁移旧 JSON。
- 设计模式保存工作流前会先迁移，落盘为新参数结构。
- 执行模式加载工作流时会自动迁移旧 JSON。
- CRPA launcher 加载和保存工作流时会自动迁移旧 JSON。

### UI 面板旧参数移除

- `node_config._panel_params_for_node()` 不再向面板注入 `df_name/out_name/df1_name/df2_name/template_name`。
- `BaseToolPanel` 已改为从 `inputs/outputs` 恢复输入和输出名称。
- `BaseToolPanel` 保存时不再写 `df_name/out_name`，而是生成新结构。
- `JoinPanel` 和 `ConcatPanel` 已改为从 `inputs[].role == left/right` 恢复输入。
- `JoinPanel` 和 `ConcatPanel` 保存时不再依赖 `df1_name/df2_name`。
- 面板恢复输入时保留 `source_node_id/source_output_id`，降低同名输出恢复错位风险。

### IO 生成职责收口到 schema

- 已新增 `io_prefs` 轻量 IO 偏好模型，面板保存用户意图，schema 生成正式 `inputs/outputs`。
- `core/workflow/schema.py` 已统一支持从以下偏好生成标准 IO：
  - 单输入选择 `selected_input`
  - 多输入启用状态 `inputs[].enabled`
  - 双输入角色 `inputs[].role`
  - 输出显示名称 `output_name` / `outputs[].name`
  - 代码块 alias、worksheet alias 和工作表选择
- 以下配置面板已停止直接保存正式 `inputs/outputs`：
  - `BaseToolPanel` 单输入面板
  - `LoadFilePanel`
  - `JoinPanel` / `ConcatPanel`
  - `BatchMapFlowPanel` 系列批量多输入面板
  - `CodeBlockPanel`
  - `ImportTemplatePanel` / `InsertBlockPanel` / `SaveTemplatePanel`
- schema 仍会在保存、运行和旧 JSON 迁移时生成标准 `inputs/outputs`，执行层无需理解 `io_prefs`。
- 已限制批量 DataFrame 算子只自动接入 table 类型，避免 workbook 被误当作 DataFrame 输入。
- `insert_block` 已固定为模板主线写入算子：必须同时接入一个 workbook 和一个 table，输出仍是同一个 workbook。
- `import_template` 已固定为模板主线源头：只加载模板文件，不接收上游输入。
- `save_template` 已作为模板主线终点：接入 workbook 并保存到 xlsx。
- 代码块会过滤为 table/workbook 输入，可只处理 DataFrame，也可接入 workbook 后原地修改模板主线。
- 加载模板预览在未指定工作表时会加载全部 sheet；指定工作表时只预览该 sheet。

### 验证

- 已运行语法检查：`python -m py_compile` 通过。
- 已用旧格式 JSON 验证迁移后无旧字段残留。
- 已用新格式 JSON 验证迁移不会破坏现有 `inputs/outputs`。
- 当前扫描中剩余的 `df_name/out_name` 多为局部变量名，或旧 JSON 迁移层中的兼容字段。
- 已验证 `io_prefs` 能生成导入、单输入、双输入、批量、代码块和模板类节点的标准 `inputs/outputs`。
- 已扫描配置面板，不再发现 `params["inputs"]` / `params["outputs"]` 的正式 IO 直写。
- 已验证面板保存的 `io_prefs` 不包含 `input_id/output_id/from_input_id` 等正式执行协议字段。
- 已验证模板主线端到端流程：`加载模板 -> 写入模板 -> 写入模板 -> 保存模板` 保持同一个 workbook entry 引用，保存文件包含两次写入结果。
- 已验证代码块模板流程：`加载模板 -> 代码块修改 wb -> 保存模板` 保持同一个 workbook entry 引用，保存文件包含代码块写入结果。
- 已验证 `python -m py_compile` 覆盖 schema、执行层、模板面板、预览、manifest、设计态和执行态入口。

## 待完成

### 高优先级

- 继续把 schema 中的 action 分类、输出类型、输出后缀迁入统一算子 metadata，减少新增算子时需要修改的文件数量。
- 为 `io_prefs` 增加更明确的 schema/校验函数，避免不同面板自行约定字段名。
- 增加保存/加载/运行链路的自动化测试，覆盖旧 JSON、`io_prefs`、多输出代码块、模板链路。

### 中优先级

- 统一算子元数据，减少以下位置的重复配置：
  - `operator_registry.py`
  - `core/workflow/operators.py`
  - `core/workflow/schema.py`
  - 各 panel 文件
- 将算子类型、输入模式、输出类型、输出后缀、面板类、执行类整合为统一 metadata。
- 拆分 `ui/design/workflow_io.py`：
  - 纯 JSON 加载、保存、校验、迁移放入 core 层。
  - 画布节点和连线恢复留在 UI 层。
- 拆分 `workspace_context.py`：
  - workflow 编译
  - 设计时预览数据池
  - 运行协调和结果合并

### 低优先级

- 将 `engine.py` 拆成纯 Python runner 和 Qt thread wrapper。
- 将 DataFrame、Workbook 的预览适配抽到独立 preview adapter。
- 将参数引用菜单和参数解析上下文从 `BaseToolPanel` 拆成独立 mixin/service。
- 清理非迁移层中的局部变量名 `df_name/out_name`，改成更明确的 `input_name/output_name/current_table_name/display_name`。

## 建议改造顺序

1. 先迁移单输入面板的 `inputs/outputs` 生成职责到 schema。
2. 再迁移双输入面板 `JoinPanel` / `ConcatPanel`。
3. 再迁移批量多输入面板 `BatchMapFlowPanel` 系列。
4. 最后迁移代码块和模板类面板，因为它们涉及 alias、workbook、worksheet 和特殊输出类型。
5. 完成 IO 生成收口后，再统一算子 metadata。
6. 最后拆分 workflow IO、workspace context 和 engine。

## 保留策略

- 旧 JSON 兼容字段暂时继续保留在 `core/workflow/schema.py`。
- 新保存的工作流保留标准 `inputs/outputs` 作为执行协议，同时可保留 `io_prefs` 作为 UI 偏好。
- 执行层只消费标准 workflow config，不兼容 UI 老参数。
