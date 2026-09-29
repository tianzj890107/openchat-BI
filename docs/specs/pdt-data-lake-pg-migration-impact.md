# PDT 本体服务数据湖切换 PG 引擎：分析 Agent 连接影响记录

> 状态：**只记录，不修改**（2026-09-22 记录）。本文件只承载"现在有什么影响、需要改什么"的
> 结论与实测证据；按当前要求，本轮**不修改任何生产代码、配置和部署文档**，不创建红测，
> 也不涉及部署。
>
> 来源：2026-09-22 对 pdt-dev 本体网关及其数据查询出口的**只读**实测
> （仅 `GET` 目录接口 + `POST` 只读 `SELECT`，无写操作、无删除/重置、无真实凭据输出），
> 以及仓库 HEAD（`20260727`）代码走查。

---

## 0. 一句话结论

pdt-dev 本体服务的数据湖已从 Doris（MySQL 协议）切换为 **PostgreSQL 17.7**，Agent 的连接方式
（HTTP 网关）**不需要改**；真正失效的是 **SQL 方言、两条元数据查询 SQL、本体库 ID** 三处，
另有若干"不报错但会答错"的语义变化。钱江本体库（id 12）目前**数据与元数据都还没落地**，
所以钱江功能当前的主要阻塞不是方言，而是"库里没有东西 + 列表/结构查询必然 500"。

---

## 1. 实测证据

### 1.1 引擎与拓扑

| 探针（`POST /agent/doris/query`，`X-Ontology-Repository-Id: 12`） | 结果 |
| --- | --- |
| `SELECT version() AS v` | `PostgreSQL 17.7 on x86_64-pc-linux-musl, compiled by gcc (Alpine 14.2.0) 14.2.0, 64-bit` |
| `SELECT current_database(), current_schema()` | `ontology` / `public` |
| `SELECT schema_name FROM information_schema.schemata` | 14 个：`bdm_customer`、`bdm_customer_sd`、`item`、`item_pd`、`mit_base`、`ods`、`ontology_import`、`ontology_qianjiang`、`ontology_wtttest`、`po`、`public` + 3 个系统 schema |
| 各 schema 表/视图数量 | `ods` 40、`ontology_wtttest` 26、`po` 19、`mit_base` 4、`item` 2、`bdm_customer` 1；**`ontology_qianjiang` 0、`ontology_import` 0、`public` 0** |

结论：**同一个 PG 库 `ontology` 承载所有本体库**，每个本体库对应一个 **schema**
（`ontology_qianjiang`、`ontology_wtttest`、…）；业务数据在 `po` / `ods` / `item` / `mit_base`
等 schema，本体库 schema 里是**视图**。

### 1.2 本体库目录（`GET /system/manager/ontology-repository?page=1&size=50`）

| 环境 | 目录内容 | 字段形态 |
| --- | --- | --- |
| pdt-dev | `total=4`：**12 钱江本体库-勿动**（`qianjiang` / `ontology_qianjiang`，创建于 `2026-09-22T14:17:14+08:00`）、8 导入工具自测（`import` / `ontology_import`）、6 测试导入（`wtttest` / `ontology_wtttest`）、5 开发本体库-PG（`dev_pg` / `ontology_wtttest`，描述 "PG view create test for ontology_dev"） | **只有 `currentDatabase`**，无 `dorisDatabase` |
| demo2 | `total=1`：1 ECore 本体库-勿动（`ecore` / `ontology_ecore`） | 同上，只有 `currentDatabase` |

`http://pdt-dev.eimos.com/api/gateway2/ontology` 与内部地址 `http://172.16.5.181:30834`
返回**完全相同的目录**（同一后端），因此"生产 MetaERP 选项"与 pdt-dev 是同一环境。

**关键变化：pdt-dev 已不存在本体库 3。** 仓库与文档长期使用的
`ONTOLOGY_REPOSITORY_ID=3` 在当前 pdt-dev 目录中查不到；按
`bi_agent/web/app.py:578-587` 的启动校验，**用 pdt-dev 重启会直接
`RuntimeError: 远程本体库 3 不在可用目录中`**。（当前本机 8765 实例是旧进程，运行态仍是 3，
目录由 TTL 缓存刷新，因此页面还能显示 12/8/6/5。）

### 1.3 必然失败的 SQL（网关统一回 `code 500` / `系统繁忙，请稍后再试`）

