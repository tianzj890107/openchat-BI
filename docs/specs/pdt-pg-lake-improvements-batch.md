# PDT 数据湖切 PG：改善批次 Spec（用户圈定 2 / 3 / 4 / 6 / 7 / 8 / 10 条）

> 来源：2026-09-28 用户从"PDT PG 切库十条问题"里圈定要改善的七条（2、3、4、6、7、8、10）。
> 本 Spec 把这七条转成可验收的契约，并给出红测落点。
> 承载红测：`tests/test_pdt_pg_lake_improvements_red.py`（新），以及既存
> `tests/test_pdt_pg_lake_flow_round2_red.py`（第 2 / 6 / 7 条）。
> 前置文档：`docs/specs/pdt-pg-lake-end-to-end-flow.md`（第一轮 R1–R7）、
> `docs/specs/pdt-pg-lake-end-to-end-flow-round2.md`（第二轮 R8–R13）。
>
> 本轮**只出 Spec 与红测**，不改生产代码；对 PDT 的实测仍为只读（目录 `GET` + 只读 `SELECT`）。

---

## 0. 七条一句话对照

| 条 | 用户现象 | 本轮契约 |
| --- | --- | --- |
| 2 | 问一个库里确实没有的东西，被答成"系统故障" | R8（已存在） |
| 3 | 内部地址和端口出现在用户可见回答里 | R9（已存在）+ R14（扩到元数据工具） |
| 4 | 错误提示说"Doris 出错"，可实际已是 PG | R10（已存在）+ R15（扩到元数据工具） |
| 6 | 按工具说明写的 SQL（`WITH`/`EXPLAIN`）注定失败 | R11（已存在）+ G4 / G5 / G7 |
| 7 | 表清单表头写着不存在的主机，0 表也没有结论 | R12 + R10b（已存在） |
| 8 | 表清单没有行数、表结构没有主键（适配 PG 时被削掉） | R16（行数）+ R17（主键） |
| 10 | 旧的本体库编号直接起不来，文档还写着旧编号 | R18（报错）+ R19（文档） |

---

## 1. 逐条现状与实测证据（2026-09-28 只读复测）

### 第 2 条：部分降级被答成"环境故障"

- 现象：确认层不可用 + tree 面 500 + **列表面正常返回空**时，`Ontology-SemanticQuery` /
  `Ontology-EntityDescribe` 输出 `remote error: HTTP 500 from /api/v1/analysis/meta/query: …`。
- 判据来源：`bi_agent/tools/remote_ontology_tools.py:321`（`if not found and errors: raise`）与
  `:470`。`_TREE_SEARCH_TYPES = ("Indicator", "Dimension")` 失败后会**回退到 `_search_type`**，
  而该回退（`list_objects`）已经成功回答"没有该对象"，那条错误却仍留在 `errors` 里。
- 要做到：**逐个类型的成功探针**才是判据；只要还有类型有成功探针，就必须回业务否定 + 降级说明；
  只有所有类型都没有任何成功探针时才允许 `remote error`。

### 第 3 条：错误正文带出内部地址

- 实测（live）：`Ontology-FactQuery (Doris) error: Doris HTTP API 请求失败 (http://172.16.5.181:30834/agent/doris/query): HTTP 500 系统繁忙，请稍后再试`。
- 同一句拼接出现在 `ListTables` / `DescribeTable` 的错误行（`sql_tools.py:246` 的异常文案被三处复用）。
- 风险：内部拓扑外泄；若数据源用 `http://user:pass@host/...` 形态，凭据会进对话。
- 要做到：用户可见文案只含网关 `msg`（可含 HTTP 状态码），**不含** URL / 主机端口 / 凭据。

### 第 4 条：文案仍称当前引擎为 Doris

- 实测（live）：`Ontology-FactQuery (Doris) error:`、`ListTables (Doris) error:`、
  `DescribeTable (Doris) error:`、`Doris HTTP API 请求失败`。
