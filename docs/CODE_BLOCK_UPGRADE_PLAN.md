# 代码块升级计划

本文档定义代码块编辑框的下一轮升级范围、实现方式、改动边界和验收标准。目标是让代码块具备可读、可编辑、可直接粘贴既有 Python 代码的基础体验，同时保持工作流保存、分发和运行行为一致。

## 结论

本轮按以下顺序实施：

1. [已完成] 为当前代码和函数空间编辑器增加 Python 语法高亮。
2. [已完成] 将函数空间按单一引用名称发布为受控的虚拟 Python 模块，兼容 `from fun import *`、`from fun import name` 和 `import fun as f`。
3. [部分完成] 已增加编辑器行号；后续补齐当前行高亮、查找替换和基础格式化入口。
4. 完成导入兼容、编辑器行为和工作流保存/加载的自动化测试。
5. [已完成] 增加“独立进程运行”模式，支持 PyQt 子窗口、参数快照和停止时终止子进程。

其中，`from fun import *` 的含义是从引用名称为 `fun` 的函数空间导入，不是允许代码块从任意磁盘路径或用户电脑上的任意 `fun.py` 导入。这样才能保证工作流保存、分发、独立运行和 PyInstaller 打包后的行为一致。

## 现状与问题

当前实现已经具备以下能力：

- `operators/panels/code_block_panel.py` 中的 `PythonCodeEditor` 基于 `QPlainTextEdit`，支持自动缩进、Tab 缩进、Shift+Tab 反缩进和缩进区块退格。
- 当前代码和函数空间共用这个编辑器，但没有 `QSyntaxHighlighter`，所以所有代码以单一文字颜色显示。
- `core/dataframe_ops/code_exec.py` 会依次执行启用的函数空间，并以受控虚拟模块注入到当前代码环境，例如 `date_utils.month_end()`。
- `_code_block_import()` 优先解析函数空间引用名称，其余绝对导入交给 Python 解释器按正常规则处理。
- 函数空间、当前代码和运行状态已能随工作流保存和恢复，升级不应改变既有 JSON 的基本字段语义。

## 范围

### 本轮必须完成

- Python 关键字、字符串、注释、数字、内置对象和预置变量的语法高亮。
- 当前代码页与函数库页使用相同的高亮和编辑行为。
- 函数空间可被当前代码和后续函数空间作为虚拟模块导入。
- 函数空间只保留一个引用名称；将引用名称设为 `fun` 后，已存在的 `from fun import *` 代码无需手动删除或改写。
- 对缺失引用名称、重复引用名称、循环依赖和不支持的相对导入给出明确错误。
- 为新增行为补充自动化测试。

### 本轮不做

- 不自动向 `sys.path` 添加任意本地目录、用户主目录或网络路径。
- 不自动猜测或复制 PyCharm 项目外的 `fun.py`。
- 不在编辑器内实现完整 IDE 级调试器、静态类型检查或第三方 LSP。
- 不改变默认 `inline` 模式的执行方式和输出协议；`process` 是显式启用的独立运行模式。动态依赖由打包预收集清单管理，不限制运行时正常 import。

### 独立进程模式

- 编辑窗口勾选“独立进程运行”后保存 `execution_mode: process`。
- 子进程以 `__name__ == "__main__"` 执行，可创建自己的 `QApplication` 并调用 `app.exec_()`。
- 子进程接收 `params`、`mappings`、`param()`、共享 `state` 和 DataFrame 输入副本；日志、异常和返回值通过进程队列回传。
- 停止时先同步 `state['run_status'] = 'stopped'`；代码可用 `should_cancel()` / `check_cancel()` 协作退出，超出短暂宽限后才强制终止。
- 内存 Workbook 输入会被拒绝；关闭子窗口或点击停止后，子进程结束。

## 一、语法高亮

### 技术选择

优先使用 PyQt5 自带的 `QSyntaxHighlighter`，不增加 Pygments 等运行时依赖。项目当前以 PyQt5 5.11.x 为兼容基线；使用 Qt 自带能力可以避免打包时新增动态依赖，也能在主程序和 CRPA 运行器中保持一致。

### 高亮规则

第一版覆盖 Python 的高价值语法元素：

