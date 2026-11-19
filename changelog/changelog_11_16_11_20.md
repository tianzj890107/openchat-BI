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

> 11-17 修订：卡片已改用《亿纬锂能本体文件_1117》，下文中的 RK02、RK05、RK03、RK07、RK10 不再输出，RK11 描述改为带去重
> 叠加金额的写法；缺口口径与 AI 根因机制保留，见下一条。

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

### 2026-11-17 商机获取卡片改用《亿纬锂能本体文件_1117》，共同分析卡片改为三行总结

- 本体：收录客户提供的《亿纬锂能本体文件_1117》（根目录与 `docs/亿纬锂能/` 各一份），配置重生成为
  `opportunity-v3-rules-14`（59 指标 / 3 风险 / 8 根因 / 9 建议）。风险只保留商机预测覆盖不足（RK01）、客户预测不足（RK06）、
  商机推进超期，影响签单（RK11）；签单进度滞后（RK02）等已去掉。配置生成脚本兼容新版阶段规则、储能范围写法、固定阶段基线
  与已删除规则的阈值（仅当对应风险/根因仍在本体中时才要求）。
- 取数：本体调用 SQL 改为三个绑定参数 `[期初, 次年初, 观察日]`；RK01 读 R01 总体行，RK06 读 R08“风险专用正缺口汇总”（按客户
  合计后分别取金额、电量正缺口客户），RK11 读 R12～R17 分档及跨阶段去重汇总；新增 P0-09、C10、R09 查询作为根因输入；
  产品部 C05 与卡片自建的全年覆盖查询不再执行。
- 商机推进超期：只列商机获取、技术交流、方案推动三个阶段的严重超期（≥ 1.5 倍固定基线）各一行，超期未满 50% 的不显示；
  风险描述给出跨阶段按商机去重的严重超期商机数及最终叠加预测金额、电量。
- 页面：总标题改为“商机当前风险判断及根因分析”；分类标题改为“商机覆盖风险及根因分析”“商机转化风险及根因分析”，加粗、
  左侧色条醒目显示；去掉“本类共 N 项风险：…”整行；每条风险下的根因默认展开；风险与根因的证据暂时隐藏。
- 根因强制规则：根因不得重复所属风险已有的内容（不复述风险描述的句子和数字、不以风险名称作根因名称），提示词约束并由程序
  校验，不合格时带原因重试一次。（11-17 修订）重试后某条风险若一条合格根因都没有，保留模型给出的根因（数字仍须可追溯），
  不再让该风险下的根因整块消失；模型完全没有给出根因时，风险下显示“根因：…”一行说明原因。根因列表默认展开。
  （11-17 修订）根因下不再显示“待补核实：…”一行和“（AI 分析 · 待核实）”标注（待补证据仍保留在结果数据中）。
- （11-17 修订）根因展示与生成：AI 全局根因每条风险由模型按数据给出 1～3 条（不再受本体 1～2 条限制），每条一段话；
  风险下的根因不再编号（标签统一为“根因”，不显示“根因1、根因2”），不再加“【商机获取】”环节前缀，折叠标题改为“根因”。根因引用与风险相同的指标（目标、已签单、缺口、缺口率等）时数值须与
  风险一致，程序校验，冲突的根因带原因重试，仍冲突则不显示。根因请求为每条风险附上本体「根因」页中关联根因的定义与 AI 分析
  要点作为上下文，模型以本轮指标结果为准，在其基础上推理。
- （11-17 修订）缺口类风险措辞：“进度”改为“已签单”，例如“124家客户的已签单＋剩余预测低于客户目标”“金额目标 X 亿元，
  已签单 Y 亿元（1—9月）＋预测 Z 亿元（10—12月）…”；商机获取卡片与销售额与出货量共同分析卡片一致，输出模板同步修改。
  本体文件中的指标口径定义（“进度＋预测”）未改。
- （11-17 修订）模型输出上限：商机获取卡的 AI 全局根因、风险/根因判定、风险行语义控制与分类总结调用不再在代码里写死
  输出 token（原 AI 根因为 600＋450×风险数，2 条风险时 1500，模型先推理就会被截断而无正文），改为读取 `.env` 的
  `COCKPIT_MODEL_CONTEXT_TOKENS`（输入＋输出总预算）：输出上限＝该预算减去估算输入；未设置时才沿用原默认值。
  涉及 `bi_agent/cockpit/{opportunity_judgement.py,section_summary.py}`。
