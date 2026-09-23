# PDT 数据湖切 PG 后的端到端流程走查 Spec（钱江本体库）

> 来源：2026-09-23 按"用户可执行的方式"对 PDT 环境做的一次**只读端到端走查**——用生产代码
> （`build_source_executors` / `RemoteOntologyClient` / `GET`·`PUT /api/sources` /
> `configure()`）依次走完「打开设置页 → 选钱江 → 提问 → 语义检索 → 指标查询 → 回退手写 SQL
> → 列表/结构 → 出图」这条链路，记录每一步的真实产出。
> 红测：`tests/test_pdt_pg_lake_flow_red.py`
>
> 走查期间对 PDT 只做两类调用：`GET` 目录接口与只读 `SELECT`；未写入、未删除、未重置、
> 未读取真实凭据、未部署、未重启服务。
>
> 走查入口说明：当天 `pdt-dev.eimos.com` 在本机解析失败（NXDOMAIN），内部地址
> `172.16.5.181:30834` 返回**完全相同**的目录与数据，因此走查用内部地址完成；两者是同一后端。

---

## 0. 一句话结论

链路本身（设置页、原子切换、策略路由）是通的，**卡在"最后一段"**：数据面与元数据面都在
PG 引擎上，而 Agent 侧仍按 Doris/MySQL 说话——两条元数据 SQL 必 500、手写 SQL 提示词教的是
MySQL 方言；更严重的是**传输故障被写成业务否定**（"本体库里没有这个对象"），以及**网关的
错误正文被丢弃**，于是用户既拿不到数据，也拿不到可判断的原因。

---

## 1. 走查逐环节实录

| # | 用户动作 / 系统动作 | 生产入口 | 实测结果 |
| --- | --- | --- | --- |
| 1 | 打开「数据源设置」 | `GET /api/sources` | ✅ 正常。`remote_repositories` = 12 钱江本体库-勿动 / 8 导入工具自测 / 6 测试导入 / 5 开发本体库-PG；`ontology.active = __metaerp_repository__:12`；`database.options` 与本体库成对，`database.active = __doris_repository__:12`；`doris.database = ontology_qianjiang` |
| 2 | 选钱江（本体库 + 数据库） | `PUT /api/sources` | ✅ 正常。`changed=[]`（已是该源）；切到 12 后 `repo=12 / ns=qianjiang / db=ontology_qianjiang / use_doris=True`，本体库与数据库始终成对 |
| 3 | 选「MetaERP（生产）」 | `PUT /api/sources` | ✅ 正常。解析成当前配置的仓库 ID（12），不产生跨源错配 |
| 4 | 提问「统计钱江2026年各月采购订单金额」 | `build_cognitive_policy_decision` | ✅ 路由正确：`mode=FACT_QUERY`→`required_tools=[Ontology-MetricQuery]`；本体类问题走 `ONTOLOGY_LOOKUP`→`Ontology-SemanticQuery` |
| 5 | 指标优先查询 | `Ontology-MetricQuery` → `POST /api/v1/analysis/data/query` | ❌ `HTTP 500 … {"success":false,"code":500,"msg":"系统繁忙，请稍后再试"}`（钱江元数据库未就绪）。**该工具报错是诚实的**，并提示回落 FactQuery |
| 6 | 对象消歧（回退前找对象） | `Ontology-SemanticQuery` → meta/query + resolve-object | ❌ **假否定**：后端 500 时输出 `Ontology-SemanticQuery: no remote matches for '采购订单'.`——把"后端坏了"写成"本体库里没有" |
| 7 | 查对象详情 | `Ontology-EntityDescribe` | ❌ **假否定**：`Ontology-EntityDescribe: no remote match for 'BO0005'.`（同一 500） |
| 8 | 图库锚点准备 | `Ontology-GraphContext` | ❌ **假否定**：`Ontology-GraphContext: no remote anchor for '采购订单'.`（同一 500） |
| 9 | 对照工具（同一故障） | `ListBusinessObjects` / `MetricCalculation` / `TermDisambiguate` / `RelationQuery` / `GraphExpand` | ✅ 均如实回 `remote error: HTTP 500 …`。**同一故障在 6 个工具里被表述成两种互相矛盾的事实** |
| 10 | 手写 SQL 兜底 | `Ontology-FactQuery` → `/agent/doris/query` | ❌ 只回 `HTTP Error 500: Server Error`；网关正文（含真实 PG 报错）被丢弃，模型/用户无法区分"语法错 / 表不存在 / 引擎不支持" |
| 11 | 列表与结构 | `ListTables` / `DescribeTable` | ❌ 两条 SQL 仍是 MySQL 方言（`information_schema.tables.table_rows`、`information_schema.columns.column_key`），PG 必 500 |
| 12 | 启动/重启 | `configure()` + `ONTOLOGY_REPOSITORY_ID` | ❌ `ONTOLOGY_REPOSITORY_ID=3` → `RuntimeError: 远程本体库 3 不在可用目录中`；改为 12 后正常启动 |
| 13 | 钱江数据本身 | `information_schema` / `meta/query` | ❌ `ontology_qianjiang` **0 表 0 视图**、元数据库 500 —— 链路通也取不到数 |

