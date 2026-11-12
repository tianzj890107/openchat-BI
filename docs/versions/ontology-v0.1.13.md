# 智能分析 ontology-v0.1.13

## 基本信息

- 版本：`ontology-v0.1.13`
- 历史合入日期：`2026-11-09`
- 实际补发日期：`2026-11-10`
- 状态：正式版 / 历史补发
- 版本位次：**PATCH**（`ontology-v0.1.12` → `ontology-v0.1.13`），用户明确授权补发
- 定版提交：`f887aad8518c1dabc580266e2776cceb22a6945b`
- Git Tag：`ontology-v0.1.13`（annotated）
- GitLab Release：[智能分析 ontology-v0.1.13](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.13)

## 版本概览

`ontology-v0.1.13` 是卡片优先刷新与分析诊断 PATCH，承接 `ontology-v0.1.12`。
历史合入日期：2026-11-09；实际补发日期：2026-11-10。

## 主要变化

- Cockpit 按可见性优先分析卡片，各阶段成功即独立发布，不再等待整页所有阶段完成。
- 手动刷新显式重算所点击卡片并重新排队；手动年度刷新正确读取 AP 数据 envelope。
- 分析失败诊断脱敏后持久化；注册补数错误进入后端诊断；表格过滤条件去重。
- 卡片刷新状态与按钮位置收敛为安静的单卡操作。

## 验证

- 已核对定版提交与 `ontology-v0.1.12..f887aad` 的完整提交范围。
- 补发时不重跑该历史提交的全量业务测试，不宣称历史缺口全部关闭。

## 边界

- 本版本聚焦刷新顺序与分析诊断，不含其后的 AI 卡片有界取数、DeepSeek 工具回传和共同分析原型排版。
- Tag 指向 master 合并定版 `f887aad8518c1dabc580266e2776cceb22a6945b`；
  后补文档不在该 tag 中。
- 本次补发不触发部署，不创建 release 分支，不修改已有 tag 或 Release。

## 相关记录

- 上一版本：[ontology-v0.1.12](./ontology-v0.1.12.md)
- 下一版本：[ontology-v0.1.14](./ontology-v0.1.14.md)
- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
