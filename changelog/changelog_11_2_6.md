# 变更记录（2026-11-02 至 2026-11-06）

按自然周维护，不创建日报。

### 2026-11-02 单一源码主目录约定

- 在 AGENTS.md 固定用户要求：未经明确授权不创建 worktree、额外 clone 或 POC/集成源码副本；已合并工作区核对线上路径及独有数据后清理。
- 允许测试框架自动清理的隔离 fixture；目录清理不授权线上重启、部署或删除历史数据。
- 验证：规则内容已核对，git diff --check 通过；仅工程约定变更，无业务行为变化。

### 2026-11-02 17:05 Cockpit 同步 iba-demo be99db5 品牌色板

- 用户可见变化：经营看板、运营页和穿透页的 KPI 数值色、图表色板与对比色更新为上游品牌色
  （`#4C8BF3` / `#63AD73` / `#5CBBD5` / `#E7B550` / `#DD8142` / `#DE5A60` / `#D751AD` 等），
  页面布局、15 个 AI 插槽和三张订单表结构保持不变。
- 运行包：`vendor/pro-bi-ui.min.js` 更新为 `iba-demo feature/demo_1021` `be99db5` 的 UMD；
  `index.html` 缓存参数改为 `?v=e152acd8`，`resources.json` 提交号、哈希和字节数同步。
  上游 UMD 未带头盔图销毁后的空实例保护，同步后重新补回 `fitView` 守卫；`pro-ui.min.css`
  与 Vue 运行时未变化。
- 配置同步：`metadata/iba-demo-1021/template-registry.json` 按上游色板更新并重新生成
  `metadata/runtime.json`；`components.json` 上游仅移除了宿主适配的默认期间，已重新写回
  `YWLN_D044=2025-10`，因此文件内容与上一版一致。
- 上游数据修复：新模板配置有 4 处中文标签以 U+FFFD 乱码交付（进行中超期电量、报价办理状态、
  投标状态分布、销售订单编号），同步时恢复为上一版正确文案，没有按乱码入库。
- 主要文件：`bi_agent/web/static/cockpit/vendor/{pro-bi-ui.min.js,resources.json}`、
  `index.html`、`metadata/iba-demo-1021/{template-registry,source}.json`、`metadata/runtime.json`、
  `tests/test_cockpit_{metadata,resource_contract}.py`。
- 验证：Cockpit 相关 Python 257 项、前端 Node 88 项通过；UMD `node --check` 通过；
  资源清单与 `source.json` 哈希一致；`git diff --check` 通过。

### 2026-11-02 17:20 Cockpit 合并客户覆盖、核查交付与宿主面板修复

- 用户可见变化：运营页商机覆盖提示可使用已核验 AP 客户覆盖数，报价状态口径修正；
  穿透页的核查建议必须有证据支撑，阶段策略支持缓存预热，任务令下发前要求确认具体
  日历期限；看板不再显示宿主自绘的“元数据缺失与渲染限制”面板。
- 交付契约：核查类动作与改善类动作分开校验，假设只能生成核查任务；责任角色和期限
  未确认时保持“待确认”，不写成已下发安排。
- 评测与修复：合入 40 条 Cockpit 业务评测用例及运行器；任务令 POC 测试改用具体日期，
  与“工作日建议不是可下发日期”的期限校验保持一致。
- 验证：全量 Python 与前端 Node 测试通过；`git diff --check` 通过。

### 2026-11-02 Cockpit 风险事项去重与客户表局部筛选

