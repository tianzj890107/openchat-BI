# 风险卡、待办卡与回执

## 生成不等于下发

- `Process360Draft` 生成服务端可信草稿；`CanvasGenerate` 把草稿原样放进
  `kind=actions` 块；生成阶段不发送任何消息。
- 用户点击“推送风险”后才调用 `RiskItemCreate`；点击“发送任务令”后才调用
  `TaskOrderCreate`。
- 风险卡只能用 `itemType=RISK + RiskItemCreate`，待办卡只能用
  `itemType=TODO + TaskOrderCreate`，类型不一致服务端阻断。

## 卡片字段

`Process360Draft.canvasActions[]` 已是 `CanvasGenerate` 的 `kind=actions`
`params.items` 形态，可直接使用：

```json
{
  "id": "…",
  "title": "…",
  "content": "…",
  "evidence": ["…"],
  "itemType": "RISK",
  "dispatchTool": "RiskItemCreate",
  "draftId": "…",
  "draftHash": "…",
  "runId": "…",
  "actionId": "…",
  "scenario": "SC05",
  "approvalStatus": "approved",
  "expiresAt": "2026-10-30T00:00:00Z"
}
```

- `draft.riskActions` 是风险卡，`draft.canvasActions` 是处置待办，不能互相替代。
- `draft.canvasActionBlock` 已合并两者，优先原样使用。
- 草稿不含手机号；接收人由服务端 `PROCESS360_RECIPIENT_MAP` 解析。
- 草稿因证据/权限/责任人不足而 blocked 时，传空 items 并写明 `reason` 与 `gaps`。

## 审批与有效期

- `approvalStatus` 不是 `approved` 或 `host_click_authorized` 时按钮显示“待审批”并禁用。
- `expiresAt` 已过时点击提示重新生成。
- 前端校验不能替代服务端校验；服务端会再次校验草稿、哈希、场景与审批状态。

## 回执判定

- 成功：服务端状态明确成功、`accepted=true`、回执 `ok=true` 且 `applied+skipped>0`。
- 失败：`blocked/rejected` 优先显示拒绝原因。
- 待确认：空回执、零处理条数、超时或 `unknown` 显示“结果待确认”，同一草稿可安全重试。
- 风险推送成功不代表风险解除；Fuxi 没有执行进度查询接口，本地执行记录不能称作
  “Fuxi 已处理完成”。

## 幂等

- 主服务与 MCP 共用执行服务，使用 `tenant:draftId:actionId` 稳定幂等键。
- 风险与待办使用不同 `actionId`、`sourceTodoId` 和执行记录。
- 网络结果不确定时返回 `unknown/unconfirmed`，不会自动换宿主重发。
