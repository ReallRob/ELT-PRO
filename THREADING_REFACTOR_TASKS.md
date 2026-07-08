# 多线程整改任务记录

本文档记录将导入、模板加载、预览生成、设计态单节点运行和代码块执行统一改造成后台任务模型的整改方案。目标是减少 UI 主线程卡顿，同时保留清晰的任务状态、日志、超时废弃和错误处理规则。

## 整改目标

- UI 主线程只负责交互、绘制、状态更新和结果展示，不做重 I/O 或重计算。
- 导入数据源、加载模板、生成预览、保存模板、设计态单节点运行和代码块执行都进入后台任务体系。
- Workbook 不跨进程传递，优先在线程内共享同一进程内存对象，避免大模板临时 xlsx 保存/加载往返。
- 代码块采用 DataFrame 子进程 + Workbook/Worksheet 内存执行的混合策略；Workbook 不再通过临时 xlsx 跨进程往返。
- 所有后台任务必须带 `task_id` / `generation`，避免旧任务结果覆盖新界面。

## 核心原则

- UI 线程禁止执行 `pandas.read_excel`、`openpyxl.load_workbook`、`workbook_to_preview_data`、`wb.save` 和用户代码。
- 后台线程不得直接操作 Qt UI，只能通过 signal / callback 把状态、日志、结果发回主线程。
- 线程无法安全强杀，超时只能标记任务废弃；未来返回的成功/失败结果都必须按 `task_id` 检查后决定是否丢弃。
- 第一版应限制并发，尤其是用户代码任务，同一时间只允许一个，避免死循环线程堆积。
- 预览必须轻量化、限量化、懒加载；不要因为选中节点就全量解析大 Workbook。
- Workbook 对象不适合多线程并发修改；同一时刻只能由一个任务拥有修改权。

## 推荐线程分工

### UI 主线程

负责：

- 用户交互、按钮状态、弹窗、状态栏。
- 画布节点刷新、配置面板刷新、预览结果展示。
- 接收后台任务完成信号，并把有效结果合并到 UI 状态。

禁止：

- 同步读取大文件。
- 同步加载模板。
- 同步生成大预览。
- 同步执行代码块。
- 同步保存大 Workbook。

### BackgroundTaskManager

统一管理后台任务：

- 提交任务。
- 分配 `task_id` / `generation`。
- 转发日志、进度、成功、失败、超时事件。
- 标记任务废弃。
- 限制并发。
- 清理过期任务引用。

可基于 `QThreadPool + QRunnable` 或 `QThread + Worker` 实现。第一版建议优先简单可靠，避免一次性引入复杂调度。

### DataTask Worker

负责数据 I/O 和解析：

- `pandas.read_excel` / `read_csv`。
- `openpyxl.load_workbook`。
- 文件元信息探测。
- DataFrame 轻量预览生成。
- Workbook 轻量预览生成。

### Workflow Worker

负责设计态单节点运行：

- 构建并运行局部 workflow。
- 汇总日志。
- 返回 `display_pool`、`output_key_map`、`output_meta`。
- 完成后由 UI 主线程合并结果。

正式执行页和 CRPA JSON 运行器已有 `WorkflowEngine(QThread)` 基础，但也要统一日志和状态规则。

### CodeBlock Worker

负责用户代码执行：

- DataFrame/普通代码块走独立子进程，保留超时强制终止能力。
- Workbook/Worksheet 上游输入走同进程后台线程内存执行，避免大模板临时保存/加载。
- stdout/stderr 实时回传。
- 超时后标记废弃，不合并结果。
- 注入 `should_cancel()` / `check_cancel()` 供用户长循环主动退出。

## 统一任务状态模型

建议后台任务统一携带以下字段：

```python
{
    "task_id": "uuid",
    "generation": 12,
    "task_type": "load_template | import_data | preview | run_node | code_block | save_template",
    "node_id": "optional node id",
    "status": "pending | running | success | failed | timeout | discarded",
    "deadline": 123456.0,
    "cancel_requested": False,
}
```

回调处理必须遵循：

```text
如果 task_id 不是当前有效任务
  -> 丢弃结果
如果 generation 不是当前项目/画布版本
  -> 丢弃结果
如果任务已 timeout/discarded
  -> 丢弃成功或失败结果
否则
  -> 合并结果并刷新 UI
```

## 超时与错误规则

### 未超时报错

有效任务抛异常时：

- 标记 `failed`。
- 保留 traceback。
- 显示错误摘要和完整错误详情。
- 不发布输出。
- 恢复 UI 按钮状态。

### 已废弃任务报错

