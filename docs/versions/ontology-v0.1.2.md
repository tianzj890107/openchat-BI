# 智能分析 ontology-v0.1.2

## 基本信息

- 版本：`ontology-v0.1.2`
- 日期：`2026-10-15`
- 状态：正式版（历史版本；早于当前版本 `ontology-v0.1.3`）
- 版本位次：**PATCH**（`ontology-v0.1.1` → `ontology-v0.1.2`），版本号由用户在当前任务中明确指定
- 版本关系：`ontology-v0.1.0` 之后的交付是相邻两个 PATCH。`ontology-v0.1.1` = 分析逻辑剥离包
  `ontology-analytics-skill`（2026-10-08 合入 `master`，定版 commit `c82221f`，tag 与 Release 于
  2026-10-15 按用户要求补建，见 [ontology-v0.1.1.md](./ontology-v0.1.1.md)）；本版本在其之上补齐
  Fuxi 技能展示字段、`CanvasGenerate` 整页交付，并完成中文过程播报与交付口径收口。
- Release 分支：按用户明确指示**不拉出** release 分支（`hotfix/*` 需要时再从 `master` 拉 `release/*`）
- 定版 commit：`3c4de1e`（`feature/progress-narration-zh` 经 Merge Request `!23` 合入 `master` 的
  merge commit）
- Git Tag：`ontology-v0.1.2`（annotated，指向定版 commit `3c4de1e`，已推送 GitLab）
- GitLab Release：[智能分析 ontology-v0.1.2](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.2)（基于同名 tag 创建；创建不触发部署）

## 版本概述

ontology-v0.1.2 把**分析逻辑对外可移植**与**执行过程对用户可见**两件事收口：剥离包（本体由
`ontology-v0.1.1` 引入）不断补齐 Fuxi 技能展示字段与 `CanvasGenerate` 整页 HTML 交付，多步分析
补齐中文过程播报，同时把 `20260727` 统一协作分支正式归档、交付口径改为「临时分支 → `master`
Merge Request」。

本版本没有破坏性变更，也不改变服务器上正在运行的服务。版本号、tag、GitLab Release 与部署
各自独立授权：版本号与文档在同一交付分支收口，tag 与 GitLab Release 随后由用户单独授权创建，
部署仍未授权、未执行。

## 交付主题

### 1. 分析逻辑剥离包 `ontology-analytics-skill` 增量

- 剥离包本体（路由 → L1–L5 SOP → 五道闸门、真实工具运行时、17 个真实工具、凭据外置）在
  `ontology-v0.1.1` 引入；本版本在其上继续演进，供通用 Agent（如 Codex、Fuxi）在仓库外复现同一
  套分析行为；
- 对齐 Fuxi 技能展示字段（中文名、中文描述、`runtime: python` 依赖声明）；
- 主要文件：`ontology-analytics-skill/`（`SKILL.md`、`references/`、`scripts/`、`tools/`）。

### 2. CanvasGenerate 整页交付工具

- 新增 `CanvasGenerate`：通用 Agent 不再返回站点内的卡片 JSON，而是直接产出可独立打开的整页
  HTML（内联样式与本地 ECharts 资源），把分析结论、表格与图一次性交付；
- 同时修复渲染类工具未注册到运行时的缺陷（`TableGenerate` / `ChartGenerate` 需要按包内真实
  实现实例化后才能调用）；
- 主要文件：`ontology-analytics-skill/tools/canvas_tool.py`、`ontology-analytics-skill/tools/serve.py`、
  `ontology-analytics-skill/tools/selftest.py`、`ontology-analytics-skill/references/08-tools-and-sources.md`。

### 3. 多步分析中文过程播报（补丁窗口二）

- 新增常驻的「过程播报规范」：多步取数或分析时，首次调用工具前以及每次进入新的分析阶段时，
  先用一句业务化中文说明接下来要做什么、为什么，让用户看得见分析在进行；
