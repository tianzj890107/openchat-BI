# Spec：Docker 固定默认值与环境变量增量同步

状态：Implemented / TDD Green（修订于 2026-09-08）

## 1. 目标与不可破坏约束

以当前 pdt-dev Pod 环境和本地真实 `.env` 为基线：

1. 确定、非敏感的运行参数全部写入 Dockerfile `ENV`；
2. 本地 `.env` **只允许增量添加，禁止删除、改名、清空或覆盖任何现有键和值**；
3. `.env.example` 同步完整运行配置键结构；
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

## 4. `.env.example` 与 10.34 服务器直接同步

`.env.example` 必须包含修改前本地 `.env` 的全部键名、Dockerfile 的全部固定运行键，以及
新增 Secret 空值或占位符。

实现阶段直接通过 SSH 主机别名 `company-server`（`172.16.10.34`）增量修改当前运行 release：

`/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/v0.1.2/.env`

修改前必须在同目录创建权限为 600 的带时间戳备份。服务器 `.env` 修改前已有键由测试中的
`BASELINE_SERVER_ENV_KEYS` 固化，必须全部保留且值不变；只追加缺失的完整运行配置键。新增
Secret 无可靠真实值时只追加空值，不得伪造或拿其他系统的凭据代替。修改采用原子替换并保持
文件权限 600。本任务只同步配置文件，不重启进程、不切换 release、不部署代码。

`GITLAB_TOKEN` 虽因“不得减少”保留在本地 `.env` 基线中，但不是应用运行依赖，不得注入
Pod；`.env.example` 只能保留空占位和注释。其他直连 provider key 同理不能写真实值。

## 5. 外部条件

配置同步不等于运行进程已加载新值：本任务禁止重启，因此当前 8765 进程仍使用启动时环境。
不得修改 README、DEPLOYMENT 或其他部署说明文件。

## 6. TDD Red

```bash
.venv/bin/python -m pytest tests/test_docker_defaults_and_local_secrets.py -q
git diff --check
```

本地 Red 必须证明 Dockerfile、`.env` 和 `.env.example` 尚缺增量配置，同时既有 `.env`
键保护测试必须通过。设置 `RUN_SERVER_ENV_SYNC_TESTS=1` 时还必须只读验收 10.34 当前 release
的 `.env`；实现前该集成测试应失败，实现后转绿。
