# 智能分析 ontology-v0.1.0

## 基本信息

- 版本：`ontology-v0.1.0`
- 日期：`2026-09-29`
- 状态：正式版 / 当前版本
- 版本位次：**MINOR**（`ontology-v0.0.10` → `ontology-v0.1.0`），由用户在当前任务中明确指定
- Release 分支：`release/ontology-v0.1.0`（已拉出；内容与本版本一致，尚未对齐到合入 commit）
- 定版 commit：`74fca80`（`feature/branch-model-and-v0.1.0-cut` 经 Merge Request 合入 `master`）
- Git Tag：`ontology-v0.1.0`（annotated，指向定版 commit `74fca80`，已推送 GitLab）
- GitLab Release：[智能分析 ontology-v0.1.0](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.0)（基于同名 tag 创建）

## 版本概述

ontology-v0.1.0 把过去一个迭代周期的交付整体收口：本体服务数据湖从旧引擎切换到 PG 后
的连接与查询链路修复、本体对象解析与元数据契约迁移、分析 Agent 评测门禁与意图路由加固、
Web 侧会话回收站与匿名读取面收敛、X360 流程定义集成，以及配套图表与文档。

其中会话回收站、X360 流程定义集成、本体对象解析/仓库详情等属于**新增的用户可感知能力**
且保持向下兼容，因此按语义化版本规则升级为 MINOR，而不是 PATCH。

## 交付主题

### 1. PDT 本体数据湖切换 PG 引擎（端到端 + 改善批次）

- 数据湖由旧引擎切到 PG 后，连接层、SQL 方言、分页与类型映射按 PG 语义重写，端到端
  R1–R7 全部转绿；
- 落地用户圈定的第 2/3/4/6/7/8/10 条改善项：分片降级不再被答成"环境故障"、错误文案不再
  外泄连接串、文案不再自称 Doris、网关与本地白名单口径一致、表头与空态陈述真实库名、
  规模与主键按 PG 元数据给出（无估算时显式 `unknown rows`）、本体库编号错误时列出可用编号；
- 主要文件：`bi_agent/tools/sql_tools.py`、`bi_agent/tools/remote_ontology_tools.py`、
  `bi_agent/web/app.py`、`DEPLOYMENT.md`。

### 2. 本体对象解析、元数据分页查询与 MAL 契约

- 元数据改走文档化的分页树查询接口；对象确认统一经权威接口，并暴露仓库详情；
- 完成 MAL 契约迁移并刷新接口文档，契约以离线测试固化；
- 主要文件：`bi_agent/ontology/*`、`API/*.md`。

### 3. 分析 Agent 评测门禁与意图路由

- 补齐安全拒绝、动作、元数据、预测类意图路由；
- 跨会话泄漏可离线度量并重平衡线上域分布；因果与代理真实性门禁可离线测量；
- 发布重复稳定性由"形同虚设"改为真实测量门禁；
- 主要文件：`bi_agent/tools/*`、`dataset/evals/*`、`scripts/run_analytics_eval.py`。

### 4. 会话回收站与匿名读取面收敛

- 删除会话改为移入回收站，保留期内可恢复；不做物理删除，历史会话与用户数据不被清空或覆盖；
- 匿名可读取面按线上验收结论收敛；
- 主要文件：`bi_agent/web/*`、`frontend/src/*`。

### 5. X360 流程定义集成

- 任务告警的流程定义改为从 X360 AI 视图解析获取，替代原先写死或间接的取值路径；
- 主要文件：`bi_agent/x360/*`。

### 6. 版本族与分支规范

- 版本族已由 `v0.1.x` 切换为 `ontology-v0.0.x`，本版本在此基础上推进到 `ontology-v0.1.0`；
- 补充分支模型与 PR 合并工作流规范（`docs/git-branch-workflow.md`）及契约测试；
- 包管理清单仍保持强制例外：`pyproject.toml` 为 PEP 440 `0.1.0`，`frontend/package*.json`
  为 semver `0.1.0`，显示与发布名统一由 `product_version()` 补 `ontology-v` 前缀。

### 7. 图表与文档

- 分析 Agent 与企业智能体平台架构图迭代（六层 20 块、显式本体层与 L1–L5 升级链路、默认浅色主题）；
- 新增 16:9 业务全景图、端到端流程图拆分、数据源模板与本体消费说明。

## 验证结果

- 全量测试：`1282 passed / 0 failed / 25 skipped / 1070 subtests passed`（本地 venv；已包含同日合入的
  稳定性门禁修复 `1427319`）；
- CI：收口分支 pipeline 3290 的 `unit-tests`、`repeat-stability`、`regression`、
  `recorded-provider`、`smoke` 全部 success（`live-canary`、`release-gate` 按设计保持 manual）；
- tag 契约双向验证：tag 不存在时 44 passed / 26 subtests，创建 tag `ontology-v0.1.0` 后
  31 passed / 19 subtests。

## 已知限制

- 本版本未部署：版本号、release 分支、tag 与 Release 都不改变服务器上正在运行的服务，部署需
  用户在未来任务中单独授权；
- `master` 仍是唯一发布主线；本收口通过 `feature/branch-model-and-v0.1.0-cut` → `master` 的
  Merge Request `!17` 由 `tianzijing` code review 后合并（`74fca80`）；
- 版本契约测试中的 tag 断言要求既有 10 个 `ontology-v0.0.x` tag 存在，并只允许再多本版本的
  `ontology-v0.1.0`（tag 已创建；多余 tag 仍会被拦住）。

## 相关记录

- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
- 分支模型：[Git 分支与合并工作流规范](../git-branch-workflow.md)
- 周 changelog：[changelog_9_28_10_2.md](../../changelog/changelog_9_28_10_2.md)
