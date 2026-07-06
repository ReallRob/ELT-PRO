# ELT-PRO

ELT-PRO 是一个面向 Excel/CSV 的可视化 ETL 与报表生成工具。它用 PyQt5 提供桌面界面，用 pandas 处理表格数据，用 openpyxl 读写 Excel 模板，目标是让常见的数据清洗、汇总、连接、计算和报表填充流程可以像搭积木一样配置、保存和复用。

项目目前处于研发阶段，已有功能以内部流程验证和业务试用为主。当前版本已经切到显式 `inputs/outputs` 工作流模型，旧 JSON 会在加载时迁移，但新开发优先围绕新模型继续演进。

## 程序组成

项目包含两个主要程序：可视化工作流设计器和独立 CRPA JSON 运行器。

### 可视化工作流设计器

设计器面向流程设计人员、数据处理人员和开发配置人员，用于拖拽算子、连接节点、配置参数并保存工作流 JSON。它把 Excel/CSV 数据处理、表格清洗、汇总计算、模板填充和自定义代码处理组织成可视化流程，解决临时脚本难复用、手工 Excel 操作难交接、流程不可视和参数变更需要改代码的问题。

设计器的优点是流程可视、配置可保存、节点可测试、结果可预览，并且支持通过参数输入和代码块扩展复杂业务逻辑。

### CRPA JSON 运行器

CRPA JSON 运行器面向业务执行人员，用于加载已经设计好的工作流 JSON，根据 `run_manifest` 自动生成文件选择、工作表映射和参数输入界面，然后一键运行完整流程。

运行器的优点是使用门槛低、不会暴露复杂设计能力、适合分发交付，并支持在不同电脑上重新选择文件路径和运行参数。它解决了业务人员运行自动化流程时还需要理解完整设计器、换电脑后路径失效、每次运行都要手工改 JSON 或代码参数的问题。

## 主要能力

- 可视化工作流设计：左侧工具箱、中间画布、右侧配置面板、底部数据预览。
- 显式输入输出：节点通过 `source_node_id + source_output_id` 引用上游结果，不再依赖表名猜测。
- 工作流 JSON 保存与导入：保存算子、连线、参数、文件路径、CRPA 元信息和运行清单。
- 执行模式：加载工作流、修正文件路径、运行全量流程、查看日志和结果预览。
- CRPA JSON 运行器：独立入口，面向业务人员，只需要选择 JSON、选择文件、填写参数并运行。
- 参数输入：支持运行参数、参数映射、文件/文件夹参数、引用参数，以及在代码算子中通过 `param()` 使用参数。
- Excel 模板处理：导入模板、写入同一个内存 Workbook、保存完整 xlsx 文件。
- 用户代码能力：公式计算支持代码模式；代码块支持无输入、多 DataFrame、Workbook、函数空间、受限 import、多输出和最长 1 小时超时控制。
- 性能辅助：节点级耗时日志、大表验证脚本、预览缓存和模板预览截断策略。

## 算子分类

当前工具箱包含以下类型的算子：

- 参数控制：高级参数输入与映射。
- 输入输出：数据源导入、自动导出。
- 数据变换：提取列、数据筛选、多级排序、数据清洗、去重、抽样、转置。
- 汇总统计：分组汇总、数据透视、逆透视、描述统计。
- 表操作：表连接、纵向拼接。
- 计算列：数据排名、公式计算、累加计算、环比计算。
- 模板处理：加载模板、写入模板、保存模板。
- 高级能力：代码块。

## 运行环境

建议使用 Python 3.9+。当前桌面界面基于 PyQt5，数据处理依赖 pandas、numpy、openpyxl。

```bash
pip install pyqt5 pandas numpy openpyxl xlrd
```

如果在 Linux 上运行 PyQt5，需要确保系统已经安装 Qt 所需的图形库和平台插件依赖。不同发行版的包名会有差异，常见问题表现为 Qt 平台插件无法加载或窗口启动后异常退出。

## 启动方式

启动主程序：

```bash
python main.py
```

启动独立 CRPA JSON 运行器：

```bash
python -m crpa_launcher.main
```

也可以直接传入工作流 JSON：

```bash
python -m crpa_launcher.main path/to/workflow.json
```

## 工作流设计流程

1. 在设计模式中从左侧工具箱拖入算子。
2. 在画布中连接算子，形成数据流。
3. 点击节点，在右侧配置面板设置数据源、规则、输出名和参数。
4. 使用“运行当前节点”测试当前节点及其上游依赖，使用“应用配置”保存当前面板参数。
5. 在底部预览区检查中间结果或模板预览。
6. 导出工作流 JSON，用于后续执行或分发给其他人员。

## 工作流 JSON 与路径迁移

