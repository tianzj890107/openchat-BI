# 变更记录（2026-11-16 至 2026-11-20）

按自然周维护，不创建日报。

> 2026-11-16 建立本周记录：按“周末内容并入下一周”的规则，`11-14`（周六）与 `11-15`（周日）
> 在 `feature/20251031` 上完成的商机获取交付记入本文件；`11-09` 至 `11-13` 的变更另见
> `changelog_11_9_13.md`（2026-11-16 补齐，补齐说明见文末）。

### 2026-11-14 商机获取卡：储能客户口径修订本体、阶段周期超期分档与风险 RK11

- 卡片改跑《储能客户口径修订》本体：新增 `亿纬锂能_本体_商机获取节点_V3_储能客户口径修订.xlsx`
  与配置生成逻辑，`opportunity_v2.py`、`assets/opportunity-v3/config.json` 同步重生成；
  随后把本体修订后的风险名贯穿到配置与卡片文案，签约覆盖率改为按商机预测总额修订口径。
- 未决语义收紧：缺数据的项不再给出结论，风险行按语义控制展示，每个未决项逐项给出 SQL 证据
  （`opportunity_judgement.py`、`frozen.py`、`insight-components/shared.js`）。
- 模型判断与成因推断改为携带本体上下文，避免脱离本体字段自由解释。
- 新增阶段周期超时分档与风险 RK11：`scripts/build_opportunity_stage_band_ontology.py`
  生成《V3_阶段周期超时分档版》本体与《阶段周期及超时分档_真实动态均值口径》基准，
  `config.json` 增加分档规则、卡片增加 RK11 判定（`tests/test_cockpit_opportunity_v2.py` 同步扩展）。
- 主要文件：`bi_agent/cockpit/{opportunity_v2,opportunity_judgement,frozen}.py`、
  `bi_agent/cockpit/assets/opportunity-v3/config.json`、`scripts/build_opportunity_v3_config.py`、
  `scripts/build_opportunity_stage_band_ontology.py`、`tests/test_cockpit_opportunity_v2.py`。

### 2026-11-14 analysis360：基于全局本体的 360 智能分析，从卡片条款进入

- 新增 `bi_agent/analysis360/`（`ontology.py`、`queries.py`、`tools.py`、`handoff.py` 与
  `assets/global-ontology.json`），提供基于全局本体的多维追问与查询能力。
- 新增前端入口 `bi_agent/web/static/analysis360-handoff.mjs`：从商机卡的风险/指标条款直接跳转
  到对应分析会话，`bi_agent/web/app.py` 增加对应路由与会话挂载，`cockpit.css`、`index.html`
  与 `insight-components/shared.js` 适配入口样式；配套 `.claude/agents/analysis360.md` 说明。
- 主要文件：`bi_agent/analysis360/`、`bi_agent/web/static/analysis360-handoff.mjs`、
  `bi_agent/web/app.py`、`bi_agent/runtime/session.py`、`tests/analysis360_handoff.test.mjs`。

### 2026-11-15 商机获取卡：问题优先分析、精简证据、分析期间定格 2025-10 与 2025-10-31 快照

- 分析口径改为“问题优先”：只对存在问题的指标展开分析，证据区精简为最终结论所需的条目
  （`sales_shipment.py`、`insight-components/shared.js`、`analysis360-handoff.mjs`、
  `web/app.py`、`web/customer.py`、`docs/analysis360.md`）。
- 在 V3 精简关联版本体上把分析期间定格为 2025-10：`periods.py` 引入默认业务期间，
  页面首帧从 `cockpit-business-period` 读取默认期间，`metadata/iba-demo-1021`、`runtime.json`
  与 `scripts/build_cockpit_site.py` 同步更新。
- 所有查询冻结到 `2025-10-31` 快照：`periods.py` 新增快照日期，`opportunity_v2._measurement_date()`
  把期间测量日期收敛到 `min(期间末日, 快照日)`；`11-16` 的 `period_range()` 截断在此基础上扩展。
- 主要文件：`bi_agent/cockpit/{periods,opportunity_v2,sales_shipment}.py`、
  `bi_agent/web/static/cockpit/{cockpit.js,metadata/runtime.json}`、
  `scripts/build_opportunity_v3_config.py`、`tests/test_cockpit_opportunity_v2.py`、
  `tests/analysis360_handoff.test.mjs`。

### 2026-11-16 商机获取卡：V3 精简关联版、分析时间定格 2025 年 10 月与 2025-10-31 取数截止

- 按《亿纬锂能_本体_商机获取节点_V3_精简关联版》重建 `opportunity-v3` 卡片配置并定版为
  `opportunity-v3-rules-11`：51 指标 / 31 规则 / 8 风险 / 8 原因 / 10 建议 / 8 关联；
  按精简关联版取消储能客户范围规则（`storageCustomerScope.enabled=false`、`storage_join` 为空），
  RK08/RK09 投标类查询关闭（风险数 8），BR-Q06 改为 `completedOnly=false`。
