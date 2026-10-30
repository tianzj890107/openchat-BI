# eimosp-ontology-agentic-analytics 变更记录（2026-10-26 至 2026-10-30）

> 本文档记录 2026-10-26（周一）至 2026-10-30（周五）当周的最终变更，
> 按周直接维护，不再创建日报。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更


### 2026-10-30 · 修正本体库编号与环境模板

- pdt-dev 当前目录已不存在本体库 `3`；ywln 目标改为 `14`（亿纬锂能开发本体库 /
  `ywln` / `ontology_ywln`），V2 为 `16`，demo2 仍为 `1`（ECore / `ontology_ecore`）。
- 同步修正 `.env.example`、`DEPLOYMENT.md` 和环境作用域说明，写清旧值会导致
  `configure()` 启动 fail-fast 与 Pod `CrashLoopBackOff`。为兼容尚未更新平台变量的
  pdt-dev 部署，增加窄口径 `3 → 14` 回退：只有目录中的 `14` 同时匹配命名空间 `ywln`
  和 Doris 库 `ontology_ywln` 时才启用并输出启动告警；`/api/sources` 显示实际编号；
  不匹配时仍保持 fail-fast，不自动选择其它业务库。平台变量仍建议改为 `14`。
- 同步修正 demo2 真实环境测试中的预期编号，并补充兼容回退的正向与数据库不匹配测试。
  涉及文件：`bi_agent/web/app.py`、`.env.example`、`DEPLOYMENT.md`、
  `docs/specs/environment-scoped-ontology-and-unused-session.md`、
  `tests/test_environment_scoped_ontology_and_unused_session.py`、
  `tests/test_pdt_pg_lake_improvements_red.py`。
- 验证：相关配置/回归测试 36 项通过（另 5 项按环境开关跳过）；用真实 pdt-dev 目录执行
  回退解析，选中 `14` 且对应 `亿纬锂能开发本体库 / ywln / ontology_ywln`，
  meta/knowledge 库也均存在；demo2 返回 `1`（ECore）；`git diff --check` 通过。

### 2026-10-28 · URL prompt 自动发起智能分析

- 工作台 `/workbench`、根路径及网关子路径支持 `?prompt=...`。页面等到现有工作台绑定输入框与
  发送事件后，自动填入问题并走原有发送流程，保留相同的 session、流式交互和会话保存行为。
- 使用标准 URL 解码，支持中文、换行及正确编码的 `&`、`+` 等特殊字符；缺失或仅空白的参数不触发
  请求。发送前从当前地址移除全部 `prompt` 参数，保留其他参数、锚点和浏览器历史状态，刷新不重复发送。
- 页面加载独立的原生 ES 模块，Python 静态服务直接提供；同步补充 README 接入示例。
- 主要文件：`bi_agent/web/static/url-prompt.mjs`、`bi_agent/web/static/index.html`、
  `frontend/tests/urlPrompt.test.mjs`、`README.md`。
- 验证：前端 Node 测试 81 项通过（新增 5 项）；无头 Chrome 通过根路径、`/workbench` 和子路径的
  自动提交、特殊字符、刷新防重发、空白参数及手动发送验证，API 使用临时模拟服务，不调用真实模型、
  不读写历史会话；相较手动发送基线无新增浏览器错误。当前 Python 服务可返回新增模块（HTTP 200）。
- 已有环境限制：完整前端构建因仓库外的 `../ontology-graph` 依赖缺失而失败；本次独立模块已单独验证。
  页面基线仍有 `getBoundingClientRect is not a function` 布局错误，自动提交与原有手动发送均可完成。
