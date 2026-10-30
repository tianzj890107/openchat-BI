# Fuxi 风险待办来源推送接口契约

| | |
|---|---|
| 版本 | v1（2026-10-20） |
| 适用读者 | 外部来源系统（如 360）对接开发人员 |
| 契约权威 | 本文档与 fuxi-control 服务实现一致（模块 `src/modules/risk-todo/`，规格基线 `specs/control-risk-foundation/spec.md`）；后续变更以 fuxi 侧通知为准 |
| 联系方式 | 由 fuxi 侧对接人提供 |

## 1. 概述

来源系统把本系统的风险/待办条目推送到 fuxi 平台，由 fuxi 桌面端展示给企业用户。

架构约定：**来源系统是数据状态的权威**。fuxi 侧是只读镜像，不提供任何修改条目内容的入口；条目的新增、更新、完成、删除均以来源系统的推送为准。fuxi 侧仅按 `sourceUpdatedAt` 判定新旧，防止乱序与重复推送产生回退。

对接需要实现两个接口，均为 HTTP POST + JSON：

| 接口 | 用途 |
|---|---|
| `POST /source/todo-batches` | 批量推送条目（新增 + 更新，同接口承载） |
| `POST /source/todo-status-events` | 状态变更通知（完成 / 归档 / 删除等轻量事件） |

## 2. 接入前提

1. **来源注册**：推送前，来源须在 fuxi 管理台完成注册并获得**来源编码（code）**，且状态为**已启用（ENABLED）**。未注册或未启用的来源推送会被 `403` 拒绝。来源编码由 fuxi 侧管理员配置，请向 fuxi 对接人索取。
2. **服务基址**：fuxi-control 服务地址（内网）由 fuxi 对接人提供，下文以 `http://<control-host>` 表示。
3. **网络**：仅要求来源系统服务端可访问 fuxi-control 的 HTTP 端口；无外网要求。

## 3. 通用约定

### 3.1 认证

当前采用**来源标识头**认证，无签名、无密钥：

```http
x-fuxi-source: <来源编码>
```

- 请求未携带该头或为空白 → `401`。
- 来源编码不存在或来源未启用 → `403`（该请求不会留下任何批次记录）。
- 后续若要求接口签名，fuxi 侧将以兼容方式扩展，另行通知。

### 3.2 请求格式

- `Content-Type: application/json`，字符集 UTF-8。
- 请求体必须是合法 JSON；解析失败按校验失败返回 `422`。

### 3.3 时间格式

所有时间字段（`sourceUpdatedAt`、`dueAt`）为 ISO 8601 字符串，**必须使用 UTC 并以 `Z` 结尾**（不接受 `+08:00` 等偏移写法），合法范围 `2000-01-01T00:00:00Z` ~ `2100-01-01T00:00:00Z`：

```
2026-10-20T08:30:00Z
```

### 3.4 枚举值（精确匹配，大小写敏感）

| 字段 | 取值 | 说明 |
|---|---|---|
| `severity` | `CRITICAL` \| `HIGH` \| `MEDIUM` \| `LOW` | 严重程度四档，直接使用 fuxi 枚举 |
| `sourceStatus` | `OPEN` \| `DONE` \| `ARCHIVED` | 条目三态；批量推送中该值即条目展示态，状态事件中该值为迁移目标 |
| `itemType` | `RISK` \| `TODO` | 条目类型；可缺省，缺省按 `TODO` 落库 |
| `eventType`（仅状态事件） | `STATUS_CHANGED` \| `DELETED` | 见 §5 |

fuxi 侧不做任何字段映射或枚举翻译：**字段名即 fuxi 模型字段名，枚举值须直接使用上表取值**。值域外字符串按结构性校验失败处理（见各接口的拒绝语义）。

### 3.5 幂等与乱序守卫（重要）

- 幂等键 = **来源编码 + `sourceTodoId`**。同一幂等键重复推送安全。
- fuxi 以条目的 **`sourceUpdatedAt` 作为新旧判据**：仅当传入值**严格晚于**已存值时才应用变更；传入值早于或等于已存值（重复投递、乱序迟到）时跳过该条，计入 `skipped`，不产生任何副作用。
- 因此来源系统应保证：同一条目每次内容/状态变化时 `sourceUpdatedAt` 严格递增。

### 3.6 批次大小

单次请求条目/事件数上限 **1000**，超出整批校验失败（`422`）。

### 3.7 错误体形状

传输级/权限级错误使用统一错误体：

```json
{ "error": { "code": "unauthorized" } }
```

数据校验结果使用各接口的 `{ applied, skipped, errors }` 响应体（见 §4、§5）。

## 4. 批量推送接口 `POST /source/todo-batches`

新增与更新同一接口：按幂等键存在与否自动插入或更新。适合首次接入全量推送、增量推送以及任何内容变更后的重新推送。

### 4.1 请求

