# 代码块任务记录

本文档记录代码块算子的设计约定、当前实现状态、已完成事项和后续待完善项。代码块目标是成为一个可独立运行、可复用函数库、可处理 DataFrame 和模板 Workbook 的高级自定义算子。

## 当前设计目标

- 代码块可以没有上游输入，理论上一个代码块也能完成整个项目处理。
- 代码块输入彼此同级，不再区分主表、连接表或当前表。
- 代码块可以接入多个 DataFrame，也可以接入模板 Workbook。
- 代码块可以只处理 DataFrame 并输出 DataFrame。
- 代码块可以处理 Workbook；包含 Workbook 输入时会直接使用内存对象执行，避免大模板跨进程保存/加载。
- 代码块支持当前代码、函数库和说明三个标签页。
- 函数库由多个函数空间组成，每个空间有独立名称、命名空间、启用状态和代码。
- 函数空间供所有代码块复用，函数内部可以 return。
- 当前代码块可以直接写脚本；需要输出给下游时，可以直接 return，也可以赋值 result 或 df/wb。
- 返回结果推荐使用字典形式，以便明确输出名称和多输出。
- 代码块执行时会实时捕获 `print()` / stderr，并同步到运行日志、CRPA JSON 运行器和代码编辑窗口日志区。

## 输入模型

### DataFrame 输入

- 输入类型为 `table`。
- 默认变量名按同类型顺序生成：
  - 第一个 DataFrame：`df`
  - 第二个 DataFrame：`df1`
  - 第三个 DataFrame：`df2`
- 用户可以在代码块面板中修改变量名。
- 所有 DataFrame 输入也会放入 `dfs` 字典。
- 代码块执行时会复制 DataFrame 输入，用于隔离用户代码副作用，避免在代码块内部修改时影响原始上游 DataFrame。

### Workbook 输入

- 输入类型为 `workbook`。
- 默认变量名按同类型顺序生成：
  - 第一个 Workbook：`wb`
  - 第二个 Workbook：`wb1`
  - 第三个 Workbook：`wb2`
- 所有 Workbook 输入也会放入 `wbs` 字典。
- Workbook 输入走内存执行路径，不再为了跨进程传递而保存临时 xlsx、再重新 `load_workbook()`。
- 当存在 Workbook 输入且当前代码没有显式 `return` / `result` 时，默认输出第一个内存 Workbook 的修改结果。
- 不再在输入配置区生成 `ws` 变量；需要工作表时，在代码中写 `ws = wb.active` 或 `ws = wb["Sheet名"]`。

### 无输入代码块

- 代码块不强制要求连接上游输入。
- 无输入时可以无输出运行；需要输出给下游时，显式 `return` 或赋值 `result` / `df` / `wb`。
- 如果没有产生输出，代码块会成功返回 0 个输出；后续节点不能连接这个代码块的空输出。

## 输出模型

代码块通过返回值类型区分输出类型，而不是通过变量名区分。

### 支持的输出类型

- `pandas.DataFrame`：输出类型为 `table`。
- `openpyxl.Workbook`：输出类型为 `workbook`。
- `openpyxl.Worksheet`：自动取所属 Workbook，输出类型为 `workbook`。
- `dict[str, DataFrame/Workbook/Worksheet]`：多输出，key 作为输出名称，value 决定输出类型。
- `list` / `tuple`：多输出，按顺序生成输出名称。

### 推荐返回方式

```python
return {
    "明细结果": df,
    "处理后模板": wb,
}
```

- 字典 key 用于命名输出。
- 字典 value 的实际类型决定输出是表格还是模板。

### 没有 return 时的默认输出顺序

1. 如果当前代码局部变量里存在 `result`，使用 `result`。
2. 否则如果存在 Workbook 输入，默认输出第一个 Workbook。
3. 否则如果存在 DataFrame 输入，默认输出第一个 DataFrame。
4. 如果都没有，返回 0 个输出，运行仍可成功。

## 函数库模型

### 函数空间

