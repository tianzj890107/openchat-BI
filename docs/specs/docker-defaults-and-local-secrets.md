# Spec：固定运行配置进入 Dockerfile，Secret 留在 `.env`

状态：TDD Red（2026-09-08）

## 1. 目标

以当前 pdt-dev 已有 Pod 环境和本地真实 `.env` 为依据，将分析 Agent 实际运行所需配置分成两层：

1. 确定、非敏感的运行参数全部写入 Dockerfile `ENV`，构建后的镜像无需运维重复录入；
2. API key、Token、密码只保存在 Git/Docker 忽略的 `.env`，由运维通过 Secret 或受控 env 文件注入。

Kubernetes 自动生成的 `*_SERVICE_HOST`、`*_SERVICE_PORT`、`*_PORT_*_TCP*` Service Link
不复制进 Dockerfile 或 `.env`。应用并不读取这些名称。

## 2. Dockerfile 固定默认值

除现有 Python/应用/端口变量外，镜像固定当前已确认的非敏感部署参数：

```dotenv
APP_ROOT_PATH=/api/ontology-agentic-analytics
APP_NAME=eimosp-ontology-agentic-analytics
APP_HOST=0.0.0.0
APP_PORT=8080
LLM_PROVIDER=team
TEAM_BASE_URL=http://172.16.10.34:4000/v1
TEAM_MODEL=direct-deepseek-v4-flash
TEAM_MODELS=<本地 .env 当前完整模型表>
TEAM_DEEPSEEK_ENABLE_THINKING=true
TEAM_QWEN_ENABLE_THINKING=
ONTOLOGY_BACKEND=production
ONTOLOGY_BASE_URL=http://172.16.5.181:30834
ONTOLOGY_REPOSITORY_ID=3
ONTOLOGY_APP_ID=ApTH1EHKdRk58WhDQB
ONTOLOGY_TIMEOUT_SECONDS=30
ONTOLOGY_CACHE_TTL_SECONDS=30
RETRIEVAL_MODE=semantic
DORIS_API_URL=http://172.16.5.181:30834/agent/doris/query
DORIS_DATABASE=ontology_demometaerp_scm_po
CONVERSATION_SYNC_URL=http://172.16.10.34:8765
CHATBI_MAX_ACTIVE_TURNS=8
CHATBI_MAX_ACTIVE_PER_PRINCIPAL=2
CHATBI_MAX_WAITING_TURNS=32
CHATBI_ADMISSION_WAIT_SECONDS=2
CHATBI_LLM_CONCURRENCY=6
CHATBI_DORIS_CONCURRENCY=12
CHATBI_ONTOLOGY_CONCURRENCY=12
CHATBI_SESSION_IDLE_TTL_SECONDS=7200
CHATBI_MAX_IN_MEMORY_SESSIONS=500
CHATBI_COORDINATION_MODE=local
CHATBI_COORDINATION_NAMESPACE=chatbi
CHATBI_COORDINATION_FAILURE_MODE=closed
TASK_ALERT_API_ENABLED=true
TASK_ALERT_API_URL=http://pdt-dev.eimos.com/api/x360/v1/task-alert/manual-create
TASK_ALERT_DEFAULT_ASSIGNEE=400
TASK_ALERT_DEFAULT_LEVEL=WARNING
TASK_ALERT_DEFAULT_BP_DEFINITION_ID=
TASK_ALERT_TIMEOUT_SECONDS=10
```

这些都是镜像默认值，同名 Kubernetes 环境变量仍可覆盖。固定内部地址意味着该镜像当前面向
pdt-dev；以后更换环境应由 Deployment/ConfigMap 覆盖，而不是把 Secret 烧进新镜像。

## 3. `.env` Secret 交付

当前 `LLM_PROVIDER=team`，运维最小 Secret 文件为：

```dotenv
TEAM_API_KEY=<真实值>
ONTOLOGY_AUTH_TOKEN=<如本体服务需要鉴权则填写，否则留空>
DORIS_PASSWORD=<当前 HTTP Doris 不需要则留空>
```

- 本地已有 `TEAM_API_KEY` 不得被覆盖或输出；
- 缺失的 `ONTOLOGY_AUTH_TOKEN`、`DORIS_PASSWORD` 只补键，无法从两边推导真实值时留空并明确交由运维确认；
- 从交付给运维的 `.env` 删除已进入 Dockerfile 的非敏感项；
- `GITLAB_TOKEN` 与当前运行无关且权限高，不得交给 Pod；Qwen/Anthropic/DeepSeek 直连 key 在当前 Team provider 部署中也不注入；
- `.env`、`.env.*` 必须同时被 Git 和 Docker build context 忽略；测试只读取键名，不打印值。

## 4. 不能由两层自动解决的外部条件

配置齐全不代表网络必然可用。运维仍需确认：新 Pod 能访问 `172.16.10.34:4000`、
`172.16.5.181:30834` 和 `172.16.10.34:8765`；Ingress 是否确实使用
`/api/ontology-agentic-analytics`；如果将来多副本运行，必须用实际 Redis URL 覆盖 local coordination。

这些是网络、路由或真实凭据，不能由 Dockerfile 或仓库自动制造。

## 5. TDD Red

`tests/test_docker_defaults_and_local_secrets.py` 验证：完整非敏感默认值、Secret 永不进入镜像、
本地 `.env` 只含允许交付的运行 Secret、忽略规则、占位示例和健康检查。

```bash
.venv/bin/python -m pytest tests/test_docker_defaults_and_local_secrets.py -q
git diff --check
```
