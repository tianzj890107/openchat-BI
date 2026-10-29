---
name: process360-analytics
name_zh: 360智能分析
description_zh: 只处理流程 360（Process360）五个治理场景：SC01 发货超期、SC02 红区报价、SC03 战略客户突破、SC04 中标未签、SC05 计划外发货偏差。任何上述问题第一步必须调用 Process360Route，并按 Process360Plan → Process360Query/Analyze → Process360Draft → CanvasGenerate → OutputGateCheck 执行，数据只取储小策的 ywln 链路（process360-postgres / ywln_crm）。禁止使用 AnalysisRoute、MetricFactQuery、ListBusinessObjects 或采购域 Doris 数据，禁止因取数 blocked 回退到通用分析。风险与待办只在用户点击后经 RiskItemCreate/TaskOrderCreate 推送。
description: Process360-only analytics skill for SC01-SC05 (发货超期/红区报价/战略客户/中标未签/计划外发货偏差). The first tool call MUST be Process360Route, followed by Process360Plan and Process360Query/Analyze on the ywln PostgreSQL chain (process360-postgres / ywln_crm). Never fall back to AnalysisRoute, MetricFactQuery, ListBusinessObjects or the procurement Doris domain. Risk cards and todos are dispatched only after an explicit user click.
---

# process360-analytics（360智能分析）

本技能是 360 智能分析的唯一入口，只覆盖流程 360 的五个治理场景。它和
`ontology-analytics`（智能分析）是两个独立技能：智能分析走通用经营/财务本体与指标，
本技能**强制**走储小策的 `ywln` 流程 360 链路，两者不得混用。

## 强制链路（最高优先级）

1. **第一笔工具调用只能是 `Process360Route`**，把用户原话放进 `question`。
   不要先调用 `AnalysisRoute`、`ListBusinessObjects`、`MetricFactQuery`、
   `Ontology-*` 或任何通用报表工具做“试探”。
2. 路由后调用 `Process360Plan(question, scenario, scope)`，拿到 `planId` 和 `steps[]`。
   后续 `Query/Analyze/Draft/Verify/Compare/Structure/ProcessFlow/Progress/Forecast/
   Solutions` 必须带同一计划的 `planId + stepId`；服务端会校验场景、范围和依赖。
3. 数据只来自 `Process360Query/Analyze` 返回的 `dataSource=process360-postgres` 与
   `sourceConnection=pg:<host>/ywln#ywln_crm`。如果返回值不是 `ywln` 链路，停止并
   报告链路异常，不得继续出结论。
4. **禁止回退**：`Process360Query` 返回 `blocked/partial` 时，按缺口原样披露。不得改用
   `AnalysisRoute`、`MetricFactQuery`、`ListBusinessObjects`、采购域 Doris 或“演示数据”
   补数，也不得把采购金额、供应商、采购订单等通用本体数据当作 360 业务事实。
5. 如果宿主连接器里看不到 `Process360Route`，说明连接器接错了：停止分析，提示改用
   `ONTOLOGY_MCP_TOOL_PROFILE=process360` 的 360 连接器，不要用通用工具顶替。

## 适用场景

| 场景 | 典型问题 | 默认 SOP |
| --- | --- | --- |
| `SC01` 发货超期治理 | 哪些订单超期未发、超期多久、为什么、怎么处置 | P03/P06/P09/P10 |
| `SC02` 红区报价治理 | 红区报价集中在哪里、占比多少、审批是否异常 | P03/P05/P06 |
| `SC03` 战略客户突破 | 哪些战略客户没有有效商机、覆盖率缺口在哪里 | P03/P05/P06 |
| `SC04` 中标未签治理 | 哪些项目中标未签、等待多久、卡在什么条款 | P03/P06/P09 |
| `SC05` 计划外发货偏差 | 哪些发货偏离日计划、如何核查、后续是否改善 | P03/P06/P09/P15 |

不在上表内的通用经营/财务问题不属于本技能，改用 `ontology-analytics`（智能分析）。
两边都不确定的，先问用户要分析哪一类，不要靠一次 `MetricFactQuery` 猜。

## 可用工具

