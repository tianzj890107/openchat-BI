# 前端交付元数据：feature/demo_1021

来源：[iba-demo](http://gitlab.boulderaitech.com/shimenglan/iba-demo/-/tree/feature/demo_1021)，
固定 commit `7e45062deaebde11bb267539ff9a32f324bac4c6`。
`components.json`、`template-registry.json` 和 `insights.js` 原样复制；`insights.json` 由声明式 `insights.js` 转为 JSON。
哈希、类型统计和已知问题见 `source.json`。

## 页面对应

| 页面 | Tab | 模板 ID |
| --- | --- | --- |
| 首页／储能产品线整体经营分析 | tab-qqzt1nj6 | 2113106174095179778 |
| 全局经营看板 | tab-bc6wp3k2 | 2112001069107167233 |
| 运营 360 整体分析 | tab-211tc4o0 | 2112434004503347202 |
| 穿透式问题分析 | tab-1suxx5hd | 2112061604959928321 |

根组件2个，子模板15份，共139个组件配置。
范围包含销售／出货目标、五类经营进度、运营头盔与节点明细、商机／订单／发货穿透等。
新版运行包已验证支持配置里的 `bar-line`、`progress`、`share-bar`、`tab-container` 等类型。

## 分析插槽

`insights.js` 现提供17个声明式插槽，覆盖运营页各环节概况与穿透页风险、原因、任务建议：

- 首页：`focus-risks`。
- 运营页：`bid-status-note`、`scheme-guide-summary`、`quote-summary`、`tech-plan-summary`、
  `bid-summary`、`order-sign-summary`、`shipment-summary`。
- 穿透页：`sales-shipment-issues`、`opportunity-risk`、`opportunity-coverage-note`、
  `sales-bid-summary`、`order-risk-summary`、`shipment-risk-summary`、
  `shipment-overdue-note`、`shipment-cause-breakdown`、`shipment-task-order`。

本轮同步插槽声明；AI 内容由宿主调用主服务模型生成，不复制示例网关鉴权和固定 AI 结论。

## 接入边界

本目录源 JSON 和 `insights.js` 保持冻结，现已由 `bi_agent/cockpit/metadata.py` 编译为当前 cockpit 的页面配置。
`GET /api/cockpit/metadata` 返回编译后的模板、显式数据绑定、插槽路径、适配记录与差异。
页面直接读取 `../runtime.json`：该文件由 `scripts/export_cockpit_runtime.py` 从同一编译结果导出，
包含年度图、运营头盔图和穿透头盔图的 ProUI 组件、绑定数据及视图挂载点，不依赖后端 API。
根 Tab 对应宿主四页导航；子模板继续使用交付 ID。运行时只移除插槽路径最外层 Tab 段。

AP中的采购指标与销售标题不一致，所有可取数组件均显式绑定 `fixtures/v3-prototype.json`；
没有生产网关调用，没有默认mock预设或按旧DemoSource比例生成的台账。
原型自身出货表中的91／319折算及产品部月度比例分配规则被保留，并明确是演示口径。
根D001采购日期筛选器不作为销售日期使用；页面仅开放原型固定期间／全产品部。
演示仓库的鉴权、浏览器token读取、网关代理及固定AI结论均未复制。

商机模板 `2112062888320483329` 的 `group-9ypz7vwt` 引用 `share-bar-79fsomq9`，
但交付中没有子组件定义。运行包不渲染该子项，并在缺项报告中列明，不猜测图形配置。
发货运营组合模板和头盔显式数据桥为宿主适配，源JSON不改写。
页面把交付页面模板原样交给 `ProBiDashboard`，并渲染 17 个 `insights` 插槽；节点入口卡、AI 卡片、周期对标和专项分析等
没有对应交付组件的位置不渲染。
完整差异及需补交内容见仓库 `docs/specs/cockpit-v3-metadata-gaps.md`。
