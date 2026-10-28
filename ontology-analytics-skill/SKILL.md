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
| `TaskOrderCreate` | 把用户确认的一条行动建议推送到 Fuxi 风险待办；只在用户点击后由服务端执行 |
| `OutputGateCheck` | 交付前检查证据、预测披露、图表、只读 SQL、对账和最终 HTML 产物 |
| `Process360Route` | Process360 S00：P01-P18 SOP 与 SC01-SC05 场景确定性路由 |
| `Process360Search` | Process360 S01：指标/业务对象双入口检索与场景归属 |
| `Process360Context` | Process360 S02：装配流程、活动、角色、规则、证据和缺口 |
| `Process360Query` | Process360 S03：五场景受控只读 PostgreSQL 取数；不接受 SQL |
| `Process360Analyze` | Process360 S04：异常、影响、候选原因和证据缺口 |
| `Process360Draft` | Process360 S05：服务端可信方案与任务令草稿（不含手机号） |
| `Process360Verify` | Process360 S07：交付验收与效果复验计划 |
| `Process360Plan` | S00 多目标拆分：DAG、依赖、步骤版本和共享预算 |
| `Process360Explore` | S08 受控自主探索：服务端工具白名单、调用去重与 path_gap |
| `Process360Compare` | P04 多期同口径比较 |
| `Process360Structure` | P05 结构贡献、排名与占比 |
| `Process360ProcessFlow` | P07 按对象键/批次的节点转化与停留 |
| `Process360Progress` | P14 本服务执行记录与 Fuxi 推送回执 |
| `Process360Forecast` | P17 显式假设下的条件推算，不冒充正式模型 |
| `Process360Solutions` | P18 多子目标综合；局部 blocked 不伪装整体完成 |

身份由服务端解析，不是工具参数：MCP 网关为每次调用生成统一请求上下文，包含
`principalId/tenantId/grantKind/grantScope/authorizationVersion/conversationId/requestId/surface`。
工具入参中出现 `principal`、`tenantId`、`canDispatch` 等身份字段会直接报错，模型既不能填写
也不能覆盖身份。POC 仍可使用服务端配置的只读身份，但下发权限必须通过
`PROCESS360_POC_DISPATCH` 单独开启。`TaskOrderCreate` 的 Process360 草稿模式还需要
`draft_id`、`draft_hash`、`action_id`，接收人由服务端映射解析，不从模型或页面读取。

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
6. **交付前过闸门**：调用 `OutputGateCheck`，正式分析报告必须传入 `canvasId`、
   `artifactHash`；行动交付（P10/P11/P12）必须带 `planId`，并尽量带 `queryId/runId`、
   本轮 SQL（如有）、图表参数和总额/分月对账。缺少最终 HTML 产物引用直接 reject；只有
   显式 `deliveryKind=fact_answer` 的纯文字事实回答可以不带 Canvas。`verdict=reject`
   时不得交付。
7. **回答附执行摘要**：路由模式、取数工具、对账结果、闸门 verdict、`Artifact URL`
   各一行。

生成任务草稿属于分析交付的一部分，不等于下发。只有用户点击某条行动建议的
“发送任务令/转督办”后，宿方才调用 `TaskOrderCreate`；模型不得在生成结论时自动发送，
也不得猜测手机号。

### 交付类型与行动卡

先判定用户要的是哪一种交付，不能把“有建议文字”当作已经交付行动卡：

| 用户需求 | 交付内容 | 任务令按钮 |
| --- | --- | --- |
| 查数量、金额、趋势、明细 | 事实、表格或图表 | 不需要 |
| 分析风险、原因，未要求处置 | 结论、证据、限制 | 不强制 |
| 要求改善建议、处置方案、任务草稿或下发 | 分析 + 服务端可信草稿 + 结构化行动卡 | 需要；条件不足时展示阻断原因 |

“建议补充数据后再分析”属于分析限制，不是可下发任务，不要为它伪造行动卡。
当交付类型需要行动卡时，按固定顺序执行：

```text
Process360Plan → Query/Analyze → Process360Draft → CanvasGenerate → OutputGateCheck
```

`Process360Draft` 返回的 `canvasActionBlock` 已是 `kind=actions` 块，应原样放入
`CanvasGenerate.blocks`；也可使用 `draft.canvasActions` 作为 `params.items`。生成草稿后
不要在正文里用一段文字替代行动卡。草稿因证据、权限或责任人不足而 blocked 时，传入
`{"kind":"actions","params":{"items":[],"reason":"…","gaps":[…]}}`，页面会显示
“尚不能生成可下发任务”及缺口，而不是让按钮无声消失。

