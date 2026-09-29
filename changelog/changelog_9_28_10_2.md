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
- 未部署、未重启服务、未创建 MR/tag/Release、该轮未改动版本号（当时为 v0.1.9；9-29 晚些
  已升级到 `ontology-v0.1.0`）、未读取真实凭据、未对真实会话或用户数据做任何删除/恢复；
  对 PDT 的调用仍为目录 `GET` + 只读 `SELECT`。

### 2026-09-29 · Git 分支模型与版本号规范落文档（新增长期规范 + 入口链接）

- 背景：用户确认把 Git 分支 / 合并 / 版本号规范写入仓库，并对三处冲突做了裁决：
  ① 季度 MINOR 与现有周节奏冲突 → **按原有**，版本节奏规则保持不变；
  ② 季度收口 MINOR 只作为**人工建议，不自动触发**；
  ③ `release/*` 分支模型作为**变更流程**正式采纳。
- 新增 `docs/git-branch-workflow.md`：长期分支（`master` 归档主线、`release/*` 每版本一条、
  由测试负责人管理、从 master 稳定节点拉出）与临时分支（`feature/*`、`bugfix/*` 从 master 拉出、
  合回 master；`hotfix/*` 从 release 拉出、双向合回 release 与 master）；把原图 5 个要点文字化 ——
  合并一律走 PR、release 拉出时机、hotfix 双 PR、日常开发与发布并行（master 作为归档）、
  命名以 `feature/` `bugfix/` `hotfix/` `release/` 前缀为准。
- 新增 `docs/diagrams/13-git-branch-model.md`（mermaid 图 + ASCII 兜底 + 读图要点表），并在
  `docs/diagrams/README.md` 图目录登记第 13 行。
- 版本判定并入 `docs/versions/versioning-policy.md`：补齐 MAJOR（不兼容重大功能 / 架构重构 /
  核心业务逻辑变更 / API 不向下兼容 / 模型模版不兼容升级）、MINOR（新增功能 / 向下兼容的功能增强 /
  模型模版新增一个元素）、PATCH（Bug 修复 / 安全补丁 / 不影响功能行为 / 模型模版新增一个元素的
  组成部分）判定；同时**校准版本口径**：policy 里"当前正式版本保持为 `v0.1.2`"改为与
  `docs/versions/README.md` 一致的 `v0.1.9`。
- 入口链接：`AGENTS.md`、`docs/gitlab-push-workflow.md`、`docs/versions/README.md` 各增加一行
  指向 `docs/git-branch-workflow.md`（冲突时以 `AGENTS.md` 为准）。
- 契约红测：新增 `tests/test_git_branch_workflow_doc.py`（10 条，先红后绿），pin 分支模型、PR 合并
  机制、release 拉出时机、hotfix 双 PR、命名前缀、不自动升级版本、图目录登记与入口链接。
- 验收（2026-09-29）：新契约测试 10 passed / 2 subtests passed；全量 `pytest -q tests`
  **1266 passed / 0 failed / 25 skipped / 1047 subtests passed**；`git diff --check` 通过。
- 未部署、未重启服务、未创建 MR/tag/Release、该轮未改动产品版本号（当时仍为 v0.1.9；
  9-29 晚些已升级到 `ontology-v0.1.0`）、未删除任何历史会话或用户数据。

### 2026-09-29 · 版本族切换到 ontology-v0.0.x：Spec 与红测

- 背景：用户要求把产品版本族从 `v0.1.x` 迁到本体产品线命名 `ontology-v0.0.x`，并"推倒重来"
  重建历史版本。用户裁决：① `v0.1.0`–`v0.1.9` **全部按顺序映射**为
  `ontology-v0.0.1`–`ontology-v0.0.10`；② 新 tag **沿用原 commit**，不改指向；③ **补齐**
  10 个 tag + 10 个 GitLab Release + 10 篇版本文档（`v0.1.3`–`v0.1.7` 原本有 Release
  但没有版本文档；仓库文档曾把 Release 记为 5 个，执行前用 API 核实为 10 个）；
  ④ **全仓统一**为新命名；⑤ 版本文档命名 `docs/versions/ontology-v0.0.N.md`；
  ⑥ 在 `AGENTS.md` 追加限定范围的一次性授权；⑦ 删除重建旧 tag / Release / 文档。
