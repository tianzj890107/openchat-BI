# eimosp-ontology-agentic-analytics 变更记录（2026-10-26 至 2026-10-30）

> 本文档记录 2026-10-26（周一）至 2026-10-30（周五）当周的最终变更，
> 按周直接维护，不再创建日报。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更

### 2026-10-29 · Cockpit 适配 iba-demo 1021 单查接口、跳转规则与 12 个 AI 插槽

- 组件同步：按上游 `feature/demo_1021` 的 `d01c08a` 更新根组件、13 份模板、145 个组件配置、
  声明式插槽和 `activate-rules.json`；新版取消旧的三节点头盔覆盖，恢复交付四节点拓扑，并保留
  唯一缺失子组件 `share-bar-79fsomq9` 的空位与缺项报告。
- 数据请求：单查改用 `/x360/v1/ontology/data/query`，服务端固定发送
  `X-Ontology-Repository-Id: 8`（可由 `COCKPIT_AP_REPOSITORY_ID` 显式覆盖），兼容
  `success:true` 与 `code:200` 两种成功包装。页面只注入 `postAnalysisDataQuery`，不再注入批量
  适配器；批量接口仍请求本体且不可用，由新版 ProUI 自动并发单查，宿主不补空数据或部分结果。
- 页内跳转：接入 6 条 `activateRules`，把跨 Tab 的 `switchTab` 转换为主服务三页路由，并在目标
  页头盔图实际挂载后恢复 `selectHelmet` 节点；“查看销售额风险”和“查看出货风险”分别落到商机、
  发货节点。新增新版 SDK 销毁后 `fitView` 回调的空实例保护，避免切页时产生内部异常。
- 插槽验收：经营看板 0 个、运营页 4 个、穿透页 8 个，共 12 个 AI 插槽。浏览器逐节点验证
  `bid-status-note`、`quote-summary`、`bid-summary`、`order-sign-summary`、
  `sales-shipment-issues`、`opportunity-risk`、`opportunity-coverage-note`、
  `order-risk-summary`、`shipment-risk-summary`、`shipment-overdue-note`、
  `shipment-cause-breakdown`、`shipment-task-order` 均能挂载，无浏览器异常。
- 数据边界：当前仅有本地 QA 夹具，真实 AP 指标尚未配完；缺口在组件原位置保留，不用旧原型、
  发布快照或零值冒充新客户数据。业务数值是否完整需等数据配置完成后再验收。
- 验证：Cockpit 相关 Python 测试 94 项通过，数据客户端／整页缓存前端测试 23 项通过；浏览器
  QA 覆盖激活跳转、非默认节点恢复、缓存首屏、AP 失败保留和三个页面，全部通过。
- 涉及文件：`bi_agent/cockpit/ap_gateway.py`、`runtime.py`、`metadata.py`、`prototype.py`、
  `cockpit.js`、`data-client.js`、`index.html`、`vendor/pro-bi-ui.min.js`、`vendor/resources.json`、
  `metadata/iba-demo-1021/*`、`.env.example`、`docs/specs/cockpit-analysis-engines.md` 及测试。
- 边界：未部署，未修改服务器或用户历史会话，未升级版本、创建 tag 或 Release。

### 2026-10-27 · Cockpit 首屏加载与整页数据版本优化

- 首屏与资源：Cockpit 改用生产版 Vue，组件脚本和静态资源支持 gzip 预压缩；目标页面在挂载前
  确定，配置、运行模块和已发布卡片并行初始化；AI 插槽组件按当前页实际出现的模块加载，不再在
  每个页面启动时加载全部 12 个插槽。新增 `scripts/build_cockpit_site.py`，按内容哈希生成可并存的
  release 静态目录、`release.json` 和 `manifest.sha256`；新增 `deploy/cockpit-nginx.conf` 作为
  独立静态站的缓存与代理模板，保留旧 release 目录。
- 整页完整版本：新增 `/api/cockpit/page`、`/page/lookup` 和 `/startup` 及前端 `page-client.js`。
  页面打开时先回放服务器上次通过校验的完整版本，包含图表数据、筛选范围、AI 卡片和数据时间；
  后台再取新 AP 数据并更新卡片，全部图表与可见 AI 插槽属于同一数据版本后才原子发布新页面。
  更新失败、页面数据不完整或筛选已变化时保留上次完整内容并显示更新时间／失败原因，不回填旧请求，
  也不接受缺项或跨版本结果。页面版本追加保存，不覆盖历史。
- AP 取数：新增按连接、认证配置和完整查询条件隔离的短时结果复用及并发合并；相同查询在同一时刻
  只访问上游一次，仍按身份和有效期校验。新增 `COCKPIT_AP_BATCH_MODE=individual`，把批量查询按原
  顺序拆成同一组 AP 单项请求，全部成功才交付；用于避开线上批量接口“本地查询组合未配置／未启用”
  导致的整批失败。`native` 模式保留供批量接口修复后联调，未以空数据或静默降级掩盖失败。
- 数据一致性：图表查询、AI 结果和页面缓存使用同一 AP 数据指纹、认证范围、连接身份和配置版本；
  AI 结果首屏改为紧凑返回，仅携带卡片所需摘要、建议、限制和证据，完整来源仍保留在分析记录中。
- 涉及文件：`bi_agent/cockpit/page_cache.py`、`ap_gateway.py`、`router.py`、`store.py`、
  `bi_agent/web/static/cockpit/page-client.js`、`cockpit.js`、`data-client.js`、
  `publication-client.js`、`insight-components/index.js`、`index.html`、`cockpit.css`、
  `bi_agent/web/static/cockpit/vendor/vue.global.prod.js`、`bi_agent/web/static/cockpit/vendor/resources.json`、
  `scripts/build_cockpit_site.py`、`deploy/cockpit-nginx.conf`、`.env.example` 及对应测试。
- 验证：Cockpit 相关 Python 测试 94 项通过；整页缓存、数据客户端和卡片发布前端测试 21 项通过；
  本地浏览器验收覆盖缓存首屏、后台替换、AP 失败保留、筛选切换和三个页面初始路由，全部通过。
  静态站构建生成 127 个文件（含 62 个 gzip 文件）并通过 manifest 校验；`git diff --check` 通过。
- 边界：本轮只完成本地实现、测试和分支交付；未部署，未修改 34 服务器或用户历史会话。

### 2026-10-27 · 收口 ontology-v0.1.5（加载性能 PATCH）

- 按用户明确指定，把驾驶舱整页缓存、后台更新、AP 短时复用与 individual 拆批、生产版 Vue、
  gzip/内容哈希静态资源、AI 插槽按页加载和初始化并行化收口为 `ontology-v0.1.5`。
- `ontology-v0.1.4` 保持为加载优化前的定版，annotated tag 指向 `3287c91`；`ontology-v0.1.5`
  的 tag 与 GitLab Release 在版本收口提交上创建。
- 同步更新 README、版本索引、新增 `docs/versions/ontology-v0.1.5.md`、版本规范、版本契约测试
  和前端/包管理清单版本号。
- 边界：不部署、不修改服务器或用户历史会话；tag、Release 与 MR 合并按独立授权执行。