- 而同一批工具的描述已按 R7 声明 "the remote analysis gateway (PostgreSQL engine, PG dialect)"。
- 边界：只收敛**人类可读文案**；类名 / 模块名 / 环境变量 / `__doris_repository__` / `DorisApiError`
  以及 `[RESULT_METADATA]` 里的结构化 `provenance.source` **不在本轮范围**（属机器字段）。

### 第 6 条：本地校验与网关白名单不一致

- `_ALLOWED_LEAD`（`sql_tools.py:326`）放行 `SELECT|WITH|PRAGMA|EXPLAIN`；网关只接受 `SELECT|MATCH`。
- 实测（live）：`WITH t AS (…) SELECT …` 与 `EXPLAIN SELECT 1` 都被网关回
  `400 第 1 条语句校验失败：仅允许以 SELECT 或 MATCH 开头的只读查询`；`PRAGMA` 已在网关分支单独拦住
  （"PRAGMA is SQLite-only"）。
- 要做到：网关模式下本地不得把 `WITH` / `EXPLAIN` 送出，拒绝原因要可操作；SQLite 本地模式的
  `PRAGMA table_info(...)` 与 `SELECT` 照旧。

### 第 7 条：表清单表头与空态

- 实测（live）：`# Tables in HTTP API:0/ontology_qianjiang (0)`——`HTTP API:0` 是
  `DorisHttpConn` 在 HTTP 模式下的占位 host/port；0 张表只体现为表头里的 `(0)`。
- 要做到：表头只陈述真实信息（库名 + 数量），并显式给出空态结论。

### 第 8 条：行数与主键能力恢复（本轮新增契约）

- 现状：`ListTables` 只回表名、`DescribeTable` 只回 列名/类型/可空 —— 为了适配 PG 把
  "行数估算"和"主键标记"直接删掉了（`sql_tools.py:513-535`、`:609-632`）。
- 实测（live，PG 17.7 网关）证明两项**都能用 PG 侧来源拿到**：
  - 行数估算：`SELECT c.relname, c.relkind, c.reltuples FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'ontology_wtttest'` → 可执行；
    本体 schema 里都是视图（`relkind='v'`），`reltuples = -1.0`，即**引擎明确表示没有估算**。
  - 主键：`information_schema.table_constraints` + `key_column_usage` 的 join 可执行；
    业务库 `ods` 有 66 条主键约束，本体 schema（视图）没有主键。
- 要做到：
  - `ListTables`：能拿到估算就显示（含"估算"字样），拿到"无估算"（`reltuples < 0` / 视图）时
    显示**显式未知标记**，不得把 `-1` 当行数展示，不得为此失败；
  - `DescribeTable`：用 PG 可用来源恢复主键标注；没有主键信息时不标注（宁可不标，不得误标）；
  - 两条都**不得**重新引入 MySQL-only 列（`table_rows` / `column_key`）。

### 第 10 条：旧本体库编号与运行/文档脱节

- 实测（live）：PDT 目录现为 12 / 8 / 6 / 5，无 3；`configure()` 报
  `RuntimeError: 远程本体库 3 不在可用目录中`（`bi_agent/web/app.py:580`），**没有列出可用编号**，
  运维只能靠猜。
- 文档现状：`DEPLOYMENT.md:135` 的 PDT dotenv 仍写 `ONTOLOGY_REPOSITORY_ID=3`，
  同文 `:171` 的环境对照表也写 `3`（PDT 的 ECore 本体库）。
- 要做到：
  - 报错可操作：包含**可用编号列表**与配置键名（`ONTOLOGY_REPOSITORY_ID`），且不含内网地址；
  - 文档不再把目录里已不存在的编号写成 PDT 当前值，取值方式以"按环境查目录"为准。

---

## 2. 契约与守卫

