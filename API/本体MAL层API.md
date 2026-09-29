# 本体MAL层API



# 访问方式



| 方式 | Base URL 示例 | 鉴权 |

| --- | --- | --- |

| 直连服务 | `http://<host>:<port>` | 无鉴权，需请求头 `X-Ontology-Repository-Id: <本体库 ID>` |

| 统一网关 | `http://pdt-dev.eimos.com/api/gateway2/ontology/xxxx` | 需请求头 `X-App-Id: <应用 ID>;`<br>需请求头`X-Ontology-Repository-Id: <本体库 ID>` |



应用id : ApTH1EHKdRk58WhDQB



直连访问地址：http://172.16.5.181:30834



**本体库 Header：**



| Header | 说明 |

| --- | --- |

| `X-Ontology-Repository-Id` | 本体库 ID（Long），告知服务操作哪个本体库；后端按此隔离分区数据 |



示例：



```http

X-Ontology-Repository-Id: 1

```



# 接口响应通用说明



所有接口响应均使用统一包装体 ：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `success` | boolean | 是否成功；成功为 `true`，失败为 `false` |

| `code` | int | 业务状态码 |

| `msg` | string \| null | 错误描述，成功时为 `null` |

| `data` | object \| null | 业务载荷 |



# 接口列表



## 元数据检索



### 意图确认(旧)



**接口描述**：根据对象元数据英文名在候选本体类型中确认其真实类型，并返回该元数据的全部属性信息。



**请求方法：** `POST`



**请求路径：** `/agent/ontology/ensureOntologyObject`



**Content-Type：** `application/json`



**请求参数**



| 参数 | 类型 | 必填 | 含义 |

| --- | --- | --- | --- |

| `name` | string | 是 | 元数据英文名，如 `prHeader` |

| `candidateTypes` | string\[\] | 是 | 候选本体类型名列表，不能为空数组 |



**请求示例**



```http

POST /agent/ontology/ensureOntologyObject

Content-Type: application/json

{

  "name": "prHeader",

  "candidateTypes": ["BusinessObject", "LogicalEntity", "BusinessAttribute"]

}

```



**返回参数**（`data` 字段）



| 参数 | 类型 | 含义 |

| --- | --- | --- |

| `found` | boolean | 是否在候选类型中命中 |

| `objectInfo` | object | 匹配成功时有值 |



**响应示例**



```http

{

  "code": 200,

  "data": {

    "found": true,

    "objectInfo": {

      "typeName": "LogicalEntity",

      "properties": {

        "code": "LE000001",

        "label": "采购需求头",

        "name": "prHeader"

      }

    }

  }

}

```



### 意图确认(新)



**接口描述**：根据对象元数据英文名在候选本体类型中确认其真实类型，并返回该元数据的全部属性信息；请求收敛为 `QueryRequest`，响应统一为 `QueryResponse(TABLE)`；命中时 `result.rows` 含一行，未命中时 `columns`、`rows` 均为空数组。



**请求方法：** `POST`



**请求路径：** `/api/v1/analysis/context/resolve-ontology-object`



**Content-Type：** `application/json`



**请求参数**



| 参数 | 类型 | 必填 | 含义 |

| --- | --- | --- | --- |

| `analysisConfig.name` | string | 是 | 元数据英文名，如 `prHeader`、`prHeaderId` |

| `analysisConfig.candidateTypes` | string\[\] | 是 | 候选本体类型名列表，按顺序优先匹配，不能为空数组 |

| `commonConfig` | object | 是 | 传 `{}`；不支持 `filters` / `sorts` / `pagination` |



`candidateTypes` 取值为本体对象英文名，例如：`BusinessObject`、`LogicalEntity`、`BusinessAttribute`、`Term`、`Dimension`、`Indicator`



**请求示例**



```http

POST /api/v1/analysis/context/resolve-ontology-object

Content-Type: application/json

{

  "analysisConfig": {

    "name": "prHeader",

    "candidateTypes": ["BusinessObject", "LogicalEntity", "BusinessAttribute"]

  },

  "commonConfig": {}

}



```



**返回参数**（`data` 字段）



| 参数 | 类型 | 含义 |

| --- | --- | --- |

| `resultType` | string | 固定为 `TABLE` |

| `result.columns` | array | 根据实际行字段生成 |

| `result.rows` | array | 命中时为单行；本体对象的 `properties` 字段展开到行根级 |



**响应示例**



命中：



```json

{

  "success": true,

  "code": 200,

  "msg": "success",

  "data": {

    "resultType": "TABLE",

    "result": {

      "columns": [

        { "identifierCode": "typeName", "label": "typeName", "type": "PROPERTY" },

        { "identifierCode": "code", "label": "code", "type": "PROPERTY" },

        { "identifierCode": "label", "label": "label", "type": "PROPERTY" },

        { "identifierCode": "name", "label": "name", "type": "PROPERTY" }

      ],

      "rows": [{

        "typeName": "LogicalEntity",

        "code": "LE000001",

        "label": "采购需求头",

        "name": "prHeader"

      }]

    }

  }

}

```



未命中：



```json

{

  "success": true,

  "code": 200,

  "msg": "success",

  "data": {

    "resultType": "TABLE",

    "result": {

      "columns": [],

      "rows": []

    }

  }

}

```



参数非法（示例）：



```json

{

  "success": false,

  "code": 400,

  "msg": "name 必须为非空字符串"

}

```



### 关联实体查询(旧)



**接口说明**：从指定本体对象出发，按顶点跳数查询关联对象列表。



**请求方法**：GET



**请求路径**：`/agent/ontology/findRelatedObjects`



**请求参数**



| 参数 | 类型 | 必填 | 含义 |

| --- | --- | --- | --- |

| `type` | string | 是 | 起点对象类型，如 `BusinessObject` |

| `code` | string | 是 | 起点对象编码，如 `BO0004` |

| `depth` | int | 是 | 图遍历深度，必须 `>= 1` |



**请求示例**



```plaintext

GET /agent/ontology/findRelatedObjects?type=BusinessObject&code=BO0004&depth=2

```



**返回参数**（`data` 字段）



| 参数 | 类型 | 含义 |

| --- | --- | --- |

| `objects` | array | 关联实体列表（按 `typeName:code` 去重） |



**响应示例**



```plaintext

{

  "code": 200,

  "data": {

    "objects": [

      {

        "typeName": "Term",

        "properties": { "code": "T000006", "label": "采购需求" }

      },

      {

        "typeName": "LogicalEntity",

        "properties": { "code": "LE000001", "label": "采购需求头", "name": "prHeader" }

      }

    ]

  }

}

```



### 关联实体查询(新)



**接口说明：**从指定本体对象出发，按顶点跳数查询关联对象列表；响应统一为 `QueryResponse(TABLE)`，关联对象逐个展开为行



**请求方法：** `GET`



**请求路径：**`/api/v1/analysis/context/expand-ontology-context`



**请求参数**



| 参数 | 类型 | 必填 | 含义 |

| --- | --- | --- | --- |

| `type` | string | 是 | 起点对象类型，如 `BusinessObject` |

| `code` | string | 是 | 起点对象编码，如 `BO0004` |

| `depth` | int | 是 | 图遍历深度，必须 >= 1（表示顶点跳数） |



**请求示例**



```http

GET /api/v1/analysis/context/expand-ontology-context?type=BusinessObject&code=BO0004&depth=2

```



**返回参数**（`data` 字段）



| 参数 | 类型 | 含义 |

| --- | --- | --- |

| `resultType` | string | 固定为 `TABLE` |

| `result.columns` | array | 所有 rows 字段的并集；`typeName` 存在时排在第一列 |

| `result.rows` | array | 关联实体列表； |



**响应示例**



```plaintext

{

  "success": true,

  "code": 200,

  "msg": "success",

  "data": {

    "resultType": "TABLE",

    "result": {

      "columns": [

        { "identifierCode": "typeName", "label": "typeName", "type": "PROPERTY" },

        { "identifierCode": "code", "label": "code", "type": "PROPERTY" },

        { "identifierCode": "label", "label": "label", "type": "PROPERTY" },

        { "identifierCode": "name", "label": "name", "type": "PROPERTY" },

        { "identifierCode": "dataType", "label": "dataType", "type": "PROPERTY" },

        { "identifierCode": "schema", "label": "schema", "type": "PROPERTY" },

        { "identifierCode": "type", "label": "type", "type": "PROPERTY" }

      ],

      "rows": [

        {

          "typeName": "LogicalEntity",

          "code": "LE000001",

          "label": "采购需求头",

          "name": "prHeader"

        },

        {

          "typeName": "BusinessAttribute",

          "code": "AT0000001",

          "label": "采购需求头ID",

          "name": "prHeaderId",

          "dataType": { "typeEnum": "BIGINT" }

        },

        {

          "typeName": "PhysicalTable",

          "code": "po.pr_header_t",

          "label": "pr_header_t",

          "name": "pr_header_t",

          "schema": "po"

        }

      ]

    }

  }

}

```



### 自定义SQL 查询旧



**接口说明**：在 ArcadeDB 本体图谱上执行只读查询脚本，支持 Gremlin / Cypher / SQL



**请求方法**：POST



**请求路径**：`/agent/ontology/scriptQuery`



**请求参数**



| 参数 | 类型 | 必填 | 含义 |

| --- | --- | --- | --- |

| `language` | string | 是 | 查询语言 |

| `script` | string | 是 | 查询脚本 |

| `paramsList` | array | 否 | 参数列表 |



**请求示例**



```plaintext

{

  "language": "sql",

  "script": "SELECT code, name, label FROM BusinessObject LIMIT 5"

}

```



**返回参数**（`data` 字段）



| 字段 | 类型 | 含义 |

| --- | --- | --- |

| `statementCount` | int | 成功执行的语句条数 |

| `results` | array | 每条语句的 `{ rowCount, rows }` |



**响应示例**



```plaintext

{

  "code": 200,

  "data": {

    "statementCount": 1,

    "results": [

      {

        "rowCount": 1,

        "rows": [

          { "code": "BO0004", "name": "PurchaseRequest", "label": "采购需求" }

        ]

      }

    ]

  }

}

```



### 自定义SQL 查询新



**接口说明：**支持**Cypher**/ Gremlin语法直接查询，优先推荐**Cypher**；结果统一为 `TABLE` 响应。



**请求方法：** `POST`



**请求路径：**`/api/v1/analysis/meta/query`



**请求参数**



| 参数 | 类型 | 必填 | 含义 |

| --- | --- | --- | --- |

| `analysisConfig.language` | string | 是 | `sql` / `opencypher` / `cypher` / `gremlin` |

| `analysisConfig.sql` | string | 是 | 单条只读语句；**排序、分页写在 SQL 内** |

| `analysisConfig.paramsList` | array | 否 | 占位符参数 |

| `commonConfig` | object | 是 | 传 `{}`；**不支持** `filters` / `sorts` / `pagination` |



**请求示例**



