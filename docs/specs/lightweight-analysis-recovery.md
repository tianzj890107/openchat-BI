# 分析 Agent 轻量 Recovery 状态机 Spec

## 1. 背景

Tool Runtime 已为单次工具调用提供 execution ID、超时、幂等、取消和 stale-result 防护，但会话仍无法结构化表达“当前执行到哪一步、最后确认的结果是什么、失败是否可以重试”。现有六步 SOP 主要服务于页面展示，`pending_tool_use_id` 只覆盖进程内 AskUser 暂停，二者都不能作为可靠的恢复协议。

本阶段在现有 `WebSession`、Tool Runtime 和会话快照上增加轻量 Recovery 状态，不复制建模 Agent 的任务调度器。

## 2. 目标

1. 每轮分析具有明确状态：`PLANNED/RUNNING/WAITING_USER/SUCCEEDED/FAILED_RETRYABLE/FAILED_FINAL/CANCELLED`。
2. 每个工具边界形成小型 checkpoint，记录步骤、输入摘要、execution ID、attempt、结果引用和可重试性。
3. timeout 等可重试故障停在 `FAILED_RETRYABLE`，不会由后续 LLM 文本错误覆盖成成功。
4. 显式重试只能从最后一个可重试 checkpoint 发起，并增加 attempt；禁止自动重放和重复执行已成功工具。
5. AskUser 暂停状态可以随会话快照保存和恢复，并在用户选择后继续。
6. 旧会话没有 recovery 字段时仍可恢复。

## 3. 非目标

- 不实现 Redis、多进程协调、分布式调度、跨实例运行中任务迁移。
- 不保证进程崩溃后继续一个仍在执行的 Python 调用；恢复只从已落盘 checkpoint 重新进入。
- 不保存或重放完整 Doris 结果集。
- 不自动重试，不进行无限重试或静默后台恢复。
- 不新增前端页面；只提供后端状态、快照和兼容 SSE 字段。
- 不把六步 SOP 替换成 Recovery 状态机。SOP 是展示轨迹，Recovery 是执行控制状态。

## 4. 状态模型

外部状态固定为：

```text
PLANNED
RUNNING
WAITING_USER
SUCCEEDED
FAILED_RETRYABLE
FAILED_FINAL
CANCELLED
```

主要转换：

```text
PLANNED -> RUNNING
RUNNING -> WAITING_USER
RUNNING -> SUCCEEDED
RUNNING -> FAILED_RETRYABLE
RUNNING -> FAILED_FINAL
RUNNING -> CANCELLED
WAITING_USER -> RUNNING
FAILED_RETRYABLE -> RUNNING      # 仅显式 retry
```

`SUCCEEDED/FAILED_FINAL/CANCELLED` 是本轮终态，不允许迟到事件改写。新用户轮次创建新的 recovery turn，不复用上轮终态。

## 5. RecoveryState

`WebSession.recovery_state` 返回防御性只读字典，至少包含：

| 字段 | 说明 |
| --- | --- |
| `recovery_version` | 当前为 1 |
| `turn_ref` | 当前 recovery 轮次标识 |
| `status` | 七种状态之一 |
| `current_step` | 稳定步骤码，不保存自由文本 |
| `attempt` | 当前步骤真实执行次数，从 0/1 开始按语义更新 |
| `retryable` | 当前失败是否允许显式重试 |
| `error_code` | 稳定机器错误码 |
| `last_checkpoint` | 最近一次原子确认的 checkpoint；无则为 null |
| `pending_user` | WAITING_USER 所需的有界、脱敏信息；其他状态为 null |
| `updated_at` | UTC ISO 时间 |

建议稳定步骤码：

- `INTENT`
- `ONTOLOGY`
- `PLAN`
- `QUERY`
- `ANALYZE`
- `DELIVER`
- `WAIT_USER`

## 6. Checkpoint

checkpoint 至少包含：

- `checkpoint_id`：UUID；
- `turn_ref`；
- `step`；
- `input_digest`：输入规范摘要，禁止保存敏感明文；
- `execution_id`：工具步骤必填，纯 LLM/交付步骤可为空；
- `attempt`；
- `result_ref`：沿用 Tool Runtime 的有界摘要；
- `retryable`；
- `created_at`。

checkpoint 只能在一次状态/结果已经确认后原子替换。迟到工具结果、被 supersede 的轮次和未通过 Evidence Gate 的候选回答不得成为 checkpoint。

## 7. 工具结果映射

| Tool Runtime 结果 | Recovery 行为 |
| --- | --- |
| `SUCCEEDED` | 保存工具 checkpoint，继续 `RUNNING` |
| `TIMED_OUT` | `FAILED_RETRYABLE`，保留该 execution/attempt，停止当前轮次 |
| `CANCELLED + STALE_TOOL_RESULT` | `CANCELLED`，不得保存结果 checkpoint |
| `CANCELLED + TOOL_CANCELLED` | `CANCELLED` |
| `FAILED + retryable=true` | `FAILED_RETRYABLE` |
| `FAILED + retryable=false` | `FAILED_FINAL` |

