# 智能分析 ontology-v0.1.6

## 基本信息

- 版本：`ontology-v0.1.6`
- 历史合入日期：`2026-10-30`
- 实际补发日期：`2026-11-03`
- 状态：正式版 / 历史补发
- 版本位次：**PATCH**（`ontology-v0.1.5` → `ontology-v0.1.6`），用户明确授权补发
- 定版提交：`3b1bc1e6b3a237179a57cd125cda380f6ce19388`
- Git Tag：`ontology-v0.1.6`（annotated）
- GitLab Release：[智能分析 ontology-v0.1.6](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.6)

## 版本概览

`ontology-v0.1.6` 是 Process360 闭环与驾驶舱分析运行时 PATCH，承接 `ontology-v0.1.5`。历史合入日期：2026-10-30；实际补发日期：2026-11-03。

## 主要变化

- Process360 五场景、本体取证、服务端冻结基准、可信草稿与 Fuxi 下发链路。
- 驾驶舱全 AI 插槽独立发布、预热与服务端静默刷新，清退旧范围调度，减少重复加载。
- AP 失败受控 PostgreSQL 补查、节点证据隔离、报价状态取证及订单数据表。
- Workbench、Cockpit 与分析 MCP 共享执行运行时。

## 验证

- 历史定版提交及相对上一版本的提交范围已核对；本次补发不重新运行这些历史版本的业务全量测试，也不宣称历史缺口全部关闭。

## 边界

- 包含证据、权限、草稿下发和缓存边界实现；业务映射、审批目标与宿主联调仍需按场景验收。
- 本 Release 指向历史定版 `3b1bc1e6b3a237179a57cd125cda380f6ce19388`，保留该提交原有版本标识；后补文档不在历史 tag 中。
- 本次补发不触发部署，不创建 release 分支，不修改已有 tag 或 Release。

## 相关记录

- 上一版本：[ontology-v0.1.5](./ontology-v0.1.5.md)
- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
