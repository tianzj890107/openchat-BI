# 智能分析 ontology-v0.1.7

## 基本信息

- 版本：`ontology-v0.1.7`
- 历史合入日期：`2026-10-30`
- 实际补发日期：`2026-11-03`
- 状态：正式版 / 历史补发
- 版本位次：**PATCH**（`ontology-v0.1.6` → `ontology-v0.1.7`），用户明确授权补发
- 定版提交：`4c63e4d3b08d757111e8c64ee17f7e9a784ae9be`
- Git Tag：`ontology-v0.1.7`（annotated）
- GitLab Release：[智能分析 ontology-v0.1.7](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.7)

## 版本概览

`ontology-v0.1.7` 是 部署收敛与分析可信性修复 PATCH，承接 `ontology-v0.1.6`。历史合入日期：2026-10-30；实际补发日期：2026-11-03。

## 主要变化

- 明确每环境一个分析容器及网关路由的部署方式。
- 删除无依据的流失判断、跨单位原因推断，收紧各插槽分析交付边界。
- 修复风险标签及订单表筛选契约。

## 验证

- 历史定版提交及相对上一版本的提交范围已核对；本次补发不重新运行这些历史版本的业务全量测试，也不宣称历史缺口全部关闭。

## 边界

- 统一路由配置仍需在目标环境落实；不因历史补发重新部署。
- 本 Release 指向历史定版 `4c63e4d3b08d757111e8c64ee17f7e9a784ae9be`，保留该提交原有版本标识；后补文档不在历史 tag 中。
- 本次补发不触发部署，不创建 release 分支，不修改已有 tag 或 Release。

## 相关记录

- 上一版本：[ontology-v0.1.6](./ontology-v0.1.6.md)
- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
