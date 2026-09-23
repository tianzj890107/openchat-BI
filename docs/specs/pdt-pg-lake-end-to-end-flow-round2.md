# PDT 数据湖切 PG 后的端到端流程走查 Spec（第二轮 · 钱江本体库）

> 来源：2026-09-23 在**第一轮修复落地后**（`689a152` + `813c5cf`）按"用户可以执行的方式"把
> 同一条链路（设置页 → 选钱江 → 提问 → 语义检索 → 指标查询 → 手写 SQL → 列表/结构 → 出图）
> 又只读走了一遍，记录每一步的真实产出与**新暴露**的问题。
> 第一轮 Spec：`docs/specs/pdt-pg-lake-end-to-end-flow.md`
> 红测：`tests/test_pdt_pg_lake_flow_round2_red.py`
>
> 对 PDT 只做两类调用：目录 `GET` 与只读 `SELECT`；未写入、未删除、未重置、未读取真实凭据、
> 未部署、未重启服务。当天 `pdt-dev.eimos.com` 在本机解析到 `172.16.5.90`，但该地址与
> `172.16.5.90:30834` 均不可达，实际可用入口仍是内部地址 `172.16.5.181:30834`。

---

## 0. 一句话结论

第一轮的三个 P0 修好了，本轮的 8 个问题也都不是它们。**新问题集中在三处**：

1. **修 F2 时把"部分降级"过升级成故障**——只有 tree 面失败、列表面正常回答"没有这个对象"，
   也会被报成 `remote error`（假故障，恰是 F2 的镜像）；
2. **模型可见文案与已声明的 PG 引擎自相矛盾**——错误行仍写 `(Doris)`，还把内部 API URL
   拼进用户可见正文（违反第一轮 §6 的"只回传 msg"约定）；
3. **本地校验与网关白名单仍不一致**——`WITH` / `EXPLAIN` 本地放行、网关 400，用户拿到的是
   一句"仅允许以 SELECT 或 MATCH 开头"，而他并不知道本地在放行。

另有两条可用性缺陷：`ListTables` 表头出现占位主机 `HTTP API:0` 且 0 表时没有显式空态；
`DescribeTable` 的"未找到"答复丢掉了用户传入的 schema 限定名。钱江本体库依然 0 表 0 视图。

---

## 1. 第二轮逐环节实录（2026-09-23，只读实测）

| # | 用户动作 / 系统动作 | 生产入口 | 实测结果（第一轮对比） |
| --- | --- | --- | --- |
| 1 | 打开「数据源设置」 | `GET /api/sources` | ✅ 正常。目录 12 钱江本体库-勿动 / 8 导入工具自测 / 6 测试导入 / 5 开发本体库-PG；`database.options` 与本体库成对（`__doris_repository__:12/8/6/5`） |
| 2 | 选钱江（本体库 + 数据库） | `PUT /api/sources` | ✅ 正常。`repo=12 / ns=qianjiang / db=ontology_qianjiang / use_doris=True` |
| 3 | 提问「统计钱江2026年各月采购订单金额」等 | `build_cognitive_policy_decision` | ✅ 路由正确：`FACT_QUERY→[Ontology-MetricQuery]`、`ONTOLOGY_LOOKUP→[Ontology-SemanticQuery]`、`DIAGNOSTIC_ANALYSIS→[Ontology-MetricQuery]` |
| 4 | 指标查询 | `Ontology-MetricQuery` | ❌ `remote error: HTTP 500 … 系统繁忙`（钱江元数据库未就绪）+「可回退 Ontology-FactQuery」提示；不传 `metric_codes` 时回 `metric_codes is empty.`。**与第一轮一致，诚实** |
| 5 | 对象消歧 | `Ontology-SemanticQuery` | ✅ **第一轮 P0 已修**：后端 500 时回 `remote error: HTTP 500 … {"success":false,…}`，不再是 `no remote matches` |
| 6 | 查对象详情 | `Ontology-EntityDescribe` | ✅ 同上，不再是 `no remote match` |
| 7 | 图库锚点 | `Ontology-GraphContext` | ✅ 同上，不再是 `no remote anchor` |
| 8 | 手写 SQL（表不存在） | `Ontology-FactQuery` | ⚠️ **第一轮 P0 半修**：网关正文已回传（`HTTP 500 系统繁忙，请稍后再试`），但**错误行自称 Doris 并把内部 API URL 拼进正文**（N2/N3）；网关侧仍把真实 PG 报错折叠成"系统繁忙" |
| 9 | 手写 SQL（`WITH` / `EXPLAIN`） | `Ontology-FactQuery` | ❌ 本地放行、网关 `400 第 1 条语句校验失败：仅允许以 SELECT 或 MATCH 开头…`（N4，第一轮 F5 未收敛） |
| 10 | 手写 SQL（`SELECT … information_schema` 只读盘点） | `Ontology-FactQuery` | ✅ 正常出表；`ontology_qianjiang` 在 `information_schema.schemata` 中存在，但表/视图 0 行 |
| 11 | 列表 | `ListTables` | ❌ 不再 500（第一轮 P0 已修），但表头是 `# Tables in HTTP API:0/ontology_qianjiang (0)`（N1/N5） |
| 12 | 结构 | `DescribeTable` | ❌ 不再 500，但 `DescribeTable: table 'poheader' not found or has no columns.` 丢掉了传入的 schema 限定名（N6） |
| 13 | 启动/重启 | `configure()` + `ONTOLOGY_REPOSITORY_ID` | repo 12 正常启动；repo 3 仍 fail-fast（`RuntimeError: 远程本体库 3 不在可用目录中`，第一轮 F7 未变） |
| 14 | 钱江数据本身 | `information_schema` / `meta/query` | ❌ schema 存在但 **0 表 0 视图**、`meta/query` 500（第一轮 F8 未变） |

