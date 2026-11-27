# eimosp-ontology-agentic-analytics 变更记录（2026-11-23 至 2026-11-27）

> 本文档记录 2026-11-23（周一）至 2026-11-27（周五）当周的最终变更，
> 按周直接维护，不再创建日报。2026-11-23 建立；`11-21`、`11-22` 周末无提交。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

### 2026-11-27 储小策智能助手 AgentKit 迁移规格

- 从 GitHub `feature/20251031-20261126` 拉出独立功能分支，记录 AgentKit 组件引入、驾驶舱停靠和看板切换、360 聊天与历史回看、客户入口限制及回退条件。规格列出 9 项产品验收和后续红测顺序。[迁移规格](../docs/specs/chuxiaoce-agentkit-workbench.md)

### 2026-11-26 360 看板：右下角“储小策智能助手”，会话停靠在看板左侧（360 智能分析）

- （11-26 修订，取代当天的弹出面板/全屏方案）驾驶舱各页面右下角为“储小策智能助手”按钮，参照
  《V6.1-总裁驾驶舱-视觉(8)》的助手模式：点击后会话栏（420px）内嵌在 360 看板左侧，内容为
  `/workbench?a360=assistant`，不再显示工作台左侧的智能分析导航与配置，只有会话和看板两列。
  打开时右侧的 360 整体看板切换为当前对话的看板；对话看板右上角“返回主页”使右侧回到驾驶舱主页看板，
  会话仍停靠在左侧；会话栏右上角“显示对话看板”再次召唤对话看板；“‹”或再次点击右下角按钮收起助手，
  对话保留。窄屏（≤900px）下会话栏占满屏宽。
- （11-26 修订）会话输入框模型按钮（团队 API / 环境配置）右侧新增“历史对话”可展开按钮，下拉列出最近会话、
  可开始新对话；助手的空会话标题改为“储小策，我帮你 / 看目标 · 看差距 · 看趋势”，不再显示三条提示问题。
  驾驶舱与工作台通过同源 `postMessage` 切换视图；工作台侧新增 `static/analysis360-assistant.{mjs,css}`，
  不改前端 React 构建产物。
- （11-26 修订）会话输入框底部的模型按钮（“团队 API（环境配置）…”）在较窄的会话栏中会压到“Enter 发送”提示
  和输入区：改为随输入框宽度收缩、超长省略，输入框窄于 460px 时隐藏发送提示。修改源码
  `frontend/src/workbench.css`，并同步到已构建的 `static/vendor/antd/eimosp-ontology-agentic-analytics-workbench.css`
  （本机无前端依赖，未重新构建），样式版本升到 `v=137`；普通工作台同样生效。
- 智能助手不需要卡片“深度分析”交接：工作台在该模式下给每次聊天带 `analysis360_direct`，经
  `/api/analysis360/chat` 首次提问即把会话建成 360 会话（无交接条款），由 analysis360 Agent 按
  《流程360全局本体_智能分析Agent访问策略_V1.0》的六步 SOP 和六个接口分析；本体为
  `亿纬锂能_流程360全局本体_无投标_V1.0`（运行配置与 `docs/亿纬锂能/` 工作簿哈希一致），数据库与大模型取 `.env`。
  通用 `/api/chat` 不受该标记影响；客户交付入口的白名单不变。
- 主要文件：`bi_agent/web/static/cockpit/{assistant.js,index.html,cockpit.css}`、`bi_agent/web/static/analysis360-handoff.mjs`、
  `bi_agent/web/static/analysis360-assistant.{mjs,css}`、`bi_agent/web/static/index.html`、`bi_agent/web/app.py`、
  `docs/analysis360.md`、`tests/{test_analysis360.py,analysis360_handoff.test.mjs}`。
- 停靠布局验证（11-26）：Node 测试 147 项全部通过；本机无 Python，未运行 Python 测试。用只提供静态文件和空接口的
  本地 Node 桩服务加无头 Chrome 走通：打开→对话看板、返回主页→会话在左/驾驶舱在右、显示对话看板→回到对话看板、
  ‹ 收起，两种视图会话栏都是 420px；历史对话下拉显示最近会话；无脚本错误。未连接真实服务、数据库和大模型实跑。
- 验证：analysis360 与客户入口 Python 测试通过；驾驶舱与 analysis360 Node 测试 146 项通过；Web 相关 Python
  测试中 2 项为既有失败（插槽说明哈希、SOP 状态映射）；前端测试 3 项为既有失败。用临时工作目录（演示 SQLite 与
  本体副本，不触碰项目会话数据）启动本地服务，以无头 Chrome 截图核对：模型按钮不再压住输入区；在助手中提问后请求进入 `/api/analysis360/chat` 并显示 6 步 SOP（本机无模型密钥，回答报未配置）。
  未连接客户数据库和大模型实跑。

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