工作流 JSON 中会保存原始文件路径，但不同电脑上的路径通常不同。为了解决这个问题，JSON 中会附带 `run_manifest`，把运行所需资源拆成：

- `file_resources`：数据源文件、模板文件、输出文件。
- `data_sources`：数据源与工作表的关系。
- `parameters`：运行时需要填写的业务参数。

在执行模式或 CRPA JSON 运行器中，用户可以重新选择文件路径并填写运行参数。参数支持文本、数字、日期、布尔、文件和文件夹等类型。启用写回后，新的路径和参数会保存回 JSON，避免每次运行都重新选择。

当前新模型中，每个节点的核心协议是：

```json
{
  "inputs": [
    {
      "input_id": "in_1",
      "source_node_id": "node_a",
      "source_output_id": "out_1",
      "name": "上游结果",
      "role": "current",
      "data_type": "table",
      "enabled": true
    }
  ],
  "outputs": [
    {
      "output_id": "out_1",
      "name": "当前结果",
      "data_type": "table"
    }
  ]
}
```

配置面板保存轻量 `io_prefs`，正式 `inputs/outputs` 由 `core/workflow/schema.py` 统一生成。

## CRPA 集成字段

导出的工作流 JSON 支持以下 CRPA 相关字段：

```json
{
  "crpa": {
    "code": "9999",
    "name": "代号名称"
  },
  "run_manifest": {
    "file_resources": [],
    "data_sources": [],
    "parameters": []
  }
}
```

CRPA JSON 运行器会根据 `run_manifest` 自动生成文件选择框、工作表映射和参数输入框。当前版本不会实现真实 CRPA 类，只会在运行时打印 CRPA payload，并继续执行工作流。代码块的 `timeout_seconds` 会随工作流 JSON 生效，默认 10 秒，最大 3600 秒。

## Excel 模板写入

模板现在按“模板主线”运行，目标是在内存里保持同一个 Workbook：

```text
加载模板 -> 写入模板 -> 写入模板/代码块 -> 保存模板
```

- 加载模板：读取 xlsx 模板文件，输出一个 workbook。
- 写入模板：接收一个 workbook 和一个 DataFrame，原地写入同一个 workbook，并继续输出这个 workbook。
- 保存模板：接收 workbook 并保存为完整 xlsx。
- 代码块也可以接入 workbook，对 `wb` 或 `ws` 做自定义写入，再输出同一个 workbook。

模板写入使用 openpyxl。默认尽量保留模板目标区域已有格式，最终结果以保存的 xlsx 文件为准。

## 代码模式与代码块

公式计算算子支持普通公式和代码模式。代码块是更高级的自定义算子，当前支持：

- 无输入运行：可以直接创建 DataFrame 或 Workbook 并返回。
- 多 DataFrame 输入：默认变量名为 `df`、`df1`、`df2`，也可以在面板中自定义。
- Workbook 输入：默认变量名为 `wb`、`wb1`，可配置 `ws` 工作表变量。
- 函数空间：代码编辑窗口支持多个函数空间，可按命名空间组织公共函数。
- 受限 import：允许 import 已打包且白名单中的库，例如 pandas、numpy、openpyxl、re、math、datetime、copy。
- 多输出：推荐使用字典返回，key 是输出名称，value 决定输出类型。
- 运行反馈：编辑窗口和状态栏会显示运行中、成功、失败、输出数量和错误详情。
- 超时控制：代码块在独立执行进程中运行，默认 10 秒，最大 3600 秒；超时后会终止执行进程。

示例：

```python
summary_df = df.groupby("部门", as_index=False)["金额"].sum()

ws = wb["汇总"]
for i, row in summary_df.iterrows():
    ws.cell(row=i + 2, column=1).value = row["部门"]
    ws.cell(row=i + 2, column=2).value = row["金额"]

return {
    "汇总表": summary_df,
    "写入后模板": wb,
}
```

代码块通过返回值类型区分输出：

- `pandas.DataFrame` -> `table`
- `openpyxl.Workbook` -> `workbook`
- `openpyxl.Worksheet` -> 自动取所属 workbook 输出
- `dict[str, DataFrame/Workbook/Worksheet]` -> 多输出

函数空间内部可以返回普通值；需要输出给下游工作流时，当前代码的 `return` / `result` 应是 DataFrame、Workbook、Worksheet 或它们组成的字典/列表；没有输出也允许运行。

代码块会在独立子进程中执行。DataFrame 通过进程序列化传输；Workbook 会先保存为临时 xlsx 文件，子进程加载后执行代码，输出 Workbook 时再保存为临时 xlsx 并由主进程重新加载。这个设计让 Workbook 代码块也能按超时时间终止，同时保持“加载模板 -> 代码块 -> 保存模板”的模板主线语义。

## 打包说明

