# 分析 Agent 多实例共享并发协调与租约 Spec

## 1. 背景

当前 `SessionSlotRegistry`、`AdmissionController` 和资源 limiter 都是单进程内存状态。单 Uvicorn worker 下可以限制同会话并发、全局并发和单用户并发；一旦部署多个 worker 或多个实例，每个进程拥有独立计数器和 session slot，同一个 session 可能在两个实例同时执行，配额也会按实例倍增。

Tool Runtime 和 Recovery 已能拒绝当前进程内的迟到结果，但它们需要一个跨实例共享、带 fencing token 的租约作为最终提交权依据。

## 2. 目标

1. 使用 Redis 提供跨 worker/实例的 session lease、generation 与 fencing token。
2. 全局 active、等待队列和 principal 并发限制在所有实例间共享。
3. 租约具有 TTL、续租和 owner 校验；实例崩溃后可以自动回收。
4. 旧 owner 的 release、renew 和迟到结果不能影响新 owner。
5. 保留当前单实例、本地内存模式，默认配置不启用 Redis 时行为不变。
6. Redis 故障时采取明确、可配置且可观测的策略，禁止无声退化成不受控多实例执行。

## 3. 非目标

- 不把会话正文、Doris 结果、Claim、Recovery checkpoint 存入 Redis。
- 不实现跨实例迁移正在运行的 Python/LLM/Doris 调用。
- 不实现通用任务队列、Celery 或建模 Agent 调度器。
- 不改变业务回答、SOP、图表和前端页面。
- 不在单元测试中连接真实 Redis。
- 不以 Redis 锁替代 Tool Runtime 自身的 execution 状态和幂等账本。

## 4. 模式与配置

新增协调模式：

```text
local   # 默认；完全保持现有单实例行为
redis   # 多实例共享协调
```

建议环境变量：

- `CHATBI_COORDINATION_MODE=local|redis`
- `CHATBI_REDIS_URL`
- `CHATBI_COORDINATION_NAMESPACE`，默认 `chatbi`
- `CHATBI_INSTANCE_ID`，启动时唯一且不含凭据
- `CHATBI_LEASE_TTL_SECONDS`
- `CHATBI_LEASE_HEARTBEAT_SECONDS`，必须小于 TTL/2
- `CHATBI_COORDINATION_FAILURE_MODE=closed|local`

约束：

- 默认 `local`，现有部署无需 Redis。
- `redis` 模式缺 URL、client 初始化失败或配置非法时启动失败，不得假装启用共享协调。
- 多实例生产环境推荐 `closed`：Redis 运行中故障时拒绝新任务，已持有任务撤销提交权。
- `local` 故障降级只允许显式配置，并必须发出醒目告警和健康状态 `degraded`；不能自动静默降级。

## 5. 抽象边界

在 `bi_agent/concurrency.py` 或独立模块中提供共享协调接口。测试约定以下构造入口：

```python
InMemorySharedCoordination(clock=None)
RedisSharedCoordination(redis_client, namespace, clock=None)

SessionSlotRegistry(
    shared_backend=None,
    instance_id="...",
)

AdmissionController(
    limits,
    shared_backend=None,
    instance_id="...",
)
```

`InMemorySharedCoordination` 仅作为同一语义的确定性测试/本地适配器；生产 Redis 实现必须使用原子 Redis 操作或 Lua 脚本，不能用进程内锁包装多个非原子 Redis 命令冒充分布式原子性。

## 6. Shared lease

共享 session key 至少由以下内容规范编码：

```text
namespace + mode + tenant/user scope + session_id
```

不得包含 token、密码或用户问题原文。

共享租约至少包含：

- `key`
- `owner`：不可预测随机 owner token；不能只用 instance ID
- `instance_id`
- `generation`
- `fence`：严格单调递增整数
- `expires_at`

获取规则：

- key 无活跃租约时原子获取；
- key 已被其他 owner 持有时返回 busy；
- 同一 owner 的重复 acquire 不得产生第二份 active lease；
- TTL 过期后新 owner 可以获取；
- 每次新的合法 ownership 都必须获得更大的 fence。

## 7. Fencing

fence 是跨实例提交权的最终依据：

- 新 lease fence 必须大于此前所有 lease；
- release 只有 owner、generation、fence 全部匹配才生效；
- renew 只有完整身份匹配才延长 TTL；
- 旧 lease 的 release 不能删除新 lease；
- 旧 lease 的 renew 不能延长新 lease；
- ToolTurnScope/TurnContext 必须携带 fence；
- Tool Runtime settle、Recovery 转换、消息提交和会话保存前均需验证共享 lease 仍为 current；
- Redis 判断 lease 丢失、TTL 到期或 fence 落后时，设置当前 turn cancel event，并拒绝业务状态提交。

