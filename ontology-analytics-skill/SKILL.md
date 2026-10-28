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
- Fuxi 的 `tools` 面板应能看到下面列出的真实工具；`AnalysisRun`、`AskUser`、
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
| `TaskOrderCreate` | 把用户确认的一条行动建议推送到 Fuxi 风险待办；只在用户点击后调用 |
| `OutputGateCheck` | 交付前检查证据、预测披露、图表、只读 SQL 和对账 |
| `Process360Route` | Process360 S00：P01-P18 SOP 与 SC01-SC05 场景确定性路由 |
| `Process360Search` | Process360 S01：指标/业务对象双入口检索与场景归属 |
| `Process360Context` | Process360 S02：装配流程、活动、角色、规则、证据和缺口 |
| `Process360Query` | Process360 S03：五场景受控只读 PostgreSQL 取数；不接受 SQL |
| `Process360Analyze` | Process360 S04：异常、影响、候选原因和证据缺口 |
| `Process360Draft` | Process360 S05：方案与任务令草稿（不含手机号） |
| `Process360Verify` | Process360 S07：交付验收与效果复验计划 |

## 默认交付契约

用户提出企业财务/经营数据问题时，自动完成以下动作，不需要用户点名工具、脚本、路径
或输出目录：

1. **先路由**：如果问题属于发货超期、红区报价、战略客户、中标未签或计划外发货，
   调用 `Process360Route`；其他经营/财务问题调用 `AnalysisRoute`。把用户原话放进
   `question`。
2. **再取数**：Process360 问题按下方 SOP 停止点调用 `Process360Query`；其他事实问题优先调用
   `MetricFactQuery`。非 Process360 问题已经给出 `M...` 指标编码时，第一笔业务调用就是
   `MetricFactQuery`，不要先堆叠 `Ontology-SemanticQuery`、
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

任务令不是分析生成步骤。只有用户点击某条行动建议的“发送任务令/转督办”后，
宿方才调用 `TaskOrderCreate`；模型不得在生成结论时自动发送，也不得猜测手机号。

只有用户明确说“只要一句话 / 不要文件 / 不要图表”时，才可以省略 HTML 或图表；
路由、取数和对账仍然必须执行。

## Process360 场景闭环（SC01-SC05）

以下问题必须走 Process360，而不是临时拼 SQL 或只做一次指标查询：

| 场景 | 典型问题 |
| --- | --- |
| `SC01` 发货超期治理 | 哪些订单超期未发、为什么、怎么处置、能否复验 |
| `SC02` 红区报价治理 | 红区报价集中在哪里、占比多少、审批是否异常 |
| `SC03` 战略客户突破 | 哪些战略客户没有有效商机、覆盖率缺口在哪里 |
| `SC04` 中标未签治理 | 哪些项目中标未签、等待多久、卡在什么条款 |
| `SC05` 计划外发货偏差 | 哪些发货偏离日计划、如何核查、后续是否改善 |

先调用 `Process360Route`，按用户目标选择步骤并到达停止点后交付：

| 用户目标 | 调用与停止点 |
| --- | --- |
| P01 定义、P02 流程规则 | `Process360Search` / `Process360Context`，无需取数 |
| P03 当前事实与明细 | `Process360Query`，查询完成即停止，不自动诊断或生成任务 |
| P06 异常、P08 影响、P09 候选原因 | `Process360Analyze`；根因仍须证据，只有明确要求才继续草稿 |
| P10 对策 | 依据上下文中的候选方案说明核查建议与适用约束；当前未实现效果/成本排序 |
| P11 任务草稿 | `Process360Draft`；`CanvasGenerate` 的 actions 使用 `draft.canvasActions` |
| P12 下发 | 仅在用户点击后由 Fuxi 宿主调用 `TaskOrderCreate` |
| P15 复验 | `Process360Verify`；当前只生成受阻断的复验计划，不宣称实际达标 |
| P04 多期、P05 结构排名、P07 转化、P14 进度、P17 预测、P18 综合 | 路由已经具备，专用执行尚未完成；按工具缺口交付，不以单次当前查询冒充完成 |
| P13 业务写入 | 本服务不执行发运/签单/调价；不能把创建待办表述为业务操作成功 |

`Process360Analyze` 已含受控查询，不必为了流程形式先重复调用 `Process360Query`。
所有分支交付前仍调用 `OutputGateCheck`；工具返回 `not_applicable` 时报告对应能力缺口。

纪律：

- `Process360Query`/`Process360Analyze`/`Process360Draft` 返回
  `status=ok|partial|blocked|needs_clarification|not_applicable`。`blocked` 或 `partial` 必须原样
  披露，禁止补 0、禁止把“不可评估”改写成“没有风险”。
- `Process360Analyze.candidateCauses` 是候选原因，不是已确认根因。缺少证据模板
  要求的证据时，只能提出核查任务。
- `Process360Draft.canvasActions[]` 已是 `CanvasGenerate` 的 `kind=actions`
  `params.items` 形态，可直接原样传入；`tasks[]` 是带审批/证据要求的完整草稿。
  两者都不含手机号。
- S06 唯一出口是 Fuxi 待办：用户点击后由宿主携带 `recipients_raw` 调用
  `TaskOrderCreate`，来源固定 `boulderai-anaylize-todo`。不调用 X360、不发送 Fuxi IM、
  不伪造发运/签单/排产等业务执行结果；这些动作由 Fuxi 待办侧承接。
- S07 使用 `Process360Verify`。没有冻结基准、批准 RF 目标或复验窗口时，
  `canClose=false`；任务状态完成不等于效果达标。
- 本地 catalog 是语义来源；数据库只提供业务事实。不要把 `ywln_crm.meta_*` 当作
  运行时本体覆盖 catalog，也不要把数据库连接串或 SQL 暴露给 Fuxi/HTML。

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

### 行动建议与任务令

- L3 及以上的行动建议除正文外，必须在 `CanvasGenerate` 的 `kind=actions` 块中
  提供结构化条目；每条至少包含稳定 `id`、`title`、`content` 和 `evidence`。
- 可选字段：`severity`（`CRITICAL/HIGH/MEDIUM/LOW`）、`due_at`（UTC `Z` 结尾）、
  `owner_ref`、`owner_name`。严重程度缺省 `MEDIUM`。
- 手机号属于宿主会话信息，不写进 HTML、不展示给模型。用户点击后由 Fuxi 宿主携带
  当前用户/责任人的 `recipients_raw` 调用 `TaskOrderCreate`。
- `TaskOrderCreate` 只写 Fuxi 风险待办，不负责 IM；接收人为空会被工具拒绝，
  因为 Fuxi 契约中空数组表示全员广播。

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

- `blocks` 按顺序放 `text`、`chart`、`chart_multi`、`table`、`actions`；
- `blocks[].params` 与 `ChartGenerate` / `ChartGenerateMultiDim` / `TableGenerate`
  一致；`actions` 块使用 `params.items`，每项至少含 `id`、`title`、`content`、
  `evidence`；
- 默认内联 ECharts，离线可开；页面偏大时可传 `inline_echarts: false`；
- 返回文本包含 `<CANVAS_SPEC>` 和 `Artifact URL`，最终回答只展示业务结论和
  `Artifact URL`，不要展示服务端内部暂存路径；
- `<CANVAS_SPEC>.actions` 是给 Fuxi 宿主的行动卡数据源；HTML 中的按钮只负责
  触发宿主回调/同源代理，不能直接持有手机号或任务服务凭据；
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
