# OpenChat BI 部署说明

> **仅供人工运维参考**：本文档描述的是人工部署方法，不构成 Agent 自动部署授权。
> Agent 默认交付方式是 commit + push（`origin/20260727` 与 `personal/main`），
> 默认禁止部署、服务器同步、服务重启和服务器配置修改；只有用户在当前任务中明确
> 要求具体部署目标和范围时，才允许按本文档执行部署。

本文档对应当前仓库的 Web 应用入口 `bi-agent-web`。

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

服务器要求 Python 3.10+、Node.js/npm 和 Git：

```bash
git clone <repository-url> openchat-BI
cd openchat-BI

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
bi_agent/web/static/vendor/antd/openchat-bi-workbench.css
```

如果服务器只用于运行已构建版本，通常不需要在服务器安装 Node.js；应在发布机执行构建并把上述构建产物随代码一起发布。

## 3. 生产配置

生产环境推荐使用远程本体服务和 Doris：

```dotenv
ONTOLOGY_BACKEND=remote
ONTOLOGY_BASE_URL=https://<ontology-service>
ONTOLOGY_REPOSITORY_ID=<repository-id>
ONTOLOGY_APP_ID=<app-id>
ONTOLOGY_AUTH_TOKEN=<token>

# LLM 至少配置当前模型对应的一个 key。当前团队网关默认模型为 direct-deepseek-v4-flash。
LLM_PROVIDER=team
TEAM_API_KEY=<key>
TEAM_BASE_URL=http://172.16.10.34:4000/v1
TEAM_MODEL=direct-deepseek-v4-flash
TEAM_MODELS=<comma-separated-verified-model-ids>
# 也可改用 qwen / anthropic / deepseek provider，并配置对应 API key。

DORIS_API_URL=http://<doris-gateway>/agent/doris/query
DORIS_DATABASE=<database>
```

把配置放在项目根目录的 `.env`（已被忽略）或由 systemd/Docker 注入。不要把真实 key 写进仓库。

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
- 客户端断开或 reset 会取消该 turn；被取消 turn 不保存部分回复。
- TTL/LRU 只回收内存 session 与 source context，不删除历史 JSON、上传、图表或日志。

锁顺序（模块文档契约）：registry lock → session slot lock → WebSession 内部状态 →
conversation store lock；严禁持有 registry/store 锁调用网络，严禁持 session 锁等待
全局下游信号量。

## 4. 启动与验证

前台启动（适合首次验证）：

```bash
source .venv/bin/activate
python -m bi_agent.web --host 127.0.0.1 --port 8765 --cwd /path/to/openchat-BI
```

浏览器访问：

```text
http://127.0.0.1:8765/workbench
```

反向代理（Nginx、网关等）只需把外部路径转发到该地址，并保留 `/api/*` 和 `/static/*`；流式对话接口需要关闭代理缓冲并适当延长超时时间。

启动后至少检查：

```bash
curl -fsS http://127.0.0.1:8765/healthz
curl -fsS http://127.0.0.1:8765/workbench >/dev/null
```

然后在页面确认模型、Doris 数据源和本体状态。API key 缺失通常不会阻止服务启动，而会在实际调用对应模型时提示。

## 5. systemd 示例

将以下内容保存为 `/etc/systemd/system/openchat-bi.service`，按服务器实际路径和用户修改：

```ini
[Unit]
Description=OpenChat BI Web
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<deploy-user>
WorkingDirectory=/path/to/openchat-BI
EnvironmentFile=/path/to/openchat-BI/.env
ExecStart=/path/to/openchat-BI/.venv/bin/python -m bi_agent.web --host 127.0.0.1 --port 8765 --cwd /path/to/openchat-BI
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用和查看日志：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openchat-bi
sudo systemctl status openchat-bi
journalctl -u openchat-bi -f
```

## 6. 更新发布

先确认服务器运行数据已备份，再执行：

```bash
cd /path/to/openchat-BI
git fetch origin
git pull --ff-only origin <branch>
source .venv/bin/activate
python -m pip install -e '.[web]'
sudo systemctl restart openchat-bi
curl -fsS http://127.0.0.1:8765/healthz
```