仅检查 generation 不足以覆盖跨实例旧 owner，必须校验 fence。

## 8. Heartbeat 与崩溃回收

- 持有 lease 的 turn 定期续租，heartbeat 小于 TTL/2。
- 续租必须 owner validated。
- turn 正常结束后立即 release；异常、断连和 GeneratorExit 仍由 finally 释放。
- 实例崩溃无法 finally 时依靠 TTL 回收。
- heartbeat 连续失败或返回 owner mismatch 时，租约视为丢失：设置 cancel event，后续结果不得提交。
- heartbeat 生命周期绑定 turn，不创建无法停止的永久线程。

## 9. 共享 Admission

Redis 模式下以下状态必须跨实例共享：

- `max_active_requests`
- `max_active_per_principal`
- `max_queued_requests`
- queue ticket 与进入时间

要求：

- 两实例总 active 不能超过全局上限；
- 同一 principal 跨实例 active 不能超过用户上限；
- queue 满返回既有 `GLOBAL_QUEUE_FULL`；
- principal 超限保持既有错误码；
- admission wait timeout/cancel 必须原子删除自己的 ticket；
- release 必须 ticket/owner validated，重复 release 幂等；
- 崩溃实例的 active ticket 通过 TTL 回收；
- 至少保持全局 FIFO；若队首 principal 自身达到上限，允许跳过以避免阻塞其他可运行 principal，并在其容量释放后重新参与。

## 10. 本地兼容

- `shared_backend=None` 时，`SessionSlotRegistry`、`SessionSlot`、`AdmissionController` 和现有 API 行为完全不变。
- 现有 `TurnLease(generation, owner)` 调用需要兼容；可以新增可选 `fence`、`shared_key` 字段，但不得破坏旧测试构造。
- 既有 409/429 JSON、错误码、SSE 和 release finally 不变。
- 单实例不因为本功能强制安装或启动 Redis。

## 11. Redis 原子操作

以下操作必须原子化：

1. acquire session lease + generation/fence 递增；
2. owner validated renew；
3. owner validated release；
4. bump generation/invalidate active lease；
5. admission 入队与容量检查；
6. admission grant；
7. ticket validated release/cancel；
8. TTL 过期 ticket 清理与计数修正。

可使用 Lua script 或 Redis Functions。禁止：

- `GET` 后在 Python 判断再 `SET`；
- 分开的 `INCR` 与 lease 写入造成 fence/owner 不一致；
- 用本地 `threading.Lock` 声称保护跨进程 Redis 操作。

## 12. 可观测性与健康检查

健康状态至少区分：

- `local`
- `redis_ok`
- `redis_degraded`
- `redis_unavailable`

日志可以记录：namespace、key 摘要、instance ID、fence、错误码和延迟；不得记录 Redis URL 凭据、session 原文或用户数据。

建议指标：

- lease acquire/busy/expired/lost；
- heartbeat success/failure；
- active/queued/principal active；
- admission reject；
- Redis 操作延迟和错误。

## 13. RED 验收

`tests/test_shared_coordination.py` 固定：

1. 默认 local 模式保持既有行为；
2. 两个 registry 共享后同 session 只能有一个 owner；
3. TTL 到期允许接管且 fence 严格递增；
4. 旧 owner release/renew 不能影响新 owner；
5. heartbeat 丢失会设置 cancel 并使旧 lease stale；
6. 两个 AdmissionController 共享全局与 principal 配额；
7. 跨实例排队保持 FIFO，并能取消自己的 ticket；
8. Redis acquire/renew/release 使用原子脚本入口；
9. Redis 不可用时 closed 模式拒绝，显式 local fallback 标记 degraded；
10. key 和诊断快照不泄漏 Redis 凭据或用户输入。

测试必须使用 fake clock、内存共享适配器或 fake Redis client，不访问网络，不依赖真实时间长等待。

## 14. GREEN 完成条件

- 新增 shared coordination RED 全部转绿；
- Recovery 11 项、Tool Runtime 9 项继续通过；
- concurrency、reliability、regressions 全部通过；
- Redis 模式的共享状态不能由两个 backend 实例各自保存在普通 Python 字典中；
- 不修改测试、skip 或 xfail；
- 不部署、不连接真实 Redis、不操作历史会话。
