---
name: ontology-analytics
name_zh: 智能分析
description_zh: 通用企业财务/经营数据问答、取数与诊断：采购金额、采购订单、供应商、合同、发票、付款、预算、费用、收入、成本、毛利、应收应付、存货库龄、管报损益的合计、月度/年度趋势、同比环比、异常定位、根因分析、行动建议与执行监督。只处理通用经营分析，不处理发货超期、红区报价、战略客户突破、中标未签、计划外发货偏差等 360 场景；上述场景必须改用 process360-analytics（360智能分析）。
description: Use this skill for general enterprise finance or operations data questions, including 采购金额/采购订单/供应商/合同/发票/付款/预算/费用/收入/成本/毛利/应收/应付/存货/库龄/管报损益, totals, trends, YoY/QoQ, anomaly diagnosis, root cause, action recommendations, and execution supervision. It routes through the remote MCP AnalysisRoute tool, queries metrics with MetricFactQuery, reconciles numbers, checks output gates, and returns a self-contained HTML artifact URL. Do NOT use for Process360 / SC01-SC05 questions; those belong to the process360-analytics skill.
---

# ontology-analytics（智能分析）

本技能把企业通用经营分析 Agent 的逻辑封装成可移植规则。运行真实数据时，不启动
本地服务、不读取本地凭据；宿主连接主服务暴露的远程 MCP，直接使用服务端已经装配好的
本体、指标和图表工具。

本技能只覆盖通用经营/财务分析。**360 场景（SC01-SC05）不在本技能范围内**：一旦识别
到发货超期、红区报价、战略客户突破、中标未签、计划外发货偏差，停止本技能流程，切换
到 `process360-analytics`（360智能分析），不得用 `AnalysisRoute`、`MetricFactQuery`、
`ListBusinessObjects` 或采购域 Doris 数据代替。

## 接入方式（Fuxi / 通用 Agent）

只需要连接一个远程 MCP 地址：

```text
transport: http
url: http://<bi-agent-host>/api/mcp
headers: {}
```

- URL 由部署主服务的团队提供；用户不需要填写 `.env`、App ID、Token 或目录。
- 通用分析连接器建议使用 `ONTOLOGY_MCP_TOOL_PROFILE=general` 的工具白名单，只暴露
  本技能的 18 个工具，不暴露 `Process360*`。
- 主服务内部使用 demo2 的本体与 Doris 配置；`X-App-Id` 和仓库 ID 不暴露给前端。
- 工具调用和模型调用都在主服务完成；Fuxi 只负责对话、展示工具卡片和打开最终
  `Artifact URL`。
- 如果服务配置了 `ONTOLOGY_MCP_AUTH_TOKEN`，Bearer 头由服务端管理员统一配置，
  普通使用者仍然不感知 token。

## 可用工具

| 工具 | 用途 |
| --- | --- |
| `AnalysisRoute` | 确定性路由；任何通用经营/财务问题先调用它 |
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
| `RiskItemCreate` | 把用户确认的一张已观察风险卡推送到 Fuxi（`itemType=RISK`）；只在用户点击后执行 |
| `TaskOrderCreate` | 把用户确认的一条处置建议推送到 Fuxi 待办（`itemType=TODO`）；只在用户点击后执行 |
| `OutputGateCheck` | 交付前检查证据、预测披露、图表、只读 SQL、对账和最终 HTML 产物 |

## 默认交付契约

用户提出企业通用财务/经营数据问题时，自动完成以下动作，不需要用户点名工具、脚本、
路径或输出目录：

1. **先路由**：调用 MCP `AnalysisRoute`，把用户原话放进 `question`。若返回
   `mode=PROCESS360_REQUIRED` / `next_step=PROCESS360_ROUTE`，说明该问题属于 360
   场景，立即停止本技能并改用 `process360-analytics`，不要继续取数。
