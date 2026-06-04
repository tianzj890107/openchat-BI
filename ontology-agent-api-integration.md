

## 3. Doris 只读查询

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