- 销售额与出货量共同分析卡片：只显示“商机 / 订单 / 发货”三行，每行一句话（模型分类总结按一句话生成；没有模型总结时列出
  该环节问题，没有问题时写“本期未发现…”或“数据不足，无法核实”）；已发布的旧结果在前端按原分类总结显示为三行。
- 文档：重写 `docs/亿纬锂能/商机获取卡片_风险输出模板.md`，`docs/specs/cockpit-opportunity-v3-rules.md` 增加 1117 口径说明。
- 主要文件：`bi_agent/cockpit/{opportunity_v2.py,opportunity_judgement.py,sales_shipment.py,section_summary.py}`、
  `bi_agent/cockpit/assets/opportunity-v3/config.json`、`scripts/build_opportunity_v3_config.py`、
  `bi_agent/web/static/cockpit/{cockpit.css,insight-components/shared.js,insight-components/opportunity-risk/index.js,insight-components/sales-shipment-issues/index.js}`、
  `tests/{test_cockpit_opportunity_v2.py,test_cockpit_sales_shipment.py,cockpit_insight_runtime.test.mjs,cockpit_sales_shipment_issues.test.mjs}`。
- 验证：商机获取、共同分析等相关 Python 测试 165 项通过；驾驶舱相关 Python 测试中 5 项为既有失败；Node 测试 142 项中 140 项通过
  （2 项为基线失败）。未连接客户数据库实跑新 SQL，未在浏览器中查看；已发布卡片需重新分析后才按新本体显示风险与根因。

### 2026-11-17 销售额与出货量共同分析：商机部分本体同步《亿纬锂能本体文件_1117》（V4）

- 本体：新增 `docs/亿纬锂能/亿纬锂能_本体_销售额出货量共同问题分析_V4.xlsx`（V3 保留），由新脚本
  `scripts/build_sales_shipment_ontology_v4.py` 在 V3 上同步 1117 的商机部分生成。商机问题改为 1117 的三个商机风险：
  IS11 商机预测覆盖不足（RK01）、IS12 客户预测不足（RK06）、IS13 商机推进超期，影响签单（RK11）；1117 的 R01、R08、
  R12～R17 以 OR01、OR08、OR12～OR17 收录（调用SQL原样、SQL 计算步骤一并收录），对应根因与行动建议收录为
  RC13～RC20、AC14～AC22。删除 IS02 全年预计达成缺口、IS07 重点客户电量缺口、IS09 / IS10（原读取商机获取卡片发布结果）、
  DQ06、RC07、AC07 及指标 C01～C08、C10、R04～R07；RC01、RC02 改按 OR01 与 OR13 / OR15 / OR17 判定。
- 运行：配置重生成为 `sales-shipment-rules-4`（指标 39、问题 9＋数据校验 5、根因 19、建议 21）。卡片用 1117 SQL
  在本卡片内判定商机问题（三个绑定参数 `[期初, 次年初, 观察日]`，六个分档共用一次执行），判定、等级与描述口径与商机获取
  卡片一致：IS11 写目标、进度＋预测与缺口，IS12 只读 R08 风险专用正缺口汇总，IS13 只以严重超期成立并给出跨阶段去重的
  最终叠加金额；不再依赖商机获取卡片先发布。卡片仍只显示商机、订单、发货三行。
- 文档：`docs/specs/cockpit-sales-shipment-problem-ontology.md` 改为 V4 说明。
- 主要文件：`bi_agent/cockpit/sales_shipment.py`、`bi_agent/cockpit/assets/sales-shipment/config.json`、
  `scripts/{build_sales_shipment_ontology_v4.py,build_sales_shipment_config.py}`、`tests/test_cockpit_sales_shipment.py`。
- 验证：共同分析卡片测试 14 项通过；驾驶舱 Python 测试 609 项通过，5 项为既有失败；26 条调用SQL绑定后经 pglast 解析通过；
  相关 Node 测试 18 项通过。未连接客户数据库实跑，未在浏览器中查看；已发布的共同分析卡片需重新分析后才按 V4 显示。

### 2026-11-18 商机获取卡片同步客户新版风险输出模板与《亿纬锂能本体文件_1117》（1119 批注）

- 本体与模板：客户新版《亿纬锂能本体文件_1117》替换 `docs/亿纬锂能/` 与根目录的同名文件，新版
  《商机获取卡片_风险输出模板》替换 `docs/亿纬锂能/商机获取卡片_风险输出模板.md`（文首注明本仓库执行差异）。
  本体只修订说明文字与规则（BR-L01、BR-D02、BR-V05/V07～V12、BR-A11、RK01/RK06/RK11 描述、根因 AI 分析要点），
  调用 SQL 未变。配置重生成为 `opportunity-v3-rules-15`，AI 根因每条风险 0～2 条（原 1～2 条）。
