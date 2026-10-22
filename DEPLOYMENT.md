# eimosp-ontology-agentic-analytics 部署说明

> **仅供人工运维参考**：本文档描述的是人工部署方法，不构成 Agent 自动部署授权。
> Agent 默认交付方式是 commit + push（日常开发在 `feature/*` / `bugfix/*` 临时分支，推送到同名 GitLab 分支），push 不等于部署；
> 默认禁止部署、服务器同步、服务重启和服务器配置修改；只有用户在当前任务中明确
> 要求具体部署目标和范围时，才允许按本文档执行部署。

本文档对应当前仓库的 Web 应用入口 `bi-agent-web`。

## 0. 应用信息清单（部署清单）

| 项 | 值 |
| --- | --- |
| Git 项目地址 | `git@gitlab.boulderaitech.com:ai-team/eimosp-ontology-agentic-analytics.git`（日常开发分支 `feature/*` / `bugfix/*`，唯一发布主线 `master`；`20260727` 已归档、停止接收新提交，`main` 已退役并删除，不得重新创建） |
| 应用名 | `eimosp-ontology-agentic-analytics`（产品名：智能分析；systemd 服务名 `eimosp-ontology-agentic-analytics.service`） |
| Python 版本 | `3.13.x`（标准运行环境；`pyproject.toml` 约束 `>=3.10,<3.14`） |
| 统一容器内部端口 | `8080`（Dockerfile `ENV APP_PORT=8080` + `EXPOSE 8080`，CMD 监听 `0.0.0.0:8080`）；推荐宿主机映射 `8765:8080`；非容器本地默认端口 `8765`（`--port` 仅用于本地/测试覆盖） |
| 统一健康检查接口 | `GET /healthz`（别名 `GET /health`）；就绪 `200`，未完成配置 `503`，响应含 `app`/`version`/`port`/`dependencies` 等固定字段 |
| 外部子路径前缀 | `APP_ROOT_PATH`：缺省为空字符串（域名根路径部署）；生产示例 `/api/ontology-agentic-analytics`，配置后对外入口为 `/api/ontology-agentic-analytics/workbench`、`/api/ontology-agentic-analytics/static/*`、`/api/ontology-agentic-analytics/api/*`、`/api/ontology-agentic-analytics/healthz` |
| Nacos 配置中心 | 预留待对接，当前未接入；中间件类配置仍由 `.env`/环境变量注入（见 §10） |
| GitLab CI/CD | 项目 runner `sys740-docker-runner`（`172.16.10.34`，docker executor）；`.gitlab-ci.yml` 只做验证（单测 + 黄金集），没有 deploy stage（见 §11） |

> 端口约定：`8080` 是统一容器内部端口；`8765`/`47313`/`47314` 是推荐宿主机映射端口
> 或非容器直接运行端口（本项目对应 `8765`）。不要把宿主机端口写成容器内部监听端口。

> 分支与构建口径：DevOps 从 `master` 创建迭代分支或构建正式镜像；仓库里的
> `.gitlab-ci.yml` 只做验证（单测 + 黄金集），是 CI 不是 CD，push 不等于部署，
> 本文档不构成自动部署授权，也不代表本任务已经部署。普通开发仍只推统一开发分支
> `feature/*` / `bugfix/*` 同名分支，正式交付通过 Merge Request 合入唯一发布主线 `master`（`hotfix/*` 双 MR 回到 `release/*` 与 `master`）。

> 子路径部署口径：网关把 `APP_ROOT_PATH`（生产示例 `/api/ontology-agentic-analytics`）
> 前缀流量转发给应用，并在 ASGI 层按 `root_path` 语义剥离前缀，应用内部路由保持
> `/workbench`、`/static/*`、`/api/*`、`/healthz` 不变。容器内置 `HEALTHCHECK` 仍
> 探测不带前缀的 `http://127.0.0.1:8080/healthz`；只有外部健康检查才使用
> `/api/ontology-agentic-analytics/healthz`。非法前缀（协议、域名、查询串、重复斜杠、
> `.`/`..` 段）会在启动/导入时快速失败，不允许静默回退。


## 1. 代码与运行数据的边界

需要从 Git 发布/同步的内容：

- Python 源码、`pyproject.toml`、`bi_agent/web/static/`；
- `frontend/` 源码和构建配置；
- `dataset/spreadsheets/`、`dataset/databases/` 中确实属于应用初始化数据的文件；
- Agent 定义、配置和其他已跟踪的项目文件。

不要提交或用代码发布覆盖的内容：

- `.env`、API key、`~/.claude/` 下的运行配置；
- `dataset/conversations/`、`dataset/uploaded_reports/`、`dataset/charts/`、`dataset/logs/`；
- `__pycache__/`、`.venv/`、`frontend/node_modules/`、临时文件和编辑器文件。

这些目录可能在服务器上有大量新增文件，但它们是用户数据或运行产物，不是需要提交的代码。部署前应先备份需要保留的数据，不要直接删除或用 `git clean` 清理。

## 2. 首次安装

服务器要求 Python 3.13.x（标准运行环境，兼容 `>=3.10,<3.14`）、Node.js/npm（仅前端重新构建时需要）和 Git：

```bash
git clone <repository-url> eimosp-ontology-agentic-analytics
cd eimosp-ontology-agentic-analytics

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[web]'

cd frontend
npm install
npm run build
cd ..
```

`npm run build` 会更新以下两个被 Git 跟踪的文件：

```text
bi_agent/web/static/vendor/antd/workbench.js
bi_agent/web/static/vendor/antd/eimosp-ontology-agentic-analytics-workbench.css
```

如果服务器只用于运行已构建版本，通常不需要在服务器安装 Node.js；应在发布机执行构建并把上述构建产物随代码一起发布。

## 3. 生产配置

生产环境推荐使用远程本体服务和 Doris：