### 2026-11-27 储小策智能助手迁移到 AgentKit 嵌入工作台

- 助手复用现有 `GET /workbench?a360=assistant&view=chat|board` 入口（普通 `/workbench` 展示页不变，没有新增路由），用 React 18 + `@assistant-ui/react@0.14.14`
  装配 AgentKit 的 Thread、SOP 条、工具折叠、Composer 与按轮对话看板；资源单独构建到
  `static/vendor/agentkit/workbench-agentkit-embed.{js,css}`，不覆盖通用工作台产物。
- 驾驶舱右下角入口改指新页；宿主与子页沿用 `closed/home/board` 状态机，首次打开携带 `view`，通过 `ready` 握手重收状态，
  收起保留 iframe 与同一会话。子页只接受校验过 origin、source window、`source=cockpit-assistant` 和枚举值的消息；
  「返回主页 / 显示对话看板 / 收起」回传 request，旧 `/workbench?a360=assistant` 页面保留可回退。
- 对话直接使用 360 契约：`POST /api/analysis360/chat`（`analysis360_direct: true`、显式 `session_id`）和
  `/api/analysis360/choice`；SOP、流式正文、工具结果、澄清失败重试沿用现有 SSE 事件与 `state.js` reducer，
  同一会话的多轮、澄清续流及晚到帧按 `turn_id` 归并。
- 嵌入页左侧保留约 420px 会话栏（新对话 + 历史分析，本地保存最近 8 个会话的轮次快照），右侧在对话与对话看板间切换；
  首屏保留「储小策，我帮你」「看目标 · 看差距 · 看趋势」，输入框贴底并显示团队模型短名。
- 客户入口继续使用原有 `/workbench`（含 `APP_ROOT_PATH` 前缀），不新增第二条助手路由；通用聊天与会话接口仍被 404 拦截；
  页面复用安全渲染，不迁移或改写历史文件，回退只切换入口地址。
- 主要文件：`bi_agent/web/app.py`、`bi_agent/web/customer.py`、`bi_agent/web/static/cockpit/assistant.js`、
  `frontend/agentkit/{embed.jsx,embed-main.jsx,embedBridge.js}`、`frontend/vite.agentkit-embed.config.js`、
  `frontend/agentkit/{Thread,Board,SopBar}` 等复用组件、`tests/{chuxiaoce_agentkit_embed,chuxiaoce_agentkit_dom}.test.mjs`、
  `tests/test_chuxiaoce_agentkit_entry.py`。
- 验证：新增 10 项验收测试（宿主 URL/握手/会话恢复/360 请求体/DOM 欢迎语与看板），Node 155 项、相关 Python 55 项通过；
  构建产物已重建。未连接真实 360 服务、客户数据库和大模型做浏览器实跑。

### 2026-11-27 储小策助手验收修复：默认可提问、澄清可重试、360 证据看板与刷新恢复

- 布局：`view=board` 下同时渲染左侧对话列（SOP、消息、输入框）和右侧对话看板，历史列表与「新对话」常驻；
  默认打开即可直接提问，不再只看得到历史列表。
- 澄清失败：提交选择返回 503 时保留澄清卡与已选项，`choice_failed` 把原 pendingChoice 恢复并显示错误，
  再次提交发送相同 `choice_ids/choice_labels`，不再只剩「重试本轮」。
- 看板适配：360 工具返回的证据 JSON（`columns`/`rows`/`rowCount`/`previewRows`/`evidenceId`）转成一张表格卡，
  行数组和对象行都支持；已有原生 `table` 规范时不重复生成。
- 历史与恢复：新增 `/api/analysis360/history`（POST 保存、GET 列表、GET 单条，会话 ID 校验），
  前端在每轮结束后同步服务端，刷新后按 `session_id` 从本地快照/服务端记录恢复轮次和待澄清卡；
  客户入口继续放行 `/api/analysis360/*`。
- 入口与版本开关：助手继续走 `/workbench?a360=assistant`，普通 `/workbench` 返回原展示页；
  新增 `WORKBENCH_ASSISTANT_UI=legacy` 服务端开关：同一 URL 下服务端返回旧工作台页，
  回退不改 iframe 地址、不新增路由。
- 主要文件：`frontend/agentkit/{embed.jsx,embedBridge.js,results.js,agentkit-theme.css}`、
  `bi_agent/web/app.py`、`bi_agent/web/static/cockpit/assistant.js`、`tests/{chuxiaoce_agentkit_dom,chuxiaoce_agentkit_results}.test.mjs`、
  `tests/test_chuxiaoce_agentkit_{entry,history}.py`。
- 验证：Node 160 项通过；相关 Python 58 项通过；嵌入构建产物已重建。