- 新增 `docs/specs/ontology-version-rename-and-rebuild.md`：映射表（10 组旧名/commit/新名）、
  命名规则与两处强制例外、9 处版本入口清单、文档与索引改动、tag/Release 重建顺序
  （先建新后删旧）、一次性授权文本、红测清单、明确不做与回滚。
- 新增 `tests/test_ontology_version_rename_red.py`（12 条，当前 15 failed 为预期红测）。
- **两处无法统一的强制例外（已实测取证）**：
  - `pyproject.toml` 的 `[project] version` 必须是合法 PEP 440：`packaging.version.Version("ontology-v0.0.10")`
    抛 `InvalidVersion`，故保持 `0.0.10`；
  - `frontend/package.json` / `frontend/package-lock.json` 的 `version` 必须是合法 semver：
    `npm pkg fix` 报 `Invalid version: "ontology-v0.0.10"`，故同样保持 `0.0.10`。
  桥接方案：`product_version()` 读 `pyproject.toml` 后补 `ontology-` 前缀对外返回显示名
  `ontology-v0.0.10`；`_version_reached()` 先剥离 `ontology-v` 前缀再比较，剥离后不合法仍返回
  `False`（否则 known_gap 超期门会静默失效）。
- 范围边界：`changelog/**` 与 `docs/specs/**` 里已写下的旧版本号属于当时的记录，本次不改写。
- 已确认的额外影响：`bi_agent/web/static/vendor/antd/workbench.js` 是构建产物且含 2 处 `v0.1.9`，
  执行时必须重跑 `cd frontend && npm run build`；`.gitlab-ci.yml` 的 release gate 规则为
  `if: $CI_COMMIT_TAG → when: always`，10 个 tag 会触发 10 次 tag pipeline。
- 验收（本批只交付 Spec + 红测）：`pytest -q tests` → **15 failed / 1268 passed / 25 skipped**
  （15 条全来自新增红测文件，其余门禁不受影响）；`git diff --check` 通过。
- 该条目交付的是 Spec 与本批红测；删除重建在下一个条目执行。

### 2026-09-29 · 版本族切换执行：10 个 tag 与 10 个 GitLab Release 重建完成

- 按用户"接受，授权执行"的指令执行 `docs/specs/ontology-version-rename-and-rebuild.md`：
  - 新建 10 个 annotated tag `ontology-v0.0.1`–`ontology-v0.0.10`，逐个指向映射表中登记的
    原 commit（tag 说明沿用原文并把版本号替换为新名）；10 个新 tag 已推送 GitLab；
  - 创建 10 个 GitLab Release（name `智能分析 ontology-v0.0.N`，说明取对应版本文档）；
  - 删除旧 10 个 Release 与旧 10 个 tag（远端 + 本地）。
- 执行前核实：仓库文档记为 5 个 Release，实际 GitLab 上 `v0.1.0`–`v0.1.9` 共 10 个 Release
  都存在、标签保护规则为空、默认分支 `master`；Spec 与 `AGENTS.md` 的一次性授权条目已按
  核实结果修正。