```dotenv
ONTOLOGY_BACKEND=production
ONTOLOGY_BASE_URL=<本环境本体网关>
ONTOLOGY_REPOSITORY_ID=<repository-id>
ONTOLOGY_APP_ID=<本环境 app-id>
ONTOLOGY_AUTH_TOKEN=<本环境 token>

# LLM 至少配置当前模型对应的一个 key。当前团队网关默认模型为 direct-deepseek-v4-flash。
LLM_PROVIDER=team
TEAM_API_KEY=<key>
TEAM_BASE_URL=http://172.16.10.34:4000/v1
TEAM_MODEL=direct-deepseek-v4-flash
TEAM_MODELS=<comma-separated-verified-model-ids>
# 也可改用 qwen / anthropic / deepseek provider，并配置对应 API key。

DORIS_API_URL=<本环境 Doris 查询网关>
DORIS_DATABASE=<database>
```

把配置放在项目根目录的 `.env`（已被忽略）或由 systemd/Docker 注入。不要把真实 key 写进仓库。

### 本体与 Doris 网关按环境隔离（PDT / demo2）

同一套镜像分别部署在两个环境，**Agent 的对外入口与它调用的本体/Doris 网关必须属于
同一环境**；镜像不再内置任何环境的固定地址，生产模式缺少 `ONTOLOGY_BASE_URL` 或
`DORIS_API_URL` 时启动即失败，不会回退到其它环境的网关。

| 环境 | Agent 对外入口 | `ONTOLOGY_BASE_URL` | `DORIS_API_URL` |
| --- | --- | --- | --- |
| PDT | http://pdt-dev.eimos.com/api/ontology-agentic-analytics | http://pdt-dev.eimos.com/api/gateway2/ontology | http://pdt-dev.eimos.com/api/gateway2/ontology/agent/doris/query |
| Demo2 | http://demo2.eimos.com/api/ontology-agentic-analytics | http://demo2.eimos.com/api/gateway2/ontology | http://demo2.eimos.com/api/gateway2/ontology/agent/doris/query |

`DORIS_API_URL` 支持两种契约，客户端按 URL 自动选方言，并在解析时同时容忍两种响应形态：

| URL 路径 | 请求体 | 响应读取 |
| --- | --- | --- |
| 以 `/agent/doris/query` 结尾（旧网关） | `{"sql": ...}` | `data.rows`（+ `data.columns`） |
| 其它（含 `/api/v1/analysis/data/query`） | `{"analysisConfig": {"sql": ...}, "commonConfig": {}}` | `data.result.rows` + `data.result.columns[].identifierCode` |

灰度期可继续使用旧网关地址；切到 `/api/v1/analysis/data/query` 时客户端改用新契约，
旧网关仍在线的期间无需与本体服务协调切换。本批不改默认值。

```dotenv
# PDT
ONTOLOGY_BASE_URL=http://pdt-dev.eimos.com/api/gateway2/ontology
DORIS_API_URL=http://pdt-dev.eimos.com/api/gateway2/ontology/agent/doris/query
# 新 MAL 契约（可选）：http://pdt-dev.eimos.com/api/gateway2/ontology/api/v1/analysis/data/query
# ONTOLOGY_REPOSITORY_ID=<按该环境目录查到的真实编号>
```

```dotenv
# Demo2（本体目录由 demo2 本体服务真实返回，预期只有 ECore 本体库及其数据库）
ONTOLOGY_BASE_URL=http://demo2.eimos.com/api/gateway2/ontology
DORIS_API_URL=http://demo2.eimos.com/api/gateway2/ontology/agent/doris/query
# 新 MAL 契约（可选）：http://demo2.eimos.com/api/gateway2/ontology/api/v1/analysis/data/query
ONTOLOGY_REPOSITORY_ID=1
```

- `ONTOLOGY_APP_ID` 两个环境取值相同且非密钥，作为镜像共享默认值（当前
  `ApTH1EHKdRk58WhDQB`），各环境可按需覆盖；`ONTOLOGY_AUTH_TOKEN` 是密钥，只能由各
  环境注入，仓库与镜像中不保存真实值（当前两个环境都为空）。
- `ONTOLOGY_REPOSITORY_ID` 只决定"当前激活哪个本体库"，**必须按环境取该环境目录里的
  真实 ID**，不要照抄文档里的编号：PDT 当前激活的是 `12`（钱江本体库-勿动，
  `ontology_qianjiang`），demo2 的 ECore 本体库是 `1`（`ontology_ecore`）。
  查法：`GET <ONTOLOGY_BASE_URL>/system/manager/ontology-repository?page=1&size=100`
  （不带 `X-Ontology-Repository-Id` 头），在 `data.items` 里按名称找到目标库的
  `id`、`namespaceCode`、`currentDatabase`。用错 ID 时 `configure()` 会快速失败，并在
  报错里列出该环境目录里的**可用编号**与配置键名，不会静默连到另一个环境的库。
- 不要通过前端过滤或在代码里写死 repository ID 来"伪造"某个环境只有少量本体库；本体
  列表必须由该环境的本体服务真实返回。
- 部署后核对：`GET <环境入口>/api/sources` 的 `ontology.production.base_url` 应等于该
  环境的 `ONTOLOGY_BASE_URL`，`remote_repositories` 与该环境本体服务返回的目录一致。

### 各环境 `.env` 必须同步更新（运维执行）

镜像与仓库只提供结构，**每个环境服务器上的 `.env` 仍保存着旧的直连地址
（`http://172.16.5.181:30834`），必须由运维按上表改成自己环境的网关**；不改就会继续
直连同一个后端、看到同一份本体库目录。

| 变量 | PDT | Demo2 | 谁维护 |
| --- | --- | --- | --- |
| `ONTOLOGY_BASE_URL` | 必填，PDT 网关 | 必填，demo2 网关 | 运维按环境注入 |
| `DORIS_API_URL` | 必填，PDT 网关 | 必填，demo2 网关 | 运维按环境注入 |
| `ONTOLOGY_REPOSITORY_ID` | `12`（钱江本体库-勿动；以该环境目录实际返回为准） | `1`（demo2 的 ECore 本体库） | 运维按环境注入 |
| `ONTOLOGY_APP_ID` | `ApTH1EHKdRk58WhDQB`（共享默认） | 同左 | 仓库默认，可覆盖 |
| `ONTOLOGY_AUTH_TOKEN` | 当前为空 | 当前为空 | 运维注入（不得入库） |

