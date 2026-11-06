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
# 当前 pdt-dev 目录的 ywln 本体库；旧编号 3 由下面的兼容回退处理。
ONTOLOGY_REPOSITORY_ID=14
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
  真实 ID**，不要照抄文档里的编号：2026-10-30 核对时，PDT 的 ywln 目标是 `14`
  （亿纬锂能开发本体库，`ontology_ywln`；V2 为 `16` / `ontology_ywln2`），demo2 的
  ECore 本体库是 `1`（`ontology_ecore`）；`12` 是钱江本体库，不是当前默认目标。
  旧 PDT 编号 `3` 已不在目录中，继续配置为 `3` 会让新进程启动即报
  “远程本体库 3 不在可用目录中”；本分支为此提供了一条窄口径兼容回退，见下表说明。
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
| `ONTOLOGY_REPOSITORY_ID` | `14`（亿纬锂能开发本体库；V2 用 `16`，以该环境目录实际返回为准） | `1`（demo2 的 ECore 本体库） | 运维按环境注入 |
| `ONTOLOGY_APP_ID` | `ApTH1EHKdRk58WhDQB`（共享默认） | 同左 | 仓库默认，可覆盖 |
| `ONTOLOGY_AUTH_TOKEN` | 当前为空 | 当前为空 | 运维注入（不得入库） |

> 2026-10-30 实测 pdt-dev 的本体目录已不再包含编号 `3`。为兼容尚未更新平台变量的部署，
> 本分支仅在目录中存在 `14`、且其 namespace 为 `ywln`、Doris 库为 `ontology_ywln` 时，
> 自动使用 `14` 并输出启动告警；`/api/sources` 的 `atomic_source.repository_id` 会显示实际
> 使用的 `14`。如果 `14` 缺失或数据库不匹配，仍保持原来的 fail-fast，不会随便选择其它库。
> 该回退只覆盖 `3 → 14`，不是通用自动切库规则；平台变量仍建议改为 `14`。

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

客户无法部署远程本体平台时，完整的本地 Excel 本体 + SQLite 回退步骤、启动参数、验收项和
能力边界见 [本地 Excel 本体回退部署说明](docs/local-excel-ontology-fallback.md)。

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
ONTOLOGY_MCP_TOOL_PROFILE=          # general | process360；按连接器固定工具白名单
ONTOLOGY_MCP_EXPOSED_TOOLS=         # 逗号分隔的工具白名单；优先于 profile，仅作用于 /api/mcp
```

### 智能分析与 360 智能分析分开接入

MCP 的 `tools/call` 不携带技能 ID，服务端不能从一次调用本身判断“是哪个技能在调”。
因此按**连接**隔离，一个技能一个连接器，工具白名单同时决定数据源：

| 连接 | 技能 | 工具白名单 | 数据源 |
| --- | --- | --- | --- |
| `http://<host>/api/mcp/general` | `ontology-analytics`（智能分析） | 18 个通用分析工具 | demo2 本体 + Doris |
| `http://<host>/api/mcp/process360` | `process360-analytics`（360智能分析） | `Process360*` + `CanvasGenerate`/`RiskItemCreate`/`TaskOrderCreate`/`OutputGateCheck` | `process360-postgres` / `ywln_crm` |

`/api/mcp` 保持原行为（全部 33 个工具），用于过渡期和旧连接器；新连接器应直接用上面
两个带 profile 的地址。`/api/mcp/general` 不暴露 `Process360*`，`/api/mcp/process360`
不暴露 `AnalysisRoute`/`MetricFactQuery`/`ListBusinessObjects`，越权调用返回
`tool_not_allowed`。

另外，即使走全量 `/api/mcp`，`AnalysisRoute` 遇到明确的 SC01-SC05 问题也会返回
`mode=PROCESS360_REQUIRED`、`next_step=PROCESS360_ROUTE`、`required_tools=["Process360Route"]`，
不再返回 `QUERY_DORIS`，避免 360 问题落到采购域数据；连接器没有 `Process360Route` 时
返回 `next_step=SWITCH_CONNECTOR`。

工具白名单永远不能重新启用 `AnalysisRun`、`AskUser`、`TodoWrite`、`Ontology-FactQuery`、
`ListTables`、`DescribeTable`。如果部署在反向代理/容器后，必须设置
`MCP_PUBLIC_BASE_URL`，否则 `CanvasGenerate` 返回的 Artifact URL 可能是容器内地址。

本体客户端默认绕过开发机的 `HTTP_PROXY` / `HTTPS_PROXY`，直接访问内网本体和 Doris
网关；否则 urllib 可能把 demo2 流量送到本地代理，出现 502 或 30 秒超时。

### Fuxi 风险待办（任务令）

Canvas 的 `actions` 块展示行动建议和“发送任务令”按钮；默认由页面直连主服务
`POST /api/process360/task-orders`，Fuxi 宿主桥接仅在显式启用时使用。页面不提交手机号，
接收人由服务端 `PROCESS360_RECIPIENT_MAP` 解析。服务端再按
`POST /source/todo-batches` 写入 Fuxi 风险待办，不调用 X360，也不发送 Fuxi IM。

```dotenv
FUXI_TODO_ENABLED=true
FUXI_CONTROL_BASE_URL=http://172.16.5.69:8080
FUXI_SOURCE_CODE=boulderai-anaylize-todo   # Fuxi 管理台注册并启用的来源编码
FUXI_TODO_CATEGORY=智能分析任务令
FUXI_TODO_TIMEOUT_SECONDS=10
```

```dotenv
# 临时 POC：所有有正文的 Canvas 行动卡都可点击；无草稿时服务端即时补建一次性草稿。
# 设为 trusted 恢复仅可信草稿可发送。
PROCESS360_CANVAS_DISPATCH_MODE=all
# 可选：指定 PROCESS360_RECIPIENT_MAP 中的键；为空时使用 __default__ 或唯一接收人。
PROCESS360_CANVAS_RECIPIENT=
```

- `recipients_raw` 必须是真实手机号；服务端会剥除 `+86`、空格和横线。
- 空接收人会被拒绝；Fuxi 契约中空数组表示全员广播。
- 标题、严重程度、截止时间、责任人、证据和追溯信息会写入待办条目；详细字段以
  `API/risk-todo-source-api.md` 为准。

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
docker build -t eimosp-ontology-agentic-analytics:0.1.4 .

# 运行（生产默认远程本体 + Doris 实时查询）
docker run -d --name eimosp-ontology-agentic-analytics -p 8765:8080 \
  -v "$(pwd)/.env:/app/.env:ro" \
  -v eimosp-ontology-agentic-analytics-conversations:/app/dataset/conversations \
  -v eimosp-ontology-agentic-analytics-charts:/app/dataset/charts \
  -v eimosp-ontology-agentic-analytics-uploads:/app/dataset/uploaded_reports \
  -v eimosp-ontology-agentic-analytics-logs:/app/dataset/logs \
  eimosp-ontology-agentic-analytics:0.1.4

