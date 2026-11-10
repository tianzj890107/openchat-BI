# 智能分析 ontology-v0.1.10

## 基本信息

- 版本：`ontology-v0.1.10`
- 历史合入日期：`2026-11-03`
- 实际补发日期：`2026-11-03`
- 状态：正式版 / 历史补发
- 版本位次：**PATCH**（`ontology-v0.1.9` → `ontology-v0.1.10`），用户明确授权补发
- 定版提交：`179a0cf7b74d2de4faca9a1979764fddb763af77`
- Git Tag：`ontology-v0.1.10`（annotated）
- GitLab Release：[智能分析 ontology-v0.1.10](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.10)

## 版本概览

`ontology-v0.1.10` 是 Workbench 本地 Excel 与只读 PostgreSQL PATCH，承接 `ontology-v0.1.9`。历史合入日期：2026-11-03；实际补发日期：2026-11-03。

## 主要变化

- 新增独立 WORKBENCH_PG_* 配置和 PostgreSQL · ywln_crm 数据源选项。
- 选择后绑定本地 Excel 本体，支持实体、属性及关系映射，独立于客户 Process360 连接配置。
- 支持 PostgreSQL 只读取数、表结构查看、查询超时和结果数量限制。

## 验证

- 历史定版提交及相对上一版本的提交范围已核对；本次补发不重新运行这些历史版本的业务全量测试，也不宣称历史缺口全部关闭。 本地 Excel + PG 功能已有 11 项新增测试通过；34 上已验证只读连接、ywln_crm schema、Workbench 页面及 8765/8876 入口正常。

## 边界

- 不含未合并的 Workbench 前端改版；缺少字段映射的属性保持受限。
- 本 Release 指向历史定版 `179a0cf7b74d2de4faca9a1979764fddb763af77`，保留该提交原有版本标识；后补文档不在历史 tag 中。
- 本次补发不触发部署，不创建 release 分支，不修改已有 tag 或 Release。

## 相关记录

- 上一版本：[ontology-v0.1.9](./ontology-v0.1.9.md)
- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