改完后必须重启服务（`ONTOLOGY_BASE_URL` / `DORIS_API_URL` 是启动期配置），并核对：

```bash
curl -s http://pdt-dev.eimos.com/api/ontology-agentic-analytics/api/sources
curl -s http://demo2.eimos.com/api/ontology-agentic-analytics/api/sources
```

两个响应里的 `ontology.production.base_url` 必须分别是各自环境的 `ONTOLOGY_BASE_URL`，
`remote_repositories` 必须与各自本体服务返回的目录一致（两个环境的库不一样）。

远程本体模式下不需要本地 Excel 本体文件；本地开发模式才需要：

```dotenv
ONTOLOGY_BACKEND=local
```

本地 SQLite 模式可显式传入 `--db dataset/databases/HyperFusion.db`；生产默认 `--db doris`，即通过 Doris 查询。

## 3.1 ChatBI 并发治理（第一阶段）

第一阶段并发保护全部在进程内生效，**当前只支持单 Uvicorn worker**，不要用
`--workers N` 横向扩容；多 worker 需要后续引入 Redis/PostgreSQL 共享状态、分布式锁和
事件流。正式用户体系未接入前，`principal_key` 退化为 `session_id`（未来接入
`user_id`/`tenant_id` 后自动升级，无需改请求协议）。

新增环境变量（全部可选，未设置时使用默认值）：

```dotenv
CHATBI_MAX_ACTIVE_TURNS=8            # 全局同时执行 turn 数上限
CHATBI_MAX_ACTIVE_PER_PRINCIPAL=2    # 同一 principal（当前即 session_id）并发上限
CHATBI_MAX_WAITING_TURNS=32          # 进程内等待队列上限
CHATBI_ADMISSION_WAIT_SECONDS=2      # 排队等待秒数，超时返回 429
CHATBI_LLM_CONCURRENCY=6             # LLM provider 并发信号量
CHATBI_DORIS_CONCURRENCY=12          # Doris/SQL 查询并发信号量
CHATBI_ONTOLOGY_CONCURRENCY=12       # 远程本体 API 并发信号量
CHATBI_SESSION_IDLE_TTL_SECONDS=7200 # 内存会话空闲回收 TTL
CHATBI_MAX_IN_MEMORY_SESSIONS=500    # 内存会话上限（超限惰性回收最旧空闲）
```

行为契约：

- 同一 `session_id` 已有 turn 运行时，再次 `chat`/`choice`/报表相关请求返回
  `409`，机器码 `SESSION_BUSY`，响应含 `error.code`、`session_id`、`retryable=true`。
- 容量保护返回 `429`，机器码 `GLOBAL_QUEUE_FULL` / `PRINCIPAL_CONCURRENCY_LIMIT` /
  `ADMISSION_TIMEOUT`，并带 `Retry-After` 头；同 session 重复 turn 优先 409，不进队列。
- 不同 `session_id` 互不阻塞，可并行执行。
- reset/restore/activate/数据源切换会使旧 turn 收到 `session_superseded` 并停止提交，
  旧请求不能写入新会话；所有关键 SSE 事件带 `turn_id`，`done` 带 `generation`。

## 3.2 Fuxi 远程 MCP

主服务 `bi_agent.web` 已内置 Streamable HTTP MCP，不需要另起进程：

```text
POST /api/mcp                 # initialize / tools/list / tools/call
GET  /api/mcp/health          # 健康检查
GET  /api/mcp/artifacts/<f>   # CanvasGenerate 产物的只读下载
```

Fuxi 连接器配置为 `transport: http`、`url: http://<host>:8080/api/mcp`、
`headers: {}`。同名宿主机映射端口按实际部署填写（本地默认 `8765`）。客户端不需要
`.env`、App ID 或 Token；本体与 Doris 配置仍由主服务持有。

新增可选环境变量：

```dotenv
ONTOLOGY_MCP_AUTH_TOKEN=            # 留空表示依赖内网/网关白名单；设置后要求 Bearer
MCP_PUBLIC_BASE_URL=                # 反向代理后的外部基址，用于拼 Artifact URL
ONTOLOGY_MCP_EXPOSED_TOOLS=         # 逗号分隔的工具白名单；默认 16 个真实分析工具
```

工具白名单永远不能重新启用 `AnalysisRun`、`AskUser`、`TodoWrite`、`Ontology-FactQuery`、
`ListTables`、`DescribeTable`。如果部署在反向代理/容器后，必须设置
`MCP_PUBLIC_BASE_URL`，否则 `CanvasGenerate` 返回的 Artifact URL 可能是容器内地址。

本体客户端默认绕过开发机的 `HTTP_PROXY` / `HTTPS_PROXY`，直接访问内网本体和 Doris
网关；否则 urllib 可能把 demo2 流量送到本地代理，出现 502 或 30 秒超时。
- 客户端断开或 reset 会取消该 turn；被取消 turn 不保存部分回复。
- TTL/LRU 只回收内存 session 与 source context，不删除历史 JSON、上传、图表或日志。

锁顺序（模块文档契约）：registry lock → session slot lock → WebSession 内部状态 →
conversation store lock；严禁持有 registry/store 锁调用网络，严禁持 session 锁等待
全局下游信号量。

## 4. 启动与验证

前台启动（适合首次验证）：

```bash
source .venv/bin/activate
python -m bi_agent.web --host 127.0.0.1 --port 8765 --cwd /path/to/eimosp-ontology-agentic-analytics
```

浏览器访问：

```text
http://127.0.0.1:8765/workbench
```

反向代理（Nginx、网关等）只需把外部路径转发到该地址，并保留 `/api/*` 和 `/static/*`；流式对话接口需要关闭代理缓冲并适当延长超时时间。