```http

POST /api/v1/analysis/meta/query

Content-Type: application/json

{

  "analysisConfig": {

    "language": "sql",

    "sql": "SELECT code, name, label FROM BusinessObject ORDER BY code ASC LIMIT 20"

  },

  "commonConfig": {}

}

```

```http

POST /api/v1/analysis/meta/query

Content-Type: application/json

{

  "analysisConfig": {

    "language": "gremlin",

    "sql": "g.V().hasLabel('BusinessObject').has('code', 'BO0004').out().limit(20)"

  },

  "commonConfig": {}

}

```

```http

{

  "analysisConfig": {

    "language": "sql",

    "sql": "SELECT FROM BusinessObject WHERE code = ?",

    "paramsList": ["BO0004"]

  },

  "commonConfig": {}

}

```



**返回参数**（`data` 字段）



| 字段 | 类型 | 含义 |

| --- | --- | --- |

| `resultType` | string | 固定 `TABLE` |

| `result.columns` | array | 动态列定义 |

| `result.rows` | array | 结果行 |



**响应示例**



```json

{

  "success": true,

  "code": 200,

  "msg": "success",

  "data": {

    "resultType": "TABLE",

    "result": {

      "columns": [

        { "identifierCode": "code", "label": "code", "type": "PROPERTY" },

        { "identifierCode": "name", "label": "name", "type": "PROPERTY" },

        { "identifierCode": "label", "label": "label", "type": "PROPERTY" }

      ],

      "rows": [

        { "code": "BO0004", "name": "Purchase Requisition", "label": "采购需求" }

      ]

    }

  }

}

```



### 分页查询本体列表(旧)



#### 基本信息



**接口说明**：分页查询本体库列表



**请求方法**：`GET`



**相对路径**：`/system/manager/ontology-repository`



#### 请求参数



| 参数 | 类型 | 必填 | 默认值 | 说明 |

| --- | --- | --- | --- | --- |

| `page` | int | 否 | 1 | 页码 |

| `size` | int | 否 | 10 | 每页条数 |

| `name` | string | 否 | — | 名称模糊查询 |



**请求示例**



```http

GET /system/manager/ontology-repository?page=1&size=10&name=开发

```



**返回参数**（`data` 字段）



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `id` | long | 本体库 ID |

| `name` | string | 本体库名称 |

| `description` | string | 描述 |

| `namespaceCode` | string | 本体库标识 |

| `cdcTopicPrefix` | string | CDC topic 前缀 |

| `arcadedbMetaDatabase` | string | ArcadeDB 元数据 database 名 |

| `arcadedbKnowledgeDatabase` | string | ArcadeDB 知识汇聚 database 名 |

| `dorisDatabase` | string | Doris 业务库名 |

| `createdAt` | string | 创建时间，格式 `yyyy-MM-dd HH:mm:ss` |

| `updatedAt` | string | 更新时间，格式 `yyyy-MM-dd HH:mm:ss` |

| `createdBy` | string | 创建人 |

| `updatedBy` | string | 更新人 |



**返回示例**



```http

{

  "code": 200,

  "data": {

    "items": [

      {

        "id": 1,

        "name": "开发联调本体库",

        "description": "开发联调使用",

        "namespaceCode": "dev_integration",

        "cdcTopicPrefix": "ontology_dev_integration",

        "arcadedbMetaDatabase": "ontology_dev_integration_all_meta",

        "arcadedbKnowledgeDatabase": "ontology_dev_integration_all_knowledge",

        "dorisDatabase": "ontology_dev_integration",

        "version": 5,

        "createdAt": "2026-07-01 10:00:00",

        "updatedAt": "2026-07-20 10:00:00",

        "createdBy": "admin",

        "updatedBy": "admin"

      }

    ],

    "total": 4,

    "page": 1,

    "size": 10

  }

}

```



### 分页查询本体列表(新)



#### 基本信息



**接口说明**：分页查询本体库列表



**请求方法**：`GET`



**相对路径**：`/api/v1/analysis/context/ontology-repository`



**Content-Type**：`application/json`



#### 请求参数



| 参数 | 类型 | 必填 | 默认值 | 说明 |

| --- | --- | --- | --- | --- |

| `page` | int | 否 | `1` | 页码，从 1 开始 |

| `size` | int | 否 | `10` | 每页条数，最大 100 |

| `name` | string | 否 | 无 | 按本体库名称模糊查询 |



**请求示例**



```http

GET /api/v1/analysis/context/ontology-repository?page=1&size=100&name=开发联调



```



**返回参数**（`data` 字段）



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `resultType` | string | 固定 `TABLE` |

| `result.columns` | array | 根据本页实际 rows 的字段并集生成；本页无数据时为 `[]` |

| `result.rows` | array | 本体库列表；本页无数据时为 `[]` |

| `pagination.pageNum` | int | 当前页（对应旧版 `page`） |

| `pagination.pageSize` | int | 每页条数（对应旧版 `size`） |

| `pagination.total` | long | 总记录数 |



`result.rows[]` 每项字段（有值才输出）：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `id` | long | 本体库 ID |

| `name` | string | 本体库名称 |

| `description` | string | 描述 |

| `namespaceCode` | string | 本体库标识 |

| `cdcTopicPrefix` | string | CDC topic 前缀 |

| `metaDatabase` | string | 元数据 database 名（旧 `arcadedbMetaDatabase`） |

| `knowledgeDatabase` | string | 知识汇聚 database 名（旧 `arcadedbKnowledgeDatabase`） |

| `currentDatabase` | string | 当前分析引擎业务库名（旧 `dorisDatabase`） |



**返回示例**



```json

{

  "success": true,

  "code": 200,

  "msg": "success",

  "data": {

    "resultType": "TABLE",

    "result": {

      "columns": [

        { "identifierCode": "id", "label": "id", "type": "FIELD" },

        { "identifierCode": "name", "label": "name", "type": "FIELD" },

        { "identifierCode": "description", "label": "description", "type": "FIELD" },

        { "identifierCode": "namespaceCode", "label": "namespaceCode", "type": "FIELD" },

        { "identifierCode": "cdcTopicPrefix", "label": "cdcTopicPrefix", "type": "FIELD" },

        { "identifierCode": "metaDatabase", "label": "metaDatabase", "type": "FIELD" },

        { "identifierCode": "knowledgeDatabase", "label": "knowledgeDatabase", "type": "FIELD" },

        { "identifierCode": "currentDatabase", "label": "currentDatabase", "type": "FIELD" }

      ],

      "rows": [

        {

          "id": 1,

          "name": "开发本体库-Doris",

          "description": "本地开发默认库",

          "namespaceCode": "dev",

          "cdcTopicPrefix": "ontology_dev",

          "metaDatabase": "ontology_dev_all_meta",

          "knowledgeDatabase": "ontology_dev_all_knowledge",

          "currentDatabase": "ontology_dev"

        }

      ]

    },

    "pagination": { "pageNum": 1, "pageSize": 10, "total": 4 }

  }

}

```



### 获取本体库信息(旧)



#### 基本信息



**接口说明**：获取指定本体库的全部信息



**请求方法**：`GET`



**相对路径**：`/system/manager/ontology-repository/{repositoryId}`



**请求参数**



| 参数 | 类型 | 必填 | 说明 |

| --- | --- | --- | --- |

| `repositoryId` | long | 是 | 路径参数，本体库 ID |



**请求示例**



```json

GET /system/manager/ontology-repository/1

```



**返回参数**（`data` 字段）



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `id` | long | 本体库 ID |

| `name` | string | 本体库名称 |

| `description` | string | 描述 |

| `namespaceCode` | string | 本体库标识 |

| `cdcTopicPrefix` | string | CDC topic 前缀 |

| `arcadedbMetaDatabase` | string | ArcadeDB 元数据 database 名 |

| `arcadedbKnowledgeDatabase` | string | ArcadeDB 知识汇聚 database 名 |

| `dorisDatabase` | string | Doris 业务库名 |

| `createdAt` | string | 创建时间，格式 `yyyy-MM-dd HH:mm:ss` |

| `updatedAt` | string | 更新时间，格式 `yyyy-MM-dd HH:mm:ss` |

| `createdBy` | string | 创建人 |

| `updatedBy` | string | 更新人 |



**返回示例**



```json

{

  "code": 200,

  "data": {

    "id": 1,

    "name": "采购域本体库",

    "description": "采购领域标准本体",

    "namespaceCode": "purchase",

    "cdcTopicPrefix": "purchase",

    "arcadedbMetaDatabase": "ontology_purchase_meta",

    "arcadedbKnowledgeDatabase": "ontology_purchase_knowledge",

    "dorisDatabase": "ontology_purchase",

    "version": 5,

    "createdAt": "2026-07-01 10:00:00",

    "updatedAt": "2026-07-20 10:00:00",

    "createdBy": "admin",

    "updatedBy": "admin"

  }

}

```



### 获取本体库信息(新)



#### 基本信息



**接口说明**：获取指定本体库的全部信息；响应为 `QueryResponse(TABLE)` 单行；`result.rows[0]` 字段与「分页查询本体列表 (新)」中 `result.rows[]` 相同。



**请求方法**：`GET`



**相对路径**：`/api/v1/analysis/context/ontology-repository/{id}`



**Content-Type**：`application/json`



**请求参数**



| 参数 | 类型 | 必填 | 说明 |

| --- | --- | --- | --- |

| `repositoryId` | long | 是 | 路径参数，本体库 ID |



**请求示例**



```json

GET /api/v1/analysis/context/ontology-repository/1

```



**返回参数**（`data` 字段）



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `resultType` | string | 固定 `TABLE` |

| `result.columns` | array | 列定义；根据 `result.rows[0]` 实际字段生成；不存在时为 `[]` |

| `result.rows` | array | 本体库详情；命中时为 1 行，不存在时为 `[]` |



`result.columns[]` 每项：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `identifierCode` | string | 列标识，与 `rows[0]` 中的字段名一致 |

| `label` | string | 列展示名（当前与 `identifierCode` 相同） |

| `type` | string | 固定 `FIELD` |



`result.rows[0]` 字段（有值才输出；管理字段已裁剪）：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `id` | long | 本体库 ID |

| `name` | string | 本体库名称 |

| `description` | string | 描述 |

| `namespaceCode` | string | 本体库标识 |

| `cdcTopicPrefix` | string | CDC topic 前缀 |

| `metaDatabase` | string | 元数据 database 名 |

| `knowledgeDatabase` | string | 知识汇聚 database 名 |

| `currentDatabase` | string | 当前分析引擎业务库名 |



**返回示例**



