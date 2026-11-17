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

### 商机获取卡：阶段周期分档本体、风险分类总结与 2025-10-31 快照

- 2026-11-15（本地时间）「穿透式分析 → 商机获取 → 销售额口径明细」切换到附件《V3 阶段周期超时分档版》，
  生成 `opportunity-v3-rules-12`（57 指标 / 34 规则 / 9 风险 / 10 原因 / 12 建议）。
  BR-Q04 按附件启用储能客户范围，BR-Q06 仅以已结束样本计算均值，RK08/RK09 投标风险继续关闭。
- 同类成立风险归到「商机覆盖风险」或「商机转化风险」父节点，每个父节点用该组已展示的风险和指标生成模型总结。
  总结失败时仍展示风险和证据，已有分析可保留原格式。
- 2026-11-15 修订（商机覆盖风险缺少分类总结）：分类总结的数字校验此前比段落总结更严，只认原文数字串，
  `12.35`→`12.4`、比例→百分比等写法会被整组丢弃，且重试不告知原因、失败无记录；RK01–RK07 小数和百分比多，
  「商机覆盖风险」最易落空，只剩「商机转化风险」有总结。现改为与段落总结同一容差（`_allowed_model_numbers`，
  并补充四舍五入半进位写法），重试携带 `validationFeedback`，拒绝原因写入 `cockpit_risk_group_summary_rejected`
  日志；仍未通过的分类改用规则总结（只列本类风险名称与等级），`riskGroups[].summarySource` 标注
  `model`/`rule`。已发布的卡片需手动刷新该卡后才会出现新总结。
- RK11 由 R13/R15/R17 任一达到超期阈值的已结束样本触发。成立后逐项显示 R12–R17 的阶段、分档、
  状态、商机数、预测金额和电量。仅有关注档时不触发。分档查询沿用快照观察时间，截止后结束的样本不参与均值。
- 风险分组、分类总结及指标明细随卡片结果传递和缓存。主要涉及 `opportunity_v2.py`、
  `opportunity_judgement.py`、`section_summary.py`、`frozen.py`、`page_cache.py` 和 `insight-components/shared.js`。
- 本次验证：203 项相关 Python 测试和 20 项前端测试通过，覆盖分类总结串组修复、RK11 分档状态、
  卡片交付与快照截止。分类总结使用模拟模型响应验证。
- 右上角分析时间固定为 2025 年 10 月：`periods.DEFAULT_BUSINESS_YEAR='2025'`、
  `DEFAULT_BUSINESS_MONTH='2025-10'`，页面首帧通过 HTML `cockpit-business-period` 注入
  `2025-10`（`cockpit.js` 优先读取该 meta 作为默认期间，meta 缺失时才回退为「当前年份-10」）；
  超出 10-31 的期间不再产生取数（月度下拉已收窄为 1–10 月，见下方页头条目）。
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
- 快照交付验证（本次切换本体之前）：Cockpit Python 套件 593 项通过，`tests/test_cockpit_resource_contract.py` 有 1 项
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

### 2026-11-15 驾驶舱页头：右上角“当前日期 25年10月31日”，月度期间收窄到 1–10 月

- 全部驾驶舱页面右上角、日期筛选器右侧新增“当前日期 25年10月31日”标签。日期由服务端
  `snapshot_date()`（默认 `2025-10-31`，可用 `COCKPIT_SNAPSHOT_DATE` 覆盖）注入
  `<meta name="cockpit-snapshot-date">`，不读浏览器时钟；页头组件没有插槽，标签通过
  `teleport` 挂入 `.pro-bi-dashboard-header__extra`，看板重挂载后自动重新定位。
- 原日期筛选位置与默认值（`2025-10`）不变：年度粒度仍只可选 `2025`；月度粒度由 2025 年 12 个月
  改为 `2025-01`～`2025-10`（`cockpit.js` 的 `PERIOD_FILTER_LAST_MONTH = 10`，交付元数据
  `components.json` / `runtime.json` 同步移除 11、12 月选项，`iba-demo-1021/source.json` 中
  `components.json` 的 SHA256 同步为新内容（LF 规范化）的值）。
