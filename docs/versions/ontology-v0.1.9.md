# 智能分析 ontology-v0.1.9

## 基本信息

- 版本：`ontology-v0.1.9`
- 历史合入日期：`2026-11-02`
- 实际补发日期：`2026-11-03`
- 状态：正式版 / 历史补发
- 版本位次：**PATCH**（`ontology-v0.1.8` → `ontology-v0.1.9`），用户明确授权补发
- 定版提交：`c5ce13922ab638b19e0ce7dadc42d657b4a4a263`
- Git Tag：`ontology-v0.1.9`（annotated）
- GitLab Release：[智能分析 ontology-v0.1.9](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.9)

## 版本概览

`ontology-v0.1.9` 是 驾驶舱展示与任务下发收口 PATCH，承接 `ontology-v0.1.8`。历史合入日期：2026-11-02；实际补发日期：2026-11-03。

## 主要变化

- 风险按业务事实去重，局部表格筛选与其他组件加载隔离。
- 补充经 AP 验证的客户覆盖数量，修复报价状态，隐藏宿主元数据诊断与无关提示。
- 增加有证据支撑的调查步骤、阶段策略预热接口及任务下发日历期限校验。
- 同步 ProUI 品牌色板，筛选切换保留旧结果并以提示文字说明后台更新。

## 验证

- 历史定版提交及相对上一版本的提交范围已核对；本次补发不重新运行这些历史版本的业务全量测试，也不宣称历史缺口全部关闭。

## 边界

- 接收人、任务权限、上游 AP 可用性取决于各环境配置；不保证所有业务原因已获证明。
- 本 Release 指向历史定版 `c5ce13922ab638b19e0ce7dadc42d657b4a4a263`，保留该提交原有版本标识；后补文档不在历史 tag 中。
- 本次补发不触发部署，不创建 release 分支，不修改已有 tag 或 Release。

## 相关记录

- 上一版本：[ontology-v0.1.8](./ontology-v0.1.8.md)
- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
