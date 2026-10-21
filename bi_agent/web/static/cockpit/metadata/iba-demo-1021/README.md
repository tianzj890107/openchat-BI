# 前端交付元数据：feature/demo_1021

来源：[iba-demo](http://gitlab.boulderaitech.com/shimenglan/iba-demo/-/tree/feature/demo_1021)，
固定 commit `55842efc2a788b9974da91a0e63afe1d6cd460f3`。
`components.json` 和 `template-registry.json` 原样复制；`insights.json` 由声明式 `insights.js` 转为 JSON。
哈希、类型统计和已知问题见 `source.json`。

## 页面对应

| 页面 | Tab | 模板 ID |
| --- | --- | --- |
| 全局经营看板 | tab-bc6wp3k2 | 2112001069107167233 |
| 运营 360 整体分析 | tab-211tc4o0 | 2112434004503347202 |
| 穿透式问题分析 | tab-1suxx5hd | 2112061604959928321 |

根组件2个，子模板14份，共130个组件配置。89项使用AP源，其余41项为mock配置。
范围包含销售／出货目标、五类经营进度、运营头盔与节点明细、商机／订单／发货穿透等。
新版运行包已验证支持配置里的 `bar-line`、`progress`、`share-bar`、`tab-container` 等类型。

## 分析插槽

- `scheme-guide-summary`：第二页方案引导子模板顶部。
- `sales-shipment-issues`：第三页 `group-dhflgwln` 后方。
- `opportunity-risk`：第三页商机子模板顶部。

源配置在第二页也预留了插槽；本轮保留交付原貌，不改变已确认的“前两页直接取数，第三页AI分析”行为。

## 接入边界

本目录为已冻结的**交付参考元数据**，当前 cockpit 不直接加载它；当前POC的演示数据和交互保持不变。
后续正式替换页面配置时，需要适配真实指标／维度编码、嵌套模板路径和数据查询接口。
例如根筛选器 D001 标注为采购订单创建时间，不能直接当成销售统计期间。
演示仓库的鉴权、浏览器token读取、网关代理及固定分析内容均未复制。

发现一处源配置缺项：商机模板 `2112062888320483329` 的 `group-9ypz7vwt` 引用
`share-bar-79fsomq9`，但本模板中没有这个子组件。本轮原样保留并记录，不伪造缺失配置。