- 版本入口统一（两处 PEP 440 / npm semver 强制例外除外）：
  - `pyproject.toml` `0.1.9 → 0.0.10`（PEP 440）、`frontend/package.json` 与
    `package-lock.json` `0.1.9 → 0.0.10`（npm semver）；
  - `bi_agent/__init__.py`、`bi_agent/web/app.py`、`open_claude/__init__.py`、
    `frontend/src/main.jsx`、`frontend/src/shell.html` 统一为 `ontology-v0.0.10`；
  - `scripts/run_analytics_eval.py`：`product_version()` 读 `pyproject.toml` 后补 `ontology-v`
    前缀返回显示名；`_version_reached()` 剥离 `ontology-v`/`v` 前缀后再比较 `X.Y.Z`，
    避免 known_gap 超期门因解析失败静默失效；
  - `cd frontend && npm run build` 重建 `bi_agent/web/static/vendor/antd/workbench.js`
    （产物内 2 处版本字符串更新；CSS 无差异；`lib/` 两个既有文件按原样保留）。
- 版本文档：`docs/versions/` 迁移为 `ontology-v0.0.1.md`–`ontology-v0.0.10.md`，补齐原
  `v0.1.3`–`v0.1.7` 缺失的 5 篇（由对应 tag 的提交、spec 与验收记录写成）；`README.md`
  索引、根 `README.md` 当前版本与 10 条 Release 链接、`versioning-policy.md` 版本格式
  （`ontology-vMAJOR.MINOR.PATCH` + 包管理清单例外）、`AGENTS.md` 当前版本口径同步。
- 历史边界：`changelog/**` 与 `docs/specs/**` 里已写下的旧版本号按当时记录保留；`DEPLOYMENT.md`
  仅把 tag 口径改为 `ontology-v0.0.3` 并注明服务器 release 目录名沿用旧版本号、未改名。
- 契约测试：新增的 `tests/test_ontology_version_rename_red.py` 由红转绿；`tests/test_versioning_policy.py`
  的版本与 tag 白名单断言、`tests/test_regressions.py` 的品牌/版本一致性断言、
  `tests/test_analytics_eval_dataset.py` 的 `product_version()/_version_reached()` 断言、
  `tests/test_repository_wide_master_consistency.py` 的版本目录豁免前缀同步更新。
- 验收（2026-09-29）：全量 `pytest -q tests` **1278 passed / 0 failed / 25 skipped /
  1066 subtests passed**；`git tag --list` 与 `git ls-remote --tags gitlab` 都只剩 10 个新 tag；
  GitLab Release 列表只剩 10 个新 Release；`git diff --check` 通过。
- 10 个新 tag 会各自触发一次 tag pipeline 的 release gate（`.gitlab-ci.yml` 规则
  `if: $CI_COMMIT_TAG → when: always`）；本批未部署、未重启服务、未做任何服务器写操作、
  未删除或迁移历史会话与用户数据。

### 2026-09-29 · 日常开发切换到 feature/bugfix 分支模型，`20260727` 归档

- 用户裁决：① 启用"临时分支开发 + MR 回流 `master`"的分支模型；② 同步改规则与文档；
  ③ 版本收口的 commit 改到 `feature/*` 上重做（原因见下一条）。
- 规则改动：
  - `AGENTS.md`：提交/推送规则由"统一推 `gitlab/20260727`"改为"日常需求 `feature/*`、日常缺陷
    `bugfix/*`（都从 `master` 拉出）、线上紧急缺陷 `hotfix/*`（从 `release/*` 拉出）"；推送成功
    标准由 `HEAD == gitlab/20260727` 改为 `HEAD == gitlab/<branch>`；`20260727` 标记为已归档、
    停止接收新提交，`scripts/push_gitlab.py` 只服务该归档分支；任务映射中的 MR 说明改为
    临时分支 → `master`，并明确 `hotfix/*` 必须开两条 MR（`release/*` 与 `master`）。
  - `docs/git-branch-workflow.md`："与当前仓库既有约定的关系"由"现阶段仍统一推 `20260727`"
    改为模型已生效（含 hotfix 双 MR 与归档说明）。
  - `docs/gitlab-push-workflow.md`：改写为临时分支推送工作流（远端映射、完成标准
    `HEAD == gitlab/<branch>`、日常流程、安全规则、正式版本与 GitLab Release）。
  - `docs/versions/versioning-policy.md`：发布流程第 11/12 步、GitLab 推送规则与 Release 规则
    改为临时分支口径。
  - 根 `README.md`、`DEPLOYMENT.md`：开发分支口径改为 `feature/*` / `bugfix/*`，注明
    `20260727` 已归档、`main` 已退役并删除。
