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

## 暴露给 Fuxi 的 16 个工具

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
| `OutputGateCheck` | 五道交付闸门 | `answer`、`question`、`sql`、`chart`、`reconcile`、`claims` |

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
   最后 `CanvasGenerate`。
7. 交付闸门：`OutputGateCheck` 返回 `pass` 才能交付；`warn` 要披露，
   `reject` 要修正或拒答。

## 数据源与安全边界

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