---

## 2. 发现的流程/逻辑问题

### F1（P0）元数据 SQL 仍是 MySQL 方言，PG 引擎必然拒绝

- `ListTables`：`SELECT table_name, table_rows FROM information_schema.tables …`
  （`bi_agent/tools/sql_tools.py:491`）——PG 的 `information_schema.tables` 没有 `table_rows`。
- `DescribeTable`：`SELECT column_name, data_type, is_nullable, column_key FROM information_schema.columns …`
  （`bi_agent/tools/sql_tools.py:570`）——PG 没有 `column_key`，主键标记永远拿不到。
- 实测（PG 17.7 网关）：两条 SQL 都返回 `code 500 系统繁忙`；`limit 0,1`、反引号、`IFNULL` 同样被拒。

影响：**取数链路的自助环节被整体掐断**。模型先 `ListTables` 摸清 `schema.table`，失败后既不知道
表名也无法核对字段，只能盲写 SQL。

### F2（P0）传输故障被写成业务否定（假否定）

- `_candidate_results`（`bi_agent/tools/remote_ontology_tools.py:315-316`）与
  `_graph_anchor_candidates`（`:463-464`）用 `except OntologyApiError: continue` **静默吞掉**
  逐类型检索失败；
- 上层在结果为空时直接断言业务事实：`no remote matches for …`（`:779`）、
  `no remote match for …`（`:888`）、`no remote anchor for …`（`:930`），
  且**不带任何降级说明**（`_with_degraded_note` 只在"有命中"分支才调用）。

影响：用户得到的是一句**无法被证伪的业务结论**（"本体库里没有采购订单"），而不是"后端不可用"。
这与仓库既有的真实性口径（`docs/specs/analytics-causal-and-proxy-truthfulness.md`）直接冲突，
且会导致 Agent 基于不存在的否定结论继续推理。

### F3（P0）网关错误正文被丢弃，错误不可诊断

`bi_agent/tools/sql_tools.py:215-216` 用 `except Exception` 统一包装：HTTP 500 由 `urlopen`
抛 `HTTPError`，其**响应正文从未被读取**，最终只留下 `HTTP Error 500: Server Error`。
对照 `bi_agent/ontology/remote.py` 的元数据客户端（会带出
`HTTP 500 … {"success":false,"code":500,"msg":"…"}`），同一次故障两种可读性。

影响：模型无法自我纠正（PG 的真实报错如 `relation "x" does not exist` 恰好是最有价值的线索），
用户也无法判断是自己问错了还是环境坏了。

### F4（P1）手写 SQL 的提示词仍在教 MySQL 方言

`SQL_RUN_SCHEMA` 描述（`bi_agent/tools/sql_tools.py:388-397`）："Apache Doris (MySQL protocol)"、
"use standard MySQL/ANSI SQL"，并示例 `database.table`。实测 PG 网关拒绝反引号、`LIMIT a,b`、
`IFNULL`。提示词与实际引擎不一致，会**稳定地诱导模型生成必然失败的 SQL**。

### F5（P1）本地只读白名单与网关白名单不一致

`_ALLOWED_LEAD`（`sql_tools.py:289`）放行 `SELECT | WITH | PRAGMA | EXPLAIN`；网关只接受
`SELECT | MATCH`。实测 `WITH …`、`EXPLAIN …`、`SHOW …` 一律 `code 400`。
结果是"本地校验通过、线上必失败"，且失败信息同样被 F3 吞掉。

### F6（P1）直连分支不支持 PG

`_parse_jdbc_mysql`（`sql_tools.py:70-79`）只认 `jdbc:mysql://`，驱动固定 `pymysql`
（`:255-263`）。切到 PG 后直连路径（`jdbc:postgresql://host:5432/db` + psycopg）完全不可用。
当前 Web 主链路走 HTTP 网关，因此不是 P0，但会误导数据源设置页的 JDBC 表单。

### F7（运维，非代码缺陷）PDT 本体库 ID 已变更

PDT 目录现为 12 / 8 / 6 / 5，**旧值 3 已不存在**；`configure()` 会 fail-fast
（`bi_agent/web/app.py:578-587`），实测 `RuntimeError: 远程本体库 3 不在可用目录中`。
代码行为正确，问题在环境注入与文档默认值（`.env.example`、`DEPLOYMENT.md:109-175`）。

### F8（环境）钱江本体库当前没有可查数据

`ontology_qianjiang` 0 表 0 视图，repo 12 的 `meta/query` 返回 500。**F1/F2 修复后链路依然取不到数**，
需要本体侧先完成建模/视图落地。

---

## 3. 目标契约