启动后至少检查（统一健康检查接口 `GET /healthz`，别名 `GET /health`）：

```bash
curl -fsS http://127.0.0.1:8765/healthz
curl -fsS http://127.0.0.1:8765/workbench >/dev/null
```

然后在页面确认模型、Doris 数据源和本体状态。API key 缺失通常不会阻止服务启动，而会在实际调用对应模型时提示。

## 5. systemd 示例

将以下内容保存为 `/etc/systemd/system/eimosp-ontology-agentic-analytics.service`，按服务器实际路径和用户修改：

```ini
[Unit]
Description=eimosp-ontology-agentic-analytics Web
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<deploy-user>
WorkingDirectory=/path/to/eimosp-ontology-agentic-analytics
EnvironmentFile=/path/to/eimosp-ontology-agentic-analytics/.env
ExecStart=/path/to/eimosp-ontology-agentic-analytics/.venv/bin/python -m bi_agent.web --host 127.0.0.1 --port 8765 --cwd /path/to/eimosp-ontology-agentic-analytics
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用和查看日志：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now eimosp-ontology-agentic-analytics
sudo systemctl status eimosp-ontology-agentic-analytics
journalctl -u eimosp-ontology-agentic-analytics -f
```

## 6. Docker 镜像部署

镜像固定使用官方 `python:3.13-slim`；容器内部统一监听 `0.0.0.0:8080`
（Dockerfile `ENV APP_PORT=8080` + `EXPOSE 8080`），宿主机推荐映射 `8765:8080`；
内置 `HEALTHCHECK` 探测容器内 `/healthz`；前端构建产物随镜像提供，构建不需要 Node.js。

```bash
# 构建
docker build -t eimosp-ontology-agentic-analytics:0.1.3 .

# 运行（生产默认远程本体 + Doris 实时查询）
docker run -d --name eimosp-ontology-agentic-analytics -p 8765:8080 \
  -v "$(pwd)/.env:/app/.env:ro" \
  -v eimosp-ontology-agentic-analytics-conversations:/app/dataset/conversations \
  -v eimosp-ontology-agentic-analytics-charts:/app/dataset/charts \
  -v eimosp-ontology-agentic-analytics-uploads:/app/dataset/uploaded_reports \
  -v eimosp-ontology-agentic-analytics-logs:/app/dataset/logs \
  eimosp-ontology-agentic-analytics:0.1.3

# 验证
curl -fsS http://127.0.0.1:8765/healthz
```

- 容器以非 root 用户运行；`/app` 下运行数据目录保持可写，建议挂载持久卷，不要把会话、图表、上传和日志放进镜像。
- 配置通过 `.env` 只读挂载或 `-e` 注入，禁止把真实密钥写进镜像/仓库。
- 本地 SQLite 演示模式可覆盖启动命令：`docker run ... eimosp-ontology-agentic-analytics:0.1.3 python -m bi_agent.web --host 0.0.0.0 --port 8080 --db dataset/databases/HyperFusion.db`（覆盖 CMD 时容器内仍需监听 `8080`，映射关系不变；需保留镜像内初始化数据文件，不要覆盖 `/app/dataset` 整体）。

## 7. 更新发布

先确认服务器运行数据已备份，再执行：

```bash
cd /path/to/eimosp-ontology-agentic-analytics
git fetch origin
git pull --ff-only origin <branch>
source .venv/bin/activate
python -m pip install -e '.[web]'
sudo systemctl restart eimosp-ontology-agentic-analytics
curl -fsS http://127.0.0.1:8765/healthz
```

如果前端源码或依赖发生变化，先在构建机运行 `cd frontend && npm ci && npm run build`，然后提交并发布构建产物；不要在生产机直接把 `node_modules/`、缓存或用户上传文件加入 Git。

## 8. 服务器未提交内容怎么判断

在服务器仓库目录执行：

```bash
git status --short
git status --short --ignored
git diff --stat
git diff --name-only
```

判断原则：

- ` M` / `??`：已跟踪文件被改动或未跟踪文件，需逐项确认；可能是服务器手工改代码，也可能是应备份的数据误放在未忽略目录。
- `!!`：被 `.gitignore` 忽略，通常是运行产物，不需要提交；其中 `conversations`、`uploaded_reports` 等如需保留，应做数据备份。
- `bi_agent/web/static/vendor/antd/workbench.js` 或 CSS 的改动：通常来自前端构建，只有确认是本次版本构建产物时才提交。

不要在未确认数据内容前执行 `git add -A`、`git clean -fd` 或删除数据库/上传目录。服务器代码应尽量保持可由 Git 重建，服务器产生的数据则单独备份和管理。

## 9. 当前服务器发布说明

当前测试服务器为 `172.16.10.34`（SSH 直连该 IP），运行目录为
`/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/<release>`，进程使用该目录下的 `.venv`，监听 `8765`。
发布时只同步源码和已构建静态资源，先在 release 目录创建带时间戳的代码备份；不要覆盖 `.env`、`.venv`、会话、上传文件、图表和日志。

当前运行状态（2026-10-20 部署远程 MCP feature）：

- 运行目录
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/mcp-11dc92c-20261020`，
  `RELEASE_COMMIT=11dc92c05dab97ae598158cc423a4da6d909640d`（分支
  `feature/mcp-server-policy`），PID 记录在 `<release>/APP.pid`。
- 新 release 从 `v0.1.2` 复制 `.env`、`.venv` 和数据集软链后覆盖代码；旧 release
  `v0.1.2` 保持完整，可直接切回作为回滚版本。`.env` 权限保持 `600`。
- 数据环境切换到 demo2：`ONTOLOGY_BASE_URL=http://demo2.eimos.com/api/gateway2/ontology`、
  `ONTOLOGY_REPOSITORY_ID=1`、
  `DORIS_API_URL=http://demo2.eimos.com/api/gateway2/ontology/agent/doris/query`；
  `APP_ROOT_PATH=/api/ontology-agentic-analytics`，
  `MCP_PUBLIC_BASE_URL=http://172.16.10.34:8765/api/ontology-agentic-analytics`。
