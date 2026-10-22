# V3 经营驾驶舱 POC

## 已确认边界（2026-10-22）

- analytics 主服务提供四个独立入口：`/cockpit/home`、`/cockpit/overview`、`/cockpit/operations`、`/cockpit/analysis`；`/cockpit` 与 `/` 直接返回 `overview`，首页不作为默认路由。现有 `/workbench`、旧驾驶舱及 MCP 不替换。
- 四个页面只渲染看板本体，页面挂载正式发布看板 `2109836674373566465` 的一个完整 `ProBiDashboard`；顶部筛选器和四个 Tab 均来自交付根配置，不再由宿主手写。
- 四个 Tab 分别为“储能产品线整体经营分析”“全局经营看板”“运营360整体分析”“穿透式问题分析”；页面不包含宿主工作区、会话区、页面标题或第二套导航。
- `/cockpit/home`、`/cockpit/overview`、`/cockpit/operations`、`/cockpit/analysis` 只负责激活对应 Tab，并保留当前 `id`。
- 两个演示身份使用 Fuxi 传入的单一查询参数 `id`：`id=1` 对应总裁，`id=2` 对应分析员。当前四页内容对两个 `id` 完全一致，两个人都可以访问和操作；`id` 只作身份标记并为将来差异化预留。页面和 API 不使用 `role`，`/cockpit` 跳转和页内跳转都保留当前 `id`。
- 正式根配置没有 `insights` 字段，宿主从 `iba-demo-1021/insights.json` 补入 17 个插槽声明，并保留完整 Tab `embedPath`；插槽内容通过主服务 `/api/cockpit` 实时调用模型，同一环节共享一次分析结果。
- 四页读取同一份静态发布包和 AP 响应快照；快照不包含 Cookie、Token 或用户身份。
- 正式配置中的 AP 指标口径与卡片标题不一致时保持原值，不在宿主层修正；真实本体＋数据库映射需要后续业务确认。
- 模拟任务令：草稿→模拟下发→接收→反馈→验收关闭。仅本地持久化，不调用任务、通知或业务单据写接口；当前只校验状态和 revision，不按 `id` 分配操作权限。
- 已有业务预测展示＋显式假设的情景测算；不建设统计预测模型。
- 四页静态看板资源与旧工作台隔离；是否部署以当前任务中出现的明确部署授权为准。

## 页面与组件

四页静态资源位于 `bi_agent/web/static/cockpit/`。页面直接使用正式发布包的根配置、15 份模板和组件注册表，通过 `ProBiDashboard` 渲染原生 ProUI 卡片；不再使用原型 DOM、宿主布局占位或手写 Tab。

| 页面 | 默认内容 |
| --- | --- |
| 首页 `/cockpit/home` | 正式模板 `2113106174095179778`“储能产品线整体经营分析”；不作为默认入口 |
| 全局经营看板 `/cockpit/overview` | 正式模板 `2112001069107167233`；`/cockpit` 的默认落点 |
| 运营 360 `/cockpit/operations` | 正式模板 `2112434004503347202`；包含指标、运营头盔、漏斗和环节卡片 |
| 穿透分析 `/cockpit/analysis` | 正式模板 `2112061604959928321`；包含穿透图、风险结构和明细表 |
| 公共 | 根 `composite-filter` 和根 `tab-container` 由 `ProBiDashboard` 直接渲染；四个路由同步当前 Tab 并保留 `id` |

入口示例：`/cockpit/home?id=1`、`/cockpit/overview?id=2`、`/cockpit/operations?id=2`、`/cockpit/analysis?id=1`。
支持 `APP_ROOT_PATH` 下静态资源地址。纯看板页面不渲染旧的角色切换、分析历史或任务抽屉。

## 数据契约和口径

正式发布目录 `static/cockpit/metadata/pdt-release-2109836674373566465/` 保存
`dashboard.json`、15 份模板和原始 hash；`runtime.py` 只做浏览器安全导出，不改组件、位置或样式。

