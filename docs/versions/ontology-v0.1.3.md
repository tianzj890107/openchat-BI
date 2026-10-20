# 智能分析 ontology-v0.1.3

## 基本信息

- 版本：`ontology-v0.1.3`
- 日期：`2026-10-20`
- 状态：正式版 / 当前版本
- 版本位次：**PATCH**（`ontology-v0.1.2` → `ontology-v0.1.3`），版本号由用户在当前任务中明确指定
- 版本关系：在 `ontology-v0.1.2` 的分析逻辑剥离包、中文过程播报与整页交付基础上，把
  Fuxi / 通用 Agent 的接入方式收口为主服务内置远程 MCP，并完成 demo2 环境下的兼容性与性能修复。
- Release 分支：不单独拉出；通过 `feature/mcp-server-policy` → `master` 的 Merge Request 评审合并
- 定版 commit：本 Merge Request 合入 `master` 后的 merge commit
- Git Tag：`ontology-v0.1.3` 是本版本发布标识；tag 与 GitLab Release 均按独立授权执行，不随
  版本号修改、commit、push 或 MR 合并自动创建
- GitLab Release：基于同名 tag 创建，只有在用户单独授权 tag 与 Release 后才执行

## 版本概述

ontology-v0.1.3 对用户最重要的变化，是 Fuxi 接入不再依赖每台机器上的本地服务、Python 运行时和
`.env` 凭据。主服务直接提供 Streamable HTTP MCP，连接方只配置一个 HTTP 地址即可调用同一套分析
工具；凭据、数据集和原始 SQL 能力继续留在服务端，并通过硬性工具白名单收敛权限。

本版本同时修复了 demo2 经开发机代理访问时的 502 / 超时问题，补齐本体语义检索快路径，并把前端、
Python 包、FastAPI 与版本文档统一到 `ontology-v0.1.3`。版本收口、MR、tag、Release 与部署仍是
彼此独立的动作。

## 交付主题

### 1. 主服务内置远程 MCP

- 主服务 `bi_agent.web` 新增 `/api/mcp`，Fuxi 使用 `transport: http` 直接连接；
- 对外提供 16 个真实分析工具，包括 `AnalysisRoute`、`Ontology-SemanticQuery`、
  `MetricCalculation`、`MetricFactQuery`、`ChartGenerate`、`TableGenerate`、`CanvasGenerate`、
  `OutputGateCheck` 等；
- 工具执行复用 Web 对话的 `build_source_executors`，不维护第二套取数与分析实现；
- 硬性不暴露 `AnalysisRun`、`AskUser`、`TodoWrite`、`Ontology-FactQuery`、`ListTables`、
  `DescribeTable`，避免通用 Agent 绕过分析纪律或直接接触原始 SQL 工具；
- 主要文件：`bi_agent/web/mcp_endpoint.py`、`bi_agent/web/app.py`、
  `bi_agent/tools/remote_ontology_tools.py`、`ontology-analytics-mcp/`。

### 2. Fuxi 与技能包交付口径

- `ontology-analytics-skill` 只保留路由、SOP、交付闸门和纯规则脚本，不再随包分发真实工具运行时、
  凭据和服务启动逻辑；
- 通用 Agent 通过远程 MCP 调用真实工具，`CanvasGenerate` 返回可下载的 Artifact URL，不再暴露
  服务端暂存路径；
- 主要文件：`ontology-analytics-skill/SKILL.md`、`ontology-analytics-skill/README.md`、
  `ontology-analytics-skill/references/`、`ontology-analytics-mcp/README.md`。

### 3. 连接稳定性与查询性能

- 本体客户端默认绕过开发机 `HTTP_PROXY` / `HTTPS_PROXY`，修复 demo2 访问中的 502 和 30 秒超时；
- 语义检索优先走 metadata LIKE；Indicator 命中后停止继续扫描其他对象类型；
- 主要文件：`bi_agent/ontology/remote.py`、`bi_agent/tools/remote_ontology_tools.py`。

### 4. 版本显示与文档收口

- 显示版本统一为 `ontology-v0.1.3`：`bi_agent/__init__.py`、`open_claude/__init__.py`、
  `bi_agent/web/app.py` `APP_VERSION`、前端 `PRODUCT_VERSION` 与首屏版本标签；
- 包管理清单保持强制例外：`pyproject.toml` 为 PEP 440 `0.1.3`，`frontend/package.json` 与
  `package-lock.json` 为 semver `0.1.3`；前端构建产物 `workbench.js` 同步重建；
- 版本文档、版本索引、根 README、版本规范与契约测试同步更新；
- 主要文件：`README.md`、`AGENTS.md`、`docs/versions/`、`frontend/`、
  `bi_agent/web/static/vendor/antd/workbench.js`。

## 验证结果

- MCP 红测与本体契约测试共 106 项通过；
- 前端 Node 测试 76 项通过，`npm run build` 成功，构建产物包含且只包含
  `ontology-v0.1.3` 版本标识；
- `ontology-analytics-skill` 离线自检 160/160 通过；
- 34 测试环境验证 MCP `tools/list` 返回 16 个工具，`MetricFactQuery` 返回 2025 年采购金额合计
  `854,057,481.11`，Fuxi 完成 `AnalysisRoute → MetricFactQuery → CanvasGenerate →
  OutputGateCheck` 链路；
- 版本契约测试与 `git diff --check` 在提交前执行。

## 已知限制

- 本版本通过 Merge Request 合入 `master` 后才具备正式定版 commit；tag 与 GitLab Release 必须由
  用户在合并后单独授权；
- 版本号与文档变更不触发部署；已有 34 测试环境部署属于独立验证，不等同于正式版本发布或生产部署；
- 不拉 `release/ontology-v0.1.3` 分支；后续如出现线上紧急缺陷，再按 `hotfix/*` 流程处理；
- 不删除、迁移或覆盖任何历史会话和用户数据。

## 相关记录

- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
- 分支模型：[Git 分支与合并工作流规范](../git-branch-workflow.md)
- 上一版本：[ontology-v0.1.2](./ontology-v0.1.2.md)
- 周 changelog：[changelog_10_19_23.md](../../changelog/changelog_10_19_23.md)