- 契约测试同步：`tests/test_master_mainline_policy.py`（MR 映射、推送工作流、部署清单）、
  `tests/test_repository_wide_master_consistency.py`（交付契约改为临时分支 → `master`）、
  `tests/test_versioning_policy.py`（GitLab 推送契约）。
- 归档分支现状：`gitlab/20260727` 停在含一个版本收口提交的 `b1cadd3`，不再接收新提交；
  已 push 的历史按规则不重写（禁止 force push）。
- 验收（2026-09-29）：相关契约测试 **60 passed / 13 subtests passed**。

### 2026-09-29 · 版本收口升级到 ontology-v0.1.0（MINOR）并拉出 release/ontology-v0.1.0

- 背景：用户明确指定把当前交付收口为 MINOR `ontology-v0.1.0`（相对 `ontology-v0.0.10`），
  并授权从发布主线拉出 `release/ontology-v0.1.0`。这条指令的授权范围**只有版本号与
  release 分支**：当时未授权 tag、未授权 GitLab Release、未授权部署；tag 与 GitLab Release
  在同日晚些由用户单独授权并已创建（合入 `master` 得定版 commit `74fca80`，tag
  `ontology-v0.1.0` 与之对应，见本文件「ontology-v0.1.0 定版」条目）。按同日生效的分支模型，本收口在
  `feature/branch-model-and-v0.1.0-cut` 分支上重做（`gitlab/20260727` 上那份同名提交作废、
  仅留归档）。
- 版本入口统一（两处强制例外照旧保持裸版本号）：
  - `pyproject.toml` `0.0.10 → 0.1.0`（PEP 440）、`frontend/package.json` 与
    `frontend/package-lock.json` `0.0.10 → 0.1.0`（npm semver）；
  - 显示与发布名统一为 `ontology-v0.1.0`：`bi_agent/__init__.py`、`bi_agent/web/app.py`
    的 `APP_VERSION`、`open_claude/__init__.py`、`frontend/src/main.jsx` 的
    `PRODUCT_VERSION`、`frontend/src/shell.html` 的 `#product-version`；
  - `cd frontend && npm run build` 重建 `bi_agent/web/static/vendor/antd/workbench.js`
    （产物内 2 处版本字符串更新；CSS 无差异）。
- 版本文档与索引：新增 `docs/versions/ontology-v0.1.0.md`（概述 6 个交付主题、验证结论，
  当时写明"未创建 tag / Release / 未部署"——该文已在定版后改写为发布后事实）；`docs/versions/README.md` 当前版本改为
  `ontology-v0.1.0` 并把 `ontology-v0.0.10` 降为“正式版（历史版本）”；根 `README.md`
  当前版本与版本说明链接；`docs/versions/versioning-policy.md` 当前正式版本、包管理清单
  例外示例，并新增"版本推进记录（ontology-v0.0.10 → ontology-v0.1.0）"；`AGENTS.md`
  当前版本口径。
- 契约测试同步：`tests/test_versioning_policy.py`（当前版本、九处版本入口、版本文档白名单
  增加 `ontology-v0.1.0.md`）、`tests/test_ontology_version_rename_red.py`
  （`CURRENT`/`PACKAGING_VERSION`、前端产物断言、README 只禁止退役的 `v0.1.x` Release 链接）、
  `tests/test_regressions.py` 品牌/版本一致性、`tests/test_analytics_eval_dataset.py`
  的 `product_version()/_version_reached()` 断言。
- 范围边界：`changelog/**` 与 `docs/specs/**` 里已写下的旧版本号属于当时的记录，本次不改写；
  `docs/specs/ontology-version-rename-and-rebuild.md` 记录的映射表与 `v0.0.10` 仍是历史事实。