`OutputGateCheck` 会读取计划中的行动交付要求：要求行动卡却没有卡片、卡片引用缺失或与
服务端草稿不一致时 reject；草稿确实 blocked 且 HTML 明确披露原因时允许交付分析结论。
纯查询、纯分析报告不受此限制。非行动交付的普通建议若放入 actions 块但未填写任何草稿
引用，严格模式下页面会标为“分析建议”且不出现发送按钮。临时 POC 直发模式
（`PROCESS360_CANVAS_DISPATCH_MODE=all`，当前默认）会把这些卡片显示为可发送，并由
服务端即时补建一次性草稿；这不改变 SOP，P10/P11/P12 仍必须先调用 Draft。

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
| P10 对策 | 先分析；需要可执行交付时继续 `Process360Draft`，不能只输出文字建议 |
| P11 任务草稿 | `Process360Draft`；`CanvasGenerate` 原样使用 `draft.canvasActionBlock`（或 `canvasActions`） |
| P12 下发 | 本轮只生成可信草稿和行动卡；用户点击后才调用主服务统一执行，页面与 MCP 共用幂等与回执契约 |
| P15 复验 | `Process360Verify`；缺冻结基准、批准目标或交付证据时 `canClose=false` |
| P04 多期比较 | `Process360Compare`；同口径窗口、对象集合和期间必须一致 |
| P05 结构排名 | `Process360Structure`；未知维度单列，贡献不等于原因 |
| P07 流程转化 | `Process360ProcessFlow`；必须有对象键/批次轨迹，缺轨迹时 blocked，不用节点总数相除 |
| P14 任务进度 | `Process360Progress`；只读本服务执行记录和 Fuxi 推送回执；Fuxi 没有进度查询接口 |
| P17 条件预测 | `Process360Forecast`；必须提供实际值、目标、期间进度和显式假设；无模型时只能称规则推算 |
| P18 综合编排 | `Process360Solutions`；多子目标独立验收，局部 blocked 时保留缺口 |
| S08 自主探索 | `Process360Explore`；只能调用服务端白名单工具，受共享预算约束 |
| P13 业务写入 | 本服务不执行发运/签单/调价；不能把创建待办表述为业务操作成功 |

`Process360Analyze` 已含受控查询，不必为了流程形式先重复调用 `Process360Query`。
所有分支交付前仍调用 `OutputGateCheck`；工具返回 `not_applicable` 时报告对应能力缺口。

纪律：

- 身份由服务端解析并在调用期间注入，模型不可见也不可覆盖。授权用 `grantKind` 显式区分：
  `none` 拒绝取数、`restricted` 与查询筛选取交集（必须至少指定一个客户/负责人/产品维度）、
  `all` 才允许全量只读。空授权列表不再等于“不限制”。
- `Process360Query`/`Process360Analyze`/`Process360Draft` 返回
  `status=ok|partial|blocked|needs_clarification|not_applicable`。`blocked` 或 `partial` 必须原样
  披露，禁止补 0、禁止把“不可评估”改写成“没有风险”。
- `Process360Route`/`Process360Plan` 返回 `planId` 和 `steps[]`。公共 MCP 的 Query、Analyze、
  Draft、Verify、Compare、Structure、ProcessFlow、Progress、Forecast、Solutions 都必须携带
  `planId + stepId`；服务端校验工具与步骤匹配、依赖已完成、场景/范围一致，且没有待澄清项。
  要改判时用 `Process360Route(planId, reviseReason)` 生成新修订，原计划保留，不要直接换场景。
- 每个 Process360 工具调用都会写执行轨迹（含只问数的 Query），可用
  `GET /api/process360/requests/{requestId}` 查看；不要求为审计强行调用 Analyze。
- CanvasGenerate 返回 `canvasId` 和 `artifactHash`；交付前 `OutputGateCheck` 必须传这两项
  （可加 `planId/queryId/runId`），服务端会校验文件哈希、冻结数据并登记 append-only
  `artifactId/requestId/planId/queryId/runId/gateResult/checkedAt`。内容变化后必须重过闸门。
- `Process360Query` 返回 `queryId` 和 `recordsRef`（`rowCount`/`totalRows`/样本 5 条），
  不再回传完整明细；把 `queryId` 传给 `Analyze/Draft/Structure/Verify` 即复用同一份结果，
  避免每步重复查库。缓存按身份、授权、范围和 catalog 版本隔离。
- `Process360Analyze` 由服务端独立重取**完整对象集**再冻结 baseline，返回
  `fullObjectCount/frozenObjectCount/complete/objectSetHash`；展示 `limit` 不再影响基准。
  `complete=false` 时 `Process360Verify` 直接 blocked，不能用“以后重跑”代替。
- 后续 `Process360Verify` 必须传 `runId` 和 `approvalRef`。目标、方向、最低分母和有效期从
  服务端批准记录读取；模型自填 `approvedTarget` 不能替代审批，冲突时返回
  `APPROVAL_TARGET_MISMATCH`。
- `Process360Analyze.candidateCauses` 是候选原因，不是已确认根因。证据哈希只能证明
  内容未变化；还要同时满足来源可信、对象/期间匹配、验证规则和反证检查，才可升级为
  已验证原因。缺少证据时只能提出核查任务。
- `Process360Draft.canvasActions[]` 已是 `CanvasGenerate` 的 `kind=actions`
  `params.items` 形态，可直接原样传入；每条带 `draftId`、`draftHash`、`runId`、
  `actionId`、`scenario`、`approvalStatus`、`expiresAt`、`dispatchTool`。
  `tasks[]` 是带审批/证据要求的完整草稿。两者都不含手机号。
