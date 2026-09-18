# 智能分析 Agent 前端 API 接口文档

> 适用项目：`eimosp-ontology-agentic-analytics`
>
> 契约来源：`bi_agent/web/app.py`、`bi_agent/web/session.py` 及结构化渲染工具
>
> 核对日期：2026-09-14
>
> 文档性质：当前实现契约，不是未来设计稿

## 1. 交付结论

如果新前端与 Agent 通过同一域名、同一网关部署，并且目标是等价替换当前内置工作台，后端业务代码不需要修改，按本文档对接即可。

以下场景不能只靠文档，需补后端或网关能力：

- 前端与 Agent 跨域部署：当前应用未配置 CORS，应由网关同域转发，或在后端增加严格的 CORS 白名单。
- 面向不受信任用户开放：应用自身没有登录认证、用户身份和租户鉴权，当前只用客户端传入的 `session_id` 隔离会话；应由网关完成认证、鉴权和用户级隔离。
- 前端需要“显式取消”和“从 checkpoint 重试”：当前公开 API 没有独立的 cancel/retry 路由。中止 `fetch` 可以取消当前 SSE 连接；`session/reset` 会取消并重建整个会话，但不是无损取消。
- 需要依据 OpenAPI 自动生成强类型 SDK：FastAPI 能生成基础 OpenAPI，但多数响应使用动态 `JSONResponse`，没有完整 response model、operationId 和 security scheme。本文档比当前自动 OpenAPI 更完整；若要稳定生成 SDK，仍需补代码契约。

本文档不要求修改业务代码，只新增接口交付文档。

## 2. 基础约定

### 2.1 服务地址

前端只维护一个环境变量 `BASE_URL`，不要分别硬编码 `/workbench`、`/static` 和 `/api`。

| 环境 | `BASE_URL` 示例 |
|---|---|
| PDT 开发环境 | `http://pdt-dev.eimos.com/api/ontology-agentic-analytics` |
| demo2 环境 | `http://demo2.eimos.com/api/ontology-agentic-analytics` |
| 本地默认环境 | `http://127.0.0.1:8080` |

请求示例：

```text
${BASE_URL}/healthz
${BASE_URL}/api/meta?session_id=<session-id>
${BASE_URL}/api/chat
${BASE_URL}/static/...
${BASE_URL}/charts/<filename>
```

`APP_ROOT_PATH` 是服务端部署配置。前端不得自行把同一个前缀重复拼接为：

```text
/api/ontology-agentic-analytics/api/ontology-agentic-analytics/api/chat
```

### 2.2 数据格式

- 普通接口使用 JSON，请求头为 `Content-Type: application/json`。
- 上传接口使用 `multipart/form-data`，字段名固定为 `file`。
- 对话接口使用 HTTP POST + SSE，响应类型为 `text/event-stream`。
- 字符编码统一为 UTF-8。
- 时间字段由服务端返回，当前通常是 ISO 8601 字符串；前端应按字符串接收并自行格式化。
- 未特别说明时，布尔字段不得用字符串 `"true"`/`"false"` 代替。

### 2.3 会话标识 `session_id`

`session_id` 是前端生成并持久化的会话隔离键，建议使用 UUID：

```text
7e76d94e-6cc1-4d3b-a344-4528508ac60b
```

约束和语义：

- 最大按 128 个字符处理。
- 数据分析模式和报表模式内部按 `data:<session_id>`、`report:<session_id>` 分开。
- 同一模式、同一 `session_id` 同时只能运行一个生成任务。
- `session_id` 不是凭据，也不是可靠的用户身份。不能用它替代登录、JWT 或租户鉴权。
- 新前端必须在同一个逻辑会话的所有请求中持续传递相同的 `session_id`，包括数据源、角色、聊天、选择、报表和历史恢复接口。

### 2.4 通用错误

FastAPI 校验错误通常为：

```json
{
  "detail": "错误说明"
}
```