| 工具 | 用途 |
| --- | --- |
| `Process360Route` | S00 确定性路由；**任何 360 问题第一步** |
| `Process360Plan` | S00 多目标 DAG、依赖、步骤版本和共享预算 |
| `Process360Search` | S01 指标/业务对象双入口检索与场景归属 |
| `Process360Context` | S02 装配流程、活动、角色、规则、证据和缺口 |
| `Process360Query` | S03 五场景受控只读 PostgreSQL 取数；不接受 SQL |
| `Process360Analyze` | S04 异常、影响、候选原因和证据缺口 |
| `Process360Draft` | S05 服务端可信风险卡、方案与任务令草稿（不含手机号） |
| `Process360Verify` | S07 交付验收与效果复验计划 |
| `Process360Explore` | S08 受控自主探索；服务端工具白名单与去重 |
| `Process360Compare` | P04 多期同口径比较 |
| `Process360Structure` | P05 结构贡献、排名与占比 |
| `Process360ProcessFlow` | P07 按对象键/批次的节点转化与停留 |
| `Process360Progress` | P14 本服务执行记录与 Fuxi 推送回执 |
| `Process360Forecast` | P17 显式假设下的条件预测 |
| `Process360Solutions` | P18 多子目标综合编排 |
| `CanvasGenerate` | 把结论、图表和行动卡拼成整页 HTML，返回 `Artifact URL` |
| `RiskItemCreate` | 用户点击“推送风险”后写入 Fuxi（`itemType=RISK`） |
| `TaskOrderCreate` | 用户点击“发送任务令”后写入 Fuxi 待办（`itemType=TODO`） |
| `OutputGateCheck` | 交付前闸门：证据、行动卡、草稿、哈希与对账 |

工具集里不应出现 `AnalysisRoute`、`MetricFactQuery`、`ListBusinessObjects`、
`Ontology-MetricQuery`、`ChartGenerate`、`TableGenerate` 等通用分析工具；出现说明
连接器白名单未隔离，按上方“强制链路”第 5 条处理。

## 标准顺序

### 只问事实

```text
Process360Route → Process360Plan → Process360Query → CanvasGenerate → OutputGateCheck
```

`Process360Query` 返回 `queryId` 和 `recordsRef`（`rowCount/totalRows`/最多 5 条样本），
不返回完整明细。后续步骤复用同一个 `queryId`，不要重复查库。

### 异常诊断

```text
Process360Route → Process360Plan → Process360Query（必要时）
  → Process360Analyze → CanvasGenerate → OutputGateCheck
```

`Process360Analyze` 已含受控查询，不必为了流程形式先重复调用 `Query`。
`candidateCauses` 是候选原因，不是已确认根因；缺证据时只能提出核查任务。

### 需要风险卡 / 待办 / 改善方案

```text
Process360Route → Process360Plan → Process360Analyze
  → Process360Draft → CanvasGenerate（原样使用 draft.canvasActionBlock）
  → OutputGateCheck
```

- 用户说“发风险”“推送风险”“生成风险卡”“风险和待办”“发待办”时，服务端计划会把
  `actionDeliveryRequired` 置为 true；必须走完 `Process360Draft`，不能只输出文字建议。
- `Process360Draft` 返回的 `canvasActionBlock` 已合并 `riskActions` 与
  `canvasActions`，可直接作为 `CanvasGenerate` 的 `kind=actions` 块。
- 草稿因证据、权限、责任人不足而 blocked 时，在 HTML 中用空 actions 块写明
  `reason` 和 `gaps`，不得伪造卡片，也不得跳过闸门。

### 复验

```text
Process360Route → Process360Plan → Process360Verify
```

必须传 `runId` 和 `approvalRef`。缺冻结基准、批准目标、交付证据或复验窗口时
`canClose=false`；任务状态完成不等于效果达标。

## 停止点

