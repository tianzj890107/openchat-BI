# 前端交付元数据：feature/demo_1021

来源：[iba-demo](http://gitlab.boulderaitech.com/shimenglan/iba-demo/-/tree/feature/demo_1021)，
固定 commit `cdaa3b683489e911fdf62d2d1d80b6ee265c8727`。
`components.json`、`template-registry.json`、`insights.js` 和 `activate-rules.json`
按上游原样复制；`insights.json` 由声明式 `insights.js` 转为 JSON。
哈希、类型统计、跳转规则数量和已知问题见 `source.json`。

## 页面对应

| 页面 | Tab | 模板 ID |
| --- | --- | --- |
| 经营看板 | tab-bc6wp3k2 | 2112001069107167233 |
| 运营 360 整体分析 | tab-211tc4o0 | 2112434004503347202 |
| 穿透式问题分析 | tab-1suxx5hd | 2112061604959928321 |

根组件 2 个，子模板 13 份，共 142 个组件配置，其中 103 个声明 AP 数据、39 个仍使用
上游 mock 配置。数据尚未配置完整的组件由原组件展示错误或空态，宿主不读取旧原型快照补数。

## 数据请求

新组件按本体库 8 的单查契约运行：

```text
POST /api/gateway2/x360/v1/ontology/data/query
X-Ontology-Repository-Id: 8
```

新版头盔组件支持元数据配置 `graphConfig.helmetViewUrl`。上游交付值指向演示环境
`172.16.5.230`，浏览器不能直连；运行包导出时统一改写为
`/api/gateway2/x360/v1/graphs/helmet-view`，再由主服务携带凭据请求 AP，页面不接触
内网 AP 地址或认证信息。

页面只注入 `postAnalysisDataQuery`，不注入批量适配器。ProUI 新版在批量适配器缺失时，
按单个查询并发兜底；批量接口仍在请求本体、当前不可用，因此不能把批量错误包装成空结果。

## 页内跳转

`activate-rules.json` 共 6 条规则，由新版 `pro-bi-ui.min.js` 消费。规则可以组合
`switchTab` 与 `selectHelmet`，例如“查看销售额风险”从经营看板跳到穿透式问题分析，
并选中 `mini-cpgraph-93j6k86p` 的“商机获取”节点 `2109840325158682625`。
宿主把跨 Tab 动作转换为现有三页路由，并在目标页恢复节点选择。

## 分析插槽

`insights.js` 提供 15 个声明式插槽，位置如下：

- 经营看板：无。
- 运营页：`bid-status-note`、`quote-summary`、`bid-summary`、`order-sign-summary`、
  `star-product-order-list`。
- 穿透页：`sales-shipment-issues`、`opportunity-risk`、`opportunity-coverage-note`、
  `order-risk-summary`、`affected-order-list`、`shipment-risk-summary`、
  `shipment-overdue-note`、`shipment-cause-breakdown`、`overdue-order-list`、
  `shipment-task-order`。

插槽内容调用主服务 `/api/cockpit/analyses`，页面运行时组件保留真实加载、错误、重试和
任务卡状态；不直接覆盖为上游静态文案。

## 订单 DataTable

本次同步启用三张订单表，布局和列配置复用上游 `ProDataTable`：

- 订单接收「明星产品订单电量及占比」：返回系列、去年参考电量、订单接收电量、
  占全部订单电量和已登记口径。
- 订单接收「受影响订单清单」：AP 事实字段之外，按证据中实际出现的订单号合并原因和
  责任动作；事实列包含变更类型、减少电量和影响金额，并固定筛选变更/取消订单。
- 发货「客户与超期订单」：AP 事实字段之外，按证据中实际出现的订单号合并主因和具体
  根因；事实列固定筛选超期天数大于 0 的订单。

上游三张表分别调用 `/api/mock/star-product-scope`、`/api/mock/affected-order-extra` 和
`/api/mock/overdue-order-root-cause`。本仓库不复制这些 mock，统一改走
`POST /api/cockpit/ai-tables/{tableKey}/query`：事实数据仍由主服务按 AP 单查契约取得，
AI 文字只从当前范围已发布且通过交付校验的环节卡片按订单证据合并。没有匹配证据的行
显示“证据不足，未确认根因”或“待核实原因后明确责任动作”，不借用其他订单的结论。

## 接入边界

前端只读取导出的 `metadata/runtime.json`。AP 地址、仓库 ID 和认证只从主服务
`COCKPIT_AP_*` 配置读取，浏览器不能指定上游 URL、请求头或证据正文。

商机模板 `2112062888320483329` 的 `group-9ypz7vwt` 仍引用不存在的
`share-bar-79fsomq9`。运行包保留原位置为空并写入缺项报告，不猜测图形配置。

发货模板中的 `shipment-task-order` 已按上游新配置落在 `share-bar-zob5z1uu` 之后，
不再依赖不存在的 `table-md1iftaj`；运行包按插槽数组顺序排在客户与超期订单列表之后。