任务已超时、被取消、被新任务替代或 generation 过期后抛异常时：

- 不弹窗。
- 不更新当前节点状态。
- 不发布输出。
- 可写内部 debug 日志。

### 超时废弃

任务超时时：

- 标记 `timeout` / `discarded`。
- UI 显示“已超时，结果将被忽略”。
- 恢复运行按钮。
- 后台线程未来返回成功/失败都丢弃。
- 如是用户代码任务，提示线程可能仍在后台运行，必要时重启程序。

## 整改步骤

### 阶段 1：建立后台任务基础设施

- 新增 `BackgroundTaskManager` 或 `DataTaskManager`。
- 定义统一任务状态、信号和回调协议。
- 加入 `task_id` / `generation` 检查。
- 实现最小并发限制：同一时间只允许一个用户代码任务。

### 阶段 2：导入数据源线程化

- 将 Excel/CSV 读取放入 DataTask Worker。
- Worker 返回 DataFrame、轻量 meta、轻量 preview。
- UI 主线程只注册结果并刷新显示。
- 连续导入时旧任务结果必须丢弃。

### 阶段 3：加载模板线程化

- 将 `openpyxl.load_workbook` 放入 DataTask Worker。
- Worker 返回 `{"_wb": wb, "_meta": meta}`。
- UI 主线程注册轻量结果；可变 Workbook 优先留在运行时上下文，不直接作为预览数据全量转换。
- 加载中显示状态，不阻塞窗口操作。

### 阶段 4：预览生成后台化/懒加载

- DataFrame preview 生成放入后台线程。
- Workbook preview 生成放入后台线程。
- 限制最大 Sheet 数、最大行数、最大列数。
- 大 Workbook 默认显示轻量信息，必要时点击加载预览。
- 未运行的加载模板节点不得因为预览触发 `load_workbook(path)`。

### 阶段 5：设计态单节点运行异步化

- `_run_node()` 改为提交 Workflow Worker。
- 运行中禁用重复运行。
- 完成后再合并结果、刷新预览、更新节点标题。
- 已运行且未修改的上游节点优先复用 raw 输出缓存，避免运行下游时重复执行上游代码块。
- 上游节点脏、存在脏祖先或 raw 缓存缺失时，自动回退为运行必要上游，保证结果正确。
- 节点参数变更或节点重新产出后，必须清理自身及下游旧预览/raw 缓存，并将下游标记为待运行，防止复用过期结果。
- 连线结构变更时，所有接收输入的节点运行缓存必须失效并标记待运行，防止旧输入关系下的结果继续参与复用。
- 复用 Workbook raw 缓存时必须先克隆，避免下游代码块修改 `wb` 污染上游缓存。
- 用户运行时切换节点不影响结果归属。
- 旧任务结果必须按 `task_id` 丢弃。

### 阶段 6：代码块线程化

- DataFrame/普通代码块继续使用独立子进程，超时可强制终止。
- Workbook/Worksheet 代码块强制走内存执行，禁止旧配置回退到子进程临时 xlsx 往返。
- stdout/stderr 实时回传。
- 超时后标记废弃。
- 注入 `should_cancel()` / `check_cancel()`。
- UI 明确提示线程模式无法强制杀死死循环。

### 阶段 7：保存模板后台化

- `wb.save(path)` 放入后台线程。
- 保存期间 UI 显示状态。
- 失败时显示 traceback 或友好错误。
- 保存成功后更新路径和状态。

### 阶段 8：文档和提示更新

- 更新 `CODE_BLOCK_TASKS.md`。
- 更新 README 或性能优化文档。
- UI tooltip 明确线程模式、超时废弃、死循环风险。

## 关键风险

- Python 线程不能安全强杀，死循环线程可能持续占 CPU。
- 纯 Python CPU 死循环可能占用 GIL，影响整体响应。
- Workbook 对象不应被多个线程同时修改。
- 旧任务结果如果没有严格丢弃，会出现幽灵错误或旧结果覆盖新结果。
- 后台任务持有大 DataFrame/Workbook 引用时，容易造成内存不释放。
- 预览转换如果仍在主线程，加载线程化后卡顿会转移到预览阶段。

## 测试清单

### 静态检查

- 对所有改动 Python 文件运行 `python -m py_compile`。
- 检查是否存在后台线程直接操作 Qt UI 的代码。

### 导入数据源

- 导入大 Excel 文件时拖动窗口、切换节点、滚动配置面板。
- 导入过程中再次选择其它节点，旧任务完成后不得污染当前 UI。
- 导入失败时显示错误，不注册半成品数据。