```json

{

  "success": true,

  "code": 200,

  "msg": "success",

  "data": {

    "resultType": "TABLE",

    "result": {

      "columns": [

        { "identifierCode": "id", "label": "id", "type": "FIELD" },

        { "identifierCode": "name", "label": "name", "type": "FIELD" },

        { "identifierCode": "description", "label": "description", "type": "FIELD" },

        { "identifierCode": "namespaceCode", "label": "namespaceCode", "type": "FIELD" },

        { "identifierCode": "cdcTopicPrefix", "label": "cdcTopicPrefix", "type": "FIELD" },

        { "identifierCode": "metaDatabase", "label": "metaDatabase", "type": "FIELD" },

        { "identifierCode": "knowledgeDatabase", "label": "knowledgeDatabase", "type": "FIELD" },

        { "identifierCode": "currentDatabase", "label": "currentDatabase", "type": "FIELD" }

      ],

      "rows": [

        {

          "id": 1,

          "name": "开发本体库-Doris",

          "description": "本地开发默认库",

          "namespaceCode": "dev",

          "cdcTopicPrefix": "ontology_dev",

          "metaDatabase": "ontology_dev_all_meta",

          "knowledgeDatabase": "ontology_dev_all_knowledge",

          "currentDatabase": "ontology_dev"

        }

      ]

    }

  }

}

```



### 本体元数据查询



#### 基本信息



**接口说明**：`analysisConfig` 只声明**需要返回**的点类型、边类型及其属性；凡不进入结果、仅用于收窄过滤范围的对象与关联关系，由上游在 `commonConfig.filters` 的 `children` 中显式列举（属性条件与关联边一并列出）。返回结果形态由接口内部实现自动推断。



**请求方法**：`POST`



**相对路径**：`api/v1/analysis/meta/query`



**Content-Type**：`application/json`



#### 请求参数



| 参数层级 | 类型 | 必填 | 含义与说明 |

| --- | --- | --- | --- |

| `analysisConfig` | Object | 是 | 查询配置。定义本次查询涉及的本体类型、关系以及需要返回的点属性和边属性。 |

| `analysisConfig.vertex` | Array | 是 | 本体点声明列表，至少包含一个本体点。 |

| `analysisConfig.vertex[].type` | String | 是 | 本体点类型，如 `Indicator`、`BusinessAttribute`、`LogicalEntity`。 |

| `analysisConfig.vertex[].label` | String | 否 | 本体点的前端展示名称，如“指标”。 |

| `analysisConfig.vertex[].properties` | Array | 否 | 需要返回的点属性列表。未传或为空数组时，返回该点的默认业务属性。 |

| `analysisConfig.vertex[].properties[].name` | String | 是 | ArcadeDB 中真实的点属性名，如 `code`、`name`。 |

| `analysisConfig.vertex[].properties[].label` | String | 否 | 点属性的前端展示名称，如“指标编码”。 |

| `analysisConfig.link` | Array | 否 | 关系声明列表。只查询单个本体点时可以不传。 |

| `analysisConfig.link[].type` | String | 是 | 关系边类型，如 `IndicatorCalculateToIndicator`、`IndicatorIsDrilledByDimension`。 |

| `analysisConfig.link[].label` | String | 否 | 关系边的前端展示名称，如“计算来源”。 |

| `analysisConfig.link[].sourceType` | String | 否 | 起点的 Type。 |

| `analysisConfig.link[].targetType` | String | 否 | 终点的 Type。 |

| `analysisConfig.link[].properties` | Array | 否 | 需要返回的边属性列表。未传或为空数组时，返回该边的默认属性。 |

| `analysisConfig.link[].properties[].name` | String | 是 | ArcadeDB 中真实的边属性名，如 `attrMappings`。 |

| `analysisConfig.link[].properties[].label` | String | 否 | 边属性的前端展示名称，如“计算表达式”。 |

| `commonConfig` | Object | 是 | 通用查询配置。统一定义过滤、排序和分页。 |

| `commonConfig.filters` | Object | 否 | 过滤条件。单条件可直接传条件节点；多条件可传逻辑节点。 |

| `commonConfig.filters.logic` | String | 逻辑节点必填 | 逻辑连接符，可选 `AND`、`OR`。 |

| `commonConfig.filters.children` | Array | 逻辑节点必填 | 子条件列表；每个子节点可以继续是逻辑节点或条件节点。 |

| `commonConfig.filters.type` | String | 条件节点必填 | 查询对象类型。 |

| `commonConfig.filters.property` | String | 条件节点必填 | 被过滤对象上的真实属性名。 |

| `commonConfig.filters.operator` | Object | 条件节点必填 | 比较操作对象，包含 `code` 与 `type`。 |

| `commonConfig.filters.operator.code` | String | 是 | 操作符编码，如 `EQ`、`LIKE`、`IN`、`BETWEEN`。 |

| `commonConfig.filters.operator.type` | String | 是 | 过滤字段值类型，如 `STRING`、`NUMBER`、`DATE`、`BOOLEAN`。 |

| `commonConfig.filters.value` | Any | 视操作符而定 | 过滤值 |

| `commonConfig.sorts` | Array | 否 | 排序规则列表。多个排序项按数组顺序确定优先级。 |

| `commonConfig.sorts[].type` | String | 是 | 排序对象类型。 |

| `commonConfig.sorts[].property` | String | 是 | 排序对象上的真实属性名。 |

| `commonConfig.sorts[].order` | String | 是 | 排序方向，可选 `ASC`、`DESC`。 |

| `commonConfig.pagination` | Object | 是 | 分页配置。 |

| `commonConfig.pagination.pageNum` | Integer | 是 | 当前页码，从 `1` 开始。 |

| `commonConfig.pagination.pageSize` | Integer | 是 | 每页数据条数，必须大于 `0`；最大值由服务端限制。 |



过滤操作符说明：



| operator.code | 支持的 operator.type 枚举值 | value要求 | 说明 |

| --- | --- | --- | --- |

| `EQ` | `STRING`、`NUMBER`、`DATE`、`DATETIME`、`BOOLEAN` | 单值 | 等于 |

| `NE` | `STRING`、`NUMBER`、`DATE`、`DATETIME`、`BOOLEAN` | 单值 | 不等于 |

| `GT` | `NUMBER`、`DATE`、`DATETIME` | 单值 | 大于 |

| `GTE` | `NUMBER`、`DATE`、`DATETIME` | 单值 | 大于等于 |

| `LT` | `NUMBER`、`DATE`、`DATETIME` | 单值 | 小于 |

| `LTE` | `NUMBER`、`DATE`、`DATETIME` | 单值 | 小于等于 |

| `LIKE` | `STRING` | 单值 | 模糊匹配 |

| `IN` | `STRING`、`NUMBER`、`DATE`、`DATETIME`、`BOOLEAN` | 非空数组 | 包含于指定集合 |

| `BETWEEN` | `NUMBER`、`DATE`、`DATETIME` | 长度为 2 的数组 | 闭区间查询 |



按 `operator.type`（字段值类型）反查可用 `operator.code`（便于前端按字段类型渲染操作符下拉）：



| operator.type | 支持的 operator.code | 说明 |

| --- | --- | --- |

| `STRING` | `EQ`、`NE`、`LIKE`、`IN` | 等于 / 不等于 / 包含（模糊） / 属于 |

| `NUMBER` | `EQ`、`NE`、`GT`、`GTE`、`LT`、`LTE`、`IN`、`BETWEEN` | 等于 / 不等于 / 大于 / 大于等于 / 小于 / 小于等于 / 属于 / 范围 |

| `DATE`（不含时分秒） | `EQ`、`NE`、`GT`、`GTE`、`LT`、`LTE`、`IN`、`BETWEEN` | 等于 / 不等于 / 大于 / 大于等于 / 小于 / 小于等于 / 属于 / 范围 |

| `BOOLEAN` | `EQ`、`NE`、`IN` | 等于 / 不等于 / 属于 |



**请求示例**



只查询指标，不查询任何关系边。返回指标的编码、名称和标签，并按照指标编码升序分页查询。



```json

{

  "analysisConfig": {

    "vertex": [

      {

        "type": "Indicator",

        "label": "指标",

        "properties": [

          { "name": "code", "label": "指标编码" },

          { "name": "name", "label": "指标名称" },

          { "name": "label", "label": "指标标签" }

        ]

      }

    ]

  },

  "commonConfig": {

    "filters": {

      "type": "Indicator",

      "property": "status",

      "operator": {

        "code": "EQ",

        "type": "STRING"

      },

      "value": "ACTIVE"

    },

    "sorts": [

      {

        "type": "Indicator",

        "property": "code",

        "order": "ASC"

      }

    ],

    "pagination": {

      "pageNum": 1,

      "pageSize": 10

    }

  }

}

```



查询指标、指标使用的业务属性，同时演示点属性过滤混合嵌套查询



```json

{

  "analysisConfig": {

    "vertex": [

      {

        "type": "Indicator",

        "label": "指标",

        "properties": [

          { "name": "code", "label": "指标编码" },

          { "name": "name", "label": "指标名称" }

        ]

      },

      {

        "type": "BusinessAttribute",

        "label": "业务属性",

        "properties": [

          { "name": "code", "label": "属性编码" },

          { "name": "name", "label": "属性名称" }

        ]

      }

    ],

    "link": [

      {

        "type": "IndicatorIsCalculatedFromATT",

        "label": "由业务属性计算",

        "sourceType": "Indicator",

        "targetType": "BusinessAttribute",

        "properties": []

      }

    ]

  },

  "commonConfig": {

    "filters": {

      "type": "Indicator",

      "property": "code",

      "operator": {

        "code": "EQ",

        "type": "STRING"

      },

      "value": "M0001"

    },

    "pagination": {

      "pageNum": 1,

      "pageSize": 10

    }

  }

}

```



#### 返回参数（`data` 字段）



| 参数层级 | 类型 | 含义与说明 |

| --- | --- | --- |

| `code` | Integer | 业务状态码，成功为 `200` |

| `msg` | String/null | 响应信息，成功时为 `success` |

| `data` | Object/null | 核心业务数据，失败且无结果时可以为 `null` |

| `├─ resultType` | String | 结果类型标识，用于前端判断如何渲染 `result` 中的数据，可选值：`TABLE`、`GRAPH`、`TREE` |

| `├─ result` | Object/Array | 查询结果 |

| `│　├─ 当 resultType = TABLE 时` | Object | 扁平表格结果，包含列定义和数据行 |

| `│　│　├─ columns` | Array | 列定义（表头元数据）描述返回结果中包含哪些点属性和边属性。 |

| `│　│　│　├─ identifierCode` | String | 列唯一标识，对应 `rows` 中的动态 Key，如 `code`、`name`、`label` |

| `│　│　│　├─ label` | String | 字段展示名称 |

| `│　│　│　└─ type` | String | 字段类型 |

| `│　│　└─ rows` | Array | 当前页的数据行列表，每行代表一条完整匹配结果 |

| `│　│　　　├─ [动态Key]` | Any | 具体字段值。Key 必须与 `columns.identifierCode` 一致。 |

| `│　└─ 当 resultType = GRAPH 时` | Object | 图结构结果 |

| `│　　　├─ vertices` | Array | 本体点列表，同一个点在当前结果中只返回一次。 |