函数库由多个函数空间组成。每个空间包含：

- `id`：内部唯一 ID。
- `name`：用户看到的空间名称，例如“日期函数”。
- `namespace`：代码调用名，例如 `date_utils`。
- `enabled`：是否参与运行。
- `expose_globals`：是否把空间内函数直接暴露到当前代码全局命名空间。新建空间默认关闭，只推荐旧 `global_code` 迁移空间开启。
- `code`：该空间代码。

推荐调用方式：

```python
df["月份"] = df["日期"].apply(date_utils.month_end)
df = df_utils.clean_columns(df)
excel_utils.set_title_style(ws["A1"])
```

不建议新函数默认裸调用：

```python
month_end(value)
```

这样函数多了以后容易重名。旧全局函数为了兼容可以继续裸调用。

### 函数空间加载规则

- 只加载 `enabled=True` 的空间。
- 按函数空间列表顺序加载。
- 每个空间会生成一个命名空间对象，例如 `date_utils`。
- 空间内部可以直接调用前面已经加载的函数空间，例如 `biz_rules` 可以调用 `date_utils.month_end()`。
- 函数内部可以返回普通值；需要输出给下游时，代码块输出应是 DataFrame、Workbook、Worksheet 或它们组成的 dict/list。

## 可用运行环境

### 已预置库

代码编辑窗口中按用户熟悉的 Python import 形式展示已预置能力，不再默认显示一串内部变量说明：

```python
import pandas as pd
import numpy as np
import re
import math
import openpyxl
from datetime import datetime, date, timedelta
from copy import copy, deepcopy
from openpyxl.utils import get_column_letter
```

高级变量单独放在折叠或低优先级说明里：`params`、`mappings`、`param()`、`state`、`dfs`、`wbs`。

### import 策略

- 允许用户写正常 Python import。
- import 受白名单限制，只允许程序已打包且明确允许的库。
- 当前允许的根模块包括：
  - `pandas`
  - `numpy`
  - `openpyxl`
  - `os`
  - `sys`
  - `re`
  - `math`
  - `datetime`
  - `copy`
  - `time`
- 说明页只展示允许导入的大模块名；具体 `from openpyxl.styles import Font` 这类写法由用户按需要自行编写。

- 不允许导入未授权模块。

## 执行与日志模型

- 代码块使用 `auto` 执行策略：无 Workbook 上游输入时走独立子进程；包含 Workbook 上游输入时走内存执行。
- 只要存在上游 Workbook，即使旧 JSON 手动写了 `execution_mode: process`，也会强制改为内存执行，禁止临时 xlsx 保存/加载往返。
- DataFrame/普通代码块由父进程轮询执行结果、实时日志和超时状态；超时后会终止独立执行进程。
- Workbook/模板代码块不跨进程传递 Workbook，可避免大模板临时 xlsx 保存/加载成本；内存模式已注入 `should_cancel()` / `check_cancel()`，并对纯 Python 代码启用行级超时检查。
- 内存模式无法安全强杀阻塞型系统调用、长 `time.sleep()` 或部分 C 扩展调用；这类代码应主动拆分循环并调用 `check_cancel()`。
- 如果代码块没有上游 Workbook，而是在代码内部自行 `openpyxl.load_workbook()` 并返回 Workbook，默认仍属于普通子进程执行；这样可以保留死循环强杀能力，但返回 Workbook 会经过子进程序列化。后续如需优化，可增加显式高级执行模式。
- 设计态单节点运行会在代码块超时时先标记后台任务废弃并恢复 UI；如果旧线程仍在收尾，会暂时禁止继续启动新的运行任务。
- `print()` 和 stderr 会按行捕获并输出为 `代码块输出:` / `代码块错误输出:` 日志。
- CRPA JSON 运行器和正式执行页会显示完整引擎日志；代码编辑窗口内的日志区只展示用户代码输出，避免被引擎步骤日志淹没。

### PyInstaller 注意事项

