# 智能分析 ontology-v0.0.2

## 基本信息

- 版本：`ontology-v0.0.2`
- 历史命名：本版本原以 `v0.1.1` 发布，2026-09-29 随版本族切换到 `ontology-v0.0.x` 时改名，定版 commit 未变
- 日期：`2026-09-02`
- 状态：正式版
- Git Tag：`ontology-v0.0.2`
- 定版 commit：以 `ontology-v0.0.2` annotated tag 指向的 commit 为准

## 版本概述

ontology-v0.0.2 是在 ontology-v0.0.1 基础上的补丁版本，主要交付：分析结论可靠性硬化（真实数据/对账
不变量、正文数值校验）、共享本体图包接入、GitLab 统一交付与正式版本流程落地、应用
改名与容器化交付规范（统一容器内部端口 8080）。产品能力边界与 ontology-v0.0.1 一致，未新增
独立业务流程。

## 核心变化（相对 ontology-v0.0.1，按交付主题）

- 分析可靠性硬化（MR !2）：
  - 只有真实数据查询（SQLRun/MetricDataQuery 路径）的结果与 Claims 进入最终交付，
    表格/图表等展示类工具不再成为后续数据源；
  - 对账只配对同指标显式父子结果，可抗其他结果穿插而不误配；
  - 关系类工具仅有显式边/路径证据才产生 Association Claims，空/错误/降级/零边输出
    如实披露 `RELATION_MISSING`；
  - 正文数值校验放行 `100` vs `100.0`、`0.25` vs `25%`、序数、列表标记、区间与时间
    表达，同时拦截编造数字。
- 共享本体图包：`@boulderaitech/ontology-graph@0.1.0` 发布到 ai-team 组包 registry，
  本体图渲染器从本地副本迁移为消费共享包，图构建与渲染职责分离。
- GitLab 统一交付与版本/Release 流程（MR !1 + AGENTS.md 规则）：
  - 日常交付只推 `gitlab/20260727`（`scripts/push_gitlab.py`，先 `--check`，成功标准
    `HEAD == gitlab/20260727`）；`main` 为受保护发布分支，合并需 code review 后走 MR；
  - 正式版本说明、Git tag 与 GitLab Release 规则明确并各自独立授权；
  - 应用/仓库/服务名统一为 `eimosp-ontology-agentic-analytics`（产品名“智能分析”不变），
    旧托管平台引用清理完毕。
- 容器化交付与端口规范（MR !3）：
  - 新增 `Dockerfile`（官方 `python:3.13-slim`、非 root、内置 `HEALTHCHECK`、前端构建
    产物随镜像），运行参数固化；
  - 容器内 HTTP 服务统一监听 `0.0.0.0:8080`，宿主机推荐映射 `-p 8765:8080`；
    `/healthz` 的 `port` 字段动态反映进程实际监听端口（非容器本地默认仍为 8765）；
  - 新增端口契约测试与 Spec，README/DEPLOYMENT/.env.example 同步端口约定。

## 用户可见变化

- 分析最终输出更可靠：结论必须有真实查询或对账证据，根因/关系缺证据时如实说明，
  不出现编造数字或“假图表变数据源”导致的错误结论；
- 本体图渲染切换为共享渲染器，能力与交互保持不变；
- 页面品牌与版本号显示 `ontology-v0.0.2`。

## 兼容性与运维变化

- 容器部署端口约定变化：容器内 `8080`、宿主机映射 `8765:8080`；不要把宿主机端口写成
  容器内部监听端口；
- 非容器本地直接启动与 systemd 部署默认端口仍为 `8765`，不迁移；
- 交付流程统一 GitLab：普通 commit 只推送 `gitlab/20260727`；merge 到 `main` 需要
  `tianzijing` code review 后单独发起 Merge Request；
- 历史会话、上传文件、图表、日志等用户数据目录保护规则不变。

## 验证情况

- 全量 Python 测试 318 项：1 项环境预置失败
  `test_no_unexpected_git_tags`（本地存在历史备份 tag，与本次改动无关）；
- 容器端口契约测试 12 项通过；前端 production build 成功且构建产物无漂移；
- 真实进程验证：`--port 8080` 下 `/healthz` 返回 `port=8080`，默认启动返回 `port=8765`；
- 版本契约测试随本次发布更新到 `ontology-v0.0.2` 并通过；
- `git diff --check` 通过；推送后 `HEAD == gitlab/20260727`；tag 与 GitLab Release 已创建。

## 已知限制

- ChatBI 并发治理当前只支持单 Uvicorn worker；
- L1/L2 简单查询不进入根因分析（第 5 步跳过，属设计行为）；
- ontology-v0.0.2 开发期间 Docker 镜像构建因拉取 `python:3.13-slim` 超时未完成，容器运行验证
  以契约测试与文档契约为准，尚未以真实镜像验证。

## 升级说明

- 从 ontology-v0.0.1 升级：
  - 非容器：更新代码到 ontology-v0.0.2，`python -m pip install -e '.[web]'`，前端有变化时重新
    `npm run build` 并同步 `bi_agent/web/static/vendor/antd/workbench.js` 与
    `eimosp-ontology-agentic-analytics-workbench.css`，再重启服务；
  - 容器：重新构建/拉取 `eimosp-ontology-agentic-analytics:ontology-v0.0.2`，按
    `-p 8765:8080` 映射并挂载数据卷；
- 历史会话迁移前先完整备份 `dataset/conversations/`，不直接改写用户数据；
- `.env` 配置（LLM/Doris/远程本体/Nacos 占位）保持不变。

## 版本管理

- 统一代码位于 GitLab `gitlab/20260727`（`ai-team/eimosp-ontology-agentic-analytics`）；
- merge 到 `main` 需要 `tianzijing` code review 后单独发起 Merge Request；
- 日常 push 保持 `HEAD == gitlab/20260727`；
- Git tag 和 GitLab Release 属于正式版本动作，不属于日常 push。

## 相关记录

- [2026-08-31 日开发记录](../../changelog/changelog_8_31.md)
- [2026-09-01 日开发记录](../../changelog/changelog_9_1.md)
- [2026-09-02 日开发记录](../../changelog/changelog_9_2.md)
- [GitLab 统一推送工作流](../gitlab-push-workflow.md)
- GitLab Release：[智能分析 ontology-v0.0.2](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.2)
- Release 基于 `ontology-v0.0.2` tag，指向定版 commit（见 tag 指向）。
