# Spec：Docker 固定默认值与环境变量增量同步

状态：TDD Red（修订于 2026-09-08）

## 1. 目标与不可破坏约束

以当前 pdt-dev Pod 环境和本地真实 `.env` 为基线：

1. 确定、非敏感的运行参数全部写入 Dockerfile `ENV`；
2. 本地 `.env` **只允许增量添加，禁止删除、改名、清空或覆盖任何现有键和值**；
3. `.env.example` 同步完整运行配置键结构，供运维配置新服务器；
4. Secret 只允许由 `.env`、Kubernetes Secret 或部署平台安全注入，绝不进入镜像；
5. Kubernetes 自动生成的 `*_SERVICE_HOST`、`*_SERVICE_PORT`、`*_PORT_*_TCP*`
   Service Link 不复制到 Dockerfile、`.env` 或 `.env.example`。

上一版“把 `.env` 收敛成三个键”的设计作废。实现不得以整理、去重或安全清理为由减少
本地 `.env` 的任何既有内容。

## 2. Dockerfile 固定非敏感默认值

Dockerfile 必须包含测试 `NON_SECRET_DEFAULTS` 定义的完整默认值，包括：应用与 base path、
Team LLM、本体、Doris、会话同步、并发与本地协调、任务提醒。当前地址是 pdt-dev 默认值，
部署平台仍可用同名变量覆盖。精确验收口径为 Red 测试中的 `NON_SECRET_DEFAULTS`。

## 3. `.env` 增量原则

测试中的 `BASELINE_LOCAL_ENV_KEYS` 固化修改前已有键名。实现后这些键必须全部仍存在，且实现
过程中不得输出或改写其值。在保留全部既有内容的基础上补充：

- `NON_SECRET_DEFAULTS` 中本地尚缺的键，值与 Dockerfile 同步；
- `ONTOLOGY_AUTH_TOKEN=`；
- `DORIS_PASSWORD=`。

已有 `TEAM_API_KEY` 等 Secret 原值必须原样保留。无法推导的新增 Secret 只补空键，交由运维
填写。`.env` 必须继续被 Git 和 Docker build context 忽略，不得提交。

## 4. `.env.example` 与服务器配置同步

`.env.example` 是可提交、无真实 Secret 的新服务器环境变量模板，必须包含修改前本地 `.env`
的全部键名、Dockerfile 的全部固定运行键，以及新增 Secret 空值或占位符。

运维应基于该模板向新服务器 Deployment/Secret **增量添加**缺项，不删除服务器当前已有的
任何环境变量。仓库任务不直接写服务器、不部署；真正的服务器同步由运维执行。

`GITLAB_TOKEN` 虽因“不得减少”保留在本地 `.env` 基线中，但不是应用运行依赖，不得注入
Pod；`.env.example` 只能保留空占位和注释。其他直连 provider key 同理不能写真实值。

## 5. 外部条件

运维仍须确认新 Pod 能访问 `172.16.10.34:4000`、`172.16.5.181:30834`、
`172.16.10.34:8765`，Ingress 使用 `/api/ontology-agentic-analytics`，并确认本体/Doris
是否要求真实凭据。多副本部署时还必须覆盖 local coordination 为实际 Redis 配置。

## 6. TDD Red

```bash
.venv/bin/python -m pytest tests/test_docker_defaults_and_local_secrets.py -q
git diff --check
```

Red 必须证明 Dockerfile、`.env` 和 `.env.example` 尚缺增量配置，同时既有 `.env` 键保护
测试必须通过。
