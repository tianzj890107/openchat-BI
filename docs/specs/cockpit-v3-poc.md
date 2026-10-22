# V3 经营驾驶舱 POC

## 已确认边界（2026-10-22）

- analytics 主服务提供三个独立看板入口：`/cockpit/overview`、`/cockpit/operations`、`/cockpit/analysis`；`/cockpit` 与 `/` 直接返回 `overview`。`/cockpit/home` 保留为兼容地址（FastAPI 307、静态站客户端改写为 `overview`），不再单独渲染第四个页面。现有 `/workbench`、旧驾驶舱及 MCP 不替换。
- 三个页面只渲染看板本体，页面挂载 `iba-demo` 交付看板 `feature/demo_1021@37975c7` 的一个完整 `ProBiDashboard`；顶部筛选器和三个 Tab 均来自交付根配置，不再由宿主手写。
- 三个 Tab 分别为“经营看板”“运营360整体分析”“穿透式问题分析”；页面不包含宿主工作区、会话区、页面标题或第二套导航。
- `/cockpit/overview`、`/cockpit/operations`、`/cockpit/analysis` 只负责激活对应 Tab，并保留当前 `id`；页内 Tab 切换同步地址。
- 两个演示身份使用 Fuxi 传入的单一查询参数 `id`：`id=1` 对应总裁，`id=2` 对应分析员。当前三个页面内容对两个 `id` 完全一致，两个人都可以访问和操作；`id` 只作身份标记并为将来差异化预留。页面和 API 不使用 `role`，`/cockpit` 跳转和页内跳转都保留当前 `id`。
- 交付根配置本身没有 `insights` 字段，宿主从 `iba-demo-1021/insights.json` 补入 12 个插槽声明，并保留完整 Tab `embedPath`。插槽位置按交付配置挂载，内容改为调用 `/api/cockpit/analyses` 的真实模型分析；页面加载后利用空闲时间预取商机、报价、投标、订单、发货 5 个环节，不等到点击才开始。
- 三个页面读取同一份静态发布包和 AP 响应快照；快照不包含 Cookie、Token 或用户身份。
- 正式配置中的 AP 指标口径与卡片标题不一致时保持原值，不在宿主层修正；真实本体＋数据库映射需要后续业务确认。
- 模拟任务令、分析历史和任务接口仍在主服务侧保留，但当前交付看板页面不渲染旧任务抽屉。
- 已有业务预测展示＋显式假设的情景测算；不建设统计预测模型。
- 静态看板资源与旧工作台隔离；是否部署以当前任务中出现的明确部署授权为准。

## 页面与组件

静态资源位于 `bi_agent/web/static/cockpit/`。页面直接使用交付包的根配置、13 份模板和组件注册表，通过 `ProBiDashboard` 渲染原生 ProUI 卡片；不再使用原型 DOM、宿主布局占位或手写 Tab。

| 页面 | 默认内容 |
| --- | --- |
| 经营看板 `/cockpit/overview` | 交付模板 `2112001069107167233`；`/cockpit` 的默认落点 |
| 运营 360 `/cockpit/operations` | 交付模板 `2112434004503347202`；包含指标、运营头盔、漏斗和环节卡片 |
| 穿透分析 `/cockpit/analysis` | 交付模板 `2112061604959928321`；包含穿透图、风险结构、明细表和风险插槽 |
| 兼容入口 `/cockpit/home` | FastAPI 307／静态站客户端改写为 `/cockpit/overview`；不单独渲染页面 |
| 公共 | 根 `composite-filter` 和根 `tab-container` 由 `ProBiDashboard` 直接渲染；三个路由同步当前 Tab 并保留 `id` |

入口示例：`/cockpit/overview?id=2`、`/cockpit/operations?id=2`、`/cockpit/analysis?id=1`。
支持 `APP_ROOT_PATH` 下静态资源地址。纯看板页面不渲染旧的角色切换、分析历史或任务抽屉。

## 数据契约和口径

交付目录 `static/cockpit/metadata/iba-demo-1021/` 保存 `components.json`、`template-registry.json`、
`insights.js`、`insights.json`、`insight-components/` 和原始 hash；`runtime.py` 只做浏览器安全导出，
不改组件、位置或样式。浏览器只读取合并后的 `metadata/runtime.json` 和本地 AP 快照。

