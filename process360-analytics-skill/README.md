# process360-analytics-skill（360智能分析）

流程 360 专用技能包：只处理 SC01-SC05 五个治理场景，强制走储小策的 `ywln` 链路。
它和 `ontology-analytics-skill`（智能分析）是两个独立技能，服务端用两个独立连接器
隔离工具集，避免 360 请求落到通用采购域。

## 目录

```text
process360-analytics-skill/
├─ SKILL.md                    主入口：强制链路、停止点、行动卡
├─ references/
│  ├─ 01-scenarios.md          SC01-SC05 场景、关键词与可回答范围
│  ├─ 02-tool-contract.md      Process360 工具参数与调用约束
│  ├─ 03-delivery-cards.md     风险卡/待办卡、草稿与回执
│  └─ 04-evidence-and-boundaries.md 状态、缺口、授权与禁止事项
└─ README.md
```

本目录不包含服务代码、凭据、SQL 或运行数据；真实工具和 HTML 由主服务 `/api/mcp`
提供。

## Fuxi 接入

360 连接器必须与通用连接器分开：

```text
transport: http
url: http://<bi-agent-host>/api/mcp
headers: {}
环境：ONTOLOGY_MCP_TOOL_PROFILE=process360
```

`process360` 白名单只暴露：

```text
Process360Route, Process360Plan, Process360Search, Process360Context,
Process360Query, Process360Analyze, Process360Draft, Process360Verify,
Process360Explore, Process360Compare, Process360Structure, Process360ProcessFlow,
Process360Progress, Process360Forecast, Process360Solutions,
CanvasGenerate, RiskItemCreate, TaskOrderCreate, OutputGateCheck
```

工具面板里出现 `AnalysisRoute`、`MetricFactQuery`、`ListBusinessObjects` 或
`Ontology-*` 就说明接错连接器，必须更换。

## 推荐执行顺序

```text
Process360Route
  → Process360Plan
  → Process360Query / Process360Analyze
  → Process360Draft（要求风险卡/待办时）
  → CanvasGenerate
  → OutputGateCheck
  → 返回业务结论 + Artifact URL
```

## 数据链路

- `Process360Query/Analyze` 返回 `dataSource=process360-postgres`、
  `sourceConnection=pg:<host>/ywln#ywln_crm`。
- 连接串只存在于服务端；技能、模型和 HTML 都不得展示。
- `blocked/partial` 必须原样披露；禁止补 0，禁止回退到采购域 Doris。

## 边界

- 不执行发运、签单、调价等业务写操作。
- 风险卡和待办只在用户点击后推送，且由服务端解析接收人。
- 技能包不启动服务、不保存 token、不包含真实数据。
