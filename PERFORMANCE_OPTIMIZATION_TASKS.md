# 性能优化任务记录

本文档记录性能优化负责范围、当前排查方向、任务拆分和验收标准。目标是在不改变现有工作流语义的前提下，降低大数据量和复杂模板场景下的耗时、内存峰值与界面卡顿。

## 兼容性约束

- 项目最低运行环境按 Python 3.8 兼容处理；性能优化和新代码不能引入 Python 3.9+ 才可解析或导入的语法。
- 如使用 `list[...]`、`dict[...]`、`tuple[...]` 或 `A | None` 等新式类型注解，运行时模块必须通过 `from __future__ import annotations` 延迟注解求值，避免 Python 3.8 启动时报 `TypeError: 'type' object is not subscriptable`。
- 验证兼容性时，除 `py_compile` 外应至少用 `ast.parse(..., feature_version=(3, 8))` 扫描改动文件或全仓 Python 文件。

## 负责人职责

- 建立可重复的性能基线，记录典型工作流在不同数据规模下的耗时、内存和输出规模。
- 优先定位高频、高耗时、高内存路径，避免只凭直觉改动。
- 优化执行链路中的无意义复制、重复预览转换、过早发布中间结果和模板逐单元操作成本。
- 保持功能兼容，所有优化必须保留现有 JSON 工作流、显式 `inputs/outputs` 和 CRPA launcher 执行能力。
- 每轮优化后补充验证结果，说明收益、风险和后续观察点。

## 优化目标

### 第一阶段目标

- 全量工作流执行时，减少不必要的中间 DataFrame 常驻内存。
- 大表预览只渲染必要行列，避免 UI 因模型构建或模板预览转换卡顿。
- 模板导入、区域插入、匹配填充场景减少重复遍历和无意义 `copy()`。
- 用户代码块执行前明确数据规模成本，避免大表跨进程序列化导致体验不可预期。

### 长期目标

- 建立 `profile` 或轻量计时日志，让每个节点能输出执行耗时、输入输出规模和内存提示。
- 为核心算子增加大数据样例回归，防止后续重构引入性能退化。
- 将预览数据、真实运行数据和导出数据边界区分清楚，减少 UI 与执行层互相拖慢。

## 当前重点排查路径

### 执行引擎

相关文件：`engine.py`、`workspace_context.py`、`core/workflow/runtime_store.py`、`core/workflow/operators.py`

- 已梳理 `keep_intermediates=True/False` 的差异：设计态全量运行保留中间结果用于预览；执行态由调试开关决定；CRPA launcher 改为默认不保留中间结果。
- 已给 `WorkflowEngine` 增加节点级耗时日志，默认输出简洁 `[perf]`，开启 `workflow_config.profile` 或 `profile_mode` 后输出更详细 `[profile]`。
- 输出日志现在包含 DataFrame 行列数和估算内存，便于定位大对象。
- `workspace_context.py` 构建工作流时减少重复深拷贝：节点参数只做一次深拷贝，步骤参数用浅拷贝剥离 `action`；后台线程运行前仍会创建独立 workflow 快照，避免 UI 编辑影响运行中任务。
- 发布预览时 workbook 默认只转换前 3 个 sheet，避免完整 workbook 一次性变成多个预览 DataFrame。

### DataFrame 算子

相关文件：`core/dataframe_ops/*`、`core/workflow/operators.py`

- 已新增 `tools/performance_baseline.py`，默认覆盖 1 万行、10 万行、50 万行场景，并支持 `--report` 导出 Markdown、JSON 或 CSV 性能报告。
- 已新增 `tools/validate_large_dataframe_ops.py`，覆盖过滤、连接、拼接、聚合、计算列的大数据正确性验证。
- 已移除明确无副作用的复制：`left_join()` 左表复制、`pivot_table()`/`melt_table()` 前置整表复制、模板插入 payload 中的只读 DataFrame 复制、模板写入截断切片复制。
- 暂时保留有隔离意义或语义保护意义的复制：清洗/计算列会修改列，代码块需要隔离用户代码副作用，过滤/选列返回独立结果以保护下游修改安全。
- 后续继续以基线结果为依据处理 `df.copy()`，避免为了省内存破坏算子隔离边界。