| 编号 | 契约 | 对应问题 |
| --- | --- | --- |
| R1 | `ListTables` 在 PG 网关上必须成功返回表清单：**不得发送 `information_schema.tables.table_rows`**（行数估算改用 PG 可用来源或直接省略） | F1 |
| R2 | `DescribeTable` 在 PG 网关上必须成功返回列清单：**不得发送 `information_schema.columns.column_key`**（主键改由 `table_constraints` / `key_column_usage` 判定） | F1 |
| R3 | 检索后端不可用时，`Ontology-SemanticQuery` **不得输出 `no remote matches`**；必须给出显式的错误/降级说明 | F2 |
| R4 | 同上，`Ontology-EntityDescribe` 不得输出 `no remote match` | F2 |
| R5 | 同上，`Ontology-GraphContext` 不得输出 `no remote anchor` | F2 |
| R6 | 网关返回 4xx/5xx 时，工具输出必须包含网关响应正文里的 `msg`（SQL 面与元数据面口径一致） | F3 |
| R7 | `Ontology-FactQuery` 的工具描述必须描述**实际引擎方言**（PG），不得再向模型声明 MySQL | F4 |
| G1 | （守卫）目录只返回 `currentDatabase`（PG 形态）时，钱江仍必须出现在设置页、并保持本体库/数据库成对可选 | §1 步骤 1-3 |
| G2 | （守卫）后端正常时，语义检索必须照常返回命中——修 R3/R4/R5 不得把正常路径也变成报错 | §1 步骤 6 |

---

## 4. 范围与非目标

**范围内**：`bi_agent/tools/sql_tools.py`（两条元数据 SQL、错误正文、工具描述）、
`bi_agent/tools/remote_ontology_tools.py`（假否定与降级说明）。

**非目标（本轮不做）**：

* 不改本体服务/网关（含其 500 语义、白名单、repository→schema 隔离）；
* 不改 `analysis_policy` 路由、SOP 语义、评测集与前端交互；
* 不改数据面跨 schema 可见性（属网关侧隔离与合规，另开需求）；
* 不清理遗留的 `Doris*` 命名（`DorisHttpConn` / `DORIS_*` / `__doris_repository__`）——
  保留旧标识做兼容，只在 R7 收敛模型可见文案；
* 不落钱江的建模/视图（属本体侧，F8）。

---

## 5. 验收

1. `tests/test_pdt_pg_lake_flow_red.py` 的 R1–R7 由红转绿——以本 Spec 定稿时的生产代码
   （`d67a723`，用 `git worktree` 独立检出后实测，不受并行改动影响）为准，当前为
   **8 failed / 4 passed**：红的是 R1、R2、R3、R4、R5、R6a、R6b、R7；
   绿的是 G1、G2、G2b 与 R7 的第二条（元数据工具说明已不含 MySQL）；
2. 守卫（G1 / G2 / G2b）在实现前后都必须保持绿，防止"更严格的报错"误伤正常路径；
3. 红测全部在 loopback 假网关 + 生产代码上运行：离线、确定性、不读真实凭据、不连真实服务；
4. 既有门禁不劣化：`tests/test_ontology_mal_contract_red.py` 的契约用例保持通过；
5. 全量 `pytest -q tests` 相对改动前无新增失败（实测基线：**1224 passed / 25 skipped /
   1042 subtests passed，8 failed**，8 条 failed 全部来自本 Spec 的红测
   `tests/test_pdt_pg_lake_flow_red.py`，文件之外 0 failed；本文件写就时并行的
   `tests/test_conversation_trash_red.py` 已由 `d67a723` 的实现转绿，故不再计入基线）。

---

## 6. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 改为"不可用时报错"后，原本能出答案的场景变成报错 | G2 守卫 + 只在确认层 `unavailable` 且候选为空时升级为错误 |
| 元数据 SQL 换成 PG 后，将来回退到 Doris/MySQL 环境会失败 | 由 `api_url`/引擎能力决定方言，或在 `DorisHttpConn` 记录引擎类型；本 Spec 只要求"对 PG 网关可用"，不要求同时支持两种 |
| 错误正文回传可能带出内部信息 | 只回传网关 `msg` 字段（已是给用户看的业务文案），不拼接响应头/连接串 |
| 回滚 | 还原 `_list_tables_doris` / `_describe_table_doris` 的 SQL、`_candidate_results` 的静默 catch 与错误包装；红测文件保留为回归 |

---

## 7. 残留观察（本轮不处理，仅记录）

| 观察 | 位置 | 说明 |
| --- | --- | --- |
| 数据面不按 repository 隔离 | 网关 `/agent/doris/query` | 带 repo 12 仍可读其他 schema 的表；多租户场景需网关侧限制 |
| 旧出口命名与文档不一致 | `API/本体MAL层API.md:3801`、`sql_tools.py` | `/agent/doris/query` 名称仍带 Doris，文档未随 PG 更新 |
| 直连 JDBC 表单仍指向 MySQL | `bi_agent/web/app.py:139-152`、`frontend/src/runtime.js:2335-2353` | 见 F6 |
| 公网域名解析 | `pdt-dev.eimos.com` | 走查当天本机 NXDOMAIN，内部地址正常；非本仓库缺陷 |
