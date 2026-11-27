# eimosp-ontology-agentic-analytics 变更记录（2026-11-23 至 2026-11-27）

> 本文档记录 2026-11-23（周一）至 2026-11-27（周五）当周的最终变更，
> 按周直接维护，不再创建日报。2026-11-23 建立；`11-21`、`11-22` 周末无提交。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

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

- 助手使用现有 `GET /workbench?a360=assistant&view=chat|board`，由驾驶舱右下角打开。默认视图显示对话、输入框和看板，保留欢迎语。主页与看板双向切换和收起沿用同一 iframe。设置 `WORKBENCH_ASSISTANT_UI=legacy` 后同一 URL 可回退到旧助手。
- 现有嵌入版接入 360 聊天、澄清重试、查询证据表格，以及按会话 ID 恢复历史轮次和待澄清卡。客户入口仍限制通用聊天和会话接口。实现位于 `frontend/agentkit/{embed.jsx,embedBridge.js,results.js}`、`bi_agent/web/app.py` 和 `bi_agent/web/static/cockpit/assistant.js`。已记录 Node 160 项、相关 Python 58 项通过及重建产物。
- （11-27 规格修订）明确打开助手必须挂载与分析 Agent 共用的完整工作台。补充默认三栏、导航、拖动分隔条、完整 Composer、交接和本体图的验收，约定客户模式下模型与数据源只读、未授权的附件上传隐藏。完整工作台重构待实施。[迁移规格](../docs/specs/chuxiaoce-agentkit-workbench.md)

### 2026-11-27 储小策助手改用完整 AgentKit 工作台（替换精简嵌入页）

- 打开助手即完整工作台：品牌、会话侧栏、新建/历史、底部「会话/对话/看板」导航、Thread/SOP、贴底完整
  Composer、Board、两条可拖动的 `PanelDivider`、按业务数据挂载的 `HandoffBanner`、`OntologyGraph` 和
  设置入口，全部沿用 `App.jsx` 共享组件树；删除独立 embed 页面、embed 构建配置和 `.ak-embed` 布局。
- 360 适配层：`/api/chat` → `/api/analysis360/chat`（自动带 `analysis360_direct`）、`/api/choice` →
  `/api/analysis360/choice`，会话列表/激活/保存映射到 `/api/analysis360/history`；配置、数据源、报表和
  角色写入在适配层直接拦截，不产生通用接口的网络请求。
- 客户只读：设置入口改为只读的「本体库与数据源（只读）」面板，展示 360 全局本体与团队模型；
  Composer 保留短模型名，隐藏报表上传、附件、模型设置与参数写入。
- 入口继续使用 `/workbench?a360=assistant`；宿主 `view=board|chat` 控制完整工作台/窄栏，刷新按
  `session_id` 从 360 历史恢复；旧 `/workbench` 展示页、旧交接链接和 `WORKBENCH_ASSISTANT_UI=legacy` 回退保留。
- 验证：Node 153 项、相关 Python 58 项通过；DOM 契约检查品牌、侧栏、底部导航、对话、输入框、看板、
  两条分隔条、只读面板，以及仅调用 360/`meta` 的网络白名单。此前精简嵌入页的实现已被本条替代。
