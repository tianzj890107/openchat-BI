# 前端交付元数据：feature/demo_1021

来源：[iba-demo](http://gitlab.boulderaitech.com/shimenglan/iba-demo/-/tree/feature/demo_1021)，
固定 commit `d01c08a07b79ba781f820524ff612f58cfa4e090`。
`components.json`、`template-registry.json`、`insights.js` 和 `activate-rules.json`
按上游原样复制；`insights.json` 由声明式 `insights.js` 转为 JSON。
哈希、类型统计、跳转规则数量和已知问题见 `source.json`。

## 页面对应

| 页面 | Tab | 模板 ID |
| --- | --- | --- |
| 经营看板 | tab-bc6wp3k2 | 2112001069107167233 |
| 运营 360 整体分析 | tab-211tc4o0 | 2112434004503347202 |
| 穿透式问题分析 | tab-1suxx5hd | 2112061604959928321 |

根组件 2 个，子模板 13 份，共 145 个组件配置，其中 106 个声明 AP 数据、39 个仍使用
上游 mock 配置。数据尚未配置完整的组件由原组件展示错误或空态，宿主不读取旧原型快照补数。

## 数据请求

新组件按本体库 8 的单查契约运行：

```text
POST /api/gateway2/x360/v1/ontology/data/query
X-Ontology-Repository-Id: 8
```

页面只注入 `postAnalysisDataQuery`，不注入批量适配器。ProUI 新版在批量适配器缺失时，
按单个查询并发兜底；批量接口仍在请求本体、当前不可用，因此不能把批量错误包装成空结果。

## 页内跳转

`activate-rules.json` 共 6 条规则，由新版 `pro-bi-ui.min.js` 消费。规则可以组合
`switchTab` 与 `selectHelmet`，例如“查看销售额风险”从经营看板跳到穿透式问题分析，
并选中 `mini-cpgraph-93j6k86p` 的“商机获取”节点 `2109840325158682625`。
宿主把跨 Tab 动作转换为现有三页路由，并在目标页恢复节点选择。

## 分析插槽

`insights.js` 提供 12 个声明式插槽，位置如下：

- 经营看板：无。
- 运营页：`bid-status-note`、`quote-summary`、`bid-summary`、`order-sign-summary`。
- 穿透页：`sales-shipment-issues`、`opportunity-risk`、`opportunity-coverage-note`、
  `order-risk-summary`、`shipment-risk-summary`、`shipment-overdue-note`、
  `shipment-cause-breakdown`、`shipment-task-order`。

插槽内容调用主服务 `/api/cockpit/analyses`，页面运行时组件保留真实加载、错误、重试和
任务卡状态；不直接覆盖为上游静态文案。

## 接入边界

前端只读取导出的 `metadata/runtime.json`。AP 地址、仓库 ID 和认证只从主服务
`COCKPIT_AP_*` 配置读取，浏览器不能指定上游 URL、请求头或证据正文。

商机模板 `2112062888320483329` 的 `group-9ypz7vwt` 仍引用不存在的
`share-bar-79fsomq9`。运行包保留原位置为空并写入缺项报告，不猜测图形配置。