- 根配置包含 2 个组件：`composite-filter-hzjk9t5q` 和 `tab-container-zm9eyxne`。
- 交付包共 13 份模板、122 个组件配置（含根组件）；三个 Tab 引用的模板全部存在。
- `ProBiDashboard` 直接接收根 `components` 和 `template-registry`；三个路由只激活对应 Tab。
- `data-snapshots.json` 保存 pdt 正式页网络中的 39 个 AP 查询、3 个批量查询和 4 个头盔图请求响应；浏览器通过 `configureBi` 回放，不访问 PDT 或生产接口。
- 快照只保存业务响应体，不保存 Cookie、Token、账号或用户身份；发布目录记录文件大小和 SHA-256。
- 未捕获的查询在原卡片显示交付组件自带的“未找到该 AP 查询的发布快照”，宿主不补造数据。
- 交付配置没有 `insights` 字段；页面使用交付目录的 12 个插槽声明：运营 360 4 个、穿透式问题分析 8 个、经营看板 0 个。AP 指标与标题的口径差异保持源配置原值。
- 已知源配置缺项：商机模板 `2112062888320483329` 的 `group-9ypz7vwt` 引用 `share-bar-79fsomq9`，交付未包含该子组件定义；运行时保留空位并在差异报告中列明。

## 智能分析插槽

插槽使用交付 `insight-components/` 的原始组件名称、DOM 和 CSS，内容由主服务真实模型分析驱动。
阶段数字读取当前分析证据包的 `facts`，记录级主因读取 `records`，风险、原因、建议和限制读取
`result.summary`、`result.causes`、`result.recommendations`、`result.limitations`；缺失字段显示
“未提供”，不再保留交付目录里的演示数字或静态文案。页面加载完成后通过 `requestIdleCallback`
（不支持时回退 800ms 定时）预取 5 个环节：商机、报价、投标、订单、发货；每个环节只发起一次分析，
前端最多 3 个并发，其余排队。插槽挂载时复用同一 Promise，点击头盔节点不会重新请求；只有组件内重试
才强制刷新。插槽入口从自身 URL 读取版本串，再以同一版本动态加载 registry、shared 和 12 个子组件；
CSS 查询串也使用该版本，避免部署后继续命中旧模块或旧样式缓存。

分析结果使用 `compact-v1` 契约：摘要、原因、措施和验收只保留可执行短文本，责任角色为单一角色，
期限改用 `deadlineDays` 工作日，补充背景放入可选 `detail`；缓存 scope 包含契约版本，旧结果不会被
继续复用。前端将摘要限制为 3–4 行，原因、证据和限制默认折叠，建议按“措施 + 责任角色 + 期限 +
验收”紧凑排列。含内嵌插槽的 ProUI 卡片为图表/KPI 区保留自适应最小高度，插槽使用剩余空间并在
内部滚动，避免固定卡片高度把 KPI 子卡压缩为 0–8px。

运营页默认显示 `bid-status-note`，点击头盔节点后按对应模板挂载 `quote-summary`、`bid-summary`、
`order-sign-summary`；穿透页默认显示 `sales-shipment-issues`、`opportunity-risk`、
`opportunity-coverage-note`，点击订单接收和发货节点后挂载 `order-risk-summary`、
`shipment-risk-summary`、`shipment-overdue-note`、`shipment-cause-breakdown`、`shipment-task-order`。
首次分析通常约 10–20 秒，已完成范围复用 SQLite 中的结果；失败时显示错误和重试。

## API