- 静态站点构建 `scripts/build_cockpit_site.py` 同步替换新占位符 `@@COCKPIT_SNAPSHOT_DATE@@`。
- 主要文件：`bi_agent/web/app.py`、`bi_agent/web/static/cockpit/{index.html,cockpit.js,cockpit.css}`、
  `bi_agent/web/static/cockpit/metadata/{iba-demo-1021/components.json,iba-demo-1021/source.json,runtime.json}`、
  `scripts/build_cockpit_site.py`、
  `tests/{cockpit_period_filter.test.mjs,test_cockpit_business_year.py,test_cockpit_metadata.py}`。
- 验证：前端 Node 测试 137 项中 135 项通过，失败的 2 项（`manual card refresh reports analysis duration…`、
  `history-card loader stays in scope…`）在改动前基线上同样失败；Cockpit Python 套件（WSL，Python 3.11）
  共 598 项，修复站点构建占位符后剩余 4 项失败均与本改动无关：Windows CRLF 检出下原始字节哈希不一致
  （`test_vendor_manifest_matches_local_artifacts`、`test_imported_metadata_hashes_and_three_tabs`）、
  既有失败 `test_delivered_insight_slots_use_live_analysis_instead_of_static_copy`、测试环境缺少 `psycopg`；
  `git diff --check` 通过。未在浏览器中实际查看页面效果。

### 2026-11-15 驾驶舱卡片文字隐藏本体编码

- 风险、问题、原因、建议及各类摘要卡片的展示文字不再出现 `RK01`、`RC03`、`AC07`、`R01`/`B01`/`C01`/`S01`/`O01`、
  `BR-Q02`、`IS01`/`DQ02`/`DR04`、`P0-01` 等本体编码，只显示文字描述：如「RK01 商机预测覆盖不足」显示为
  「商机预测覆盖不足」，「（R13）」「（本体 DR04）」整段括号去掉，「按 BR-Q02 订单关联口径判断」显示为
  「按订单关联口径判断」；RK11 分档明细行去掉 `R12`–`R17` 前缀，只显示阶段、分档与状态。
  `P0`/`P2` 等阶段名称、产品型号与日期不受影响。
- 实现为前端展示层统一过滤（`insight-components/number-highlight.js` 的 `stripOntologyCodes`）：
  `number-text`（描述、摘要、建议、验收）、`useInsight().summary` 及风险/问题/原因标题、`bid-summary`、
  `opportunity-coverage-note`、`order-sign-summary`、`shipment-cause-breakdown` 的标题与名称均经过滤；
  已发布卡片无需重新分析即生效。后端结果、本体追溯、证据与 SQL 明细（折叠区）仍保留编码，便于审计和深度分析交接。
- 主要文件：`bi_agent/web/static/cockpit/insight-components/{number-highlight.js,shared.js,bid-summary/index.js,
  opportunity-coverage-note/index.js,order-sign-summary/index.js,shipment-cause-breakdown/index.js}`、
  `tests/{cockpit_stage_risk_format,cockpit_sales_shipment_issues}.test.mjs`。
- 验证：前端 Node 测试 139 项中 137 项通过，失败的 2 项为改动前即存在的基线失败；读取前端组件的 Python 测试
  49 项通过，3 项为既有失败（CRLF 哈希 2 项、`test_delivered_insight_slots…` 1 项）。未在浏览器中实际查看。
- 2026-11-16 修订（浏览器报错 `does not provide an export named 'stripOntologyCodes'`）：`shared.js` 以相对路径
  静态导入 `./number-highlight.js`、`./task-order/*.js`，这些子模块 URL 不带 `?v=` 版本号，而 `/static` 原先
  不返回 `Cache-Control`，浏览器按启发式缓存复用了旧版子模块。`app.py` 的 `/static` 挂载改为
  `RevalidatingStaticFiles`：不带查询串的静态请求返回 `Cache-Control: no-cache`（按 ETag 校验，未变化时 304），
  带 `?v=` 的版本化 URL 行为不变；主服务与客户入口共用。新增 `tests/test_static_revalidation.py`。
  已打开旧页面的浏览器需强制刷新一次（Ctrl+F5）。

