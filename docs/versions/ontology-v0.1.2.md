# 智能分析 ontology-v0.1.2

## 基本信息

- 版本：`ontology-v0.1.2`
- 日期：`2026-10-15`
- 状态：正式版 / 当前版本
- 版本位次：**PATCH**（`ontology-v0.1.0` → `ontology-v0.1.2`），版本号由用户在当前任务中明确指定
- 补丁窗口说明：本次含两个补丁窗口的内容一起发布。窗口一（对应 `v0.1.1`）是分析逻辑剥离包
  `ontology-analytics-skill` 的收尾，窗口二（对应 `v0.1.2`）是多步分析的中文过程播报与交付口径
  收口；两个窗口落在同一条交付分支上，用户明确要求按 `ontology-v0.1.2` 一次性收口，因此不单独
  发布 `v0.1.1`，也不为它创建版本文档或 tag。
- Release 分支：`release/ontology-v0.1.2`（尚未拉出；拉出需要用户单独授权）
- 定版 commit：本版本由 `feature/progress-narration-zh` → `master` 的 Merge Request `!23`
  收口，合入后的 `master` commit 即定版 commit（创建 tag 时以该 commit 为准）
- Git Tag：尚未创建（用户未授权 tag）
- GitLab Release：尚未创建（用户未授权 Release）

## 版本概述

ontology-v0.1.2 是把分析 Agent 的**分析逻辑对外可移植**与**执行过程对用户可见**两件事收口：
分析逻辑剥离包补齐了真实工具运行时与整页交付工具，多步分析补齐了中文过程播报，同时把
`20260727` 统一协作分支正式归档、交付口径改为「临时分支 → `master` Merge Request」。

本版本没有破坏性变更，也不改变服务器上正在运行的服务。版本号、tag、GitLab Release 与部署
各自独立授权：本版本只完成了版本号与文档收口，tag 与 Release 需要用户另行授权。

## 交付主题

### 1. 分析逻辑剥离包 `ontology-analytics-skill` 收尾（补丁窗口一）

- 把分析 Agent 的整套分析逻辑（确定性路由 → L1–L5 分档 SOP → 交付前五道闸门）剥离为自包含
  交付目录，供通用 Agent（如 Codex、Fuxi）在仓库外复现同一套分析行为；
- 接入真实工具运行时：按配置装配本体（远程服务 / 本地工作簿）与取数后端，暴露 17 个真实工具，
  凭据不随包交付、只从仓库外自建文件或进程环境变量读取；
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
- tag 契约：本版本尚未创建 tag，仓库本地 tag 仍是 10 个 `ontology-v0.0.x` 加 `ontology-v0.1.0`；
  测试的 tag 白名单已在用户授权创建新 tag 后再行更新；
- 前端构建：`cd frontend && npm run build` 重建 `bi_agent/web/static/vendor/antd/workbench.js`，
  构建前后可重复（同样的源码重复构建不产生额外 diff）；
- 全量测试与 `git diff --check` 结果见本版本合入的 Merge Request `!23`。

## 已知限制

- 本版本**未部署**：版本号、文档与前端构建产物都不改变服务器上正在运行的服务，部署需要用户
  在未来任务中单独授权；
- 本版本**未创建 tag、未创建 GitLab Release、未拉出 `release/ontology-v0.1.2` 分支**，三者都需要
  用户单独授权；
- `v0.1.1` 未单独发布：剥离包（窗口一）与其后的过程播报（窗口二）在同一条交付分支上一起收口为
  `ontology-v0.1.2`，因此没有 `ontology-v0.1.1` 的版本文档与 tag，`ontology-v0.1.1` 不构成
  已发布版本，后续不得复用该号码；
- 本仓库当前周（2026-10-12 起）的周 changelog 文件尚未建立，按仓库规则不擅自新建；需要时由用户
  明确要求后按本周 Git 记录补齐。

## 相关记录

- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
- 分支模型：[Git 分支与合并工作流规范](../git-branch-workflow.md)
- 上一版本：[ontology-v0.1.0](./ontology-v0.1.0.md)
- 交付口径：[master 交付主线说明](../specs/master-mainline-delivery.md)