### 加载模板

- 加载多 Sheet、大样式 Workbook，主窗口不冻结。
- 加载中显示状态。
- 加载完成后运行时上下文可持有 `_wb` 和 `_meta`，设计态 `data_pool` 优先保存轻量预览或轻量说明。
- 连续选择不同模板时，旧模板加载结果必须丢弃。

### 预览

- 选中大 Workbook 输出节点不应立即卡死。
- Preview 限制 Sheet/行/列数量。
- 后台预览完成后刷新 UI。
- 未运行模板节点预览不得临时 `load_workbook(path)`。

### 设计态单节点运行

- 普通节点运行成功后预览刷新、输出名称正确。
- 运行中切换节点，完成后结果仍归属原节点。
- 快速连续点击运行，只启动一个有效任务。
- 代码块 A 已成功运行且未修改时，运行下游代码块 B 不应重复执行 A，A 的 `print()` 不应再次出现在 B 的运行日志。
- 修改 A 后再运行 B，应自动重新运行 A 和 B，避免使用过期缓存。
- A 重新运行成功后，B/C 等下游旧预览和 raw 缓存应失效，不能继续被当作有效输出复用。
- 新增或删除连线后，接收输入的节点应被标记待运行，旧预览/raw 缓存应失效。
- 删除节点或删除连线后，相关节点及下游旧预览/raw 缓存应被清理，不应留下孤立运行结果。
- B 修改来自 A 的 Workbook 时，不应污染 A 的 raw 缓存；再次运行 B 应从 A 的缓存克隆副本开始。
- 运行失败时显示错误摘要和完整详情。

### 代码块成功场景

```python
print("start")
result = df
print("done")
```

预期：日志实时显示，输出发布，预览刷新。

### 代码块异常场景

```python
print("before error")
raise ValueError("测试错误")
```

预期：保留报错前日志，显示 traceback，不发布输出。

### 代码块超时废弃

```python
import time
time.sleep(999)
result = df
```

预期：超时后 UI 恢复，任务标记废弃，未来返回结果不合并。

### 死循环风险

```python
while True:
    pass
```

预期：超时后提示线程可能仍在后台运行，禁止继续启动多个用户代码任务。

### 软取消

```python
for i in range(1000000):
    check_cancel()
    # long work
```

预期：取消或超时后 `check_cancel()` 抛出取消异常，任务快速结束。

### Workbook 代码块

流程：

```text
加载模板 -> 代码块修改 ws["A1"] -> 保存模板
```

预期：不跨进程、不生成中间 xlsx，保存文件包含修改。

### 保存模板

- 保存大 Workbook 时 UI 不冻结。
- 保存成功后显示目标路径。
- 保存失败时显示友好错误。

### 旧任务丢弃

- 任务 A 超时后启动任务 B。
- A 后续成功或失败不得覆盖 B 的输出。
- A 后续失败不得弹出幽灵错误。

### 内存观察

- 多次加载模板、运行代码块、废弃任务后观察内存。
- 确认过期任务引用被释放。
- 确认不保留不必要的 Workbook/DataFrame 强引用。

## 第一版验收标准

- 导入大数据源时 UI 不冻结。
- 加载大模板时 UI 不冻结。
- 预览大 Workbook 时不全量阻塞 UI。
- 设计态单节点运行不会占住主线程。
- 代码块日志仍能实时显示。
- 超时任务结果不会合并。
- 旧任务错误不会弹幽灵错误。
- Workbook 模板主线不跨进程、不保存中间 xlsx。

## 已实施记录

### 2026-07-07：阶段 5 设计态单节点运行异步化

已完成：

