# eimosp-ontology-agentic-analytics 变更记录（2026-11-23 至 2026-11-27）

> 本文档记录 2026-11-23（周一）至 2026-11-27（周五）当周的最终变更，
> 按周直接维护，不再创建日报。2026-11-23 建立；`11-21`、`11-22` 周末无提交。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

### 2026-11-26 360 看板：右下角“智能助手”内嵌 Ontology Analyst（360 智能分析）

- 驾驶舱各页面右下角新增“智能助手”漂浮按钮；点击后在本页弹出面板，内嵌 Ontology Analyst 工作台的 360 模式
  （`/workbench?a360=assistant`），保留工作台原有的 SOP 步骤展示、对话展示和看板；面板可放大、可新窗口打开，
  关闭后对话保留，Esc 关闭；手机宽度下面板占满屏宽（两侧 16px）。
- 智能助手不需要卡片“深度分析”交接：工作台在该模式下给每次聊天带 `analysis360_direct`，经
  `/api/analysis360/chat` 首次提问即把会话建成 360 会话（无交接条款），由 analysis360 Agent 按
  《流程360全局本体_智能分析Agent访问策略_V1.0》的六步 SOP 和六个接口分析；本体为
  `亿纬锂能_流程360全局本体_无投标_V1.0`（运行配置与 `docs/亿纬锂能/` 工作簿哈希一致），数据库与大模型取 `.env`。
  通用 `/api/chat` 不受该标记影响；客户交付入口的白名单不变。
- 主要文件：`bi_agent/web/static/cockpit/{assistant.js,index.html,cockpit.css}`、`bi_agent/web/static/analysis360-handoff.mjs`、
  `bi_agent/web/static/index.html`、`bi_agent/web/app.py`、`docs/analysis360.md`、
  `tests/{test_analysis360.py,analysis360_handoff.test.mjs}`。
- 验证：analysis360 与客户入口 Python 测试 43 项通过；驾驶舱与 analysis360 Node 测试 145 项通过；Web 相关 Python
  测试中 2 项为既有失败（插槽说明哈希、SOP 状态映射）。未启动服务在浏览器中查看，未连接客户数据库和大模型实跑。

### 2026-11-23 首页经营看板：红区报价卡片标题与单数取整

- 首页经营看板红区报价 KPI 卡片的标题（及指标别名）由“红区报价集中，存在增量不理风险”改为
  “红区报价集中，存在增量风险”；修改交付元数据 `metadata/iba-demo-1021/template-registry.json`
  （`source.json` 中该文件的 sha256 同步更新），并用 `scripts/export_cockpit_runtime.py` 重新生成 `metadata/runtime.json`。
- 单位为“单”的指标（当前为红区报价单数 `YWLN_M0137`）显示为整数（千分位，如 `1,200`），不再显示两位小数：
  ProUI KPI 卡对无格式的数值默认保留两位小数，看板数据客户端在把 AP 结果交给卡片显示时为这些指标补充整数
  `formatValue`；保存的分析证据仍是 AP 原值。单位取自看板元数据中指标的 `unit`，以后新增“单”单位的指标自动适用。
- 主要文件：`bi_agent/web/static/cockpit/{data-client.js,cockpit.js}`、`bi_agent/web/static/cockpit/metadata/`、
  `tests/cockpit_data_client.test.mjs`。
- 验证：驾驶舱 Node 测试 137 项通过；元数据与资源契约测试中 3 项为既有失败（组件元数据、vendor 清单、插槽说明哈希），
  其余通过。未在浏览器中查看实际看板。
