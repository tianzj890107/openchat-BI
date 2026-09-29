# 智能分析 ontology-v0.0.4

## 基本信息

- 版本：`ontology-v0.0.4`
- 历史命名：本版本原以 `v0.1.3` 发布，2026-09-29 随版本族切换到 `ontology-v0.0.x` 时改名，定版 commit 未变
- 日期：`2026-09-07`
- 状态：正式版
- Git Tag：`ontology-v0.0.4`
- 定版 commit：`f9012f383195b9818fa322f8e47837aea4235972`

## 版本概述

ontology-v0.0.4 为每次普通工具调用引入独立的 Tool Runtime 执行边界：唯一执行标识、
执行状态、单工具超时、轮内确定性幂等、稳定错误分类，以及工具返回后的 stale-result
拒绝。本版本不改变业务回答、六步 SOP、图表与前端页面。

## 交付主题

### 1. Tool Runtime 执行边界（`bi_agent/tool_runtime.py`）

- 每次工具调用生成唯一 `execution_id`，并维护
  `PENDING / RUNNING / SUCCEEDED / FAILED / CANCELLED / TIMED_OUT` 状态；
- 单工具超时可配置，超时归类为 `TIMED_OUT`，与取消、执行异常区分开；
- 轮内确定性幂等：同一 `tool_use` 重复投递不会重复执行；
- 保留 `attempt` 计数与稳定错误分类，异常不再只落成 `Error executing ...` 字符串；
- 工具返回后复核提交权，拒绝在 reset、restore、数据源切换或新 generation 取代之后
  到达的迟到结果，避免旧结果进入 `query_results`、Claim 或渲染状态；
- 增加有界、脱敏的执行审计，保持既有 SSE 事件与图表策略兼容。

### 2. 契约测试与文档

- 先红后绿：`tests/test_tool_execution_boundary.py` 先定义执行边界红契约，随后实现转绿；
- 规范：`docs/specs/tool-runtime-execution-boundary.md`；
- 定版前最后一个修复（`f9012f3`）：让 executor start 的抢占在 ledger 锁内原子完成，
  消除并发下重复启动同一执行的窗口。

## 用户可见变化

- 工具超时、取消与执行异常不再混为同一种失败描述，页面与日志能回答一次执行处于
  什么状态、是否重试、为什么失败；
- 会话被重置、恢复或切换数据源后，迟到的工具结果不会再污染当轮结论。

## 验证情况

- `tests/test_tool_execution_boundary.py` 全部通过（含 start-claim 竞争用例）；
- 既有会话并发、SSE 与图表策略回归保持通过。

## 已知限制

- 不实现 Redis、多进程共享锁或分布式租约（由 ontology-v0.0.6 承接）；
- 不实现任务级 Recovery 状态机（由 ontology-v0.0.5 承接）；
- 本版本未部署，服务器运行版本不受影响。

## 相关记录

- GitLab Release：[智能分析 ontology-v0.0.4](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.4)
- 历史 tag：`v0.1.3`（2026-09-29 已随版本族切换删除，指向同一 commit `f9012f3`）
- 规范：[语义化版本与正式发布规范](./versioning-policy.md)