# 验证
curl -fsS http://127.0.0.1:8765/healthz
```

- 容器以非 root 用户运行；`/app` 下运行数据目录保持可写，建议挂载持久卷，不要把会话、图表、上传和日志放进镜像。
- 配置通过 `.env` 只读挂载或 `-e` 注入，禁止把真实密钥写进镜像/仓库。
- 本地 SQLite 演示模式可覆盖启动命令：`docker run ... eimosp-ontology-agentic-analytics:0.1.4 python -m bi_agent.web --host 0.0.0.0 --port 8080 --db dataset/databases/HyperFusion.db`（覆盖 CMD 时容器内仍需监听 `8080`，映射关系不变；需保留镜像内初始化数据文件，不要覆盖 `/app/dataset` 整体）。

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
  MCP `tools/list` 返回 17 个工具且不包含 `AnalysisRun/AskUser/TodoWrite`；
  `MetricFactQuery` 实测 2025 年采购金额合计 `854,057,481.11`；
  Fuxi 验收完成 `AnalysisRoute → MetricFactQuery → CanvasGenerate → OutputGateCheck`，
  Artifact URL 返回 HTTP 200。

### Cockpit 三页看板（8876，2026-10-26已切实时AP／主服务）

- 初始范围（2026-10-22历史）：发布 `/cockpit/overview`、`/cockpit/operations`、`/cockpit/analysis` 三个看板 HTML 及其
  CSS／JS、静态 ProUI 运行包和顶部三个视图 Tab，使用 `ProBiDashboard` 渲染原生 ProUI 组件；
  `/cockpit/home` 保留为兼容入口并 307 到 `overview`。不启动第二套 `bi_agent.web`，不占用或重启
  `8765` 主服务，不复制 `dataset/`，不读取生产接口。看板内的交付插槽通过同源
  `/api/cockpit/*` 调用 8877 旁路 API 的真实模型分析。
- 访问地址：
  - `http://172.16.10.34:8876/cockpit/overview?id=1` 或 `?id=2`
  - `http://172.16.10.34:8876/cockpit/operations?id=1` 或 `?id=2`
  - `http://172.16.10.34:8876/cockpit/analysis?id=1` 或 `?id=2`
  - `http://172.16.10.34:8876/cockpit/home?id=1` 或 `?id=2` 静态站返回 200，加载后由客户端改写为 `overview`；FastAPI 入口直接 307。
  - `/` 与 `/cockpit` 直接返回经营看板，不单独渲染首页。
- 身份参数：Fuxi 统一传 `id`，`1=总裁`、`2=分析员`；当前三页内容和功能对两个 `id` 完全一致，
  两个人都可访问，`id` 仅作将来差异化的预留标识。三个页面共用同一路径，不使用 `role` 或维护两套地址；
  总入口、页内 Tab 切换、指标切换和节点跳转都保留当前 `id`。
- 服务器目录：`/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/site`；
  nginx 配置：`/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/conf/default.conf`。
- 容器：`eimosp-cockpit-8876`，镜像 `nginx:latest`，端口映射 `8876:80`，
  静态站点和配置均为只读挂载，`--restart unless-stopped`。
- 当前运行（2026-10-26 10:16切换，10:18复核）：用户明确要求服务器启用实时AP和主服务路线，
  代码仍为 `f783102f701253d32e031178845eaea7a5c0e336`，静态包保持原样。
  nginx的 `/api/cockpit/*` 已由8877改为代理 `http://172.16.10.34:8765`；
  `data/config` 返回 `mode=ap, available=true`，`engines` 返回默认 `main`、`comparisonOnly=true`。
  联调仍允许显式独立引擎对照，默认全部插槽走main，没有失败后自动换源。
- 主服务已更新到 `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/cockpit-main-f783102-20261026-101212`，
  PID `1804504`，原8765进程已优雅停止。新release的 `dataset`、`.env`、`.venv` 链接原
  `mcp-11dc92c-20261020` 目录，未覆盖用户数据或改写原认证。新旧 `/api/sources` 完全一致，
  原 `ONTOLOGY_*`、`DORIS_*` 环境值保持一致；328个会话、上传报告、图表文件哈希未变。
- Cockpit独立认证文件为静态站根目录之外的
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/private/ap-headers-poc.json`，目录700、文件600，
  不能输出或提交。此次是POC，使用已验证的PDT登录授权；它不是长期服务账号，无法保证长期有效。
  失效时应更新这个独立文件，不改默认本体／Doris认证，不静默回退快照。
- 独立配置：`COCKPIT_AP_BASE_URL=http://pdt-dev.eimos.com/api/gateway2`、
  `COCKPIT_DATA_MODE=ap`、`COCKPIT_ANALYSIS_ENGINE=main`、`COCKPIT_COMPARISON_ENABLED=true`，
  AP网络并发2、超时10秒、结果凭据1800秒，主服务Cockpit分析并发1。
  完整进程环境持久化在新release的 `runtime-env.json`（600），`start-main.py` 从中恢复；
  如需重启，必须另获当次授权后，在该release运行 `nohup python3 start-main.py >> <受保护日志路径> 2>&1 &`。
- 旧8877独立服务已在无进行中任务时停止，原PID `1771143`；`api-f783102` 和 `api-data` 及所有历史分析保留原地，
  未迁移到主服务。现在8876展示主服务的新分析历史，不等于删除8877原历史库。
- 本次备份：`/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/backups/main-ap-20261026-101212`，
  保留旧环境、nginx配置、SQLite一致备份、切换后用户数据哈希清单、预检与正式日志；环境文件600，目录700。
  `main-ap-deployment-state.json` 记录发布路径、PID及验证任务。回滚必须另获明确授权，使用保留的原代码与环境，
  不能覆盖或清空共享dataset。
- 验证：先用回环18765预检健康及六组AP查询（四组缺失指标、批量、头盔图），再切正式入口。
  真模型任务 `10c657bf6d414c17bba590c972c95548` 约20.619秒，3轮、2次看板工具调用、1项事实，
  路由为 `DIAGNOSTIC_ANALYSIS / QUERY_DASHBOARD`，没有默认本体或SQL取数；结果为 `limited`，
  正常披露没有同源根因明细，不能将其解读为根因已验证。此任务在同一release的临时端口运行后可从8876回看。
  正式8876三个页面浏览器验收共7／15／14次AP请求全部200，无快照缺失或运行异常；页面验收拦截自动模型请求，
  避免重复费用。id=2三个路由与8765原工作台均200；临时18765进程已停止。
- 上一发布（2026-10-26 10:07，已由上面实时AP／主服务运行状态取代）：代码提交
  `f783102f701253d32e031178845eaea7a5c0e336`（`feature/cockpit-v3-poc`），交付包
  `iba-demo` `feature/demo_1021@5791b362cac875ca041884079c3d0d45a58aeb89`。8876 静态站从该提交
  构建，HTML、CSS和插槽模块统一使用 `?v=f783102`；发布包62个文件，manifest 全部通过。
  页面保持交付包的白色主题（`data-dashboard-theme="white"`），ProUI JS 为 `2eb9912a`，
  CSS 仍为 `b1ee836d`，Vue 复用 3.5.25；新增 `data-client.js`，用于启用实时 AP 时按页面查询
  保存结果凭据。保留旧站备份后覆盖静态文件，没有重启8765。
- 8877同步更新：新代码目录 `api-f783102`，PID `1771143`，健康检查返回本次提交；
  `api-data` 软链继续指向 `api-017d65f/api-data`，切换前确认没有进行中任务，21条已完成和
  26条失败的历史分析记录保留，并生成 SQLite 一致备份。服务器没有独立的
  `COCKPIT_AP_HEADERS_FILE`，也没有接入主服务Cockpit入口，因此本次显式配置
  `COCKPIT_DATA_MODE=snapshot`、`COCKPIT_ANALYSIS_ENGINE=standalone`、
  `COCKPIT_COMPARISON_ENABLED=false`：看板继续使用交付快照，AI插槽使用真实模型的独立路线，
  不启用实时AP、不伪造AP凭据、不回退到默认本体或Doris。原 `api-b5c797e` 代码、数据和启动环境
  保留以便回滚；环境备份权限600，严禁输出或提交。
- 回滚备份：`backups/deploy-20261026-100720-pre-f783102/` 包含旧站、SQLite备份、旧进程信息与
  环境备份；静态暂存目录 `site-next-f783102-20261026-1007`。nginx配置、8765进程及主服务数据未修改。
- 验证（2026-10-26 10:07）：驾驶舱相关64项Python测试和5项前端数据客户端测试通过；线上三个路由、
  `release.json`、`cockpit.css`、`cockpit.js`、`data-client.js`、`runtime.json`、
  `/api/cockpit/data/config`、`/api/cockpit/engines` 和 `/api/cockpit/bootstrap?id=1|2`
  均返回200；8877 `/healthz` 返回 `commit=f783102f701253d32e031178845eaea7a5c0e336`，
  `/api/cockpit/data/config` 明确返回 `mode=snapshot`，`/api/cockpit/engines` 返回 `default=standalone`。
  远程浏览器确认三页 `data-dashboard-theme=white`、背景为 `rgb(255,255,255)`、各只有一个
  `ProBiDashboard` 且无横向溢出；验收时拦截了自动分析请求，插槽因此显示预期的网络失败，未产生
  额外模型费用。经营看板的4处“未找到该AP查询的发布快照”仍是既有快照缺口，宿主不补造数据。
- 上一发布（2026-10-26 08:57，历史）：代码提交
  `b5c797e7069a3f0d9da4ec9c2d38ab1994c79b95`。8876 使用白色主题和 `?v=b5c797e`，
  发布包61个文件；8877 使用 `api-b5c797e`、PID `1495655`。回滚备份为
  `backups/deploy-20261026-085731-pre-b5c797e/`。未配置独立AP请求头，AP实时取数未启用。
- 上一发布（2026-10-22 17:38，历史）：代码提交
  `74d642db92bd65caf7f4c2ceaef07a66da60ffb0`（`feature/cockpit-v3-poc`）。8876 静态站从该提交
  构建，HTML、CSS和插槽模块统一使用 `?v=74d642d`；发布包62个文件（含manifest），manifest列出的
  61个文件哈希全部通过。既有nginx容器和挂载目录保持，保留旧站备份后覆盖静态文件，没有重启8765。
  8877 当时同步到 `api-74d642d`，PID `2011023`，`compact-v1` 输出契约、短原因／短措施、
  `deadlineDays`及带契约版本的缓存scope生效。回滚备份为
  `backups/deploy-20261022-173750-pre-74d642d/`。真实模型输出验证曾受团队模型网关 HTTP 400
  `budget_exceeded` 阻塞，新分析明确显示失败，未用固定文案代替，也没有更换凭据或修改额度。
- 上一发布（2026-10-22 16:27，历史）：`feature/cockpit-v3-poc` commit
  `b6eaaca58ec8976bf29d5e04e972709bec476c84`，构建时间 `2026-10-22T08:26:27Z`；对应交付包
  `iba-demo` `feature/demo_1021@5791b362cac875ca041884079c3d0d45a58aeb89`。
  目录内 `manifest.sha256` 使用相对路径保存发布文件哈希（38 个文件全部校验通过），
  `release.json` 记录分支、提交和构建时间；发布目录共 38 个文件。
  上一发布为 `1e5457a914756817be247be4623b88f7d0d76e23`。本版修复插槽入口静态导入导致
  子组件继续命中旧浏览器缓存的问题：入口按 `cockpit-version` 动态加载 registry、shared 和 12 个
  子组件，子组件与 CSS 均使用同一版本串，线上模块实际请求为 `?v=b6eaaca`。
  HTML 使用 `Cache-Control: no-store`，`cockpit.js/css`、`metadata/runtime.json` 和
  `data-snapshots.json` 使用提交短哈希作为版本查询串，避免继续使用旧缓存。
  ProUI 运行包为 `2eb9912a`，CSS 为 `b1ee836d`，Vue 复用 3.5.25。
  页面静态资源走同源 `/static/*`；`/api/cockpit/*` 仍走 nginx 反向代理，其余 `/api/*` 固定返回 404。
- 页面壳层：外层使用与 `iba-demo` 示例一致的白色画布和 20px 内容留白；
  `ProBiDashboard` 使用发布态和自带标题区，不启用配置态拖入占位。
- 内容校验：交付包包含 3 个 Tab、13 份模板、2 个根组件、135 个组件配置和 12 个插槽声明。
  离线回放用的 `data-snapshots.json` 保存39个AP查询、3个批量查询和4个头盔图请求；只有显式snapshot模式
  才依赖它。当前AP模式直接读同一套上游接口，不再因旧快照缺少这四组查询而报错。
- 插槽：交付根配置没有 `insights`，运行时从交付目录补入 12 个声明（经营看板 0、运营 360 4、
  穿透式问题分析 8）。插槽位置按交付配置，内容调用 `/api/cockpit/analyses` 的真实模型分析；
  主路线按可见插槽和当前节点串行调度，不再空闲预取五个环节；只有“重新分析”强制刷新。
- 反向代理：nginx 在 `/api/` 404 规则之前增加 `location /api/cockpit/`，转发到
  `http://172.16.10.34:8765`（2026-10-26切换，之前为8877），读取超时300秒并禁用响应缓存。
- 已停止的历史旁路 API：独立目录
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/api-f783102`，入口为
  `cockpit_api.py`，原监听 `172.16.10.34:8877`，现已停服；原PID记录在 `app.pid`，日志为 `api.log`，
  运行数据独立保存到 `api-data/`，不接触历史会话和主服务 `dataset/`。当前进程由
  `setsid nohup` 启动，没有 systemd 自动拉起；数据软链继续指向 `api-017d65f/api-data`。
- 文件权限：发布后 `site/` 及子目录必须为 `755`、文件为 `644`；根目录若被 staging 权限
  覆盖为 `700`，容器内 nginx worker 会返回 404。
- 路由配置：nginx 保留 `location = /cockpit/home`；配置备份为
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/backups/conf-20261022-115417-pre-proxy/default.conf`。
- 验证（2026-10-22 16:27，线上 `172.16.10.34:8876`）：`/cockpit/overview`、
  `/cockpit/operations`、`/cockpit/analysis`、`/release.json`、`runtime.json`、`cockpit.js`、
  ProUI CSS／JS、Vue、`insight-components/shared.js`、`shipment-cause-breakdown/index.js` 和
  `/api/cockpit/bootstrap?id=1|2` 均返回 200；HTML 版本串为 `b6eaaca`，插槽模块请求均为
  `?v=b6eaaca`。远程浏览器确认三个 Tab 切换后 URL 分别同步到三个路由且保留 `id`，`id=1|2`
  都能加载同一套页面。运营页旧 `cockpit-insight` 数量为 0，真实交付插槽已挂载，投标插槽显示当前
  `2025-10` 真实模型分析内容而不是旧静态文案；穿透页商机与发货插槽均正常渲染，无插槽错误。
- 历史验证（2026-10-22 14:49，`2b828a5`）：四条页面路由和 `release.json` 返回新提交；HTML 版本串、
  `cockpit.js` 和 `runtime.json` 的 `v=2b828a5` 生效，线上 `cockpit.js` 包含插槽组件与轮询逻辑。
  该版本的 AI 插槽实时调用 `/api/cockpit/analyses`，商机“重新分析”13.8 秒完成。当前版本继续使用
  真实模型分析；当前主路线改为按需串行，不再空闲预取。
- 回滚副本：本轮部署前旧站已备份到
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/backups/site-20261022-162707-pre-b6eaaca`
  （上一版 `1e5457a`）；更早备份为 `site-20261022-161324-pre-a438fcd`（`a438fcd`）、
  `site-20261022-155309-pre-2b828a5`（`2b828a5`）和 `site-20261022-144900-pre-5501d6f`（`5501d6f`）。
  新构建暂存目录为 `site-next-b6eaaca`，线上目录为 `site`。
- 本地预览：`/tmp/cockpit-local-preview.py` 使用当前工作区代码启动
  `127.0.0.1:8876`，已更新到新交付包资源和 39／3／4 快照；该进程只监听回环地址。

#### 2026-10-27 发布：master@032bad3（看板 v0.1.5 加载优化）

- 范围：只更新 34 上的 Cockpit 静态站与 8765 主服务，不改 8876 入口拓扑、不复制或清空
  `dataset/` 用户历史、不动 8878 等其他容器。
- 代码与提交：`032bad38f99c47b3b4e121ca1708a361a325ece9`（`master`，含
  `feature/cockpit-v3-poc` 合并与 `ontology-v0.1.5` 加载优化），静态站
  `assetVersion=31f5d6cf3c49bbdf2574`。
- 后端 release：`/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/cockpit-main-032bad3-20261027-1825`，
  PID 记录在 `APP.pid`（本次切换后为 `1931070`），监听 `8765`；`.env`、`.venv`、`dataset`
  均软链到 `mcp-11dc92c-20261020`，历史分析库继续共用
  `dataset/cockpit/history.sqlite3`（47 条分析记录）。
- 切换方式：先在同 release 的 `18765` 预检 `/healthz`、`/api/cockpit/data/config`、
  `/api/cockpit/startup` 和 `page/lookup`，再 SIGTERM 旧 `ca3d29b` 进程（原 PID `2250486`）
  并在 `8765` 启动新进程；旧 release 目录完整保留可回滚。
- 发布过程修正：首次解包时 `dataset/` 是仓库内真实目录，`ln -s` 被建到了
  `dataset/dataset`。已于 21:53 保留该次新产生的数据到 `dataset.local-20261027-2155`，
  再把 `dataset` 指回共享目录并重启；没有删除或覆盖任何历史会话、上传或分析记录。
- 静态站：新增内容寻址资源目录
  `/static/cockpit/releases/31f5d6cf3c49bbdf2574/`（127 个文件），并替换
  `site/index.html`、`site/release.json`、`site/manifest.sha256`；旧扁平资源仍在原地。
  发布前入口备份：`backups/site-20261027-182452-pre-032bad3/`；staging：
  `site-next-31f5d6c-20261027-182452/`。
- 加载优化：nginx 对 `/static/cockpit/releases/` 开启 `gzip_static` 和一年
  `immutable` 缓存；实测 `pro-bi-ui.min.js` 从 6.33 MB 降到 2.24 MB 传输，
  `runtime.json` 从 425 KB 降到 25 KB。配置备份
  `conf/default.conf.bak-20261027-215058`，`nginx -t` 通过后热加载。
- 验证：`/cockpit/overview|operations|analysis`、`/release.json`、新资源、
  Vue 生产包、`/api/cockpit/startup`、`page/lookup` 均 200；远程浏览器三页均渲染
  `ProBiDashboard`（图表 3／9／54），无 JS 异常；经营看板整页快照已发布并显示
  “完整看板 · 数据时间”；AI 插槽继续走 `8765` 真实模型分析。共享分析库的 47 条历史
  记录保留；页面按当前筛选范围重新绑定已发布卡片，数据指纹一致时复用已有分析，
  整页快照按本版本重新生成。
- 已知上游缺口（不启用本地兜底；2026-10-28 已由运行适配层兼容，见下）：AP 返回的活动/头盔配置引用
  `D020/M0023`、`D021/M0031`，对这两组字段调用 AP 数据查询接口返回 HTTP 500
  `系统繁忙，请稍后再试`；同一凭据下 `M0001`、`M0001+D001/D002` 正常，说明代理、
  认证与网络可用。页面按设计显示“AP请求失败；未切换到本体、数据库或旧快照”，
  不使用快照或补 0 冒充结果；需 AP 侧修复该发布配置或字段映射后再复验。
- 回滚：停当前 PID 后用旧 release `cockpit-cards-ca3d29b-20261026-120629/start-main.py`
  重启；静态站恢复上述备份的 `index.html`／`release.json`／`manifest.sha256` 即可，
  旧资源和旧分析数据都未删除。整页快照是可重建缓存，不属于用户历史。

#### 2026-10-28 热修复：头盔图 AP 字段兼容（0cf0f4b）

- 现象：运营页和穿透页的头盔图批次请求返回 502，页面显示
  “AP请求失败；未切换到本体、数据库或旧快照”。
- 定位：AP 的 X360 流程配置（`FULL_PROCESS_OPERATIONS_MANAGEMENT`、
  `SALES_CALIBER`）当前引用 `D020/M0023`、`D021/M0031`、`D016/M0033`、
  `D024/M0036`；当前 AP 分析模型只发布 `M0001-M0013`、`D001-D008`，这些字段
  单独查询也返回 500“系统繁忙”。2026-10-22 参考发布中商机获取节点使用
  `D007/M00013`，其余节点没有数据配置；同一查询实测返回 2 行数据。
- 修复：新增 `bi_agent/cockpit/helmet_compat.py`，在 `/api/cockpit/data/query`
  的 helmet 分支把两类旧节点恢复为参考配置：商机获取 → `D007/M00013` +
  参考 `statusMappings`（并清理 pie 切片），报价/订单接收/发货 → 移除不可用的
  `helmetConfig`。其他节点、流程和已修正的上游配置原样透传，不新建指标、
  不补 0、不切换数据源。
- 测试：新增 `tests/test_cockpit_helmet_compat.py` 和代理链路回归；全量
  `1394 passed, 28 skipped`。
- 发布：release
  `cockpit-main-0cf0f4b-20261028-0041`，PID `2587466`；先在 `18765` 预检两套
  flow（helmet 200、batch 200、2 行），再切 `8765`；上一 release
  `cockpit-main-6f0d9ab-20261028-0036` 保留可回滚，共享 `dataset` 未变。
- 验证：`id=1|2` 的 overview/operations/analysis 全部 AP 请求 200，页面不再出现
  “未切换…”；运营页 13／30 次、穿透页 29 次 AP 请求均无失败，整页快照继续发布。
- 边界：该映射是针对 X360 仍引用未发布字段的临时兼容；X360/AP 修正字段后应删除
  `helmet_compat.py` 的映射并复验，避免长期掩盖上游口径问题。

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

## Cockpit 主服务路线联调配置（2026-10-26，已部署至8765）

本节说明配置与实现。2026-10-26已按用户当次明确授权切换实时AP／主服务；具体运行状态见上面的当前运行记录。后续部署、重启或停服仍须新的明确授权。

- 主服务新增无对话分析任务适配器，`/api/cockpit/analyses` 的 `engine=main` 直接执行现有
  WebSession及源绑定工具，不需要另外启动8877。独立router没有主服务执行器时返回503，不降级。
- 联调配置：`COCKPIT_ANALYSIS_ENGINE=main`、`COCKPIT_COMPARISON_ENABLED=true`；页面使用
  `/cockpit/analysis?id=1&engine=main`。同源API须指向已配置分析Agent和独立AP连接的主服务，沿用APP_ROOT_PATH规则。
- 选型后设置 `COCKPIT_COMPARISON_ENABLED=false`，固定唯一全站引擎，所有插槽统一执行。
  若选择main，后续部署将静态站API代理指向主服务，不再保留8877分析进程；代理切换和停服需要新的明确授权。
- 原8877历史库原地保留，不自动复制、迁移或清空；主服务任务存储位于其工作目录的
  `dataset/cockpit/history.sqlite3`。禁止用旧目录覆盖主服务dataset。
- 2026-10-26实现更新：默认 `COCKPIT_DATA_MODE=ap`，主服务只读代理单条指标、批量指标和头盔图。
  当前 8877 因缺少独立 AP 请求头且未接入主服务 Cockpit 入口，部署时显式使用 `snapshot` 模式和
  `standalone` 分析引擎；实时 AP 能力尚未启用。
  独立配置 `COCKPIT_AP_BASE_URL=http://pdt-dev.eimos.com/api/gateway2` 与仓库外权限600的
  `COCKPIT_AP_HEADERS_FILE`（JSON请求头，按AP实际要求配置应用、本体库及认证，必要时包括Cookie）。
  不读取或修改主服务默认本体／Doris连接，不复用其认证；不跟随认证重定向。不得将本地临时登录态作为正式部署凭据。
- 新接口 `/api/cockpit/data/config`、`/api/cockpit/data/query` 仅完整主服务提供AP能力；
  页面取数成功返回receiptId，分析携带同批apReceiptIds与chartQueries，主服务只读保存的AP响应，不二次取数。
  `ap_results` 表自动追加到Cockpit历史库，保留旧分析与任务。凭据默认1800秒有效；过期要求重新取数，不删除旧材料。
- 默认AP网络并发2、网络超时10秒（允许1–240秒），Cockpit主服务分析并发1；`COCKPIT_AP_CONCURRENCY`、
  `COCKPIT_AP_TIMEOUT_SECONDS`、`COCKPIT_AP_RECEIPT_TTL_SECONDS` 可按需配置。
  上游SQL预算调整为3分钟时，本侧必须同步三处：`COCKPIT_AP_TIMEOUT_SECONDS=180`（排队等待与
  上游执行共用同一期限）、浏览器单请求超时200秒、取数就绪等待220秒；上游快速失败仍重试一次，
  已经消耗掉长预算的504不再重试，避免等待翻倍。
  AP失败不回退默认本体、数据库或旧快照；缺少同源根因明细时仍受限交付。
- 如需离线回放，显式设置 `COCKPIT_DATA_MODE=snapshot`；未捕获的查询仍可能缺失。新代码不再默认依赖旧快照。
- 已在2026-10-26获当次授权后完成代理切换、8765更新与独立8877停服，并验证三类AP和同次结果分析。
  只同步静态文件或升级独立8877不能启用该完整能力；此说明不授权未来的部署、重启或停服。
- 冻结证据对照与其他限制见 `docs/specs/cockpit-analysis-engines.md`。

## AI插槽样式与服务端发布缓存（2026-10-26，已预热并上线）

- 已按用户本次明确授权完成：先在18765真实预热，再提交推送修复并切换正式8765／8876。运行代码为 `ca3d29b1210dd8488eaf2b96cbc449262dfa8e55`；原本体／Doris环境保持一致。后续部署或重启仍需新的明确授权。
- 8765更新后自动追加 `publications`、`publication_views` 表；数据仍在原Cockpit历史库，不删除原会话或分析。
- 8876静态包增加 `publication-client.js`，所有12个AI插槽使用原组件结构和对应加载样式；主服务交付短卡片字段。
- 更新成功才原子替换已发布内容，失败和取消保留上次成功。相同AP请求范围与连接下，新receiptId不会造成缓存失效。
- 首次部署要在切流前预热两个固定身份的默认页面和所需默认节点，确认 `/api/cockpit/analyses/published` 已有完整卡片。
  未建立缓存的新筛选范围显示原AI插槽加载态，不能拿旧范围内容或演示数据占位。
- 沿用独立AP认证配置、8765执行链和既有数据目录，不启动新服务，8877保持停止。
- 实现及验证说明见 `docs/specs/cockpit-card-publications.md`。

### 本次预热验证

- 临时release：`cockpit-cards-13f81bb-20261026-113809`，临时端口18765；与正式服务共享原数据目录，未迁移或覆盖历史数据。
- 两个身份的默认经营页没有AI插槽；默认运营页各发布bid，默认穿透页各发布opportunity和shipment，共6组真实卡片缓存。
- 用户1：bid=`cd345bf9b2994ae0b603cb05bbaae070`，shipment=`2606ff4d8a52424abe7f3040ae33b246`，opportunity=`09391ef244964417813a71e295ec68af`。
- 用户2：bid=`4c63a7816f414ea493858cc9e38da501`，shipment=`cd7c411fa0bb48c9a7d384e996456ffc`，opportunity=`bdf98fcdb6554a4ab258abeeb7bb1e3c`。
- 全部为主服务真实模型、真实AP结果，契约均为cockpit-cards-v1；业务口径或因果证据不足时保持limited，不假造已验证根因。
- 预热发现CardDelivery参数校验异常会被Tool Runtime当作致命执行失败；已修正为业务拒绝反馈，允许在同一循环内修正重交，测试覆盖首次失败后修正成功。
  原失败任务保留在历史，不用于成功缓存；不修改原主服务的工具执行失败边界。
- 回归：148项Python测试、12项前端测试通过，1项环境条件跳过，34个子测试通过；JS语法、diff空白检查通过。

### 正式上线记录（2026-10-26 12:06切换，12:10复核）

- 主服务目录：`/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/cockpit-cards-ca3d29b-20261026-120629`，PID `2250486`。
  runtime-env.json权限600，start-main.py沿用可持久重启方式；APP_ROOT_PATH、原本体与数据库配置保留。
- 正式切换前逐一对比bi_agent全部Python文件，确认最终Git归档与已预热运行代码字节一致；临时预热进程2192691已停止。
  8765旧进程1804504优雅停止，没有强杀；正式服务使用原dataset实体目录，6组已发布卡片在重启后全部可读。
- 8876静态站已更新到ca3d29b，64个文件，manifest的63项均通过；原挂载目录保持不变，使用原地覆盖避免nginx绑定旧inode。
  `/api/cockpit/*`继续代理8765，实时AP和默认main路线保持启用；8877保持停止。
- 回滚备份：`/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/backups/cards-20261026-113809`，
  保留原静态站、nginx、原进程环境、SQLite一致备份及预热后的完整Cockpit库。预热与正式日志保存在该受保护目录。
  部署状态保存在cards-deployment-state.json；回滚须另获明确授权，禁止覆盖或清空dataset。
- 源配置API与切换前完全一致，328个会话／报告／图表文件哈希未变。旧失败预热任务和全部原分析历史保留，不写成成功缓存。
- 正式六个路由（3页×2身份）均200；健康检查就绪，data/config为ap且available=true，默认引擎main，版本号仍ontology-v0.1.4，未新建tag或Release。
- 正式浏览器复核两个身份的运营／穿透页：均先显示上次成功卡片，无AI加载骨架、无长正文替代块、无JavaScript错误，实际查询范围与服务端缓存一致。
  只读首屏验收拦截自动刷新并回放已发布真实缓存，以免重复调用模型；此前预热已使用真实AP和模型，不能将受限结论当成已验证根因。

### Cockpit 饼图组件与展示调整（2026-10-26）

- 上游资源基线更新至 `iba-demo feature/demo_1021@558f2ae27cdc5a9569c5d91a1db45f97d31a4321`；原样引入 `lib/pro-bi-ui.min.js`、`template-registry.json`，重新生成 runtime、资源哈希与版本查询串。穿透式分析头盔节点由新 SDK 绘制为饼图。
- 页面及浏览器标题统一使用“储能经营风险驾驶舱”，清空交付仓库说明。销售额／出货量共同问题分析默认展开风险与待核实原因，不再逐条展示底层事实数值，编号从 1 开始；证据仍保留在主服务历史中。
- 本次部署目标仅为 `172.16.10.34:8876` 静态站。打包当前提交的 Cockpit 与共享 Vue，保留现有 nginx 挂载目录，先备份 site，再覆盖交付包文件并校验 manifest；不重启 8765、不启动 8877、不修改 AP 凭据、不覆盖任何会话或分析缓存。
- 验证：资源与元数据 14 项测试、数据／发布客户端 13 项 Node 测试通过；本地浏览器已确认三个节点绘制为饼图、标题正确、原因默认展开且无逐条指标列表。视觉测试内容仅用于本地，静态包不包含测试数据。

- 新 SDK 对不同图节点发送相同指标、不同状态过滤的批查询。宿主原先只按指标定义保存最后一条凭据，会因节点请求顺序不同造成默认缓存范围漂移；现改为按完整查询保留每个组件的凭据，用户真正切换筛选时仍整体失效旧范围。新增正／逆响应顺序的回归测试，发布后重新预热两身份默认范围。

### Cockpit AP并发排队修复（2026-10-28）

- 用户可见变化：驾驶舱不再显示“Cockpit AP查询并发已满，请稍后重试”。AP共享槽位占满时，
  请求在自身超时内排队；只有排队超过超时才返回504排队超时，且不降级到旧快照、本体或数据库。
- 代码提交：`15d31e0`（`feature/cockpit-34-deploy-record`）。`bi_agent/cockpit/ap_gateway.py`
  改为带剩余超时的阻塞获取；默认 `COCKPIT_AP_CONCURRENCY` 由2调整为4。
  `data-client.js` 对429和“排队超时”504做短暂重试，避免瞬时排队直接显示为错误。
- 后端 release：`/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/cockpit-main-15d31e0-20261028-0817`，
  PID `158559`，监听8765；`.env`、`.venv`、`dataset` 继续软链到 `mcp-11dc92c-20261020`，
  未迁移或覆盖历史会话、上传、图表和分析记录。
- 切换方式：新release先在18765预检（PID `153599`，`/healthz`和`data/config`通过后停止），
  再SIGTERM旧 `0cf0f4b` 进程（PID `2587466`）并启动新进程；旧release完整保留回滚。
  运行环境确认 `COCKPIT_AP_CONCURRENCY=4`、`COCKPIT_AP_TIMEOUT_SECONDS=180`（与上游3分钟SQL
  预算对齐，浏览器单请求200秒、取数就绪220秒）、`data_mode=ap`、`analysis_engine=main`。
- 静态站：新增内容寻址目录 `/static/cockpit/releases/4da3f092598bd18dde3b/`，
  `site/release.json` 已指向该版本；staging `site-next-15d31e0-20261028-085226`，
  入口备份 `backups/site-20261028-085226-pre-15d31e0`。manifest校验通过，旧资源目录保留，
  `gzip_static` 和一年immutable缓存不变。
- 验证：全量Python `1395 passed, 28 skipped`；前端Node测试22项通过。
  34线上24／48／64并发AP查询全部200，64并发最大约1.8秒；新release日志429和5xx均为0。
  `id=1|2` 的 overview／operations／analysis 共6个路由浏览器验收全部AP 200，
  无“并发已满”“未切换”“查询失败”等错误文案，无JavaScript异常和console error。
- 边界：本轮只修复Cockpit 8765／8876的AP排队与前端重试，不修改AP上游、不切换数据源、
  不改变X360字段兼容映射，也不覆盖任何历史会话或运行数据。

### Process360 与 Cockpit 34 集成发布（2026-10-28）

- 代码提交：`a23ba77`（集成分支 `feature/process360-cockpit34-integration`），包含
  `eb0b119` 的 Cockpit 历史 AP 缓存来源域兼容，以及 `a23ba77` 对带明确
  `snapshotId=ap-*`、`sourceMode=service` 历史卡片的整页重发支持。PostgreSQL、演示结果
  仍不能命中 AP 旧 scope；历史 SQLite 未搬迁、覆盖或重生成。
- 后端 release：
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-a23ba77-20261028-160256`，
  PID `1999223`，监听8765。上一发布候选
  `process360-eb0b119-20261028-155839`、更早 `process360-c47237c-20261028-154904`
  与线上原 `cockpit-main-15d31e0-20261028-0817` 均完整保留可回滚。
- 运行配置：`.env`、`.venv`、`dataset` 继续软链到 `mcp-11dc92c-20261020`；新release的
  `PWD/PYTHONPATH/PROCESS360_CATALOG_PATH` 指向自身目录，`COCKPIT_DATA_MODE=ap`、
  `COCKPIT_AP_BATCH_MODE=individual`，Process360 PG 为
  `172.16.5.181:32444/ywln#ywln_crm`。Fuxi 地址已配置，但
  `PROCESS360_POC_DISPATCH=0`、接收人映射为空，本轮未发送真实待办。
- 切换方式：新release先在 `127.0.0.1:18765` 预检，真实重放 analysis 页的8条AP凭据后
  整页发布返回200；随后SIGTERM旧release PID `1988300`，启动新release。预检进程已停止，
  18765不再监听。8876静态站与nginx未改动，继续代理8765。
- 验证：当前提交全量Python `1598 passed / 37 skipped / 1 failed`，唯一失败仍是worktree
  缺少 `frontend/node_modules/@boulderaitech/ontology-graph/src/layout.js` 的环境问题；
  Cockpit聚焦Python 31项、前端Node 22项通过。34线上 `id=1|2` 三页HTML均200，
  `startup`历史快照为 overview 0项、operations 1项、analysis 2项；analysis页真实AP重放
  8条凭据、operations页10条、overview页7条，整页发布全部200且无AP失败。
- 线上校验：`/api/mcp/health` 的 `missingExecutors=[]`，MCP暴露32个工具并包含
  `Process360Plan/TaskOrderCreate`；真实 `Process360Plan + Process360Query` 返回 SC01
  `partial`、`dataSource=process360-postgres`、查询结果4项，仍披露 G01/G12/G16。
  8765日志无4xx/5xx、Traceback或429。
- 边界：SC01仍为partial，SC02—SC05业务闭环、真实任务下发和业务效果复验不能据此判为完成；
  未创建MR/tag/Release，未升级正式版本。

### Process360 下发联调启用与 Skill 交付（2026-10-28 16:47）

- 按本轮授权，仅调整 34 的现有 Process360 主服务运行配置并重启 8765，未替换代码、
  未更新 8876。release 仍为 `process360-a23ba77-20261028-160256`，新 PID 为 `2184357`。
- 开启 `PROCESS360_POC_DISPATCH=1`、`PROCESS360_PAGE_DISPATCH=1`、`FUXI_TODO_ENABLED=1`。
  接收人映射只保留一个默认接收人，不写任何姓名；手机号仅保存在服务器私有环境配置，
  生成草稿时不带姓名，未知接收人阻断下发。
- 共享环境文件先保存权限 600 的 `.env.backup-dispatch-20261028-164644`，保持既有环境、
  release 和历史数据目录。回退时恢复该备份并按既有启动方式重启服务。
- 最新 Skill 源码重新打为本地 `ontology-analytics-skill.zip`（24 文件），逐文件比对、ZIP
  完整性验证通过；SHA256 为 `7034d0ceea77a7bec7f08efd6c6489c0db89390f494464943dd9cb2c633c5025`。
  分发包不入库；对外 MCP 地址仍为
  `http://172.16.10.34:8765/api/ontology-agentic-analytics/api/mcp`。
- 验证：线上 MCP 健康检查通过、`missingExecutors=[]`；任务令状态接口正常，运行进程权限
  与接收人映射解析通过；未知接收人无默认回退。本轮未创建新待办，未验收完整 HTML 点击链路。

### 34 线上 Process360 接入真实 PostgreSQL（2026-10-28 17:06）

- 代码提交：`a6239d4e287bcb7eba27045e870bcbee873687a7`（分支
  `feature/process360-cockpit34-integration`）。仅部署新 release，未修改 8876 静态站、
  未覆盖历史会话或分析缓存。
- release：`/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-a6239d4-20261028-170622`，
  PID `2321809`，监听 8765；`.env`、`.venv` 软链到 `mcp-11dc92c-20261020`，`dataset`
  软链到 `cockpit-main-15d31e0-20261028-0817/dataset`。旧目录
  `process360-a23ba77-20261028-160256` 及 `dataset.tracked-a6239d4-20261028-170622` 完整保留。
- 运行环境：本 release 通过 `runtime-env.json`（权限 600，不入库）显式注入 95 个变量，
  由同目录 `start-main.py` 启动。`PROCESS360_PG_*` 指向
  `172.16.5.181:32444/ywln#ywln_crm`，`PROCESS360_CATALOG_PATH`、`PYTHONPATH`、
  `RELEASE_COMMIT` 指向本 release；Cockpit 继续 `COCKPIT_DATA_MODE=ap`，下发配置沿用
  单一默认接收人映射。此前直接读共享 `.env` 启动会漏掉 Cockpit 变量并使
  `analyses/published` 返回 503，本次已按旧 release 的启动方式恢复。
- 验证：`/healthz`、`/api/mcp/health`（`missingExecutors=[]`）、
  `/api/cockpit/data/config`、`/api/cockpit/engines`、
  `/api/cockpit/analyses/published?id=1&page=analysis` 均 200；`Process360Route` 后执行
  `Process360Query`（SC01）返回 `partial`、`dataSource=process360-postgres`、
  `18.3961 亿元 / 4.6066 GWh`，并披露 G01/G12/G16；8765 日志无 Traceback 与 5xx。
  8876 到 8765 的代理与三页 HTML 均 200；Cockpit 看板的 AP 业务数据尚未接通，属已知状态。
- 回退：停止本 release 进程，恢复 `process360-a23ba77-20261028-160256` 的 `start-main.py`
  启动方式；共享 `.env` 备份为 `mcp-11dc92c-20261020/.env.bak-20261028-170622`。

### Process360 Canvas 临时直发上线（2026-10-28 18:14）

- 代码提交：`a5342cdea459d01438384d177a96eee832f9d1e4`（分支
  `feature/process360-cockpit34-integration`）。仅新增并切换 8765 主服务 release，
  未修改或替换 8876 静态站、nginx、历史会话、上传、图表和分析缓存。
- release：`/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-a5342cd-20261028-180448`，
  PID `2561043`，监听 8765；旧 PID `2321809` 已正常退出，旧 release
  `process360-a6239d4-20261028-170622` 完整保留可回滚。`.env`、`.venv` 软链到
  `mcp-11dc92c-20261020`，运行 `dataset` 软链到共享数据目录；git archive 自带数据目录
  保留为 `dataset.tracked-a5342cd-20261028-180448`，未覆盖运行数据。
- 运行配置：`runtime-env.json` 权限 600，`RELEASE_COMMIT`、`PYTHONPATH`、
  `PROCESS360_CATALOG_PATH` 指向新 release；`PROCESS360_PG_*` 仍为
  `172.16.5.181:32444/ywln#ywln_crm`，`COCKPIT_DATA_MODE=ap`。临时 POC 设置
  `PROCESS360_CANVAS_DISPATCH_MODE=all`，并使用服务端单一接收人配置；接收人、手机号和
  身份字段不进入 HTML，页面提交这些字段会被拒绝。
- Skill：本地分发包 `ontology-analytics-skill.zip` 已按当前源码重建，24 个文件逐项一致，
  ZIP 完整性校验通过，SHA256 为
  `297911caba6a992560b6c0aee66be5bb38a59cf02522a2c65fd2a83247cb3d84`；分发包不入库。
- 切换方式：先在 `127.0.0.1:18765` 启动同提交预检实例，验证 `/healthz`、MCP 健康、
  Cockpit 配置/引擎/已发布分析、Canvas 行动卡和真实 PG 查询后停止预检进程；再 SIGTERM
  旧 8765 进程并由新 release `start-main.py` 启动。预检进程与 18765 端口已关闭。
- 验证：18765 与 8765 的 `/healthz`、`/api/mcp/health`（`missingExecutors=[]`）、
  `/api/cockpit/data/config`、`/api/cockpit/engines`、
  `/api/cockpit/analyses/published?id=1&page=analysis` 均 200；线上 Canvas 生成的测试卡
  `temporaryDispatch=true`，HTML 含“临时直发”“发送任务令”和服务端下发端点，且不含手机号。
  `Process360Plan + Process360Query`（SC01）返回 `partial`、来源
  `process360-postgres`、18.3961 亿元 / 4.6066 GWh，并披露 G01/G12/G16。
  `172.16.10.34:8765/healthz` 与 8876 根页面均 200，8765 日志无 Traceback 与 5xx。
- 边界：本轮未点击发送按钮、未创建真实 Fuxi 待办；真实点击回执和业务效果需在伏羲中人工
  验证。SC01 仍为 partial，SC02—SC05 不能据此判为完成；未创建 MR/tag/Release，未升级版本。
- 回退：停止本 release PID，使用旧 release
  `process360-a6239d4-20261028-170622/start-main.py` 启动；旧 release、共享环境和历史数据
  均保留。

### Cockpit iba-demo 1021 部署（2026-10-29 08:18）

- 代码提交：`2b7ff725f5653d8ffafe09c4d0cecd1898a195df`（分支
  `feature/cockpit-iba-demo-1021-deploy`）。该提交先把线上 Process360 基线 `b32449c`
  与 Cockpit `f68f0bd` 合并，再部署，避免以旧 Cockpit 分支覆盖 Process360 运行能力。
- 8765 主服务 release：
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-2b7ff72-20261029-081724`，
  PID `1629274`；旧 `process360-a5342cd-20261028-180448`（PID `2561043`）已优雅停止并
  完整保留。新 release 的 `.env`、`.venv`、`dataset` 继续软链原共享实体，git archive
  自带数据目录保留为 `dataset.tracked-2b7ff72-20261029-081724`；`runtime-env.json`
  为 600，`RELEASE_COMMIT`、`PYTHONPATH`、`PROCESS360_CATALOG_PATH` 指向新 release。
- 切换：新 release 先在 `127.0.0.1:18765` 预检通过，再停止旧 8765 并由
  `start-main.py` 启动新进程；18765 预检进程已停止，当前只监听 8765。
- 8876 静态站：`commit=2b7ff725f5653d8ffafe09c4d0cecd1898a195df`、
  `assetVersion=9c906a9a91660d3a9406`、资源前缀
  `/static/cockpit/releases/9c906a9a91660d3a9406`。新增资源目录与原 `4da3f092598bd18dde3b`、
  `31f5d6cf3c49bbdf2574` 并存；站点原地叠加，未替换 bind mount inode，未重启 nginx。
  manifest 128 项全部通过，站点根恢复为 755、文件 644。
- 备份：部署前完整站点备份为
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/backups/iba-demo-2b7ff72-20261029-081844`；
  新包暂存保留在
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/staging-iba-demo-2b7ff72-20261029-081844`。
- 验证：8765 `/healthz`、`/api/mcp/health`（`missingExecutors=[]`）、
  `/api/cockpit/data/config`、`/api/cockpit/engines` 均 200；真实 AP 单查成功，
  `FULL_PROCESS_OPERATIONS_MANAGEMENT` 头盔图返回 6 节点、`SALES_CALIBER` 返回 3 节点。
  8876 三页 `id=1|2` 均 200；浏览器逐节点确认经营看板 0、运营页 4、穿透页 8，共 12 个 AI
  插槽全部挂载；“查看销售额风险”“查看出货风险”正确路由并恢复目标节点；无 batch 适配器请求，
  无 JavaScript 或控制台异常。
- Process360：`Process360Plan` 正常，`Process360Query`（SC01）仍连接
  `process360-postgres`，当前因 G16 口径一致性缺口返回 `blocked`，未执行未经批准的口径查询。
  8765 日志无 Traceback；浏览器验收中 7 次 Cockpit AP 查询返回上游 502，页面按设计显示
  原始失败状态，不切换数据源或伪造数据。该现象属当前指标尚未配完，不是部署回退。
- 回退：停止新 release PID `1629274` 后，用
  `process360-a5342cd-20261028-180448/start-main.py` 启动旧 8765；静态站从上述备份目录
  原地复制回 `site` 并保持 755/644。不得删除或覆盖共享 dataset、历史会话、上传、图表和
  分析记录。本轮未创建 MR/tag/Release，未升级正式版本，未发送真实 Fuxi 待办。

### Cockpit 风险直发与失败态收口部署（2026-10-29 09:38）

- 代码提交：`98ababe86e5e0fb46c7b3233e7e82147157cbd41`（分支
  `feature/cockpit-risk-dispatch-closure`）。本轮保留页面直接发待办、直接推风险，服务端
  继续校验草稿/权限/接收人/幂等/回执，并在正文和卡片标注“临时直发 / 未经验证分析”，
  不将页面文字包装成已验证根因。
- 8765 主服务 release：
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-98ababe-20261029-0934`，
  PID `1933085`。切换前同提交实例先在 `127.0.0.1:18765` 预检通过，`/healthz`、
  `/api/mcp/health`（`missingExecutors=[]`）、`/api/cockpit/data/config`
  （`mode=ap`、`batchMode=individual`）、`/api/cockpit/analyses/published` 均 200；
  预检进程已停止，当前只监听 8765。旧 release
  `process360-cockpit-e1f508a-20261029-0932`、`process360-cockpit-ef093c5-20261029-0928`
  完整保留可回退；`.env`、`.venv` 继续软链共享环境，`dataset` 软链共享数据目录。
- 8876 静态站：`commit=98ababe86e5e0fb46c7b3233e7e82147157cbd41`、
  `assetVersion=85f84189ce8533c3cd19`、资源前缀
  `/static/cockpit/releases/85f84189ce8533c3cd19`。站点原地叠加，未替换 bind mount inode、
  未重启 nginx；manifest 128 项校验通过，三页 `id=1|2` 均 200。备份为
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/backups/site-98ababe-*`，
  新包暂存在 `staging-cockpit-98ababe-20261029-093532`。
- 失败态修复：AP 上游返回 `success:false` 时保留指标级原因；失败组件 KPI、周期、达成率、
  目标值显示“—”，失败组件内的 `0.00` 金额/电量/天数占位改为“—”，真实非零值与真实零值
  不替换；长期 `loading`/`加载中` 显示“加载失败”。失败提示出现后保留 6 秒宽限期，避免
  误伤仍在进行的查询；切换筛选时清空旧失败提示。
- 浏览器验收（172.16.10.34:8876，独立 headless Chrome）：运营页加载新资源
  `85f84189ce8533c3cd19`，头盔图无 `0.00` 节点，失败周期卡显示“— — 目标 — —”，
  无 JavaScript 异常；失败提示包含具体指标编码与上游原因（SQL 超时/请求不可达），
  未切换数据源、未补造数据。经营页在本次验收时上游接口大量 504，KPI 按设计显示“—”
  和失败原因；穿透页 AI 插槽显示指标级取数失败与重试，未输出伪造原因或建议。
- 直发验收：按用户本轮要求向固定接收人各发送一条带“【验收测试】”标识的条目。
  风险条目 `sourceTodoId=analytics-risk-canvas-b2aea9b406780ece052bc5fb52f6981b-risk-verify-20261029`、
  `executionId=c9f1108b24fe43fe8eba55d06c3a682c`，Fuxi 回执 `applied=1`；待办条目
  `sourceTodoId=analytics-canvas-8b21eafd3230f662409dc24f071fb69d-todo-verify-20261029`、
  `executionId=5c6f6aa5e5fe41ceb2500531a0b9800e`，Fuxi 回执 `applied=1`。两条均标注
  `temporaryDraft=true`、`verificationStatus=unverified`、`sourceKind=page_direct`；同一
  action 再次提交返回相同 `sourceTodoId`/`executionId` 且 `idempotentReplay=true`，未重复创建。
  另生成一张仅用于验收的 Canvas 行动卡页面（`canvas-20261029-094108-看板风险直发验收测试.html`），
  在 headless Chrome 中分别点击“推送风险”和“发送任务令”：风险回执
  `analytics-risk-canvas-243e4bc6cbeb681d62187253636a12f2-risk-html-verify-20261029`，
  待办回执 `analytics-canvas-bfea4966ace4c2b39f3cddd7e829b17f-todo-html-verify-20261029`；
  页面显示“已推送（未经验证分析）”/“已创建（未经验证分析）”，按钮点击后禁用，无 JavaScript
  异常。四条测试条目均带“【验收测试】”标识和 `unverified/page_direct` 标记。
  Fuxi 列表可见性仍需在伏羲客户端人工确认；回执成功只代表 Fuxi 接收，不代表根因已验证。
- Skill 分发包：`ontology-analytics-skill.zip` 已按当前源码重打，29 个文件，排除
  `__pycache__`/`.pyc`，SHA256 `94c9d56dc83283fb1d4159adaa6206d55abbf251b46fbf776dc699f58f3256cb`；
  工具说明已与 POC 直发模式对齐。分发包不入库。
- 边界：上游 AP 当前存在 SQL 超时和未配置指标，属于数据配置/上游故障，页面按设计明确失败。
  未创建 MR/tag/Release，未升级正式版本。
- 回退：停止本 release PID，使用旧 release
  `process360-cockpit-e1f508a-20261029-0932/start-main.py` 启动；静态站从上述备份目录
  原地复制回 `site` 并保持 755/644。不得删除或覆盖共享 dataset、历史会话、上传、图表和
  分析记录。

### Cockpit 全局失败横幅移除（2026-10-29 09:56）

- 代码提交：`2ef3e464cbc8bef03b4ba97aa66f2cae2e246292`（分支
  `feature/cockpit-risk-dispatch-closure`）。移除 `index.html` 中渲染 `liveError` 全文的
  全局红色横幅，失败指标和上游原因只保留在组件内错误与悬浮提示中；失败值 `—`、失败态
  清理和 6 秒宽限逻辑不变。
- 8765 release：
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-2ef3e4-20261029-0953`，
  PID `2009985`；同提交实例先在 `127.0.0.1:18765` 预检通过后切换。旧 release
  `process360-cockpit-968e75-20261029-0945` 完整保留。
- 8876 静态站：`commit=2ef3e464cbc8bef03b4ba97aa66f2cae2e246292`、
  `assetVersion=375937a05aa317ad6ff5`，manifest 128 项通过，三页 `id=1|2` 均 200；
  部署前站点备份为 `backups/site-2ef3e46-*`。
- 验证：运营页不再出现“部分指标加载失败”全局横幅（出现次数 0），组件内仍显示指标级
  上游失败原因，失败周期卡保持“— — 目标 — —”，无 `0.00` 占位和 JavaScript 异常。
- 回退：停止 PID `2009985`，用旧 release `process360-cockpit-968e75-20261029-0945`
  的 `start-main.py` 启动；静态站从上述备份原地恢复。

### Cockpit 状态行并入看板 Header（2026-10-29 10:10）

- 代码提交：`432e2a2b50380c34ffab805332560557fc08e7fa`（分支
  `feature/cockpit-risk-dispatch-closure`）。页面标题继续由看板组件
  `ProBiDashboardHeader` 的 `title` 渲染；“完整看板/数据时间/后台更新”状态行改由同一
  Header 的 `description` 渲染，删除 cockpit 自定义 `cockpit-publication-state`。失败时
  状态行只显示“部分数据加载失败”，不展开上游 SQL 错误。
- 8765 release：
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-432e2a-20261029-1006`，
  PID `2065756`；同提交实例先在 `127.0.0.1:18765` 预检通过后切换。旧 release
  `process360-cockpit-dd5e33-20261029-1005` 完整保留。
- 8876 静态站：`commit=432e2a2b50380c34ffab805332560557fc08e7fa`、
  `assetVersion=73cf660573ad48a69811`，manifest 128 项通过，三页 `id=1|2` 均 200；
  部署前站点备份为 `backups/site-432e2a2-*`。
- 验证：经营页 `.pro-bi-dashboard-header__main` 显示“储能经营风险驾驶舱”，
  `.pro-bi-dashboard-header__sub` 显示“部分数据加载失败”；页面不存在
  `.cockpit-publication-state`，无 JavaScript 异常。
- 边界：AI 插槽内容仍由 cockpit 的 `insight-components` 实现；页面标题和状态行不再由
  cockpit 自定义样式承载。
- 回退：停止 PID `2065756`，用旧 release `process360-cockpit-dd5e33-20261029-1005`
  的 `start-main.py` 启动；静态站从上述备份原地恢复。

### Cockpit AI 插槽移除未接线下发按钮（2026-10-29 10:30）

- 代码提交：`e355e5c0ce24382f423a48d9b39971aee1af45b1`（分支
  `feature/cockpit-risk-dispatch-closure`）。AI 插槽卡片按原型 HTML 交付，原型不含
  风险/待办下发按钮；本次删除 `insight-components/shipment-task-order` 中未接线的
  “下发 N 条任务令”占位按钮及对应 CSS。Canvas 生成 HTML 中的行动卡仍是
  “推送风险/发送任务令”的唯一入口（`temporaryDraft=true`、
  `verificationStatus=unverified`、`sourceKind=page_direct`）。
- 8765 release：
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-e355e5-20261029-1022`，
  PID `2133904`；同提交实例先在 `127.0.0.1:18765` 预检通过（`/healthz` 正常、
  `missingExecutors=[]`、`mode=ap`、`batchMode=individual`）后切换。旧 release
  `process360-cockpit-432e2a-20261029-1006` 完整保留，预检进程已停止。
- 8876 静态站：`commit=e355e5c0ce24382f423a48d9b39971aee1af45b1`、
  `assetVersion=b332f2bce76cb5252863`，manifest 128 项校验通过，三页 `id=1|2`
  均返回 200；部署前站点备份为 `backups/site-e355e5c-20261029-102449`。
- 验证：overview/operations/analysis 三页由看板组件 `ProBiDashboardHeader` 渲染标题
  “储能经营风险驾驶舱”，状态行位于 `description`；页面不存在
  `.cockpit-publication-state`；AI 插槽内按钮数量为 0（不再出现“下发 N 条任务令”）。
  分析页仍按设计显示组件级 AP 失败与 `—`，无 `0.00` 占位，无未捕获 JavaScript 异常。
  控制台存在既有的 Vue `insertBefore` 错误，已在上一版本 `432e2a2` 复现确认，不是本次
  改动引入，且不影响页面渲染。
- 回退：停止 PID `2133904`，用旧 release `process360-cockpit-432e2a-20261029-1006`
  的 `start-main.py` 启动；静态站从 `backups/site-e355e5c-20261029-102449` 原地恢复。

### Cockpit AI 分析按环节隔离上游失败（2026-10-29 11:40）

- 代码提交：`552e5a63476518d99886e0416c7a0531f6defba9`（分支
  `feature/cockpit-risk-dispatch-closure`）。单个 AP 指标查询失败不再让整页 AI 插槽
  全部报错：成功查询照常构成证据，失败查询按环节写入 `stageEvidence.failed/failedLabels`
  并在卡片限制中披露；本环节没有可用指标时继续交付限制卡，不引用其他环节数据、不生成
  原因和建议。前端分析请求新增 `unavailableQueries`，加载阶段显示“正在加载分析数据”，
  进入模型后显示“AI 正在分析”。商机证据白名单纳入客户规划与实际电量指标
  （`YWLN_M0075`、`YWLN_M_CUSTOMER_TARGET_ENERGY`、`YWLN_M_CUSTOMER_ACTUAL_ENERGY`），
  `YWLN_` 前缀自定义编码参与环节匹配；`vertex:[]` 且无指标/维度配置的组件在宿主侧
  直接标记“看板组件未配置实体查询字段，已跳过空查询”，不再发往 AP。
- 8765 release：
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-552e5a6-20261029-1124`，
  PID `2402427`；同提交实例先在 `127.0.0.1:18765` 预检通过后切换。旧 release
  `process360-cockpit-e355e5-20261029-1022` 完整保留。
- 8876 静态站：`commit=552e5a63476518d99886e0416c7a0531f6defba9`、
  `assetVersion=0c2fc8c9f9792677a2bd`，manifest 128 项通过，三页 `id=1|2` 均 200；
  部署前站点备份为 `backups/site-552e5a6-20261029-112909`。
- 验证：真实分析页在 8876 上由“所有卡片取数失败”变为可交付：商机获取卡最终显示
  “62 条证据”，无持续 loading、无错误；上游失败的 3 类商机指标在限制中列明
  “未纳入，不能据此判断该环节经营正常”。110 项 Cockpit Python 测试、29 项前端测试通过。
- 边界：上游 AP 的日期过滤 SQL 超时、`acc_t` 别名错误和慢查询仍需数据侧修复；本轮
  只是让看板在部分指标失败时继续分析可用环节并如实披露缺口，不补造数据。
- 回退：停止 PID `2402427`，用旧 release
  `process360-cockpit-e355e5-20261029-1022` 的 `start-main.py` 启动；静态站从
  `backups/site-552e5a6-20261029-112909` 原地恢复。

### Cockpit 分析排队优先与数据库同口径补查上线（2026-10-29 11:55）

- 代码提交：`fe154e9da3f1b6c5dbe9bf82ccf994f807ea91c2`（分支
  `feature/cockpit-risk-dispatch-closure`）。分析槽位占满时后端不再返回 429，改为
  `queued` 任务等待共享槽位（最长 900 秒）；前端按真实视口排序（重试最高、屏幕内按位置、
  屏幕外最后），取数在申请槽位之前完成，卡片在排队期间持续加载。
- 数据库补查：页面 AP 查询失败时，主服务按同一指标/维度/筛选口径从
  `172.16.5.181:32444`（`ywln` / `ywln_crm`）只读补查，结果保存为独立的 `pg` 凭据
  （`kind=pg`、`transport=postgres`、`authScope=<registry version>`），页面成功结果仍以
  AP 为准，同一计算范围只用一种来源。
- 口径登记：`dataset/process360/ywln-v3.1/pg-fallback.json` 版本
  `ywln-pg-fallback-2026-10-29.2`。仅 `YWLN_M0036 发货金额` 为 `enabled`；`YWLN_M0024 商机数`
  因对账相差约 4 倍标记 `RECONCILE_GAP`，不输出数字。维度、`D007`、产品类型等未映射筛选
  返回 `DIMENSION_UNMAPPED`/`FILTER_UNMAPPED` 等原因代码，不换指标、不补 0。单次分析最多
  补查 4 条失败查询。
- 8765 release：
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-fe154e9-20261029-1150`，
  PID `2496079`；旧 `process360-cockpit-552e5a6-20261029-1129`（PID `2402427`）完整保留。
  `.env`/`.venv` 软链沿用上一 release，`dataset` 由 git archive 后与当前运行副本无覆盖合并，
  `history.sqlite3`（3.76 MB）保留；`runtime-env.json` 的 `PYTHONPATH`、`PWD`、
  `RELEASE_COMMIT` 指向新 release，`preflight-main.py` 从上一 release 复制。同提交实例先在
  `127.0.0.1:18765` 预检通过后切换。
- 8876 静态站：`commit=fe154e9da3f1b6c5dbe9bf82ccf994f807ea91c2`、
  `assetVersion=ad7a02148ca32ce8b2ec`、资源前缀
  `/static/cockpit/releases/ad7a02148ca32ce8b2ec`；新增资源目录与既有目录并存，站点原地
  叠加，未替换 bind mount inode，未重启 nginx。manifest 128 项通过，目录 755、文件 644。
  部署前站点备份 `backups/site-fe154e9-20261029-115307`，新包保留在
  `staging-cockpit-fe154e9-20261029-115307`。
- 验证：8765 `/healthz`、`/api/cockpit/data/config`、`/api/cockpit/bootstrap`、
  `/api/cockpit/startup`、`/api/cockpit/analyses/published` 均 200；新 release 的 venv 内直接
  执行补查得到 2025 全年发货金额 79.16 亿元。线上真实复现：发货金额 AP 返回 504（网关超时）
  时，创建的分析任务上下文为 `dataSource=ap+pg`、`pgReceiptIds=1`、
  `fallback.metrics=["YWLN_M0036"]`、`stageEvidence.failed=0`，随后取消该任务（状态
  `cancelled`），未产生卡片、未写业务数据、未发送 Fuxi 待办。8876 三页 `id=1|2` 均 200，
  `cockpit.js`/`page-client.js`/`publication-client.js` 下载后语法检查通过。
- 回退：停止 PID `2496079` 后，用
  `process360-cockpit-552e5a6-20261029-1124/start-main.py` 启动旧 8765；静态站从
  `backups/site-fe154e9-20261029-115307` 原地恢复。
- 边界：上游 AP 的日期过滤 SQL 超时、`acc_t` 别名错误和慢查询仍需数据侧修复；补查只覆盖
  已登记且对账通过的指标，商机数等未对齐口径继续返回阻断原因，不替代看板图表自身的错误提示。

## 服务端定时刷新与页面订阅（2026-10-29，代码已实现，部署需新的明确授权）

- 刷新调度由浏览器移到主服务：页面打开只读取 `page_snapshots` 中的上次完整版本，不再自行发起
  模型分析；服务端按默认范围定时复核数据指纹，只有数据或口径变化才调用模型。
- 新增表 `page_refresh`（`scope` 主键、`status`、`attempt`、`next_check`、`lease_until`、
  `last_error`、`last_success`、`updated`），由 `Store` 在打开历史库时自动创建，不迁移、不删除
  既有分析与页面快照。
- 新增接口：`GET /api/cockpit/publications/status`（轻量状态）、
  `POST /api/cockpit/publications/refresh`（手工把某个范围置为待刷新）；`GET /api/cockpit/startup`
  改为返回 `snapshot` + `status`，`POST /api/cockpit/page/lookup` 增加 `displaySnapshot`/
  `displayStale`。
- 调度线程随 `build_cockpit_router` 启动，仅在 `COCKPIT_DATA_MODE=ap` 且已连接主服务上下文时启用；
  配置异常只打印日志并关闭调度，不影响读取上次发布版本。
- 环境变量：`COCKPIT_REFRESH_ENABLED`（默认开启，测试环境关闭）、
  `COCKPIT_REFRESH_INTERVAL_SECONDS=900`、`COCKPIT_REFRESH_TIMEOUT_SECONDS=1200`、
  `COCKPIT_REFRESH_SCAN_SECONDS=20`、`COCKPIT_REFRESH_SCOPE_LIMIT=1`。时间可按数据源更新频率
  调整，检查数据不等于重新调用模型；范围上限默认 1，避免后台预热同时占满页面 AP 槽位。
- 更新失败、AP 超时、模型失败或进程重启都不覆盖上一版本；`retry_wait` 按 60 秒递增退避，上限
  15 分钟，租约过期后由调度器重新领取。
- 前端先渲染已发布快照，再按 5～15 秒轮询版本（页面隐藏时降频），发现新版本才拉取整页替换；
  状态行不再显示“路由、取证与交付校验中”等内部步骤。
- 本段只记录实现与配置；部署、重启 8765 或更新 8876 静态资源仍需当次明确授权。
- 设计与验证细节见 `docs/specs/cockpit-card-publications.md`。

### 定时刷新闭环修复（2026-10-29）

- 新增 `refresh_plans`（`scope` 主键、`body`、`updated`），保存手工刷新的查询计划；仍在
  `Store` 打开历史库时自动创建，只新增表，不迁移或删除历史会话、分析、草稿、回执和页面快照。
- `RefreshScheduler` 每次扫描显式登记两种身份 × 三个默认页面，不再要求先存在整页快照；有整页
  版本的范围复核整页，没有整页版本但已发布环节卡片的运营页/穿透页复核卡片。没有查询计划的
  范围标记 `awaiting-plan`，不再伪装成 `idle` 或持续 `waiting`。
- 页面与环节卡片复核统一调用 `dashboard_source.page_analysis_context`，与 HTTP 分析入口共享
  证据解析、`snapshotId`、`dataFingerprint` 和来源披露；helmet 图不进入业务分析凭据。
- 单条 AP 业务查询失败时按同一环节与筛选调用已登记 PostgreSQL 补查；整页复核先合并所有环节的
  补查凭据再分析，页面记录 `dataSource=ap+pg`/`pg`、`dataIdentity=postgres`，补查凭据独立保存。
  `PageRequest` 新增 `pgReceiptIds`，整页条目可包含 `kind=pg` 的补查结果。
- 手工刷新改为 `Store.request_refresh`：运行中的租约不会被清除；没有查询计划的范围返回 409，
  不再创建随后被调度器置为 `idle` 的空任务。
- 新增 `GET /api/cockpit/publications/cards`，`GET /api/cockpit/publications/status` 增加
  `cardsVersion`；没有整页快照的页面按卡片版本原位替换。
- `Store.default_views()` 只返回每个业务环节最新的卡片键；配置轮换留下的旧键不会被调度器
  反复复核。整页复核会回读历史失败查询，AP 恢复后替换补查或部分证据。
- 没有整页快照的运营页/穿透页，其状态接口聚合环节卡片状态：未来定时检查为 `scheduled`，
  手工刷新为 `waiting`/`running`，发布完成为 `published`，页面不会永久显示后台更新提示。
- 前端状态轮询改为 `publication-poll.js` 单一循环：探测异常继续重试，页面卸载后停止，标签页
  隐藏时降频，重新可见时立即检查；文件随 8876 静态资源一起发布，需要新的 `COCKPIT_VERSION`。
- 发布步骤不变：8765 使用新 release 目录并通过 `preflight-main.py` 预检后重启；8876 先备份
  `site/`，再用 `scripts/build_cockpit_site.py` 生成的新静态包整体替换。`history.sqlite3` 从旧
  release 复制/沿用，禁止覆盖或清空。
- 验证：Cockpit 聚焦 Python 测试 147 项通过；Node 测试 48 项通过；新增用例覆盖真实证据解析、
  PostgreSQL 补查整页发布、无整页快照的卡片维护、手工刷新租约去重、自定义范围执行、轮询
  失败续跑与卡片版本原位替换。

### 刷新生命周期与静默更新收口（2026-10-29）

- `page_refresh` 在启动时做加法迁移，增加 `business_key`、`config_version`、`lifecycle`、
  `last_access`、`expires`、`superseded_by`、`job_id`、`worker_id`、`deadline`、`heartbeat`、
  `generation`。旧配置产生的范围只标记为 `superseded`，不删除页面快照、分析或任何历史结果。
- 默认范围常驻维护；自定义范围由 `COCKPIT_CUSTOM_REFRESH_TTL_SECONDS` 控制（默认 86400 秒）。
  到期查询、手工刷新和任务领取都校验 `active`、配置版本和有效期；旧范围不会再永久占用调度扫描。
- 刷新 worker 领取时保存 job/generation，分析等待期间续租；超时或租约失效会协作取消分析。
  手动刷新不会清掉正在运行的租约；已被重新排队或配置轮换的旧 worker 不能完成状态或覆盖发布版本。
- 两个角色、三张默认 AI 表格在启动后按浏览器相同的默认查询键预热并持久化；浏览器先读缓存，
  后台更新时只有实际行数据变化才重建 DataTable。新整页版本通过现有 runtime 原位更新图表，
  不再重挂看板或整页取数。
- 状态接口的 `update.queue` 提供 `activeCount`、`dueCount`、`runningCount`、`waitingCount`、
  `oldestWaitSeconds`、`timedOutCount`，用于区分历史记录和实时待执行队列。
- 本次只使用加法迁移和后台线程，不修改服务器 `.env`、历史会话、上传文件或任务数据；部署仍需当次
  明确授权。

### Cockpit 初始化重复 loading 修复上线（2026-10-29 18:48）

- 代码提交：`71070ee789c9c99355cef8eecbbf564a302f0981`（分支
  `feature/cockpit-risk-dispatch-closure`）。ProUI 初始化时回放默认筛选（`YEAR`、日期等）不再
  被当成用户切换口径：初始化阶段只记录状态，第一次真实用户操作后才允许触发 `changeScope()`；
  节点选择、头盔图选择继续作为视图状态，不进入数据查询范围。
- 防止宿主重建循环：整页快照增加 `id`／页面／`uiScope` 一致性校验和幂等安装；同一页面、同一
  范围、同一快照版本不再重复递增 `boardRevision` 重挂看板。快照缺失恢复最多每 30 秒一次，
  普通重复范围请求在 1.2 秒内合并；范围准备失败会进入明确错误态，不再无限加载。
- AI 插槽补齐终止态：服务端没有该环节可用卡片时显示“该环节尚无可用分析结果，服务端正在补充
  当前口径数据”，不再保留无限骨架屏；有已发布卡片的插槽继续直接展示。
- 8765 release：
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-71070ee-20261029-1848`，
  PID `4187781`。同提交实例先在 `127.0.0.1:18765` 预检 `/healthz`、
  `/api/cockpit/data/config`、两种角色各 15/15 张 AI 卡片后切换；`.env`、`.venv` 和
  `dataset` 继续指向旧 release 的共享副本，历史分析库未复制、清空或迁移；旧 release
  `process360-cockpit-464ae6c-20261029-1807` 完整保留。预检进程已停止，`18765` 不再监听。
- 8876 静态站：`commit=71070ee789c9c99355cef8eecbbf564a302f0981`、
  `assetVersion=858ed16fc8bac3de386e`、资源前缀
  `/static/cockpit/releases/858ed16fc8bac3de386e`；manifest 146 项校验通过。站点原地叠加，
  nginx bind mount inode 未变、未重启 nginx。部署前备份
  `backups/site-71070ee-20261029-1848`，暂存包保留在
  `staging-cockpit-71070ee-20261029-1848`。
- 真实浏览器验证（`172.16.10.34:8876`，独立 headless Chrome）：运营页 `id=1|2` 首屏正常
  结束加载，无启动占位、无持续 AI 骨架、无 JavaScript 异常；`id=1` 稳定后连续观察 20 秒，
  新增 `/api/cockpit/data/query` 为 0，页面未重复重建。经营看板 `id=1` 同样无加载残留。
  穿透页仍有少量 AP 慢查询在 180 秒预算内等待，属于上游数据等待，不是宿主重复刷新。
- 回退：停止 PID `4187781`，用旧 release
  `process360-cockpit-464ae6c-20261029-1807/start-main.py` 启动；8876 静态站从
  `backups/site-71070ee-20261029-1848` 原地恢复。

### Cockpit AI 缓存、表格口径与任务令下发上线（2026-10-29 22:54）

- 代码提交：`ae5933143017b652d50d49a63ba4ea36c34544a1`（分支
  `feature/cockpit-risk-dispatch-closure`）。补齐第三页 `computed` 引用、AI 插槽错误终态、
  全插槽旧口径提示、后台发布原位更新、AI 表格持久快照/页面期间继承、发布完整性统计和发货任务令
  草稿编辑下发闭环；默认页面期间与默认预热缓存统一为 `2025-10`。
- 8765 release：
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-ae59331-20261029-2254`，
  PID `962439`。新 release 先在 `127.0.0.1:18765` 预检 `/healthz`、`data/config`、两种角色
  AI 发布后切换。`.env`、`.venv` 沿用共享实体，`dataset` 继续软链
  `process360-cockpit-464ae6c-20261029-1807/dataset`；历史分析库未复制、清空或迁移。
- 发布过程处置：`git archive` 自带空 `dataset/` 目录，首次预检因此读到空库并返回 0/15。
  预检进程停止后，将该目录原样移到
  `process360-cockpit-ae59331-20261029-2254/dataset.local-preflight-ae59331-20261029-2254`
  保留，再建立共享 `dataset` 软链并重跑预检；没有删除任何用户数据。旧 8765 进程 `845106`
  在预检通过后由 SIGTERM 正常停止，旧 release `process360-cockpit-dd27e55-20261029-1948`
  完整保留。
- 8876 静态站：`commit=ae5933143017b652d50d49a63ba4ea36c34544a1`、
  `assetVersion=531a79456736f510ee6f`、资源前缀
  `/static/cockpit/releases/531a79456736f510ee6f`；新资源 147 个文件，manifest 校验通过。
  发布前备份 `backups/site-ae59331-20261029-225539`，暂存包保留在
  `staging-cockpit-ae59331-20261029-225539`；站点原地叠加，未重启 nginx。
- 验证：`/healthz`、三页静态路由、`release.json`、新 `cockpit.js`／`cockpit.css`、
  `/api/cockpit/startup`、AI 发布接口均返回 200；两种角色默认范围均为
  `readyCount=15`、`missingCount=0`，按新完整性字段显示 15 张 limited（可渲染，但不伪装为
  内容完整）。默认页展示期间 `2025-10`，AI 表格默认请求显式携带该期间并映射为
  `YWLN_D044` 的 `2025-10-01` 至 `2025-10-31`。主服务日志无 Traceback 或 5xx。
- 回退：停止 PID `962439`，用旧 release
  `process360-cockpit-dd27e55-20261029-1948/start-main.py` 启动 8765；8876 从
  `backups/site-ae59331-20261029-225539` 原地恢复入口文件。旧资源和历史分析数据均已保留。
- 边界：本轮没有实际下发任务令或风险；接收人配置为 `18837823993`，只在用户点击“确认下发”
  时由服务端调用待办接口。AP 侧慢查询和未登记指标口径仍按原有受限结果披露。

### Cockpit 自动合页静默与最终静态发布（2026-10-30 08:25）

- 代码提交：`07650cdb8e656e1d6beb323d675aee75e60be560`（分支
  `feature/cockpit-risk-dispatch-closure`），在 `28e7745` 基础上修复自动整页合并的误报：
  `/page` 的后台校验拒绝和本地 `client.entries()` 未齐全不再写入 `pageState.error`，三页标题
  不再出现“部分数据加载失败”；显式用户刷新仍保留自己的错误态。前序提交包括 `7d9e98c`
  （AI 表格去重日期筛选）和 `c36feca`（ProUI 头盔深链路径对象）。
- 8765 主服务：release
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-28e7745-20261030-0813`，
  PID `3129750`，提交 `28e7745`；`/healthz` 正常，`18765` 预检进程已停止。本轮只更新静态站，
  未重启 8765，`.env`、`.venv` 和 `dataset` 继续使用共享目录；历史分析、会话、上传和图表未删除、
  未迁移。
- 8876 静态站：`commit=07650cdb8e656e1d6beb323d675aee75e60be560`、
  `assetVersion=38d6b9718fa7076aac5f`、资源前缀
  `/static/cockpit/releases/38d6b9718fa7076aac5f`；147 个文件，manifest 全量校验通过。
  部署前备份为
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/backups/site-07650cd-20261030-082320-pre`，
  暂存包保留在 `staging-cockpit-07650cd-20261030-082320`。站点原地叠加，未重启 nginx；`site`
  目录权限保持 `755`。
- 验证：两个角色 `id=1|2` 的默认范围均为 `expectedCount=15`、`readyCount=15`、
  `missingCount=0`；三张 AI 表格在两个角色下的 `cacheOnly=true` 请求共 6/6 返回 `200/hit`。
  真实浏览器（`172.16.10.34:8876`）复核经营看板、运营页、穿透页：无 AI loading、无
  “部分数据加载失败”、无 JavaScript 异常；三页 `id=1|2` 路由均返回 200。
- 口径与限制：页面“分析更新于 2026/10/29”是最后一次成功分析时间，不是本次部署时间。数据指纹
  未变化时服务端按设计复用上次成功分析，没有为刷新展示时间而强制调用模型；现有卡片仍为
  `limited`，表示可交付但存在上游证据或指标缺口，不等于根因已经充分验证。
- 回退：静态入口可从
  `backups/site-07650cd-20261030-082320-pre` 原地恢复；如需回到本轮部署前的静态版本，可使用
  `backups/site-28e7745-20261030-0815-pre`。8765 回退时停止 PID `3129750`，使用旧 release
  `process360-cockpit-7d9e98c-20261030-0759/start-main.py` 启动。不得删除历史 release、
  备份、会话、上传、图表或 dataset。

### 2026-10-30 · 共同分析单插槽发布

- `sales-shipment-issues` 改为独立 `combined` 分析，保留原 `shipment` 发布历史。通过 `POST /api/cockpit/combined/preheat`（`id`、`page=analysis`、`uiScope=default`）仅重新生成此插槽；只读现有 AP 凭据，允许复用已过 TTL 的冻结结果并披露历史来源，不续签观察时间、不访问 AP/PG。
- 普通组件 SQL 调度不负责此组合任务。部署保留共享 dataset、凭据与虚拟环境，后台刷新配置保持既有值；不清空其他卡片、不手动请求全量刷新。验证应检查组合分析使用至少两个环节的同期间查询，其他插槽分析 ID 不变。

- 本次实际部署：代码 `c087a0cf22fa556ddd6831175c02318c831c1bb8`，8765 release `process360-cockpit-c087a0c-20261030-combined`，PID `3250689`；8876 `assetVersion=4775ab66d1ec485bc4a3`。原服务正常退出后启动新服务，未并行保留验证调度器。入口备份 `backups/site-combined-c087a0c-pre`，共享 `.env`、`.venv`、dataset 未覆盖。
- 仅主动预热共同分析：总裁 `a5f779c3bc5543b887b0365154935bc1`（8 查询、117 条证据、8 原因、5 建议），分析员 `d9deeae109fe43dcb8d54b24c9fdd987`（9 查询、118 条证据、4 原因、2 建议）；两者为 limited，继续披露因果未验证及上游缺失。两个角色均恢复 15 个可渲染插槽；共同分析 ID 与发货卡片分离。
- 验证：58 项相关 Python、7 项前端测试通过；manifest 校验通过。浏览器拦截实时取数后，第三页共同分析正常显示、AI loading=0、无 JS 异常；没有实际下发待办或风险。

### 2026-10-30 · 报价状态插槽单独替换

- 通过 `POST /api/cockpit/quotation/preheat`（`id`、`page=operations`、`uiScope=default`）仅重建报价分析；从同角色、同连接、同日期范围的已保存 `YWLN_D021`/`YWLN_M0031` 凭据取证，不重新请求 AP/PG。
- 插槽按原始记录展示完成/未完成状态，元数据及头盔图保持原样。发布保留其他卡片和共享 dataset，入口资源使用独立版本目录，可回退到前一版本入口文件。

- 实际上线 `919c3922ac3ae0fb3ab3f354484cac40e255bb6f`（包含 `75cb19c`），8765 release `process360-cockpit-919c392-20261030-quote`，PID `3327493`；8876 资源版本 `9b5c5e29d1bc366efc7b`，入口备份 `backups/site-quote-75cb19c-pre`。报价压缩响应仅保留状态/电量两个展示字段，修复原始行在发布层被裁掉的问题。
- 仅预热报价：总裁 `b0933d26279e4cfdb155ff07bf571781`、分析员 `088dce766ee542ca96adb938e2afdc3c`。两个角色均 15 个 ready；逐插槽比较仅 `quote-summary` 的分析 ID 变化，共同分析及其他卡片未重算。正常完成 25.57、逾期完成 0.56、逾期未完成 0.60 GWh，未返回状态不补零。

### 2026-10-30 · 关闭已完成 AP 响应复用（8765 + 8876）

- 代码 `37476f2b471b2a40d382025aa3cf2b701b293cba`（`bugfix/cockpit-disable-ap-reuse-cache`）：后端 `COCKPIT_AP_REUSE_SECONDS` 默认 `0`，前端 `DATA_REUSE_WINDOW_MS = 0`；相同查询不再复用上一次已完成响应，重叠在途请求仍合并。AI 发布卡片与历史快照不受影响。
- `8765` 主服务：release `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-37476f2-20261030-no-ap-cache`，PID `3852987`，进程环境未设置 `COCKPIT_AP_REUSE_SECONDS`（走默认 `0`），`.venv`／`.env`／共享 `dataset` 继续使用原目录。
- `8876` 静态站：`assetVersion=b6628694318ccccd18f1`，`commit=37476f2`，资源前缀 `/static/cockpit/releases/b6628694318ccccd18f1`，manifest 149 个文件校验通过。部署前备份 `backups/site-919c392-20261030-105250-pre`，新站目录 `site-next-37476f2-20261030-105008`，`site` 软链已指向新目录。
- 8876 的 nginx 容器（`eimosp-cockpit-8876`，ID `10de73310da9`）以 bind mount 在启动时解析 `site` 软链，仅切换软链不会生效；本次执行 `docker restart 10de73310da9` 后重新解析挂载。重启后 `http://172.16.10.34:8876/` 返回 200，`release.json` 与 `/static/cockpit/releases/b6628694318ccccd18f1/data-client.js` 均为新版本（`DATA_REUSE_WINDOW_MS = 0`）。
- 验证：`8765 /healthz` 200；连续两次相同 AP 查询 receipt `aed6f8e82312`／`524fe7cd7eec`，`cacheHit=false`、`follower=false`，证明已完成响应不再复用。Python 42 项、Node 82 项测试通过。
- 回退：`8765` 停止 PID `3852987` 后用旧 release `process360-cockpit-919c392-20261030-quote` 启动；`8876` 将 `site` 软链指回 `backups/site-919c392-20261030-105250-pre` 并再次 `docker restart 10de73310da9`。不得删除历史 release、备份、会话、上传、图表或 dataset。

### 2026-10-30 · 图表默认实时取数（8876 静态站）

- 代码 `4c933e41f836973f61a4b3624f23a6502377cd83`（`bugfix/cockpit-disable-ap-reuse-cache`）：`cockpit.js` 只有在 URL 带 `?cache=1` 时才把整页快照交给数据客户端回放；默认传 `null`，图表逐条实时查询 AP。AI 发布卡片与显示元数据仍来自发布结果。
- `8876` 静态站：`assetVersion=4dc6e0a2dda046f2c5bd`，`commit=4c933e4`，资源前缀 `/static/cockpit/releases/4dc6e0a2dda046f2c5bd`，manifest 149 个文件校验通过；目录 `site-next-4c933e4-20261030-115044`，`site` 软链已切换，容器 `10de73310da9` 重启后 HTTP 返回新版本。
- `8765` 后端保持 `process360-cockpit-37476f2-20261030-no-ap-cache`（PID `3852987`），本轮未改后端代码；`/healthz` 200。
- 验证：Node 看板测试全通过、`node --check` 通过；`release.json`、入口 HTML、`cockpit.js` 均返回新版本并包含 `cache=1` 分支。AP 已完成响应复用仍为关闭（`COCKPIT_AP_REUSE_SECONDS` 默认 `0`、`DATA_REUSE_WINDOW_MS=0`）。
- 回退：`site` 指回 `site-next-37476f2-20261030-105008` 并重启容器 `10de73310da9`；更早备份 `backups/site-919c392-20261030-105250-pre`。不得删除历史 release、备份、会话、上传、图表或 dataset。

### 2026-10-30 · 逐插槽交付契约与推理校验上线

- 代码 `14b258720c5bcbfbb65d228b5eab4b7a253fd9b7`（`bugfix/cockpit-disable-ap-reuse-cache`）：新增 `bi_agent/cockpit/delivery.py`，按 15 个插槽裁剪同一环节分析并校验推理；金额/电量混用比较、未验证集合相加、现象写成原因、目标口径冲突隐藏、不可检查验收会在交付时被拒绝。
- `8765` 主服务：release `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-14b2587-20261030-143353`，PID `590092`，`/healthz` 200，启动日志无 Traceback。`.env`、`.venv`、`dataset` 继续软链到原目录，历史数据未覆盖。
- `8876` 静态站：`assetVersion=75295eae3d3c7f708a7f`，`commit=14b2587`，目录 `site-next-14b2587-20261030-143548`，manifest 校验通过，容器 `10de73310da9` 重启后生效。
- 验证：两个角色 `/api/cockpit/ai-publications` 均 `readyCount=15`、`missingCount=0`，所有插槽 `deliveryContract=cockpit-delivery-v2`；`quote-summary` 与 `shipment-overdue-note` 不再携带原因列表，`bid-summary` 原因已标注 `[结构定位]` 等层级。
- 回退：`8765` 停止 PID `590092`，用旧 release `process360-cockpit-37476f2-20261030-no-ap-cache/start-main.py` 启动；`8876` 将 `site` 指回 `site-next-4c933e4-20261030-115044` 并重启容器。不得删除历史 release、备份、会话、上传、图表或 dataset。

### 2026-10-30 · 交付推理清理与逐插槽完整性验收（8765 + 8876）

- 代码提交序列 `012fd2a7a68483c0c270e9ce8a6781887c4cc668`、`d611a72c42fcaf616977e97a040723a84240e306`、`71a4da67335f6843300c790416e85a8b141dd140`（`bugfix/cockpit-disable-ap-reuse-cache`）：交付投影直接删除跨金额/电量推断和由同一推断派生的“取消变更量级有限”子句；删除原因后同步剔除悬空建议；原因分类按标题优先；证据计数按 id 去重；逐插槽完整性按职责判断，状态类卡片不再强制要求原因和措施。
- `8765` 主服务：release `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-71a4da6-20261030-151759`，PID `763133`，`/healthz` 200，`/api/mcp/health` 返回 `missingExecutors=[]`，启动日志无 Traceback。新 release 在 `8769` 关闭定时刷新预检通过后再切换。`.env`、`.venv`、共享 `dataset` 均软链到原目录，未覆盖历史会话、上传、图表或分析数据。`git archive` 自带的 `dataset/` 已原样改名为 `dataset.git-archive-71a4da6`，再建立共享软链。
- `8876` 静态站：`assetVersion=f4b2cb70ffa2f8e87c77`、`commit=71a4da67335f6843300c790416e85a8b141dd140`、资源前缀 `/static/cockpit/releases/f4b2cb70ffa2f8e87c77`，manifest 149 个文件校验通过；目录 `site-next-71a4da6-20261030-151847`，`site` 软链已切换，容器 `10de73310da9` 重启后生效。
- 验证：两个角色 `/api/cockpit/ai-publications` 均为 `readyCount=15`、`missingCount=0`；报价 `contentGaps=['ANALYSIS_LIMITED']`，共同分析去重证据为 117/118 条。总裁共同分析保留 5 条有依据的原因，分析员保留口径冲突、商机覆盖、客户结构 3 条；接口全文不再出现“难以解释”“不足以解释”“金额占比不足”“订单取消变更量级有限”及悬空 `signed-unsigned-scope`。8876 首页、三个 Cockpit 路由、静态 `cockpit.js` 均返回 200；`release.json` 已指向 `71a4da6`。
- 自动化验证：Cockpit 相关 Python 219 项通过，Node 看板测试 82 项通过，`git diff --check` 通过。本次验收请求只读取已发布结果，未主动触发 AP 或模型重新分析；代码修改集中在交付投影和验收口径。
- 回退：停止 8765 PID `763133`，用 `process360-cockpit-d611a72-20261030-151355/start-main.py` 启动；8876 将 `site` 指回 `site-next-012fd2a-20261030-151130` 并执行 `docker restart 10de73310da9`。更早 release、备份、共享 `dataset`、会话、上传、图表和分析结果均完整保留，不得删除。

### 2026-10-31 · 8765 AI 交付优化发布

- 部署代码 `8e1c8882abd41aa1976d4603a5b69bb5d25c0500`，release `process360-cockpit-8e1c888-20261031`，PID `2641625`；原 8765 服务正常退出后启动新服务，无并行验证进程。正式入口仍为 `http://172.16.10.34:8765/api/ontology-agentic-analytics/cockpit/{overview|operations|analysis}`；8876 未更新。
- 沿用原 `.env`、`.venv`、共享 dataset 与路由前缀，未清空、迁移历史数据，未手动触发 AP、模型分析或任务下发。旧 release `process360-cockpit-71a4da6-20261030-151759` 保留供回退。
- 线上三页、JS 资源和 healthz 均正常；两个角色各 15 个可读取插槽，无建议原因引用断裂；重复句号、生成说明、数据缺口分类修复已在接口响应生效，报价3条状态行保留。发布体积分别约362 KB、625 KB。复验为路由、资源及发布接口检查，未执行浏览器交互全流程。

### 2026-11-02 · 8765 风险数量标签 runtime 绑定修复发布

- 部署代码 `990c4fa365078ccb86aa9d52d4dc1c283b3dc494`（`bugfix/cockpit-disable-ap-reuse-cache`）：移除 `syncRiskCountLabels(runtime=biRuntime.value)` 的非法默认参数，改为由页面显式绑定最终 `biRuntime.value`；AI 卡片后台更新、筛选重建和快照初始化共用绑定 runtime，组件卸载时按 runtime 身份解除绑定，避免旧实例继续写入。
- `8765` 主服务：release `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-990c4fa-20261102-094608`，PID `3677772`。新 release 先在 `18765` 预检通过后切换，预检进程 `3676578` 已停止；旧 release `process360-cockpit-8e1c888-20261031` 与旧 PID `2641625` 保留用于回退。`.env`、`.venv`、共享 `dataset` 继续软链原目录，`git archive` 自带的 `dataset/` 保留为 `dataset.git-archive-990c4fa`，未覆盖历史会话、上传、图表或分析结果。
- `8876` 保持既有反向代理到 `8765`，无需单独构建静态站；根地址、三个 `/cockpit/*` 路由和静态 `cockpit.js` 均返回新版本，Fuxi 现有 8876 地址继续有效。
- 验证：`/healthz`、三页入口、静态资源和 Cockpit API 均返回 200；两个角色 `id=1|2` 的 `/api/cockpit/ai-publications` 均为 `readyCount=15`、`missingCount=0`、`renderableCount=15`。真实 headless Chrome 覆盖 8765 两角色三页面共 6 组路由及 8876 代理入口，未出现看板配置加载失败、`ReferenceError` 或浏览器异常；风险数量标签可从“风险分析中”更新为实际条数。
- 自动化验证：Cockpit 相关 Python 222 项通过，Node 看板测试 83 项通过；新增专项浏览器回归覆盖 AI 结果先于 runtime 返回、三个页面首次打开、切 Tab 和筛选重建，`git diff --check` 通过。本次未手动触发 AP、模型分析或任务下发。
- 回退：停止 8765 PID `3677772`，在 `process360-cockpit-8e1c888-20261031` 执行 `nohup python3 start-main.py >> main-8e1c888.log 2>&1 &` 恢复旧版本；不得删除新 release、历史 release、备份、共享 `dataset`、会话、上传、图表或分析记录。8876 仍代理到恢复后的 8765，无需改 nginx。

### 2026-11-02 · 风险事实计数与头盔组件接口同步发布

- 部署代码 `84fd3b803e89237b9b60601cd77e158cd6d999c4`（`bugfix/cockpit-disable-ap-reuse-cache`）：顶栏风险数改为只统计当前指标范围内、证据有效且去重的 `risk_fact`，销售额与出货量分域计数；原因、数据缺口、结构定位不进入风险数。发布响应同时返回 `known` 与 `complete`，数据不完整时保留上次有效标签，不把未知状态显示成 `0条风险`。同步 `iba-demo feature/demo_1021@cdaa3b6` 的 `pro-bi-ui.min.js` 和模板，支持 `helmetViewUrl`，并把上游内网绝对地址在运行包中统一改写为 `/api/gateway2/x360/v1/graphs/helmet-view`。
- `8765` 主服务：release `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-84fd3b8-20261102-102335`，PID `3851649`。新 release 先在 `18765` 预检，预检进程 `3850132` 已停止；预检显式关闭刷新调度，正式进程继续沿用 `COCKPIT_REFRESH_ENABLED=1`。旧 release `process360-cockpit-990c4fa-20261102-094608` 与旧 PID `3677772` 保留用于回退。
- 运行边界：`.env`、`.venv` 继续软链到 `mcp-11dc92c-20261020`，`dataset` 继续软链到共享数据目录；`git archive` 自带数据目录保留为 `dataset.git-archive-84fd3b8`。`runtime-env.json` 权限 600，`RELEASE_COMMIT`、`PYTHONPATH`、`PWD` 指向新 release。未迁移、清空或覆盖历史会话、上传、图表、分析结果，未修改 AP 凭据、本体或数据库配置。
- `8876` 保持既有反向代理到 `8765`，本轮不构建或覆盖静态站、不重启 nginx；根地址、三个 Cockpit 路由和 API 代理均返回 200。
- 验证：`/healthz`、三页入口、`data/config`、`engines`、`metadata` 和新版 `pro-bi-ui.min.js` 均返回 200，静态包 SHA256 为 `68f6bb8f...`；运行包 `source.commit=cdaa3b6`，不含 `172.16.5.230`，两个头盔组件的 `helmetViewUrl` 均为受控网关路径。两个角色 `id=1|2` 的 `/api/cockpit/ai-publications` 均为 `readyCount=15`、`missingCount=0`、`renderableCount=15`。
- 风险计数实测：`id=1` 的销售额为 `1` 条、出货量为 `2` 条；`id=2` 的销售额为 `2` 条、出货量为 `0` 条，出货量来源完整且 `known=true`。真实 headless Chrome 验证三页和 Tab 切换无看板配置错误或浏览器异常，`id=1` 顶栏显示 `1条风险/2条风险`，`id=2` 显示 `2条风险/0条风险`，不再出现“风险分析中”。
- 自动化验证：Cockpit 相关 Python 289 项通过，Node 看板测试 84 项通过；`git diff --check` 通过。页面验收产生正常的图表 AP 读取；未手工调用分析接口、未发送任务令。
- 回退：停止 8765 PID `3851649`，在 `process360-cockpit-990c4fa-20261102-094608` 使用 `.venv/bin/python start-main.py` 恢复旧版本；不得删除新 release、历史 release、共享 `dataset`、会话、上传、图表或分析记录。8876 继续代理恢复后的 8765，无需修改 nginx。

### 2026-11-02 · 8876 兼容入口代理到主服务

- 已应用 `deploy/cockpit/nginx-8876.conf`，8876 的三个 `/cockpit/*` 页面、当前静态资源、旧 `/api/cockpit/*` 与主服务前缀 `/api/ontology-agentic-analytics/*` 均反向代理到 `172.16.10.34:8765`，保留 URI 和查询参数；根地址映射经营看板。Fuxi 现有 8876 URL 不需调整，不是跳转到新端口。
- 只为已打开旧页面保留 `/static/cockpit/releases/` 不可变资源兼容；新页面资源由主服务提供。8876 的旧 `release.json` 不再作为正式版本来源。修改只涉及 nginx，不重启主服务、不触发取数或分析。
- nginx 配置 `nginx -t` 通过后平滑 reload；原配置备份为 `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/backups/nginx-before-main-proxy-1793582991.conf`。回退时将备份内容写回 `conf/default.conf` 原 inode，再 `docker exec eimosp-cockpit-8876 nginx -t` 和 `nginx -s reload`；不能用 rename 替换单文件 bind mount。
- 线上复验：两角色三页面共6组 HTML 与8765完全相同，三个JS入口资源均200；旧API与带前缀API均返回15个AI插槽，根地址正常。没有执行真实SQL或任务下发。

### 2026-11-02 · 核查建议策略定向预热

- 新增 `POST /api/cockpit/stages/{opportunity|order|shipment}/preheat`，请求体 `id`、`page`、`uiScope=default`。仅复用同角色、同连接已保存且匹配该环节的AP成功凭据；缺失凭据标为缺失，不重签取数时间、不额外请求AP/PG。共同分析继续使用 `/combined/preheat`。
- 用于规则升级后定向强制分析，即使数据指纹没变也可生成新的分析；正常页面打开不调用该入口。生成成功通过既有发布流程替换缓存，失败保留历史结果。

- 下发期限契约：任务服务 `dueAt` 必须是ISO8601。用户需把“建议期限：N个工作日”改为明确日期（YYYY-MM-DD）并确认；服务端在任何外发前校验所有措施日期，日期按北京时间18:00转UTC。相对期限或非法日期返回422，不返回500、不发请求。不会私自用自然日或忽略节假日的算法替代工作日。前端弹窗同步提示日期格式；旧草稿保留，需编辑日期后再确认。本轮不代用户重发失败任务。

### 2026-11-02 · 核查建议部署与下发日期修复复验

- 正式版本 `9bcd3b802f98e2f821530624eef2ec364843648f`，包含 master `8f673fc` 全部已合并feature和核查建议策略；修复候选尚在 `feature/cockpit-investigation-delivery`，未自动合并master。8765 release `process360-cockpit-9bcd3b8-20261102-policy`，PID `726787`；8876继续代理当前主服务，路由与共享数据保留，未启用实验引擎。
- 两角色商机、订单、发货、共同分析8个目标已定向预热。仅重试失败的分析员共同分析一次，成功ID `19a1473ddfd249f2a459900e207f0f58`；失败记录保留，旧发布在重试成功前继续展示。所有目标均产生核查建议，两个角色15个插槽可读，无建议原因引用断裂。
- 用户点击任务 `POC-24D113CF65` 下发时遇到的500来自本地日期转换：相对期限被直接传入ISO8601字段，未发出到Fuxi。现对所有措施先校验具体日期，返回422格式提示；弹窗增加日期要求，未代用户重发或创建真实待办。
- 验证：88项前端、54条黄金评测、28项定向预热及草稿相关测试通过；另20项日期和下发合约测试（含非法期限零外发）及6项任务令前端测试通过。正式三页与资源均200。
- 按既定“只发沈康”配置修正任务令接收人，运行环境凭据不入库；同版本正常重启后PID为 `754270`，健康检查通过。未试发、未重发失败任务。

### 2026-11-02 · 风险去重与旧口径提示发布（53c4662）

- 部署代码 `53c4662b39a4a1ee99000f3c0349d90d5cf9ba0a`，包含 MR `!36` 的风险事项去重与客户表局部筛选，以及 MR `!37` 的旧口径提示文字化。`8765` release 为
  `/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/process360-cockpit-53c4662-20261102-1823`，PID `1561973`；旧 release
  `process360-cockpit-ce39ab3-20261102-1659`（旧 PID `1203631`）完整保留用于回退。
- 新 release 先在 `127.0.0.1:18765` 预检，预检进程 `1536082` 验证后停止；预检环境关闭后台刷新。正式进程继续使用共享
  `.env`、`.venv` 和 `dataset` 软链，`runtime-env.json` 权限 600，`PYTHONPATH`、`PWD`、`RELEASE_COMMIT` 指向新 release。
  新 release 内的源码数据目录已替换为指向共享 `process360-cockpit-464ae6c-20261029-1807/dataset` 的软链，未迁移、覆盖或删除历史会话、上传、图表和分析结果。
- `8876` 保持既有反向代理到 `8765`，本轮不重建静态站、不重启 nginx。`/healthz`、`data/config` 及 `id=1|2` 的三页在 `8765` 与 `8876` 均返回 200；两个角色的
  `/api/cockpit/ai-publications` 均为 `readyCount=15`、`missingCount=0`、`renderableCount=15`。
- 风险计数实测：`id=1` 销售额 `9` 条、出货量 `3` 条；`id=2` 销售额 `8` 条、出货量 `2` 条，均为 `complete=true`。服务端样式已确认旧口径提示使用
  `--cockpit-text-help`、无警告底色并带 `ⓘ` 前缀。启动日志无 Traceback、CRITICAL 或 ERROR。
- 验证：合并后本地运行前端 Node 92 项、Python 1876 项及 1072 个子测试通过，`git diff --check` 通过。GitLab runner 在本轮分支和既有 `master` 流水线上均因无法访问
  GitLab/pypi 镜像超时失败，失败发生在 `get_sources` 和安装 `setuptools` 阶段，不是测试断言失败；本轮未修改 CI 规避门禁。
- 回退：停止 PID `1561973`，在 `process360-cockpit-ce39ab3-20261102-1659` 执行 `.venv/bin/python start-main.py` 恢复旧版本；不得删除新 release、历史 release、共享 `dataset`、
  会话、上传、图表或分析记录。8876 无需修改 nginx。

### 2026-11-03 Workbench本地Excel + ywln_crm可选源

配置独立的`WORKBENCH_LOCAL_ONTOLOGY_PATH`及`WORKBENCH_PG_HOST/PORT/DATABASE/SCHEMA/USER/PASSWORD`后，Workbench数据源页出现“PostgreSQL · ywln_crm”；此选项自动配对本地Excel，不使用远程本体平台或Doris。也可直接使用`python -m bi_agent.web --db postgres`启动。SQL执行器只读并限制超时／返回行数，不从客户Process360配置继承连接。说明见[本地Excel与PG](docs/specs/workbench-local-excel-pg.md)。本次只准备本地配置、测试、提交，不部署或覆盖客户包。

### 客户镜像固定年度分析（2026-11-06）

- 客户专用入口 `bi_agent.web.customer` 启动时关闭 Cockpit 自动分析调度，首次从镜像内的
  `bi_agent/cockpit/frozen-annual.json` 导入六组年度分析，投影为 15 个 AI 插槽。
  预置数据属于交付产物，不提交 Git；需保留真实来源、观察时间与受限说明。
- 发布结果保存在已有 dataset 挂载中的 `cockpit/frozen-annual.sqlite3`。已有发布版不会被镜像
  内旧种子覆盖；历史分析与会话均保留。打开、切页、筛选及轮询只读取发布版。
- “重新分析”显式发送 `POST /api/cockpit/publications/refresh`、`{"manual":true}`。
  后台仍复用主服务执行链，只有六组分析全部可渲染且年度一致才原子替换；失败保留旧版。
  页面标明固定年度分析独立于图表筛选，后台更新期间不清空卡片。
- 此模式仅用于客户专用入口，公司普通主服务调度保持原行为。图表 AP 实时查询并不被冻结。
- 本次只替换 `images/cockpit-linux-amd64.tar`，镜像名称不变；客户 `.env`、Compose、
  配置挂载与已有运行数据不改。重新 `docker load` 后按原 Compose 服务重建容器即可。

- 2026-11-06 补充：客户页面初始隐藏 AI 插槽，点击“分析”立即显示内置发布结果并后台重算；成功后替换，失败保留。仅替换 tar，外部配置不变。


### 2026-11-06 · 34 点击后显示内置分析预览

- 按当前授权将 `6265ecf` 部署到 34 的 8765，release 为
  `process360-cockpit-6265ecf-20261106-click`，PID `3296804`；8876 保持原反向代理。
- 启动器仅为 Cockpit 添加固定年度发布边界，其他主服务/Workbench 路由保留；启动环境关闭
  自动分析调度，原 `.env` 不改，dataset、依赖环境与配置延续原共享目录。
- 三页初始隐藏 AI 插槽，点击“分析”立即显示预置发布结果并后台重算；只有完整候选通过
  才原子替换。预置保留真实年度证据时间与限制，未伪造客户实时结果。
- 预检 18765 已停止；8765/8876 三路由、两角色 15 插槽和点击显示静态资源检查通过。
  本轮未试发任务、未代用户点击真实重新分析。客户镜像 tar 不受本次服务器切换影响。
- 回退：停止新 PID 后运行旧 release `process360-cockpit-5f2a615-20261106-1505/start-main.py`；
  不删除任何 release、共享 dataset、历史会话或分析记录。

- 2026-11-06 客户 tar 小修：顶部分析工具条使用宿主设计 token（蓝色按钮、中性文字、橙色状态提示），不覆盖看板组件；销售额与出货量各展示最多 3 条重点风险，原分析和完整风险总数保留，不调用模型重算。仅替换 tar，外部配置不变。
