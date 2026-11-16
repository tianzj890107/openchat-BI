# 变更记录（2026-11-09 至 2026-11-13）

> 2026-11-16 补记：本周周文件此前缺失，依据 `2026-11-07`～`2026-11-13` 的 Git 提交与
> 最终代码状态补齐；`11-07`、`11-08`（周末）无提交，无需并入下一周。本文按功能主题合并，
> 不逐条罗列 commit；各提交自带的测试与验收结论见对应提交，本轮补记未重跑全量测试。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更

### 2026-11-09 Cockpit 分析交付链路：可见卡片优先、按环节独立发布、失败可诊断

- 分析交付改为“可见卡片优先、成功的环节独立发布”：模型 token 耗尽时仍发布已完成的受限卡片；
  卡片重分析与整页缓存、年度卡发布相互隔离，避免一张卡失败拖垮整页。
- 手动分析链路收敛：强制显式重算、点击卡片重新排队、静默的按卡文本操作；手动年度刷新读取
  AP 数据信封；分析耗时与刷新状态移到动作之后展示。
- 失败诊断可追溯：脱敏后的失败诊断持久化、表筛选去重，注册补充阶段的错误也进入后端诊断。
- 组合分析可独立运行并增量交付，同步升级 BI SDK；分析仅受 AP 约束时按卡显示进度并与元数据同步。
- 证据与文案：MCP 画布页渲染完整证据；卡片摘要保持纯文本，行动计划统一归入 recommendations；
  移除前两个页签上的宿主分析工具栏。
- 模型层：省略 DeepSeek 空 assistant 轮并保留模型族信息；预加载观测与 DeepSeek 工具历史分离。
- 客户交付构建：统一手动模式、精确回执与可复现的客户构建（`deploy/customer/Dockerfile`、
  `DEPLOYMENT.md`）。
- 主要文件：`bi_agent/cockpit/{frozen,refresh,router,main_service,dashboard_source}.py`、
  `bi_agent/web/static/cockpit/{cockpit.js,data-client.js,ai-publication-client.js}`、
  `bi_agent/llm/provider_deepseek.py`、`docs/specs/cockpit-{priority-manual-refresh,backend-diagnostics,completed-fixes-integration-2026-11-09}.md`、`DEPLOYMENT.md`。

### 2026-11-10 组合分析卡对齐原型，AP 契约与 DeepSeek 重放保护

- 组合分析卡按原型对齐：色板 token、数字高亮、风险—成因编号、区块改用“成因”语义，移除风险
  总览元数据块；审阅性风险与风险关联行动进入卡片。
- 取数稳健性：被拒绝的 AP 指标组合拆分处理；按已实现的 AP 契约取数；DeepSeek 重放保护；
  用业务维度替代“数据缺口”结论。
- 有界卡片交付稳定化，风险发现按契约渲染（`tests/test_cockpit_opportunity_v2.py`、
  `tests/cockpit_stage_risk_format.test.mjs` 等）。
- 正式版本补录：补全 `docs/versions/README.md` 中 0.1.5–0.1.9 索引，补录 0.1.11–0.1.14
  版本文档，并把 0.1.6–0.1.10 发布补录并入 cockpit 交付分支。

### 2026-11-11 商机获取 V2 规则化：规则由本体驱动、AP 回退、证据与风险判定

- 新增 `bi_agent/cockpit/opportunity_v2.py` 与 `bi_agent/cockpit/assets/opportunity-v2/config.json`，
  由本体规则驱动商机获取卡，AP 作为回退；新增 `scripts/build_opportunity_v2_config.py` 生成配置，
  规则说明见 `docs/specs/cockpit-opportunity-v2-rules.md`。
- 回退与边界加固：聚合回退、进度与确认签约隔离、既有商机文本校验不覆盖、V2 证据交付加固。
- 模型判定 V2 风险；先行接入 V3 建议与证据规则；证据计数暴露给风险卡模板；建议负责人样式调整。
- 主要文件：`bi_agent/cockpit/{opportunity_v2,delivery,frozen}.py`、
  `bi_agent/cockpit/assets/opportunity-v2/config.json`、`bi_agent/web/static/cockpit/`、
  `tests/test_cockpit_opportunity_v2.py`。

### 2026-11-11 Process360 客户物理 schema 适配与客户本体随镜像交付

