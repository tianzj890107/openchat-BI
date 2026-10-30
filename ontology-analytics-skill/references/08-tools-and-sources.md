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

## 暴露给 Fuxi 的通用工具（`ONTOLOGY_MCP_TOOL_PROFILE=general`）

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
8. 风险/任务令：只有用户点击卡片后才调用对应工具。风险卡使用 `RiskItemCreate`，处置卡
   使用 `TaskOrderCreate`。主服务按服务端身份和接收人映射调用，不采用调用方改写的
   标题/正文；手机号只在服务端映射中配置，技能和模型不得猜测；空接收人会被拒绝。