- Fuxi 连接地址：
  `http://172.16.10.34:8765/api/ontology-agentic-analytics/api/mcp`。
- 验证：`/healthz` 返回 200，`/api/mcp/health` 返回
  `server=ontology-analytics-mcp`、`version=0.2.0`、`protocol=2025-03-26`；
  MCP `tools/list` 返回 16 个工具且不包含 `AnalysisRun/AskUser/TodoWrite`；
  `MetricFactQuery` 实测 2025 年采购金额合计 `854,057,481.11`；
  Fuxi 验收完成 `AnalysisRoute → MetricFactQuery → CanvasGenerate → OutputGateCheck`，
  Artifact URL 返回 HTTP 200。

### Cockpit 三页静态看板（8876，2026-10-22）

- 范围：发布 `/cockpit/overview`、`/cockpit/operations`、`/cockpit/analysis` 三个看板 HTML 及其
  CSS／JS、静态 ProUI 运行包和顶部三个视图 Tab，使用 `ProBiDashboard` 渲染原生 ProUI 组件；
  `/cockpit/home` 保留为兼容入口并 307 到 `overview`。不启动第二套 `bi_agent.web`，不占用或重启
  `8765` 主服务，不复制 `dataset/`，不读取生产接口。看板内的交付插槽是静态组件，不访问
  `/api/cockpit/*`；旁路 API 仍保留供后续接入实时 AI。
- 访问地址：
  - `http://172.16.10.34:8876/cockpit/overview?id=1` 或 `?id=2`
  - `http://172.16.10.34:8876/cockpit/operations?id=1` 或 `?id=2`
  - `http://172.16.10.34:8876/cockpit/analysis?id=1` 或 `?id=2`
  - `http://172.16.10.34:8876/cockpit/home?id=1` 或 `?id=2` 会跳到 `overview`。
  - `/` 与 `/cockpit` 直接返回经营看板，不单独渲染首页。
- 身份参数：Fuxi 统一传 `id`，`1=总裁`、`2=分析员`；当前三页内容和功能对两个 `id` 完全一致，
  两个人都可访问，`id` 仅作将来差异化的预留标识。三个页面共用同一路径，不使用 `role` 或维护两套地址；
  总入口、页内 Tab 切换、指标切换和节点跳转都保留当前 `id`。
- 服务器目录：`/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/site`；
  nginx 配置：`/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/conf/default.conf`。
- 容器：`eimosp-cockpit-8876`，镜像 `nginx:latest`，端口映射 `8876:80`，
  静态站点和配置均为只读挂载，`--restart unless-stopped`。
- 上一发布：`feature/cockpit-v3-poc` commit
  `2b828a53e39abc41410fe9e4b922d8d99b15f19b`。新交付包为 `iba-demo`
  `feature/demo_1021@37975c7a03719c037b4acca70c38b50fb68f4516`，本轮部署记录在部署完成后补入本节。
  目录内 `manifest.sha256` 使用相对路径保存发布文件哈希，`release.json` 记录分支、提交和构建时间。
  HTML 使用 `Cache-Control: no-store`，`cockpit.js/css`、`metadata/runtime.json` 和
  `data-snapshots.json` 使用提交短哈希作为版本查询串，避免继续使用旧缓存。
  ProUI 运行包为 `011269f8`，CSS 为 `b1ee836d`，Vue 复用 3.5.25。
  页面静态资源走同源 `/static/*`；`/api/cockpit/*` 仍走 nginx 反向代理，其余 `/api/*` 固定返回 404。
- 页面壳层：外层使用与 `iba-demo` 示例一致的 `#f3f5f8` 灰底和 20px 内容留白；
  `ProBiDashboard` 使用发布态和自带标题区，不启用配置态拖入占位。
- 内容校验：交付包包含 3 个 Tab、13 份模板、2 个根组件、122 个组件配置和 12 个静态插槽组件。
  `data-snapshots.json` 保存 39 个 AP 查询、3 个批量查询和 4 个头盔图请求；未捕获查询在原卡片
  显示组件自带的“未找到该 AP 查询的发布快照”，宿主不补造数据。
- 插槽：交付根配置没有 `insights`，运行时从交付目录补入 12 个声明（经营看板 0、运营 360 4、
  穿透式问题分析 8）。内容直接使用交付 `insight-components/`，本轮不预加载、不轮询、不调用模型。
- 反向代理：nginx 在 `/api/` 404 规则之前增加 `location /api/cockpit/`，转发到
  `http://172.16.10.34:8877`，读取超时 300 秒并禁用响应缓存。
- 旁路 API：独立目录
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/api-017d65f`，入口为
  `cockpit_api.py`，监听 `172.16.10.34:8877`；PID 写入 `app.pid`，日志为 `api.log`，
  运行数据独立保存到 `api-data/`，不接触历史会话和主服务 `dataset/`。当前进程由
  `setsid nohup` 启动，没有 systemd 自动拉起。本轮静态站升级不改后端接口，继续复用该服务。
- 文件权限：发布后 `site/` 及子目录必须为 `755`、文件为 `644`；根目录若被 staging 权限
  覆盖为 `700`，容器内 nginx worker 会返回 404。
- 路由配置：nginx 保留 `location = /cockpit/home`；配置备份为
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/backups/conf-20261022-115417-pre-proxy/default.conf`。
- 验证（2026-10-22，本地构建）：三条页面路由和 `release.json`、`runtime.json`、`cockpit.js`、
  ProUI CSS／JS、Vue 均返回 200；`/cockpit/home` 返回 307；浏览器确认三个 Tab、一个
  `ProBiDashboard`、`id=1|2` 传播和 URL 同步；运营页头盔图切到报价、投标、订单接收节点时分别出现
  报价、投标、订单签单插槽，穿透页切到订单接收、发货节点时出现订单风险和 4 个发货插槽；
  时间筛选切到 `2026-08-13 19:06:09` 后无组件错误、无未捕获快照。三页均无 ProUI 组件错误。