- 设计态单节点运行从 `ctx.run_workflow_sync()` 改为后台 `WorkflowEngine.start()`。
- 单节点运行期间 UI 主线程不再直接执行 `load_workbook`、`read_excel`、`workbook_to_preview_data` 或代码块主逻辑。
- 代码块 `print()` 日志继续通过 `WorkflowEngine.log_signal` 回到代码编辑器日志区。
- 新增单节点 `generation` / `discarded` 状态，清空画布或导入工作流时旧任务结果会被丢弃。
- 单节点运行与全量运行互斥，同一时间只允许一个有效设计态运行任务。
- 用户运行节点 A 时切换到节点 B，A 的结果仍归属 A；完成后只在当前仍选中 A 时刷新 A 的预览，避免污染 B 的界面。
- 设计态预览面板不再对原始 `_wb` 兜底执行同步 `workbook_to_preview_data()`，仅显示轻量说明，防止未来直接注册 Workbook 时再次卡 UI。
- 数据源面板读取 Excel sheet 名改为后台扫描，连续换文件时旧扫描结果会被丢弃。
- 加载模板面板选择文件后的结构扫描改为后台扫描，并限制界面最多展开显示 80 个 sheet。
- 模板预览生成会使用面板中的预览 sheet/范围配置；未指定 sheet 时默认只预览前 3 个 sheet，并在预览区显示未展开说明。
- Workbook/Worksheet 代码块内存执行模式已注入 `should_cancel()` / `check_cancel()`，并启用纯 Python 行级超时检查。
- 代码块面板已提示内存模式的取消边界：长循环可协作取消，阻塞型 IO/长 sleep 无法安全强杀。
- 设计态单节点运行新增外部超时废弃计时器：代码块超过配置超时时会先恢复 UI、标记结果废弃，旧线程未来返回不会合并。
- 已废弃后台任务仍在收尾时会阻止新的单节点/全量运行，避免多个阻塞代码线程堆积。
- 设计态全量运行新增外部代码块超时废弃计时器，超时后关闭进度框并忽略旧引擎结果。
- 执行页运行引擎新增外部代码块超时废弃计时器，超时后恢复运行按钮并忽略旧引擎结果。
- 设计态单节点运行新增 raw 输出缓存复用：运行下游节点时，已运行、未修改且无脏祖先的上游节点不再重复执行，直接将 raw 输出注入本次后台引擎。
- raw 缓存与预览数据分离：预览继续使用轻量 `display_pool`，下游运行读取 `raw_data_pool` 中的真实 DataFrame/Workbook。
- 注入上游 Workbook raw 缓存时会先内存克隆，避免下游代码块原地修改 `wb` 后污染上游缓存。
- 节点配置变更和节点重新运行成功后，会清理自身及下游旧预览/raw 缓存并标记下游待运行，防止缓存复用过期结果。
- 连线结构变更后会清理所有接收输入节点的运行缓存并标记待运行，避免旧输入拓扑下的结果继续显示为有效。
- 删除节点或连线时会提前清理相关运行缓存，避免画布结构变化后留下孤立预览/raw 输出。

已验证：

- `python -m py_compile core\\dataframe_ops\\code_exec.py core\\dataframe_ops\\code_block.py core\\workflow\\operators.py core\\workflow\\timeouts.py engine.py operators\\panels\\background_scanners.py operators\\panels\\code_block_panel.py operators\\panels\\io_panels.py operators\\panels\\template_panels.py ui\\design\\node_config.py ui\\design\\preview_panel.py ui\\design\\import_export_ui.py ui\\design\\canvas_actions.py ui\\design\\run_controls.py workspace_context.py ui\\execute\\run_controls.py` 通过。
- 代码块 smoke：DataFrame 子进程 `print()`、Workbook 内存模式 `print()`、Workbook 纯 Python 死循环超时、`check_cancel()` 协作超时均验证通过。
- 单节点缓存 smoke：代码块 B 复用 A 的 raw 输出运行时，A 的 `print()` 不再重复出现；Workbook 缓存克隆后，下游修改不会污染上游缓存。

本轮收尾：

- 设计态旧同步入口 `ctx.run_workflow_sync()` 已改为明确禁用，避免后续误把重 I/O、预览转换、保存或用户代码接回 UI 线程。
- 保存模板节点的 `wb.save()` 通过设计态单节点、设计态全量运行、执行页和 CRPA 运行器的 `WorkflowEngine(QThread)` 执行；当前没有直接在 UI 线程调用 `save_template()` 的保存按钮路径。
- 代码块包含上游 Workbook/Worksheet 时，无论旧 JSON 是否写了 `execution_mode: process`，都会强制使用内存执行，禁止回退到临时 xlsx 跨进程传递。
- `should_cancel()` / `check_cancel()` 已作为保留变量名，避免输入别名覆盖协作取消函数。

后续可选增强，不列为本轮阻塞项：

- 如果后续需要“不运行节点也直接加载数据到设计态”，再拆独立 DataTask；当前正式运行路径已在后台 `WorkflowEngine` 中执行。
- 如果后续需要从设计态直接浏览原始内存 Workbook 的指定 sheet，可追加后台预览 Worker；当前已避免 UI 线程同步全量转换。
- 如果后续需要让“代码内部自己 `load_workbook()` 并 return Workbook”也完全避免子进程序列化，应增加显式高级执行模式或静态声明；当前默认保留子进程强杀能力。
- 若要把 DataFrame 代码块也完全线程化，需要单独评估阻塞型代码无法强杀的风险。