### 2026-11-16 穿透式分析：头盔图改为“商机 → 订单 → 订未发”，共同分析卡片按业务环节分组

- 头盔图：标题由「销售额口径 · 三节点头盔图（商机获取 → 订单接收 → 发货）」改为
  「销售额口径 · 三节点头盔图（商机 → 订单 → 订未发）」（`template-registry.json`、`runtime.json`，
  `source.json` 哈希同步）；图中三个节点名由 AP 返回的「商机获取 / 订单接收 / 发货」在展示层改为
  「商机 / 订单 / 订未发」（`data-client.js` 的 `relabelHelmet`，实时与快照回放两条读取路径都经过；
  节点选择与联动规则按节点 ID，不受影响，AP 原始响应与快照比对保持不变）。
- 共同分析卡片：标题由「销售额与出货量共同分析当前问题判断」改为「销售额与出货量共同分析」；问题改为与
  销售额口径明细卡片相同的父子结构，父节点按“商机 → 订单 → 订未发”顺序为「商机问题」「订单问题」
  「订未发问题」，每个父节点附模型分类总结（校验未通过时用规则总结，`summarySource` 标注），不再显示
  「【指标异常】」前缀和整卡段落总结；顶部总述改为业务语言（如「本期发现 N 项业务问题：商机问题 a 项、…」），
  不再出现「本轮 14 项本体问题中…规则判定…」。数据问题（取数失败、结果为空、口径不一致等）不再作为问题展示，
  也不再交给模型判断；取数失败仍在「数据范围」限制中说明。
- 本体更新为《销售额出货量共同问题分析_V3》（`docs/亿纬锂能/`，V2 保留）：问题类型由「指标异常 / 数据问题」
  改为业务环节分类——商机问题：商机覆盖问题、商机转化问题、全年预计达成缺口、重点客户电量缺口；订单问题：
  销售额与出货量量价背离、在手订单不足以覆盖剩余目标、订单取消／变更冲减；订未发问题：销售额与出货量双双落后
  时间进度、超期订未发积压、订单履约率偏低；原 6 项数据问题改为「数据校验」（不展示）。原有指标、SQL、根因与建议不变。
- （11-16 修订）商机问题与「商机获取 · 销售额口径明细」卡片关联：新增 IS09 商机覆盖问题、IS10 商机转化问题，
  不另设指标，直接读取商机获取卡片同期间最新发布结果中「商机覆盖风险」「商机转化风险」分类——分类内至少 1 项风险成立
  即成立，等级取最高等级，描述列出成立风险名称、等级及该分类总结；商机获取卡片未发布同期间结果时不判定、不交模型推断，
  在限制中提示。客户年度模式整页分析时商机获取卡片先于共同分析卡片运行（`frozen.priority_order`），
  `customer.py` 向执行器提供已发布卡片读取（`_published_for_period` 校验期间）。
- 生成脚本 `build_sales_shipment_ontology.py` 同步（输出 V3、新增“问题分类”说明与关联问题类型 `link`），
  `build_sales_shipment_config.py` 读取 V3 并写入 `category` / `kind: link`，运行配置升级为 `sales-shipment-rules-3`。
  模型角色提示改为业务语言、不出现编码。新增说明文档 `docs/specs/cockpit-sales-shipment-problem-ontology.md`。
- 主要文件：`bi_agent/cockpit/{sales_shipment,section_summary,frozen}.py`、
  `bi_agent/cockpit/assets/sales-shipment/config.json`、`scripts/build_sales_shipment_{ontology,config}.py`、
  `bi_agent/web/static/cockpit/{data-client.js,cockpit.js}`、
  `bi_agent/web/static/cockpit/insight-components/{shared.js,sales-shipment-issues/index.js}`、
  `bi_agent/web/static/cockpit/metadata/{iba-demo-1021/template-registry.json,iba-demo-1021/source.json,runtime.json}`。
