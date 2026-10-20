# 智能分析 ontology-v0.1.1

## 基本信息

- 版本：`ontology-v0.1.1`
- 日期：`2026-10-08`（内容定版日；tag 与 GitLab Release 于 `2026-10-15` 按用户要求补建）
- 状态：正式版（历史版本；早于当前版本 `ontology-v0.1.3`）
- 版本位次：**PATCH**（`ontology-v0.1.0` → `ontology-v0.1.1`），由用户在当前任务中明确要求补建
- Release 分支：无（不拉 release 分支；`hotfix/*` 需要时再从 `master` 拉 `release/*`）
- 定版 commit：`c82221f`（`feature/analytics-logic-extraction-pack` 经 Merge Request 合入 `master`
  的 merge commit，2026-10-08）
- Git Tag：`ontology-v0.1.1`（annotated，指向定版 commit `c82221f`，已推送 GitLab；补建，未移动任何
  已发布 tag）
- GitLab Release：[智能分析 ontology-v0.1.1](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.1)（基于同名 tag 创建；创建不触发部署）

## 命名说明（避免与已退役的旧 `v0.1.1` 混淆）

- 2026-09-02 曾存在一个名字就是 `v0.1.1` 的 tag（commit `28bb1d6`）；它在 2026-09-29 的版本族切换中
  被改名为 `ontology-v0.0.2`，仍然指向同一个 commit。
- 本版本 `ontology-v0.1.1` 是 `ontology-v0.1.0` 之后的 PATCH，与该旧 tag 无关；旧号码族 `v0.1.x`
  已退役，不再使用。

## 版本概述

ontology-v0.1.1 把分析 Agent 的**整套分析逻辑从系统里剥离出来**，做成可以交给通用 Agent（如
Codex、Fuxi）在仓库外复现同一套分析行为的自包含交付目录 `ontology-analytics-skill`：确定性路由
→ L1–L5 分档 SOP → 交付前五道闸门，并补齐真实工具运行时（17 个真实工具）与离线自检用例。

本版本对仓库现有代码是**纯新增**：不改任何现有代码、配置或 Prompt，也不改变线上服务行为，因此
按语义化版本规则为 PATCH 而不是 MINOR。

## 交付主题

### 1. 分析逻辑剥离包 `ontology-analytics-skill`

- 入口工作流（路由 → L1–L5 SOP → 五道交付闸门）与交付说明：`SKILL.md`、`README.md`；
- 规则正文 `references/01–10`：SOP、分档模板、纪律、深入洞察、命名规则、路由规则、五道闸门、
  工具与数据源、图库模式、角色风格；
- 确定性 CLI：`scripts/route.py`、`scripts/gates.py`（仅标准库），规则真源在 `scripts/vendor/`；
- 冻结用例：`cases/routing_cases.jsonl` 137 条、`cases/gate_cases.jsonl` 23 条。

### 2. 剥离包真实工具运行时 `tools/`（方案 C，凭据外置）

- `tools/serve.py`：CLI / JSONL 入口，按配置装配本体（远程服务 / 本地 Excel）与取数后端
  （Doris HTTP 网关 / Doris MySQL / 本地 SQLite），暴露 **17 个真实工具**；
- `tools/_vendor/`：真实工具实现原样副本（基线提交 `cc4a134`，31 个文件），仅两处可缺失导入的
  最小改动，详见 `_vendor/README.md`；
- 凭据不随包交付：只从仓库外自建文件（`~/.config/ontology-analytics/credentials.env`，600 权限）
  或进程环境变量读取，`tools/.gitignore` 已忽略本地凭据文件；
- `tools/selftest.py`（离线自检）、`tools/config.example.env`（只有变量名、无值）、`tools/README.md`。

### 3. 工程记录

- 预建 2026-10-05 至 2026-10-09 周 changelog 文件（`0df7617`）；属工程记录，不是用户可见能力。

## 与相邻版本的关系

- 上一版本：`ontology-v0.1.0`（定版 commit `74fca80`）；
- 下一版本：`ontology-v0.1.2`（定版 commit `3c4de1e`），剥离包在该版本中继续演进（Fuxi 技能展示
  字段对齐、`CanvasGenerate` 整页 HTML 交付）；
- 本版本定版 commit `c82221f` 早于 `ontology-v0.1.2` 的定版 commit `3c4de1e`，两者都在 `master` 上。

## 验证结果

- 剥离包自检：`python3 scripts/selfcheck.py` → routing 137/137、gates 23/23、**160/160**；
- 工具运行时自检：`python3 tools/selftest.py` → **ok**（17 个工具、临时 SQLite 端到端取值、
  `DELETE` 被只读守卫拒绝）；
- 内网实测：`python3 tools/serve.py --call ListBusinessObjects` 返回真实业务对象；
- 本次补建 tag 与 Release 属记录补建，无代码变更（内容已于 2026-10-08 合入 `master` 并当时验证）。

## 已知限制

- 本版本**未部署**；tag 与 GitLab Release 创建都不改变服务器上正在运行的服务；
- 不拉 `release/ontology-v0.1.1` 分支；
- 本版本的 tag 与 Release 属**事后补建**：内容于 2026-10-08 合入 `master`，tag 于 2026-10-15 补建，
  因此 GitLab 上 Release 的创建时间晚于 `ontology-v0.1.2`，但所指向的 commit 早于它；补建只新建对象，
  未覆盖、未移动任何已有 tag 或 Release。

## 相关记录

- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
- 分支模型：[Git 分支与合并工作流规范](../git-branch-workflow.md)
- 上一版本：[ontology-v0.1.0](./ontology-v0.1.0.md)
- 下一版本：[ontology-v0.1.2](./ontology-v0.1.2.md)
- 周 changelog：[changelog_10_12_16.md](../../changelog/changelog_10_12_16.md)