| SQL 特征 | 探针 | 结果 |
| --- | --- | --- |
| MySQL 行数估算列 | `SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema='ontology_qianjiang'` | **500**（PG 的 `information_schema.tables` 无 `table_rows`） |
| MySQL 主键列 | `SELECT column_name, data_type, is_nullable, column_key FROM information_schema.columns ...` | **500**（PG 无 `column_key`） |
| 反引号引用 | ``SELECT 1 AS one FROM `ontology_qianjiang`.`x` LIMIT 1`` | **500** |
| MySQL 分页 | `SELECT 1 AS a LIMIT 0,1` | **500**（PG 只认 `LIMIT n OFFSET m`） |
| MySQL 空值函数 | `SELECT IFNULL(NULL,1) AS a` | **500**（PG 需 `COALESCE`） |
| 不带 schema 限定的表名 | `SELECT count(*) AS n FROM poheader` | **500**（`search_path` 不含本体库 schema） |
| 旧 CamelCase 表名 | `SELECT count(*) AS camel FROM ontology_wtttest."PoAllocationRelation"` | **500**（新库全部小写） |

### 1.4 网关只读白名单（回 `code 400`）

| 探针 | 结果 |
| --- | --- |
| `WITH t AS (SELECT 1 AS a) SELECT a FROM t` | `第 1 条语句校验失败：仅允许以 SELECT 或 MATCH 开头的只读查询` |
| `EXPLAIN SELECT 1` | 同上 400 |
| `SHOW search_path` | 同上 400 |

即：**网关只放行 `SELECT` / `MATCH` 开头的单条只读语句**。

### 1.5 可用但语义变了

| 探针 | 结果 |
| --- | --- |
| `SELECT count(*) AS n FROM ontology_wtttest.poheader` | `667`（schema 限定可用，视图有数据） |
| `SELECT date_trunc('month', now()) AS m` | `2026-09-01 00:00:00`（PG 函数） |
| `information_schema.views`（`ontology_wtttest`） | 26 个对象**全是视图**；`pg_class.reltuples` 对它们全是 `-1`（PG 对视图无行数估算） |
| `SELECT 1830513348099637200::bigint, 12.345::numeric(10,3), true, now(), NULL::text` | 正常；`bigint` 以 JSON number 返回，`timestamp` 以 `"YYYY-MM-DD HH:MM:SS"` 文本返回 |
| 2000 行 `SELECT` | 原样返回 2000 行（**网关不做行数截断**，截断仍由 Agent 侧 `MAX_RESULT_ROWS=1000` / 工具 `limit` 负责） |

### 1.6 仓库身份与隔离

| 探针 | 结果 |
| --- | --- |
| `X-Ontology-Repository-Id: 999` | `400 本体库不存在: id=999` —— repo 头**会校验** |
| 带 repo 12 查 `ontology_wtttest.poheader` | 仍返回 667 —— **数据面不按 repository 隔离 schema** |
| 两个查数出口 `/agent/doris/query` 与 `/api/v1/analysis/data/query` | 都可用，且是同一 PG 后端（方言失败表现完全一致） |

### 1.7 钱江（id 12）专项

| 探针 | 结果 |
| --- | --- |
| `information_schema.tables` / `views` where `table_schema='ontology_qianjiang'` | **0 表 / 0 视图** |
| `POST /api/v1/analysis/meta/query` + `SELECT code, name FROM BusinessObject LIMIT 3` | **500**（同一查询在 repo 1 / 6 / 8 / 5 均正常返回 `BO0001 Supplier` 等） |

结论：钱江本体库的业务 schema 为空、元数据库（`ontology_qianjiang_all_meta`）不可用，
语义检索 / 元数据 / 指标 / FactQuery **目前全部无数据可查**。

### 1.8 复现命令（只读）

```bash
BASE=http://pdt-dev.eimos.com/api/gateway2/ontology
H1='X-App-Id: ApTH1EHKdRk58WhDQB'
H2='X-Ontology-Repository-Id: 12'

# 目录
curl -s -H "$H1" "$BASE/system/manager/ontology-repository?page=1&size=50"

# 引擎
curl -s -X POST -H 'Content-Type: application/json' -H "$H1" -H "$H2" \
  -d '{"sql":"SELECT version() AS v"}' "$BASE/agent/doris/query"

# 方言：MySQL 行数估算列在 PG 下必然报错
curl -s -X POST -H 'Content-Type: application/json' -H "$H1" -H "$H2" \
  --data-binary @- "$BASE/agent/doris/query" <<'JSON'
{"sql":"SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema='ontology_qianjiang'"}
JSON
```

---

## 2. 对现有连接的影响

### 2.1 不需要改（现状已兼容）

