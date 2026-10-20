---
name: ontology-analytics
name_zh: 硕磐智能分析 Agent
description_zh: 企业财务/经营数据问答、取数与诊断：采购金额、采购订单、供应商、合同、发票、付款、预算、费用、收入、成本、毛利、应收应付、存货库龄、管报损益的合计、月度/年度趋势、同比环比、异常定位、根因分析、行动建议与执行监督。只要用户询问上述指标或要求分析经营数据，就必须使用本技能，即使用户没有点名技能；技能会自动完成路由、指标取数、对账、交付闸门和整页 HTML。
description: Use this skill for enterprise finance or operations data questions, including 采购金额/采购订单/供应商/合同/发票/付款/预算/费用/收入/成本/毛利/应收/应付/存货/库龄/管报损益, totals, trends, YoY/QoQ, anomaly diagnosis, root cause, action recommendations, and execution supervision. Trigger even when the user does not name the skill. It routes through the remote MCP AnalysisRoute tool, queries metrics with MetricFactQuery, reconciles numbers, checks output gates, and returns a self-contained HTML artifact URL.
---

# ontology-analytics

本技能把企业数据分析 Agent 的分析逻辑封装成可移植规则。运行真实数据时，不启动
本地服务、不读取本地凭据；宿主连接主服务暴露的远程 MCP，直接使用服务端已经装配好的
本体、指标和图表工具。

## 接入方式（Fuxi / 通用 Agent）

只需要连接一个远程 MCP 地址：

```text
transport: http
url: http://<bi-agent-host>/api/mcp
headers: {}
```

- URL 由部署主服务的团队提供；用户不需要填写 `.env`、App ID、Token 或目录。
- 主服务内部使用 demo2 的本体与 Doris 配置；`X-App-Id` 和仓库 ID 不暴露给前端。
- Fuxi 的 `tools` 面板应能看到下面 16 个真实工具；`AnalysisRun`、`AskUser`、
  `TodoWrite` 和任何原始 SQL / 表结构工具都不会出现。
- 工具调用和模型调用都在主服务完成；Fuxi 只负责对话、展示工具卡片和打开最终
  `Artifact URL`。
- 如果服务配置了 `ONTOLOGY_MCP_AUTH_TOKEN`，Bearer 头由服务端管理员统一配置，
  普通使用者仍然不感知 token。

## 可用工具

| 工具 | 用途 |
| --- | --- |
| `AnalysisRoute` | 确定性路由；任何经营/财务问题先调用它 |
| `Ontology-SemanticQuery` | 名称/术语跨本体检索；只在名称无法解析或需要消歧时调用 |
| `Ontology-TermDisambiguate` | 把业务词解析成权威术语 |
| `MetricCalculation` | 查看指标公式、口径、来源表和适用维度 |
| `Ontology-MetricQuery` | 底层指标聚合查询；通常由 `MetricFactQuery` 代替 |
| `MetricFactQuery` | **事实取数首选**：一次完成指标解析、日期过滤、管理单元/已审批口径、月度和下钻 |
| `Ontology-RelationQuery` | 查询实体关系 |
| `Ontology-EntityDescribe` | 查看业务对象/实体的完整描述 |
| `ListBusinessObjects` | 列出本体业务对象 |
| `Ontology-GraphContext` | 拉取业务对象或指标的下挂上下文 |
| `Ontology-GraphExpand` | 从锚点扩散上下游关系；L3–L5 才按需使用 |
| `ChartGenerate` | 单维图表 |
| `ChartGenerateMultiDim` | 多维可切换图表 |
| `TableGenerate` | 结构化表格 |
| `CanvasGenerate` | 把结论、图表、表格和口径拼成整页自包含 HTML，返回 `Artifact URL` |
| `OutputGateCheck` | 交付前检查证据、预测披露、图表、只读 SQL 和对账 |

## 默认交付契约

用户提出企业财务/经营数据问题时，自动完成以下动作，不需要用户点名工具、脚本、路径
或输出目录：

1. **先路由**：调用 MCP `AnalysisRoute`，把用户原话放进 `question`。
2. **再取数**：事实问题优先调用 `MetricFactQuery`；已经给出 `M...` 指标编码时，
   第一笔业务调用就是 `MetricFactQuery`，不要先堆叠 `Ontology-SemanticQuery`、
   `MetricCalculation` 和多次 `Ontology-MetricQuery`。
3. **必对账**：总额、分月、维度下钻之间核对；差额超过容差必须披露。
4. **再出图/表**：分析型结果用同一份数据生成 `TableGenerate` 和合适的
   `ChartGenerate`；纯标量事实可以只给文字。
5. **最后出整页 HTML**：调用 `CanvasGenerate`，把 📌 结论、文字说明、图表和表格
   放进同一页。返回的 `Artifact URL` 就是最终交付链接；不要再执行
   `run_scratch`、`promote_artifact` 或手工复制 HTML。
