# 智能分析 ontology-v0.0.6

## 基本信息

- 版本：`ontology-v0.0.6`
- 历史命名：本版本原以 `v0.1.5` 发布，2026-09-29 随版本族切换到 `ontology-v0.0.x` 时改名，定版 commit 未变
- 日期：`2026-09-07`
- 状态：正式版
- Git Tag：`ontology-v0.0.6`
- 定版 commit：`99ac6f1f0aaf1235bfdaa49e35957bd59dafd7a6`

## 版本概述

ontology-v0.0.6 把单进程内存里的会话 slot、准入控制和并发上限扩展为可选的跨实例
共享协调：以 Redis 提供带 fencing token 的会话租约、generation 与全局并发计数。默认
`local` 模式行为与之前完全一致；Redis 故障时按配置明确失败，不允许无声退化成不受控的
多实例执行。

## 交付主题

### 1. 共享协调与租约（`bi_agent/shared_coordination.py`、`bi_agent/concurrency.py`）

- 协调模式 `local`（默认，保持单实例行为）/ 共享后端；
- 会话租约具备 TTL、续租、owner 校验，实例崩溃后可自动回收；
- 旧 owner 的 release、renew 与迟到结果不能影响新 owner（fencing token）；
- 全局 active、等待队列与 principal 并发上限在所有实例间共享；
- `SharedSessionSlot` 增加 owner / generation / `bump_generation` 一致性，
  InMemory 与 Redis 后端都提供原子的 `bump_generation` / `current_generation`。

### 2. 接入生产轮次守卫（`99ac6f1`、`bi_agent/web/app.py`）

- `AppState` 新增 `configure_coordination` / `configure_coordination_from_env`
  （校验后热切换安装共享后端到 session slots、准入、TTL/心跳与有界健康信息）；
- `start_turn_heartbeat` 守护线程续租；本地租约为 no-op 守卫；
- `configure()` 从环境变量安装后端（Redis 已关闭策略下启动即失败，不静默降级）；
- `_begin_turn` 按配置 TTL 获取租约，`_run_turn_stream` 在 SSE 生命周期内启停心跳；
- `/healthz` 暴露有界协调摘要。

### 3. 契约测试与文档

- `tests/test_shared_coordination.py` 新增共享协调用例；
- 规范：`docs/specs/shared-multi-instance-coordination.md`。

## 用户可见变化

- 多 worker / 多实例部署时，同一会话不会在两个实例同时执行，全局限额不再按实例倍增；
- Redis 故障时按配置明确失败并可观测，不会无声退化成不受控并发。

## 验证情况

- `tests/test_shared_coordination.py`、`tests/test_concurrency.py` 通过（不连接真实 Redis）；
- 默认 `local` 模式下单实例行为与历史一致。

## 已知限制

- 不把会话正文、Doris 结果、Claim 或 Recovery checkpoint 存入 Redis；
- 不实现跨实例迁移正在运行的调用，不引入通用任务队列；
- 本版本未部署，生产仍是单实例配置。

## 相关记录

- GitLab Release：[智能分析 ontology-v0.0.6](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.6)
- 历史 tag：`v0.1.5`（2026-09-29 已随版本族切换删除，指向同一 commit `99ac6f1`）
- 规范：[语义化版本与正式发布规范](./versioning-policy.md)
