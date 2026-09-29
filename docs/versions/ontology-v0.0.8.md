# 智能分析 ontology-v0.0.8

## 基本信息

- 版本：`ontology-v0.0.8`
- 历史命名：本版本原以 `v0.1.7` 发布，2026-09-29 随版本族切换到 `ontology-v0.0.x` 时改名，定版 commit 未变
- 日期：`2026-09-08`
- 状态：正式版
- Git Tag：`ontology-v0.0.8`
- 定版 commit：`706e0d54af0c3c6604179dc8eaf2862a7faf920e`

## 版本概述

ontology-v0.0.8 让应用既能部署在域名根路径，也能完整部署在网关保留的子路径
（生产前缀 `/api/ontology-agentic-analytics`）下；同一批提交还把仓库的发布主线收口到
`master` 并把 changelog 收敛为按周维护。

## 交付主题

### 1. 可配置应用 Base Path（`706e0d5`）

- 新增环境变量 `APP_ROOT_PATH`，缺省空字符串，根路径部署完全兼容；
- 规范化规则：接受空值、`/`、`api/foo/`、`/api/foo/`，结果分别为 `""`、`""`、
  `"/api/foo"`、`"/api/foo"`；非空前缀必须以 `/` 开头、不以 `/` 结尾；
- 非法配置（查询串、fragment、协议、域名、`.`/`..` 段、重复斜杠）在启动/导入即快速
  失败并给出明确错误，不静默回退；
- FastAPI `root_path` 使用规范化值，内部路由仍为 `/workbench`、`/static/*`、`/api/*`、
  `/healthz`，不复制注册带固定前缀的第二套路由；
- 前端 `frontend/src/runtime.js` 按 `root_path` 适配请求前缀，
  `bi_agent/web/static/index.html` 与构建产物同步重建；
- 测试：`tests/test_application_base_path.py`（144 项新增），`tests/test_regressions.py`
  同步更新。

### 2. 发布主线与记录方式收口（`bf425cb`、`ae0890c`、`0de7cda`、`cf700dd`）

- 仓库发布主线迁移到 `master`，`main` 退役；合并到 `master` 需 `tianzijing`
  code review 后单独发起 Merge Request；
- 新增 master 切换验收门；仓库级规则与文档统一为 `master` 口径；
- changelog 由日报合并为按周记录。

## 用户可见变化

- 应用可以整体挂在网关子路径下访问，也可继续部署在根路径，行为不变；
- 新增配置错误会在启动时直接失败，而不是运行期出现"部分接口 404"。

## 验证情况

- `tests/test_application_base_path.py` 全部通过；`tests/test_regressions.py` 通过；
- 本版本记录了 v0.1.7 部署前置配置，但未部署到服务器。

## 已知限制

- 前缀必须在网关侧完成转发与 ASGI `root_path` 语义处理，应用不代理网关；
- 本版本未部署，服务器运行版本不受影响。

## 相关记录

- GitLab Release：[智能分析 ontology-v0.0.8](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.8)
- 历史 tag：`v0.1.7`（2026-09-29 已随版本族切换删除，指向同一 commit `706e0d5`）
- 规范：[语义化版本与正式发布规范](./versioning-policy.md)