- 历史验证（2026-10-22 14:49，`2b828a5`）：四条页面路由和 `release.json` 返回新提交；HTML 版本串、
  `cockpit.js` 和 `runtime.json` 的 `v=2b828a5` 生效，线上 `cockpit.js` 包含插槽组件与轮询逻辑。
  该版本的 AI 插槽实时调用 `/api/cockpit/analyses`，商机“重新分析”13.8 秒完成；本轮已改用交付
  静态插槽，不再发起模型请求。
- 回滚副本：`2b828a5` 部署前旧站备份为
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/backups/site-20261022-144900-pre-5501d6f`
  （上一版 `5501d6f`）。本轮部署前会另建 `site-<timestamp>-pre-2b828a5` 备份并记录在这里。
- 本地预览：`/tmp/cockpit-local-preview.py` 使用当前工作区代码启动
  `127.0.0.1:8876`，当前已更新到新交付包资源和 39／3／4 快照；该进程只监听回环地址。

上一运行状态（2026-09-03 部署 v0.1.2，现保留为回滚版本）：

- 运行目录 `~/eimosp-ontology-agentic-analytics-releases/v0.1.2`，
  `RELEASE_COMMIT=c8454d82f052a6770bae975a5d865a6f37eff721`（tag `ontology-v0.0.3`，
  该 tag 原名为 `v0.1.2`；下面的 release 目录名是服务器上的真实路径，仍沿用旧版本号，
  不随版本族切换改名），
  启动命令：`cd <release> && set -a && . ./.env && set +a && nohup ./.venv/bin/python -m bi_agent.web --host 0.0.0.0 --port 8765 --db doris >> ~/eimosp-ontology-agentic-analytics-8765.log 2>&1 &`
  （无 systemd 单元，进程 PID 记录在 `<release>/APP.pid`）。
- 服务器系统缺少 `python3-venv`（`ensurepip` 不可用），无法新建 venv：当前 release 的
  `.venv` 由上一 release（`v0.1.1`）复制而来，并把 site-packages 内可编辑安装引用
  改写到新 release 路径（`__editable___open_claude_0_1_0_finder.py`、
  `direct_url.json` 与对应 `__pycache__` 共 3 处被处理），不要用 `python3 -m venv` 重建。
- 会话/图表/上传/日志/图数据目录保留策略：v0.1.2 的
  `dataset/{conversations,charts,uploaded_reports,logs,graphs}` 符号链接沿用
  v0.1.1 指向的同一数据目录（`openchat-BI-releases/a035df9/dataset/` 同名目录），
  `dataset/exports` 指向 `v0.1.1/dataset/exports`；历史会话与运行产物不复制、不覆盖；
  `databases`/`spreadsheets`/`documents` 来自代码库初始化数据。
- 切换记录（2026-09-03）：停掉 v0.1.1 进程（PID 记录于 `v0.1.1/APP.pid`）后启动
  v0.1.2；旧 release 目录完整保留可回滚。验证：`/healthz` 返回
  `version=0.1.2`、`port=8765`、`configured=true`，dependencies
  `agent/ontology/conversation_store` 全部为 true；启动日志
  `history_root=.../dataset/conversations scanned=78`（历史会话接入，与 v0.1.1 一致）；
  `/workbench` 返回 200，`workbench.js?v=161` 正常加载。

本体管理服务的新目录接口可能返回 `currentDatabase`，旧接口返回 `dorisDatabase`；应用兼容读取两个字段，避免目录字段升级导致新 release 无法启动。

本体任务 Agent 的数据库连接凭据使用平台 AES-GCM 加密格式时，运行进程必须加载与加密端一致的 `ontology.crypto.secret`（或对应环境变量）。Agent 已采用 fail-closed 行为：缺少密钥、密钥错误、密文损坏或 Tag 校验失败会在任务上下文刷新阶段返回 `DATABASE_CREDENTIAL_DECRYPTION_FAILED`，不会把密文当作数据库明文密码继续连接，也不会把密钥写入日志。部署后应使用真实部署密钥重启 eimosp-ontology-agentic-modeling，并重新创建或刷新受影响任务；密钥文件/环境文件权限应为 `600`，不要提交到仓库。当前服务器已配置后端提供的 32 字节 Base64 secret，并验证任务凭据解密后可连接 PostgreSQL。

### 团队网关 thinking 能力表与参数路由

Team 模型的 `supports_thinking` 不是由 LiteLLM 自动上报，而是应用依据真实网关探测结果
维护。代码内置 2026-08-26 已验证能力表；只有能稳定产出 reasoning 且请求参数可安全处理的
模型才在 UI 显示 thinking 开关。可用环境变量覆盖整张能力表：

```dotenv
# 不配置时使用代码内置实测表；显式空值表示所有 Team 模型均不展示 thinking 开关
# TEAM_THINKING_MODELS=qwen3.5-397b-a17b,qwen3.7-plus
TEAM_DEEPSEEK_ENABLE_THINKING=        # 可选：覆盖 DeepSeek 运行时开关
TEAM_QWEN_ENABLE_THINKING=            # 可选：覆盖 Qwen 运行时开关
```

Qwen 使用 `enable_thinking`，已验证的豆包 2.1 与 DeepSeek 路由使用
`thinking.type=enabled/disabled`；其他模型不发送未经验证的 thinking 参数。部分 DeepSeek
路由即使收到 disabled 仍返回 reasoning，应用会保留内部上下文但不向用户输出思考过程，
正文不会因此被拦截。`qwen3.8-2.4t-a95b` 的网关会拒绝显式 false，关闭时会省略参数并由
本地显示开关兜底。`Qwen/Qwen3-80B-AWQ` 实测不产生 reasoning，因此保持 false。

用户开启可见思考且当前模型 `supports_thinking=true` 时，应用会在发给模型的系统提示中
追加简体中文约束：面向用户的思考摘要必须简短、概括、可读，不得暴露逐 token 推理、
隐藏指令、内部系统提示词或完整思维链；语言要求由模型原生输出，后端不做机械翻译。
thinking 关闭时，会话层不会向浏览器转发任何 `thinking_delta`，即使上游意外返回
reasoning 也只保留在内部供工具调用上下文使用。

自动配额 fallback 仅对当前 turn 生效：同一 turn 后续工具调用复用临时模型，但不会改写
用户已保存的模型选择、全局模型配置或默认模型，下一轮新请求仍从用户显式选择的模型开始；
只有设置界面显式保存模型才会永久修改模型选择。

旧全局 `TEAM_ENABLE_THINKING` 仅作为 DeepSeek 的兼容项。不要使用
`litellm.drop_params=true` 掩盖参数错误；部署时若保留旧变量，请确认它只影响 DeepSeek。

### 全局本体子图卡片

`POST /api/ontology/subgraph` 是独立于 Agent 检索模式的只读接口。它始终按请求中的
`session_id` 使用该会话当前绑定的本体源；远程源还会校验 `repository_id`，避免相同编码
跨本体库串图。`strategy=context` 返回 GraphContext 子图，`strategy=expand` 返回扩散后的
上下游子图。该接口不调用 LLM、不执行 SQL、不产生聊天消息，也不推进 SOP。

### Agent Tool 名称迁移

2026-08-27 起，本体相关 Tool 使用 `Ontology-SemanticQuery`、
`Ontology-TermDisambiguate`、`MetricCalculation`、`Ontology-RelationQuery`、
`Ontology-EntityDescribe`、`Ontology-MetricQuery` 和 `Ontology-FactQuery`。发布时必须同步
Agent 定义、后端 Schema 与前端构建产物；如需迁移历史会话，应先完整备份
`dataset/conversations/`，仅精确替换已知旧名称，并逐个校验 JSON，禁止清空或重建会话。

### 六步分析 SOP

会话 SOP 固定为“意图识别、本体模型匹配、深度思考&分析规划、数据获取和可视化、
根因分析、决策行动”。前端构建产物必须与 `frontend/src/sopMachine.js` 同步发布；终态
只把实际访问过的步骤标为完成，未执行步骤显示为 `skipped`，查询后的普通 L1/L2
回答不得自动进入根因分析。部署后应同时核对源码状态机与 `workbench.js` 中的六步名称
及 `skipped` 状态，不能只依赖健康检查。

终态加载清理同样属于发布验收项：`done`、`error`、`session_superseded` 和 SSE 自然关闭
后不得残留 `thinking-line`、`antd-step-thinking` 或流式光标；ThoughtChain 仅允许
`in_progress` 使用动态 pending 状态，`pending` 与 `skipped` 必须保持静态。

前端通过共享包 `@boulderaitech/ontology-graph`（发布在 ai-team 组包 registry，托管项目 `ai-team/ontology-graph`，见 `groups/ai-team/-/packages`）复用
Sigma + Graphology + ForceAtlas2 布局与渲染核心，在“命中的本体”和“本体内容”实体卡两个
入口打开同一个弹窗。依赖包括 `sigma`、`graphology`、`graphology-layout-forceatlas2` 与
共享包；部署时必须同步 `frontend/package*.json`、共享包版本和前端构建产物，不得覆盖会话、
上传、图表或日志目录。

### 行动 → 转督办（任务令）外部服务代理

“行动 → 转督办”由 ChatBI 后端代理到真实任务令服务，不在浏览器直接跨域调用：

```dotenv
TASK_ALERT_API_ENABLED=true            # 功能开关，默认并保持开启
TASK_ALERT_API_URL=http://pdt-dev.eimos.com/api/x360/v1/task-alert/manual-create
TASK_ALERT_DEFAULT_ASSIGNEE=400        # 默认责任人；X360 命中活动时改用该活动的 responsiblePerson
TASK_ALERT_DEFAULT_LEVEL=WARNING       # 只允许 ALERT / WARNING
# 仅当 X360 未接入/未命中时使用的遗留关键词回退(回款/开票/销售项目/投标/合同/订单/
# 生产/发货/签收/验收/线索/项目/关闭/履约单);留空且未命中则不传
TASK_ALERT_DEFAULT_BP_DEFINITION_ID=
TASK_ALERT_TIMEOUT_SECONDS=10          # 上游超时，0.5–120s

