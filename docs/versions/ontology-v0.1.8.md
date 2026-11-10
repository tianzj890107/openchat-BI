# 智能分析 ontology-v0.1.8

## 基本信息

- 版本：`ontology-v0.1.8`
- 历史合入日期：`2026-11-02`
- 实际补发日期：`2026-11-03`
- 状态：正式版 / 历史补发
- 版本位次：**PATCH**（`ontology-v0.1.7` → `ontology-v0.1.8`），用户明确授权补发
- 定版提交：`8f673fc5c6f118b3fb20ad897155798bc176c77b`
- Git Tag：`ontology-v0.1.8`（annotated）
- GitLab Release：[智能分析 ontology-v0.1.8](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.8)

## 版本概览

`ontology-v0.1.8` 是 风险交付与评测体系 PATCH，承接 `ontology-v0.1.7`。历史合入日期：2026-11-02；实际补发日期：2026-11-03。

## 主要变化

- 新增驾驶舱业务黄金评测及缺口诊断，完善交付文本和证据裁剪。
- 风险事实与原因分开，风险数量连接看板运行时，调查草稿和整改草稿独立生成。
- 恢复 8876 兼容代理，规范宿主自定义颜色及任务令弹窗样式。
- 本阶段还纳入可选 LangGraph 实验引擎及 Canvas 任务令相关分支。

## 验证

- 历史定版提交及相对上一版本的提交范围已核对；本次补发不重新运行这些历史版本的业务全量测试，也不宣称历史缺口全部关闭。

## 边界

- 实验引擎保持可选，不代表默认路线；黄金评测不替代真实数据和 Fuxi 端到端验收。
- 本 Release 指向历史定版 `8f673fc5c6f118b3fb20ad897155798bc176c77b`，保留该提交原有版本标识；后补文档不在历史 tag 中。
- 本次补发不触发部署，不创建 release 分支，不修改已有 tag 或 Release。

## 相关记录

- 上一版本：[ontology-v0.1.7](./ontology-v0.1.7.md)
- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
