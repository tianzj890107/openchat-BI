# eimosp-ontology-agentic-analytics 变更记录（2026-09-28 至 2026-10-02）

> 本文档记录 2026-09-28（周一）至 2026-10-02（周五）当周的最终变更，
> 按周直接维护，不再创建日报。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更

### 2026-09-28 · PDT 数据湖切 PG：改善批次（第 2/3/4/6/7/8/10 条）Spec、红测与实现

- 背景：用户从我给出的"PDT PG 切库十条业务问题"里圈定 **2、3、4、6、7、8、10** 七条，要求改善。
  先按仓库节奏交付 Spec + 红测（`docs/specs/pdt-pg-lake-improvements-batch.md` 与
  `tests/test_pdt_pg_lake_improvements_red.py` 11 条；第 2/6/7 条复用
  `docs/specs/pdt-pg-lake-end-to-end-flow-round2.md` 与 `tests/test_pdt_pg_lake_flow_round2_red.py`
  13 条），并在同轮把两批红测（轮二 R8–R13 + 本批 R14–R19）**全部实现转绿**。
- 生产实现（`bi_agent/tools/sql_tools.py`、`bi_agent/tools/remote_ontology_tools.py`、
  `bi_agent/web/app.py`、`DEPLOYMENT.md`）：
  - 第 2 条（部分降级被答成"环境故障"）：`_candidate_results` / `_graph_anchor_candidates`
    的判据由"没有命中 + 有错误"改为**逐个类型的成功探针**——tree 面失败但已回退到本地全量检索
    并成功回答"没有该对象"时回业务否定并附降级说明，只有每个类型都无成功探针才抛 `remote error`；
    `Ontology-SemanticQuery` / `Ontology-EntityDescribe` 的"无命中"分支同步补上降级说明。
  - 第 3 条（连接串外泄）：`_doris_query` 的错误文案不再拼接 `conn.api_url`，网关 5xx 只回状态码 +
    `msg`；pymysql 直连分支同步去掉 host:port 与 "Doris" 字样。
  - 第 4 条（文案称 Doris）：`Ontology-FactQuery` / `ListTables` / `DescribeTable` 的错误前缀去掉
    `(Doris)`；`ListTables` 表头不再打印 HTTP 模式下的占位主机 `HTTP API:0`。
  - 第 6 条（本地白名单与网关不一致）：网关后端新增 `SELECT|MATCH` 开头校验，`WITH` / `EXPLAIN`
    在本地即拒绝并给出可操作原因（`PRAGMA` 仍回既有 `PRAGMA is SQLite-only`）；SQLite 本地模式与
    `_validate_sql` 默认语义不变。
  - 第 7 条（表头与空态）：`ListTables` 表头只陈述真实库名 + 数量，0 表/视图时显式给出空态结论。
  - 第 8 条（规模与主键）：`ListTables` 用 PG 侧 `pg_class.reltuples`（按 `pg_namespace` 对齐
    schema）给出估算，`-1`/缺失显式渲染为 `unknown rows`、不得当行数；`DescribeTable` 用
    `key_column_usage` + `table_constraints`（`PRIMARY KEY`）恢复 `[PK]` 标注，无信息则不标。
  - 第 10 条（本体库编号）：`configure()` 在编号不在目录中时报错列出该环境**可用编号**与
    `ONTOLOGY_REPOSITORY_ID` 键名（不含内网地址）；`DEPLOYMENT.md` 删除写死的
    `ONTOLOGY_REPOSITORY_ID=3`，改为"按环境查目录"口径（PDT 当前为 12 钱江本体库-勿动）。
- 契约依据与实测（2026-09-28 只读复测，PG 17.7 网关，内部入口 `172.16.5.181:30834`）：
  - `pg_class.reltuples` 可查，本体 schema 里都是视图（`relkind='v'`）且 `reltuples=-1.0`，
    即引擎明确"没有估算"——契约要求"有则显示、无则显式未知"，不得伪造数字；
  - `information_schema.table_constraints` + `key_column_usage` 的 join 可执行，业务库 `ods`
    有 **66** 条主键约束，本体 schema（视图）没有主键；
  - 实现前缺陷复现：`ListTables (Doris) error: Doris HTTP API 请求失败 (http://<内网IP>:<端口>/…): …`、
    `# Tables in HTTP API:0/ontology_qianjiang (0)`、配置 3 时报
    `RuntimeError: 远程本体库 3 不在可用目录中`（不列可用编号）、`DEPLOYMENT.md` 仍写
    `ONTOLOGY_REPOSITORY_ID=3`。
- 验收（2026-09-28 实测）：
  - 轮一红测 `tests/test_pdt_pg_lake_flow_red.py` 12 passed 不回归；轮二 13 passed、
    本批 11 passed，三文件合计 **36 passed / 3 subtests passed、0 failed**（实现前 17 failed /
    1239 passed）；第一至六批分析 Agent 红测（安全 / 行动 / 元数据 / 残余 / 预测 / 匿名面收敛）
    保持通过；
  - 全量 `pytest -q tests` **1256 passed / 0 failed / 25 skipped / 1045 subtests passed**；
  - 评测 smoke 140/140、adversarial 15/15 P0、recorded-provider 34/34 P0、regression/all
    147/147 P0，known_gap 0/0、`known_gap_ratchet` 与 `p0_all_pass` 均 PASS（`repeat_stability`
    仍为 not_measured）。
- 需求冲突的处理：轮一 R6b 要求把网关对 `WITH` 的 400 校验文案回传给用户，轮二 R11 要求 `WITH`
  不得送到网关。实现采用本地拒绝、文案复用网关原句（含"仅允许以 SELECT"），两批断言同时满足，
  全程未修改任何红测。
- 未纳入本轮（用户未圈定，保持登记）：第 1 条（钱江本体库 0 表 0 视图、元数据接口 500）、
  第 5 条（网关把三种故障折叠成同一句"系统繁忙"）、第 9 条（数据面未按本体库隔离）。
- 未部署、未重启服务、未创建 MR/tag/Release、未改动版本号（v0.1.9）、未读取真实凭据、
  未对真实会话或用户数据做任何删除/恢复；对 PDT 的调用仍为目录 `GET` + 只读 `SELECT`。