- 播报不依赖可见思考开关与模型思考能力，任何模型、任何档位都会注入；单步即可完成的取数不强制
  播报，且仍禁止输出技术旁白、工具参数原文与 SOP/模板复述；
- 主要文件：`bi_agent/web/session.py`（`PROGRESS_NARRATION_RULE`）、`.claude/agents/bi-analyst.md`。

### 4. 交付口径：`20260727` 归档，临时分支 → `master`

- `20260727` 归档分支退役，停止接收新提交；日常开发在 `feature/*` / `bugfix/*` / `hotfix/*` 临时
  分支上进行，正式交付通过「临时分支 → `master`」的 Merge Request（reviewer `tianzijing`）完成；
- `scripts/push_gitlab.py` 收敛为归档分支的核对/补推辅助脚本，不再作为日常交付入口；
- 主要文件：`AGENTS.md`、`debug.md`、`docs/gitlab-push-workflow.md`、`docs/specs/master-mainline-delivery.md`、
  `docs/specs/repository-wide-master-branch-consistency.md`、`scripts/push_gitlab.py`。

### 5. 取数证据与双环境对比归档

- 把管理单元 `2800` 与 `101701` 实际执行的原始 SQL（全口径 / 已审批口径）与两个环境的取数结果
  对比归档为可追溯文档，便于核对口径差异；
- 主要文件：`docs/specs/executed-sql-management-units-2800-101701.md`。

### 6. 版本显示统一

- 显示与发布名统一为 `ontology-v0.1.2`：`bi_agent/__init__.py`、`bi_agent/web/app.py` `APP_VERSION`、
  `open_claude/__init__.py`、前端 `PRODUCT_VERSION` 与首屏版本 chip；
- 包管理清单保持强制例外：`pyproject.toml` 为 PEP 440 `0.1.2`，`frontend/package.json` 与
  `package-lock.json` 为 semver `0.1.2`；前端构建产物 `workbench.js` 同步重建。

## 验证结果

- 版本契约测试：`tests/test_versioning_policy.py`、`tests/test_ontology_version_rename_red.py`、
  `tests/test_regressions.py`、`tests/test_analytics_eval_dataset.py` 已同步到 `ontology-v0.1.2`；
- tag 契约：本版本 tag 已由用户授权创建，仓库 tag 现在恰好是 10 个 `ontology-v0.0.x` 加
  `ontology-v0.1.0`、`ontology-v0.1.2`；测试的 tag 白名单已同步更新；
- 前端构建：`cd frontend && npm run build` 重建 `bi_agent/web/static/vendor/antd/workbench.js`，
  构建前后可重复（同样的源码重复构建不产生额外 diff）；
- 全量测试与 `git diff --check` 结果见本版本合入的 Merge Request `!23`。

## 已知限制

- 本版本**未部署**：版本号、文档与前端构建产物都不改变服务器上正在运行的服务，部署需要用户
  在未来任务中单独授权；
- 本版本不拉 `release/ontology-v0.1.2` 分支（用户明确指示）；tag 与 GitLab Release 已按用户授权
  创建，创建不触发部署；
- 版本关系：剥离包本体属 `ontology-v0.1.1`（定版 commit `c82221f`）；本版本是其后的 PATCH
  （定版 commit `3c4de1e`）。两个版本都在 `master` 上、都已创建 GitLab Release，tag 未移动、
  未覆盖；
- 周 changelog 已在用户要求后建立：`changelog/changelog_10_12_16.md`（2026-10-12 至 2026-10-16），
  按本周 Git 记录补齐为最终状态。

## 相关记录

- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
- 分支模型：[Git 分支与合并工作流规范](../git-branch-workflow.md)
- 上一版本：[ontology-v0.1.1](./ontology-v0.1.1.md)（更早：[ontology-v0.1.0](./ontology-v0.1.0.md)）
- 下一版本：[ontology-v0.1.3](./ontology-v0.1.3.md)
- 交付口径：[master 交付主线说明](../specs/master-mainline-delivery.md)
- 周 changelog：[changelog_10_12_16.md](../../changelog/changelog_10_12_16.md)