# X360 流程定义接口(只读)：转督办时解析流程定义 / 活动 / 责任人
X360_ENABLED=true                      # 显式 false/0/no/off 关闭
X360_BASE_URL=                         # 空 = 未接入(走静态回退)；必须是域名，禁止 IP/别名
X360_PROCESS_DEFINITION_KEY=           # 流程定义 KEY(首选 selector)
X360_PROCESS_DEFINITION_ID=            # 流程定义 ID(备用 selector)
X360_APP_ID=ApTH1EHKdRk58WhDQB         # 非密 App ID；未配置时回退 ONTOLOGY_APP_ID
X360_AUTH_TOKEN=                       # 空 = 不发送 Authorization
X360_TIMEOUT_SECONDS=10                # 0.5–120s
X360_CACHE_TTL_SECONDS=300             # 0 = 每次回源
X360_BP_ID_LEVEL=process_definition    # process_definition(按文档) / activity(回退)
X360_FAILURE_COOLDOWN_SECONDS=30       # 失败冷却；冷却期内直接回退静态表
```

- 后端端点：`POST /api/task-alert/manual-create`，校验 `title`/`content` 非空与
  `level` 取值，`clientRequestId` 做进程内幂等（成功缓存、进行中互斥、失败可重试）。
- `bpDefinitionId` 解析优先级：请求体显式传入 > X360 流程定义解析 > 遗留关键词表；
  实际来源如实写在响应 `source`（`request` / `x360` / `static_fallback` / `default`），
  责任人取命中活动的 `responsiblePerson`（为空才回落到 `TASK_ALERT_DEFAULT_ASSIGNEE`）。
- 响应在 `ok`/`taskId`/`clientRequestId` 之外新增 `source`、`activityName`、
  `bpDefinitionId`；前端仍只依赖 `ok`/`taskId`。
- **上线顺序**：在拿到上游书面确认“`bpDefinitionId` 要流程定义 ID 还是活动 ID”之前，
  生产保持现状——`X360_BASE_URL` 留空（未接入，行为与接入前逐字一致）或已接入时
  `X360_BP_ID_LEVEL=activity`；确认后再切到 `process_definition`。两种口径都只需改环境
  变量，不需要改代码或回滚发布。
- X360 只读：客户端只有文档的两个 `GET`
  (`/api/gateway2/x360/v1/process-definitions/ai/key/{key}` 与 `.../ai/{id}`)，
  没有写接口；X360 不可用时转督办照常创建（降级到静态表并标记 `source`），不会让用户
  侧变成 5xx。
- 即使当前运维网络无法访问上游（连接失败/超时/HTTP 错误），前端也只展示真实失败并可
  重试，不允许关闭开关或显示假成功。
- 上游即使业务失败也返回 HTTP 200（`success:false, code:500`），代理按响应体
  `success`/`code` 判定成功，任务号取 `data`（UUID 字符串）。
- 示例：`curl -sS -X POST http://127.0.0.1:8765/api/task-alert/manual-create
  -H 'Content-Type: application/json' -d '{"title":"t","content":"c"}'`

## 10. Nacos 配置中心对接（待办，当前未接入）

当前应用不依赖 Nacos：模型、本体、Doris 和并发治理等中间件/下游配置均通过 `.env`
或进程环境变量注入，仓库内不保存任何 Nacos 客户端代码与凭据。

后续接入 Nacos 时按以下约定补充（本任务仅预留，不实现）：

- 配置归属：`dataId=eimosp-ontology-agentic-analytics`，`group=DEFAULT_GROUP`，命名空间按环境隔离；
- 下发范围：中间件连接参数（Doris、本体服务、模型网关、任务令代理）等运行配置，
  密钥优先走 K8s Secret / 环境变量，不进配置中心明文；
- 与现有 `.env` 的优先级约定、客户端版本（Python nacos-sdk）和回退策略需在接入
  任务中明确后再实施，并同步更新本文档与 `.env.example` 占位注释。

## 11. GitLab CI/CD（只做验证，不做部署）

仓库根目录的 `.gitlab-ci.yml` 在 GitLab 项目 `ai-team/eimosp-ontology-agentic-analytics`
（project id `1065`）上运行，**不含任何部署动作**：

| Job | Stage | 内容 |
| --- | --- | --- |
| `unit-tests` | test | `python -m pytest -q tests` |
| `analytics-eval-smoke` | eval | `python -m scripts.run_analytics_eval --suite smoke`（P0 契约集门禁） |
| `analytics-eval-regression` | eval | `python -m scripts.run_analytics_eval --suite regression`（全量离线黄金集） |

### Runner

- 项目 runner `sys740-docker-runner` 注册在 `172.16.10.34`
  （`being-SYS-740GP-TNRT`，Ubuntu 22.04），executor 为 `docker`，`concurrent = 2`。
- 该 runner **不执行 untagged job**，job 必须声明 `tags: [boulderai]`，否则会被忽略。
- 启动方式（配置持久化在 docker volume `gitlab-runner-config`）：

  ```bash
  docker run -d --name gitlab-runner --restart unless-stopped \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v gitlab-runner-config:/etc/gitlab-runner \
    docker.m.daocloud.io/gitlab/gitlab-runner:v14.10.1 run
  ```

- 该 runner 已同时授权给 `ai-team/eimosp-ontology-agentic-modeling`（1064）和
  `ai-team/cpq_agent`（1068）；这两个项目在自己的 `.gitlab-ci.yml` 里声明
  `tags: [boulderai]` 即可复用同一台 runner，不需要再注册。
- 镜像（都在 `172.16.10.34` 本地构建，`pull_policy = if-not-present`）：
  - `boulderai/python-ci:3.13`：`python:3.13-slim` + `git`（docker executor 需要
    容器内有 git 才能 clone 仓库）；
  - `boulderai/analytics-ci:3.13`：再加 `pyproject.toml` 声明的全部依赖和 pytest，
    job 只需离线的 `pip install -e . --no-deps`，单个 job 约 1 分钟。
  - `pyproject.toml` 依赖变化后必须重建 `analytics-ci`：

    ```bash
    scp pyproject.toml <host>:~/ci-image/deps/pyproject.toml
    docker build -t boulderai/analytics-ci:3.13 ~/ci-image/deps
    ```

### 已知限制

- `unit-tests` 用 `--deselect` 跳过
  `test_ontology_graph_modal_uses_product_labels_and_synced_cluster_layout`：该用例
  读取 `frontend/node_modules/@boulderaitech/ontology-graph/src/layout.js`，而
  `@boulderaitech/ontology-graph` 是 `file:../../ontology-graph` 本地依赖，远端
  `ai-team/ontology-graph` 仓库当前为空，CI 拿不到该文件。本地安装过 npm 依赖的
  开发机仍会正常执行这条断言；`ai-team/ontology-graph` 有内容后可去掉 `--deselect`。
- 流水线不跑前端构建（`frontend` 依赖 antd/vite，镜像未预装 npm 依赖）。
- 步骤说明：job 里 `git config --global --add safe.directory "$CI_PROJECT_DIR"` 是
  必需的，否则容器内 root 用户对 checkout 执行 git 命令会因 dubious ownership 失败。

### 安全边界

- docker executor 的 job 容器可以访问宿主机 `/var/run/docker.sock`，等价于在
  `172.16.10.34` 上执行任意命令。只把该 runner 授权给可信项目，也不要把它当作
  生产部署机使用。
- CI 全绿只代表验证通过，不构成部署授权；部署仍按本文档由人工执行，且需要当前
  任务中的明确部署指令。
