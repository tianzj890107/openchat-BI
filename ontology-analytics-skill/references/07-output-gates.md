<!-- 来源：bi_agent/reliability.py、bi_agent/web/session.py、bi_agent/tools/chart_policy.py、bi_agent/tools/sql_tools.py（基线提交 c94d430）。规则正文以 scripts/vendor/ 下的 vendored 模块为准。 -->

# 交付前的五道闸门

回答写完之后、发给用户之前，必须过闸门。闸门是确定性的，不要用"感觉没问题"替代。

Fuxi 运行时直接调用远程 MCP 的 `OutputGateCheck`，传入 `answer`、`question`、
`sql`、`chart`、`reconcile` 和可选的 `claims`；返回 `verdict=pass/warn/reject`。
正式报告还必须传 `CanvasGenerate` 返回的 `canvasId`、`artifactHash`，以及可用的
`planId/queryId/runId`。缺少最终 HTML 产物引用时直接 reject。只有显式
`deliveryKind=fact_answer` 的纯文字事实回答可以不带 Canvas；缺省视为 `analysis_report`。
行动交付（P10/P11/P12）必须传服务端生成的 `planId`，闸门从计划读取行动卡要求，不能由
模型在交付时自行声明“本轮不需要行动卡”。

离线开发/回归时可以运行纯规则脚本：

```bash
python scripts/gates.py check --input turn.json      # 证据 / 预测披露 / 图表 / 兜底
python scripts/gates.py sql --sql "SELECT ..."       # 只读 SQL 守卫
```

`turn.json` 结构见 `cases/gate_cases.jsonl` 里的样例；至少包含 `answer`，预测轮次再带 `forecast_kind` / `forecast_assumption`，数字轮次带 `query_results`。

## 0. 行动交付闸门

- 触发：服务端计划（`Process360Route/Plan`）标记 `actionDeliveryRequired=true`，即
  P10 对策、P11 任务草稿或 P12 下发语义。
- 要求：最终 HTML 必须有 `kind=actions` 块。每张卡必须带服务端草稿引用
  `draftId/draftHash/actionId/dispatchTool`，且能在服务端回读到同一草稿和同一 action。
- 不通过：计划要求行动卡但 HTML 没有卡片、草稿不存在、哈希不符、action 不属于草稿、
  卡片缺少草稿字段，均 reject；不得用正文“建议……”或普通“分析建议”替代可信行动卡。
- 允许阻断：`Process360Draft` 因证据、权限、责任人不足而 blocked 时，HTML 必须用
  空 actions 块写明 `reason`；计划中必须有一次 Draft 步骤记录，否则 reject。
- 不强制：纯事实查询（P03 等）、纯分析（P06/P09 等未要求处置）可以不带行动卡。
- 下发边界：生成草稿和行动卡不等于发送；只有用户点击后宿主才调用 `TaskOrderCreate`。
- 临时 POC 直发模式允许普通建议卡在页面上点击，并由服务端补建一次性草稿；该模式不放宽
  P10/P11/P12 的行动交付闸门，也不能替代本轮的 Draft 步骤。

## 1. 证据闸门（数字与确定性判断）

- 触发：回答里出现数字、合计、排名、比例、结论性判断。
- 判定：每个数字必须能追溯到本次工具的结构化结果；分项与合计必须能对账（容差 `1e-9`）；同一指标的不同口径不得混用。
- 不通过：不得输出原候选回答，改用"证据不足"兜底话术（见第 5 条），只列可确认的事实。
- 反模式：把上一轮的会话历史、报表解析文本或模型记忆里的数字当作本轮证据。

## 2. 预测披露闸门

- 触发：`wants_forecast = true`（路由决策给出）或回答里出现未来时点判断。
- 必须同时满足：披露数据窗口/时间区间；披露方法或明确声明无统计模型；情景类必须复述用户假设；说明不确定性。
- 一票否决：出现"置信区间、置信度、显著性、季节性、回测、准确率、误差率、拟合优度"等本系统无法产出的统计词汇；把计划/预算记录说成模型预测。
- 不通过：追加标准提示："说明：当前系统不具备统计预测能力，以上内容不是统计预测结论。如需继续，可提供明确假设后做情景推演、改为查询系统中已有的计划或预算数据，或补充数据范围后重试。"

## 3. 图表闸门

- 触发：本轮生成了图表。
- 判定：列表型问题（"列一下/有哪些/清单"）不生成图表，改用表格；所有数值相同（常数序列）不生成图表；图表中引用的指标口径必须与结论一致。
- 不通过：跳过图表并说明原因，不要用图表掩盖没有数值差异的事实。

## 4. 只读 SQL 闸门

- 所有取数 SQL 必须先过 `gates.py sql`。
- 允许：单条语句，以 `SELECT` / `WITH` / `PRAGMA` / `EXPLAIN` 开头，且不含写操作关键字；`PRAGMA` 不得带 `=`（赋值会改连接状态）。
- 远程网关额外要求：只接受 `SELECT` / `MATCH` 开头，`WITH` / `EXPLAIN` / `PRAGMA` 会被网关拒绝，因此远程模式不要下发这三类。
- 禁止：多语句（含 `;`）、`insert/update/delete/drop/alter/create/replace/truncate/attach/detach/vacuum/reindex`。

## 5. 兜底话术（不通过时用）

- 证据校验失败：

```
结论

本轮工具检索已完成，但自动证据校验发现最终叙述包含无法由结构化结果确认的数字或确定性判断，因此未展示原候选回答。

当前可确认的证据

（逐条列出可确认的事实；一条都没有时写"本轮尚未形成可验证的数据事实。"）

后续处理

需要重新执行或补全数据查询的结构化结果后，才能给出包含相关数字的业务结论。
```

- 只做了本体/结构检索、没形成数据结论：

```
结论

本轮已完成 <工具名> 的检索，但在最大执行轮次内没有形成可交付的数据结论。

下一步需要补齐可执行的数据查询、物理字段映射或明确分析口径；当前不把本体操作本身当作最终业务答案。
```

## 6. 产物绑定与服务端登记

- `canvasId` + `artifactHash` 必须指向当前 HTML；文件不存在、哈希缺失或不一致分别返回
  `artifact_missing`、`artifact_hash_required`、`artifact_hash_mismatch`；两者都缺失返回
  `artifact_reference_required`。
- 闸门通过或失败都会登记一次 append-only artifact 版本，包含
  `artifactId/artifactHash/requestId/planId/queryId/runId/gateResult/checkedAt`。
- 页面内容修改后哈希会变化，必须重新生成产物并重过闸门；旧的成功记录不能复用。
- `runId` 绑定冻结分析运行；冻结基准 `complete=false` 时返回
  `frozen_baseline_incomplete`。事实报告可以披露缺口后交付，但不能据此宣称效果验收通过。
- 正式效果复验还必须绑定服务端可信 `approvalRef`；模型自填目标不构成批准。