```json
POST /source/todo-batches
x-fuxi-source: <来源编码>
Content-Type: application/json

{
  "batchRef": "20261020-001",
  "items": [
    {
      "sourceTodoId": "RISK-2026-0001",
      "title": "核心交换机端口异常",
      "severity": "HIGH",
      "itemType": "RISK",
      "category": "网络安全",
      "sourceStatus": "OPEN",
      "sourceUpdatedAt": "2026-10-20T08:30:00Z",
      "recipientsRaw": ["13800000001", "+86 139-0000-0002"],
      "dueAt": "2026-10-27T00:00:00Z",
      "description": "端口协商速率异常下降……",
      "impactText": "影响办公区网络质量",
      "ownerRef": "emp-1024",
      "ownerName": "张三",
      "evidence": [{ "type": "link", "url": "https://example.com/detail/1" }],
      "activity": [{ "at": "2026-10-20T08:31:00Z", "text": "风险创建" }],
      "caliberMeta": { "bizLine": "网络" }
    }
  ]
}
```

### 4.2 字段说明

信封（envelope）：

| 字段 | 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `batchRef` | 批次号 | string | 是 | 非空。来源侧自定，用于对账与日志检索。**以 `full-sync:` 为前缀的批次视为全量重推**，服务端整批事务执行，中途失败整批回滚不留半批；普通批次逐条提交 |
| `items` | 条目数组 | array | 是 | 条目数组，≤ 1000 |

条目字段：

| 字段 | 名称 | 类型 | 必填 | 约束与说明 |
|---|---|---|---|---|
| `sourceTodoId` | 来源条目 ID | string | 是 | 非空。来源系统内稳定唯一 ID，幂等键 |
| `title` | 标题 | string | 是 | 1 ~ 200 字符 |
| `severity` | 严重程度 | string | 是 | 四档枚举，见 §3.4 |
| `itemType` | 条目类型 | string | 否 | `RISK` / `TODO`，缺省 `TODO` |
| `category` | 分类 | string | 是 | 非空。开放枚举，未知分类原样透传展示，不拒绝 |
| `sourceStatus` | 来源状态 | string | 是 | 三态枚举；推送条目时该值即落库展示态 |
| `sourceUpdatedAt` | 来源更新时间 | string | 是 | ISO 8601 UTC（`Z` 结尾），乱序守卫判据，同条目变更时须严格递增 |
| `recipientsRaw` | 接收人手机号 | string[] | 是 | **空数组 = 全员可见（广播）**；非空 = 仅列出的接收人可见。服务端落库前逐元素归一（剥除 `+86` 前缀、空格、横线、括号），归一结果须为 5~20 位数字；归一失败的元素保留原文但不参与可见性匹配（也不拒批）。建议来源侧直接传纯数字手机号 |
| `dueAt` | 办理期限 | string \| null | 否 | 无期限传 `null` 或缺省 |
| `description` | 描述 | string \| null | 否 | 缺省按空串落库 |
| `impactText` | 影响说明 | string \| null | 否 | 缺省按空串落库 |
| `ownerRef` | 责任人账号 | string \| null | 否 | 传值时须非空 |
| `ownerName` | 责任人姓名 | string \| null | 否 | |
| `evidence` | 证据材料 | array \| null | 否 | 任意 JSON 数组，原样存储透传 |
| `activity` | 动态记录 | array \| null | 否 | 任意 JSON 数组，原样存储透传 |
| `caliberMeta` | 扩展元数据 | object \| null | 否 | **来源扩展数据的唯一透传通道**：条目中的未知字段会被忽略，需要随条目带到 fuxi 侧的附加数据请放入此对象 |

### 4.3 响应

**200** —— 全部条目合法并处理完成（部分被乱序守卫跳过也返回 200）：

```json
{ "applied": 1, "skipped": 0, "errors": [] }
```

| 字段 | 名称 | 说明 |
|---|---|---|
| `applied` | 已应用条数 | 新插入或实际更新（`sourceUpdatedAt` 晚于已存值）的条数 |
| `skipped` | 已跳过条数 | 已存在且传入 `sourceUpdatedAt` ≤ 已存值（重复投递 / 乱序迟到）而被跳过的条数 |

**422** —— **整批拒绝**：任一条目或信封校验失败时不产生半批入库，合法条目也不会落库。需修正数据后整批重推：

```json
{
  "applied": 0,
  "skipped": 0,
  "errors": [
    { "sourceTodoId": "RISK-2026-0002", "code": "VALIDATION_FAILED", "message": "severity: Invalid option..." },
    { "sourceTodoId": "", "code": "VALIDATION_FAILED", "message": "items: 数组长度超过上限..." }
  ]
}
```

`errors[]` 元素为 `{ sourceTodoId, code, message }`；信封级错误（如条数超限、缺 `batchRef`）的 `sourceTodoId` 为空串。校验失败条目的 `message` 汇总该条最多 3 个问题的字段路径与原因。

## 5. 状态通知接口 `POST /source/todo-status-events`

条目已在 fuxi 侧存在、来源侧仅发生状态变化时，用轻量事件通知，无需重推整条内容。

### 5.1 请求