- `bi_agent/process360/{catalog,queries,service}.py` 按客户物理 schema 改造固定查询，新增
  `tests/test_process360_customer_physical_sql.py`（141 项断言规模）；交付文档
  `docs/specs/process360-customer-ontology-delivery-2026-11-03.md` 同步更新。
- 客户镜像内置校验后的客户本体：新增 `scripts/build_customer_image.sh`，`bi_agent/web/customer.py`
  与 `deploy/customer/Dockerfile` 支持镜像内本体入口，扩展 `tests/test_customer_cockpit_entrypoint.py`，
  `DEPLOYMENT.md` 补充交付与启动说明。

### 2026-11-12 商机获取 V3 本体、规则优先裁决与逐项证据

- 采用 V3 本体与 `V3_含SQL` 工作簿的指标 SQL（`assets/opportunity-v3/config.json` 大幅重生成）；
  再收敛为 V3 精简关联版并支持对未解释风险推断成因。
- 期间与口径：页面的业务年度不再取浏览器时钟，期间过滤固定到 2025 业务年度；C05 查询按业务
  年度执行并显示风险指标。
- 规则与证据：规则已定的风险标签不再导致整卡失败；风险卡详情显示规则、本体与 SQL 证据，
  以及查询执行记录；证据计数与覆盖缺口写入 `docs/亿纬锂能/商机卡_AP证据能力与缺口清单.md`。
- 本体口径清理：移除商机卡本体中的投标部分，不再按审批状态过滤商机；模型 JSON 修复与 V3
  阈值从本体读取；目标与预测读取已填充的电力字段。
- 主要文件：`bi_agent/cockpit/{opportunity_v2,opportunity_judgement,section_summary}.py`、
  `bi_agent/cockpit/assets/opportunity-v3/config.json`、`scripts/build_opportunity_v3_config.py`、
  `bi_agent/web/static/cockpit/insight-components/shared.js`、
  `tests/test_cockpit_opportunity_v2.py`。

### 2026-11-12 商机获取模型链路加固：非思考路由、预算、失败诊断与降级

- 风险裁决改为 rule-first：规则可判定的直接判定，仅未决项各发一次模型调用；卡片由代码按
  最小模型决策组装，未撰写分析的卡片不再沿用旧卡。
- 资源约束：单次模型调用限制在 11,999 token 预算内，发送前裁剪输入；环境配置模型 180s 预算；
  请求不携带工具；非思考模型路由在 allowlist 缺失时也能注册。
- 稳定性：模型修复有界、可恢复中断的流；手动分析中断时弹出说明对话框，失败对话框可展开诊断，
  并说明模型步骤停止的原因。
- 交互：支持单卡重分析；卡片各区块按展示项生成摘要；客户镜像可在无年度种子时启动。
- 主要文件：`bi_agent/cockpit/{opportunity_judgement,opportunity_v2,section_summary,frozen}.py`、
  `bi_agent/web/static/cockpit/{cockpit.js,cockpit.css}`、`bi_agent/llm/`、
  `tests/test_cockpit_opportunity_v2.py`、`tests/cockpit_insight_runtime.test.mjs`。

### 2026-11-13 销售额／出货量共同问题分析卡本体 V1/V2 与卡片接入

- 新增该卡本体 V1（`scripts/build_sales_shipment_ontology.py`、`亿纬锂能_本体_销售额出货量共同问题分析_V1.xlsx`），
  随后改为问题驱动的 V2（V2 工作簿与脚本重构）。
- 卡片按该本体运行“销售额／出货量共同问题分析”，覆盖数据获取与展示；补充该卡风险描述模板文档。
- 主要文件：`scripts/build_sales_shipment_ontology.py`、`docs/亿纬锂能/`、`bi_agent/cockpit/`、
  `tests/cockpit_sales_shipment_issues.test.mjs`。

### 2026-11-13 商机获取卡同步 V3 无投标/周期红字版，签约覆盖与目标能耗口径

- 商机获取卡同步到 V3“无投标、周期红字”本体版本；任务指令草稿对话框调整到所有卡片之上。
- 签约覆盖改为按商机预测总额度量；商机卡补充销售运营系统角色；目标能耗换算使用本体中的 kWh 因子。
- 主要文件：`bi_agent/cockpit/assets/opportunity-v3/config.json`、`bi_agent/cockpit/opportunity_v2.py`、
  `bi_agent/web/static/cockpit/`、`scripts/build_opportunity_v3_config.py`、
  `tests/test_cockpit_opportunity_v2.py`。