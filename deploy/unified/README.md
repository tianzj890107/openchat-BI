# Analytics 单主服务部署

同一镜像、每环境一个 analytics 服务，容器监听 8080。工作台、Cockpit、基础工具 MCP 和任务 MCP 由同一应用分发，不再部署独立静态 Cockpit。

PDT 与 demo2 分别使用 Compose project `analytics-pdt`、`analytics-demo2`，确保配置、任务数据库和持久卷隔离；34 可作为其中一个实例的宿主或独立验收环境，不能仅因域名不同就假定有三套环境。

## 部署输入

- `ANALYTICS_IMAGE`：精确 commit 对应的不可变 tag 或 digest。
- `ANALYTICS_ENV_FILE`：该环境的运行配置绝对路径，不提交仓库。
- `ANALYTICS_PORT`：宿主机端口，候选验收使用未占用端口，不覆盖旧实例。
- `ANALYTICS_BIND_ADDRESS`：默认 127.0.0.1；网关跨机器访问时按网络拓扑设置。

运行配置需包含模型、本体、Doris、Cockpit AP/PG、Process360 配置及 MCP 鉴权。`MCP_PUBLIC_BASE_URL` 使用外部完整基址，例如 `http://pdt-dev.eimos.com/api/ontology-agentic-analytics`；demo2 对应替换域名。

Compose 文件固定路径前缀，网关只配置一个前缀转发，参见 `gateway-location.conf`。示例中的 upstream 是占位符，必须替换，不能直接应用。

## 路由

- `/workbench`
- `/cockpit/overview`、`/cockpit/operations`、`/cockpit/analysis`
- `/api/mcp/general`、`/api/mcp/process360`、`/api/mcp/tasks`
- `/healthz`

所有地址都可加 `/api/ontology-agentic-analytics` 前缀；一个主服务同时支持直连和网关路径。

## 验收及切换

先执行 `docker compose -p <environment> -f deploy/unified/compose.yaml config --quiet`。
在候选端口启动镜像前，先确认环境配置、数据备份及持久卷；本文件不自动执行部署。
**空卷不能代替原历史数据**。原会话、产物、Cockpit 数据和 Process360 runtime.sqlite3 必须制定并验核迁移方案；Process360 状态挂载独立目录，避免覆盖镜像内的 catalog。

候选实例必须完成真实模型问答、只读取数、会话恢复、Cockpit 卡片、MCP 工具/任务和产物访问验收，再切网关或旧端口。保留旧实例与数据用于回滚，观察后才退役。验收不得发送真实风险/待办或删除历史数据。

任务数据库仅允许单进程所有者，不使用多 uvicorn worker 或多个副本共享任务卷。
