# 智能分析 ontology-v0.1.11

## 基本信息

- 版本：`ontology-v0.1.11`
- 历史合入日期：`2026-11-06`
- 实际补发日期：`2026-11-10`
- 状态：正式版 / 历史补发
- 版本位次：**PATCH**（`ontology-v0.1.10` → `ontology-v0.1.11`），用户明确授权补发
- 定版提交：`5f2a615cfa81106b740575a75072e78dfab43397`
- Git Tag：`ontology-v0.1.11`（annotated）
- GitLab Release：[智能分析 ontology-v0.1.11](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.11)

## 版本概览

`ontology-v0.1.11` 是 Workbench Pro UI 与 Cockpit 期间缓存 PATCH，承接 `ontology-v0.1.10`。
历史合入日期：2026-11-06；实际补发日期：2026-11-10。

## 主要变化

- Workbench 整页迁移到 Pro UI React 外壳与组件，设置面板改为声明式配置并移除 DOM 轮询；
  侧边栏控件统一，会话支持按轮次导航，聊天区恢复全高布局。
- 助手消息改为扁平化转录，图表与可视化保留在结果板；本体命中改为共享图谱视图，
  按可见输出分组执行，只展示已检索命中，缩放时节点保持固定尺寸。
- Cockpit 按期间缓存分析结果并合并并发刷新请求，刷新期间持续发布；新增期间发布索引与
  期间计划，AP 模板缺期间时自动补期间过滤，默认读取落在已交付期间。
- 共同分析预热时保留部分 AP 证据，避免刷新后证据整体丢失。

## 验证

- 已核对定版提交与 `ontology-v0.1.10..5f2a615` 的完整提交范围。
- 补发时不重跑该历史提交的全量业务测试，不宣称历史缺口全部关闭。

## 边界

- 本版本包含 Cockpit 期间缓存，不含其后的客户离线部署、冻结年度发布和 AI 卡片重构。
- Tag 指向 master 合并定版 `5f2a615cfa81106b740575a75072e78dfab43397`；
  后补文档不在该 tag 中。
- 本次补发不触发部署，不创建 release 分支，不修改已有 tag 或 Release。

## 相关记录

- 上一版本：[ontology-v0.1.10](./ontology-v0.1.10.md)
- 下一版本：[ontology-v0.1.12](./ontology-v0.1.12.md)
- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
