# V3 驾驶舱组件覆盖与元数据缺失（2026-10-22）

## 当前页面边界

- `/cockpit/home`：首页；交付 Tab“储能产品线整体经营分析”（模板 `2113106174095179778`）。
- `/cockpit/overview`：全局经营看板；`/cockpit` 的默认落点。
- `/cockpit/operations`：运营 360 整体分析。
- `/cockpit/analysis`：穿透式问题分析。
- 四页只加载看板本体；顶部保留四个 ProUI `pro-tabs` Tab：首页、全局经营看板、运营 360 整体分析、穿透式问题分析。
  不渲染左侧工作区、会话区、宿主页面标题或外层筛选栏；看板内部保留 `ProBiDashboard` 自带标题区。
  所有 Tab 和页内跳转保留当前 `id`。

## 渲染方式（2026-10-22 改为交付原样）

1. `metadata.py` 冻结 `iba-demo/feature/demo_1021` commit `7e45062deaebde11bb267539ff9a32f324bac4c6` 的
   `components.json`、`template-registry.json`、`insights.js`，并派生出 `insights.json`。
2. `runtime.py` 直接输出交付模板组件：`position`、`parentId`、`children`、`type`、容器、标题和样式不改；
   宿主只替换 `dataConfig`（注入冻结演示数据）并附加 `cockpitBindingKey`。
3. 不再按类型过滤、不再合成模板、不再追加卡片、不再重写位置或标题。未知类型交给 `ProBiDashboard` 占位。
4. 页面组件与 `template-registry.json` 逐字段一致（测试断言），差异只允许出现在 `dataConfig`／`tableColumnConfig`／
   `cockpitBindingKey`／`cockpitGraphData`，以及头盔图移除无法访问的远程 `processCode`。
5. 17 个 `insights` 按页面、按 `embedPath` 过滤后传入 `ProBiDashboard`；宿主用 `#insight-${id}` 插槽调用
   `POST /api/cockpit/analyses` 执行真实模型分析、轮询结果并回填。没有结果时保留空位或显示错误，不写固定结论。
6. 交付根组件（`components.json` 的复合筛选器＋三页 Tab 容器）没有直接挂载：宿主用路由和顶部 ProUI Tab 导航，
   页面内容来自各 Tab 对应的交付模板。`ProBiTabContainer` 没有受控 `activeTab`，无法用路由驱动。

## 交付覆盖

| 页面 | 交付组件 | 已绑定数据 | 分析插槽 | 主要组件 |
| --- | ---: | ---: | ---: | --- |
| 首页 | 9 | 6 | 1 | 5 个 `progress`、1 个 `mini-cpgraph`、1 个 `group`、1 个 `title`、1 个 `button-group` |
| 全局经营看板 | 9 | 5 | 0 | 5 个 `progress`、1 个 `template`、1 个 `group`、1 个 `button-group`、1 个 `title` |
| 运营 360 | 43 | 33 | 7 | 18 个 `kpiCard`、7 个 `group`、6 个 `share-bar`、5 个 `progress`、2 个 `horizontal-bar`、1 个 `mini-cpgraph`、1 个 `funnel` 等 |
| 穿透分析 | 10 | 6 | 9 | 5 个 `progress`、1 个 `mini-cpgraph`、1 个 `template`、1 个 `group` 等 |

运行包包含 15 份模板、139 个交付组件（2 个根组件＋137 个模板组件），其中 106 个组件带冻结演示数据。

## 未渲染与缺失项

| 缺口 | 影响 | 当前处理 |
| --- | --- | --- |
| `share-bar-79fsomq9` | 商机模板 `2112062888320483329/group-9ypz7vwt` 引用，但源配置没有定义 type、字段、数据或样式 | 分组中该位置空着 |
| 红区报价专项 | 缺少原因、型号／客户／区域分析、改善专题模板和入口动作 | 不补近似模板 |
| 毛利率／净利率／回款详情 | 缺少独立下钻模板、字段和动作契约 | 保留指标卡，不补详情页 |
| 图表下钻／客户操作列 | 缺少目标模板、参数和动作配置 | 保留交付表格与图表 |
| 运营周期对标／履约率第四卡 | 交付元数据没有对应组件或字段 | 不渲染 |
| 运营页模板区默认内容 | 交付头盔 `graphConfig.defaultActiveKey = "n1"` 与节点 ID 不匹配，首屏不选中节点 | 保持空位；点击头盔节点后加载对应模板和插槽，不回写默认节点 |
| 交付根筛选器 | `components.json` 的 D001 复合筛选器属于外层 Tab 画布，挂在根组件上 | 当前按页面模板挂载，未渲染根筛选器；字段口径仍需业务确认 |
| 真实 AP 指标映射 | 交付 AP 中的采购金额、采购时间维度与销售／出货标题不一致 | 保持演示数据，等待业务确认指标编码、日期维度和实体关联 |

页面底部“元数据缺失与渲染限制”会列出当前运行包记录的缺项。它只说明哪些位置没有渲染，不声称与原型 HTML 逐项一致。

## 数据口径冲突（保留原值）

- 原型订未发同时出现 `44.6／39.6／45.0` 亿元，并混有 2025／2026 日期；各区域保留原文，不能强行相加。
- 团队目标存在 `90／91`、`73／72` 等差异；未来月份是原型预测，不是实绩。
- 出货电量按 `319 亿元 = 91 GWh` 的模拟比例折算；产品部月度数据按原型分配公式生成，不是真实逐产品部统计。
- 交付里“越低越好”的指标（应收周转）没有方向标记，宿主不再补 `surplus` 样式；按组件原样展示。
- 静态 8876 页面使用 JSON 中的冻结数据；AI 插槽需要同源 `/api/cockpit`。当前 8876 经 nginx 代理到独立
  `172.16.10.34:8877` 的 cockpit API，并已用真实模型完成发货环节分析。

## 验证

- 驾驶舱相关契约测试 `37 passed`：源哈希、缺失子组件、运行包可复现性、页面组件与交付逐字段一致、四页插槽数量、`id` 路由和原任务接口。
- JavaScript 语法检查通过。
- 浏览器检查四个路由、四个 Tab、`id=1|2`、全局经营看板默认页、首页指标＋头盔＋风险插槽、运营和穿透头盔图、表格和 KPI 组件。
- 页面外层使用与 `iba-demo` 示例一致的灰底、20px 内容留白和 `ProBiDashboard` 发布态标题区，没有配置态拖入占位。
- 1440px 与 480px 视口无横向溢出。
- 真实模型调用已验证：首页 `focus-risks` 和穿透页 `sales-shipment-issues` 返回原因与证据数量；同一环节多个插槽共享一次分析结果。