工具失败后不得继续请求 LLM并最终发出 `SUCCEEDED`。失败事件可以向用户给出安全说明，但 Recovery 终态必须保持失败。

## 8. AskUser

当工具轮包含 AskUser：

- 已成功执行的 sibling tools 先形成 checkpoint；
- 状态原子转为 `WAITING_USER`；
- `current_step=WAIT_USER`；
- `pending_user` 保存 `tool_use_id`、问题和有限选项，不保存任意 HTML 或敏感上下文；
- `pending_tool_use_id`、`pending_choice_spec` 与 recovery state 必须一致。

用户提交有效选择后：

- `WAITING_USER -> RUNNING`；
- 清除 `pending_user`；
- 延续同一 `turn_ref`，不能创建一条无关新任务；
- 最终回答通过既有门禁后进入 `SUCCEEDED`。

无 pending 状态、错误 tool ID 或重复提交不得推进状态。

## 9. 显式重试

提供后端领域接口 `WebSession.retry_from_checkpoint()`（名称可等价，但测试约定使用该名称）：

- 仅 `FAILED_RETRYABLE` 可调用；其他状态返回稳定错误 `RECOVERY_NOT_RETRYABLE`，且不执行工具；
- 从 `last_checkpoint` 描述的失败步骤恢复，不重放更早的成功工具；
- 使用 Tool Runtime 的显式 retry 能力，复用逻辑 execution 身份并使 attempt 加 1；
- 同一 retry 请求重复投递仍具幂等性；
- retry 成功后继续原分析轮次，最终才能进入 `SUCCEEDED`；
- 最大 attempt 默认 2（初次 1 + 一次 retry）。耗尽后进入 `FAILED_FINAL/RETRY_EXHAUSTED`。

## 10. 持久化与恢复

会话 snapshot schema 增加可选 `recovery_state`：

- `ConversationSaveRequest` 不信任浏览器提供的 recovery 状态；保存时从当前 `WebSession` 读取服务端状态；
- `ConversationStore.save()` 原子保存经过规范化、有界化的 recovery state；
- restore/activate 把状态导入目标 WebSession；
- 只有 `WAITING_USER` 和 `FAILED_RETRYABLE` 可恢复为可继续状态；
- 快照中的 `RUNNING` 表示进程已经失去原执行，恢复时降级为 `FAILED_RETRYABLE/INTERRUPTED_DURING_EXECUTION`，不得假装仍在运行；
- 旧快照缺少 recovery 字段时初始化为 `PLANNED`，不得报错；
- 非法状态、超长字段、敏感字段按安全默认值规范化，禁止任意对象注入。

本阶段只持久化小型状态和引用，不持久化完整工具结果、Claim 集合或线程对象。

## 11. SSE 兼容

新增 `recovery_state` SSE 事件，至少包含：

- `type=recovery_state`
- `status`
- `current_step`
- `attempt`
- `retryable`
- `error_code`

Web 层应像其他 turn 事件一样添加 `turn_id`。旧前端忽略该事件后不受影响。不得借此改变现有 `done/error/session_superseded/awaiting_user_choice` 语义。

## 12. 安全与一致性

- Recovery、Tool Runtime 和 TurnLease 的状态更新必须遵循同一提交权；旧 generation 不得覆盖新状态。
- recovery 快照不保存 SQL、用户原文、凭据、完整结果或 traceback，只保存摘要和有界提示。
- `recovery_state` 属性每次返回防御性副本。
- 保存恢复测试只使用临时目录，禁止操作真实 `dataset/conversations`。

## 13. RED 验收

`tests/test_analysis_recovery.py` 固定以下行为：

1. 新会话初始为 `PLANNED`，快照不可反向修改内部状态；
2. 普通无工具轮经历 RUNNING 并最终 `SUCCEEDED/DELIVER`；
3. AskUser 进入 `WAITING_USER`，选择后沿用 turn 并成功；
4. 工具 timeout 进入 `FAILED_RETRYABLE` 且不继续调用 LLM；
5. 非重试异常进入 `FAILED_FINAL`；
6. supersede/cancel 进入 `CANCELLED`，迟到结果不能改写；
7. 显式 retry 只从 `FAILED_RETRYABLE` 发起并增加 attempt；
8. recovery state 经临时 ConversationStore 保存/加载保持一致；
9. 旧快照缺字段兼容为 `PLANNED`，恢复的 `RUNNING` 降级为可重试中断。

## 14. GREEN 完成条件

- 新增 Recovery RED 全部转绿；
- Tool Runtime 9 项继续全绿；
- concurrency、reliability、regressions 全部通过；
- 不删除、迁移或覆盖任何真实历史会话；
- 不通过修改测试、skip 或 xfail 规避契约。