### 模板处理

相关文件：`template_engine.py`、`operators/panels/template_panels.py`

- `workbook_to_preview_data()` 已支持 `max_sheets`，返回 `sheet_count`、`previewed_sheet_count`、`skipped_sheets`、`preview_truncated` 元信息。
- 新增 `worksheet_to_preview_df()` 和 `workbook_sheet_preview_data()`，支持按单个 sheet、起始行列和最大行列范围构建预览，并已接入导入模板节点的设计态预览配置。
- 设计态临时模板预览默认只转换首个 sheet；执行引擎发布模板预览默认转换前 3 个 sheet。
- 执行模式导出模板预览时，如果存在真实保存路径，优先复制真实 xlsx，避免把截断预览当完整 workbook 导出。
- 匹配填充已改为列数组构建匹配索引：只保存首个匹配行号和重复键集合，写入时按列数组读取值，减少逐行 `df.iloc` 创建 Series 的成本。
- 后续重点是逐单元写入热点、公式保护策略和执行态更细粒度 sheet/range 预览交互。

### UI 预览

相关文件：`ui/design/preview_panel.py`、`ui/execute/preview_panel.py`、`table_model.py`

- `PandasModel` 已有预览行数限制和分批加载机制。
- `PandasModel` 新增稳定缓存 key，设计态和执行态预览都加入小型模型缓存，重复查看同一数据对象时复用模型。
- 模板预览通过限制 sheet 数和导入模板节点的 sheet/range 预览配置降低一次性渲染压力。
- 设计态导入模板预览可配置预览工作表、起始行列和最大行列数；后续可把相同策略扩展到执行态模板结果查看。

### 用户代码块

相关文件：`core/dataframe_ops/code_exec.py`、`core/dataframe_ops/code_block.py`、`operators/panels/code_block_panel.py`

- 当前仍保留代码块输入 `df.copy()`，这是为了隔离用户代码副作用。
- `core/dataframe_ops/code_exec.py` 已补充 `from __future__ import annotations`，修复 Python 3.8 下 `outputs: list[CodeExecutionOutput]` 导致的启动导入错误。
- 后续可在 UI 或日志中提示跨进程序列化的数据规模和风险。
- 保持超时机制和安全边界优先，不为性能牺牲隔离性。

## 任务清单

### 高优先级

- [x] 建立性能基线脚本或手动记录模板，覆盖 1 万行、10 万行、50 万行 DataFrame 场景。
- [x] 给 `WorkflowEngine` 增加节点级耗时日志，默认简洁输出，必要时可扩展为详细模式。
- [x] 盘点并标注核心路径中的 `df.copy()`，先优化明确无副作用的复制。
- [x] 优化模板预览：避免非必要情况下转换所有 sheet 的完整预览数据。
- [x] 检查全量执行结束后的 `display_pool` 是否保留了过多大对象，明确设计态和执行态差异。

### 中优先级

- [x] 为 DataFrame 过滤、连接、拼接、聚合、计算列增加大数据样例验证。
- [x] 优化模板匹配填充的数据查找结构，减少重复扫描。
- [x] 为 UI 预览增加模型复用或轻量刷新策略。
- [x] 统一输出节点规模日志格式，例如 `rows`、`cols`、`memory_mb`、`elapsed_ms`。
- [x] CRPA launcher 执行完成后确认 workbook、DataFrame 和临时对象释放路径。

### 低优先级

- [x] 引入可选性能报告导出，方便对比不同版本优化效果。
- [x] 为大型 Excel 文件增加更细的预览加载策略，例如按 sheet 或按范围懒加载。
- [x] 梳理 `workspace_context.py` 中同步运行与后台线程运行的差异，减少重复深拷贝。
- [x] 在文档中补充大数据工作流使用建议。

## 大数据工作流使用建议

