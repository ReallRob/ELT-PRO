# RPA_json

RPA_json 是一个面向 Excel/CSV 的可视化 ETL 与报表生成工具。它用 PyQt5 提供桌面界面，用 pandas 处理表格数据，用 openpyxl 读写 Excel 模板，目标是让常见的数据清洗、汇总、连接、计算和报表填充流程可以像搭积木一样配置、保存和复用。

项目目前处于研发阶段，已有功能以内部流程验证和业务试用为主。当前版本已经切到显式 `inputs/outputs` 工作流模型，旧 JSON 会在加载时迁移，但新开发优先围绕新模型继续演进。

## 程序组成

项目包含两个主要程序：`RPA_json设计器` 和 `RPA_json运行器`。

### RPA_json设计器

面向流程设计人员、数据处理人员和开发配置人员。通过拖拽节点、连接数据流、配置文件和参数，将 Excel/CSV 清洗、汇总计算、模板填充和自定义代码组织为可保存、可复用的工作流 JSON。

适用于搭建、测试和发布自动化数据流程：流程可视、配置可保存、节点可测试、结果可预览，并支持参数输入和代码块扩展复杂业务逻辑。

### RPA_json运行器

面向业务执行人员。加载设计器发布的工作流 JSON 后，根据 `run_manifest` 自动生成文件选择、工作表映射和参数输入界面，再按配置一键执行流程。

适用于交付和日常运行：不暴露复杂设计能力，支持在不同电脑上重新选择文件路径、填写运行参数、查看运行日志和管理本地 JSON 历史记录。

## 主要能力

- 可视化工作流设计：左侧工具箱、中间画布、右侧配置面板、底部数据预览。
- 显式输入输出：节点通过 `source_node_id + source_output_id` 引用上游结果，不再依赖表名猜测。
- 工作流 JSON 保存与导入：保存算子、连线、参数、文件路径、CRPA 元信息和运行清单。
- 执行模式：加载工作流、修正文件路径、运行全量流程、查看日志和结果预览。
- RPA_json运行器：独立入口，面向业务人员，只需要选择 JSON、选择文件、填写参数并运行。
- 参数输入：支持运行参数、参数映射、文件/文件夹参数、引用参数，以及在代码算子中通过 `param()` 使用参数。
- Excel 模板处理：导入模板、写入同一个内存 Workbook、保存完整 xlsx 文件。
- 用户代码能力：公式计算支持代码模式；代码块支持无输入、多 DataFrame、内存 Workbook、工作流级函数空间、正常 Python import、多输出，以及协作停止或可选独立进程运行。
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

建议使用 Python 3.9+。当前桌面界面以 PyQt5 5.11.x 为兼容基线，数据处理依赖 pandas、numpy、openpyxl。新增 UI 代码应避免使用 PyQt5 5.12/5.15 才提供的 API。

```bash
pip install "PyQt5==5.11.3" pandas numpy openpyxl xlrd
```

如果在 Linux 上运行 PyQt5，需要确保系统已经安装 Qt 所需的图形库和平台插件依赖。不同发行版的包名会有差异，常见问题表现为 Qt 平台插件无法加载或窗口启动后异常退出。

## 启动方式

启动主程序：

```bash
python main.py
```

启动 RPA_json运行器：

```bash
python -m crpa_launcher.main
```

也可以直接传入工作流 JSON：

```bash
python -m crpa_launcher.main path/to/workflow.json
```

## RPA_json运行器使用

1. 点击“选择 JSON”或在左侧历史记录中点击卡片的非编辑区域加载工作流。
2. JSON 加载成功后会立即登记到左侧历史记录，并按最近加载时间置顶；此时显示“运行 0 次”，不会因为加载而增加次数。
3. 左侧搜索框使用包含匹配，同时搜索历史名称、标签和 CRPA 代码，不需要选择额外的匹配模式。
4. 名称和标签右侧的铅笔图标是唯一的编辑入口。名称仅修改该电脑上的历史显示名称，不会改写工作流 JSON 内的 CRPA 名称；标签同样保存在本地历史配置中。
5. 点击“运行”并通过当前配置校验后，运行次数才会加 1。仅浏览历史、加载 JSON、编辑名称或标签、校验失败以及写回失败都不会增加次数。

历史记录保存在 CRPA 运行器自己的配置文件中，可随时删除单条记录；删除记录不会删除对应的 JSON 文件。

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

在执行模式或 RPA_json运行器中，用户可以重新选择文件路径并填写运行参数。参数支持文本、数字、日期、布尔、文件和文件夹等类型。启用写回后，新的路径和参数会保存回 JSON，避免每次运行都重新选择。

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

