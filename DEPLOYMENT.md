# OpenChat BI 部署说明

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

# LLM 至少配置当前模型对应的一个 key
LLM_PROVIDER=qwen
DASHSCOPE_API_KEY=<key>
# 或使用 QWEN_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / TEAM_API_KEY

DORIS_API_URL=http://<doris-gateway>/agent/doris/query
DORIS_DATABASE=<database>
```

把配置放在项目根目录的 `.env`（已被忽略）或由 systemd/Docker 注入。不要把真实 key 写进仓库。

远程本体模式下不需要本地 Excel 本体文件；本地开发模式才需要：

```dotenv
ONTOLOGY_BACKEND=local
```

本地 SQLite 模式可显式传入 `--db dataset/databases/HyperFusion.db`；生产默认 `--db doris`，即通过 Doris 查询。

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

### 团队网关 thinking 参数（模型族路由）

团队网关请求中的 DeepSeek 专属 `thinking` 参数按模型族路由，只对 DeepSeek 生效：

```dotenv
TEAM_DEEPSEEK_ENABLE_THINKING=true   # DeepSeek 专属，优先于旧全局变量
TEAM_QWEN_ENABLE_THINKING=           # 显式设为 true 才给 Qwen 发 enable_thinking
```

旧全局 `TEAM_ENABLE_THINKING` 仅作为 DeepSeek 的兼容项；无论其取值如何，都不会再影响
Qwen、GLM、Kimi 等模型。不要使用 `litellm.drop_params=true` 掩盖参数错误。部署时若在
服务器保留旧变量，请确认新代码已生效（只影响 DeepSeek），或直接改用上面的模型族变量。

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