---

## 2. 本轮发现的问题

### N1（P1，新）部分降级被过升级成"环境故障"

`_candidate_results`（`bi_agent/tools/remote_ontology_tools.py:321`）与
`_graph_anchor_candidates`（`:470`）的判据是 **"没有命中 + 有错误"** 就抛 `OntologyApiError`：

```python
if not found and errors:
    raise errors[0]
```

但 `_TREE_SEARCH_TYPES = ("Indicator", "Dimension")` 的 tree 面失败会**回退到 `_search_type`**，
而这个回退（`list_objects`，覆盖全部候选类型）**已经成功回答"没有该对象"**。此时 `errors`
里仍留着那次 tree 失败，于是正确结论被丢弃、报成故障。

实测（loopback 假网关：确认层 500 + tree 面 500 + 列表面 200 空）：

```
Ontology-SemanticQuery remote error: HTTP 500 from /api/v1/analysis/meta/query: {…"系统繁忙"…}
Ontology-EntityDescribe  remote error: HTTP 500 from /api/v1/analysis/meta/query: {…"系统繁忙"…}
```

影响：用户问一个**确实不存在**的对象，得到的是"环境坏了"。这是第一轮 F2（假否定）的镜像——
**假故障**，同样阻止模型收敛答案，且会误导用户去排查环境。

### N2（P1，残留）错误文案仍把当前引擎称作 Doris

`Ontology-FactQuery (Doris) error:`、`Doris HTTP API 请求失败`、`ListTables (Doris) error:`
（`sql_tools.py:246`、`:491`、`:583` 等）都随工具输出进入模型上下文，而同一个工具的描述刚被
R7 改成"engine: PostgreSQL"。模型同时被告知"引擎是 PostgreSQL"和"Doris 请求失败"。

实测：`Ontology-FactQuery (Doris) error: Doris HTTP API 请求失败 (…)`。

### N3（P1，新）错误正文拼接了内部 API URL（连接串）

`sql_tools.py:246` 把 `conn.api_url` 拼进异常文案：

```
Doris HTTP API 请求失败 (http://172.16.5.181:30834/agent/doris/query): HTTP 500 系统繁忙…
```

第一轮 §6 明确约定"**只回传网关 msg 字段，不拼接响应头/连接串**"。这既是内部拓扑外泄
（IP + 端口 + 内部路径回显给模型与用户），也是潜在凭据外泄——若数据源用
`http://user:pass@host/...` 形态配置，密码会直接进对话。

### N4（P1，残留）本地只读白名单与网关白名单仍不一致

`_ALLOWED_LEAD`（`sql_tools.py:326`）放行 `SELECT|WITH|PRAGMA|EXPLAIN`，网关只接受
`SELECT|MATCH`。`PRAGMA` 已在网关分支单独拦住（"PRAGMA is SQLite-only"），但
`WITH` / `EXPLAIN` 仍原样送出。实测：

