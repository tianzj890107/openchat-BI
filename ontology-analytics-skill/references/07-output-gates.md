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

- 触发：服务端计划标记 `actionDeliveryRequired=true`。通用分析对应“处置方案/任务草稿/
  下发”语义；360 场景由 `process360-analytics` 的 `Process360Route/Plan` 判定。
- 要求：最终 HTML 必须有 `kind=actions` 块。每张卡必须带服务端草稿引用
  `draftId/draftHash/actionId/itemType/dispatchTool`，且能在服务端回读到同一草稿和同一
  action。风险卡只能是 `itemType=RISK + RiskItemCreate`，处置待办只能是
  `itemType=TODO + TaskOrderCreate`，类型不一致即 reject。
- 不通过：计划要求行动卡但 HTML 没有卡片、草稿不存在、哈希不符、action 不属于草稿、
  卡片缺少草稿字段，均 reject；不得用正文“建议……”或普通“分析建议”替代可信行动卡。
- 允许阻断：草稿工具因证据、权限、责任人不足而 blocked 时，HTML 必须用空 actions 块
  写明 `reason`；360 场景的计划中必须有一次 Draft 步骤记录，否则 reject。
- 不强制：纯事实查询（P03 等）、纯分析（P06/P09 等未要求处置）可以不带行动卡。
- 下发边界：生成草稿和行动卡不等于发送；只有用户点击后才调用 `RiskItemCreate` 或
  `TaskOrderCreate`。风险推送成功只表示 Fuxi 已接收，不表示风险解除。
- 临时 POC 直发模式允许普通建议卡在页面上点击，并由服务端补建一次性草稿；该模式不放宽
  行动交付闸门，也不能替代本轮的 Draft 步骤。
