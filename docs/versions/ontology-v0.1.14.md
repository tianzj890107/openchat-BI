# 智能分析 ontology-v0.1.14

## 基本信息

- 版本：`ontology-v0.1.14`
- 定版日期：`2026-11-10`
- 状态：正式版 / 当前版本
- 版本位次：**PATCH**（`ontology-v0.1.13` → `ontology-v0.1.14`），用户明确授权发布
- 定版提交：`7c586b29c9106f8186fea5d59c3768d6cf0710c4`
- Git Tag：`ontology-v0.1.14`（annotated）
- GitLab Release：[智能分析 ontology-v0.1.14](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.14)

## 版本概览

`ontology-v0.1.14` 是 Cockpit AI 卡片交付与 AP/DeepSeek 契约 PATCH，承接 `ontology-v0.1.13`。

## 主要变化

- AP-only 分析改为有界取数，按卡片显示进度与同步后的元信息；被拒绝的 AP 指标组合自动拆分，
  只请求上游已实现的组合与日期口径。
- DeepSeek reasoning 先保存再回传；空 assistant 轮不再发送；旧记录缺失 reasoning 时保留工具结果做
  兼容降级，不伪造、不重复执行工具。
- 卡片以业务维度替代数据缺口 findings，风险与原因按编号关联；共同分析按原型排版并高亮数字。
- 完整证据复用 MCP canvas 页面；显示分析耗时；刷新状态移到操作之后；模型 token 耗尽时仍发布受限卡片。
- 合并分析独立运行并支持增量交付，同步更新 BI SDK 与客户交付镜像。

## 验证

- 已核对 `ontology-v0.1.13..7c586b2` 的完整提交范围，并覆盖 0.1.6–0.1.10 的版本补发收口提交。
- 本次发布前已运行 Cockpit 相关 Python/Node 测试；补发不重跑历史提交的全量业务测试，
  不宣称历史缺口全部关闭。

## 边界

- 不含定版后仍在临时分支上的共同分析颜色/数字高亮等后续提交，这些提交需另行合并后再评估下一版本。
- Tag 指向 master 合并定版 `7c586b29c9106f8186fea5d59c3768d6cf0710c4`；
  后补版本文档与版本号提交不在该 tag 中。
- 本次发布不触发部署，不创建 release 分支，不修改已有 tag 或 Release。

## 相关记录

- 上一版本：[ontology-v0.1.13](./ontology-v0.1.13.md)
- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
