# 智能分析 ontology-v0.0.5

## 基本信息

- 版本：`ontology-v0.0.5`
- 历史命名：本版本原以 `v0.1.4` 发布，2026-09-29 随版本族切换到 `ontology-v0.0.x` 时改名，定版 commit 未变
- 日期：`2026-09-07`
- 状态：正式版
- Git Tag：`ontology-v0.0.5`
- 定版 commit：`51939b2c3e5da755c4bef0df7e665cc5ac01d776`

## 版本概述

ontology-v0.0.5 在 Tool Runtime 之上增加轻量 Recovery 状态机：每轮分析有明确状态、
每个工具边界形成小型 checkpoint、可重试故障停在 `FAILED_RETRYABLE`，显式重试只能从
最后一个可重试 checkpoint 发起。它不替代六步 SOP（SOP 仍是展示轨迹，Recovery 是执行
控制状态）。

## 交付主题

### 1. 轻量 Recovery 状态机（`bi_agent/recovery.py`）

- 外部状态固定为
  `PLANNED / RUNNING / WAITING_USER / SUCCEEDED / FAILED_RETRYABLE / FAILED_FINAL / CANCELLED`；
- 每个工具边界生成 checkpoint：步骤、输入摘要、execution ID、attempt、结果引用与
  可重试性；
- timeout 等可重试故障停在 `FAILED_RETRYABLE`，不会被后续 LLM 文本覆盖成成功；
- 显式重试只从最后一个可重试 checkpoint 发起并增加 attempt；不自动重放、不重复执行
  已成功工具；
- AskUser 暂停状态随会话快照保存与恢复，用户选择后继续；
- 旧会话没有 recovery 字段时仍可恢复。

### 2. 恢复后的重试输入重建（`51939b2`）

- 恢复 `FAILED_RETRYABLE` 快照时，从会话自身持久化的 assistant `tool_use` 消息按
  checkpoint 的 `tool_use_id` 精确匹配，重建重放描述符；
- 描述符找不到时降级为 `FAILED_FINAL` / `RECOVERY_INPUT_MISSING`；
- 只有描述符校验通过才进入 `RUNNING`，避免出现"轮次在跑但没有东西可执行"的状态。

### 3. 会话与接口（`bi_agent/web/session.py`、`bi_agent/web/app.py`）

- WebSession 暴露恢复状态与快照，SSE 增加兼容字段；
- Tool Runtime 增加 checkpoint 写入点。

## 用户可见变化

- 出现超时等可重试故障时，页面能明确停在"可重试"而不是变成一段错误的成功叙述；
- 用户显式重试会从最后一个可重试步骤继续，不重复执行已经成功的工具。

## 验证情况

- `tests/test_analysis_recovery.py`（94 项新增）通过；
- 既有 Tool Runtime、会话并发与 SSE 回归保持通过。

## 已知限制

- 不保证进程崩溃后继续一个仍在执行的 Python 调用，恢复只从已落盘 checkpoint 重新进入；
- 不保存或重放完整 Doris 结果集；不自动重试、不后台静默恢复；
- 不新增前端页面，只提供后端状态、快照与兼容 SSE 字段；
- 本版本未部署。

## 相关记录

- GitLab Release：[智能分析 ontology-v0.0.5](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.5)
- 历史 tag：`v0.1.4`（2026-09-29 已随版本族切换删除，指向同一 commit `51939b2`）
- 规范：[语义化版本与正式发布规范](./versioning-policy.md)