- 代码块运行不要求用户本机单独安装 Python，前提是程序用 PyInstaller 打包时已经把 Python 运行时和依赖库打进去。
- 因为代码块支持动态 import，打包时需要关注 hidden imports。
- openpyxl、pandas、numpy 等动态使用的模块需要在打包配置中显式覆盖。

## UI 当前状态

### 已完成

- 代码编辑窗口改为非模态窗口，打开后可以点击其它地方。
- 编辑窗口升级为三个标签页：
  - 当前代码
  - 函数库
  - 说明
- 函数库页用于管理多个函数空间，当前代码通过 `date_utils.xxx()`、`df_utils.xxx()` 等命名空间调用。
- 当前代码页只保留代码编辑器，不再被说明区挤占横向空间。
- 说明页按“当前输入、输出写法、已预置库、支持 import”分组展示。
- 说明页支持复制片段，可插入常用 import 和输出写法。
- 编辑窗口运行失败时显示短错误摘要，并可展开/复制完整错误详情。
- 编辑窗口运行时增加日志区，实时显示 `print()` / stderr 输出。
- 支持换行自动缩进。
- 支持 Tab 缩进和 Shift+Tab 反缩进。
- 支持缩进区块退格。
- 编辑窗口增加运行按钮，可在编写完成后直接测试。
- 代码块面板不再显示主表/连接表。
- 输入显示为同级形式，例如：
  - `输入 1 · 数据表`
  - `输入 2 · 模板`
- 无输入时显示代码块可独立运行的提示。
- 变量配置显示为中文“变量名”。
- 保存代码后切换算子再切回来，代码和输入配置应保持稳定。
- 多输出运行后在代码块面板展示输出列表，并允许修改输出显示名称。

### 当前 UI 约定

- 当前代码页用于当前节点实际执行的代码。
- 函数库页用于放所有代码块可复用的函数和常量。
- 说明页用于放当前输入、输出写法、已预置库和可 import 示例。
- 每个函数空间有命名空间，推荐通过命名空间调用，例如 `date_utils.month_end(value)`。
- 函数空间顶层不要直接写 `return`；函数内部可以 return。
- 函数空间可以返回普通值，当前代码可以继续使用这些值；需要输出给下游时，当前代码的 `return` / `result` 应是 DataFrame、Workbook、Worksheet 或它们组成的字典/列表。
- 从旧 `global_code` 迁移出来的空间可以保留“允许直接调用”能力，避免旧代码立刻失效；新建空间默认使用命名空间调用。
- 当前代码页可以直接 `return`。

## 已完成任务

