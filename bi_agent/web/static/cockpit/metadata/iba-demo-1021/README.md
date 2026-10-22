# 前端交付元数据：feature/demo_1021

来源：[iba-demo](http://gitlab.boulderaitech.com/shimenglan/iba-demo/-/tree/feature/demo_1021)，
固定 commit `37975c7a03719c037b4acca70c38b50fb68f4516`。
`components.json`、`template-registry.json`、`insights.js` 和 `insight-components/` 原样复制；
`insights.json` 由声明式 `insights.js` 转为 JSON。哈希、类型统计和已知问题见 `source.json`。

## 页面对应

| 页面 | Tab | 模板 ID |
| --- | --- | --- |
| 经营看板 | tab-bc6wp3k2 | 2112001069107167233 |
| 运营 360 整体分析 | tab-211tc4o0 | 2112434004503347202 |
| 穿透式问题分析 | tab-1suxx5hd | 2112061604959928321 |

根组件 2 个，子模板 13 份，共 122 个组件配置。
范围包含五类经营进度、运营头盔与节点明细、商机／订单／发货穿透、流程弧形图等。
运行包已验证支持配置里的 `process-arc`、`mini-cpgraph`、`bar-line`、`progress`、
`share-bar`、`funnel`、`segmented-strip` 和 `tab-container` 等类型。

## 分析插槽

`insights.js` 提供 12 个声明式插槽，位置如下：

- 经营看板：无。
- 运营页：`bid-status-note`、`quote-summary`、`bid-summary`、`order-sign-summary`。
- 穿透页：`sales-shipment-issues`、`opportunity-risk`、`opportunity-coverage-note`、
  `order-risk-summary`、`shipment-risk-summary`、`shipment-overdue-note`、
  `shipment-cause-breakdown`、`shipment-task-order`。

插槽位置按交付配置挂载，内容调用主服务 `/api/cockpit/analyses` 的真实模型分析。
页面加载后利用空闲时间预取商机、报价、投标、订单、发货 5 个环节，点击节点时直接展示预热结果。
`insight-components/` 保留为交付原始文件，当前页面不再加载其静态文案。

## 接入边界

`components.json`、`template-registry.json`、`insights.js` 和 `insight-components/` 保持交付原样，
由 `bi_agent/cockpit/metadata.py` 编译为 `metadata/runtime.json`。页面只读取导出的 runtime 和
`pdt-release-2109836674373566465/data-snapshots.json`，不访问 AP、PDT 或生产接口。
`GET /api/cockpit/metadata` 返回编译后的模板、插槽路径、适配记录与差异。

AP 中的采购指标与销售标题可能不一致，页面保留交付原值；未捕获的查询显示组件自带的
“未找到该 AP 查询的发布快照”，不补造数据。
交付仓库的鉴权、浏览器 token、网关代理和固定 AI 结论均未复制。

商机模板 `2112062888320483329` 的 `group-9ypz7vwt` 引用 `share-bar-79fsomq9`，
但交付中没有子组件定义。运行包保留空位并在缺项报告中列明，不猜测图形配置。
完整差异及需补交内容见仓库 `docs/specs/cockpit-v3-metadata-gaps.md`。
