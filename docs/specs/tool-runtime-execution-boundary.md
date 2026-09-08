# 分析 Agent Tool Runtime 执行边界 Spec

## 1. 背景

分析 Agent 已经通过 `SessionSlot`、`TurnLease` 和 cancel event 避免同一会话的多个轮次同时提交消息，但工具执行仍直接发生在 `WebSession` 的工具循环中。当前缺少独立的执行标识、状态记录、统一超时、幂等保护和工具返回后的提交权复核。

因此仍存在以下故障窗口：

- Doris 或本体查询长时间不返回，占用会话和全局并发资源；
- 同一 `tool_use` 被重复投递时重复执行；
-轮次在工具运行期间被 reset、restore、数据源切换或新 generation 取代后，旧结果仍可能进入 `query_results`、Claim 或渲染状态；
- 异常仅被转换为 `Error executing ...` 字符串，无法稳定区分超时、取消、执行异常和迟到结果；
-页面和日志只能看到工具名称与耗时，无法回答一次执行处于什么状态、是否重试以及为什么失败。

## 2. 目标

在不重写现有会话并发机制的前提下，为每次普通工具调用增加轻量执行边界：

1. 唯一 `execution_id`；
2. `PENDING/RUNNING/SUCCEEDED/FAILED/CANCELLED/TIMED_OUT` 状态；
3. 可配置的单工具超时；
4. turn 内确定性幂等；
5. `attempt` 与稳定错误分类；
6. 工具返回后的 stale-result 拒绝；
7. 有界、脱敏的执行审计；
8. 保持现有 SSE、工具输出和图表策略兼容。

## 3. 非目标

- 本阶段不实现 Redis、多进程共享锁或分布式租约。
- 不建立通用补偿事务。Doris/本体查询是只读操作，图表与表格可由结果重建。
- 不实现任务级 Recovery 状态机、checkpoint 或页面刷新后的任务续跑。
- 不改造 Cognitive Policy、Skill Registry、六步 SOP 和前端样式。
- `AskUser` 是等待用户输入的控制点，不进入普通工具超时和幂等执行器。
- 不保证强行终止任意第三方阻塞线程；本阶段保证其迟到结果失去提交权。
- 超时只允许限制等待和撤销提交权，不得截断、改写一个按时成功返回的真实工具结果。

## 4. 核心模型

每个 `WebSession` 持有一个可替换存储实现的 session 级执行账本。首期允许进程内存储，但工具循环只能通过账本接口访问，不能散落维护字典。

执行记录最少包含：

| 字段 | 约束 |
| --- | --- |
| `execution_id` | 首次接受逻辑调用时生成的 UUID；不同于 `tool_use_id` |
| `idempotency_key` | 规范化调用身份的摘要 |
| `turn_id` | Web 层分配的轮次 ID；直接调用时使用明确的本地轮次作用域 |
| `generation` | `TurnLease.generation`；无 TurnContext 时使用明确的 sentinel |
| `tool_use_id` | 模型产生的工具调用 ID |
| `tool_name` | 工具注册名称 |
| `input_digest` | 规范化参数的 SHA-256 摘要，不保存敏感参数明文 |
| `status` | 六种状态之一 |
| `attempt` | 从 1 开始；只有真正启动底层执行才增加 |
| `started_at` | UTC 时间 |
| `finished_at` | 终态 UTC 时间 |
| `duration_ms` | 单调时钟计算的非负整数 |
| `error_code` | 稳定机器码，成功时为空 |
| `error_message` | 有界、脱敏的人类可读摘要 |
| `retryable` | 是否允许显式重试 |
| `result_ref` | 有界结果摘要或引用，不复制完整结果集 |

执行账本对测试和诊断暴露只读快照 `WebSession.tool_execution_records`；快照为按创建顺序排列的字典列表，调用方修改快照不得改变内部账本。

## 5. 幂等身份

`idempotency_key` 至少由以下内容的规范序列化计算：

```text
session scope + turn_id + generation + tool_use_id + tool_name + canonical input
```

规范序列化必须递归排序对象键，因此参数键顺序不同但语义相同的输入得到相同键。不同 generation 或不同 turn 不得复用结果，避免用户修改指标、时间或过滤条件后收到旧数据。

同一 key 的规则：

- 首次调用创建记录并执行一次；
- `PENDING/RUNNING` 的重复投递不得启动第二个 executor；
- `SUCCEEDED` 的重复投递复用原 `execution_id` 和结果；
- `FAILED/TIMED_OUT/CANCELLED` 的普通重复投递不得隐式重试；
- 后续显式 retry 才产生新 attempt。显式 retry 接口不属于本轮 RED 的实现要求，但数据模型不得阻碍它。

## 6. 状态机

合法主路径为：

```text
PENDING -> RUNNING -> SUCCEEDED
                   -> FAILED
                   -> CANCELLED
                   -> TIMED_OUT
```

终态不可变。迟到成功、迟到异常或重复取消都不得改写既有终态。状态必须在调用 executor 前进入 `RUNNING`；进入终态时一次性写入 `finished_at`、`duration_ms` 和错误字段。

## 7. 超时、取消与迟到结果

### 7.1 单工具超时

