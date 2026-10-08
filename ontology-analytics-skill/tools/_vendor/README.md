# _vendor — 真实工具实现（原样取自源仓库）

本目录是源仓库真实工具实现的原样副本，基线提交 `cc4a134`（`master`）。作用是让
`../serve.py` 在不安装 `bi_agent` 包的情况下直接调用真实工具。

## 文件清单（31 个）

- `bi_agent/tools/`：`__init__.py`（注册表与执行器装配）、`analysis_policy.py`、
  `chart_policy.py`、`ask_user.py`、`chart_tools.py`、`chart_multidim_tools.py`、
  `graph_tools.py`、`ontology_tools.py`、`remote_ontology_tools.py`、`sql_tools.py`、
  `table_tools.py`、`todo_tools.py`
- `bi_agent/ontology/`：`store.py`、`remote.py`、`remote_retriever.py`、`retriever.py`、
  `schema.py`
- `bi_agent/x360/`：`client.py`
- `bi_agent/`：`concurrency.py`、`tool_runtime.py`、`paths.py`、`display_names.py`、
  `reliability.py`、`shared_coordination.py`
- `open_claude/`：`tools.py`（工具注册表）、`config.py`、`tasks.py`、`agent.py`

## 相对源仓库的两处最小改动（其余逐字节一致）

1. `open_claude/tools.py`
   - 原因：文件末尾 `from .tasks import ...` / `from .agent import AGENT_SCHEMA` 会拉起
     `anthropic`，而纯工具服务器不需要 Claude / Agent 内置工具。
   - 改动：这两行改为 `try/except ModuleNotFoundError` 降级（缺失时任务/Agent 工具为空），
     BI 工具注册不受影响。

2. `bi_agent/ontology/store.py`
   - 原因：模块顶层 `import openpyxl` 会让「远程本体模式」也被这个 Excel 依赖阻塞。
   - 改动：改为可缺失导入，并在 `_load_workbook`（仅本地 Excel 模式使用）里给出
     `pip install openpyxl` 的明确提示。

## 外部依赖

| 依赖 | 何时需要 |
| --- | --- |
| 无（纯标准库） | 远程本体 + Doris HTTP 网关 + 图表/表格工具（推荐形态） |
| `openpyxl` | 本地 Excel 本体模式（`OA_LOCAL_ONTOLOGY_XLSX`） |
| `pymysql` | Doris MySQL 协议（`DORIS_JDBC_URL`），源仓库本就是惰性导入 |
| `redis` | 多进程协调（`shared_coordination.py`），源仓库本就是惰性导入 |