| 用户目标 | 调用与停止点 |
| --- | --- |
| P01 定义、P02 流程规则 | `Process360Search` / `Process360Context`，不取数 |
| P03 当前事实与明细 | `Process360Query`，查完即停，不自动诊断或生成任务 |
| P06 异常、P08 影响、P09 候选原因 | `Process360Analyze`；只有明确要求才继续草稿 |
| P10 对策 / P11 任务草稿 | 继续 `Process360Draft`，不能只给文字建议 |
| P12 下发 | 本轮只生成草稿和行动卡；用户点击后才推送 |
| P15 复验 | `Process360Verify`；条件不足时 `canClose=false` |
| P04 / P05 / P07 / P14 / P17 / P18 | 对应 `Compare` / `Structure` / `ProcessFlow` / `Progress` / `Forecast` / `Solutions` |
| P13 业务写入 | 本服务不执行发运/签单/调价；不能把创建待办表述为业务操作成功 |

## 风险卡与待办

- 风险卡只走 `RiskItemCreate`，待办卡只走 `TaskOrderCreate`，两者不能互相替代。
- 卡片必须原样带上 `draftId`、`draftHash`、`runId`、`actionId`、`scenario`、
  `approvalStatus`、`expiresAt`、`dispatchTool`；按钮只携带这些不透明引用和展示字段。
- `approvalStatus` 不是 `approved` 或 `host_click_authorized` 时按钮禁用；`expiresAt`
  过期时提示重新生成，前端校验不能替代服务端校验。
- 手机号由服务端 `PROCESS360_RECIPIENT_MAP` 解析：页面不提交、HTML 不包含、模型不
  展示。接收人映射变化会阻断重试，避免把任务发给另一批人。
- 只有服务端状态明确成功、`accepted=true`、回执 `ok=true` 且 `applied+skipped>0` 才算
  发送成功；`blocked/rejected` 显示原因，空回执、零处理条数、超时或 `unknown` 显示
  “结果待确认”，同一草稿可安全重试。
- 风险推送成功不代表风险解除；Fuxi 没有执行进度查询接口，本地执行记录不能称作
  “Fuxi 已处理完成”。

## 证据与状态纪律

- `Process360Query/Analyze/Draft` 返回
  `status=ok|partial|blocked|needs_clarification|not_applicable`。`blocked/partial`
  必须原样披露，禁止补 0，禁止把“不可评估”改写成“没有风险”。
- 身份由服务端解析并在调用期间注入，模型不可见也不可覆盖。`grantKind=none` 拒绝取数，
  `restricted` 必须至少指定一个客户/负责人/产品维度，`all` 才允许全量只读。
- `Process360Analyze` 独立重取完整对象集并冻结 baseline，返回
  `fullObjectCount/frozenObjectCount/complete/objectSetHash`；`complete=false` 时
  `Process360Verify` 直接 blocked。
- `CanvasGenerate` 返回 `canvasId` 和 `artifactHash`；`OutputGateCheck` 必须传这两项
  （可加 `planId/queryId/runId`），服务端校验文件哈希、冻结数据并登记 append-only
  审计记录。内容变化后必须重过闸门。
- 本地 catalog 是语义来源，数据库只提供业务事实。不要把 `ywln_crm.meta_*` 当作运行时
  本体覆盖 catalog，也不要把数据库连接串或 SQL 暴露给 Fuxi/HTML。

## 接入方式（Fuxi）

360 智能分析必须使用独立的 MCP 连接器，与通用智能分析分开：

```text
transport: http
url: http://<bi-agent-host>/api/mcp
headers: {}
环境：ONTOLOGY_MCP_TOOL_PROFILE=process360
```

服务端 `process360` 白名单只暴露 `Process360*`、`CanvasGenerate`、
`RiskItemCreate`、`TaskOrderCreate`、`OutputGateCheck`。连接后工具面板不应出现
`AnalysisRoute`；出现即说明用了通用连接器，必须更换。

360 Agent 的技能引用只绑定 `process360-analytics`。让两个技能同时挂在一个 Agent 上，
模型就仍然可能先调 `AnalysisRoute`，这不是本技能支持的用法。

## 边界

- 技能包本身不启动服务、不保存 token、不包含真实数据；数据由主服务远程 MCP 提供。
- 不执行发运、签单、调价等业务写操作；S06 的唯一出口是 Fuxi 风险卡/待办，且必须由
  用户点击触发。
- 工具不可用、网络不可达、授权不足或数据 blocked 时，明确说明能力限制与缺口，不得用
  本地脚本、演示数据或通用采购域数据伪造结果。
