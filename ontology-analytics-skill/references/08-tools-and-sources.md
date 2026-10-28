# 工具清单与数据源契约

## 接入形态

真实数据只通过主服务的远程 MCP 接入：

```text
POST http://<bi-agent-host>/api/mcp
Content-Type: application/json
Accept: application/json, text/event-stream
```

Fuxi 连接器使用 `transport: http`，URL 指向 `/api/mcp`，headers 留空。服务端负责
连接 demo2 本体库、解析 `ontology_ecore`、使用 Doris 网关和保存 `X-App-Id`；
客户端不读取 `.env`、不需要 App ID 或 Token。若部署方显式设置
`ONTOLOGY_MCP_AUTH_TOKEN`，Bearer 头由管理员在连接器统一配置。

## 暴露给 Fuxi 的通用与 Process360 工具

| 工具 | 用途 | 主要参数 |
| --- | --- | --- |
| `AnalysisRoute` | 确定性路由：模式、档位、下一步、建议工具链 | `question`、可选 `allowed_tools` |
| `Ontology-SemanticQuery` | 跨本体关键词检索；名称解析失败时使用 | `query`、`limit` |
| `Ontology-TermDisambiguate` | 业务词到权威术语的消歧 | `term` |
| `MetricCalculation` | 指标公式、口径、来源表、适用维度 | `metric` |
| `Ontology-MetricQuery` | 底层指标聚合；通常不直接调用 | `metric_codes`、`dimensions`、`filters`、分页 |
| `MetricFactQuery` | 事实取数首选：名称/编码解析、日期过滤、管理单元、已审批口径、月度拆分、下钻 | `metric` / `metric_codes`、`start`、`end`、`monthly`、`dimensions`、`breakdown_period`、`management_unit`、`approved_only` |
| `Ontology-RelationQuery` | 实体关系查询 | `entity` |
| `Ontology-EntityDescribe` | 业务对象/实体完整描述 | `entity` |
| `ListBusinessObjects` | 列出业务对象 | `limit` |
| `Ontology-GraphContext` | 业务对象或指标的下挂上下文 | `anchor`、`limit` |
| `Ontology-GraphExpand` | 图邻域扩散；L3–L5 按需使用 | `anchor`、`depth`、上限 |
| `ChartGenerate` | 单维图表 | 与 Web 图表参数一致 |
| `ChartGenerateMultiDim` | 多维可切换图表 | 与 Web 多维图表参数一致 |
| `TableGenerate` | 结构化表格 | 与 Web 表格参数一致 |
| `CanvasGenerate` | 整页自包含 HTML，返回 `Artifact URL` | `title`、`conclusion`、`source_note`、`blocks` |
| `RiskItemCreate` | 用户点击后把有证据的已观察风险推送到 Fuxi（`itemType=RISK`） | Process360 风险卡：`draft_id`、`draft_hash`、`action_id`，可选 `retry`；不接受旧版无草稿调用，身份与接收人由服务端解析 |
| `TaskOrderCreate` | 用户点击后把一条处置建议推送到 Fuxi 待办（`itemType=TODO`） | Process360：`draft_id`、`draft_hash`、`action_id`，可选 `idempotency_key`/`retry`；身份与接收人均由服务端解析。旧版通用：`action_id`、`title`、`content`、`recipients_raw` |
| `OutputGateCheck` | 五道交付闸门与最终产物登记 | 正式报告必填 `canvasId`、`artifactHash`；`deliveryKind=fact_answer` 的纯文字事实回答可免 Canvas；可选 `answer`、`question`、`sql`、`chart`、`reconcile`、`claims`、`planId`、`queryId`、`runId` |
| `Process360Route/Search/Context/Query/Analyze/Draft/Verify` | SC01-SC05 的 S00-S07 主链 | 身份由服务端注入；Query/Analyze/Draft/Verify 等业务步骤必须带 `planId + stepId`；`Query` 返回 `queryId`，后续步骤可用 `queryId` 复用同一结果 |
| `Process360Plan` | S00 多目标 DAG、依赖、步骤版本、共享预算 | `question`、可选预算 |
| `Process360Explore` | S08 受控自主探索 | `question`、`planRef`、`stepId` |
| `Process360Compare` | P04 多期同口径比较 | `scenario`、`scope`、`periods` |
| `Process360Structure` | P05 结构贡献/排名/占比 | `scenario`、`scope`、`dimension`、可选 `queryId` |
| `Process360ProcessFlow` | P07 节点转化与停留 | `scenario`、`stages`、`objectKey`、`batchKey` |
| `Process360Progress` | P14 执行记录和 Fuxi 推送回执 | `scenario`、可选 `draftId` |
| `Process360Forecast` | P17 显式假设下的规则推算 | `actualToDate`、`target`、`elapsedDays`、`totalDays`、`assumption` |
| `Process360Solutions` | P18 多子目标综合 | `question`、可选方案依据 |

### 不暴露的工具

