# tools — 真实工具运行时

把源仓库**真实的 BI 工具实现**接出来，供任意 agent（Codex 等）调用；实现原样取自
源仓库（见 `_vendor/README.md`），本目录只负责「装配 + 配置 + 调用入口」。

- `serve.py`：CLI / JSONL 入口，按配置装配本体与取数后端，暴露 18 个工具。
- `canvas_tool.py`：**交付包自有**的整页交付工具（`CanvasGenerate`），把结论/图表/表格拼成
  一份自包含 HTML；实现不依赖 Web 前端，也不改 `_vendor/` 里的原实现。
- `assets/echarts.min.js`：随包携带的 ECharts，用于把图表页内联成离线可开的单文件。
- `_vendor/`：真实工具实现（原样副本，仅两处可缺失导入的最小改动）。
- `config.example.env`：配置模板（**只有变量名，没有值**）。
- `selftest.py`：离线自检（不需要任何凭据）。

## 快速开始

```bash
# 1. 凭据：复制模板后填值（不要提交、不要外发）
mkdir -p ~/.config/ontology-analytics
cp tools/config.example.env ~/.config/ontology-analytics/credentials.env
chmod 600 ~/.config/ontology-analytics/credentials.env
$EDITOR ~/.config/ontology-analytics/credentials.env

# 2. 看工具清单（不需要凭据）
python3 tools/serve.py --list-tools

# 3. 调一个工具
python3 tools/serve.py --call Ontology-FactQuery \
  --params '{"sql": "SELECT COUNT(*) AS n FROM fact_purchase_order"}'

# 4. 批量（JSONL：每行 {"tool": "...", "params": {...}}）
printf '%s\n' '{"tool":"Ontology-FactQuery","params":{"sql":"SELECT 1"}}' | python3 tools/serve.py --serve

# 5. 离线自检
python3 tools/selftest.py

# 6. 产出一份可以打开/转发的整页交付物（单文件、离线可开）
python3 tools/serve.py --call CanvasGenerate --params '{
  "title": "采购金额月度趋势",
  "conclusion": "📌 结论：3 月采购金额 153 万元，为上半年最高。",
  "source_note": "M001 · ontology_dev · 2025-01~2025-06",
  "blocks": [
    {"kind": "chart", "params": {"chart_type": "bar", "title": "采购金额月度趋势",
      "x_axis": ["1月", "2月", "3月"],
      "series": [{"name": "采购金额", "data": [120, 98, 153]}]}},
    {"kind": "table", "params": {"title": "明细",
      "columns": [{"key": "m", "label": "月份"}, {"key": "a", "label": "采购金额", "format": "number", "unit": "万元"}],
      "rows": [["1月", 120], ["2月", 98], ["3月", 153]]}}
  ]
}'
# 产出：dataset/canvas/canvas-<时间戳>-<标题>.html（默认内联 ECharts，约 1 MB）
```

## 配置

按优先级读取（后者不覆盖已存在的环境变量）：

1. 进程环境变量
2. `tools/credentials.env`（gitignore，勿提交）
3. `~/.config/ontology-analytics/credentials.env`（推荐，600 权限）

关键变量见 `config.example.env`。三种典型形态：

| 形态 | 必填 | 说明 |
| --- | --- | --- |
| 生产推荐 | `ONTOLOGY_BASE_URL`、`ONTOLOGY_REPOSITORY_ID`、`ONTOLOGY_APP_ID`、`ONTOLOGY_AUTH_TOKEN`、`ONTOLOGY_NAMESPACE`、`DORIS_API_URL`、`DORIS_DATABASE` | 远程本体 + Doris HTTP 网关，零第三方依赖 |
| Doris MySQL | 同上，把 `DORIS_API_URL` 换成 `DORIS_JDBC_URL/DORIS_USERNAME/DORIS_PASSWORD` | 需 `pip install pymysql` |
| 离线自检 | `OA_SQLITE_DB` 指向本地 SQLite 文件 | 只有取数/图表/表格工具可用，本体工具会明确提示未配置 |

## 与 agent 对接

- **CLI**：一次一个工具，`--call NAME --params JSON`，输出 JSON（`ok/result/error`）。
- **JSONL**：`--serve` 从 stdin 读、stdout 写，适合由 coding agent 用 shell 调用。
- **MCP/常驻**：需要常驻或 MCP 形态时，在 `serve.py` 外再包一层即可，工具执行器签名
  统一为 `executor(params: dict, cwd: str) -> str`（`build_source_executors()` 返回的映射）。

## 工具清单（18）

`Ontology-SemanticQuery`、`Ontology-TermDisambiguate`、`MetricCalculation`、
`Ontology-RelationQuery`、`Ontology-EntityDescribe`、`ListBusinessObjects`、
`Ontology-GraphContext`、`Ontology-GraphExpand`、`Ontology-FactQuery`、`ListTables`、
`DescribeTable`、`ChartGenerate`、`ChartGenerateMultiDim`、`TableGenerate`、
`TodoWrite`、`AskUser`、`Ontology-MetricQuery`、`CanvasGenerate`。

说明：`CanvasGenerate` 是交付包新增的**交付形态**工具（原系统没有），其余 17 个为原系统工具。
渲染/交互类工具（`ChartGenerate`、`ChartGenerateMultiDim`、`TableGenerate`、`TodoWrite`、
`AskUser`、`CanvasGenerate`）不依赖取数后端，任何环境下都可执行；`--list-tools` 声明与
可执行集合一致（`selftest.py` 会校验）。

返回格式：文本摘要 + `[RESULT_METADATA]` 结构化块（列/行、作用域、来源），下游证据
闸门（`scripts/gates.py`）依赖该结构化块。

## 安全

- 任何凭据都**不写入本目录**；`credentials.env`、`.env`、`*.pyc` 已被忽略。
- 取数一律只读；写操作/DDL/多语句由 `Ontology-FactQuery` 与 `scripts/gates.py sql` 双重拦截。
- 只在内网分发；不要把 `credentials.env` 放进压缩包或发给外部。