| `│　　　│　├─ id` | String | 点唯一标识，使用 ArcadeDB RID，如 `#10:1`。 |

| `│　　　│　├─ type` | String | 本体点类型，对应请求中的 `vertex.type`。 |

| `│　　　│　├─ properties` | Object | 点属性对象，只包含请求中 `vertex.properties` 声明的属性。 |

| `│　　　│　│　└─ [动态属性]` | Any | 点属性。Key 对应 `vertex.properties[].name`。 |

| `│　　　└─ links` | Array | 关系边列表，同一条边在当前结果中只返回一次。 |

| `│　　　　　├─ id` | String | 边唯一标识，使用 ArcadeDB RID，如 `#20:1`。 |

| `│　　　　　├─ relation` | String | 关系边类型，对应请求中的 `link.type`。 |

| `│　　　　　├─ source` | String | 起点 RID，引用 `vertices.id`。 |

| `│　　　　　├─ target` | String | 终点 RID，引用 `vertices.id`。 |

| `│　　　　　└─ properties` | Object | 边属性对象，只包含请求中 `link.properties` 声明的属性。未声明返回字段时返回空对象。 |

| `│　　　　　　　└─ [动态边属性]` | Any | 边属性。Key 对应 `link.properties[].name`。 |

| `└─ pagination` | Object | 分页信息。 |

| `├─ pageNum` | Integer | 当前页码。 |

| `└─ pageSize` | Integer | 每页目标结果数量。 |



**返回示例**



```json

{

  "code": 200,

  "msg": "success",

  "data": {

    "resultType": "TABLE",

    "result": {

      "columns": [

        {

          "identifierCode": "code",

          "label": "指标编码",

          "type": "PROPERTY"

        },

        {

          "identifierCode": "label",

          "label": "指标标签",

          "type": "PROPERTY"

        }

      ],

      "rows": [

        {

          "code": "M0001",

          "label": "采购金额"

        },

        {

          "code": "M00011",

          "label": "到货周期"

        }

      ]

    },

    "pagination": {

      "pageNum": 1,

      "pageSize": 10

    }

  }

}

```

```json

{

  "code": 200,

  "msg": "success",

  "data": {

    "resultType": "GRAPH",

    "result": {

      "vertices": [

        {

          "id": "#10:1",

          "type": "Indicator",

          "properties": {

            "code": "M0001",

            "name": "xxx",

            "label": "销售总金额"

          }

        }

      ],

      "edges": []

    },

    "pagination": {

      "pageNum": 1,

      "pageSize": 10

    }

  }

}

```



#### 更多场景