```json
POST /source/todo-status-events
x-fuxi-source: <来源编码>
Content-Type: application/json

{
  "events": [
    {
      "sourceTodoId": "RISK-2026-0001",
      "eventType": "STATUS_CHANGED",
      "sourceStatus": "DONE",
      "sourceUpdatedAt": "2026-10-21T10:00:00Z"
    },
    {
      "sourceTodoId": "RISK-2026-0003",
      "eventType": "DELETED",
      "sourceStatus": "ARCHIVED",
      "sourceUpdatedAt": "2026-10-21T10:05:00Z"
    }
  ]
}
```

### 5.2 字段说明

信封：`events` 数组，≤ 1000。

| 字段 | 名称 | 类型 | 必填 | 约束与说明 |
|---|---|---|---|---|
| `sourceTodoId` | 来源条目 ID | string | 是 | 非空。目标条目须已通过批量推送存在，否则该事件报 `TODO_NOT_FOUND`（不创建占位条目） |
| `eventType` | 事件类型 | string | 是 | `STATUS_CHANGED` / `DELETED` |
| `sourceStatus` | 迁移目标状态 | string | 是 | 三态枚举。`STATUS_CHANGED` 时该值即迁移目标；`DELETED` 时展示态固定迁移为 `ARCHIVED`（字段仍必填合法枚举） |
| `sourceUpdatedAt` | 来源更新时间 | string | 是 | ISO 8601 UTC（`Z` 结尾），乱序守卫判据，同条目变更时须严格递增 |

### 5.3 响应

事件**逐条独立处理**（与批量推送的整批拒绝不同）：同批中合法事件照常应用，非法事件仅自身报错。

**200** —— 全部事件合法并处理完成；**422** —— 存在错误事件，同时 `applied`/`skipped` 如实上报同批合法事件的处理结果：

```json
{
  "applied": 1,
  "skipped": 0,
  "errors": [
    { "sourceTodoId": "RISK-2026-0009", "code": "TODO_NOT_FOUND", "message": "条目不存在，事件无法应用" }
  ]
}
```

错误 `code` 取值：

| code | 含义 | 处理建议 |
|---|---|---|
| `VALIDATION_FAILED` | 事件结构/枚举/时间不合法 | 修正后重推该事件 |
| `TODO_NOT_FOUND` | 目标条目在 fuxi 侧不存在（事件先于首次推送到达等） | 确认条目已推送；若为时序问题稍后重试本事件即可（幂等） |

## 6. 错误码汇总与重试建议

| HTTP | 错误体/位置 | 含义 | 重试建议 |
|---|---|---|---|
| `200` | `{ applied, skipped, errors: [] }` | 成功（可含乱序跳过） | 无需处理；`skipped` 偏大时检查是否重复/乱序推送 |
| `401` | `{ error: { code: "unauthorized" } }` | 缺少 `x-fuxi-source` 头 | 修正请求头后重试 |
| `403` | `{ error: { code: "forbidden" } }` | 来源编码不存在或未启用 | 联系 fuxi 对接人确认来源注册与启用状态 |
| `422` | `{ applied, skipped, errors[] }` | 数据校验失败（两接口语义见 §4.3 / §5.3） | 按 `errors[]` 修正数据后重推 |
| `503` | `{ error: { code: "unavailable" } }` | 服务暂不可用 | 可重试；建议指数退避 |

推送失败与重复推送均安全：因幂等守卫存在，任何成功后的重推只会计入 `skipped`，不会产生重复条目或状态回退。

## 7. 常见问题

**Q：重复推送同一条目会怎样？**
安全。`sourceUpdatedAt` 相同的重复推送按 `skipped` 跳过，不修改任何数据。

**Q：批量推送与状态事件乱序到达会怎样？**
以 `sourceUpdatedAt` 判新旧：较旧的迟到数据被跳过，fuxi 侧始终收敛到最新状态，不产生回退。

**Q：条目内容更新应该用哪个接口？**
内容（标题、描述、接收人等）变化用批量推送重推整条；仅状态变化时可用更轻量的状态事件接口。两接口可混用，守卫语义一致。

**Q：全量重推怎么做？**
`batchRef` 加 `full-sync:` 前缀（如 `full-sync:20261020`），服务端整批事务执行；配合 `sourceUpdatedAt` 守卫，已是最新的条目自动 `skipped`。

**Q：`category` 有白名单吗？**
没有。开放枚举，原样透传展示；新增分类无需通知 fuxi 侧。

**Q：条目里的扩展字段怎么带？**
条目中的未知字段会被忽略。扩展数据放入 `caliberMeta` 对象随条目透传；数组类材料用 `evidence` / `activity`。

**Q：接收人如何决定谁能看到条目？**
`recipientsRaw` 为空数组时全员可见；非空时仅手机号命中的用户可见。匹配在归一后精确进行，建议直接传 11 位手机号（如 `13800000001`）。

**Q：fuxi 侧会修改或删除我推送的条目吗？**
不会。fuxi 是只读镜像；条目状态只由来源推送/事件驱动（以及来源在 fuxi 管理台注销时的全量归档）。