RPA_json运行器会根据 `run_manifest` 自动生成文件选择框、工作表映射和参数输入框。当前版本不会实现真实 CRPA 类，只会在运行时打印 CRPA payload，并继续执行工作流。代码块配置中的 `timeout_seconds` 会保存在工作流 JSON 中，并被限制在 1 至 3600 秒；当前运行时不使用它自动中断代码，停止依赖运行状态的协作检查或独立进程终止。

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
- Workbook 输入：默认变量名为 `wb`、`wb1`；在代码中通过 `wb.active` 或 `wb["工作表名"]` 获取工作表。
- 函数空间：代码编辑窗口支持多个工作流级函数空间，可按命名空间组织公共函数，并使用普通 Python `import` / `from ... import ...` 引用。
- import：代码块使用正常 Python import，开发环境可导入当前解释器已安装且可见的模块。打包版只保证仓库打包清单中预收集的动态依赖可用；其他第三方包需要加入打包清单。
- 多输出：推荐使用字典返回，key 是输出名称，value 决定输出类型。
- 运行反馈：编辑窗口和状态栏会显示运行中、成功、失败、输出数量和错误详情。
- 停止机制：默认运行会将共享 `state['run_status']` 设为 `stopped`；长循环应调用 `check_cancel()` 或检查 `should_cancel()`。独立进程模式在短暂等待协作退出后会终止子进程。

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
- `dict[str, DataFrame/Workbook/Worksheet]`，或由这些对象组成的 `list` / `tuple` -> 多输出
- 普通显式返回值 -> 自动包装成单个 DataFrame 输出

函数空间内部可以返回普通值；需要输出给下游工作流时，当前代码必须显式 `return`。没有 `return` 时允许运行，但不会产生正式输出。

代码块默认在 `WorkflowEngine` 的后台线程中执行。每个 DataFrame 输入会先复制，以隔离用户代码对上游表的修改；Workbook 则保留内存对象，适合“加载模板 -> 代码块 -> 保存模板”的模板主线。勾选“独立进程运行”后，代码会在 `spawn` 子进程中执行，DataFrame 会被序列化传入，`print()` 和 stderr 会实时回传；该模式不支持内存 Workbook 输入，适合需要独立 GUI 事件循环或难以协作停止的脚本。

## 打包说明

项目可以用 PyInstaller 打包。推荐先使用 `onedir`，比 `onefile` 更适合 PyQt、pandas、numpy、openpyxl 和代码块子进程场景。

裸命令 `pyinstaller -F -w main.py` 不会自动收集只出现在用户代码字符串里的动态 import。优先使用仓库里的 spec 文件打包；它会读取 `config/dynamic_imports.json`，为预收集清单中属于当前构建目标的包加入 hiddenimports/collect-all，并按当前构建 Python 自动收集运行时标准库（Windows 和 Linux 分别按各自环境收集，排除测试和开发工具）。设计器的“打包依赖”页可保存清单并覆盖生成对应 spec：

```powershell
pyinstaller main.spec --clean
pyinstaller crpa_launcher.spec --clean
```

`main.spec` 生成目录版 `dist/RPA_json设计器/`，启动
`dist/RPA_json设计器/RPA_json设计器.exe`。请分发整个 `dist/RPA_json设计器/`
目录；目录版不会在每次启动时解压 100MB 以上的运行库，启动速度明显优于单文件 exe。
`crpa_launcher.spec` 同样生成目录版 `dist/RPA_json运行器/`，启动
`dist/RPA_json运行器/RPA_json运行器.exe`。

对于只能兼容 Python 3.7 的旧设备，保留了 RPA_json运行器的单文件配置
`crpa_json_py37_onefile.spec`。必须在与目标设备架构一致的 Python 3.7 环境中
构建，因为 PyInstaller 会嵌入构建时的 Python 解释器：

```powershell
py -3.7-32 -m pip install -r crpa_launcher/requirements-py37-32.txt
py -3.7-32 -m PyInstaller crpa_json_py37_onefile.spec --clean --noconfirm
```

该命令生成单个 `dist/RPA_json运行器.exe`。单文件启动会比目录版慢，因为每次启动都要
解压运行库；它的作用是兼容旧设备的部署方式，不替代普通设备使用的目录版。

如果仍使用命令行直打入口文件，需要给新增库手动加参数，例如 `--collect-all 包名` 或 `--hidden-import 包名`。

```powershell
pyinstaller main.py `
  --name RPA_json设计器 `
  --onedir `
  --windowed `
  --clean `
  --collect-all pandas `
  --collect-all numpy `
  --collect-all openpyxl `
  --collect-all PyQt5
```

RPA_json运行器可以用同一套依赖单独打包入口：

```powershell
pyinstaller crpa_launcher/main.py `
  --name RPA_json运行器 `
  --onedir `
  --windowed `
  --clean `
  --collect-all pandas `
  --collect-all numpy `
  --collect-all openpyxl `
  --collect-all PyQt5
```

两个 exe 放在同一目录下时会共用 `config/` 目录，但配置文件已经区分：RPA_json设计器写入 `config/workspace_config.json`，RPA_json运行器写入 `config/crpa_launcher_config.json`。RPA_json运行器首次启动时会兼容读取旧 `workspace_config.json` 中的 `crpa_launcher` 段，后续保存只写自己的配置文件。

