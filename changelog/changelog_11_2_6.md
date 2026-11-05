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

### 2026-11-03 10:55 Workbench 分析 Agent 接入真实 Pro UI 组件

- 用户可见变化：工作台左侧导航与最近会话、空会话引导、用户/助手气泡、输入框与停止按钮、
  工具/SOP 执行步骤、分析状态和报表工具条改用内部 npm 的 `@pro-ui/x-react@0.1.2`
  真实 ProX 组件；结果卡片统一使用 ProX `ToolResultCard` 外壳，设置页、系统调用记录、
  本体类型筛选和报表向导的按钮、输入、选择、开关、滑块、步骤条、页签与提示块统一为
  Pro UI token 下的 Ant Design 组件。侧栏首次进入默认展开，页面内返回/保存后高亮同步
  当前视图；九条业务路由均可直接切换。会话区恢复满高，单栏切换不再产生额外空白行；
  左侧导航与最近会话行距压缩，输入区底部增加当前模型入口，可直接进入模型参数页。
- 对话与结果：工具开始即显示执行行，结果按同 ID 原位置更新；思考、等待选择、完成、
  失败、会话重建和中断使用不同状态，停止后保留已输出内容且不保存为完成回答。报表模式
  的上传、数据库查询、最近报表和报表生成工具条迁移到 React 输入区，旧附件行不再重复显示。
- 历史兼容：欢迎页和空状态移到独立覆盖层，历史恢复清空消息区时不会删除 React 挂载点；
  旧历史 HTML 中保存的 Ant Design X Bubble/ThoughtChain 快照在恢复时原位替换为 ProX
  气泡和执行步骤；旧历史、图表、表格、本体实体和服务端会话格式保持不变。
- 页面级控件：新增 `ProUiPageControls.jsx` 以隐藏原生节点作为 runtime 锚点，可见控件
  使用 ProX Button 与 Ant Design Input、Select、InputNumber、Checkbox、Radio、Switch、
  Slider、Steps、Alert、Divider、Tabs、Segmented、Tag 和 Tooltip；输入框与 Select 的
  hover/focus 态统一为 sage 色，Select 使用包装层外圈避免 rc-select 内层样式丢失。
  原 HTML 控件不再可见，现有业务事件、参数保存、页签切换和报表向导逻辑保持不变。
- 看板与布局：两栏看板折叠后显示 Pro UI 浮动展开按钮，展开或单栏时自动隐藏；浮动控件
  保持绝对定位，不再作为网格项撑出隐式行。1440×900 下以 878px 全高布置对话区，
  760×900 单栏也保持满高且无横向溢出。
- 声明式设置页（2026-11-04）：模型参数与个人账号设置改为 React 表单，直接读取
  `/api/meta`、写入 `/api/config` 或浏览器本地偏好；删除隐藏原生控件、240ms 快照轮询、
  模拟点击和控件镜像 host。runtime 只发布 `bi-settings-snapshot` / `bi-settings-updated`
  事件并保留顶层 meta 展示，保存后仍立即刷新模型入口与顶栏信息。
- 事件驱动输入区（2026-11-04）：去掉 Sender 每 320ms 读取旧输入框的轮询，改由 runtime
  发布 `bi-composer-state`，输入、忙碌、模式、附件、上传状态和占位文案通过明确事件同步；
  legacy 输入框仅保留发送适配，不再作为第二状态源。
- 图表适配器（2026-11-04）：新增 `analyticsChartAdapter.js`，使用 `series_1`…稳定 key
  生成 Pro BI 行数据，避免同名系列互相覆盖；保留 stack、双轴 `yAxisIndex`（通过
  `customOptions`）和百分比/金额格式，空值不再伪装成 0，并显式关闭默认 12 类截断。
- 生命周期清理（2026-11-04）：统一登记页面根节点，卸载时逐个 `root.unmount()` 并断开
  `chat-scroll` / `dashboard-list` 观察器；页面控件桥保存可遍历的 record，清理时卸载 root、
  断开可见性观察器并恢复原生节点；历史切换只对真正移除的消息/步骤/结果卡执行 React 卸载。
- 无障碍名称（2026-11-04）：设置页、账号页、页面控件桥的图标按钮、Select、Input、Slider
  和 Switch 补齐 `aria-label` 或关联标签，1440px 验收未发现无名称的可见控件。
- 主题收敛（2026-11-04）：`proUiTheme.js` 从逐组件覆盖 Button/Input/Select/Slider 等
  内部尺寸和形状，收敛为品牌 token、ProX 侧栏/会话/输入区密度，以及 Form/Table 两项
  业务布局覆盖；通用控件重新继承平台主题，不再为每个控件维护一套几何参数。
