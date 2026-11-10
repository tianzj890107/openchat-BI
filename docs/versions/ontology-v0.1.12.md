# 智能分析 ontology-v0.1.12

## 基本信息

- 版本：`ontology-v0.1.12`
- 历史合入日期：`2026-11-09`
- 实际补发日期：`2026-11-10`
- 状态：正式版 / 历史补发
- 版本位次：**PATCH**（`ontology-v0.1.11` → `ontology-v0.1.12`），用户明确授权补发
- 定版提交：`6f051934351c46344fd02cffb0c53ad427a12160`
- Git Tag：`ontology-v0.1.12`（annotated）
- GitLab Release：[智能分析 ontology-v0.1.12](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.12)

## 版本概览

`ontology-v0.1.12` 是客户离线部署、冻结年度 AI 发布与交互收敛 PATCH，承接 `ontology-v0.1.11`。
历史合入日期：2026-11-09；实际补发日期：2026-11-10。

## 主要变化

- 生成客户 DDL 对齐的 Process360 V3.1 本体工作簿与 catalog，并补充 YWLN V3.1 本体元素边界文档。
- 新增客户离线镜像部署；连接配置全部由环境变量提供，Fuxi 连接器由客户环境推导，不再内置凭据。
- Cockpit 交付冻结年度 AI 发布与显式刷新；预设只在用户点击分析后展示，静默分析控件移入卡片元信息，
  前两页移除宿主分析工具栏。
- 同步上游默认表格排序；表格本地查询不触发环节分析刷新；x360 前缀统一归入 AP 网关 base。
- 手动模式、精确回执与可复现客户构建完成对账。

## 验证

- 已核对定版提交与 `ontology-v0.1.11..6f05193` 的完整提交范围。
- 补发时不重跑该历史提交的全量业务测试，不宣称历史缺口全部关闭。

## 边界

- 本版本包含客户离线部署与冻结年度发布，不含其后的卡片优先刷新、AI 卡片契约重构和原型样式收口。
- Tag 指向 master 合并定版 `6f051934351c46344fd02cffb0c53ad427a12160`；
  后补文档不在该 tag 中。
- 本次补发不触发部署，不创建 release 分支，不修改已有 tag 或 Release。

## 相关记录

- 上一版本：[ontology-v0.1.11](./ontology-v0.1.11.md)
- 下一版本：[ontology-v0.1.13](./ontology-v0.1.13.md)
- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