- 数据源导入时尽量配置 `nrows`、`start_col`、`ncols` 和精确 sheet，先缩小输入规模，再做后续清洗和计算。
- 过滤、选列、去重等能减少行列规模的算子应尽量靠前放置，降低后续连接、排序、模板写入和预览成本。
- 大表连接前优先确认右表提取列最少、匹配键唯一；如果右表存在重复键，先去重或聚合后再连接。
- 排序、透视、逆透视、代码块和模板写入都可能产生较大临时对象，建议放在必要路径末端，避免对同一大表重复执行。
- 执行模式下不要轻易开启调试保留中间结果；需要排查时只保留必要流程，排查结束后关闭。
- 模板预览只用于检查结构和局部结果，不应依赖预览加载完整大型 workbook；完整结果以保存的 xlsx 为准。
- 代码块会跨进程序列化 DataFrame，输入大表前应先过滤和选列，避免把无关数据传入代码沙箱。
- 用 `python tools\performance_baseline.py --report reports\baseline.json` 保存基线，优化前后保留同格式报告，方便做版本对比。

## 验收标准

- 优化前后至少保留一组可对比基线，包含数据规模、步骤数、执行耗时、内存观察和输出结果。
- 核心功能不回退：工作流加载、保存、运行、模板导入/写入、执行模式预览、CRPA launcher 均保持可用。
- 优化后的代码通过基础语法检查，例如 `python -m py_compile` 覆盖改动文件。
- 运行环境兼容 Python 3.8；涉及类型注解或语法特性的改动需通过 Python 3.8 语法模式检查。
- 涉及 UI 的改动至少手动验证一次主程序启动和典型预览流程。
- 性能收益必须写回本文档或后续记录，不能只停留在代码改动里。

## 记录模板

每次性能优化完成后按以下格式追加：

```text
日期：YYYY-MM-DD
范围：涉及文件或模块
场景：数据规模、工作流节点、模板大小
改动：关键优化点
结果：优化前耗时/内存，优化后耗时/内存
验证：运行过的命令或手动验证步骤
风险：可能影响的边界场景
后续：下一步观察或待办
```

## 优化记录

```text
日期：2026-06-30
范围：engine.py、template_engine.py、core/dataframe_ops、core/workflow/operators.py、ui 预览、CRPA launcher、tools/performance_baseline.py
场景：DataFrame 核心算子、模板 workbook 预览、执行态 display_pool
改动：新增节点级 perf/profile 日志；新增基线脚本；模板预览支持 max_sheets；CRPA 默认不保留中间结果；移除部分无副作用 DataFrame copy；模板导出优先复制真实保存文件。
结果：已降低模板预览一次性转换规模，并减少连接、透视、逆透视、模板 payload 和模板写入截断路径的额外复制。默认基线显示 50 万行场景下，filter_numeric 约 736.5ms，clean_strip_text 约 107.1ms，sort_amount 约 56.8ms，group_sum 约 69.2ms，left_join 约 7.9ms。
验证：`python -m py_compile engine.py template_engine.py core\workflow\operators.py core\dataframe_ops\table.py core\dataframe_ops\aggregate.py ui\design\preview_panel.py ui\execute\preview_panel.py crpa_launcher\app.py tools\performance_baseline.py`；`python tools\performance_baseline.py --repeats 1`。
风险：模板预览默认不再展示所有 sheet，但导出会优先使用真实保存的 xlsx；需要继续观察用户是否需要完整预览入口。
后续：补充基线结果，继续优化匹配填充和 UI 预览缓存。
```