- 关键字：`def`、`class`、`return`、`if`、`for`、`try`、`import`、`from`、`as`、`with`、`lambda` 等。
- 内置对象和异常：`len`、`range`、`print`、`dict`、`list`、`ValueError`、`Exception` 等。
- 字符串、三引号多行字符串、转义字符、注释、数字和装饰器。
- 函数定义中的函数名、类定义中的类名。
- 代码块预置变量：`df`、`dfs`、`wb`、`wbs`、`params`、`param`、`state`、`should_cancel`、`check_cancel`、`pd`、`np`、`openpyxl`。
- 已启用函数空间的引用名称，例如 `date_utils`、`fun`。

高亮器只负责显示，不修改编辑器文本，也不参与代码执行。多行字符串必须使用 `setCurrentBlockState()` 保持跨行状态，避免滚动和局部刷新后颜色错乱。

### 需要改动的文件

| 文件 | 改动 |
| --- | --- |
| `operators/panels/code_block_panel.py` | 已实现 `PythonSyntaxHighlighter` 并挂接到 `PythonCodeEditor`；当前代码和函数空间因此自动获得高亮。动态函数空间引用名称高亮留待后续增强实现。 |
| `tests/test_code_block_highlighter.py`（新增） | 已覆盖关键字、预置变量、注释、普通字符串和三引号多行字符串的格式范围。 |

如果项目暂时没有测试目录，先建立 `tests/` 并使用标准库 `unittest`，避免为了 UI 测试额外引入测试框架。

### 验收标准

- 当前代码页和函数库页的 Python 代码不再以纯文本单色显示。
- 输入、滚动、撤销/重做和切换函数空间时没有明显卡顿或文本跳动。
- 三引号字符串跨多行时颜色连续；结束引号后的后续代码恢复正常颜色。
- 编辑器内容、保存结果和运行结果与升级前一致。

## 二、兼容 `from fun import *`

### 兼容目标

以下写法应可用，前提是工作流中存在启用的函数空间，且其引用名称为 `fun`：

```python
from fun import *
result = normalize_name("示例")
```

```python
from fun import normalize_name
result = normalize_name("示例")
```

```python
import fun as f
result = f.normalize_name("示例")
```

同时保留当前推荐的命名空间调用：

```python
result = text_utils.normalize_name("示例")
```

`import *` 只作为既有 PyCharm 代码的兼容入口。新建代码仍建议使用 `import fun as f` 或显式导入名称，能避免函数名冲突，也更容易阅读来源。

### 设计方案

函数空间会被转换成 `ModuleType` 并注入执行环境。Python 的 `import` 语句不能直接从普通变量导入，因此需要在每一次代码块运行时建立独立的“虚拟模块注册表”。

每个启用函数空间只保留一个引用名称：

- `namespace`：现有内部字段，界面显示为“引用名称”；它同时用于 `text_utils.normalize_name()` 这种属性调用和 Python import。

执行时先注册全部引用名称，再按 `from` 依赖顺序处理：

1. 创建本次运行专用的模块注册表，不写入进程全局 `sys.modules`。
2. 解析空间间的 `from` 依赖，并优先执行被引用空间，再筛选出可公开的函数、类和常量。
3. 用 `types.ModuleType` 生成虚拟模块，为其写入公开成员和明确的 `__all__`。
4. 用空间的唯一引用名称注册该模块。
5. 后续函数空间和当前代码的 `__import__` 先查询本次运行的虚拟模块注册表；命中后返回虚拟模块，未命中时再走 Python 的正常导入机制。
6. `from fun import *` 按该模块的 `__all__` 导入公开成员；私有名、执行环境变量和控制函数不进入 `__all__`。

这种实现无需把函数空间落成 `.py` 文件，也不会污染不同工作流或并发运行之间的模块状态。

### 错误与边界

- `fun` 没有对应的启用函数空间时：提示“未找到函数空间引用 fun；请将目标空间的引用名称设置为 fun”。
- 两个函数空间使用同一个引用名称时：保存和运行前校验直接失败，并指出冲突的空间名称。
- 引用名称与预置模块冲突，例如 `pandas`、`openpyxl`：拒绝保存，避免导入语义被覆盖。
- 函数空间引用后置空间：单向 `from` 依赖会自动排序；循环 `from` 依赖提示改用普通 `import` 后在函数体内调用。
- 函数空间导入自身：不作为支持场景，提示移除自导入。函数空间本身就是该引用名称模块的定义来源，自导入不会带来任何成员。
- 从 PyCharm 复制的代码若依赖真实外部文件 `fun.py`，仅复制调用代码并不能恢复缺失函数。需要将 `fun.py` 的公共定义粘入函数空间，或后续单独设计“受管项目库”功能。