- [x] 代码块支持当前代码和函数库两个编辑页。
- [x] 全局函数可被当前代码调用。
- [x] 函数可以继续调用其它函数。
- [x] 函数库支持多个函数空间、命名空间调用、启用/禁用和旧全局函数兼容。
- [x] 代码编辑窗口增加独立说明页，展示当前输入、输出写法、已预置库和支持 import。
- [x] 当前代码页恢复为全宽编辑区，说明不再挤占代码编辑空间。
- [x] 说明页支持复制片段，可插入已预置库和输出写法；支持 import 只显示根模块清单。
- [x] 代码编辑窗口运行失败时显示短错误摘要，可展开和复制完整错误详情。
- [x] 代码编辑窗口运行时实时显示 `print()` / stderr 输出。
- [x] 多输出运行后在代码块面板展示输出列表，支持修改输出显示名称。
- [x] 代码编辑框支持基础自动缩进。
- [x] 代码编辑框支持运行按钮。
- [x] 代码编辑窗口改为非模态。
- [x] 代码块支持无输入运行。
- [x] 代码块支持多个 DataFrame 输入。
- [x] 代码块支持 Workbook 输入。
- [x] 代码块输入配置区已移除 Worksheet alias；工作表对象由用户在代码内通过 Workbook 获取。
- [x] 代码块支持返回 DataFrame、Workbook、Worksheet。
- [x] 代码块支持字典多输出。
- [x] 代码块支持受限 import。
- [x] 代码块面板去掉主表/连接表概念。
- [x] 代码块输入保存切到新 `io_prefs` 模型，不再写旧 `input_bindings`。
- [x] 增加代码块运行结果提示，包含运行中、成功、失败、输出数量和错误详情。
- [x] 完善代码编辑窗口内的测试运行反馈。
- [x] 多输出结果运行后同步更新 `outputs` 和 `io_prefs.outputs`，使画布和预览能识别新增输出。
- [x] 明确 Workbook 输入时没有 return 会默认输出 Workbook。
- [x] 代码块 stdout/stderr 通过引擎日志实时输出，CRPA JSON 运行器、正式执行页和代码编辑窗口均可见。
- [x] DataFrame/普通代码块在独立子进程中支持超时终止，避免用户死循环卡住主程序。
- [x] Workbook/模板代码块改为内存执行，不再跨进程保存临时 xlsx 后重新加载。
- [x] Workbook 上游输入强制内存执行，旧 JSON 手写 `execution_mode: process` 也不会回退到临时 xlsx 跨进程路径。
- [x] Workbook/模板内存执行模式注入 `should_cancel()` / `check_cancel()`，并支持纯 Python 行级超时。
- [x] `should_cancel` / `check_cancel` 已设为保留变量名，避免输入别名覆盖取消函数。
- [x] 增加返回普通类型时的友好错误提示，并说明全局函数内部返回普通值不受影响。

## 待完善任务

### 高优先级

- [x] 将设计态单节点运行彻底异步化；当前单节点运行已改为后台 `WorkflowEngine.start()`。

### 中优先级

- [ ] 增加代码格式化能力。
- [ ] 增加自动补全能力，至少覆盖当前变量、函数空间、常用 pandas/openpyxl 对象。
- [ ] 增加代码语法高亮。
- [ ] 增加代码块运行前的数据规模提示，尤其是大 DataFrame 跨进程执行成本。
- [x] 增加 Workbook 内存执行模式的风险提示和设计态后台运行保护，尤其是用户代码死循环场景。
- [ ] 增加函数库保存和同步的明确状态提示。
- [ ] 为无输入代码块增加模板示例，例如从空 DataFrame 或新 Workbook 开始生成结果。

### 低优先级

- [ ] 将函数空间进一步抽象为项目级函数库，支持跨工作流复用。
- [ ] 增加函数库版本记录，避免多个代码块依赖同名函数时难以追踪。
- [ ] 支持更多安全白名单库，但需要和打包配置一起设计。
- [ ] 增加更完整的沙箱限制和安全审计。
- [ ] 增加代码块单元测试模板，方便用户验证自定义逻辑。

## 设计风险

- DataFrame 输入复制能保护上游数据，但大表会增加内存和耗时。
- Workbook 上游输入走内存执行，性能更适合模板主线；纯 Python 长循环可被行级超时打断，阻塞型 IO/长 sleep 仍无法被线程安全强杀。
- 代码内部自行 `load_workbook()` 的无上游场景仍默认走子进程；这是为了保留超时强杀能力，代价是返回 Workbook 时仍需要跨进程序列化。
- 允许 import 会增加打包和安全边界复杂度，必须维持白名单。
- 函数库越强大，越需要清晰的保存、同步、命名空间和版本提示。
- 函数空间之间如果互相调用，需要保持加载顺序可解释；当前按函数空间列表顺序加载。
- 多输出代码块需要 UI、schema、运行层和预览层保持一致，否则容易出现输出配置和真实返回不一致。

## 建议后续改造顺序

1. 补充大数据、大 Workbook 的运行前规模提示。
2. 完善代码示例、格式化、自动补全和语法高亮。
3. 完善函数库保存状态、项目级函数库和函数版本记录。
4. 评估无上游代码块自行 `load_workbook()` 后返回 Workbook 的高级内存执行模式。
5. 最后补齐代码块单元测试模板、更完整的安全沙箱和审计能力。