- 验证（含商机问题关联修订）：Cockpit 与 360 分析 Python 套件 643 项中 637 项通过，6 项为既有失败（CRLF 哈希 3 项、缺 `psycopg` 1 项、
  `test_delivered_insight_slots…` 1 项、计时敏感的 `test_completed_router_analysis…` 1 项）；元数据 LF 规范化哈希
  全部一致；前端 Node 测试 141 项中 139 项通过，2 项为基线失败。已发布的共同分析卡片需重新分析后才按新分组展示。
  未在浏览器中实际查看。

### 2026-11-16 商机获取 · 销售额口径明细：根因挂在风险下，隐藏建议

- 风险与根因改为一对多展示：每条风险下增加可展开的「N 项根因」列表，列出与该风险关联的全部根因（同一根因关联多条风险时
  在每条风险下都出现），根因保留环节、名称、描述、模型推理标注与证据；不再单独展示【原因】分区，也不再显示
  「风险N—原因M」对应关系文字。
- 建议暂时隐藏：建议分区、底部「建议 N 验收」行与建议库统计均不显示（根因改为 AI 全局分析后不再关联本体建议，见下条）。
- 仅作用于该卡片（`opportunity-risk` 的 `causesUnderRisks: true`、`showRecommendations: false`）；订单、发货等其他
  环节卡片版式不变。风险与根因的证据（识别的规则、取数 SQL）抽为共用组件 `StageTraceDetails`，三处展示一致。
- 主要文件：`bi_agent/web/static/cockpit/insight-components/{shared.js,opportunity-risk/index.js}`、
  `bi_agent/web/static/cockpit/cockpit.css`、`tests/cockpit_sales_shipment_issues.test.mjs`。
- 验证：前端 Node 测试 142 项中 140 项通过（2 项为基线失败）；读取前端组件的 Python 测试 50 项通过，3 项为既有失败。
  已发布卡片无需重新分析即按新版式展示。未在浏览器中实际查看。

### 2026-11-16 商机获取 · 销售额口径明细：风险规则修订本体、缺口口径与 AI 根因

- 本体：收录客户新版《亿纬锂能_本体_商机获取节点_V3_风险规则及周期SQL修复》（根目录与 `docs/亿纬锂能/` 各一份），
  并由新脚本 `scripts/build_opportunity_ai_cause_ontology.py` 生成《…_V3_缺口口径及AI根因版》作为卡片本体，
  配置重生成为 `opportunity-v3-rules-13`（57 指标 / 8 风险 / 10 根因 / 12 建议 / 21 条链路）。
- 风险规则（客户修订）：RK02 签单达成率改为已签单商机预测 ÷ 年度目标，并新增全年金额覆盖率 < 120% 预警（仅因此成立时
  不定级），取消季度未签比例窗口；删除电芯独立风险 RK04；RK05 改为 PACK 待签 > 0 且 PACK 全年目标缺口率 > 20% 触发，
  待签 < 10 亿元不定级。
- 缺口类风险统一给出“目标、进度＋预测 → 缺口”：RK01、RK05、RK06 的缺口 ＝ 目标 −（进度＋预测），进度为观察月以前已签单
  商机预测、预测为观察月至 12 月全部商机预测（本体 R03 全年覆盖预测分支）；本体 R01、R08 的定义、规则与调用 SQL 同步改写。
  卡片新增查询“全年覆盖预测”，失败时这些风险记“无法判定”，不回退旧口径。RK02 领先时间进度时写“未落后时间进度”，
  不再出现负的“落后”点数。
- RK11（商机转化风险 · 阶段风险）描述改为“{n}条商机的阶段周期超均值50%及以上。”。
- 根因全部改为 AI：本体根因表、链路“判定方式”统一为 AI，BR-L01 改为“AI 全局根因分析”。卡片对本轮全部已成立风险及其
  指标结果调用一次模型做全局分析，每条风险给出 1～2 条根因（维度由模型自定，不匹配本体根因库；数字须来自输入，
  漏答或越界数字重试一次），根因标注“（AI 分析 · 待核实）”，不关联本体建议。