### 需要改动的文件

| 文件 | 改动 |
| --- | --- |
| `operators/panels/code_block_panel.py` | 将“命名空间”显示为“引用名称”；一个函数空间只有一个引用名称，保存时会移除旧 `import_aliases` 字段。 |
| `core/dataframe_ops/code_exec.py` | 将公开成员转换为 `ModuleType`；构建本次运行独有的模块注册表；只按引用名称注册模块；让 `_code_block_import()` 优先解析虚拟模块，再交给 Python 处理正常导入。 |
| `core/dataframe_ops/code_block.py` | 仅在接口说明中补充可导入函数库模块，无需改变参数协议。 |
| `workspace_context.py`、`engine.py`、`ui/design/workflow_io.py` | 检查深拷贝、保存和恢复函数空间时不会保留废弃的 `import_aliases` 字段。 |
| `docs/CODE_BLOCK_TASKS.md` | 将该能力从待办转为已完成，并链接本计划和用户使用示例。 |
| `tests/test_code_block_function_imports.py` | 覆盖 `from fun import *`、显式成员导入、模块导入、重复引用名称、缺失引用名称和非预收集模块导入。 |

### 安全要求

- 虚拟模块只来自工作流 JSON 内的函数空间，不从磁盘动态扫描。
- 不允许引用名称覆盖保留变量或打包预收集模块，避免虚拟模块覆盖常用导入。
- `_code_block_import()` 拒绝相对导入；绝对导入遵循当前 Python 环境的可见模块和 `sys.path`。
- 模块注册表必须是单次执行局部对象，不能向全局 `sys.modules` 写入 `fun`，避免不同任务互相污染。

### 验收标准

- 将引用名称设为 `fun` 后，现有 `from fun import *` 代码无需修改即可在当前代码页运行。
- `from fun import name`、`import fun as f` 与既有 `引用名称.name()` 均可用。
- 工作流保存、重新打开、设计态单节点运行、完整工作流运行和 CRPA JSON 运行器的表现一致。
- 未安装或不可见的模块仍按 Python 标准错误报错；默认预收集模块的导入行为不回退。

## 三、编辑体验补齐

语法高亮完成后，按收益从高到低继续实现以下能力。

### 第一优先级

- [已完成] 行号区：在编辑器左侧绘制稳定宽度的行号栏，行数增加、滚动或字体变化时自动更新。
- 当前行高亮：弱对比色提示光标所在行，不覆盖语法颜色和文本选择色。
- 查找与替换：使用 `Ctrl+F` 打开查找栏，支持下一个/上一个、大小写、整词和替换当前/全部。
- 转到行：使用 `Ctrl+G` 定位长脚本行号，并使光标滚动到可视区域。
- 括号匹配：光标位于 `()[]{}` 之一时显示配对位置；仅做显示，不自动改写代码。

建议继续放在新增的 `python_code_editor.py` 中，避免把编辑器基础设施继续堆入 `CodeEditorDialog`。

### 第二优先级

- 格式化：弹窗工具栏增加“格式化”按钮。优先集成可选的 `black`；未安装时显示可理解提示，不影响运行。格式化前后保留光标位置并作为一次撤销操作。
- 最小补全：无需引入完整 LSP。输入 `.` 时为 `df`、`pd`、`np`、`wb` 和函数空间命名空间显示静态候选；函数空间候选来自已解析的 `def` 名称。
- 错误定位：运行失败时从 traceback 提取代码块行号，点击错误信息后定位到当前代码或函数空间的对应行。
- 代码片段：保留现有说明页插入能力，并补充“导入函数库”“DataFrame 返回”“Workbook 返回”“取消检查”等片段。

格式化和自动补全涉及可选依赖与更多交互状态，应在语法高亮、函数库导入和基础测试稳定后再做。

## 四、实施顺序