- 验收（2026-09-29）：全量 `pytest -q tests` **1278 passed / 0 failed / 25 skipped /
  1068 subtests passed**；`git diff --check` 通过；`docs/versions/` 目录内容与白名单一致。
- 交付边界：本条目只改版本号、版本文档、索引与契约测试；该轮未创建 tag、未创建 GitLab Release、
  未执行部署、未重启服务（tag 与 Release 已在同日由用户单独授权后创建，版本文档也已同步为
  发布后事实）；`master` 仍是唯一发布主线，本收口通过
  `feature/branch-model-and-v0.1.0-cut` → `master` 的 Merge Request 评审合入；未删除、清空或
  覆盖任何历史会话与用户数据。

### 2026-09-29 · ontology-v0.1.0 tag 契约放宽与定版前置（为收口合入后打 tag 做准备）

- 背景：用户要求把 `feature/branch-model-and-v0.1.0-cut` 走 Merge Request 合入 `master`，
  并在 `master` 上为 `ontology-v0.1.0` 创建 tag 与 GitLab Release（部署未授权）。
  按仓库规则 tag 必须指向 `master` 上的定版 commit，而该 commit 只在收口 MR 合入后才存在，
  因此本轮先解除"新 tag 会让 CI 变红"的前置阻塞。
- 契约测试：`tests/test_versioning_policy.py` 与 `tests/test_ontology_version_rename_red.py`
  的 tag 断言由"只允许既有 10 个 `ontology-v0.0.x` tag"的**精确相等**改为**上下界**——
  必须包含这 10 个改名后的 tag，同时只允许再出现 `ontology-v0.1.0`（允许、不要求存在），
  这样 tag 创建前后 CI 都是绿的，且仍然会拦住任何多余 tag。
- 文档：`docs/versions/ontology-v0.1.0.md` 的 Git Tag / GitLab Release 字段与"已知限制"
  改为记录用户已授权的 tag 与 Release（tag 指向合入后 `master` 的定版 commit、部署仍未授权）；
  `docs/versions/versioning-policy.md` 的"版本推进记录"补记同日单独授权的 tag/Release，
  并把已失效的 `20260727` → `master` 表述改为临时分支 → `master`。
- 范围边界：本轮未创建 tag、未创建 GitLab Release、未部署、未重启服务，未删除或覆盖任何
  历史版本文件与用户数据；tag 与 Release 随后在收口 MR 合入 `master` 后按用户授权执行
  （结果见本文件「ontology-v0.1.0 定版」条目）。
- 合入前置：创建收口 MR 前先把 `master` 合并进本分支（`master` 已含同日合入的稳定性门禁
  修复 `1427319`），唯一冲突是本条 changelog——两条 09-29 记录都追加在文件末尾，按"保留双方
  条目"解决，未丢弃任何一方的记录。
- 验收（2026-09-29）：合并后全量 `pytest -q tests` **1282 passed / 0 failed / 25 skipped /
  1070 subtests passed**；tag 创建前 44 passed / 26 subtests、临时打上 `ontology-v0.1.0`
  后 31 passed / 19 subtests 均通过（临时 tag 已删除，本地回到 10 个 tag）；`git diff --check` 通过。

### 2026-09-29 · 修复 release 稳定性门禁误报：多维持图产物名时间戳泄漏

- 现象：`master`（`9e1a029`）的 CI `unit-tests` 失败，两条用例报同一案例不稳定：
  `test_real_regression_selection_is_perfectly_stable`（agreement 0.998246）与
  `test_truthfulness_metrics_survive_a_repeat_run`（0.991803），`unstable_case_ids` 都是
  `['ANA-RPCHART-008']`（多维持图）。本地跑同一批测试却全绿。