- S06 唯一出口是 Fuxi 待办：用户点击后，页面只向主服务提交
  `draftId/draftHash/actionId/requestId`；主服务和 MCP 共用同一个执行服务，使用
  `tenant:draftId:actionId` 稳定幂等键。服务端从草稿回读标题/正文和接收人，不采用调用方
  改写；发送前原子登记执行，网络结果不确定时返回 `unknown/unconfirmed`，不会自动换宿主
  再发。不调用 X360、不发送 Fuxi IM、不伪造发运/签单/排产等业务执行结果。
- Fuxi 契约只有 `POST /source/todo-batches` 和 `POST /source/todo-status-events`，没有
  单条待办或执行进度查询接口。字段名固定为 `sourceTodoId/title/severity/itemType/
  category/sourceStatus/sourceUpdatedAt/recipientsRaw/dueAt/description/impactText/
  ownerRef/ownerName/evidence/activity/caliberMeta`，不得改名或自行补造。
- S07 使用 `Process360Verify`。没有冻结基准、批准 RF 目标、交付证据或复验窗口时，
  `canClose=false`；任务状态完成不等于效果达标。SC05 无批准关闭公式时保持 blocked。
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
  Process360 的 P10/P11/P12 交付必须先调用 `Process360Draft`，不能只写文字建议。
- 可选字段：`severity`（`CRITICAL/HIGH/MEDIUM/LOW`）、`due_at`（UTC `Z` 结尾）、
  `owner_ref`、`owner_name`、`category`。严重程度缺省 `MEDIUM`。
- Process360 草稿生成的行动卡必须原样带上 `draftId`、`draftHash`、`runId`、
  `actionId`、`scenario`、`approvalStatus`、`expiresAt`、`dispatchTool`。按钮只携带
  这些不透明引用和展示字段，不携带任务正文替代品、手机号或凭据。
- 未携带任何服务端草稿引用的 actions 条目是普通“分析建议”：严格模式不出现发送按钮并
  提示“尚未生成任务草稿”；临时 POC 直发模式显示“临时直发”，点击后由服务端按当前卡片
  内容生成一次性草稿。带任一草稿引用但六项字段
  （`draftId/draftHash/actionId/approvalStatus/expiresAt/dispatchTool`）不完整的旧版卡片
  在严格模式仍按钮禁用并显示“缺少草稿字段，请重新生成任务草稿”，不能手工补字段。
- 交付闸门会检查计划 `actionDeliveryRequired`：要求行动卡但 HTML 没有卡片、行动卡引用的
  草稿不存在/哈希不符/不属于该草稿时 reject；草稿 blocked 时必须由计划记录一次 Draft
  尝试，并在 HTML 中用空的 actions 块写明原因，才允许交付分析结论。要求行动交付时，
  普通“分析建议”不能替代可信行动卡。
- 点击“发送任务令”时，页面只把草稿引用和当前卡片展示字段 POST 到主服务
  `/api/process360/task-orders`；服务端解析身份、映射接收人、回读或按需补建草稿并调用
  统一执行服务。临时模式的接收人取服务端唯一配置，页面仍不得提交手机号。
  只有显式设置 `window.PROCESS360_TASK_ORDER_TRANSPORT='host'` 时才走 Fuxi 宿主桥接，
  HTTP 异常不会自动切换传输方式，避免服务端已执行后重复发送。
- 统一回执：仅当服务端状态明确成功、`accepted=true`、回执 `ok=true` 且 `applied+skipped>0`
  时显示成功；`blocked/rejected` 优先显示拒绝原因，空回执、零处理条数、超时或 `unknown`
  显示“结果待确认”，不会因为 HTTP 200、`sourceTodoId` 或消息已发出就当作成功。页面刷新后
  自动恢复待确认行动并短时轮询，`unknown` 可用同一草稿显式安全重试。
- `approvalStatus` 不是 `approved` 或 `host_click_authorized` 时按钮显示“待审批”并
  禁用；`expiresAt` 已过时点击会提示重新生成。服务端还会再次校验，不能靠前端绕过。
- 手机号属于服务端配置：页面不提交、HTML 不包含、模型不展示；主服务用
  `PROCESS360_RECIPIENT_MAP` 解析接收人，未配置时明确 blocked。接收人映射版本会冻结进
  执行记录，重试时映射变化会阻断，避免把任务发给另一批人。Canvas 生成阶段会拒绝包含
  手机号字段或 11 位手机号文本的行动条目。
- `TaskOrderCreate` 只写 Fuxi 风险待办，不负责 IM；接收人为空会被工具拒绝，
  因为 Fuxi 契约中空数组表示全员广播。Fuxi 返回的 `applied/skipped/errors` 原样保存
  为回执；没有进度查询接口，不能把本地执行记录称为 Fuxi 已处理完成。
- `TaskOrderCreate` 的所有分支（Process360 草稿、旧版普通行动和重试）都先检查服务端
  `canDispatch`；无下发权限时不会调用 Fuxi 客户端。

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