| 阶段 | 目标 | 主要文件 | 完成条件 |
| --- | --- | --- | --- |
| 0 | 建立回归基线 | `tests/test_code_exec.py` | 固化当前 import 白名单、函数空间顺序、输出协议和 JSON 保存行为。 |
| 1 | 接入语法高亮（已完成） | `code_block_panel.py`、`tests/test_code_block_highlighter.py` | 当前代码和函数库均有高亮，原有缩进行为不回退。 |
| 2 | 发布虚拟函数模块（已完成） | `core/dataframe_ops/code_exec.py`、`code_block_panel.py`、`tests/test_code_block_function_imports.py` | `from fun import *`、显式导入和模块导入通过，安全边界仍有效。 |
| 3 | 保存和跨入口回归 | `workspace_context.py`、`engine.py`、`workflow_io.py` | 设计器、完整运行和 CRPA 运行器均能恢复引用名称。 |
| 4 | 编辑效率能力（进行中） | `code_block_panel.py` | 行号已完成；待增加查找替换、转到行和错误定位。 |
| 5 | 可选增强 | 格式化/补全相关模块 | 在不强制新增运行依赖的前提下逐步启用。 |

阶段 0 到阶段 3 是一个可独立发布的版本。阶段 4 和阶段 5 不应阻塞 `from fun import *` 的兼容需求。

## 五、测试清单

### 执行层

- 函数空间的 `引用名称.name()` 调用保持可用。
- `from fun import *` 可访问函数、类和显式公开常量。
- `from fun import one_name` 和 `import fun as f` 正常工作。
- 多个函数空间之间可跨引用名称导入；单向 `from` 依赖不受列表顺序限制。
- 需要双向调用时，可使用 `import 引用名称` 并在函数体内调用。
- 禁用空间不可导入。
- 缺失引用名称、重复引用名称、引用名称与预置库冲突均有稳定错误信息。
- 缺失模块按 Python 标准错误提示；相对 import 不受支持，且不会自动添加任意路径到 `sys.path`。
- DataFrame、Workbook、普通返回值、多输出和无 `return` 的既有行为不回退。

### UI 层

- 当前代码页、函数库页都能正确高亮 Python 代码。
- 切换函数空间、修改引用名称后高亮立即更新。
- Tab、Shift+Tab、回车自动缩进、退格缩进、撤销/重做保持正常。
- 修改函数空间后保存、重新打开工作流，引用名称保持稳定，废弃的 `import_aliases` 会被移除。
- 函数空间校验能在运行前指出引用名称冲突和无效引用名称。

### 打包与回归

- 运行 `python -m py_compile operators/panels/python_code_editor.py operators/panels/code_block_panel.py core/dataframe_ops/code_exec.py`。
- 在开发环境中执行代码块单元测试。
- 打包前后分别验证 `from fun import *`。虚拟函数模块不需要增加 PyInstaller hidden import；新增第三方格式化或补全依赖时才需要同步更新 `main.spec` 和 `crpa_launcher.spec`。

## 六、使用方式（升级完成后）

1. 在“函数库”中新建或选择一个函数空间。
2. 填写空间名称和引用名称，例如 `fun`。
3. 保存函数，例如：

```python
def normalize_name(value):
    return str(value).strip().upper()
```

4. 在“当前代码”中直接粘贴既有代码：

```python
from fun import *

df["名称"] = df["名称"].map(normalize_name)
return df
```

5. 对新代码，优先写成更明确的形式：

```python
import fun as f

df["名称"] = df["名称"].map(f.normalize_name)
return df
```

## 七、风险与决策

- `import *` 会引入同名覆盖风险，因此只作为兼容路径；界面要持续推荐显式导入或命名空间调用。
- 函数空间加载有顺序，跨空间依赖必须可见。后续可增加依赖图，但本轮先以列表顺序和清晰报错控制复杂度。
- 不能把任意本地 `fun.py` 自动加入 `sys.path` 来换取“直接可用”，否则工作流在别的电脑、CRPA 运行器或打包版中会失效。
- 代码复制的“拿来就用”依赖目标环境已安装所需模块；打包版还需要把第三方包加入预收集清单。

## 完成定义

当以下条件同时满足时，本轮升级完成：

- 编辑器有正确、稳定的 Python 语法高亮。
- 用户把函数空间引用名称设为 `fun` 后，可直接运行 `from fun import *` 的既有代码。
- 所有导入仍受控，不支持任意路径导入。
- 设计器、完整工作流、CRPA 运行器和打包版行为一致。
- 自动化测试覆盖主要成功路径和拒绝路径，且现有代码块功能没有回归。