| 编号 | 契约 | 对应条 | 承载红测 |
| --- | --- | --- | --- |
| R8 | 部分降级不得升级成故障：只要还有成功探针回答"没有"，就必须回业务否定 + 降级说明；全失败才可 `remote error` | 2 | `test_pdt_pg_lake_flow_round2_red.py::PartialDegradationTests`（已存在，红） |
| R9 | 网关错误输出只含网关 `msg`（可含状态码），不得含 API URL / 主机端口 / 凭据 | 3 | `…round2…::ErrorCopyTests::test_r9_…`（已存在，红） |
| R14 | 同上口径**覆盖元数据工具**：`ListTables` / `DescribeTable` 的错误文案同样不得带出连接串 | 3 | `test_pdt_pg_lake_improvements_red.py::ErrorCopyTests`（新，红） |
| R10 | 模型可见文案不得把当前引擎称作 Doris（错误前缀 / 表头 / 拒绝文案） | 4 | `…round2…::ErrorCopyTests::test_r10a_…`（红）+ `…round2…::ListingAndDescribeTests::test_r10b_…`（红） |
| R15 | 同上口径**覆盖元数据工具**：`ListTables` / `DescribeTable` 的错误文案不得称 Doris | 4 | `…improvements…::ErrorCopyTests`（新，红） |
| R11 | 网关模式下本地不得送出网关已知会拒绝的语句（`WITH` / `EXPLAIN`），拒绝原因可操作 | 6 | `…round2…::LocalValidationParityTests`（红） |
| R12 | `ListTables` 必须显式表达空态；表头只陈述真实信息（不得出现占位主机） | 7 | `…round2…::ListingAndDescribeTests::test_r12_…` / `test_r10b_…`（红） |
| R16 | `ListTables` 恢复规模信息：有估算则显示，无估算则显式未知；不得把 `-1` 当行数；不得因此失败 | 8 | `…improvements…::ScaleInformationTests::test_r16_…`（新，红） |
| R17 | `DescribeTable` 恢复主键标注（PG 可用来源）；无信息时不标注 | 8 | `…improvements…::ScaleInformationTests::test_r17_…`（新，红） |
| R18 | 本体库编号不在目录中时，报错必须列出**可用编号**与配置键名，且不含内网地址 | 10 | `…improvements…::RepositoryIdErrorTests`（新，红） |
| R19 | `DEPLOYMENT.md` 不得再把目录里已不存在的编号写成 PDT 当前值 | 10 | `…improvements…::DocumentationTests`（新，红，机械守卫） |
| G4 | 收紧本地校验后 `SELECT` 仍必须送到网关 | 6 | `…round2…::HappyPathGuards::test_g4_…`（已绿） |
| G5 | SQLite 本地模式 `PRAGMA table_info(...)` 仍可用 | 6 | `…round2…::HappyPathGuards::test_g5_…`（已绿） |
| G7 | 本地拒绝必须给出可操作原因（提到 SELECT / MATCH / 只读规则） | 6 | `…round2…::LocalValidationParityTests::test_r11b_…`（已绿） |
| G8 | 恢复行数/主键后**不得**重新引入 MySQL-only 列（`table_rows` / `column_key` / 反引号 / `limit a,b`） | 8 | `…improvements…::ScaleInformationTests`（守卫，现绿） |
| G9 | 后端正常时 `ListTables` / `DescribeTable` 仍必须正常出清单 | 8 | `…improvements…::ScaleInformationTests`（守卫，现绿） |

---

## 3. 红测落点与当前状态

`tests/test_pdt_pg_lake_improvements_red.py`（新文件，11 条，实测 **9 failed / 2 passed**）：

- 红（9 条）：R14a / R14b（`ListTables` / `DescribeTable` 的错误文案带连接串）、
  R15a / R15b（同两条错误文案仍称 Doris）、R16（基表没有行数估算）、
  R16b（视图没有估算也没有显式未知标记）、R17（没有主键标注）、
  R18（本体库编号报错不列可用编号）、R19（`DEPLOYMENT.md` 仍写旧编号）；