- 右上角分析时间固定为 2025 年 10 月：`periods.DEFAULT_BUSINESS_YEAR='2025'`、
  `DEFAULT_BUSINESS_MONTH='2025-10'`，页面首帧通过 HTML `cockpit-business-period` 注入
  `2025-10`（`cockpit.js` 优先读取该 meta 作为默认期间，meta 缺失时才回退为「当前年份-10」）；
  期间下拉仍列出 2025 各月，但超出 10-31 的期间不再产生取数。
- 新增 `periods.DEFAULT_SNAPSHOT_DATE='2025-10-31'`、`snapshot_date()`（`COCKPIT_SNAPSHOT_DATE`
  可覆盖）与 `period_range()` 截断语义：年度粒度窗口为 `2025-01-01`～`2025-10-31`（YTD，
  指标 SQL 仍按全年口径计算进度），月度粒度保留各自月末但不超过 10-31，`2025-11` 及之后的
  期间返回 `None`，服务端不再为其发起 AP 查询。
- `opportunity_v2._measurement_date()` 把每个期间的测量日期收敛到 `min(期间末日, 快照日)`，
  显式传入的测量日期优先；`query_capabilities` 的期间 `bounds`、`refresh` 的期间请求同步使用
  `periods.period_range()`，保证 SQL 参数统一为 `2025-10-31`（此前年度请求仍出现 `2025-12-31`）。
- 规则补丁 SQL 的观测时间统一写为 `2025-10-31 23:59:59`，配置版本与卡片元数据同步更新。
- 主要文件：`bi_agent/cockpit/{periods,opportunity_v2,query_capabilities,refresh}.py`、
  `scripts/build_opportunity_v3_config.py`、`bi_agent/cockpit/assets/opportunity-v3/config.json`、
  `bi_agent/web/static/cockpit/{cockpit.js,metadata/runtime.json}`、
  `tests/test_cockpit_{business_year,query_capabilities,period_refresh,opportunity_v2}.py`。
- 验证：Cockpit Python 套件 593 项通过，`tests/test_cockpit_resource_contract.py` 有 1 项
  在基线 `8c5e3d4` 同样失败的既有用例（`test_delivered_insight_slots_use_live_analysis_instead_of_static_copy`）；
  前端 Node 套件 136 项通过；镜像内实测 `period_range('2025')='2025-01-01'..'2025-10-31'`、
  `'2025-10'='2025-10-01'..'2025-10-31'`、`'2025-11'=None`，AP 年度过滤为
  `2025-01-01~2025-10-31`，无 `CURRENT_TIMESTAMP` 残留。

### 2026-11-16 客户镜像重打包（`feature/20251031@7ffc324`）

- 以 `feature/20251031` 最新提交重打包客户镜像 `cockpit-process360:customer-20261103`
  （linux/amd64），输出 `cockpit-customer-20261103/images/cockpit-linux-amd64.tar`：
  `164,414,976` 字节，SHA256 `df61e0dad6baa0264374fb269675ccad4c8b091d1f2595e9fb6c62a855d53020`，
  `docker load -i` 后镜像 ID `sha256:3439318e43081469ea4e719a583bdcbb04c8103babd22d3bf5c93d7bc8e1db1d`。
- 镜像内 254 个受控文件与 `7ffc324` 逐文件 SHA256 一致；快照日期、期间截断、AP 年度过滤、
  卡片配置版本（`opportunity-v3-rules-11`：51 指标 / 8 风险）、页面默认期间 `2025-10`、
  预置种子年度期间 2025 与内置本体清单均校验通过。
- 同步交付目录 `cockpit-customer-20261103/SHA256SUMS`（仅 `images/cockpit-linux-amd64.tar` 行）、
  `release.json`（sourceCommit `7ffc324`、imageId、imageSha256、previousImage、tests）；
  `打包说明.md` 更新到 `7ffc324` 并修正其中遗留的旧主机路径、seed/wheels 路径与远端 detach 步骤；
  归档 `release.7ffc324.json`、`SHA256SUMS.7ffc324`、`打包说明.7ffc324.md` 到
  `.cockpit-build-20261115/20251031/`，原 `df562f5` tar 保留备份。
- 验证：tar 大小与 SHA256 和 `SHA256SUMS` 一致，`docker load` 与容器内 import 正常；
  仅打包，未部署、未重启服务、未改动服务器数据。

## 补齐说明

- 2026-11-16 补记：`11-09` 至 `11-13` 的周文件此前缺失，已按 Git 记录新建
  `changelog_11_9_13.md`；`11-14`（周六）、`11-15`（周日）的提交按“周末内容并入下一周”
  规则记入本文件，并在 `11-16` 条目中收敛为定版状态。
- 本文件按最终状态合并同一交付的多次提交，不逐条罗列 commit。