| 方法／地址（前缀 `/api/cockpit`） | 用途 |
| --- | --- |
| GET `/bootstrap` | 角色、期间、部门、环节、数据模式 |
| GET `/metadata` | 当前页面模板、显式绑定、插槽、差异及适配记录 |
| GET `/snapshot?period=&department=&source=prototype` | 原型固定快照（不传 source 保留旧 demo 契约） |
| GET `/evidence?period=&department=&stage=&source=prototype` | 当前环节事实、明细、证据 |
| POST `/analyses` | id、period、department、stage、source、refresh；返回分析任务 |
| GET `/analyses?id=` | 当前身份历史，可按期间和部门筛选 |
| GET `/analyses/{id}` | 状态、进度、工具取证记录、结果 |
| POST `/analyses/{id}/cancel` | 停止；不删除记录 |
| GET `/analyses/{id}/report` | 完成后的转义 HTML 报告 |
| POST `/analyses/{id}/draft` | 基于完成结果幂等创建任务草稿 |
| GET `/tasks`、`/tasks/{id}` | 模拟任务及状态 |
| POST `/tasks/{id}` | 带 revision 的保存／下发／接收／反馈／关闭 |

错误：422 无效范围／字段、404 未知记录、409 状态或版本冲突、429 分析并发已满。
`id=1|2` 是 Fuxi 传入的唯一身份参数，当前不作为页面或操作权限依据；分析历史仍按 `id` 归属保存。

## 持久化与恢复

服务工作目录下 `dataset/cockpit/history.sqlite3`，已 gitignore。SQLite 事务和 revision 防止覆盖更新。
不与现有会话表混用，不提供清空或删除接口。分析缓存及任务按分析 ID 关联。
本 POC 使用单进程内存任务执行器；服务首次打开存储时把未结束分析标记为 interrupted，保留证据并可重试。
正式多 worker 部署需使用共享任务协调器替换内存作业管理，不应直接多进程运行这个 POC 执行器。

## 资源

ProUI 资源随 `iba-demo@37975c7` 更新，冻结 SHA 见 `static/cockpit/vendor/resources.json`。
旧工作台 BI 包保持不变；cockpit 使用新版 `pro-bi-ui.min.js`（`011269f8`）与 `pro-ui.min.css`（`b1ee836d`）。
页面渲染入口是 `ProBiDashboard`，组件类型映射包括 `ProKpiCard`、`ProProgressCard`、`ProDataTable`、`ProBarChart`、`ProDualAxisChart`、`ProHorizontalBarChart`、`ProFunnelChart`、`ProShareBar`、`ProMiniCpGraph`、`ProTitle`、`ProButtonGroup` 及分组／模版容器。
Vue 版本为 3.5.25，哈希一致，复用原有文件。
资源文档：<http://pro-ui.eimos.com/bi-components/setup/>、<http://pro-ui.eimos.com/bi-components/dashboard/>。

## 验证

离线契约测试：

```bash
/path/to/venv/bin/python -m pytest -q \
  tests/test_cockpit_poc.py tests/test_cockpit_resource_contract.py tests/test_cockpit_metadata.py
```

当前结果：`40 passed`。JavaScript 语法检查：

```bash
node --check bi_agent/web/static/cockpit/cockpit.js
```

浏览器验收使用独立临时工作目录，避免接触用户会话。已检查：

- 三条路由均返回 200，`/cockpit` 跳到 `overview`，`/cockpit/home` 在静态站加载后改写为 `overview`（FastAPI 直接 307）。
- 页面只有一个 `ProBiDashboard`，顶部根筛选器和三个 Tab 由交付配置生成；页内 Tab 切换同步 URL 并保留 `id=1|2`。
- 三条路由分别激活“经营看板”“运营360整体分析”“穿透式问题分析”；`id=1` 与 `id=2` 内容一致。
- 运营页加载后后台出现报价、订单等尚未显示环节的分析任务，证明空闲预取生效；点击节点后插槽直接显示已完成结果。
- 三个页面均无组件错误；运营页头盔图切到报价、投标、订单接收节点时分别挂载 `quote-summary`、`bid-summary`、`order-sign-summary`，穿透页切到订单接收和发货节点时挂载 `order-risk-summary` 与 4 个发货插槽。
- 穿透页默认显示 3 个插槽；12 个交付插槽位置均挂载真实模型分析，页面空闲时预取 5 个环节。
- 页面只回放本地 `/static/cockpit/metadata/pdt-release-2109836674373566465/data-snapshots.json` 中的请求，不访问 AP。
- 时间筛选切换到 `2026-08-13 19:06:09` 后无组件错误、无未捕获快照，销售额卡按交付绑定更新，其余卡保持不变（与交付筛选绑定范围一致）。