2. **再取数**：事实问题优先调用 `MetricFactQuery`；已经给出 `M...` 指标编码时，
   第一笔业务调用就是 `MetricFactQuery`，不要先堆叠 `Ontology-SemanticQuery`、
   `MetricCalculation` 和多次 `Ontology-MetricQuery`。
3. **必对账**：总额、分月、维度下钻之间核对；差额超过容差必须披露。
4. **再出图/表**：分析型结果用同一份数据生成 `TableGenerate` 和合适的
   `ChartGenerate`；纯标量事实可以只给文字。
5. **最后出整页 HTML**：调用 `CanvasGenerate`，把 📌 结论、文字说明、图表和表格
   放进同一页。返回的 `Artifact URL` 就是最终交付链接；不要再执行
   `run_scratch`、`promote_artifact` 或手工复制 HTML。
6. **交付前过闸门**：调用 `OutputGateCheck`，正式分析报告必须传入 `canvasId`、
   `artifactHash`；本轮 SQL（如有）、图表参数和总额/分月对账一并传入。缺少最终 HTML
   产物引用直接 reject；只有显式 `deliveryKind=fact_answer` 的纯文字事实回答可以不带
   Canvas。`verdict=reject` 时不得交付。
7. **回答附执行摘要**：路由模式、取数工具、对账结果、闸门 verdict、`Artifact URL`
   各一行。

生成行动卡属于分析交付的一部分，不等于下发。只有用户点击某条行动建议的
“推送风险”后宿方才调用 `RiskItemCreate`，“发送任务令/转督办”后宿方才调用
`TaskOrderCreate`；模型不得在生成结论时自动发送，也不得猜测手机号。

### 交付类型与行动卡

先判定用户要的是哪一种交付，不能把“有建议文字”当作已经交付行动卡：

| 用户需求 | 交付内容 | 任务令按钮 |
| --- | --- | --- |
| 查数量、金额、趋势、明细 | 事实、表格或图表 | 不需要 |
| 分析风险、原因，未要求处置 | 结论、证据、限制 | 不强制 |
| 要求改善建议、处置方案或下发 | 分析 + 结构化行动卡 | 需要；条件不足时展示阻断原因 |

“建议补充数据后再分析”属于分析限制，不是可下发任务，不要为它伪造行动卡。
当交付类型需要行动卡时，按固定顺序执行：

```text
AnalysisRoute → MetricFactQuery → 结论 → CanvasGenerate（kind=actions） → OutputGateCheck
```

`OutputGateCheck` 会检查行动交付要求：要求行动卡却没有卡片、卡片引用缺失或与服务端
草稿不一致时 reject；草稿确实 blocked 且 HTML 明确披露原因时允许交付分析结论。
普通建议若放入 actions 块但未填写任何服务端草稿引用，严格模式下页面会标为“分析建议”
且不出现发送按钮。

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

### 风险卡、行动建议与任务令

- L3 及以上的行动建议除正文外，必须在 `CanvasGenerate` 的 `kind=actions` 块中
  提供结构化条目；每条至少包含稳定 `id`、`title`、`content` 和 `evidence`。
- 有证据支持且已观察到的风险使用 `item_type=RISK` 和 `dispatchTool=RiskItemCreate`。
  卡片必须包含风险标题、已观察事实、影响、等级依据、业务范围、证据和责任人。候选原因
  必须标为“待验证，不是已确认根因”，不得作为已确认风险事实推送。
- 处置任务使用 `item_type=TODO` 和 `dispatchTool=TaskOrderCreate`。风险条目与待办条目
  必须使用不同 `actionId`、`sourceTodoId` 和幂等执行记录。
- 可选字段：`severity`（`CRITICAL/HIGH/MEDIUM/LOW`）、`due_at`（UTC `Z` 结尾）、
  `owner_ref`、`owner_name`、`category`。严重程度缺省 `MEDIUM`。
- 手机号属于服务端配置：页面不提交、HTML 不包含、模型不展示；接收人由主服务解析，
  未配置时明确 blocked。
