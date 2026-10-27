# eimosp-ontology-agentic-analytics 变更记录（2026-10-26 至 2026-10-30）

> 本文档记录 2026-10-26（周一）至 2026-10-30（周五）当周的最终变更，
> 按周直接维护，不再创建日报。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更

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
