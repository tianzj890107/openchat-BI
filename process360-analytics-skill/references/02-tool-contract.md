# Process360 工具契约

## 调用约束

- 所有业务步骤必须带同一计划的 `planId + stepId`；`Process360Route`/`Process360Plan`
  负责生成计划。
- 服务端校验：工具与步骤匹配、依赖已完成、场景/范围一致、没有待澄清项。
- 要改判时调用 `Process360Route(planId, reviseReason)` 生成新修订，原计划保留。
- 身份由服务端解析并在调用期间注入，模型不可见也不可覆盖。

## 工具

| 工具 | 阶段 | 用途 | 关键参数 |
| --- | --- | --- | --- |
| `Process360Route` | S00 | 场景/SOP 确定性路由 | `question`、可选 `scenario`、`planId`+`reviseReason` |
| `Process360Plan` | S00 | 多目标 DAG、依赖、预算 | `question`、`scenario`、`scope` |
| `Process360Search` | S01 | 指标/业务对象检索 | `query`、`scenario` |
| `Process360Context` | S02 | 流程、活动、角色、规则、证据 | `scenario`、`objectKey` |
| `Process360Query` | S03 | 受控只读取数 | `planId`、`stepId`、`scenario`、`scope`、`limit` |
| `Process360Analyze` | S04 | 异常、影响、候选原因 | `planId`、`stepId`、可选 `queryId` |
| `Process360Draft` | S05 | 可信风险卡/方案/任务草稿 | `planId`、`stepId`、可选 `runId` |
| `Process360Verify` | S07 | 复验与关闭判定 | `planId`、`stepId`、`runId`、`approvalRef` |
| `Process360Explore` | S08 | 受控自主探索 | `question`、`planRef`、`stepId` |
| `Process360Compare` | P04 | 多期同口径比较 | `planId`、`stepId`、`periods` |
| `Process360Structure` | P05 | 结构、排名、占比 | `planId`、`stepId`、`dimension` |
| `Process360ProcessFlow` | P07 | 节点转化与停留 | `planId`、`stepId`、`stages`、`objectKey` |
| `Process360Progress` | P14 | 执行记录与推送回执 | `planId`、`stepId`、可选 `draftId` |
| `Process360Forecast` | P17 | 显式假设下的规则推算 | `actualToDate`、`target`、`elapsedDays`、`totalDays`、`assumption` |
| `Process360Solutions` | P18 | 多子目标综合 | `question`、可选方案依据 |
| `CanvasGenerate` | 交付 | 整页 HTML | `title`、`conclusion`、`source_note`、`blocks` |
| `RiskItemCreate` | 下发 | 推送风险卡 | `draft_id`、`draft_hash`、`action_id`、可选 `retry` |
| `TaskOrderCreate` | 下发 | 推送待办 | `draft_id`、`draft_hash`、`action_id`、可选 `idempotency_key`/`retry` |
| `OutputGateCheck` | 交付 | 证据与产物闸门 | `canvasId`、`artifactHash`、`planId`、`queryId`、`runId` |

## 结果复用

- `Process360Query` 返回 `queryId` 与 `recordsRef`（`rowCount/totalRows`/样本 5 条），
  不返回完整明细；把 `queryId` 传给 `Analyze/Draft/Structure/Verify` 复用同一结果。
- 缓存按身份、授权、场景、范围和 catalog 版本隔离；不匹配时 blocked，不静默换范围。
- `Process360Analyze` 独立重取完整对象集并冻结 baseline，返回
  `fullObjectCount/frozenObjectCount/complete/objectSetHash`。

## 禁止

- 不接受 SQL/DSN 参数；不要在对话或 HTML 中输出连接串。
- 不调用 `AnalysisRoute`、`MetricFactQuery`、`ListBusinessObjects`、`Ontology-*`
  作为 360 场景的路由或取数入口。
- 不把 `ywln_crm.meta_*` 当作运行时本体覆盖 catalog。