6. **交付前过闸门**：调用 `OutputGateCheck`，传入候选回答、本轮 SQL（如有）、
   图表参数和总额/分月对账；`verdict=reject` 时不得交付。
7. **回答附执行摘要**：路由模式、取数工具、对账结果、闸门 verdict、`Artifact URL`
   各一行。

只有用户明确说“只要一句话 / 不要文件 / 不要图表”时，才可以省略 HTML 或图表；
路由、取数和对账仍然必须执行。

## 一轮的标准顺序

### L1 事实查询

```text
AnalysisRoute
  → MetricFactQuery
  → TableGenerate / ChartGenerate（有月度或多行结果时）
  → CanvasGenerate
  → OutputGateCheck
```

如果 `MetricFactQuery` 返回指标名称不唯一，再调用 `Ontology-SemanticQuery` 或
`Ontology-TermDisambiguate` 消歧；不要把所有常见指标都先查一遍。

### L2 问题寻找

在 L1 基础上增加至少一个对比基线（同比、环比、目标差或结构占比）和一个异常切片；
输出只定位问题，不在这一级展开完整根因。

### L3 根因分析

使用 `MetricFactQuery` 做一次主查询，再对最异常切片做一次必要的维度/时间下钻；
用 `Ontology-RelationQuery` 或 `Ontology-GraphExpand` 验证至少一条关联假设；最后
必须给出基于证据的 1–2 条建议雏形。

### L4 / L5 决策与执行

L4 输出 2–4 个可比较方案（效果、成本、风险、周期）和推荐方案；L5 才输出责任人/
责任视角、时间节点、完成标准、监控指标和复盘机制。证据不足时先补取数或明确说明
限制，不要编造根因、预测数字或执行结果。

## 术语、消歧与澄清

- 编码已给出时，跳过名称消歧，直接 `MetricFactQuery`。
- 名称无法解析时，先用 `Ontology-SemanticQuery`，仍有多个候选再用
  `Ontology-TermDisambiguate`。
- 业务词确实有多个口径且上下文无法唯一确定时，**直接在回答里向用户提出 2–3 个
  明确选项**，等待用户选择后再取数。不要调用未暴露的 `AskUser` 工具。
- 同一轮不要为了“确认口径”重复查 SemanticQuery、MetricCalculation 和
  MetricQuery；返回值已经带回 `metric_names` / `dimension_names`。

## 数字、证据与安全

- 所有数字必须来自本轮 MCP 工具返回；没有工具证据时按能力限制说明，不得编造。
- 保留工具返回的 `[RESULT_METADATA]`、指标编码、维度编码和查询时间窗口，作为
  `OutputGateCheck` 的证据输入。
- 不执行写操作、删除、覆盖、DROP、TRUNCATE；不调用未暴露的原始 SQL 工具。
- 预测/情景必须披露数据窗口、方法和假设之一，不得给出无依据的置信区间或准确率。
- 业务名称优先展示；编码只放在括号或 `source_note` 中追溯。

## 整页 HTML 契约

`CanvasGenerate` 生成的是可以直接打开、保存和转发的单文件 HTML：

- `blocks` 按顺序放 `text`、`chart`、`chart_multi`、`table`；
- `blocks[].params` 与 `ChartGenerate` / `ChartGenerateMultiDim` / `TableGenerate`
  一致；
- 默认内联 ECharts，离线可开；页面偏大时可传 `inline_echarts: false`；
- 返回文本包含 `<CANVAS_SPEC>` 和 `Artifact URL`，最终回答只展示业务结论和
  `Artifact URL`，不要展示服务端内部暂存路径；
- 如果 URL 是相对/内网地址，按宿主实际入口补全，不要手工重建 HTML 文件。

## 纯规则脚本（可选，离线校验）

技能目录中的 `scripts/` 只保留确定性规则，不包含在线服务、凭据或工具运行时：

```bash
python3 scripts/route.py --question "2025年采购金额合计是多少" --pretty
python3 scripts/route.py --batch cases/routing_cases.jsonl
python3 scripts/gates.py sql --sql "SELECT 1"
python3 scripts/gates.py check --input turn.json
python3 scripts/selfcheck.py --quiet     # 期望 160/160 passed
```

Fuxi 运行时不要执行这些 CLI；直接调用远程 MCP 的 `AnalysisRoute` 和
`OutputGateCheck`。这些脚本用于离线验证规则、冻结用例和开发排查。

## 边界

- 远程 MCP 由主服务 `bi_agent.web` 提供，入口是 `/api/mcp`；技能包不启动服务、
  不保存 token、不包含真实数据。
- 不处理前端会话、流式输出和用户数据；HTML 由 MCP 生成并通过 `Artifact URL`
  交付。
- 工具不可用、网络不可达或权限不足时，明确说明能力限制，不要用本地脚本伪造结果。
