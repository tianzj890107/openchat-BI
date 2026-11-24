# eimosp-ontology-agentic-analytics 变更记录（2026-11-23 至 2026-11-27）

> 本文档记录 2026-11-23（周一）至 2026-11-27（周五）当周的最终变更，
> 按周直接维护，不再创建日报。2026-11-23 建立；`11-21`、`11-22` 周末无提交。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

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