- 根因文档复核：RC04 改名“产品部商机储备与目标不匹配”、RC06 改名“待签商机重点跟踪覆盖不足”；删除不成立的关联
  RC01—RK07、RC06—RK01、RC07—RK03（链路 L024、L002、L012），新增 RC03—RK02（L035）。
- 文档：重写 `docs/亿纬锂能/商机获取卡片_风险输出模板.md`，`docs/specs/cockpit-opportunity-v3-rules.md` 增加本次口径说明。
- 主要文件：`bi_agent/cockpit/{opportunity_v2.py,opportunity_judgement.py}`、`bi_agent/cockpit/assets/opportunity-v3/config.json`、
  `scripts/{build_opportunity_ai_cause_ontology.py,build_opportunity_v3_config.py}`、
  `bi_agent/web/static/cockpit/insight-components/shared.js`、`tests/test_cockpit_opportunity_v2.py`、
  `tests/cockpit_sales_shipment_issues.test.mjs`。
- 验证：商机获取相关 Python 测试 170 项通过（1 项为缺少 `psycopg` 的既有失败）；Node 测试 143 项中 141 项通过（2 项为基线
  失败）。未连接客户数据库实跑新查询（SQL 已用 pglast 做语法解析），未在浏览器中查看；已发布卡片需重新分析后才显示新口径。

### 2026-11-17 商机获取卡：根因「深度分析」改为条目内对话框

- 深度分析入口从隐藏改为挂在每个根因条目后面：商机获取 · 销售额口径明细卡片展开某个风险后，
  每条「根因N」条目末尾新增「深度分析」按钮；风险行和建议行不加，其他卡片复用同一组件时
  也只在根因行出现。
- 点击后在当前页弹出「深度分析 · 根因」对话框：顶部固定这条根因的编码、名称、描述、环节与
  期间，输入框自动预填 `深度分析「<根因名称>」根因`，可修改后再发送；不再打开新的
  `/workbench?a360=` 标签页。
- 对话框首轮仍把条款交给 `POST /api/analysis360/handoff`，随后 `POST /api/analysis360/chat`
  在同一会话内流式回答；AskUser 选项渲染成按钮，经 `POST /api/analysis360/choice` 继续。
  交接编号只在首轮发送，避免服务端重建会话；关闭对话框后前端不再展示该轮回答，也不写入
  工作台历史。360 智能分析未配置时对话框内直接提示错误，不静默失败。
- 新增 `insight-components/deep-analysis/{model.js,dialog.js}`：SSE 分帧、事件归并、先转义
  再套标题/列表/加粗/行内代码的安全 markdown 渲染，以及对话框的会话、请求、关闭逻辑；
  `shared.js` 在两种根因排版（挂在风险下、独立原因区）挂同一个入口。
- 主要文件：`bi_agent/web/static/cockpit/insight-components/{shared.js,deep-analysis/model.js,deep-analysis/dialog.js}`、
  `docs/analysis360.md`、`tests/deep_analysis_dialog.test.mjs`、`tests/analysis360_handoff.test.mjs`。
- 验证：Node 套件 149 项通过（新增 7 项覆盖提示词、SSE 分帧、事件归并、转义渲染与入口挂载）；
  用 `analysis360.handoff.normalise` 实测对话框 payload 能归一化并生成首轮 opening message；
  `git diff --check` 通过；未启动服务、未部署。

## 补齐说明

- 2026-11-16 补记：`11-09` 至 `11-13` 的周文件此前缺失，已按 Git 记录新建
  `changelog_11_9_13.md`；`11-14`（周六）、`11-15`（周日）的提交按“周末内容并入下一周”
  规则记入本文件，并在 `11-16` 条目中收敛为定版状态。
- 本文件按最终状态合并同一交付的多次提交，不逐条罗列 commit。
