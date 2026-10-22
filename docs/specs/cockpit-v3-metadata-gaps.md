# V3 驾驶舱交付覆盖与缺失（2026-10-22）

## 当前交付

- 来源：`http://gitlab.boulderaitech.com/shimenglan/iba-demo`，分支 `feature/demo_1021`，
  commit `37975c7a03719c037b4acca70c38b50fb68f4516`。
- 渲染入口：一个 `ProBiDashboard`，直接接收交付根配置和 13 份模板注册表。
- 根组件：`composite-filter-hzjk9t5q`、`tab-container-zm9eyxne`。
- 三个 Tab：经营看板、运营360整体分析、穿透式问题分析。
- 组件规模：13 份模板、122 个组件配置（含 2 个根组件）。
- 插槽组件：交付 `insight-components/` 共 12 个静态组件，`insights.json` 声明 12 个插入位置。
- 本运行包模板和组件类型检查：通过；三个页面均无 ProUI 组件错误。

## 页面映射

| 路由 | Tab | 模板 |
| --- | --- | --- |
| `/cockpit/overview` | 经营看板 | `2112001069107167233` |
| `/cockpit/operations` | 运营360整体分析 | `2112434004503347202` |
| `/cockpit/analysis` | 穿透式问题分析 | `2112061604959928321` |
| `/cockpit/home` | 兼容入口（FastAPI 307／静态站客户端改写） | 不单独渲染 |

三个路由只激活对应 Tab，并保留 Fuxi 传入的 `id=1|2`。两个 `id` 当前看到完全相同的看板和功能。

## 数据回放

`data-snapshots.json` 保存 pdt 正式页浏览器网络中的响应体：

- AP 查询：39 个。
- 批量查询：3 个。
- 头盔图请求：4 个。

页面通过 `ProUIBi.configureBi` 按规范化请求键回放，不访问 PDT、AP 或生产接口。
快照不包含 Cookie、Token、账号或用户身份。本次新增且未捕获的查询会在原卡片显示组件自带的
“未找到该 AP 查询的发布快照”，宿主不补造数据。

## 智能分析插槽

交付根配置本身没有 `insights` 字段。宿主从 `iba-demo-1021/insights.json` 补入 12 个插槽声明，
并保留完整 Tab `embedPath`：

- 经营看板 0 个。
- 运营 360 4 个：`bid-status-note`、`quote-summary`、`bid-summary`、`order-sign-summary`。
- 穿透式问题分析 8 个：`sales-shipment-issues`、`opportunity-risk`、`opportunity-coverage-note`、
  `order-risk-summary`、`shipment-risk-summary`、`shipment-overdue-note`、
  `shipment-cause-breakdown`、`shipment-task-order`。

本轮插槽内容直接使用交付 `insight-components/` 的静态组件，不预加载、不轮询、不调用模型。
穿透页默认显示 3 个插槽；点击头盔图订单接收和发货节点后，其余插槽按所切换的模板挂载。
主服务 `/api/cockpit` 的实时分析、历史和任务令接口继续保留，后续需要实时 AI 时再接入页面。

## 已知差异

以下现象来自交付配置和交付数据本身，宿主未改写：

- 商机模板 `2112062888320483329` 的 `group-9ypz7vwt` 引用 `share-bar-79fsomq9`，
  但交付没有该子组件定义；运行包保留空位并在此列明，不猜测图形配置。
- 五个进度卡当前绑定同一批 AP 采购指标，数值和完成率相同。
- 卡片标题与实际 AP 指标口径可能不一致，例如销售类标题绑定采购金额／采购时间维度。
- 顶部“采购订单创建时间维度”按交付配置只联动当前 Tab 的一个指标卡：
  经营看板联动“促进增长｜销售额”，运营 360 联动“保障交付｜出货量”；其余卡片没有声明该维度绑定。
  宿主不自行扩展联动范围。
- 交付模板和组件标题保留源配置原值；路由标题使用“经营看板”“运营360整体分析”“穿透式问题分析”。

## 验证

- 驾驶舱契约测试 `37 passed`。
- `node --check bi_agent/web/static/cockpit/cockpit.js` 通过。
- 浏览器检查 `overview`、`operations`、`analysis` 在 `id=1|2` 下均能激活正确 Tab，只有一个
  `ProBiDashboard`，无组件错误。
- 运营页头盔图切换到报价、投标、订单接收节点时分别出现报价、投标、订单签单插槽；
  穿透页切换到订单接收、发货节点时分别出现订单风险、发货风险／超期／主因／任务令插槽。
- 时间筛选切换到 `2026-08-13 19:06:09` 后无组件错误，销售额卡更新，其余卡保持不变。
- 页面不请求 AP；所有查询命中本地发布快照。