| 面 | 说明 |
| --- | --- |
| 传输 | 仍是 HTTP 网关，两个出口都在线（`bi_agent/tools/sql_tools.py:179-181`） |
| 请求头 | `X-Ontology-Repository-Id` / `X-App-Id` / `Authorization` 契约不变（`sql_tools.py:183-194`） |
| 请求体 | 旧 `{"sql":…}` 与新 `{"analysisConfig":{"sql":…},"commonConfig":{}}` 双栈共存（`sql_tools.py:200-205`） |
| 响应形态 | 旧 `data.rows` 与新 `data.result.rows` / `columns[].identifierCode` 都能解析（`sql_tools.py:215-255`） |
| 目录字段 | 已同时接受 `dorisDatabase` / `currentDatabase`（`bi_agent/web/app.py:1393`、`bi_agent/ontology/remote.py:85`） |
| `库.表` 限定思路 | PG 下就是 `schema.table`，语义仍然成立（`sql_tools.py:395`、`:500-501`） |
| 只读与行数上限 | 只读白名单与 `MAX_RESULT_ROWS=1000` 仍适用 |

### 2.2 直接失效

| 编号 | 位置 | 问题 |
| --- | --- | --- |
| B1 | `bi_agent/tools/sql_tools.py:485-505`（`_list_tables_doris`，SQL 在 `:491`） | 依赖 `information_schema.tables.table_rows`，PG 无该列 → `ListTables` 必 500 |
| B2 | `bi_agent/tools/sql_tools.py:567-580`（`_describe_table_doris`，SQL 在 `:570`） | 依赖 `information_schema.columns.column_key`，PG 无该列 → `DescribeTable` 必 500，主键标记永远拿不到 |
| B3 | `bi_agent/tools/sql_tools.py:388-397`（`SQL_RUN_SCHEMA.description`） | 明确写 "Apache Doris (MySQL protocol)"、"standard MySQL/ANSI SQL"，会持续诱导 LLM 生成反引号 / `LIMIT a,b` / `IFNULL` |
| B4 | `bi_agent/tools/sql_tools.py:70-79`、`:99`、`:255-275` | 直连分支只支持 `jdbc:mysql://` + `pymysql`；PG 是 `jdbc:postgresql://host:5432/db`，解析与驱动都不成立 |
| B5 | 环境注入与文档默认值（`.env.example`、`DEPLOYMENT.md:109-175`、`Dockerfile`） | `ONTOLOGY_REPOSITORY_ID=3`、`DORIS_DATABASE=ontology_demometaerp_scm_po` 在 pdt-dev 已不存在（详见 §3.1） |

### 2.3 语义变化（不报错但会答错）

| 编号 | 说明 |
| --- | --- |
| C1 | `currentDatabase` 现在是 PG 的 **schema**，不再是 database；一个 PG 库 `ontology` 承载全部本体库 |
| C2 | 物理表 / 视图名**全部小写**，旧 CamelCase（`PoAllocationRelation`）已不可解析 |
| C3 | 必须始终 schema 限定；网关 `search_path` 是 `public`，不含本体库 schema |
| C4 | 行数估算要换源：视图的 `pg_class.reltuples = -1`，`pg_stat_user_tables.n_live_tup` 才可用（或干脆不显示估算） |
| C5 | 业务数据分布：本体库 schema 里是视图，真实数据在 `po` / `ods` / `item` / `mit_base` / `bdm_customer` |

### 2.4 网关白名单更严

Agent 侧 `_ALLOWED_LEAD`（`bi_agent/tools/sql_tools.py:289`）放行 `select|with|pragma|explain`，
网关只放行 `SELECT|MATCH`。结果是 **CTE（`WITH`）、`EXPLAIN`、`PRAGMA` 本地能过、线上必 400**，
模型一旦选择 CTE 就会拿到"系统繁忙"这类无法自我纠正的报错。

---

## 3. 需要改什么（本轮不执行，仅登记）

### 3.1 环境与配置

| 编号 | 事项 |
| --- | --- |
| E1 | pdt-dev 的 `ONTOLOGY_REPOSITORY_ID` 必须改为目录中真实存在的库（钱江 = 12），否则重启即启动失败（`bi_agent/web/app.py:578-587`） |
| E2 | `DORIS_DATABASE` 按所选本体库的 `currentDatabase` 注入（PG 下是 schema 名，如 `ontology_qianjiang`） |
| E3 | 建议同步更新 `.env.example`、`DEPLOYMENT.md:109-175`、`Dockerfile` 的 PDT 取值说明（"Doris 库"→"当前分析引擎库 / schema"） |

### 3.2 P0：不修就查不了数