- 顶栏风险统计改为按业务风险事项去重，统一节点卡、综合分析卡及自动指标判断的同义事项；不再把指标编码组合视为风险唯一标识。同一指标上的不同风险可以独立交付。
- 汇总按风险所属领域收集全部插槽，补计商机卡中属于出货量的风险；统计返回可核对的去重风险清单、稳定事项键及分析／插槽／证据引用，数量直接来自该清单。
- 客户表内客户等级、商机类型、投标状态、客户商机筛选及重置保留为组件局部行为，不再触发宿主全页筛选、清空缓存和重建看板；全页时间筛选继续生效。保留局部筛选的重放记录，不更改厂家组件与交付元数据。
- 主要文件：`bi_agent/cockpit/{risk,agent}.py`、`bi_agent/web/static/cockpit/{data-client,cockpit}.js`；补充风险同义去重、跨节点归属、同指标不同事项、局部筛选与全局筛选隔离测试。
- 本地浏览器验收：在隔离 AP／模型 fixture 下，客户等级 1、2 与重置均保持原看板 DOM 和 runtime 实例；未触发整页重建。线上历史响应只读复算为总裁销售 7 条、出货 3 条，不作为已部署结果。
- 验证：Cockpit Python 291 项、前端 Node 91 项通过；本地浏览器局部筛选与全页月度筛选对照通过；`git diff --check` 通过。本轮未部署。

### 2026-11-02 18:05 Cockpit 旧口径提示改为文字提示

- 用户可见变化：AI 卡片上方的“当前展示上次分析”类旧口径提示不再使用橙色警告底色和边框，
  改为带 `ⓘ` 前缀的灰色辅助文字；提示内容和触发逻辑不变。
- 主要文件：`bi_agent/web/static/cockpit/cockpit.css`、`tests/cockpit_insight_runtime.test.mjs`。
- 验证：Cockpit 运行时测试 6 项、Cockpit Python 测试 284 项通过；`git diff --check` 通过。

### 2026-11-03 09:10 Workbench 分析 Agent 全页 Pro UI 组件化

- 用户可见变化：工作台从单条对话状态条扩展为整页统一视觉，左侧导航与最近会话、
  空会话引导、用户/助手气泡、输入框与停止按钮、报表工具条、分析状态、结果卡片和
  设置页统一为 Pro UI sage 主题和组件层级。侧栏首次进入默认展开，页面内返回/保存后
  高亮同步当前视图；九条业务路由均可直接切换。
- 对话与结果：工具开始即显示执行行，结果按同 ID 原位置更新；思考、等待选择、完成、
  失败、会话重建和中断使用不同状态，停止后保留已输出内容且不保存为完成回答。报表模式
  的上传、数据库查询、最近报表和报表生成工具条迁移到 React 输入区，旧附件行不再重复显示。
- 历史兼容：欢迎页和空状态移到独立覆盖层，历史恢复清空消息区时不会删除 React 挂载点；
  旧历史 HTML 快照、图表、表格、本体实体和服务端会话格式保持不变。
- 依赖边界：文档 `guide/quickstart` 的 `npm install @pro-ui/core` 面向 Vue 3 / Element Plus；
  React 文档仅使用 `@pro-ui/x-react` / `@pro-ui/chat-runtime` import 路径，公共 npm、镜像和
  当前 GitLab npm 代理均无可用 React 包（404），文档仓库地址当前账号也不可访问；本轮使用
  已安装的 Ant Design X 1.6.1、Ant Design 5.29.3、React 18.3.1 实现同体系可见组件，
  未伪造依赖。
- 主要文件：`frontend/src/ProUiSidebar.jsx`、`ProUiComposer.jsx`、`ProUiWelcome.jsx`、
  `proUiBridge.js`、`ProUiAgentStatus.jsx`、`main.jsx`、`runtime.js`、`shell.html`、
  `workbench.css`、`bi_agent/web/static/index.html`、前端构建产物及相关测试、规范文档。
- 验证：前端 Node 测试 98 项、`tests.test_regressions` 221 项、`npm run build` 和
  `git diff --check` 通过；1440×1000 本地 CDP 验收九条路由、侧栏折叠偏好刷新后保留、
  设置页尺寸、Sender 双向同步和返回高亮，未发现 JS 异常或业务资源 404。本轮未部署。
