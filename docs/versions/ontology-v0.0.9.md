# 智能分析 ontology-v0.0.9

## 基本信息

- 版本：`ontology-v0.0.9`
- 历史命名：本版本原以 `v0.1.8` 发布，2026-09-29 随版本族切换到 `ontology-v0.0.x` 时改名，定版 commit 未变
- 日期：`2026-09-17`
- 状态：正式版
- Git Tag：`ontology-v0.0.9`（annotated）
- 定版 commit：`c938fc0`（`master` 主线 HEAD）

## 版本概述

ontology-v0.0.9 交付仓库在 `master` 唯一发布主线收口后的部署与运行配置固化：Dockerfile 固定
非敏感运行环境默认值并保留华为云 SWR 基础镜像、本地与服务器 `.env` 增量同步契约、
服务器引用统一字面 IP、changelog 仅按周维护规则，以及仓库级 `master` 主线口径统一。
本版本没有新增用户可见能力，按 PATCH 级发布执行。

本版本同时是一次**版本更正**：同一批内容曾在 2026-09-09 以 `v0.2.0` 发布，但这批
改动属于配置、文档与规则收口，按 `versioning-policy.md` 应为 PATCH，不应占用 MINOR
版本号（MINOR 需要新增能力，且一周内只有修复和小优化时必须继续用 PATCH）。因此：

- `v0.2.0` 的 Git Tag 与 GitLab Release 均已撤销（两者原本指向同一定版 commit）；
- 以 `ontology-v0.0.9` 重新发布同一定版 commit `c938fc0`，版本号回到 `ontology-v0.0.x` 序列；
- `v0.2.0` 从未包含代码变更，撤销它不影响 `master` 分支内容，也未触发任何部署；
- 版本契约测试的官方 tag 白名单同步为 `ontology-v0.0.1`–`ontology-v0.0.9`（commit `59fb09d`）。

## 交付主题

### 1. Dockerfile 固定默认值与镜像规范

- Dockerfile 唯一 FROM 行保持华为云镜像
  `swr.cn-east-3.myhuaweicloud.com/release/python:3.13-slim`（保留容器端口 8080、
  非 root 运行与 `HEALTHCHECK 127.0.0.1:8080/healthz`）；
- 固定非敏感运行参数写入 Dockerfile `ENV`：应用名/host/端口与 `APP_ROOT_PATH`、
  Team LLM、本体、Doris API/database、会话同步地址、ChatBI 并发/队列/TTL/内存会话、
  coordination 与 task alert 配置；运行时同名环境变量可覆盖默认值；
- 禁止把 Secret（`TEAM_API_KEY`、`ONTOLOGY_AUTH_TOKEN`、`DORIS_PASSWORD`、
  `GITLAB_TOKEN`、各模型 API key）写入 Dockerfile/ARG/镜像层；不 `COPY .env`；
  不复制 Kubernetes Service Link 变量。

### 2. 环境变量增量同步契约

- 本地 `.env` 与 `.env.example` 只允许增量添加：不删除、改名、清空、排序或覆盖任何
  既有键和值；补齐 Dockerfile 固定默认值与 `ONTOLOGY_AUTH_TOKEN=`、
  `DORIS_PASSWORD=` 空键（Secret 不伪造值）；文件权限保持 600；
- `172.16.10.34` 服务器当前 release 的 `.env` 按同一增量契约同步：修改前创建带
  时间戳、权限 600 的备份，原子替换前验证原有键全部存在、原有值未变化、新增键
  完整且无重复；
- Secret 只允许由本地 `.env`、Kubernetes Secret 或部署平台注入，绝不进入镜像或 Git。

### 3. 服务器引用与 changelog 规则

- 仓库内服务器引用统一字面 IP `172.16.10.34`，不再依赖 SSH Host 别名；
- changelog 仅按周维护：自 2026-09-08 起不再创建日报，所有变更合并写入当周文件
  `changelog/changelog_M_D-D.md`；AGENTS/README/版本规范/工作流文档同步固化；
  历史 changelog 中的“每日”字样属于过去事实，不做机械改写。

### 4. 仓库级 master 主线一致性

- 所有当前有效开发、推送、MR、构建、版本与部署指令统一指向 `master`；`main` 已退役
  并删除，只以“禁止重建”的负向保护与历史审计形式出现；
- 版本契约断言与 base path 接线对齐（`FastAPI(..., root_path=APP_ROOT_PATH)`）；
- Docker/服务器同步、master 一致性与 weekly changelog 新增 RED→GREEN 契约测试。

### 5. 配套文档与测试

- 新增 `docs/specs/docker-defaults-and-local-secrets.md`、
  `docs/specs/literal-ip-server-references.md`、
  `docs/specs/weekly-changelog-only.md`、
  `docs/specs/repository-wide-master-branch-consistency.md` 及对应测试
  （`test_docker_defaults_and_local_secrets.py`、
  `test_literal_ip_server_references.py`、`test_weekly_changelog_only.py`、
  `test_repository_wide_master_consistency.py`）。

## 验证

- Docker 默认值与 Secret 边界、`.env` 增量同步契约测试通过（本地 Green；
  `RUN_SERVER_ENV_SYNC_TESTS=1` 服务器同步验收通过）；
- `tests.test_weekly_changelog_only`（5 项）、`test_literal_ip_server_references`
  （2 项）、`test_repository_wide_master_consistency`（5 项）通过；
- `tests.test_versioning_policy` 全部 19 项通过（`test_no_unexpected_git_tags`
  白名单已放行 `ontology-v0.0.1`–`ontology-v0.0.9`）；`test_container_port_contract`（12 项）保持通过；
- 开发分支 `20260727` 全量单测：456 passed / 25 skipped / 193 subtests；
- `git diff --check` 通过。

## 已知限制

- 服务器 `.env` 修改后当前运行进程不会自动加载新增变量，本版本只同步配置文件；
- 本版本仅完成仓库内规则、配置与测试收口，不包含服务器重启或服务切换，未部署；
- 定版 commit `c938fc0` 内的代码版本号仍是当时打包用的裸版本号（`0.1.2`），与
  ontology-v0.0.4–ontology-v0.0.8 的既有 tag 做法一致：tag 不改变代码内版本号；
  开发分支 `20260727` 上当时的产品版本号为 `0.1.7`；
- 本版本发布时 `docs/versions/` 只为 ontology-v0.0.1–ontology-v0.0.3 与本次
  ontology-v0.0.9 建档；2026-09-29 版本族重建时已补齐
  ontology-v0.0.4–ontology-v0.0.8 的版本文档。

## 相关记录

- GitLab Release：[智能分析 ontology-v0.0.9](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.9)
- 被撤销版本：`v0.2.0`（Git Tag 与 GitLab Release 均已删除，内容与 ontology-v0.0.9 相同）
- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
- 周 changelog：[changelog_9_7_11.md](../../changelog/changelog_9_7_11.md)