| 编号 | 位置 | 最小改动 |
| --- | --- | --- |
| P0-1 | `sql_tools.py:491` | `ListTables` 改为 `SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = '<schema>' ORDER BY table_name`；行数估算改用 `pg_stat_user_tables.n_live_tup`，或直接去掉估算列 |
| P0-2 | `sql_tools.py:570` | `DescribeTable` 去掉 `column_key`；主键改查 `information_schema.table_constraints` + `key_column_usage`（或 `pg_index`）；`is_nullable` 在 PG 仍是 `YES/NO`，可沿用 |
| P0-3 | `sql_tools.py:388-397`、`:500-501`、`:556` | 提示词从 MySQL 方言改为 PG 方言：字符串用单引号、标识符必要时双引号、分页 `LIMIT n OFFSET m`、空值 `COALESCE`、无 `PRAGMA` |

### 3.3 P1：不修会误报或误判

| 编号 | 位置 | 事项 |
| --- | --- | --- |
| P1-1 | `sql_tools.py:70-79`、`:255-275` | 直连分支加 PG JDBC 解析 + `psycopg`（或明确只支持 HTTP 网关，禁掉直连） |
| P1-2 | `sql_tools.py:289` 与网关白名单 | 让本地校验与网关一致：要么禁 CTE / `EXPLAIN` / `PRAGMA`，要么在提示里只宣传 `SELECT` |
| P1-3 | 命名与文案 | `DorisHttpConn` / `DorisApiError` / `DORIS_*` / `CHATBI_DORIS_CONCURRENCY`（`bi_agent/concurrency.py:122`、`:894`）/ `__doris_api__`、`__doris_repository__`（`bi_agent/web/app.py:844-846`）/ 前端 "API · Doris 实时查询"（`frontend/src/runtime.js:2335-2353`）/ 错误文案 "未配置 dorisDatabase"（`app.py:582`、`:2092`）、"远程本体库必须与其 dorisDatabase 作为一个原子数据源切换"（`app.py:2190`）。建议**保留旧标识做兼容**，只改用户可见文案 |

### 3.4 P2：验证与隔离

| 编号 | 事项 |
| --- | --- |
| P2-1 | 数据面无 repository 隔离（§1.6）：钱江这类多租户场景需在网关侧按 repository 限定 schema 或授权，否则 SQL 可跨 schema 取数 |
| P2-2 | 回归面：`tests/test_docker_defaults_and_local_secrets.py`、`tests/test_environment_scoped_ontology_and_unused_session.py` 中的 Doris 取值 / URL 断言需要随环境取值一起复核 |
| P2-3 | 交付后的验证清单：`SELECT 1`、schema 限定的 `information_schema.tables` / `columns`、`date_trunc`、`LIMIT n OFFSET m` 各跑通；`ListTables` / `DescribeTable` 在 PDT 上不再 500 |

---

## 4. 钱江功能当前的阻塞（按优先级）

1. **业务 schema 为空**：`ontology_qianjiang` 无表无视图 → `ListTables` 无内容、FactQuery 无表可查。
2. **元数据库不可用**：对 repo 12 的 `meta/query` 返回 500 → 语义检索 / 元数据 / 指标查询全部不可用。
3. **P0-1 / P0-2**：即使后续灌了数据，列表与结构查询仍会 500。
4. 与方言无关，属"数据与元数据未落地 + 代码未适配"的叠加。

---

## 5. 未决问题与风险

| 项 | 说明 |
| --- | --- |
| 钱江元数据库 500 的根因 | 网关只回通用错误，未能区分"库未建 / 连接未配 / 权限不足" |
| `X-Ontology-Repository-Id` 是否影响 `search_path` | 实测未限定名的查询一律失败，倾向"不影响"；需网关侧确认 |
| 两个查数出口的最终去留 | 旧 `/agent/doris/query` 名字带 Doris，契约文档（`API/本体MAL层API.md:3801`）尚未更新 |
| 目录字段 `currentDatabase` 的兼容期 | 当前兼容良好，但 `dorisDatabase` 作为主键名散落在 `app.py` 多处，重命名风险需评估 |
| 数据面跨 schema 可见 | 见 P2-1，属隔离与合规问题，非功能缺陷 |

---

## 6. 本轮范围声明

- **只新增本记录文档**，不修改任何生产代码、配置、部署文档、测试与前端；不创建红测。
- 未部署、未重启服务、未创建 MR / tag / Release、未改动版本号、未读写真凭据。
- 实测全部为只读（目录 `GET` + 只读 `SELECT`），未对任何本体库执行写入、删除或重置。