- 根因（用历史 pipeline 3166 的 repeat-stability artifact 取证）：
  `ChartGenerateMultiDim` 写出的文件名是 `multidim-YYYYMMDD-HHMMSS-<标题>.html`，工具结果里
  打印 `Saved:` 路径。稳定性归一化只掩了绝对沙箱路径 `/…analytics-eval-…` 和 `chart-`/`report-`
  两个文件名前缀，**漏了 `multidim-`**；而 Linux CI 上沙箱就是 cwd，`Saved:` 是相对路径
  `dataset/charts/multidim-<戳>-…html`，绝对沙箱规则不命中 → 文件名的墙上时钟戳进入比较指纹
  → 同一案例两次运行的指纹不同 → 被判定为漂移。macOS 本地因为 `/private/var` 与 `/var` 符号
  链接差异，`Saved:` 打印的是绝对路径，被沙箱规则掩盖，所以本地不复现。
- 修复：`scripts/run_analytics_eval.py` 的 `_VOLATILE_TEXT_PATTERNS` 把产物名戳归一化改为按
  **家族**匹配 `(chart|report|multidim)-YYYYMMDD-HHMMSS-` → `<ts>`，并补一条尾部规则处理
  "被长度截断切到一半的戳"（检查项 actual 先截断到 200 字符再归一化，截断点可能落在戳中间）。
- 契约与红测：`docs/specs/analytics-release-stability.md` 的归一化表与"允许变化"补上相对路径与
  `multidim-`；`tests/test_analytics_release_stability_red.py` 新增 `GeneratedArtifactStampTests`
  4 条（相对路径戳、绝对路径戳、被截断的戳、产物名家族覆盖扫描），修复前 3 条为红，修复后全绿。
- 验收（2026-09-29）：`pytest -q tests/test_analytics_release_stability_red.py` **67 passed /
  14 subtests passed**；全量 `pytest -q tests` **1282 passed / 0 failed / 25 skipped /
  1068 subtests passed**；`git diff --check` 通过。
- 边界：只改离线不稳定判定的归一化，不改产品行为、不改文件命名、不改门禁阈值；未部署、
  未重启服务、未删除历史会话与用户数据。

### 2026-09-29 · ontology-v0.1.0 定版：MR 合入、tag 与 GitLab Release 创建，版本记录收口

- 用户指令：把 `feature/branch-model-and-v0.1.0-cut` 合入 `master`，并在 `master` 上为
  `ontology-v0.1.0` 打 tag 与创建 GitLab Release（部署未授权）。
- 合入：Merge Request `!17`（reviewer `tianzijing`、assignee `zhangzhen`）合入后 `master` =
  `74fca80`（"Merge branch 'feature/branch-model-and-v0.1.0-cut' into 'master'"），
  `master` 上 `bi_agent/__init__.py`、`frontend/src/main.jsx` 等九处版本入口均为 `ontology-v0.1.0`；
  该 MR 的 pipeline 3290 里 `unit-tests`、`repeat-stability`、`regression`、`recorded-provider`、
  `smoke` 全部 success（`smoke` 首跑是 runner 拉代码超时，重试后通过；两条 manual 任务按设计不自动跑）。
- tag：创建 annotated tag `ontology-v0.1.0` 指向定版 commit `74fca80` 并推送 GitLab
  （`refs/tags/ontology-v0.1.0`，推送后 tag pipeline 3294 按设计触发 release gate）；推送前后都用
  `git ls-remote --tags` 确认远端不存在同名 tag，未覆盖、未移动任何已有 tag。
- GitLab Release：基于同名 tag 创建「智能分析 ontology-v0.1.0」，说明取本版本文档并改写为发布后口径
  （定版 commit / tag / Release 链接、最终验证数字）；创建前先查 Release 列表确认只有原 10 个，
  创建后共 **11** 个，未覆盖任何已有 Release。