- 根配置包含 2 个组件：`composite-filter-hzjk9t5q` 和 `tab-container-zm9eyxne`。
- 15 份模板共 137 个组件；加上根组件共 139 个。四个 Tab 引用的模板全部存在，运行时缺项检查为 0。
- `ProBiDashboard` 直接接收根 `components` 和 `template-registry`；四个路由只激活对应 Tab。
- `data-snapshots.json` 保存正式页网络的 38 个 AP 查询、2 个批量查询和 2 个头盔图请求响应；包含 2025／2026 两个年度筛选变体、七个头盔节点的明细表查询和供应商明细第 2 页，浏览器通过 `configureBi` 回放，不访问 PDT 或生产接口。
- 快照只保存业务响应体，不保存 Cookie、Token、账号或用户身份；发布目录记录文件大小和 SHA-256。
- 正式配置没有 `insights` 字段；页面使用交付目录的 17 个插槽声明，首页 1 个、运营 360 7 个、穿透式问题分析 9 个。AP 指标与标题的口径差异保持源配置原值。

## AI 分析与任务令

页面挂载 AI 插槽后按需发起实时异步分析，不做预加载：插槽挂载时调用 `POST /api/cockpit/analyses`，
前端每 1.5 秒轮询任务；同一期间、部门、环节和 `id` 已存在完成结果时直接复用，点“重新分析”才强制刷新。
穿透页默认显示 3 个插槽内容，但只触发商机获取、发货 2 个分析任务；点击头盔图其他节点后再按需加载。
首次分析实测通常约 10–20 秒（最近一次商机分析从点击到完成约 19.9 秒），复用结果通常小于 1.5 秒显示。
以下 `/api/cockpit` 能力同时保留给 Fuxi 和历史查询使用。

主服务复用现有模型调用链执行分析。每次分析使用当前 `id`、期间、部门和环节对应的只读证据快照；模型失败、证据不足或输出校验失败时不回退为预写成功结论。

模型先取证，再输出严格 JSON（summary、causes、recommendations、limitations）。Pydantic 校验长度和字段；引用必须来自本轮查询；原因必须关联具体记录；建议必须关联原因；限制由服务端追加。这些检查保证结构与引用有效，不能证明自然语言中的所有因果推论。

取消后禁止迟到结果覆盖终态。底层供应商同步网络读可能仍需等待自身超时才能退出；本模块不承诺杀死上游请求。

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

ProUI 文档站与 PDT 当前发布的 BI UMD 相同，冻结 SHA 见 `static/cockpit/vendor/resources.json`。
旧工作台 BI 包保持不变；cockpit 使用新版 `pro-bi-ui.min.js` 与 `pro-ui.min.css`。
页面渲染入口是 `ProBiDashboard`，组件类型映射包括 `ProKpiCard`、`ProProgressCard`、`ProDataTable`、`ProBarChart`、`ProDualAxisChart`、`ProHorizontalBarChart`、`ProFunnelChart`、`ProShareBar`、`ProMiniCpGraph`、`ProTitle`、`ProButtonGroup` 及分组／模版容器。
Vue 版本为 3.5.25，哈希一致，复用原有文件。
资源文档：<http://pro-ui.eimos.com/bi-components/setup/>、<http://pro-ui.eimos.com/bi-components/dashboard/>。

## 验证

离线契约测试：

```bash
/path/to/venv/bin/python -m pytest -q \
  tests/test_cockpit_poc.py tests/test_cockpit_resource_contract.py tests/test_cockpit_metadata.py
```

当前结果：`37 passed`。JavaScript 语法检查：

```bash
node --check bi_agent/web/static/cockpit/cockpit.js
```

浏览器验收使用独立临时工作目录，避免接触用户会话。已检查：

- 四个路由均返回 200，`/cockpit` 跳到 `overview`，首页不作为默认路由。
- 页面只有一个 `ProBiDashboard`，顶部根筛选器和四个 Tab 由交付配置生成；点击 Tab 后 URL 正确切换并保留 `id=1|2`。
- 四个路由分别激活“储能产品线整体经营分析”“全局经营看板”“运营360整体分析”“穿透式问题分析”。
- 首页、全局、运营、穿透页均无组件错误；运营页生成头盔图和漏斗，穿透页生成图表和 16 个表格。
- 页面只回放本地 `/static/cockpit/metadata/pdt-release-2109836674373566465/data-snapshots.json` 中的请求，不访问 AP。
- 穿透页在 `id=1|2` 下均显示 3 个 AI 插槽内容，默认由商机获取和发货 2 个分析任务驱动；
  “重新分析”实测约 19.9 秒完成，已有结果复用通常小于 1.5 秒。