或字段校验数组：

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "message"],
      "msg": "Field required",
      "input": null
    }
  ]
}
```

聊天并发和排队错误使用稳定结构：

```json
{
  "error": {
    "code": "SESSION_BUSY",
    "message": "当前会话仍在生成，请等待完成或取消"
  },
  "code": "SESSION_BUSY",
  "message": "当前会话仍在生成，请等待完成或取消",
  "session_id": "7e76d94e-6cc1-4d3b-a344-4528508ac60b",
  "retryable": true
}
```

| HTTP 状态 | 稳定错误码 | 含义 |
|---:|---|---|
| 409 | `SESSION_BUSY` | 同一会话已有任务正在生成 |
| 409 | `TURN_SUPERSEDED` | 会话已被重置、恢复、激活或切源，旧请求作废 |
| 429 | `PRINCIPAL_CONCURRENCY_LIMIT` | 当前 `session_id` 达到并发上限 |
| 429 | `GLOBAL_QUEUE_FULL` | 全局等待队列已满 |
| 429 | `ADMISSION_TIMEOUT` | 等待执行名额超时 |
| 429 | `ADMISSION_CANCELLED` | 排队期间请求被取消 |

429 可能携带 `Retry-After` 响应头。前端应优先按该秒数退避，不要立即循环重试。

## 3. 接口暴露分级

应用本身没有实现权限校验。这里的“级别”是交给网关和前端工程的暴露建议，不代表当前后端已经强制执行。

| 级别 | 用途 | 接口 |
|---|---|---|
| 用户前端 | 普通业务用户可用 | 健康检查、元信息、聊天、选择、本体子图、角色、本人会话、报表分析 |
| 管理端 | 仅管理员或可信运维页面 | `/api/config`、`/api/sources`、`/api/graph/build`、`/api/system-prompt` |
| 内部调试 | 不向普通前端开放 | `/api/conversations/{cid}/record`、独立 HTML 原型页 |
| 静态资源 | 由网关透传 | `/static/*`、`/charts/*` |

特别注意：`PUT /api/config` 能修改模型 API key；`PUT /api/sources` 能修改 Doris 密码和连接地址。这两个接口不能直接暴露给匿名用户。

## 4. 接口总览

### 4.1 基础与资源

| 方法 | 路径 | 说明 | 建议级别 |
|---|---|---|---|
| GET | `/` | 直接返回工作台，不重定向 | 用户前端 |
| GET | `/workbench` | 工作台兼容入口，与 `/` 内容一致 | 用户前端 |
| GET | `/healthz` | 健康与就绪检查 | 用户前端 |
| GET | `/health` | `/healthz` 的别名 | 用户前端 |
| GET | `/static/{path}` | 静态文件 | 静态资源 |
| GET | `/charts/{filename}` | Agent 生成的图表文件 | 静态资源 |
| GET | `/dashboard.html` | 角色看板独立页 | 内部调试 |
| GET | `/ceo_dashboard_standalone.html` | CEO 看板独立页 | 内部调试 |
| GET | `/ceo_cockpit.html` | CEO 驾驶舱页 | 内部调试 |
| GET | `/asset_overdue_inventory.html` | 资产逾期示例页 | 内部调试 |
| GET | `/ceo_dashboard.html` | CEO 看板页 | 内部调试 |
| GET | `/new_analysis_nav_chat_board.html` | 工作台原型页 | 内部调试 |

### 4.2 业务 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/meta` | Agent、模型、本体和解析能力元信息 |
| GET | `/api/config` | 读取模型配置与密钥状态 |
| PUT | `/api/config` | 修改模型配置与密钥 |
| GET | `/api/sources` | 读取本体、数据库和检索源 |
| PUT | `/api/sources` | 切换本体、Doris 和检索源 |
| POST | `/api/graph/build` | 从本体表格构建图库 |
| GET | `/api/system-prompt` | 查看完整 system prompt |
| GET | `/api/ontology/seen` | 当前会话已识别本体实体 |
| GET | `/api/ontology/all` | 全量本体实体索引 |
| POST | `/api/ontology/subgraph` | 查询实体上下文图或扩展图 |
| POST | `/api/session/reset` | 重置数据分析会话 |
| GET | `/api/roles` | 读取角色偏好和选项 |
| PUT | `/api/roles` | 更新角色偏好 |
| GET | `/api/conversations` | 最近会话列表 |
| POST | `/api/conversations/save` | 保存或更新会话快照 |
| POST | `/api/conversations/restore` | 兼容式完整恢复 |
| GET | `/api/conversations/{cid}/preview` | 获取轻量预览 |
| GET | `/api/conversations/{cid}/assets` | 获取渲染资产 |
| POST | `/api/conversations/{cid}/activate` | 恢复服务端上下文 |
| GET | `/api/conversations/{cid}/record` | 获取完整原始记录 |
| DELETE | `/api/conversations/{cid}` | 删除会话 |
| POST | `/api/chat` | 数据分析 SSE 对话 |
| POST | `/api/choice` | 继续数据分析中的 AskUser 选择 |
| POST | `/api/task-alert/manual-create` | 将行动建议转为任务令 |
| POST | `/api/report/upload` | 上传 PDF/DOCX |
| GET | `/api/report/list` | 文件列表 |
| DELETE | `/api/report/{rid}` | 删除文件 |
| GET | `/api/report/status` | 当前报表会话状态 |
| POST | `/api/report/activate` | 激活一至五份报表 |
| PUT | `/api/report/config` | 开关报表会话的数据库查询 |
| POST | `/api/report/session/reset` | 重置报表会话 |
| POST | `/api/report/generate` | 创建标准报表生成会话 |
| POST | `/api/report/compose` | 将看板块编排为正式报表结构 |
| POST | `/api/report/chat` | 报表分析 SSE 对话 |
| POST | `/api/report/choice` | 继续报表分析中的 AskUser 选择 |

## 5. 基础与配置接口

### 5.1 健康检查

```http
GET /healthz
GET /health
```

成功就绪返回 200，未就绪返回 503；检查不会调用大模型。

```json
{
  "ok": true,
  "status": "ok",
  "app": "eimosp-ontology-agentic-analytics",
  "name": "智能分析 Agent",
  "version": "0.1.9",
  "host": "pod-hostname",
  "port": 8080,
  "uptime_seconds": 120,
  "configured": true,
  "llm_call": false,
  "dependencies": {
    "agent": true,
    "ontology": true,
    "conversation_store": true
  },
  "coordination": {
    "status": "local",
    "effective_mode": "local"
  }
}
```

版本示例仅用于表示字段类型，前端不得据此写死版本号。

### 5.2 元信息

```http
GET /api/meta?session_id=<session-id>
```

```json
{
  "agent": {
    "name": "bi-analyst",
    "description": "...",
    "model": "...",
    "tools": ["Ontology-FactQuery", "ChartGenerate"],
    "welcome_message": "..."
  },
  "report_agent": {
    "name": "report-analyst",
    "description": "...",
    "model": "...",
    "welcome_message": "..."
  },
  "report_parser": {
    "pdf": true,
    "docx": true
  },
  "ontology_stats": {
    "Term": 10,
    "BusinessObject": 20
  },
  "db_path": "",
  "cwd": "/app",
  "ontology_backend": "production",
  "ontology_service": {
    "configured": true,
    "base_url": "http://demo2.eimos.com/api/gateway2/ontology",
    "repository_id": "3"
  },
  "llm": {
    "models": [],
    "current": {},
    "api_keys": {}
  }
}
```

`report_agent` 可能为 `null`。`ontology_stats` 的键取决于本体后端，前端应按 `Record<string, number>` 接收。

### 5.3 模型配置

```http
GET /api/config
PUT /api/config
```

PUT 请求体所有字段均可省略；省略表示不改，密钥字段传空字符串表示清空：

```json
{
  "model_key": "team-direct-deepseek-v4-flash",
  "max_tokens": 12000,
  "temperature": 0.3,
  "thinking": true,
  "anthropic_api_key": null,
  "qwen_api_key": null,
  "deepseek_api_key": null,
  "team_api_key": null
}
```

约束：

- `max_tokens`：256–200000。
- `temperature`：0–2。
- 密钥原文永远不在响应中返回。

GET 和 PUT 返回同一结构：

```json
{
  "models": [
    {
      "key": "team-direct-deepseek-v4-flash",
      "label": "团队 API · direct-deepseek-v4-flash",
      "provider": "team",
      "default_max_tokens": 8192,
      "default_temperature": 0.7,
      "max_output_tokens": 16384,
      "supports_thinking": true
    }
  ],
  "current": {
    "model_key": "team-direct-deepseek-v4-flash",
    "max_tokens": 12000,
    "temperature": 0.3,
    "thinking": true
  },
  "api_keys": {
    "team": {
      "present": true,
      "masked": "sk-***",
      "source": "env",
      "env_var": "TEAM_API_KEY"
    }
  }
}
```

此接口应归入管理端，不应由普通业务前端调用。

## 6. 数据源与本体接口

### 6.1 获取数据源

```http
GET /api/sources?session_id=<session-id>
```

```json
{
  "atomic_source": {
    "repository_id": "3",
    "namespace": "Ecore",
    "doris_database": "ontology_demo"
  },
  "ontology": {
    "options": [],
    "active": "__metaerp_repository__:3",
    "production": {
      "value": "__metaerp_ontology__",
      "label": "MetaERP",
      "active": true,
      "base_url": "http://demo2.eimos.com/api/gateway2/ontology",
      "repository_id": "3"
    },
    "remote_repositories": [
      {
        "id": "3",
        "name": "Ecore",
        "description": "",
        "dorisDatabase": "ontology_demo",
        "namespace": "Ecore",
        "value": "__metaerp_repository__:3",
        "databaseValue": "__doris_repository__:3"
      }
    ],
    "remote_status": {
      "available": true,
      "message": ""
    }
  },
  "database": {
    "options": [],
    "active": "__doris_repository__:3",
    "remote_databases": []
  },
  "retrieval": {
    "mode": "semantic",
    "graph": {
      "options": [],
      "active": ""
    }
  },
  "doris": {
    "value": "__doris_api__",
    "active": true,
    "api_url": "http://demo2.eimos.com/api/gateway2/ontology/agent/doris/query",
    "jdbc_url": "",
    "driver": "",
    "username": "",
    "password": "",
    "database": "ontology_demo"
  }
}
```

`doris.password` 始终为空，不能用于判断服务端是否已配置密码。

### 6.2 更新数据源

```http
PUT /api/sources
Content-Type: application/json
```

```json
{
  "session_id": "<session-id>",
  "ontology": "__metaerp_repository__:3",
  "database": "__doris_repository__:3",
  "retrieval_mode": "semantic",
  "doris_api_url": "http://demo2.eimos.com/api/gateway2/ontology/agent/doris/query",
  "doris_database": "ontology_demo"
}
```

可选字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ontology` | string | 本地 xlsx 相对路径、`__metaerp_ontology__` 或 `__metaerp_repository__:<id>` |
| `database` | string | 本地 db 相对路径、`__doris_api__` 或 `__doris_repository__:<id>` |
| `doris_jdbc_url` | string | Doris JDBC/MySQL 协议地址 |
| `doris_api_url` | string | Doris HTTP 查询接口地址 |
| `doris_driver` | string | 驱动标识 |
| `doris_username` | string | 用户名 |
| `doris_password` | string | 密码，只写不回显 |
| `doris_database` | string | 数据库名 |
| `retrieval_mode` | `semantic` 或 `graph` | 本体检索模式 |
| `graph` | string | 本地图文件相对路径；远程图模式不使用 |
| `session_id` | string | 会话隔离键 |

远程 repository 与 Doris 是原子绑定。若 `ontology` 和 `database` 指向不同 repository，返回 400。切源会让该会话正在运行的旧 turn 失效。

响应：

```json
{
  "changed": ["ontology", "database"],
  "ontology": "__metaerp_repository__:3",
  "database": "__doris_repository__:3",
  "doris_jdbc_url": "",
  "doris_database": "ontology_demo",
  "namespace": "Ecore",
  "retrieval_mode": "semantic",
  "graph": ""
}
```

远程库管理服务失败时可能返回 502。此接口包含连接和凭据变更能力，应由管理端或受信任的会话配置页调用。

### 6.3 构建本地图库

```http
POST /api/graph/build
```

```json
{
  "ontology": "dataset/spreadsheets/ontology.xlsx"
}
```

响应：

```json
{
  "graph": "dataset/graphs/ontology.graphml",
  "stats": {
    "nodes": 100,
    "edges": 200
  }
}
```

输入必须是工作目录内存在的本体 xlsx 文件。该接口会写文件，建议仅管理端使用。

### 6.4 查看 system prompt

```http
GET /api/system-prompt?mode=data&session_id=<session-id>
```

```json
{
  "system_prompt": "..."
}
```

`mode` 可传 `data` 或 `report`，默认 `data`。报表模式尚未激活时返回一段状态说明。此接口会暴露 Agent 指令、本体上下文和运行规则，只应在受信任调试页面开放。

### 6.5 当前会话已识别实体

```http
GET /api/ontology/seen?mode=data&session_id=<session-id>
```

```json
{
  "entities": [
    {
      "code": "M001",
      "kind": "metric",
      "name": "营业收入",
      "display": "...",
      "entity_key": "...",
      "source": "remote",
      "repository_id": "3"
    }
  ]
}
```

`mode` 可传 `data` 或 `report`，默认 `data`。实体对象允许增加扩展字段，前端应保留未知字段。

### 6.6 全量本体索引

```http
GET /api/ontology/all?session_id=<session-id>
```

响应包含以下数组：

```json
{
  "terms": [{"code": "T001", "kind": "term", "name": "采购"}],
  "business_objects": [],
  "logical_entities": [],
  "attributes": [],
  "relations": [],
  "metrics": [],
  "dimensions": [],
  "activities": [],
  "processes": [],
  "rules": [],
  "meta_relations": []
}
```

远程后端不支持的类别返回空数组，不代表请求失败。

### 6.7 本体子图

```http
POST /api/ontology/subgraph
```

请求：

```json
{
  "session_id": "<session-id>",
  "code": "M001",
  "type": "metric",
  "repository_id": "3",
  "strategy": "context"
}
```

约束：

- `code` 必须匹配 `[A-Za-z][A-Za-z0-9_]{0,63}`。
- `strategy` 只有精确传 `expand` 时采用扩展模式，其余值都按 `context`。
- `repository_id` 非空时必须与会话当前本体库一致。

响应：

```json
{
  "strategy": "context",
  "focus": {"type": "Indicator", "code": "M001"},
  "anchor": {"type": "BusinessObject", "code": "BO001", "name": "采购订单"},
  "nodes": [
    {
      "id": "M001",
      "code": "M001",
      "name": "采购金额",
      "type": "Indicator",
      "properties": {},
      "focus": true,
      "anchor": false
    }
  ],
  "links": [
    {
      "id": "r1",
      "source": "BO001",
      "target": "M001",
      "relationType": "HAS_INDICATOR",
      "directed": true,
      "synthetic": false,
      "properties": {}
    }
  ],
  "relations_available": true,
  "relation_error": "",
  "truncated": false,
  "repository_id": "3",
  "source": "remote"
}
```

错误：编码非法 400、repository 不一致 409、实体不存在 404、远程本体失败 502。

## 7. 角色与会话生命周期

### 7.1 获取角色偏好

```http
GET /api/roles?session_id=<session-id>
```

```json
{
  "user_role": "manager",
  "agent_pref": "concise",
  "user_role_options": [
    {"key": "manager", "label": "管理者", "desc": "..."}
  ],
  "agent_pref_options": [
    {"key": "concise", "label": "简洁", "desc": "..."}
  ]
}
```

### 7.2 更新角色偏好

```http
PUT /api/roles
```

```json
{
  "session_id": "<session-id>",
  "user_role": "manager",
  "agent_pref": "concise"
}
```

```json
{
  "ok": true,
  "user_role": "manager",
  "agent_pref": "concise"
}
```

非法 key 会被清空而不是返回校验错误。会话忙时返回 `SESSION_BUSY`。

### 7.3 重置数据分析会话

```http
POST /api/session/reset?session_id=<session-id>
```

```json
{
  "ok": true
}
```

该操作会取消当前数据分析 turn、清空上下文并建立新会话。它不是普通的“停止生成”按钮。

## 8. 数据分析对话

### 8.1 发起对话

```http
POST /api/chat
Content-Type: application/json
Accept: text/event-stream
```

```json
{
  "message": "查询今年各事业部采购金额并生成图表",
  "visible_user_text": "查询今年各事业部采购金额并生成图表",
  "session_id": "<session-id>"
}
```

字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `message` | 是 | 真正发给 Agent 的完整文本，不可为空 |
| `visible_user_text` | 否 | UI 展示和会话标题使用的稳定文本；未传则使用 `message` |
| `session_id` | 否但强烈建议 | 会话隔离键 |

响应是 SSE，详见第 10 节。

### 8.2 提交 AskUser 选择

```http
POST /api/choice
Content-Type: application/json
Accept: text/event-stream
```

推荐多选格式，单选也使用长度为 1 的数组：

```json
{
  "choice_ids": ["monthly"],
  "choice_labels": ["按月"],
  "session_id": "<session-id>"
}
```

兼容旧格式：

```json
{
  "choice_id": "monthly",
  "choice_label": "按月",
  "session_id": "<session-id>"
}
```

ID 和 label 必须非空、数量相同。没有待处理选择时返回 400。响应继续使用 SSE。

前端必须使用服务端 `user_choice_requested.options` 中的原始 ID 和 label，不能自行翻译后回传。

## 9. SSE 协议

### 9.1 传输规则

这不是浏览器原生 `EventSource` 场景，因为端点使用 POST。前端应使用 `fetch()` 读取 `ReadableStream`。

每个事件帧格式固定为：

```text
data: {"type":"text_delta","text":"正在分析","turn_id":"t000001-ab12cd34"}

```

即 `data: ` + 单行 JSON + 两个换行。读取时必须保留半包缓冲，按空行分帧，不能假设一次 `reader.read()` 正好等于一个事件。

服务端响应头包括：

```text
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

### 9.2 生命周期规则

- 每个用户可见事件都带 `turn_id`。
- `done` 额外带 `generation`；只有收到当前 turn 的 `done` 才能把本轮标记为成功并保存快照。
- `awaiting_user_choice` 表示暂停等待用户，不是失败，也不是完成。
- `error` 和 `session_superseded` 是异常终态，不得伪装成成功。
- SSE 网络 EOF 且未收到 `done`、`awaiting_user_choice`、`error` 或 `session_superseded` 时，应显示“生成中断”，不得自动保存为完整回答。
- 客户端中止当前 `fetch` 会断开流并触发服务端协作取消；当前没有独立 cancel API。
- 忽略不认识的事件类型和扩展字段，保持向前兼容。

### 9.3 事件类型

#### `user_message`

```json
{
  "type": "user_message",
  "text": "用户问题",
  "turn_id": "t000001-ab12cd34"
}
```

#### `cognitive_policy`

```json
{
  "type": "cognitive_policy",
  "policy_version": 1,
  "mode": "FACT_QUERY",
  "reason_code": "FACT_REQUEST_RESOLVED",
  "next_step": "QUERY_DORIS",
  "required_tools": ["Ontology-MetricQuery"],
  "evidence_required": true,
  "needs_human": false,
  "input_digest": "sha256:...",
  "turn_id": "t000001-ab12cd34"
}
```

`mode` 当前可能值：`FACT_QUERY`、`DIAGNOSTIC_ANALYSIS`、`ONTOLOGY_LOOKUP`、`CLARIFICATION`、`CAPABILITY_LIMITATION`、`GENERAL_RESPONSE`。此事件用于可观测性，不能被前端当成工具执行白名单。

#### `sop_progress`

```json
{
  "type": "sop_progress",
  "step": 3,
  "detail": "上下文准备",
  "allow_backward": false,
  "turn_id": "t000001-ab12cd34"
}
```

`step` 为 1–6。允许在服务端纠错时回退，前端按 `allow_backward` 更新步骤状态。

#### `recovery_state`

```json
{
  "type": "recovery_state",
  "status": "RUNNING",
  "current_step": "QUERY",
  "attempt": 1,
  "retryable": false,
  "error_code": "",
  "turn_id": "t000001-ab12cd34"
}
```

状态可能为：`PLANNED`、`RUNNING`、`WAITING_USER`、`SUCCEEDED`、`FAILED_RETRYABLE`、`FAILED_FINAL`、`CANCELLED`。

当前后端内部有 checkpoint/retry 状态机，但没有公开 retry API。前端只能展示该状态；不能假定存在 `/api/retry`。

#### `iteration_start`

```json
{
  "type": "iteration_start",
  "iteration": 1,
  "turn_id": "t000001-ab12cd34"
}
```

#### `llm_request`

```json
{
  "type": "llm_request",
  "iteration": 1,
  "model": "direct-deepseek-v4-flash",
  "model_key": "team:direct-deepseek-v4-flash",
  "max_tokens": 12000,
  "temperature": 0.3,
  "message_count": 2,
  "messages_snapshot": [],
  "turn_id": "t000001-ab12cd34"
}
```

`messages_snapshot` 属于调试信息，普通用户界面无需展示。

#### `thinking_delta` 与 `text_delta`

```json
{"type":"thinking_delta","text":"...","turn_id":"t000001-ab12cd34"}
```

```json
{"type":"text_delta","text":"...","turn_id":"t000001-ab12cd34"}
```

文本是增量片段，前端按到达顺序追加，不要覆盖。

#### `tool_start`

```json
{
  "type": "tool_start",
  "id": "toolu_123",
  "name": "Ontology-FactQuery",
  "turn_id": "t000001-ab12cd34"
}
```

#### `tool_input`

```json
{
  "type": "tool_input",
  "id": "toolu_123",
  "name": "Ontology-FactQuery",
  "input": {"sql": "SELECT ..."},
  "turn_id": "t000001-ab12cd34"
}
```

#### `tool_result`

```json
{
  "type": "tool_result",
  "id": "toolu_123",
  "name": "ChartGenerate",
  "input": {},
  "output": "Chart generated ...",
  "duration_ms": 125,
  "ontology_entities": [],
  "chart": null,
  "table": null,
  "multi_chart": null,
  "todos": [],
  "execution_id": "...",
  "execution_status": "SUCCEEDED",
  "attempt": 1,
  "error_code": "",
  "turn_id": "t000001-ab12cd34"
}
```

并非每次都有全部扩展字段；缺省时按空值处理。

`chart` 结构：

```json
{
  "option": {"xAxis": {}, "yAxis": {}, "series": []},
  "title": "采购金额趋势",
  "chart_type": "line",
  "saved_path": "artifacts/charts/chart-1.html"
}
```

`option` 是 ECharts option，前端直接交给 ECharts 渲染，同时应保留未知 option 字段。

`table` 结构：

```json
{
  "title": "事业部采购金额",
  "subtitle": "",
  "columns": [
    {"key": "bu", "label": "事业部", "align": "left", "format": "text"},
    {"key": "amount", "label": "采购金额", "align": "right", "format": "money", "unit": "元"}
  ],
  "rows": [["A事业部", 1000000]],
  "summary": "",
  "footnote": "",
  "source_note": "M001 · 2026",
  "highlight_rows": [0],
  "analysis_scope": {},
  "semantic": {}
}
```

表格最多 30 列、500 行。`rows` 在 SSE 中已规范化为与 `columns` 对齐的二维数组。`format` 可能为 `text`、`number`、`percent`、`money`。

`multi_chart` 是多维图表卡对象，核心字段为：

```json
{
  "title": "采购金额 · 维度洞察",
  "subtitle": "",
  "metric_code": "M001",
  "source_note": "M001 · 2026",
  "default_dim": "by_bu",
  "dimensions": [
    {
      "key": "by_bu",
      "label": "按事业部",
      "chart_type": "bar",
      "summary": "",
      "option": {
        "xAxis": {"data": ["A事业部"]},
        "yAxis": {},
        "series": [{"name": "采购金额", "data": [1000000]}]
      }
    }
  ]
}
```

`dimensions` 为 2–5 项。服务端已把各维度的原始 `x_axis`、`series`、`unit` 和 `y_axis_name` 编译进 `option`；切换维度只需把对应 `option` 交给 ECharts，无需重新请求数据。

#### `llm_response`

```json
{
  "type": "llm_response",
  "iteration": 1,
  "text": "...",
  "tool_uses": [
    {"id": "toolu_123", "name": "Ontology-FactQuery", "input": {}}
  ],
  "stop_reason": "tool_use",
  "usage": {},
  "turn_id": "t000001-ab12cd34"
}
```

#### `user_choice_requested`

```json
{
  "type": "user_choice_requested",
  "tool_use_id": "toolu_choice_1",
  "question": "请选择下钻维度",
  "options": [
    {"id": "monthly", "label": "按月", "description": "查看月度趋势"}
  ],
  "context": {},
  "turn_id": "t000001-ab12cd34"
}
```

随后会出现：

```json
{
  "type": "awaiting_user_choice",
  "turn_id": "t000001-ab12cd34"
}
```

用户提交 `/api/choice` 后，新 SSE 流首先可能返回：

```json
{
  "type": "user_choice_resolved",
  "tool_use_id": "toolu_choice_1",
  "choice_ids": ["monthly"],
  "choice_labels": ["按月"],
  "choice_id": "monthly",
  "choice_label": "按月",
  "turn_id": "t000002-ef56gh78"
}
```

#### 证据与交付门禁事件

```json
{"type":"claim_context","claims":["claim-1"],"turn_id":"..."}
```

```json
{
  "type": "answer_validation",
  "status": "warning",
  "issues": [],
  "adjusted": false,
  "turn_id": "..."
}
```

```json
{
  "type": "answer_blocked",
  "status": "blocked",
  "issues": [],
  "message": "证据不足，已阻止不可靠回答",
  "turn_id": "..."
}
```

```json
{
  "type": "render_enforce",
  "iteration": 2,
  "reasons": [],
  "called_tools": [],
  "message": "...",
  "turn_id": "..."
}
```

```json
{"type":"action_repair","attempt":1,"message":"...","turn_id":"..."}
```

```json
{
  "type": "delivery_incomplete",
  "reason": "action_missing",
  "attempts": 2,
  "message": "...",
  "turn_id": "..."
}
```

```json
{
  "type": "action_recommendations",
  "turn": 1,
  "items": [
    {"title": "...", "content": "...", "evidence": "..."}
  ],
  "turn_id": "..."
}
```

这些事件用于解释可靠性门禁和渲染补救。前端可以展示，但不能把 `answer_blocked` 或 `delivery_incomplete` 标成普通成功答案。

#### `status`

```json
{"type":"status","message":"正在查询数据","turn_id":"..."}
```

#### `error`

```json
{
  "type": "error",
  "message": "错误说明",
  "error_code": "TOOL_TIMEOUT",
  "turn_id": "..."
}
```

`error_code` 可能缺省。

#### `session_superseded`

```json
{"type":"session_superseded","turn_id":"..."}
```

收到后丢弃该 turn 后续 UI 写入，不得让旧回答覆盖新会话。

#### `done`

```json
{
  "type": "done",
  "stop_reason": "end_turn",
  "turn_id": "t000001-ab12cd34",
  "generation": 3
}
```

`stop_reason` 由模型或交付门禁决定，不应写死枚举。前端用 `done + turn_id + generation` 作为本轮可保存的唯一成功戳。

### 9.4 最小 SSE 读取示例

```js
async function streamPost(url, body, onEvent, signal) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw Object.assign(new Error(payload.message || `HTTP ${response.status}`), {
      status: response.status,
      payload,
    });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const {value, done} = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) {
      const line = frame.split("\n").find((item) => item.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)));
    }
    if (done) break;
  }
}
```

生产实现还需校验 EOF 是否具有合法终态，并按 `turn_id` 拒绝旧流写入。

## 10. 会话历史

### 10.1 会话摘要对象

```json
{
  "id": "8d6a7b9c...",
  "mode": "data",
  "title": "查询采购金额",
  "first_user_question": "查询采购金额",
  "updated_at": "2026-09-14T10:00:00+08:00",
  "created_at": "2026-09-14T09:00:00+08:00",
  "turn_count": 2,
  "message_count": 8,
  "schema_version": 1,
  "title_version": 1
}
```

### 10.2 列表

```http
GET /api/conversations?mode=data
```

`mode` 可省略，或传 `data`、`report`。

```json
{
  "conversations": []
}
```

### 10.3 保存或更新快照

```http
POST /api/conversations/save
```

```json
{
  "mode": "data",
  "title": "查询采购金额",
  "chat_html": "<div>...</div>",
  "dashboard_html": "<div>...</div>",
  "ontology_html": "<div>...</div>",
  "tools_html": "<div>...</div>",
  "llm_html": "<div>...</div>",
  "sop_steps": [],
  "source_config": {
    "ontology": "__metaerp_repository__:3",
    "database": "__doris_repository__:3",
    "retrieval_mode": "semantic",
    "doris_api_url": "http://demo2.eimos.com/api/gateway2/ontology/agent/doris/query",
    "doris_database": "ontology_demo"
  },
  "cid": null,
  "first_user_question": "查询采购金额",
  "session_id": "<session-id>",
  "turn_id": "t000001-ab12cd34",
  "generation": 3
}
```

规则：

- `mode` 非 `report` 时按 `data` 保存。
- 首次保存不传 `cid`；更新原记录时传服务端返回的 `id`。
- `turn_id`、`generation` 使用 `done` 事件原值。旧 generation 会返回 `TURN_SUPERSEDED`。
- 前端传入的标题不是最终权威标题，首个真实用户问题用于稳定标题。
- 单个 HTML 字段最多约 4 MiB；SOP 最多 32 条。
- `source_config` 只允许保存非敏感源信息，禁止包含 `doris_password`、token 或 API key。

响应为会话摘要对象。

### 10.4 轻量预览

```http
GET /api/conversations/{cid}/preview
```

```json
{
  "id": "...",
  "title": "查询采购金额",
  "first_user_question": "查询采购金额",
  "mode": "data",
  "preview": [
    {"role": "user", "text": "查询采购金额"}
  ],
  "chat_html_preview": "",
  "turn_count": 1,
  "source_config_needs_restore": true,
  "has_ontology_html": true
}
```

前端最近会话列表应先调 preview，不要为列表逐条读取完整 record。

### 10.5 读取渲染资产

```http
GET /api/conversations/{cid}/assets
```

```json
{
  "id": "...",
  "mode": "data",
  "chat_html": "...",
  "dashboard_html": "...",
  "ontology_html": "...",
  "tools_html": "...",
  "llm_html": "...",
  "sop_steps": []
}
```

这些字段包含服务端持久化的客户端 HTML。渲染前必须经过可信 HTML 策略；不要直接把来自不可信用户的数据无条件写入 `innerHTML`。

### 10.6 激活会话上下文

```http
POST /api/conversations/{cid}/activate?session_id=<session-id>
```

```json
{
  "id": "...",
  "mode": "data",
  "title": "查询采购金额",
  "first_user_question": "查询采购金额",
  "source_config": {},
  "source_restore_error": "",
  "context_restored": true
}
```

推荐恢复顺序：先 `activate` 恢复服务端上下文，再 `assets` 恢复 UI。激活操作会使当前同模式 turn 作废。

### 10.7 兼容式完整恢复

```http
POST /api/conversations/restore
```

```json
{
  "id": "<conversation-id>",
  "session_id": "<session-id>"
}
```

响应是 `activate` 结果加全部 HTML 和 `sop_steps`。新前端优先使用 `activate + assets`，此接口保留给旧客户端。

### 10.8 完整原始记录

```http
GET /api/conversations/{cid}/record
```

```json
{
  "conversation": {}
}
```

会包含原始消息、工具调用和内部恢复状态，只用于可信调试或后端同步，不向普通前端开放。

### 10.9 删除会话

```http
DELETE /api/conversations/{cid}
```

```json
{
  "ok": true
}
```

当前存储接口没有用户所有权参数；必须由外层鉴权保证用户只能删除有权访问的会话。

## 11. 行动转任务令

```http
POST /api/task-alert/manual-create
```

```json
{
  "title": "跟进重点客户回款",
  "content": "根据本轮分析结果，跟进逾期回款。",
  "assignee": "400",
  "level": "WARNING",
  "bpDefinitionId": "2081949636213985282",
  "clientRequestId": "action-8d6a7b9c-1"
}
```

规则：

- `title`、`content` 运行时必填，缺失返回 422。
- `level` 仅允许 `ALERT`、`WARNING`，默认 `WARNING`。
- `assignee` 省略时使用服务端默认值；最终不能为空。
- `bpDefinitionId` 必须是数字字符串；可省略，由服务端根据关键词匹配默认流程。
- `clientRequestId` 建议每个行动卡唯一；服务进程内会做成功缓存和提交中防重。

成功：

```json
{
  "ok": true,
  "taskId": "123456789",
  "clientRequestId": "action-8d6a7b9c-1"
}
```

错误：功能关闭 403、字段非法 422、同一请求处理中 409、服务地址缺失 500、上游失败 502、上游超时 504。

## 12. 报表分析

### 12.1 报表对象

完整上传记录：

```json
{
  "id": "rpt_...",
  "filename": "经营分析.pdf",
  "ext": ".pdf",
  "size_bytes": 102400,
  "uploaded_at": "2026-09-14T10:00:00+08:00",
  "page_count": 12,
  "text_length": 30000,
  "tables_count": 6,
  "preview": "文档预览文本...",
  "warnings": []
}
```

状态接口里的摘要会省略 `size_bytes` 和 `warnings`。

### 12.2 上传报表

```http
POST /api/report/upload
Content-Type: multipart/form-data
```

表单字段固定为 `file`。只支持 `.pdf` 和 `.docx`，单文件最大 50 MiB。响应为完整报表对象。

### 12.3 报表列表

```http
GET /api/report/list
```

```json
{
  "items": []
}
```

### 12.4 删除报表

```http
DELETE /api/report/{rid}
```

```json
{
  "ok": true
}
```

删除后，服务端会从所有内存报表会话中移除此文件；若某会话已无激活报表，则该报表会话被清空。上传存储当前是共享的，必须由外层鉴权限制删除权限。

### 12.5 激活报表

```http
POST /api/report/activate
```

```json
{
  "report_ids": ["rpt_a", "rpt_b"],
  "with_db": true,
  "session_id": "<session-id>"
}
```

兼容旧字段 `report_id`；如果同时传，`report_ids` 优先。去重后最多激活 5 份报表。

响应：

```json
{
  "ok": true,
  "active_reports": [],
  "active_report": null,
  "with_db": true
}
```

`active_report` 是第一份报表的旧客户端兼容字段，新前端使用 `active_reports`。

### 12.6 报表状态

```http
GET /api/report/status?session_id=<session-id>
```

```json
{
  "active_reports": [],
  "active_report": null,
  "with_db": true,
  "has_session": false
}
```

### 12.7 修改数据库查询开关

```http
PUT /api/report/config
```

```json
{
  "with_db": false,
  "session_id": "<session-id>"
}
```

```json
{
  "ok": true,
  "with_db": false
}
```

只调整当前报表会话工具能力，不丢弃聊天历史。没有激活报表会话时返回 400；会话忙时返回 409。

### 12.8 重置报表会话

```http
POST /api/report/session/reset?session_id=<session-id>&clear_reports=false
```

`clear_reports=false`：清空聊天并基于当前激活报表重建会话。

```json
{"ok": true}
```

`clear_reports=true`：同时解除所有激活报表。

```json
{"ok": true, "active_reports": []}
```

### 12.9 创建标准报表生成会话

```http
POST /api/report/generate?session_id=<session-id>
```

```json
{"ok": true}
```

该接口只创建 `report-generator` 会话，不直接生成正文。创建成功后，把报表向导组装的自然语言任务发送到 `/api/report/chat`。

### 12.10 报表对话与选择

```http
POST /api/report/chat
POST /api/report/choice
```

请求模型、SSE 协议分别与 `/api/chat`、`/api/choice` 相同，但必须先激活报表或调用 `/api/report/generate` 创建报表会话。

### 12.11 正式报表编排

```http
POST /api/report/compose
```

请求：

```json
{
  "blocks": [
    {
      "idx": 0,
      "kind": "text",
      "title": "核心结论",
      "content": "本期采购金额同比下降。"
    },
    {
      "idx": 1,
      "kind": "chart",
      "title": "采购金额趋势",
      "content": "按月趋势图"
    }
  ]
}
```

`kind` 约定为 `text`、`table`、`chart`。空 blocks 返回 400。服务端会调用一次 LLM，每个 block 内容最多取前 600 个字符进入编排提示。

成功：

```json
{
  "title": "采购经营分析报告",
  "summary": "...",
  "sections": [
    {
      "heading": "一、经营概览",
      "intro": "...",
      "blocks": [0, 1]
    }
  ]
}
```

LLM 调用或 JSON 解析失败返回 502。服务端当前只验证 `sections` 是数组；前端仍应验证 block 索引存在、无重复、标题和正文类型正确，并在失败时回退为原始顺序导出。

## 13. 推荐前端调用流程

### 13.1 数据分析

```text
创建并持久化 session_id
  → GET /healthz
  → GET /api/meta?session_id=...
  → GET /api/sources?session_id=...
  → POST /api/chat（读取 SSE）
      → 若 awaiting_user_choice：POST /api/choice（读取新 SSE）
      → 若 done：用 turn_id + generation 保存快照
  → POST /api/conversations/save
```

### 13.2 恢复历史会话

```text
GET /api/conversations?mode=data
  → GET /api/conversations/{cid}/preview
  → 用户点击会话
  → POST /api/conversations/{cid}/activate?session_id=...
  → GET /api/conversations/{cid}/assets
  → 恢复页面
```

### 13.3 上传报表分析

```text
POST /api/report/upload
  → POST /api/report/activate
  → POST /api/report/chat（读取 SSE）
      → 必要时 POST /api/report/choice
  → POST /api/conversations/save（mode=report）
```

### 13.4 标准报表生成

```text
POST /api/report/generate?session_id=...
  → POST /api/report/chat（message=向导生成的完整任务）
  → 收集 text/table/chart/multi_chart
  → POST /api/report/compose
  → 前端导出 HTML/Word/PDF
```

## 14. 前端必须实现的状态规则

1. 每个浏览器逻辑会话生成唯一 `session_id`，不能全站共用常量。
2. 同一 `session_id` 在一个模式里只允许一个在途生成请求。
3. 使用 `AbortController` 支持用户断开 SSE；断开不等于服务端 `done`。
4. 只接受当前 `turn_id` 的增量事件，旧 turn 事件必须丢弃。
5. 只有 `done` 才标记成功；EOF 不能代替 `done`。
6. `awaiting_user_choice` 要保留当前消息和选择上下文，不能结束整轮。
7. 收到 `SESSION_BUSY`/`TURN_SUPERSEDED`/429 时展示可恢复状态，不自动重复提交写操作。
8. 图表使用 `tool_result.chart.option`，表格使用 `tool_result.table`，多维图使用 `tool_result.multi_chart`。
9. 保存历史时传递 `done` 中的 `turn_id` 和 `generation`。
10. 对持久化 HTML 做可信来源限制和必要的消毒处理。
11. 管理类 API 不放进普通用户 bundle 可直接访问的设置入口。
12. 未知事件和字段应被安全忽略，不能导致整个流解析失败。

## 15. 当前后端边界与后续改造清单

以下不是本次文档交付的阻塞，但在“彻底前后端分离并对外提供”前应明确负责人。

| 项目 | 当前状态 | 同域可信前端是否阻塞 | 对外生产前端建议 |
|---|---|---:|---|
| 业务 API | 已覆盖现有工作台能力 | 否 | 直接复用 |
| SSE 对话 | 已实现 POST 流式协议 | 否 | 网关关闭缓冲并放宽长连接超时 |
| Base path | 已支持 `APP_ROOT_PATH` | 否 | 前端只配置一个 `BASE_URL` |
| CORS | 应用未配置 | 同域不阻塞 | 网关同域代理或后端严格白名单 |
| 登录认证 | 应用未实现 | 可信网关下不阻塞 | 网关认证并传递可信身份 |
| 用户/租户数据隔离 | 仅客户端 `session_id` | 内部演示不阻塞 | 后端绑定用户、租户和资源所有权 |
| 显式取消 API | 无 | 可用 AbortController | 可增加无损 cancel 路由 |
| 显式 retry API | 内部有状态机，未暴露路由 | 当前 UI 不阻塞 | 需要恢复按钮时新增受控 retry 路由 |
| SDK 级 OpenAPI | 请求模型有，响应模型不完整 | 不阻塞 | 补 response models、operationIds、securitySchemes |
| 管理接口权限 | 后端未强制 | 依赖网关 | 配置、数据源、原始记录必须单独授权 |
| 文件/历史所有权 | 当前存储不是用户级 ACL | 内部演示不阻塞 | 增加 owner/tenant 过滤和审计 |

## 16. 联调验收清单

- `/healthz` 返回 200，且 `configured=true`。
- `GET /api/meta`、`GET /api/sources` 使用同一个 `session_id`。
- 外部 URL 的 base path 只拼接一次，静态资源和 API 均无 404。
- 网关对 SSE 禁止响应缓冲，长回答不会被固定 60 秒超时截断。
- 前端可正确处理 SSE 拆包、粘包和 UTF-8 中文半字符。
- AskUser 单选、多选、继续生成均可用。
- 中止请求后，旧流不会继续写入当前界面。
- 同会话并发返回 409，不会出现旧结果覆盖新结果。
- 429 能读取 `Retry-After` 并友好提示。
- ECharts、表格、多维图均用结构化字段渲染。
- `answer_blocked`、`delivery_incomplete`、无 `done` EOF 不显示为成功。
- 会话保存带 `turn_id`、`generation`；恢复按 `activate + assets` 流程执行。
- PDF、DOCX 上传、最多五份激活、数据库开关、报表对话可用。
- 普通用户无法访问模型密钥修改、数据源密码修改、system prompt 和完整 record。
- 前端日志、埋点、错误提示不得输出 API key、Doris 密码、Token 或完整敏感请求头。

## 17. 契约维护规则

- 新增、删除或修改 `bi_agent/web/app.py` 的路由时，同一个 MR 必须更新本文档。
- 修改 `bi_agent/web/session.py` 的 SSE 事件、终态或字段时，同一个 MR 必须更新第 9 节。
- 修改 ChartGenerate、TableGenerate、ChartGenerateMultiDim 输出时，同一个 MR 必须更新结构化渲染契约。
- 不得只改前端猜测后端字段；以服务端路由和事件生成代码为准。
- 破坏兼容的字段删除、类型变更或终态语义变更应提升版本，并提供迁移说明。
- 文档示例中的域名、repository、database 和版本只是示例，环境真实值由部署配置决定。