更多本体元数据分析场景请参阅：[《本体元数据查询API-WIP》](https://alidocs.dingtalk.com/i/nodes/a9E05BDRVQ0jarzPFDyNQ56RW63zgkYA)



### 获取智能建模任务上下文信息(旧)



**接口说明**：按 `taskCode` 获取智能建模执行上下文。



**请求方法**：GET



**相对路径**：`/intelligent/modeling/tasks/{taskCode}/execution-context`



#### 请求参数



| 参数 | 类型 | 必填 | 含义与说明 |

| --- | --- | --- | --- |

| taskCode | String | 是 | 路径参数。智能建模任务编码，如 RM123456789。 |



**请求示例**



```json

GET /intelligent/modeling/tasks/RM123456789/execution-context

```



#### 返回参数（`data` 字段）



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `repositoryId` | long | 本体库 ID |

| `taskCode` | string | 任务编码 |

| `taskName` | string | 任务名称 |

| `modelName` | string | 模型名称 |

| `taskType` | string | 任务类型：`DATA_SOURCE_MODELING`（数据源建模）、`DOCUMENT_MODELING`（文档建模） |

| `prompt` | string | 用户补充提示词 |

| `parseElements` | array | 解析要素列表，如 `business_object`、`logical_entity` |

| `expectedFiles` | array | 期望产出的 CSV 文件名列表；仅包含 `parseElements` 对应文件；成功时还需额外上传 `ok.csv`（固定约定，不在此列表中） |

| `outputPrefix` | string | Agent 输出目录前缀，如 `ontology/1/modeling-tasks/RM123456789/agent-output` |

| `database` | object / null | 数据库建模上下文；`taskType=DOCUMENT_MODELING` 时为 `null` |

| `document` | object / null | 文档建模上下文；`taskType=DATA_SOURCE_MODELING` 时为 `null` |



`database` 对象（数据源建模时有值）：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `databaseSourceId` | long | 数据库来源 ID |

| `dbType` | string | 数据库类型，如 `POSTGRESQL` |

| `host` | string | 主机 |

| `port` | int | 端口 |

| `database` | string | 数据库名 |

| `username` | string | 用户名 |

| `password` | string | 密码（加密，仅 Agent 执行使用） |

| `sourceSchema` | string | 源 Schema |

| `selectedTables` | array | 选中的表名列表 |



`document` 对象（文档建模时有值）：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `fileSourceId` | long | 文件来源 ID |

| `fileType` | string | 文件类型，如 `PDF` |

| `objectKey` | string | 对象存储 objectKey |



**响应示例**



```json

{

  "success": true,

  "code": 200,

  "msg": "success",

  "data": {

    "repositoryId": 1,

    "taskCode": "RM123456789",

    "taskName": "采购库智能建模",

    "modelName": "采购域模型",

    "taskType": "DATA_SOURCE_MODELING",

    "prompt": "优先识别采购订单与供应商",

    "parseElements": [

      "business_object",

      "logical_entity",

      "business_attribute"

    ],

    "expectedFiles": [

      "business_objects.csv",

      "logical_entities.csv",

      "business_attributes.csv"

    ],

    "outputPrefix": "ontology/1/modeling-tasks/RM123456789/agent-output",

    "database": {

      "databaseSourceId": 12,

      "dbType": "POSTGRESQL",

      "host": "127.0.0.1",

      "port": 5432,

      "database": "purchase",

      "username": "ontology_agent",

      "password": "crypted-password",

      "sourceSchema": "public",

      "selectedTables": ["purchase_order", "supplier"]

    },

    "document": null

  }

}

```



### 获取智能建模任务上下文信息(旧)



#### 基本信息



**接口说明**： 按 `taskCode` 获取智能建模任务的执行上下文，包括解析要素、期望输出文件、数据源或文档来源信息。响应统一为 `QueryResponse(TABLE)` 单行



**请求方法**：`GET`



**相对路径**：`/api/v1/analysis/context/modeling/tasks/{taskCode}/execution-context`



#### 请求参数



| 参数 | 类型 | 必填 | 含义与说明 |

| --- | --- | --- | --- |

| taskCode | String | 是 | 路径参数。智能建模任务编码，如 RM123456789。 |



**请求示例**



```json

GET /api/v1/analysis/context/modeling/tasks/RM123456789/execution-context

```



#### 返回参数（`data` 字段）



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `resultType` | string | 固定 `TABLE` |

| `result.columns` | array | 列定义；根据 `result.rows[0]` 实际字段生成 |

| `result.rows` | array | 执行上下文；命中时为 1 行，不存在或不可获取时为 `[]` |



`result.columns[]` 每项：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `identifierCode` | string | 列标识，与 `rows[0]` 中的字段名一致 |

| `label` | string | 列展示名（当前与 `identifierCode` 相同） |

| `type` | string | 固定 `FIELD` |



`result.rows[0]` 字段与旧版 `data`（`ModelingExecutionContext`）相同：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `repositoryId` | long | 本体库 ID |

| `taskCode` | string | 任务编码 |

| `taskName` | string | 任务名称 |

| `modelName` | string | 模型名称 |

| `taskType` | string | `DATA_SOURCE_MODELING` / `DOCUMENT_MODELING` |

| `prompt` | string | 用户补充提示词 |

| `parseElements` | array | 解析要素列表 |

| `expectedFiles` | array | 期望产出的 CSV 文件名列表 |

| `outputPrefix` | string | Agent 输出目录前缀 |

| `database` | object / null | 数据库建模上下文 |

| `document` | object / null | 文档建模上下文 |



`database` 对象（数据源建模时有值）：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `databaseSourceId` | long | 数据库来源 ID |

| `dbType` | string | 数据库类型，如 `POSTGRESQL` |

| `host` | string | 主机 |

| `port` | int | 端口 |

| `database` | string | 数据库名 |

| `username` | string | 用户名 |

| `password` | string | 密码（加密，仅 Agent 执行使用） |

| `sourceSchema` | string | 源 Schema |

| `selectedTables` | array | 选中的表名列表 |



`document` 对象（文档建模时有值）：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `fileSourceId` | long | 文件来源 ID |

| `fileType` | string | 文件类型，如 `PDF` |

| `objectKey` | string | 对象存储 objectKey |



解析要素与输出文件对应关系：



| parseElement | 输出文件 |

| --- | --- |

| business\_object | business\_objects.csv |

| logical\_entity | logical\_entities.csv |

| business\_attribute | business\_attributes.csv |

| entity\_relation | entity\_relations.csv |

| business\_rule | business\_rules.csv |



**返回示例**



```json

{

  "success": true,

  "code": 200,

  "msg": "success",

  "data": {

    "resultType": "TABLE",

    "result": {

      "columns": [

        { "identifierCode": "repositoryId", "label": "repositoryId", "type": "FIELD" },

        { "identifierCode": "taskCode", "label": "taskCode", "type": "FIELD" },

        { "identifierCode": "taskName", "label": "taskName", "type": "FIELD" },

        { "identifierCode": "modelName", "label": "modelName", "type": "FIELD" },

        { "identifierCode": "taskType", "label": "taskType", "type": "FIELD" },

        { "identifierCode": "prompt", "label": "prompt", "type": "FIELD" },

        { "identifierCode": "parseElements", "label": "parseElements", "type": "FIELD" },

        { "identifierCode": "expectedFiles", "label": "expectedFiles", "type": "FIELD" },

        { "identifierCode": "outputPrefix", "label": "outputPrefix", "type": "FIELD" },

        { "identifierCode": "database", "label": "database", "type": "FIELD" },

        { "identifierCode": "document", "label": "document", "type": "FIELD" }

      ],

      "rows": [{

        "repositoryId": 1,

        "taskCode": "RM123456789",

        "taskName": "采购库智能建模",

        "modelName": "采购域模型",

        "taskType": "DATA_SOURCE_MODELING",

        "prompt": "优先识别采购订单与供应商",

        "parseElements": ["business_object", "logical_entity", "business_attribute"],

        "expectedFiles": ["business_objects.csv", "logical_entities.csv", "business_attributes.csv"],

        "outputPrefix": "ontology/1/modeling-tasks/RM123456789/agent-output",

        "database": {

          "databaseSourceId": 12,

          "dbType": "POSTGRESQL",

          "host": "127.0.0.1",

          "port": 5432,

          "database": "purchase",

          "username": "ontology_agent",

          "password": "crypted-password",

          "sourceSchema": "public",

          "selectedTables": ["purchase_order", "supplier"]

        },

        "document": null

      }]

    }

  }

}

```



### 获取智能建模任务上下文信息(新)



#### 基本信息



**接口说明**： 按 `taskCode` 获取智能建模任务的执行上下文，包括解析要素、期望输出文件、数据源或文档来源信息。响应统一为 `QueryResponse(TABLE)` 单行



**请求方法**：`GET`



**相对路径**：`/api/v1/analysis/context/modeling/tasks/{taskCode}/execution-context`



#### 请求参数



| 参数 | 类型 | 必填 | 含义与说明 |

| --- | --- | --- | --- |

| taskCode | String | 是 | 路径参数。智能建模任务编码，如 RM123456789。 |



**请求示例**



```json

GET /api/v1/analysis/context/modeling/tasks/RM123456789/execution-context

```



#### 返回参数（`data` 字段）



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `resultType` | string | 固定 `TABLE` |

| `result.columns` | array | 列定义；根据 `result.rows[0]` 实际字段生成 |

| `result.rows` | array | 执行上下文；命中时为 1 行，不存在或不可获取时为 `[]` |



`result.columns[]` 每项：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `identifierCode` | string | 列标识，与 `rows[0]` 中的字段名一致 |

| `label` | string | 列展示名（当前与 `identifierCode` 相同） |

| `type` | string | 固定 `FIELD` |



`result.rows[0]` 字段与旧版 `data`（`ModelingExecutionContext`）相同：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `repositoryId` | long | 本体库 ID |

| `taskCode` | string | 任务编码 |

| `taskName` | string | 任务名称 |

| `modelName` | string | 模型名称 |

| `taskType` | string | `DATA_SOURCE_MODELING` / `DOCUMENT_MODELING` |

| `prompt` | string | 用户补充提示词 |

| `parseElements` | array | 解析要素列表 |

| `expectedFiles` | array | 期望产出的 CSV 文件名列表 |

| `outputPrefix` | string | Agent 输出目录前缀 |

| `database` | object / null | 数据库建模上下文 |

| `document` | object / null | 文档建模上下文 |



`database` 对象（数据源建模时有值）：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `databaseSourceId` | long | 数据库来源 ID |

| `dbType` | string | 数据库类型，如 `POSTGRESQL` |

| `host` | string | 主机 |

| `port` | int | 端口 |

| `database` | string | 数据库名 |

| `username` | string | 用户名 |

| `password` | string | 密码（加密，仅 Agent 执行使用） |

| `qualifiedTables` | array | 全限定表名列表，格式为 `schema.table`；支持多个 Schema |



`document` 对象（文档建模时有值）：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `fileSourceId` | long | 文件来源 ID |

| `fileType` | string | 文件类型，如 `PDF` |

| `objectKey` | string | 对象存储 objectKey |



解析要素与输出文件对应关系：



| parseElement | 输出文件 |

| --- | --- |

| business\_object | business\_objects.csv |

| logical\_entity | logical\_entities.csv |

| business\_attribute | business\_attributes.csv |

| entity\_relation | entity\_relations.csv |

| business\_rule | business\_rules.csv |

| term | terms.csv |

| indicator | indicators.csv |

| action | actions.csv |



**返回示例**



```json

{

  "success": true,

  "code": 200,

  "msg": "success",

  "data": {

    "resultType": "TABLE",

    "result": {

      "columns": [

        { "identifierCode": "repositoryId", "label": "repositoryId", "type": "FIELD" },

        { "identifierCode": "taskCode", "label": "taskCode", "type": "FIELD" },

        { "identifierCode": "taskName", "label": "taskName", "type": "FIELD" },

        { "identifierCode": "modelName", "label": "modelName", "type": "FIELD" },

        { "identifierCode": "taskType", "label": "taskType", "type": "FIELD" },

        { "identifierCode": "prompt", "label": "prompt", "type": "FIELD" },

        { "identifierCode": "parseElements", "label": "parseElements", "type": "FIELD" },

        { "identifierCode": "expectedFiles", "label": "expectedFiles", "type": "FIELD" },

        { "identifierCode": "outputPrefix", "label": "outputPrefix", "type": "FIELD" },

        { "identifierCode": "database", "label": "database", "type": "FIELD" },

        { "identifierCode": "document", "label": "document", "type": "FIELD" }

      ],

      "rows": [{

        "repositoryId": 1,

        "taskCode": "RM123456789",

        "taskName": "采购库智能建模",

        "modelName": "采购域模型",

        "taskType": "DATA_SOURCE_MODELING",

        "prompt": "优先识别采购订单与供应商",

        "parseElements": ["business_object", "logical_entity", "business_attribute"],

        "expectedFiles": ["business_objects.csv", "logical_entities.csv", "business_attributes.csv"],

        "outputPrefix": "ontology/1/modeling-tasks/RM123456789/agent-output",

        "database": {

          "databaseSourceId": 12,

          "dbType": "POSTGRESQL",

          "host": "127.0.0.1",

          "port": 5432,

          "database": "purchase",

          "username": "ontology_agent",

          "password": "crypted-password",

          "qualifiedTables": [

            "public.purchase_order",

            "public.supplier",

            "finance.invoice"

          ]

        }

      }]

    }

  }

}

```



### 智能建模任务状态回调(旧)



**接口说明**：回传建模任务执行状态；`SUCCESS` 时必须携带结果文件清单；`FAILED` 时应填写错误码与错误信息



**请求方法**：POST



**相对路径**：`/intelligent/modeling/tasks/{taskCode}/callback`



#### 请求参数



| 参数 | 类型 | 必填 | 说明 |

| --- | --- | --- | --- |

| `taskCode` | string | 是 | 路径参数，建模任务编码 |

| `agentStatus` | string | 是 | Agent 状态：`RUNNING`、`SUCCESS`、`FAILED` |

| `occurredAt` | string | 是 | 事件发生时间，ISO-8601 带时区，如 `2026-07-20T10:35:00+08:00` |

| `errorCode` | string | `FAILED` 时建议填 | 失败错误码，如 `SOURCE_READ_FAILED` |

| `errorMessage` | string | `FAILED` 时建议填 | 失败信息 |

| `files` | array | `SUCCESS` 时必填 | 结果文件清单；`RUNNING` / `FAILED` 时可为空或 `null` |



`files[]` 每项：



| 字段 | 类型 | 必填 | 说明 |

| --- | --- | --- | --- |

| `parseElement` | string | 是 | 解析要素，如 `business_object` |

| `filename` | string | 是 | 文件名，如 `business_objects.csv` |

| `objectKey` | string | 是 | 对象存储 objectKey |

| `previewUrl` | string | 是 | FileServer 预览地址，须为 `http://\` 或 `https://\` |



**请求示例**



```json

POST /intelligent/modeling/tasks/RM123456789/callback

Content-Type: application/json

{

  "agentStatus": "RUNNING",

  "occurredAt": "2026-07-20T10:30:00+08:00"

}

```

```json

{

  "agentStatus": "SUCCESS",

  "occurredAt": "2026-07-20T10:35:00+08:00",

  "files": [

    {

      "parseElement": "business_object",

      "filename": "business_objects.csv",

      "objectKey": "ontology/1/modeling-tasks/RM123456789/agent-output/business_objects.csv",

      "previewUrl": "https://files.example.com/file/preview/static/ontology/1/modeling-tasks/RM123456789/agent-output/business_objects.csv"

    },

    {

      "parseElement": "logical_entity",

      "filename": "logical_entities.csv",

      "objectKey": "ontology/1/modeling-tasks/RM123456789/agent-output/logical_entities.csv",

      "previewUrl": "https://files.example.com/file/preview/static/ontology/1/modeling-tasks/RM123456789/agent-output/logical_entities.csv"

    }

  ]

}

```

```json

{

  "agentStatus": "FAILED",

  "occurredAt": "2026-07-20T10:36:00+08:00",

  "errorCode": "SOURCE_READ_FAILED",

  "errorMessage": "无法连接源数据库"

}

```



**响应示例**



```json

{

  "success": true,

  "code": 200,

  "msg": "success"

}

```



### 智能建模任务状态回调(新)



#### 基本信息



**接口说明**： 回传建模任务执行状态。`SUCCESS` 时必须携带结果文件清单；`FAILED` 时应填写错误码与错误信息。回调字段放入 `analysisConfig`



**请求方法**：`POST`



**相对路径**：`/api/v1/analysis/context/modeling/tasks/{taskCode}/callback`



**Content-Type**：`application/json`



#### 请求参数



| 参数 | 类型 | 必填 | 说明 |

| --- | --- | --- | --- |

| `taskCode` | string | 是 | 路径参数，建模任务编码 |

| `analysisConfig` | object | 是 | `AgentTaskCallbackConfig`，字段含义与旧版 body 根级相同 |

| `commonConfig` | object | 是 | 传 `{}` 即可；`filters` / `sorts` / `pagination` 不生效 |



`analysisConfig` 字段：



| 字段 | 类型 | 必填 | 说明 |

| --- | --- | --- | --- |

| `agentStatus` | string | 是 | Agent 状态：`RUNNING`、`SUCCESS`、`FAILED` |

| `occurredAt` | string | 是 | 事件发生时间，ISO-8601 带时区 |

| `errorCode` | string | `FAILED` 时建议填 | 失败错误码 |

| `errorMessage` | string | `FAILED` 时建议填 | 失败信息 |

| `files` | array | `SUCCESS` 时必填 | 结果文件清单；`RUNNING` / `FAILED` 时可为空或 `null` |



`analysisConfig.files[]` 每项：



| 字段 | 类型 | 必填 | 说明 |

| --- | --- | --- | --- |

| `parseElement` | string | 是 | 解析要素，如 `business_object` |

| `filename` | string | 是 | 文件名，如 `business_objects.csv` |

| `objectKey` | string | 是 | 对象存储 objectKey |

| `previewUrl` | string | 是 | FileServer 预览地址 |



**请求示例**



```json

POST /api/v1/analysis/context/modeling/tasks/RM123456789/callback

Content-Type: application/json

{

  "analysisConfig": {

    "agentStatus": "RUNNING",

    "occurredAt": "2026-07-20T10:30:00+08:00"

  },

  "commonConfig": {}

}



```

```json

{

  "analysisConfig": {

    "agentStatus": "SUCCESS",

    "occurredAt": "2026-07-20T10:35:00+08:00",

    "files": [

      {

        "parseElement": "business_object",

        "filename": "business_objects.csv",

        "objectKey": "ontology/1/modeling-tasks/RM123456789/agent-output/business_objects.csv",

        "previewUrl": "https://files.example.com/file/preview/static/ontology/1/modeling-tasks/RM123456789/agent-output/business_objects.csv"

      }

    ]

  },

  "commonConfig": {}

}



```

```json

{

  "analysisConfig": {

    "agentStatus": "FAILED",

    "occurredAt": "2026-07-20T10:36:00+08:00",

    "errorCode": "SOURCE_READ_FAILED",

    "errorMessage": "无法连接源数据库"

  },

  "commonConfig": {}

}



```



**返回示例**



```json

{

  "success": true,

  "code": 200,

  "msg": "success"

}

```



### 获取智能消歧整合任务上下文信息(旧)



**接口说明**：按 `taskCode` 获取消歧整合任务的执行上下文，包括源模型、校验类型、整合策略、期望输出文件等。



**请求方法**：`GET`



**相对路径**：`/intelligent/integration/tasks/{taskCode}/execution-context`



#### 请求参数



| 参数 | 类型 | 必填 | 说明 |

| --- | --- | --- | --- |

| `taskCode` | string | 是 | 路径参数，整合任务编码，如 `MI123456789` |



**请求示例**



```json

GET /intelligent/integration/tasks/MI123456789/execution-context

```



#### 返回参数（`data` 字段）



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `taskCode` | string | 任务编码 |

| `modelName` | string | 模型名称 |

| `sourceMode` | string | 来源模式，如 `MODELING_TASKS` |

| `sourceModels` | object | 待整合源模型；结构随 `sourceMode` 变化 |

| `sourceModels.mode` | string | 来源模式，与 `sourceMode` 一致 |

| `sourceModels.items` | array | 源模型条目列表 |

| `sourceModels.items[].taskCode` | string | 源建模任务编码（`mode=MODELING_TASKS` 时） |

| `checkTypes` | array | 校验类型，如 `CONSISTENCY` |

| `validationRules` | object | 校验规则 |

| `integrationStrategy` | object | 整合策略 |

| `integrationStrategy.semanticSimilarityThreshold` | number | 语义相似度阈值，如 `0.85` |

| `prompt` | string | 用户补充提示词 |

| `outputPrefix` | string | Agent 输出目录前缀 |

| `expectedFiles` | array | 期望产出的文件名列表 |



**返回示例**



```json

{

  "success": true,

  "code": 200,

  "msg": null,

  "data": {

    "taskCode": "MI123456789",

    "modelName": "采购域标准模型",

    "sourceMode": "MODELING_TASKS",

    "sourceModels": {

      "mode": "MODELING_TASKS",

      "items": [

        { "taskCode": "RM123456789" },

        { "taskCode": "RM123456790" }

      ]

    },

    "checkTypes": ["CONSISTENCY"],

    "validationRules": {},

    "integrationStrategy": {

      "semanticSimilarityThreshold": 0.85

    },

    "prompt": "同义实体优先合并",

    "outputPrefix": "ontology/1/integration-tasks/MI123456789/agent-output",

    "expectedFiles": [

      "business_objects.csv",

      "logical_entities.csv",

      "business_attributes.csv",

      "entity_relations.csv",

      "integration_report.csv",

      "merged_elements.csv",

      "pending_elements.csv",

      "conflict_elements.csv",

      "missing_elements.csv"

    ]

  }

}

```



### 获取智能消歧整合任务上下文信息(新)



#### 基本信息



**接口说明**： 按 `taskCode` 获取消歧整合任务的执行上下文，包括源模型、校验类型、整合策略、期望输出文件等。响应统一为 `QueryResponse(TABLE)` 单行



**请求方法**：`GET`



**相对路径**：`/api/v1/analysis/context/integration/tasks/{taskCode}/execution-context`



**Content-Type**：`application/json`



#### 请求参数



| 参数 | 类型 | 必填 | 含义与说明 |

| --- | --- | --- | --- |

| taskCode | String | 是 | 路径参数。消歧整合任务编码，如 MI123456789。 |



**请求示例**



```json

GET /api/v1/analysis/context/integration/tasks/MI123456789/execution-context

```



#### 返回参数（`data` 字段）



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `resultType` | string | 固定 `TABLE` |

| `result.columns` | array | 列定义 |

| `result.rows` | array | 最多 1 行；上下文为空时为 `[]` |



`result.rows[0]` 字段与旧版 `IntegrationExecutionContext` 相同



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `taskCode` | string | 任务编码 |

| `modelName` | string | 模型名称 |

| `sourceMode` | string | 来源模式，如 `MODELING_TASKS` |

| `sourceModels` | object | 待整合源模型；结构随 `sourceMode` 变化 |

| `sourceModels.mode` | string | 来源模式，与 `sourceMode` 一致 |

| `sourceModels.items` | array | 源模型条目列表 |

| `sourceModels.items[].taskCode` | string | 源建模任务编码（`mode=MODELING_TASKS` 时） |

| `checkTypes` | array | 校验类型，如 `CONSISTENCY` |

| `validationRules` | object | 校验规则 |

| `integrationStrategy` | object | 整合策略 |

| `integrationStrategy.semanticSimilarityThreshold` | number | 语义相似度阈值，如 `0.85` |

| `prompt` | string | 用户补充提示词 |

| `outputPrefix` | string | Agent 输出目录前缀 |

| `expectedFiles` | array | 期望产出的文件名列表 |



**返回示例**



```json

{

  "success": true,

  "code": 200,

  "msg": "success",

  "data": {

    "resultType": "TABLE",

    "result": {

      "columns": [

        { "identifierCode": "taskCode", "label": "taskCode", "type": "FIELD" },

        { "identifierCode": "modelName", "label": "modelName", "type": "FIELD" },

        { "identifierCode": "sourceMode", "label": "sourceMode", "type": "FIELD" },

        { "identifierCode": "sourceModels", "label": "sourceModels", "type": "FIELD" },

        { "identifierCode": "checkTypes", "label": "checkTypes", "type": "FIELD" },

        { "identifierCode": "validationRules", "label": "validationRules", "type": "FIELD" },

        { "identifierCode": "integrationStrategy", "label": "integrationStrategy", "type": "FIELD" },

        { "identifierCode": "prompt", "label": "prompt", "type": "FIELD" },

        { "identifierCode": "outputPrefix", "label": "outputPrefix", "type": "FIELD" },

        { "identifierCode": "expectedFiles", "label": "expectedFiles", "type": "FIELD" }

      ],

      "rows": [{

        "taskCode": "MI123456789",

        "modelName": "采购域标准模型",

        "sourceMode": "MODELING_TASKS",

        "sourceModels": {

          "mode": "MODELING_TASKS",

          "items": [{ "taskCode": "RM123456789" }, { "taskCode": "RM123456790" }]

        },

        "checkTypes": ["CONSISTENCY"],

        "validationRules": {},

        "integrationStrategy": { "semanticSimilarityThreshold": 0.85 },

        "prompt": "同义实体优先合并",

        "outputPrefix": "ontology/1/integration-tasks/MI123456789/agent-output",

        "expectedFiles": [

          "business_objects.csv",

          "logical_entities.csv",

          "business_attributes.csv",

          "entity_relations.csv",

          "integration_report.csv",

          "merged_elements.csv",

          "pending_elements.csv",

          "conflict_elements.csv",

          "missing_elements.csv"

        ]

      }]

    }

  }

}

```



### 智能消歧整合任务状态回调(旧)



#### 基本信息



**接口说明**： 回传消歧整合任务执行状态。`SUCCESS` 时 Agent 须已将结果文件写入 `outputPrefix` 并上传 `ok.csv`；`FAILED` 时应填写错误码与错误信息



**请求方法**：`POST`



**相对路径**：`/intelligent/integration/tasks/{taskCode}/callback`



#### 请求参数



| 参数 | 类型 | 必填 | 说明 |

| --- | --- | --- | --- |

| `taskCode` | string | 是 | 路径参数，整合任务编码 |

| `agentStatus` | string | 是 | Agent 状态：`RUNNING`、`SUCCESS`、`FAILED` |

| `occurredAt` | string | 是 | 事件发生时间，ISO-8601 带时区 |

| `errorCode` | string | `FAILED` 时建议填 | 失败错误码 |

| `errorMessage` | string | `FAILED` 时建议填 | 失败信息 |



**请求示例**



```json

POST /intelligent/integration/tasks/MI123456789/callback

{

  "agentStatus": "RUNNING",

  "occurredAt": "2026-07-20T11:00:00+08:00"

}

```

```json

{

  "agentStatus": "SUCCESS",

  "occurredAt": "2026-07-20T11:05:00+08:00"

}

```

```json

{

  "agentStatus": "FAILED",

  "occurredAt": "2026-07-20T11:06:00+08:00",

  "errorCode": "MERGE_CONFLICT",

  "errorMessage": "存在无法自动合并的冲突实体"

}

```



**返回示例**



```json

{

  "success": true,

  "code": 200,

  "msg": null,

  "data": null

}

```



### 智能消歧整合任务状态回调(新)



#### 基本信息



**接口说明**： 回传消歧整合任务执行状态。`SUCCESS` 时 Agent 须已将结果文件写入 `outputPrefix` 并上传 `ok.csv`；`FAILED` 时应填写错误码与错误信息



**请求方法**：`POST`



**相对路径**：`/api/v1/analysis/context/integration/tasks/{taskCode}/callback`



**Content-Type**：`application/json`



#### 请求参数



| 参数 | 类型 | 必填 | 说明 |

| --- | --- | --- | --- |

| `taskCode` | string | 是 | 路径参数，整合任务编码 |

| `analysisConfig` | object | 是 | `AgentTaskCallbackConfig`；字段含义与旧版 body 根级相同 |

| `commonConfig` | object | 是 | 传 `{}` 即可 |



`analysisConfig` 字段：



| 字段 | 类型 | 必填 | 说明 |

| --- | --- | --- | --- |

| `agentStatus` | string | 是 | `RUNNING`、`SUCCESS`、`FAILED` |

| `occurredAt` | string | 是 | 事件发生时间 |

| `errorCode` | string | `FAILED` 时建议填 | 失败错误码 |

| `errorMessage` | string | `FAILED` 时建议填 | 失败信息 |

| `files` | array | 禁止 | Integration 回调**不得**携带；传非空数组返回 400 |



**请求示例**



```json

POST /api/v1/analysis/context/integration/tasks/MI123456789/callback

{

  "analysisConfig": {

    "agentStatus": "RUNNING",

    "occurredAt": "2026-07-20T11:00:00+08:00"

  },

  "commonConfig": {}

}

```

```json

{

  "analysisConfig": {

    "agentStatus": "SUCCESS",

    "occurredAt": "2026-07-20T11:05:00+08:00"

  },

  "commonConfig": {}

}

```

```json

{

  "analysisConfig": {

    "agentStatus": "FAILED",

    "occurredAt": "2026-07-20T11:06:00+08:00",

    "errorCode": "MERGE_CONFLICT",

    "errorMessage": "存在无法自动合并的冲突实体"

  },

  "commonConfig": {}

}

```



**返回示例**



```json

{

  "success": true,

  "code": 200,

  "msg": "success"

}

```



## 业务数据



### 自定义SQL 查询(旧)



**接口说明**：支持ANSI标准，执行只读 `SELECT` 查询，返回结果集



**请求方法**：POST



**路径**：`/agent/doris/query`



**请求参数**



| 参数 | 类型 | 必填 | 含义 |

| --- | --- | --- | --- |

| `sql` | string | 是 | 待执行的 SQL 语句，**仅允许单条 SELECT** |



**SQL 约束：**



| 规则 | 说明 |

| --- | --- |

| 必须以 `SELECT` 开头 | 不区分大小写 |

| 不允许多条语句 | 不能包含 `;` 分隔的多条 SQL |

| 末尾分号 | 会自动去除 |



**请求示例**



```json

POST /agent/doris/query

{

  "sql": "SELECT allocationRelationId, unitCode, deleteFlag FROM `ontology_demo_scm_po`.`PoAllocationRelation` LIMIT 10"

}

```



**返回参数**（`data` 字段）



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `rows` | array | 结果行列表 |

| `rowCount` | int | 返回行数 |



**响应示例**



```json

{

  "code": 200,

  "msg": null,

  "data": {

    "rows": [

      {

        "allocationRelationId": 1830513348099637200,

        "unitCode": "1000",

        "deleteFlag": "N"

      }

    ],

    "rowCount": 1

  }

}

```



### 自定义SQL 查询(新)



**接口说明：**支持ANSI标准，执行只读 `SELECT` 查询，返回统一分析 `TABLE` 结果集。



**请求方法：** `POST`



**路径：** `/api/v1/analysis/data/query`



**Content-Type：** `application/json`



**请求参数**



| 参数 | 类型 | 必填 | 含义 |

| --- | --- | --- | --- |

| `analysisConfig.sql` | string | 是 | 单条 SELECT；排序分页写在 SQL 内 |

| `commonConfig` | object | 是 | 传 `{}`；不支持 `filters` / `sorts` / `pagination` |



**业务库命名约定**



| 概念 | 规则 | 示例 |

| --- | --- | --- |

| 业务库名 | 取本体库 `currentDatabase` | `ontology_demo_scm_po` |

| 表名（查询用） | `LogicalEntity.name` | `PoAllocationRelation` |

| 列名 | `BusinessAttribute.name` | `allocationRelationId` |



**请求示例**



```http

POST /api/v1/analysis/data/query

Content-Type: application/json

{

  "analysisConfig": {

    "sql": "SELECT allocationRelationId, unitCode, deleteFlag FROM `ontology_demo_scm_po`.`PoAllocationRelation` LIMIT 10"

  },

  "commonConfig": {}

}



```

```http

{

  "analysisConfig": {

    "sql": "SELECT allocationRelationId, unitCode, deleteFlag FROM `ontology_demo_scm_po`.`PoAllocationRelation` ORDER BY allocationRelationId ASC LIMIT 20 OFFSET 0"

  },

  "commonConfig": {}

}

```



**返回参数**（`data` 字段）



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `resultType` | string | 固定 `TABLE` |

| `result.columns` | array | 列定义；根据首行 `rows[0]` 的字段名动态生成；无数据时为 `[]` |

| `result.rows` | array | 结果行 |



`result.columns[]` 每项：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `identifierCode` | string | 列标识，与 `rows[]` 中的字段名一致 |

| `label` | string | 列展示名（当前与 `identifierCode` 相同） |

| `type` | string | 固定 `ATTRIBUTE`（业务属性列） |



`result.rows[]` 每项：动态对象，字段由 SQL `SELECT` 列表决定。上例中：



| 字段 | 类型 | 说明 |

| --- | --- | --- |

| `allocationRelationId` | long | 分配关系 ID |

| `unitCode` | string | 组织单元编码 |

| `deleteFlag` | string | 删除标记，如 `N` |



**响应示例**



```json

{

  "success": true,

  "code": 200,

  "msg": "success",

  "data": {

    "resultType": "TABLE",

    "result": {

      "columns": [

        { "identifierCode": "allocationRelationId", "label": "allocationRelationId", "type": "ATTRIBUTE" },

        { "identifierCode": "unitCode", "label": "unitCode", "type": "ATTRIBUTE" },

        { "identifierCode": "deleteFlag", "label": "deleteFlag", "type": "ATTRIBUTE" }

      ],

      "rows": [

        {

          "allocationRelationId": 1830513348099637200,

          "unitCode": "1000",

          "deleteFlag": "N"

        }

      ]

    }

  }

}

```



### 指标维度计算



#### 基本信息



**接口说明：**指标多维维度分析接口，返回指标结果集



**请求方法：** `POST`



**相对路径：** `api/v1/analysis/data/query`



**Content-Type：** `application/json`



#### 请求参数



| 参数层级 | 类型 | 必填 | 含义与说明 |

| --- | --- | --- | --- |

| `analysisConfig` | Object | 是 | 分析配置。定义当前查询需要展示的指标和维度。 |

| ├─ `indicators` | Array | 是 | 指标列表。定义需要聚合计算的度量字段。 |

| ├─ `identifierCode` | String | 是 | 指标唯一标识编码（如 `M0001`）。 |

| ├─ `alias` | String | 否 | 指标别名，用于前端展示（如 `销售总金额`）。 |

| ├─ `valueConfig` | Object | 否 | **值处理与格式化配置**。统一处理字段的数据预处理逻辑及前端展示样式。 |

| └─ `numericScale` | Integer | 否 | 数值精度，保留的小数位数（如 `2`）。 |

| └─ `dimensions` | Array | 是 | 维度列表。定义数据分组的字段（明细模式下通常为空）。 |

| ├─ `identifierCode` | String | 是 | 维度唯一标识编码（如 `order_date`）。 |

| └─ `alias` | String | 否 | 维度别名，用于前端展示（如 `下单时间`）。 |

| `commonConfig` | Object | 是 | 通用查询配置。包含过滤、排序、分页等全局设置。 |

| ├─ `filters` | Array | 否 | 过滤条件列表。支持树形嵌套逻辑组合。 |

| ├─ `identifierCode` | String | 条件必填 | 字段标识。仅当该节点为具体条件时必填，逻辑节点无需此字段。 |

| ├─ `operator` | Object | 条件必填 | 比较操作对象，包含 code 与 type; <br>code 是操作符编码如 EQ、LIKE、IN、BETWEEN; <br>type 是过滤字段值类型，如 STRING、NUMBER、DATE、BOOLEAN |

| ├─ `valueType` | String | 否 | 值类型标识。`ABSOLUTE`（绝对值，默认）、`MODIFIER`（修饰词/动态相对值）。 |

| ├─ `value` | Any | 条件必填 | 过滤值。根据 `valueType` 支持多种类型：<br>• 绝对值：字符串或数组<br>• 简单修饰词：字符串（如 `TODAY`）<br>• 动态修饰词：对象（如 `{modifierCode: "RECENT_N_DAYS", params: {days: 7}}`） |

| ├─ `logic` | String | 条件必填 | 逻辑连接符。仅当该节点为逻辑组合节点时必填，可选 `AND`、`OR`。 |

| └─ `children` | Array | 条件必填 | 子过滤条件列表。仅当该节点为逻辑组合节点时必填，支持无限递归嵌套。 |

| ├─ `sorts` | Array | 否 | 排序规则列表。 |

| ├─ `identifierCode` | String | 是 | 排序字段的唯一标识编码（可以是指标或维度编码）。 |

| └─ `order` | String | 是 | 排序方向。可选值：`ASC`（升序）、`DESC`（降序）。 |

| └─ `pagination` | Object | 是 | 分页配置。 |

| ├─ `pageNum` | Integer | 是 | 当前页码，从 1 开始。 |

| └─ `pageSize` | Integer | 是 | 每页数据条数。 |



**示例**



```json

{

    "analysisConfig": {

        "indicators": [

            {

                "identifierCode": "M0001",

                "alias": "销售总金额",

                "valueConfig": {

                    "numericScale": 2

                }

            }

        ],

        "dimensions": [

            {

                "identifierCode": "order_date",

                "alias": "下单时间"

            },

            {

                "identifierCode": "region",

                "alias": "地区"

            },

            {

                "identifierCode": "category",

                "alias": "类别"

            }

        ]

    },

    "commonConfig": {

        "filters": {

            "logic": "AND",

            "children": [

                {

                    "identifierCode": "order_date",

                    "operator": {

                       "code": "BETWEEN",

                       "type": "DATA"

                     },

                    "valueType": "ABSOLUTE",

                    "value": [

                        "2026-01-01",

                        "2026-06-17"

                    ]

                },

                {

                    "logic": "AND",

                    "children": [

                        {

                            "logic": "OR",

                            "children": [

                                {

                                    "identifierCode": "category",

                                     "operator": {

                                        "code": "EQ",

                                        "type": "STRING"

                                     },

                                    "valueType": "ABSOLUTE",

                                    "value": "1"

                                },

                                {

                                    "identifierCode": "region",

                                     "operator": {

                                        "code": "EQ",

                                        "type": "STRING"

                                     },

                                    "valueType": "ABSOLUTE",

                                    "value": "ShangHai"

                                }

                            ]

                        },

                        {

                            "identifierCode": "M0001",

                            "operator": {

                               "code": "GT",

                               "type": "NUMBER"

                            },

                            "valueType": "ABSOLUTE",

                            "value": 1000

                        }

                    ]

                }

            ]

        },

        "sorts": [

            {

                "identifierCode": "M0001",

                "order": "DESC"

            }

        ],

        "pagination": {

            "pageNum": 1,

            "pageSize": 20

        }

    }

}

```



#### 返回参数（`data` 字段）



| 参数层级 | 类型 | 含义与说明 |

| --- | --- | --- |

| `data` | Object | 核心业务数据。包含查询结果的元数据、数据行及分页信息。 |

| ├─ `resultType` | String | 结果类型标识。用于前端判断如何渲染 `result` 中的数据。<br>值：`TABLE`（扁平表格）。 |

| ├─ `result` | Object | 结果数据载体（多态）。根据 `resultType` 的不同，包含不同的数据结构。 |

| ├─ `columns` | Array | 指标或维度（表头元数据）。描述返回结果中包含哪些字段及其类型。 |

| ├─ `identifierCode` | String | 指标或维度实例数据唯一标识（对应 `rows` 中的 key，如 `region`）。 |

| ├─ `label` | String | 指标或维度展示名称（用于前端表头渲染，如 `区域`）。 |

| └─ `type` | String | 指标或维度类型。可选值：`DIMENSION`（维度）、`METRIC`（指标/度量）。 |

| ├─ `rows` | Array<Map<`Key`,`Value`\>> | 数据行列表。包含具体的查询结果数据。 |

| ├─ `[Key]` | Any | 对应 `columns` 中的 `identifierCode`。 |

| ├─ `[value]` | Any | 对应的`identifierCode`关联的Value Object |

| ├─ value | Any | 具体值。 |

| └─ `render` | Object | 单元格渲染配置（选填）。用于后端下发动态样式或交互规则。 |

| ├─ unit | String | 金额value的单位 |

| └─ `frontColor` | String | 字体颜色配置（如 `#FF0000`）。 |

| └─ `pagination` | Object | 分页信息。 |

| ├─ `total` | Integer | 满足当前查询条件的总记录数。 |

| ├─ `pageNum` | Integer | 当前页码。 |

| └─ `pageSize` | Integer | 每页数据条数。 |



**示例**



```json

{

    "code": 200,

    "msg": "success",

    "data": {

        "resultType": "TABLE",

        "result": {

            "columns": [

                {

                    "identifierCode": "region",

                    "label": "区域",

                    "type": "DIMENSION"

                },

                {

                    "identifierCode": "category",

                    "label": "类别",

                    "type": "DIMENSION"

                },

                {

                    "identifierCode": "total_sales",

                    "label": "总销售额",

                    "type": "METRIC"

                }

            ],

            "rows": [

                "region": {

                        "value": "华东"

                    },

                "category": {

                    "value": "数码"

                },

                "total_sales": {

                    "value": 150,

                    "render": {

                        "unit": "万元",

                        "frontColor": "#FF0000"

                    }

                }

            ]

        },

        "pagination": {

            "total": 2,

            "pageNum": 1,

            "pageSize": 20

        }

    }

}

```



#### 更多场景



更多指标计算场景请参阅：[《指标维度计算API-WIP》](https://alidocs.dingtalk.com/i/nodes/R1zknDm0WRbNmEZ0I0v92j3zWBQEx5rG)



### 本体实例计算



#### 基本信息



**接口说明：**指标多维维度分析接口，返回指标结果集



**请求方法：** `POST`



**相对路径：** `api/v1/analysis/data/query`



**Content-Type：** `application/json`



#### 请求参数



| 参数层级 | 类型 | 必填 | 含义与说明 |

| --- | --- | --- | --- |

| `analysisConfig` | Object | 是 | 分析配置。定义明细查询需要返回的字段（业务对象）。 |

| ├─ `vertex` | Array | 是 | 业务对象字段列表。定义明细数据中需要展示的具体列。 |

| ├─ `identifierCode` | String | 是 | 本体元数据唯一标识；如：逻辑实体编码。（如 `LE000006`）。 |

| ├─ properties | Array | 否 |  |

| ├─ `alias` | String | 否 | 字段别名，用于前端表头展示（如 `采购订单类型`）。 |

| ├─ `identifierCode` | String | 是 | 字段/属性的唯一标识编码（如 `AT0000212`）。 |

| ├─ `valueConfig` | Object | 否 | 值处理与格式化配置。统一处理字段的数据预处理逻辑及前端展示样式。 |

| ├─ `function` | String | 否 | 预处理/聚合函数。定义对原始数据的处理逻辑，如 `distinct`（去重）、`sum`（求和）等。未传则返回原始值。 |

| └─ `numericScale` | Integer | 否 | 数值精度。定义格式化后保留的小数位数（如 `2`）。 |

| ├─ `link` | Array | 否 | 默认查ER关系，暂时不支持其他关系 |

| `commonConfig` | Object | 是 | 通用查询配置。包含过滤、排序、分页等全局设置。 |

| ├─ `filters` | Object | 否 | 过滤条件（根节点）。注意：此处为树形结构的根节点对象，非数组。 |

| ├─ `logic` | String | 是 | 根节点的逻辑连接符。可选值：`AND`、`OR`。 |

| └─ `children` | Array | 是 | 子过滤条件列表。支持递归嵌套。 |

| ├─ `identifierCode` | String | 条件必填 | 过滤字段的唯一标识编码。 |

| ├─ `operator` | Object | 条件必填 | 比较操作对象 |

| ├─ `valueType` | String | 否 | 值类型标识。`ABSOLUTE`（绝对值，默认）、`MODIFIER`（修饰词）。 |

| └─ `value` | Any | 条件必填 | 过滤值。根据 `valueType` 和操作符传入对应的值。 |

| ├─ `sorts` | Array | 否 | 排序规则列表。 |

| ├─ `identifierCode` | String | 是 | 排序字段的唯一标识编码。 |

| └─ `order` | String | 是 | 排序方向。可选值：`ASC`（升序）、`DESC`（降序）。 |

| └─ `pagination` | Object | 是 | 分页配置。 |

| ├─ `pageNum` | Integer | 是 | 当前页码，从 1 开始。 |

| └─ `pageSize` | Integer | 是 | 每页数据条数。 |



**示例**



```json

{

    "analysisConfig": {

        "vertex": [

            {

                "identifierCode": "LE000006",

                "properties": [

                    {

                        "alias": "采购订单类型",

                        "identifierCode": "AT0000212"

                    }

                ]

            },

            {

                "identifierCode": "LE000007",

                "properties": [

                    {

                        "alias": "数量",

                        "identifierCode": "AT0000271",

                        "valueConfig": {

                            "function": "sum"

                        }

                    }

                ]

            }

        ]

    },

    "commonConfig": {

        "filters": {

            "logic": "AND",

            "children": [

                {

                    "identifierCode": "AT0000212",

                    "operator": {

                      "code": "EQ",

                      "type": "STRING"

                    },

                    "valueType": "ABSOLUTE",

                    "value": "STANDARD_PURCHASE_ORDER"

                },

                {

                    "identifierCode": "AT0000271",

                    "operator": {

                      "code": "GT",

                      "type": "NUMBER"

                    },

                    "valueType": "ABSOLUTE",

                    "value": 50

                }

            ]

        },

        "sorts": [

            {

                "identifierCode": "AT0000212",

                "order": "DESC"

            }

        ],

        "pagination": {

            "pageNum": 1,

            "pageSize": 20

        }

    }

}

```



#### 返回参数（`**data**` 字段）



| 参数层级 | 类型 | 含义与说明 |

| --- | --- | --- |

| `data` | Object | 核心业务数据。包含查询结果的元数据及动态的结果载体。 |

| ├─ `resultType` | String | 结果类型标识。用于前端判断如何渲染 `result` 中的数据。<br>可选值：`TABLE`（扁平表格）、`TREE`（树形结构）。 |

| ├─ `result` | Object | 结果数据载体（多态）。根据 `resultType` 的不同，包含不同的数据结构。 |

| ├─ `columns` | Array | 本体元数据列表。同时兼容表格表头和树形节点配置。 |

| ├─ `identifierCode` | String | 本体元数据(如：属性/维度)唯一标识（对应 `rows` 中的 key ）。 |

| ├─ `label` | String | 本体元数据的展示名称。 |

| └─ `type` | String | 本体元数据类型。如 `ATTRIBUTE`（普通属性）、`DIMENSION`（维度）。 |

| ├─ 当 `**resultType**` **=** `**TABLE**` 时： |  |  |

| ├─ `rows` | Array<Map<`Key`,`Value`\>> | 本体元数据的实例数据行列表 |

| ├─ `[Key]` | Any | 对应 `columns` 中的 `identifierCode`。 |

| ├─ `[Value]` | Any | 对应的`identifierCode`关联的Value Object |

| ├─ value | Any | 具体值。如：性别维度值男、女 |

| ├─ `render` | Object | 单元格渲染配置（选填）。用于后端下发动态样式或交互规则。 |

| └─ `frontColor` | String | 字体颜色配置（如 `#FF0000`）。 |

| ├─ **当** `**resultType**` **=** `**TREE**` **时：** |  |  |

| ├─ `rows` | Array<Map<`Key`,`Value`\>> | 本体元数据的实例数据树形节点列表。`Value`支持无限层级嵌套。 |

| ├─ `[Key]` | Any | 对应 `columns` 中的 `identifierCode`。 |

| ├─ `[Value]` | Any | 对应的`identifierCode`关联的Value Object |

| ├─ `identifierNumber` | Any | 本体元数据的实例数据节点编号或唯一标识。 |

| ├─ `value` | Any | 本体元数据的实例数据节点的展示文本。 |

| ├─ `render` | Object | 单元格渲染配置（选填）。用于后端下发动态样式或交互规则。 |

| └─ `frontColor` | String | 字体颜色配置（如 `#FF0000`）。 |

| └─ `children` | Array<`[Value]`\> | 子节点列表。结构同 `[Value]`，支持递归嵌套。 |

| └─ `pagination` | Object | 分页信息（仅 `TABLE` 模式下生效）。 |

| ├─ `total` | Integer | 满足当前查询条件的总记录数。 |

| ├─ `pageNum` | Integer | 当前页码。 |

| └─ `pageSize` | Integer | 每页数据条数。 |



**示例**



```json

{

    "code": 200,

    "msg": "success",

    "data": {

        "resultType": "TABLE",

        "result": {

            "columns": [

                {

                    "identifierCode": "AT0000212",

                    "label": "采购订单类型",

                    "type": "ATTRIBUTE"

                },

                {

                    "identifierCode": "AT0000271",

                    "label": "数量",

                    "type": "ATTRIBUTE"

                }

            ],

            "rows": [

                {

                    "AT0000212": "STANDARD_PURCHASE_ORDER",

                    "AT0000271": {

                       "value": 150

                    }

                },

                {

                    "AT0000212": "STANDARD_PURCHASE_ORDER",

                    "AT0000271": {

                        "value": 85,

                        "render": {

                            "frontColor": "#FF0000"

                        }

                    }

                },

                {

                    "AT0000212": "STANDARD_PURCHASE_ORDER",

                    "AT0000271": {

                       "value": 210

                    }

                }

            ]

        },

        "pagination": {

            "total": 3,

            "pageNum": 1,

            "pageSize": 20

        }

    }

}

```

```json

{

    "code": 200,

    "msg": "success",

    "data": {

        "resultType": "Table",

        "result": {

            "columns": [

                {

                    "identifierCode": "D00000982",

                    "label": "性别",

                    "type": "DIMENSION"

                }

            ],

            "rows": [

                {

                    "D00000982": [

                      {

                        "identifierNumber": "1",

                        "value": "男"

                      },

                       {

                        "identifierNumber": "1",

                        "value": "女"

                      }

                    ]

                }

            ]

        },

        "pagination": null

    }

}

```

```json

{

    "code": 200,

    "msg": "success",

    "data": {

        "resultType": "TREE",

        "result": {

            "columns": [

                {

                    "identifierCode": "D00000981",

                    "label": "组织架构",

                    "type": "DIMENSION"

                }

            ],

            "rows": [

                {

                    "D00000981": {

                      "identifierNumber": "1001",

                      "value": "华东大区",

                      "children": [

                          {

                              "identifierNumber": "1001-01",

                              "value": "上海分公司",

                              "children": []

                          }

                      ]

                    }

                }

            ]

        },

        "pagination": null

    }

}

```



#### 更多场景



更多本体实例计算场景请参阅：[《本体实例计算API-WIP》](https://alidocs.dingtalk.com/i/nodes/gvNG4YZ7JnYN9R1yuNqyQgQOV2LD0oRE?utm_scene=team_space)