- 版本记录收口（本条目所在的临时分支 → `master` 的后续 MR）：
  `docs/versions/ontology-v0.1.0.md` 的 Release 分支 / 定版 commit / Git Tag / GitLab Release 与
  验证结果、已知限制改为发布后事实；`docs/versions/versioning-policy.md` 的版本推进记录补记
  tag 与 Release 的执行结果；根 `README.md` 发布清单新增本版本 Release 链接；
  契约测试 `tests/test_versioning_policy.py` 与 `tests/test_ontology_version_rename_red.py`
  的 tag 断言由「允许但不要求」改回**精确相等**：必须正好是 10 个 `ontology-v0.0.x` tag 加
  `ontology-v0.1.0`，缺失或多余 tag 都会失败。
- 过期表述清理（避免 tag/Release 创建后自相矛盾）：本周早前几条 09-29 记录里"未授权 tag /
  未创建 tag / 未创建 GitLab Release / 仍为 v0.1.9"的写法，改为注明"该轮当时如此，同日稍后
  已由用户单独授权并创建"；`docs/specs/ontology-version-rename-and-rebuild.md` 的 R12 契约行
  与 §12 收尾核实的 10 个 tag 说明补上"本任务验收时点"限定与 2026-09-29 晚些发布
  `ontology-v0.1.0` 后为 11 个的尾注；`docs/versions/README.md` 增加当前 tag 与 Release 现状
  （共 11 个）。历史周 changelog（9-07 至 9-25）与已归档的统一推送规则保持原貌，不改写历史。
- 边界：本轮只做 MR 合入、tag、Release 与版本记录；未部署、未重启服务、未做任何服务器写操作，
  未删除或迁移历史会话与用户数据。

### 2026-09-29 · 品牌名改为「硕磐智能分析 Agent」，版本徽标移出侧栏、改挂在工作台标题后

- 用户可见变化：侧栏左上角品牌由「智能分析 + ontology-v0.1.0 徽标」改为只显示
  「硕磐智能分析 Agent」；蓝色版本徽标 `ontology-v0.1.0` 移到工作台主标题（原
  「硕磐财务 BI 智能分析」）右侧，标题本身改名「硕磐智能分析 Agent」，即
  「硕磐智能分析 Agent `ontology-v0.1.0`」。
- 实现：`frontend/src/shell.html` 侧栏品牌行删除 `brand-version` 节点、品牌名改新名；
  工作台空态标题改为 `.empty-title-row`（`.empty-title` + `.empty-version#product-version`
  首帧蓝色样式兜底）。`frontend/src/main.jsx` 的 `PRODUCT_NAME` 改为「硕磐智能分析 Agent」，
  侧栏只渲染名称，新增 `ProductVersionTag()` 在挂载时把 `#product-version` 渲染成蓝色
  Ant Design `Tag`（沿用 `PRODUCT_VERSION` 单一口径）；`frontend/src/runtime.js` 的
  空态标题同步改名；`frontend/src/workbench.css` 新增 `.empty-title-row` / `.empty-version`
  样式并调整 `.antd-product-version` / `.antd-product-brand`。
- 契约与测试：`frontend` 重建产物 `bi_agent/web/static/vendor/antd/workbench.js` 与
  `…-workbench.css` 同步更新；`tests/test_regressions.py::test_product_branding_and_version_display`
  断言更新为新品牌名、侧栏无版本徽标、标题行含 `empty-version#product-version`。
- 验收（2026-09-29）：`pytest -q tests` **1282 passed / 0 failed / 25 skipped /
  1070 subtests passed**；`cd frontend && npm run build` 重建结果幂等（仅上述两份产物变化）；
  本地静态页无头渲染 OCR 核对到「硕磐智能分析 Agent `ontology-v0.1.0`」。页面文档标题
  `<title>智能分析 · 本体工作台</title>` 未在本次改名范围，保持原样。
- 边界：只改前端品牌名与版本徽标位置，未改版本号、未改 tag/Release、未部署、未重启服务，
  未删除或迁移历史会话与用户数据。
