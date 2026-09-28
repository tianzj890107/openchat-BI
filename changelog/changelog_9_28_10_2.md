# eimosp-ontology-agentic-analytics 变更记录（2026-09-28 至 2026-10-02）

> 本文档记录 2026-09-28（周一）至 2026-10-02（周五）当周的最终变更，
> 按周直接维护，不再创建日报。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更

### 2026-09-28 · PDT 数据湖切 PG：改善批次 Spec 与红测（用户圈定第 2/3/4/6/7/8/10 条）

- 背景：用户从我给出的"PDT PG 切库十条业务问题"里圈定 **2、3、4、6、7、8、10** 七条，要求改善；
  本轮交付 **Spec + 红测**（按仓库既有节奏：先契约与红测，实现另起一轮），**未改生产代码**。
- 交付物：
  - `docs/specs/pdt-pg-lake-improvements-batch.md`——七条 → 契约与红测落点（含 2026-09-28 只读实测
    证据、范围与非目标、验收、风险与回滚）；
  - `tests/test_pdt_pg_lake_improvements_red.py`——loopback PG 方言假网关（MySQL-only 构造回
    `code 500 系统繁忙`，行数/主键按列名应答，不绑定某一种 PG 写法），11 条用例。
- 契约落点：
  - 第 2 条（部分降级被答成"环境故障"）= R8，承载红测在既存
    `tests/test_pdt_pg_lake_flow_round2_red.py::PartialDegradationTests`（本轮不重复新增）；
  - 第 3 / 4 条 = R9 / R10（轮二已覆盖 `Ontology-FactQuery`）＋ 本轮新增 R14 / R15，把
    **元数据工具**（`ListTables` / `DescribeTable`）的错误文案一并纳入"不得带连接串、不得称 Doris"；
  - 第 6 / 7 条 = R11 / R12（承载在轮二红测），本轮不重复；
  - 第 8 条 = R16（`ListTables` 恢复规模信息：有估算就显示，无估算显式标未知，不得把 `-1` 当行数）
    ＋ R17（`DescribeTable` 恢复主键标注，无信息时不标），守卫 G8（不得重新引入 MySQL-only 列）、
    G9（正常清单/结构仍可用）；
  - 第 10 条 = R18（本体库编号不在目录中时报错须列出可用编号与 `ONTOLOGY_REPOSITORY_ID`，
    且不含内网地址）＋ R19（`DEPLOYMENT.md` 不得再把目录里已不存在的编号写成 PDT 当前值）。
- 2026-09-28 只读实测（PG 17.7 网关，PDT 内部入口 `172.16.5.181:30834`）：
  - 行数：`pg_class.reltuples` 可查，但本体 schema 里都是视图（`relkind='v'`）且 `reltuples=-1.0`，
    即引擎明确"没有估算"——所以契约要求"有则显示、无则显式未知"，不得伪造数字；
  - 主键：`information_schema.table_constraints` + `key_column_usage` 的 join 可执行，
    业务库 `ods` 有 **66** 条主键约束，本体 schema（视图）没有主键；
  - 现状缺陷复现：`ListTables` / `DescribeTable` 出错时输出
    `ListTables (Doris) error: Doris HTTP API 请求失败 (http://<内网IP>:<端口>/agent/doris/query): …`
    ——同时命中"连接串外泄"与"文案称 Doris"；`ListTables` 表头仍是
    `# Tables in HTTP API:0/ontology_qianjiang (0)`；本体库目录为 12/8/6/5，配置 3 时报
    `RuntimeError: 远程本体库 3 不在可用目录中`（不列可用编号），而 `DEPLOYMENT.md` 仍写
    `ONTOLOGY_REPOSITORY_ID=3`。
- 红测实测：`tests/test_pdt_pg_lake_improvements_red.py` **9 failed / 2 passed**
  （红：R14a/R14b、R15a/R15b、R16、R16b、R17、R18、R19；绿：G8、G9）；
  全量 `pytest -q tests` **17 failed / 1239 passed / 25 skipped / 1045 subtests passed**，
  17 条 failed = 轮二红测 8 条 + 本批红测 9 条，两个红测文件之外 0 failed。
- 本轮只出 Spec 与红测，**未改动生产代码**；未部署、未重启服务、未创建 MR/tag/Release、
  未改动版本号、未读取真实凭据、未对真实会话或用户数据做任何删除/恢复；对 PDT 的调用仍为
  目录 `GET` + 只读 `SELECT`（含 `pg_class` / `information_schema` / `table_constraints` 盘点）。
- 未纳入本轮（用户未圈定，保持登记）：第 1 条（钱江本体库 0 表 0 视图、元数据接口 500）、
  第 5 条（网关把三种故障折叠成同一句"系统繁忙"）、第 9 条（数据面未按本体库隔离）。