```text
日期：2026-06-30
范围：template_engine.py、table_model.py、ui/design/preview_panel.py、ui/execute/preview_panel.py、tools/validate_large_dataframe_ops.py
场景：10 万行 DataFrame 算子验证、模板匹配填充、设计态/执行态预览重复渲染
改动：新增大数据算子验证脚本；模板匹配填充改为列数组索引和首行位置映射；设计态和执行态预览增加 PandasModel 小型缓存。
结果：10 万行验证通过：filter 约 169.7ms，left_join 约 2.0ms，concat_rows 约 5.5ms，group_calc 约 11.3ms，calc_col 约 5.9ms。模板匹配填充烟测保持重复键取第一条语义。
验证：`python -m py_compile template_engine.py table_model.py ui\design\preview_panel.py ui\execute\preview_panel.py tools\validate_large_dataframe_ops.py`；`python tools\validate_large_dataframe_ops.py --rows 100000`；模板匹配填充内存样例烟测。
风险：预览模型缓存会短暂保留最近的数据模型引用，已限制设计态 16 个、执行态 8 个；上下文无数据时会清理缓存。
后续：继续评估大型模板逐单元写入耗时，补充性能报告导出能力。
```

```text
日期：2026-06-30
范围：tools/performance_baseline.py、template_engine.py、workspace_context.py、operators/panels/template_panels.py、ui/design/preview_panel.py、table_model.py、PERFORMANCE_OPTIMIZATION_TASKS.md
场景：性能报告导出、大型 Excel 局部预览、设计态 workflow 构建和后台运行
改动：基线脚本支持 `--report` 和 Markdown/JSON/CSV 导出；模板引擎新增单 sheet/range 预览接口并接入导入模板设计态预览配置；workspace_context 构建阶段减少重复深拷贝，后台运行保留独立快照；补充大数据工作流使用建议。
结果：可生成可对比报告文件；大型 Excel 设计态模板预览可只加载指定 sheet/range；构建工作流时避免对同一 params 连续深拷贝。
验证：`python -m py_compile engine.py template_engine.py table_model.py workspace_context.py operators\panels\template_panels.py ui\design\preview_panel.py ui\execute\preview_panel.py tools\performance_baseline.py tools\validate_large_dataframe_ops.py core\workflow\operators.py core\dataframe_ops\table.py core\dataframe_ops\aggregate.py`；`python tools\performance_baseline.py --rows 1000 --repeats 1 --report _tmp_perf_report.json`；`workbook_sheet_preview_data()` range 烟测。
风险：sheet/range 懒加载已接入导入模板设计态预览，但执行态模板结果查看仍展示结果中的首个预览 sheet；后台运行仍会深拷贝 workflow 快照，这是为了线程安全保留的必要成本。
后续：将 sheet/range 懒加载扩展到执行态模板结果查看，并增加报告对比工具。
```

```text
日期：2026-06-30
范围：core/dataframe_ops/code_exec.py、PERFORMANCE_OPTIMIZATION_TASKS.md
场景：Python 3.8 启动兼容性；Linux 环境运行 `python3 main.py` 导入用户代码块模块时失败
改动：为 `code_exec.py` 增加 `from __future__ import annotations`，避免 Python 3.8 在导入 dataclass 时立即求值 `list[CodeExecutionOutput]` 类型注解。
结果：修复截图中的 `TypeError: 'type' object is not subscriptable` 启动报错；明确后续优化必须兼容 Python 3.8。
验证：`python -m py_compile core\dataframe_ops\code_exec.py core\dataframe_ops\__init__.py core\dataframe_ops\calc.py main.py operator_registry.py operators\base_panel.py`；`python -c "import core.dataframe_ops.code_exec as m; print('code_exec import ok')"`；全仓 `ast.parse(..., feature_version=(3, 8))` 语法检查；新式注解文件均检查到 `from __future__ import annotations`。
风险：当前验证是在本机 Python 环境模拟 Python 3.8 语法模式；用户机器仍需确认依赖版本和 PyQt/pandas/openpyxl 安装完整。
后续：新增或修改模块时继续把 Python 3.8 兼容性作为验收项。
```

## 当前结论

项目已经具备中间结果引用计数释放、模板预览行列限制、代码块超时机制、节点级性能日志、大数据算子验证、预览模型复用、性能报告导出和导入模板设计态 sheet/range 局部预览。后续性能工作应优先围绕真实基线报告做对比优化，重点继续观察大表代码块、模板逐单元写入和执行态大型 Excel 结果查看。