项目可以用 PyInstaller 打包。推荐先使用 `onedir`，比 `onefile` 更适合 PyQt、pandas、numpy、openpyxl 和代码块子进程场景。

```powershell
pyinstaller main.py `
  --name 文档处理助手 `
  --onedir `
  --windowed `
  --clean `
  --collect-all pandas `
  --collect-all numpy `
  --collect-all openpyxl `
  --collect-all PyQt5
```

CRPA JSON 运行器可以用同一套依赖单独打包入口：

```powershell
pyinstaller crpa_launcher/main.py `
  --name CRPA-JSON运行器 `
  --onedir `
  --windowed `
  --clean `
  --collect-all pandas `
  --collect-all numpy `
  --collect-all openpyxl `
  --collect-all PyQt5
```

两个 exe 放在同一目录下时会共用 `config/` 目录，但配置文件已经区分：主程序写入 `config/workspace_config.json`，CRPA 运行器写入 `config/crpa_launcher_config.json`。CRPA 运行器首次启动时会兼容读取旧 `workspace_config.json` 中的 `crpa_launcher` 段，后续保存只写自己的配置文件。

代码块允许动态 import，因此新增允许导入的第三方库时，需要同时：

1. 在 `core/dataframe_ops/code_exec.py` 的 `_ALLOWED_IMPORT_ROOTS` 增加根模块名。
2. 如果是第三方库，在 PyInstaller 命令或 `.spec` 中增加对应 `--collect-all 包名`。标准库如 `os`、`sys` 不需要额外收集。
3. 更新代码块说明页提示和 `CODE_BLOCK_TASKS.md`。

打包后的目标电脑通常不需要单独安装 Python，但需要复制整个 `dist/文档处理助手` 目录。

## 文档入口

- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)：项目结构、职责边界和当前执行模型。
- [DECOUPLING_TASKS.md](DECOUPLING_TASKS.md)：工作流参数模型与架构解耦任务记录。
- [CODE_BLOCK_TASKS.md](CODE_BLOCK_TASKS.md)：代码块设计约定、已完成和待完善事项。
- [PERFORMANCE_OPTIMIZATION_TASKS.md](PERFORMANCE_OPTIMIZATION_TASKS.md)：性能优化范围、基线脚本和大数据使用建议。

## 目录结构

```text
.
├── main.py                         # 主程序入口，包含设计模式和执行模式
├── engine.py                       # 工作流执行线程，负责参数解析、运行存储、输出发布和内存释放
├── workspace_context.py            # 设计态上下文和数据池管理
├── node_editor.py                  # 画布节点与连线
├── operator_registry.py            # 算子注册表
├── template_engine.py              # Excel 模板导入、预览、写入和保存
├── parameter_resolver.py           # 参数与映射解析
├── core/
│   ├── dataframe_ops/              # pandas/openpyxl 数据处理与代码执行
│   ├── parameters/                 # 参数映射 schema
│   ├── workflow/                   # 显式输入输出模型、算子类、运行存储和 schema
│   └── manifest_builder.py         # run_manifest 构建
├── operators/
│   ├── base_panel.py               # 算子配置面板基类
│   └── panels/                     # 各类算子配置面板
├── ui/
│   ├── design/                     # 设计模式 UI
│   ├── execute/                    # 执行模式 UI
│   └── dialogs/                    # 路径重映射等弹窗
├── crpa_launcher/                  # 独立 CRPA JSON 运行器
└── tools/                          # 性能基线和大数据验证脚本
```

## 开发说明

- 配置文件、测试工作流、导出结果和本地路径文件不应作为通用项目文件提交。
- 新增算子时，优先把数据处理逻辑放入 `core/dataframe_ops/`，把运行类放入 `core/workflow/operators.py`，把配置面板放入 `operators/panels/`，再在 `operator_registry.py` 注册。
- UI 面板应保存用户意图和轻量 `io_prefs`，不要直接承担正式 `inputs/outputs` 生成职责。
- 修改 UI 后建议至少运行一次主程序，并执行一次 `python -m py_compile` 或基础导入检查。
- 大数据性能优化应先跑 `tools/performance_baseline.py` 或 `tools/validate_large_dataframe_ops.py` 建立基线。

## 当前限制

- 大型 Excel 模板预览会按 sheet 和范围截断，完整结果以保存的 xlsx 为准。
- 用户代码和代码块需要跨进程传输 DataFrame 或临时 xlsx 文件，大表和大型模板会增加内存、磁盘 IO 和运行时间。
- Workbook 代码块通过临时 xlsx 文件跨进程传输，不依赖主进程对象原地修改；代码块输出的 workbook 会作为新的工作流输出继续传给下游节点。
- 受限 import 只允许白名单库，新增第三方库需要同时调整白名单和打包配置。
- 项目仍在打磨配置面板、运行器体验、工作流校验规则和自动化测试覆盖。