代码块允许正常 Python import。新增第三方库时，在设计器的“打包依赖”页添加根模块、发行包、构建目标，并选择交付方式：

1. `内置到程序`：默认方式。依赖会写入 `config/dynamic_imports.json`，点击“生成 Spec”或“开始打包”后由 `collect_all` 收集进 exe。适用于 PyQt5、pandas、numpy、openpyxl 等程序核心依赖；新增或升级后需要重新打包对应 exe。
2. `外置扩展（代码块热更新）`：适用于 selenium、requests、OCR、浏览器自动化等仅由代码块使用的库。保存清单后点击“生成扩展包”，页面会从配置 Python 的本地 `site-packages` 复制所选发行包及其已安装依赖，生成 `extensions/archives/<版本>.zip`；此操作不联网，也不会下载缺失的包。
3. 在目标电脑的设计器或运行器中打开“外置扩展”标签，点击“导入并合并启用”选择 ZIP。导入单个 `requests` 包及其依赖时，程序会保留当前扩展中的 `selenium` 等包，构建新的完整版本；同一发行包版本不同会先显示更新确认。下次启动程序时，当前版本的 `extensions/versions/<版本>/site-packages` 会自动加入代码块的 import 路径；不需要重新打包 exe。

预收集依赖表会始终保留 PyQt5、numpy、openpyxl、pandas 四项程序基线，不能删除。需要制作独立 ZIP 时，点击“新建扩展清单”：表格会切换到独立的空草稿，新增库固定作为外置扩展；点击“生成扩展包”后会回到内置清单，过程中不会覆盖 `dynamic_imports.json`。ZIP 根目录的 `manifest.json` 同时记录根包的实际版本和全部递归发行包版本。

外置扩展包必须由与目标 exe 相同 Python 主版本和位数的解释器生成。切换或回滚扩展版本不会卸载当前进程已经导入的模块，因此会在下次启动设计器、运行器或代码块独立进程时完全生效。首次使用该能力前，需要先发布一次包含本版本运行时扩展加载器的设计器和运行器。

`tkinter` 是标准库，不存在于 `site-packages`，不能作为外置扩展 ZIP 复制。代码块需要 Tk GUI 时，应在“打包依赖”页将它标记为“标准库 · collect_all / 内置到程序”，然后重新打包目标 exe；构建前可用 `python -m tkinter` 确认所选 Python 自带 Tcl/Tk。

打包后的目标电脑通常不需要单独安装 Python，但需要复制对应应用的整个 `dist/<应用目录>` 文件夹；
例如 `main.spec` 的产物为 `dist/RPA_json设计器/`。

## 文档入口

- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)：项目结构、职责边界和当前执行模型。
- [DECOUPLING_TASKS.md](DECOUPLING_TASKS.md)：工作流参数模型与架构解耦任务记录。
- [CODE_BLOCK_TASKS.md](CODE_BLOCK_TASKS.md)：代码块设计约定、已完成和待完善事项。
- [PERFORMANCE_OPTIMIZATION_TASKS.md](PERFORMANCE_OPTIMIZATION_TASKS.md)：性能优化范围、基线脚本和大数据使用建议。

## 目录结构

```text
.
├── main.py                         # RPA_json设计器入口，包含设计模式和执行模式
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
├── crpa_launcher/                  # RPA_json运行器实现
└── tools/                          # 性能基线和大数据验证脚本
```

## 开发说明

- 配置文件、测试工作流、导出结果和本地路径文件不应作为通用项目文件提交。
- 新增算子时，优先把数据处理逻辑放入 `core/dataframe_ops/`，把运行类放入 `core/workflow/operators.py`，把配置面板放入 `operators/panels/`，再在 `operator_registry.py` 注册。
- UI 面板应保存用户意图和轻量 `io_prefs`，不要直接承担正式 `inputs/outputs` 生成职责。
- UI 兼容基线是 PyQt5 5.11.x；不要直接使用新版 PyQt 才有的方法，例如 `QComboBox.setPlaceholderText()`，需要通过兼容封装或旧 API 实现。
- 修改 UI 后建议至少运行一次主程序，并执行一次 `python -m py_compile` 或基础导入检查。
- 大数据性能优化应先跑 `tools/performance_baseline.py` 或 `tools/validate_large_dataframe_ops.py` 建立基线。

## 当前限制

- 大型 Excel 模板预览会按 sheet 和范围截断，完整结果以保存的 xlsx 为准。
- 默认模式会复制 DataFrame 输入；独立进程模式还会序列化 DataFrame。大表会增加内存占用和运行时间。
- Workbook 代码块在默认模式下直接操作内存对象；独立进程模式不支持内存 Workbook 输入。
- 当前 `timeout_seconds` 不会自动中断代码。长循环、阻塞 IO 或 `sleep` 应使用独立进程模式，或在循环中定期调用 `check_cancel()`。
- 代码块使用正常 Python import，不适合执行不可信代码。新增第三方依赖时，打包配置需要同步预收集该包。
- 项目仍在打磨配置面板、运行器体验、工作流校验规则和自动化测试覆盖。