```
SQL: WITH t AS (SELECT 1 AS a) SELECT a FROM t   -> HTTP 400 仅允许以 SELECT 或 MATCH 开头…
SQL: EXPLAIN SELECT 1                            -> HTTP 400 仅允许以 SELECT 或 MATCH 开头…
```

影响：模型据本工具描述（"standard PostgreSQL (ANSI) SQL"）完全有理由写 CTE；本地校验通过
让它以为语句合法，失败信息又是网关的通用校验文案，"本地放行、线上必失败"的往返白烧一轮。

### N5（P2，新）`ListTables` 表头用了占位主机，且 0 表没有显式空态

`_list_tables_doris` 用 `conn.host:conn.port` 做表头，而 HTTP 网关形态下这两个字段是占位符：

```
# Tables in HTTP API:0/ontology_qianjiang (0)
```

用户/模型看到的是"HTTP API:0"这个不存在的主机；0 张表这件事也只体现为一个 `(0)`，没有
一句可执行的结论（第一轮已指出：模型靠 `ListTables` 摸 `database.table`，摸不到就只能盲写）。

### N6（P2，新）`DescribeTable` 答复丢掉 schema 限定名

`_describe_table_doris` 收到 `ontology_qianjiang.poheader` 后按 `table` 字段渲染答复：

```
DescribeTable: table 'poheader' not found or has no columns.
```

而本工具的描述刚要求用户"必须 db 限定"。答复里回显完整限定名才能与调用方对账。

### 未变（第一轮登记、本轮复测）

- **F7（环境）**：`ONTOLOGY_REPOSITORY_ID=3` → `RuntimeError: 远程本体库 3 不在可用目录中`；
  12 正常。代码行为正确，属环境注入/文档默认值。
- **F8（环境）**：`ontology_qianjiang` schema 存在但 **0 表 0 视图**；repo 12 的 `meta/query`
  与 `data/query` 均 500。F1/F2 修好也暂无数据可查。

---

## 3. 目标契约（第二轮）

| 编号 | 契约 | 对应问题 |
| --- | --- | --- |
| R8 | **部分降级不得升级成故障**：只有当每个候选类型都**没有任何成功探针**时，才可以抛 `remote error`；只要还有成功探针（含 tree→本地回退）回答了"没有"，就必须回业务否定，并保留降级说明 | N1 |
| R9 | 网关错误输出只含网关 `msg`（可含 HTTP 状态码），**不得**包含 API URL / 主机端口 / 凭据 | N3 |
| R10 | 模型可见文案不得把当前引擎称作 Doris：`Ontology-FactQuery` 等错误前缀、`ListTables` 表头都要与 R7 已声明的 PostgreSQL 一致；`HTTP API:0` 之类占位符不得出现在输出里 | N2 / N5 |
| R11 | 网关模式下，**本地放行的语句必须是网关也会接受的**：`WITH` / `EXPLAIN`（`PRAGMA` 已拦）必须在本地被拒并说明原因，不得原样送到网关 | N4 |
| R12 | `ListTables` 必须**显式表达空态**（0 张表/视图时给出可执行结论），表头只陈述真实已知信息 | N5 |
| R13 | `DescribeTable` 的"未找到"答复必须回显用户传入的**完整限定名**（含 schema） | N6 |
| G3 | （守卫）后端正常时 `Ontology-SemanticQuery` 必须照常出命中——修 R8 不得把正常路径变成报错 | N1 |
| G4 | （守卫）收紧本地校验（R11）后，`SELECT` 仍必须送到网关 | N4 |
| G5 | （守卫）SQLite 本地模式下 `PRAGMA table_info(...)` 仍必须可用——R11 只针对网关后端 | N4 |
| G6 | （守卫）`_validate_sql` 的默认（未指定引擎）语义不变：`SELECT` / `PRAGMA table_info` 放行，`PRAGMA` 赋值与多语句拒绝（既有 `tests/test_regressions.py` 断言不得被推翻） | N4 |
| G7 | （守卫）本地拒绝时给出的原因必须可操作（提到 `SELECT`/`MATCH`/只读校验规则），不能只说一句 not permitted；红测文件内以 `test_r11b_...` 承载 | N4 |