- 绿（守卫 2 条）：G8（未发 MySQL-only 列）、G9（后端正常时清单/结构仍可用）。

已存在红测（不重复新增，避免两处维护同一契约）：

- 第 2 条 → `…round2…::PartialDegradationTests`（R8 / R8b，红）；
- 第 6 条 → `…round2…::LocalValidationParityTests`（R11 红，R11b 绿）；
- 第 7 条 → `…round2…::ListingAndDescribeTests`（R10b / R12 红）。

---

## 4. 范围与非目标

**范围内**：

- `bi_agent/tools/remote_ontology_tools.py`：`_candidate_results` / `_graph_anchor_candidates`
  的"部分降级 vs 全失败"判据（第 2 条）；
- `bi_agent/tools/sql_tools.py`：错误文案（去 URL、去 Doris 字样）、网关模式语句白名单、
  `ListTables` 表头与空态、`ListTables` 行数估算、`DescribeTable` 主键标注（第 3/4/6/7/8 条）；
- `bi_agent/web/app.py`：本体库编号不在目录时的报错文案（第 10 条）；
- `DEPLOYMENT.md`：PDT 的 `ONTOLOGY_REPOSITORY_ID` 取值说明（第 10 条）。

**非目标（本轮不做）**：

- 不改网关：三种故障折叠成同一句 `500 系统繁忙`、数据面无 repository 隔离——已登记，属网关/本体侧；
- 不落钱江的建模与视图（第 1 条，本轮未选）；不改第 5 / 9 条；
- 不改 `_validate_sql` 的默认语义（G6），也不改 SQLite 本地模式的 `PRAGMA` 能力；
- 不改结构化 `provenance.source` 等机器字段；
- 不做 `Doris*` 类名/模块名/环境变量重命名。

---

## 5. 验收

1. `tests/test_pdt_pg_lake_improvements_red.py` 由红转绿（当前 9 红 / 2 绿）；
2. 第 2 / 6 / 7 条由既存 `tests/test_pdt_pg_lake_flow_round2_red.py` 的红测转绿（当前 8 红 / 5 绿）；
3. 第一轮红测（`tests/test_pdt_pg_lake_flow_red.py`，12 passed）不得回归；
4. 守卫（G4 / G5 / G7 / G8 / G9）在实现前后都保持绿；
5. 全量 `pytest -q tests` 相对改动前无新增失败（本轮改动前基线：**8 failed / 1237 passed /
   25 skipped / 1045 subtests passed**，8 条 failed 全部来自第二轮红测文件；加入本批红测后实测
   **17 failed / 1239 passed / 25 skipped / 1045 subtests passed**，17 条 failed 分布为
   第二轮红测 8 条 + 本批红测 9 条，两个红测文件之外 0 failed）。

---

## 6. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 第 2 条放宽后把真故障说成"没有该对象" | 判据必须是**逐个类型的成功探针**；全失败仍必须 `remote error`（R3 不动） |
| 第 8 条恢复行数时用 PG 不存在的列（重犯 F1） | G8 守卫：任何 MySQL-only 构造都会让假网关返回 500，测试直接红 |
| 视图没有估算，容易被 `-1` 误显示成"负行数" | R16 要求显式未知标记；`-1` 不得出现在规模位 |
| 主键 join 在视图上永远为空，易误标 | R17 要求"没有信息就不标"；假网关对非主键列返回 False 时不得出现 PK 标记 |
| 第 10 条改报错文案影响既有断言 | 只加信息（可用编号 + 键名），不改异常类型；跑 `tests/test_regressions.py` 与第一二轮红测 |
| 机械文档守卫（R19）过严 | 若评审认为不合适可移除该用例，改为评审清单；改代码行为不受影响 |
| 回滚 | 还原 `sql_tools.py` / `remote_ontology_tools.py` / `app.py` 与本轮文档；红测文件保留为回归 |