如果前端源码或依赖发生变化，先在构建机运行 `cd frontend && npm ci && npm run build`，然后提交并发布构建产物；不要在生产机直接把 `node_modules/`、缓存或用户上传文件加入 Git。

## 7. 服务器未提交内容怎么判断

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

## 8. 当前服务器发布说明

当前测试服务器通过 SSH 主机别名 `company-server` 发布，运行目录为
`/home/data/zhangzhen_home/zhangzhen/openchat-BI-releases/<release>`，进程使用该目录下的 `.venv`，监听 `8765`。
发布时只同步源码和已构建静态资源，先在 release 目录创建带时间戳的代码备份；不要覆盖 `.env`、`.venv`、会话、上传文件、图表和日志。

本体管理服务的新目录接口可能返回 `currentDatabase`，旧接口返回 `dorisDatabase`；应用兼容读取两个字段，避免目录字段升级导致新 release 无法启动。

本体任务 Agent 的数据库连接凭据使用平台 AES-GCM 加密格式时，运行进程必须加载与加密端一致的 `ontology.crypto.secret`（或对应环境变量）。Agent 已采用 fail-closed 行为：缺少密钥、密钥错误、密文损坏或 Tag 校验失败会在任务上下文刷新阶段返回 `DATABASE_CREDENTIAL_DECRYPTION_FAILED`，不会把密文当作数据库明文密码继续连接，也不会把密钥写入日志。部署后应使用真实部署密钥重启 ontology-agent，并重新创建或刷新受影响任务；密钥文件/环境文件权限应为 `600`，不要提交到仓库。当前服务器已配置后端提供的 32 字节 Base64 secret，并验证任务凭据解密后可连接 PostgreSQL。

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

前端直接复用 ontology-agent 的 Sigma + Graphology + ForceAtlas2 布局实现与交互参数，在
工具调用“命中的本体”和“本体内容”实体卡两个入口打开同一个弹窗。依赖包括 `sigma`、
`graphology` 与 `graphology-layout-forceatlas2`；部署时必须同步 `frontend/package*.json`、
ForceAtlas2 源码适配层和前端构建产物，不得覆盖会话、上传、图表或日志目录。

### 行动 → 转督办（任务令）外部服务代理

“行动 → 转督办”由 ChatBI 后端代理到真实任务令服务，不在浏览器直接跨域调用：

```dotenv
TASK_ALERT_API_ENABLED=true            # 功能开关，默认并保持开启
TASK_ALERT_API_URL=http://pdt-dev.eimos.com/api/x360/v1/task-alert/manual-create
TASK_ALERT_DEFAULT_ASSIGNEE=400        # 前端未传时的默认责任人(当前临时写死 400)
TASK_ALERT_DEFAULT_LEVEL=WARNING       # 只允许 ALERT / WARNING
# bpDefinitionId 临时按行动内容关键词匹配(回款/开票/销售项目/投标/合同/订单/生产/
# 发货/签收/验收/线索/项目/关闭/履约单);留空时未命中关键词则不传
TASK_ALERT_DEFAULT_BP_DEFINITION_ID=
TASK_ALERT_TIMEOUT_SECONDS=10          # 上游超时，0.5–120s
```

- 后端端点：`POST /api/task-alert/manual-create`，校验 `title`/`content` 非空与
  `level` 取值，`clientRequestId` 做进程内幂等（成功缓存、进行中互斥、失败可重试）。
- 即使当前运维网络无法访问上游（连接失败/超时/HTTP 错误），前端也只展示真实失败并可
  重试，不允许关闭开关或显示假成功。
- 上游即使业务失败也返回 HTTP 200（`success:false, code:500`），代理按响应体
  `success`/`code` 判定成功，任务号取 `data`（UUID 字符串）。
- 示例：`curl -sS -X POST http://127.0.0.1:8765/api/task-alert/manual-create
  -H 'Content-Type: application/json' -d '{"title":"t","content":"c"}'`