---

## 4. 范围与非目标

**范围内**：`bi_agent/tools/sql_tools.py`（错误文案、URL 拼接、网关模式下的语句白名单、
`ListTables` 表头与空态、`DescribeTable` 名称回显）、
`bi_agent/tools/remote_ontology_tools.py`（`_candidate_results` / `_graph_anchor_candidates`
的"部分降级 vs 全失败"判据）。

**非目标（本轮不做）**：

* 不改网关：它把三种不同故障（schema 不存在 / 表不存在 / 校验失败）折叠成同一句
  `500 系统繁忙`，真实 PG 报错（`relation "…" does not exist`）仍到不了 Agent——这属网关侧；
* 不改数据面的 repository 隔离（带 repo 12 仍可读 `ontology_wtttest`、`po`/`ods`/`bdm_customer`）；
* 不落钱江的建模/视图（F8），不改策略路由、SOP、评测集与前端；
* 不做 `Doris*` 类名/模块名/环境变量重命名（保留兼容），只收敛**模型可见文案**（R10）；
* 不改 `_validate_sql` 的默认语义（G6），只在网关后端上收紧（R11）。

---

## 5. 验收

1. `tests/test_pdt_pg_lake_flow_round2_red.py` 由红转绿——当前 **8 failed / 5 passed**：
   红的是 R8、R8b、R9、R10a、R10b、R11、R12、R13；
   绿的是守卫 R11b（拒绝原因可操作）、G3、G4、G5、G6；
2. 守卫（G3–G7）在实现前后都必须保持绿，防止"更严格的报错/校验"误伤正常路径与 SQLite 本地模式；
3. 红测全部在 loopback 假网关 + 生产代码上运行：离线、确定性、不读真实凭据、不连真实服务；
4. 第一轮 Spec 的红测（`tests/test_pdt_pg_lake_flow_red.py`，12 passed）不得回归；
5. 全量 `pytest -q tests` 相对改动前无新增失败（本轮改动前基线：**1232 passed / 25 skipped /
   1042 subtests passed，0 failed**，见 `813c5cf`；加入本红测后实测
   **8 failed / 1237 passed / 25 skipped / 1045 subtests passed**，8 条 failed 全部来自本红测
   文件，文件之外 0 failed）。

---

## 6. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 按 R8 放行"部分降级下的业务否定"后，真后端故障被说成"没有该对象" | 判据必须是**逐个类型的成功探针**（tree 失败但 `_search_type` 成功即算成功）；全失败仍必须报 `remote error`（第一轮 R3 守卫不动） |
| R10 改文案时误伤日志/内部识别 | 只改模型可见字符串；类名、模块名、环境变量、`DorisApiError` 类型名保持不变 |
| R11 收紧后用户写不了 CTE | 本地拒绝必须给出可操作原因（G7）：网关只收 `SELECT`/`MATCH`，请改写为子查询/普通 SELECT |
| R12/R13 改输出格式影响既有断言 | 先跑第一轮红测与 `tests/test_regressions.py`；只新增行、不改既有语义行 |
| 回滚 | 还原 `sql_tools.py` 的错误文案/白名单/表头与 `remote_ontology_tools.py` 的判据；红测文件保留为回归 |

---

## 7. 残留观察（本轮不处理，仅记录）

| 观察 | 位置 | 说明 |
| --- | --- | --- |
| 网关折叠真实报错 | 网关 `/agent/doris/query`、`/meta/query` | 三种不同故障同一句 `500 系统繁忙`，Agent 无法自我纠正 |
| 数据面不按 repository 隔离 | 网关 | repo 12 活跃时实测可 `SELECT` 到 `ontology_wtttest`（8/5 的 schema）与 `po`/`ods`/`bdm_customer` |
| 外部入口 | `pdt-dev.eimos.com` → `172.16.5.90` | 解析通常了，但 `:30834` 不可达；可用入口仍是 `172.16.5.181:30834` |
| 旧出口命名 | `sql_tools.py`、`API/本体MAL层API.md` | `/agent/doris/query` 名称与 PG 引擎不一致（本轮只收敛模型可见文案） |
| 直连分支仍只认 MySQL | `_parse_jdbc_mysql`、数据源设置页 JDBC 表单 | 第一轮 F6，未变；主链路走 HTTP 网关 |