- Tool Runtime 提供默认超时，并允许按工具名称覆盖。
- 测试可通过构造参数或测试专用注入配置毫秒级超时，不依赖真实网络超时。
- 超时终态为 `TIMED_OUT`，`error_code=TOOL_TIMEOUT`，`retryable=true`。
- 超时返回给 LLM/UI 的内容保持字符串兼容，但必须携带稳定机器码，且不得包含 traceback、密码、token 或连接串。
- 若任务在执行线程池队列中等待时已经超时或取消，worker 取得任务后必须在调用 executor **之前**检查终态；已处于终态的排队任务必须直接丢弃，不能在用户收到超时后继续向 Doris、本体服务或其他工具发起无效调用。
- “检查仍为 `RUNNING`”与“取得不可撤销的 executor 启动权”必须构成同一个原子决策。不能先在锁内检查、释放锁后再无条件调用 executor；否则 timeout 可能插入两者之间，使已终态化的任务仍然启动。实现可以增加显式 `STARTING/started` 内部标记或等价的锁内启动权协议，但不得把新的内部状态暴露成违反六状态外部契约的第七种终态。

### 7.2 取消

- executor 启动前 cancel 已置位：不调用底层工具，记录 `CANCELLED/TOOL_CANCELLED`。
- executor 运行中取消：尽力传播现有 cancel event，同时立即撤销该 execution 的提交权。
- 即使底层调用随后成功返回，终态也不能改回 `SUCCEEDED`。

### 7.3 stale-result 提交门禁

底层工具返回后，在任何业务状态修改或成功 SSE 事件之前，必须原子复核：

1. 捕获的 `TurnContext` 未被取消；
2. lease owner 与 generation 仍有效；
3. execution record 仍是 `RUNNING`；
4. 当前 execution 仍拥有该幂等调用的提交权。

任一条件不满足时，结果视为 stale：记录 `CANCELLED` 和 `STALE_TOOL_RESULT`（若已是 `TIMED_OUT` 则保持原终态），并禁止：

- `record_query_result`；
- 更新 `query_results`、`_turn_results`、`claims` 或 reconciliation；
- 更新本轮图表/表格状态；
- 将成功 `tool_result` 追加给下一轮 LLM；
- 发出成功的 `tool_result` SSE。

旧轮次结束时继续沿用现有 `session_superseded` 事件。

## 8. 工具适用范围

- Doris 与本体网络查询：必须受超时、取消、幂等和 stale 门禁保护。
- `ChartGenerate`、`ChartGenerateMultiDim`、`TableGenerate`：必须保留现有名称规范化、语义补充和 usefulness guard；真正调用 executor 后才进入执行账本。
- usefulness guard 在 executor 前决定跳过的图表沿用现有 suppressed 输出，不制造一次已运行的工具审计。
- `AskUser` 不进入执行器。

## 9. SSE 兼容契约

现有 `tool_result` 字段保持不变：

- `type`
- `id`
- `name`
- `input`
- `output`
- `duration_ms`
- 现有图表、表格、todo 和 ontology 字段

成功执行新增：

- `execution_id`
- `execution_status`，值为 `SUCCEEDED`
- `attempt`

失败、取消和超时可以使用现有 `error/session_superseded` 流程或增加兼容事件字段，但不得伪装成成功 `tool_result`。旧前端忽略新增字段后仍能工作。

## 10. 错误分类

| error_code | 状态 | retryable |
| --- | --- | --- |
| `TOOL_TIMEOUT` | `TIMED_OUT` | `true` |
| `TOOL_CANCELLED` | `CANCELLED` | `true` |
| `STALE_TOOL_RESULT` | `CANCELLED` | `true` |
| `TOOL_EXECUTION_ERROR` | `FAILED` | 由分类器决定，默认 `false` |

内部状态不得再依赖 `output.startswith("Error")` 推断。为了兼容 LLM，可以在边界处把结构化失败转换为既有字符串格式。

## 11. 审计与数据安全

- 审计保存摘要和引用，不保存无界 Doris 完整结果。
- 审计限界只作用于审计快照和 `result_ref`。Tool Runtime 必须把按时成功完成的原始结果完整交还 WebSession；不得为了限制审计大小而截断供 LLM、`record_query_result`、表格或图表消费的业务结果。
- 参数中的 `password`、`passwd`、`token`、`secret`、`authorization`、连接串凭据必须脱敏。
- `error_message` 必须限长并移除 traceback。
- 首期审计跟随 session 生命周期；历史快照没有执行账本字段时必须可以正常恢复。
- 是否将审计持久化到历史会话属于后续任务，本阶段不改变历史数据格式。

## 12. RED 验收场景

`tests/test_tool_execution_boundary.py` 固定以下外部行为：

1. 成功工具事件携带 execution 元数据，并形成完整成功审计；
2. 同一轮重复投递相同逻辑调用只执行一次；
3. 单工具超时能在底层调用返回前结束，且迟到结果不进入分析状态；
4. 工具运行时轮次被 supersede，旧结果不进入分析状态；
5. executor 异常形成稳定 `FAILED/TOOL_EXECUTION_ERROR` 审计；
6. 审计不保存敏感输入或完整大结果。
7. 超过审计限界的大结果仍完整返回给 WebSession，只有审计引用被压缩；
8. 在线程池队列中已经超时的调用以后不得迟到启动 executor。
9. timeout 发生在 worker 前置检查通过后、executor 调用前的竞态窗口时，必须由原子启动权协议确定唯一结果，不能同时出现 `TIMED_OUT` 和“executor 随后启动”。

RED 测试必须离线、确定性运行，不访问真实 LLM、Doris 或本体服务，不读写真实会话数据。并发同步使用 `threading.Event`，不以长时间 `sleep` 作为主要同步手段。

## 13. GREEN 实现边界

建议把执行记录、幂等计算、超时协调与终态 CAS 放在独立的 `bi_agent` 运行时模块中，由 `WebSession` 注入使用；`WebSession` 只负责准备参数、调用边界、通过提交门禁后更新业务状态并发 SSE。

GREEN 完成条件是新增 RED 全部转绿且既有 session、reliability、concurrency 回归测试通过。不得为通过测试弱化 lease、取消、Claim 或渲染门禁。
