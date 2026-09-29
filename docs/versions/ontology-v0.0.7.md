# 智能分析 ontology-v0.0.7

## 基本信息

- 版本：`ontology-v0.0.7`
- 历史命名：本版本原以 `v0.1.6` 发布，2026-09-29 随版本族切换到 `ontology-v0.0.x` 时改名，定版 commit 未变
- 日期：`2026-09-07`
- 状态：正式版
- Git Tag：`ontology-v0.0.7`
- 定版 commit：`1ae9894df5e2fba190dbadca483ec7a15b1cd216`

## 版本概述

ontology-v0.0.7 为每个新用户轮次生成一份可测试、可观测的内部决策快照
（cognitive policy），说明"这一轮为什么走这条路线"。它只增加轻量决策记录，不取代六步
SOP、LLM 推理、本体检索、Tool Runtime 或 Recovery。

## 交付主题

### 1. `build_cognitive_policy_decision`（`bi_agent/tools/analysis_policy.py`）

- 纯函数 `build_cognitive_policy_decision(question, allowed_tools)`，复用既有确定性意图
  分类（L2/L3/L4/L5、根因与行动意图）；
- 每个新用户轮次只生成一次决策，WebSession 保存最近一次决策的防御性快照；
- 在首次 `llm_request` 之前发出 `cognitive_policy` SSE 事件，Web 层附加当前 `turn_id`；
- `required_tools` 始终是当前会话允许工具的子集，只做推荐、不构成硬白名单；
- 只保存输入摘要（问题 sha256 摘要），不保存原始问题、SQL、工具结果或密钥。

### 2. 契约测试与文档

- `tests/test_cognitive_policy.py`（163 项新增）覆盖决策字段、工具子集约束与不落原文；
- 规范：`docs/specs/structured-cognitive-policy.md`。

## 用户可见变化

- 对用户不可见的行为变化；为路由统计、故障定位与前端后续展示提供稳定字段。

## 验证情况

- `tests/test_cognitive_policy.py` 与既有路由/安全分类回归通过。

## 已知限制

- 不新增 LLM 分类调用，不阻断模型根据后续证据调整路线；
- 不实现策略配置后台、持久化、跨会话统计平台或前端展示；
- 本版本未部署。

## 相关记录

- GitLab Release：[智能分析 ontology-v0.0.7](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.7)
- 历史 tag：`v0.1.6`（2026-09-29 已随版本族切换删除，指向同一 commit `1ae9894`）
- 规范：[语义化版本与正式发布规范](./versioning-policy.md)
