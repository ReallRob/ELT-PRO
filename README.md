# ELT-PRO

ELT-PRO 是一个面向 Excel/CSV 的可视化 ETL 与报表生成工具。它用 PyQt5 提供桌面界面，用 pandas 处理表格数据，用 openpyxl 读写 Excel 模板，目标是让常见的数据清洗、汇总、连接、计算和报表填充流程可以像搭积木一样配置、保存和复用。

项目目前处于研发阶段，已有功能以内部流程验证和业务试用为主，旧工作流兼容不是当前优先级。

## 主要能力

- 可视化工作流设计：左侧工具箱、中间画布、右侧配置面板、底部数据预览。
- 工作流 JSON 保存与导入：保存算子、连线、参数、文件路径、CRPA 元信息和运行清单。
- 执行模式：加载工作流、修正文件路径、运行全量流程、查看日志和结果预览。
- CRPA JSON 运行器：独立入口，面向业务人员，只需要选择 JSON、选择文件、填写参数并运行。
- 参数输入：支持运行参数、参数映射、引用参数，以及在代码算子中通过 `param()` 使用参数。
- Excel 模板处理：使用 openpyxl 导入模板、向指定工作表和区域写入数据，并输出完整 xlsx 文件。
- 用户代码能力：公式计算支持代码模式，实验性代码块算子支持多表输入和超时控制。

## 算子分类

当前工具箱包含以下类型的算子：

- 参数控制：参数输入。
- 输入输出：数据源导入、自动导出。
- 数据变换：提取列、数据筛选、多级排序、数据清洗、去重、抽样、转置。
- 汇总统计：分组汇总、数据透视、逆透视、描述统计。
- 表操作：表连接、纵向拼接。
- 计算列：数据排名、公式计算、累加计算、环比计算。
- 实验功能：导入模板、插入模板、代码块。

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
4. 使用“运行”测试当前算子或工作流，使用“保存”保存当前面板参数。
5. 在底部预览区检查中间结果或模板预览。
6. 导出工作流 JSON，用于后续执行或分发给其他人员。

## 工作流 JSON 与路径迁移

工作流 JSON 中会保存原始文件路径，但不同电脑上的路径通常不同。为了解决这个问题，JSON 中会附带 `run_manifest`，把运行所需资源拆成：

- `file_resources`：数据源文件、模板文件、输出文件。
- `data_sources`：数据源与工作表的关系。
- `parameters`：运行时需要填写的业务参数。

在执行模式或 CRPA JSON 运行器中，用户可以重新选择文件路径。启用写回后，新的路径和参数会保存回 JSON，避免每次运行都重新选择。

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

CRPA JSON 运行器会根据 `run_manifest` 自动生成文件选择框和参数输入框。当前版本不会实现真实 CRPA 类，只会在运行时打印 CRPA payload，并继续执行工作流。

## Excel 模板写入

模板相关算子分为两步：

- 导入模板：读取 xlsx 模板文件，作为后续写入目标。
- 插入模板：把上游 DataFrame 写入模板中的指定工作表、起始行、结束行、起始列、结束列。

模板写入使用 openpyxl。默认不继承上一行样式，而是尽量保留模板目标区域已有格式。最终输出是完整 xlsx 文件，不是单独的数据表。

## 代码模式与代码块

公式计算算子支持普通公式和代码模式。实验性代码块算子支持多个输入表：

- 第一个输入默认是 `df`。
- 后续输入可使用 `df1`、`df2`、`df3` 等别名，也可以在配置中自定义别名。
- 默认可用对象包括 `pd`、`np`、`re`、`math`、`datetime`、`date`、`timedelta`。
- 可以通过 `param("参数名")` 或 `param("参数名", "映射名")` 引用运行参数。
- 代码会在子进程中执行，并带有超时机制，避免死循环卡住主界面。

代码块会序列化 DataFrame 到子进程，大数据量场景可能有明显耗时和内存开销，使用前应控制输入规模。

## 目录结构

```text
.
├── main.py                    # 主程序入口，包含设计模式和执行模式
├── engine.py                  # 工作流执行引擎
├── workspace_context.py       # 设计态上下文和数据池管理
├── node_editor.py             # 画布节点与连线
├── operator_registry.py       # 算子注册表
├── template_engine.py         # Excel 模板导入、写入和保存
├── parameter_resolver.py      # 参数与映射解析
├── core/
│   ├── dataframe_ops/         # pandas 数据处理算子实现
│   ├── parameters/            # 参数映射 schema
│   ├── workflow/              # action handler 和依赖收集
│   └── manifest_builder.py    # run_manifest 构建
├── operators/
│   ├── base_panel.py          # 算子配置面板基类
│   └── panels/                # 各类算子配置面板
├── ui/
│   ├── design/                # 设计模式 UI
│   ├── execute/               # 执行模式 UI
│   └── dialogs/               # 路径重映射等弹窗
└── crpa_launcher/             # 独立 CRPA JSON 运行器
```

## 开发说明

- 代码以研发迭代为主，暂不承诺旧版 JSON 的长期兼容。
- 配置文件、测试工作流、导出结果和本地路径文件不应作为通用项目文件提交。
- 新增算子时，优先把数据处理逻辑放入 `core/dataframe_ops/`，把配置面板放入 `operators/panels/`，再在 `operator_registry.py` 和 `core/workflow/action_handlers.py` 注册。
- 修改 UI 后建议至少运行一次主程序，并执行一次 `compileall` 或基础导入检查。

## 当前限制

- 大型 Excel 模板预览会被限制为最多 5000 行、200 列，以避免界面卡死。
- 用户代码和代码块需要跨进程序列化 DataFrame，大表会增加内存和运行时间。
- 模板写入当前按指定区域写入，不会自动理解复杂业务区域，区域范围需要在算子中明确配置。
- 项目仍在打磨配置面板、运行器体验和工作流校验规则。