以下工具即使通过环境变量请求也不会出现在 `tools/list`，调用会被服务端拒绝：

- `AnalysisRun`：主服务没有这个概念；不再提供单次包装器。
- `AskUser` / `TodoWrite`：由宿主对话直接澄清，不进入数据工具白名单。
- `Ontology-FactQuery`、`ListTables`、`DescribeTable`：原始 SQL 和表结构探测不向
  外部 Agent 开放，避免绕过指标口径和只读策略。

## 工具选择顺序

1. **每轮先调用 `AnalysisRoute`**，以 `mode` / `next_step` / `required_tools` 为准。
2. 事实问题：直接 `MetricFactQuery`。`required_tools` 里的
   `Ontology-MetricQuery` 表示底层指标能力族，不要求再手写一次低层查询。
3. 名称无法解析或多候选：`Ontology-SemanticQuery` →
   `Ontology-TermDisambiguate`；仍不唯一时在对话中向用户提问。
4. 指标公式/口径有疑问：`MetricCalculation`；不要把它作为每轮前置步骤。
5. 多维下钻或根因：`MetricFactQuery` 一次传多个维度和 `breakdown_period`；
   证据不足时再加一次必要的下钻或关系查询。
6. 结果交付：`TableGenerate` / `ChartGenerate` / `ChartGenerateMultiDim`；
   最后 `CanvasGenerate`。L3 以上的行动建议放进 `kind=actions` 块。
7. 交付闸门：`OutputGateCheck` 返回 `pass` 才能交付；`warn` 要披露，
   `reject` 要修正或拒答。必须传最终 `canvasId/artifactHash`；缺失即 reject，不得把中间
   模型回答当作最终报告。
8. 风险/任务令：只有用户点击卡片后才调用对应工具。风险卡使用 `RiskItemCreate`，处置卡
   使用 `TaskOrderCreate`。Process360 卡片携带
   `draftId/draftHash/actionId/itemType/runId/scenario/approvalStatus/expiresAt/dispatchTool`；
   主服务按服务端身份和接收人映射调用，服务端从草稿回读标题/正文，不采用
   调用方改写。手机号只在服务端映射中配置，技能和模型不得猜测；空接收人会被拒绝。
   页面与 MCP 共用按 `itemType` 隔离的幂等键（风险额外使用独立 `analytics-risk-*`
   `sourceTodoId`）；网络结果不确定返回 `unknown`，
   用同一身份查询或显式 `retry=true` 安全重试，成功回执不得重发。回执必须同时满足
   `ok=true` 且 `applied+skipped>0`，不能仅凭 `sourceTodoId` 或 HTTP 200 判成功。
9. Fuxi 契约只有 `POST /source/todo-batches` 和 `POST /source/todo-status-events`；
   没有进度查询接口。字段名固定为 `sourceTodoId/title/severity/itemType/category/
   sourceStatus/sourceUpdatedAt/recipientsRaw/dueAt/description/impactText/ownerRef/
   ownerName/evidence/activity/caliberMeta`，不得改名或补造。

## 数据源与安全边界

- `Process360Query` 可把 `queryId` 传给 `Analyze/Draft/Structure/Verify` 复用同一结果。
  `Process360Query` 返回 `dataSource=process360-postgres` 与 `sourceConnection`；驾驶舱 AP
  数据返回 `dataSource=ap`。PostgreSQL 事实与旧 AP 快照必须分别标明来源，不能仅因页面标题
  相同就合并为同一份证据。
- `queryId` 是服务端结果引用，不是权限通行证。复用前检查 tenant/principal、授权版本、
  当前数据库来源连接、场景、范围、查询模板、catalog 版本和有效期；不匹配时明确 blocked，
  不静默换范围或换连接重取。
- 本体：主服务启动时从 demo2 读取 repository catalog，解析
  `ontology_ecore`；不在客户端保存连接信息。
- 指标与明细：通过主服务的 `analysis/meta/query`、`analysis/data/query` 和
  Doris 网关执行，只读。
- MCP 服务端只暴露上表白名单；工具执行仍复用 Web 对话的
  `build_source_executors`，不是另一套分析实现。
- `CanvasGenerate` 把 HTML 写到服务端工作区的 `dataset/canvas/`，通过
  `/api/mcp/artifacts/<filename>` 提供只读下载；文件名做路径穿越校验。
- 历史会话、上传文件、图表和数据库中的数据不由本技能删除或覆盖。

## 返回与错误

- 工具统一返回文本；结构化数据以 `[RESULT_METADATA]` 或 `<CANVAS_SPEC>` 块保留，
  作为证据和闸门输入。
- `tools/call` 的业务失败返回 `isError: true` 和明确错误文本；传输层失败返回
  JSON-RPC error，不得把失败伪装成空数据。
- 没有 MCP 连接时，按 `DELIVER_LIMITATION` 说明能力限制，不在本地拼 SQL 或伪造
  数字。