- 风险描述按新模板：
  - RK01“金额目标 X 亿元，1—9月已签单 Y 亿元，10—12月剩余预测 Z 亿元，全年缺口 G 亿元，缺口率 r%。”，电量同样
    写月份；1 月不写已签单片段。
  - RK06“共 n 家客户存在缺口。金额口径涉及 a 家，目标 …，已签单 …，剩余预测 …，缺口合计 …。电量口径涉及 …”。
  - RK11“n 条商机在已结束阶段出现严重超期，涉及预测金额 … 亿元，涉及预测电量 … GWh。”；只部分可得时写
    “已记录预测…”，全部缺失写“预测…待核实”，不再写去重说明和部分合计尾注。阶段行改为
    “商机获取阶段 · 严重超期 · n 条 · 涉及预测金额 … · 涉及预测电量 …”，不再显示阈值和“触发风险”。
- 根因发布校验（BR-L01、BR-D02、BR-V11、BR-V12）：
  - 没有合格根因时风险下显示“根因：暂无可验证根因”（模型调用失败时括注原因）；重试后仍不合格的根因直接丢弃，
    取消 11-17 的“保留不合格根因”兜底。
  - 每条根因只能使用所属风险自己的指标与数值，须给出所用指标编码（evidence），引用其他风险的指标即丢弃；
    数字校验包括 12 以内的业务数量，月份、序号、年份与编码除外。
  - 停用总体“商机储备严重不足”及同义结论；战略及重点客户储备只在客户预测不足下、并写明存在缺口的客户范围时
    可说明；商机预测覆盖不足下不重复该解释。跨风险按标题和共用数字去重。
  - P0-09（截至观察日仍处于商机获取阶段）不再交给模型，只在商机推进超期下按固定句式
    “截至观察日，仍处于商机获取阶段且严重超期的商机有 n 个，涉及预测金额 …。”由程序展示，占用一条根因名额；
    模型根因提及在途或仍处于商机获取阶段即丢弃。
  - 根因文字去掉“反映”等引导词，P0/P1/P2 阶段写作商机获取、技术交流、方案推动阶段，“正缺口客户”写作
    “存在缺口的客户”。
  - 按用户 11-18 确认，根因仍不显示“（AI 分析 · 待核实）”标注、“【商机获取】”前缀和编号。
- 销售额与出货量共同分析卡片：V4 本体与配置按新版 1117 重新生成（只改说明文字，版本仍为 `sales-shipment-rules-4`），
  IS11～IS13 描述与商机获取卡片新模板一致。
- 主要文件：`bi_agent/cockpit/{opportunity_v2.py,opportunity_judgement.py,sales_shipment.py}`、
  `bi_agent/cockpit/assets/{opportunity-v3,sales-shipment}/config.json`、`scripts/build_opportunity_v3_config.py`、
  `bi_agent/web/static/cockpit/insight-components/shared.js`、`docs/亿纬锂能/`（1117 本体、风险输出模板、V4 本体）、
  `docs/specs/cockpit-sales-shipment-problem-ontology.md`、`tests/{test_cockpit_opportunity_v2.py,test_cockpit_sales_shipment.py}`。
- 验证：商机获取与共同分析测试 103 项通过；驾驶舱 Python 测试中仅 5 项既有失败；Node 测试 136 项中 134 项通过
  （2 项为基线失败）。未连接客户数据库实跑、未调用真实模型、未在浏览器中查看；已发布卡片需重新分析后才按新模板显示。

- 2026-11-19 补记（AI 根因：四段完整性与输出预算）：`GLOBAL_CAUSE_PROMPT` 要求每条根因写全
  规模／范围／机制／影响四段、不使用「已记录」「涉及」前缀；新增 `global_cause_max_tokens()`
  （下限 4000、上限 8000，并读取 `COCKPIT_OPPORTUNITY_V2_MODEL_MAX_TOKENS`），避免长本体/规则
  文本把 JSON 截断导致整条根因丢失。
## 补齐说明

- 2026-11-16 补记：`11-09` 至 `11-13` 的周文件此前缺失，已按 Git 记录新建
  `changelog_11_9_13.md`；`11-14`（周六）、`11-15`（周日）的提交按“周末内容并入下一周”
  规则记入本文件，并在 `11-16` 条目中收敛为定版状态。
- 本文件按最终状态合并同一交付的多次提交，不逐条罗列 commit。
