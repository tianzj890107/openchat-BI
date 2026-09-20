

## 3. Doris 只读查询

本仓库的 `DorisHttpConn` 同时支持两种契约，按 `DORIS_API_URL` 的路径自动选择方言，
并在解析时容忍两种响应形态（灰度期同一网关可能返回任一形态）：

| | 旧网关（现状默认） | MAL 新契约 |
| --- | --- | --- |
| 路径 | `POST /agent/doris/query` | `POST /api/v1/analysis/data/query` |
| 请求体 | `{"sql": "..."}` | `{"analysisConfig": {"sql": "..."}, "commonConfig": {}}` |
| 行数据 | `data.rows` | `data.result.rows` |
| 列定义 | `data.columns`（可选） | `data.result.columns[].identifierCode` |

### 3.1 MAL 新契约

**请求方法：** `POST`
**路径：** `/api/v1/analysis/data/query`
**Content-Type：** `application/json`

请求示例：

```json
{
  "analysisConfig": {
    "sql": "SELECT id, name FROM demo LIMIT 10"
  },
  "commonConfig": {}
}
```

返回参数：

| 参数 | 类型 | 含义 |
|------|------|------|
| `data.result.rows` | array | 查询结果行列表，每行是一个键值对对象 |
| `data.result.columns[].identifierCode` | array | 列顺序与列名；缺失时按首行键顺序回退 |

返回示例：

```json
{
  "success": true,
  "code": 200,
  "msg": "success",
  "data": {
    "resultType": "TABLE",
    "result": {
      "columns": [
        {"identifierCode": "id", "label": "id", "type": "PROPERTY"},
        {"identifierCode": "name", "label": "name", "type": "PROPERTY"}
      ],
      "rows": [{"id": 1, "name": "Alice"}]
    }
  }
}
```

上游 `success=false`、`code` 非 200、HTTP 非 2xx 或非 JSON 仍会抛出 `DorisApiError`，
不会被吞掉；空结果集返回 `([], [])`，不算错误。

### 3.2 旧网关契约（仍在兼容）

**请求方法：** `POST`
**路径：** `/agent/doris/query`
**Content-Type：** `application/json`

### 请求参数

| 参数 | 类型 | 必填 | 含义 |
|------|------|------|------|
| `sql` | string | 是 | 待执行的 SQL 语句，仅允许单条 `SELECT` |

SQL 约束：

- 必须以 `SELECT` 开头（不区分大小写）
- 不允许多条语句（不能包含 `;` 分隔的多条 SQL）
- 末尾分号会自动去除

### 请求示例

```json
{
  "sql": "SELECT id, name FROM demo LIMIT 10"
}
```

### 返回参数

| 参数 | 类型 | 含义 |
|------|------|------|
| `rows` | array | 查询结果行列表，每行是一个键值对对象 |
| `rowCount` | int | 返回行数，等于 `rows.length` |

### 返回示例

```json
{
  "rows": [
    {
      "id": 1,
      "name": "Alice"
    }
  ],
  "rowCount": 1
}
```

`rows` 中各字段名与类型由 SQL 查询结果决定，不同查询返回的列名和值类型可能不同。

### 错误码

| HTTP 状态码 | 说明 |
|-------------|------|
| 400 | `sql` 为空；或非 SELECT、多条语句等非法 SQL；响应体为空 |

---