- 依赖与构建：内部 npm `http://npm.boulderaitech.com/` 提供 `@pro-ui/x-react` 0.1.0–0.1.2，
  当前固定 0.1.2，支持 React 18.3.1；移除 `@ant-design/x`。`@pro-ui/chat-runtime` 未发布，
  浏览器会话仍由 Analytics runtime 管理。为兼容 assistant-ui 依赖，固定
  `@assistant-ui/store@0.2.13` 和 `@assistant-ui/tap@0.5.16`，`npm run build` 已通过。
- 主要文件：`frontend/src/ProUiSidebar.jsx`、`ProUiComposer.jsx`、`ProUiWelcome.jsx`、
  `ProUiSettingsPage.jsx`、`ProUiAccountPage.jsx`、`ProUiPageControls.jsx`、
  `analyticsChartAdapter.js`、`proUiTheme.js`、`proUiBridge.js`、`ProUiAgentStatus.jsx`、
  `main.jsx`、`runtime.js`、`shell.html`、`workbench.css`、`frontend/tests/`、`frontend/package.json`、
  `frontend/package-lock.json`、`bi_agent/web/static/index.html`、前端构建产物、
  回归测试和规范文档。
- 验证：前端 Node 测试 111 项（新增图表适配器与声明式桥接回归）、`tests.test_regressions`
  222 项、`npm run build` 和 `git diff --check` 通过；1440×900 与 760×900 本地 CDP 验收
  九条路由、声明式模型/账号表单、无隐藏原生设置控件、无无名称可见控件、侧栏展开/收起、
  数据源页面、Sender 输入/清空/发送按钮状态和返回高亮；导航行高 30px、最近会话行高
  38px，模型按钮可跳转并高亮模型参数页，看板折叠后的展开按钮位于右上浮动层且可恢复
  两栏，展开和单栏状态隐藏，无隐式网格行、横向溢出或 JS 异常。恢复含工具调用的历史
  会话时 6 条消息全部为 ProX Bubble，旧 Bubble/ThoughtChain 为 0；模型页控件、本体
  筛选、系统日志页签和报表向导控件正常，Select 悬浮与输入框 hover/focus 态可见。
  历史切换连续往返两次后消息 73 条、Pro BI 图表 11 个、结果卡 11 个均未增长，
  console error 为 0；新会话对话区占满 1162px 可用宽度。本轮未部署。

### 2026-11-04 Workbench 视觉与交互再验收

- 新访客默认收起空看板，保留显式布局偏好；对话与输入区采用统一阅读宽度，760px 窄屏无横向溢出。
- 未开始分析不显示空 SOP；精简欢迎区重复标题、版本与推荐问题说明，输入框不重复显示快捷键提示。
- 模型页凭据默认折叠，清除密钥改为删除图标及二次确认；设置页收窄并保持操作入口可达。
- 修复无需执行阶段误显示为中止的问题，明确区分 skipped 与真实取消。
- 验证：前端113项、后端回归222项通过，生产构建通过；本地浏览器桌面/窄屏、设置导航、提示填入与隔离SSE发送回放验收。没有真实模型调用、配置写入、历史保存或线上部署。

### 2026-11-05 侧栏图标与会话轮次导航

- 移除分析工作区、业务内容、设置分组的重复收起工具，统一到品牌标题右侧，使用 Pro UI 面板图形。
- 品牌图形采用主色与透明背景，统一分析员头像内外层底色。
- 分析 SOP 默认折叠；参考本机 Fuxi 的 message-elevator，将任务清单卡片改为消息区边缘轮次刻度，支持悬停/聚焦预览、点击定位和当前轮次高亮。
- 验证：前端113项、后端回归222项、生产构建通过；桌面与760px浏览器隔离夹具验证单实例导航、第二轮跳转、图标与折叠状态，无线上改动或真实模型调用。

### 2026-11-05 对话正文与右侧结果收敛

- 助手回答使用无头像、无气泡框的正文排版；用户问题保持原样。工具执行收为默认折叠摘要，展开后保留原工具详情、本体命中与图查看入口。
- 图表、表格、多维图只在右侧依次追加，左侧不重复生成卡片或额外结果链接；默认保留右侧看板，结果到达不触发面板展开。
- 保留旧历史文件，恢复时不重复渲染左侧图表；执行时间线可位于摘要容器内，流式更新不会重新创建时间线。
- 验证：前端113项、后端回归222项及生产构建通过；隔离浏览器回放确认右侧一图一表、左侧零图表、正文零头像、三个工具详情和本体图请求保留。无真实模型调用、历史/配置写入或线上部署。
