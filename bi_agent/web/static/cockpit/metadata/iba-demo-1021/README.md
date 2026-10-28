# 前端交付元数据：储能经营风险驾驶舱

原始来源：[iba-demo](http://gitlab.boulderaitech.com/shimenglan/iba-demo/-/tree/feature/demo_1021)，
固定 commit `558f2ae27cdc5a9569c5d91a1db45f97d31a4321`（2026-10-26 首次导入）。
看板现已改由 `pdt-dev` 发布，当前内容按发布配置重新导入：

| 项 | 值 |
| --- | --- |
| 发布看板 | `2109836674373566465` 储能经营风险驾驶舱 |
| 根配置最后更新 | 2026-10-28 14:07:56 |
| 导入日期 | 2026-10-28 |
| 模板最后更新区间 | 2026-10-23 ～ 2026-10-28 16:02 |

`components.json`、`template-registry.json` 由 `scripts/import_cockpit_publish.py` 从
`dashboard.json` 和 `templates/*.json` 原样转换；哈希、类型统计、插槽锚点、宿主适配和已知缺口
记录在 `source.json`。只有两处宿主侧转换，均在 `source.json.adaptations` 列明：

1. 发布配置把 `activateRules` 放在仪表盘根级，ProUI 只从组件 `baseConfig.activateRules` 注册，
   导入时回填到 `tab-container-zm9eyxne`（与上一版交付形态一致）。
2. 新规则的 `actions` 数组改写为 ProUI 的 `tab` / `helmet` 结构；无法表达的规则
   （当前 1 条 `titleText` 表面）列入 `source.json.unsupportedRules`，不猜测行为。

## 页面对应

| 页面 | Tab | 模板 ID |
| --- | --- | --- |
| 经营看板 | tab-bc6wp3k2 | 2112001069107167233 |
| 运营 360 整体分析 | tab-211tc4o0 | 2112434004503347202 |
| 穿透式问题分析 | tab-1suxx5hd | 2112061604959928321 |

根组件 2 个，子模板 13 份，共 142 个组件配置（AP 103 个、mock 39 个）。
本次发布在运营页新增“订单履约率”KPI、五环节分段条（商机获取／报价／投标／订单接收／发货）
和对应进度卡，并把经营看板指标从采购口径切换为 `YWLN_*` 销售口径。

## 分析插槽

`insights.js` 提供 12 个声明式插槽，位置如下：

- 经营看板：无。
- 运营页：`bid-status-note`、`quote-summary`、`bid-summary`、`order-sign-summary`。
- 穿透页：`sales-shipment-issues`、`opportunity-risk`、`opportunity-coverage-note`、
  `order-risk-summary`、`shipment-risk-summary`、`shipment-overdue-note`、
  `shipment-cause-breakdown`、`shipment-task-order`。

本次发布未改动这 12 个锚点组件，锚点校验在导入脚本和 `runtime.json` 缺项报告中执行。
插槽内容调用主服务 `/api/cockpit/analyses` 的真实模型分析，按可见插槽串行调度；
`insight-components/` 保留为交付原始文件，页面不再加载其静态文案。

## 接入边界

`components.json`、`template-registry.json`、`insights.js` 和 `insight-components/` 保持交付原样，
由 `bi_agent/cockpit/runtime.py` 导出为 `metadata/runtime.json`。页面只读取导出的 runtime 和
`pdt-release-2109836674373566465/data-snapshots.json`（显式回放模式），实时模式下通过主服务 AP 代理取数。

卡片上的 `headerActions`（如“查看销售额风险／查看出货风险”）由交付的 `activateRules` 驱动：
运行时把切换 Tab 与选中头盔图节点同步到宿主路由，跳转后保留 `id` 与 `node` 参数。

商机模板 `2112062888320483329` 的 `group-9ypz7vwt` 仍引用 `share-bar-79fsomq9`，
交付中没有该子组件定义。运行包保留空位并在缺项报告中列明，不猜测图形配置。
完整差异及需补交内容见仓库 `docs/specs/cockpit-v3-metadata-gaps.md`。
