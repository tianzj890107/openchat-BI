# 变更记录（2026-11-02 至 2026-11-06）

按自然周维护，不创建日报。

### 2026-11-06 Cockpit 分析库存与刷新节拍

- 在现有 `dataset/cockpit/history.sqlite3` 增加 `analysis_inventory` 持久化库存，保存每个刷新范围的
  当前结果、证据指纹、分析时间、分析依据数据时间、最近检查时间、最新待处理版本、失败重试状态和
  下次允许分析时间；不新增服务，也不删除旧分析或发布记录。
- 数据检查与模型分析拆成两个节拍：数据仍按 `COCKPIT_REFRESH_INTERVAL_SECONDS` 检查，模型分析
  默认至少间隔 `COCKPIT_ANALYSIS_MIN_INTERVAL_SECONDS=1800` 秒，连续变化在
  `COCKPIT_ANALYSIS_COALESCE_SECONDS=300` 秒窗口内只保留最新待处理指纹；达到间隔后先发布本轮
  固定证据，再处理最新版本。失败重试仍由原刷新退避控制，不被分析间隔额外阻塞。
- `/api/cockpit/publications/status` 增加 `analysisPolicy` 与 `analysisInventory`，可查看当前结果的
  分析时间、最新数据时间、待处理状态和下次允许分析时间。
- 主要文件：`bi_agent/cockpit/{store,refresh,router}.py`、`.env.example`、相关设计说明。
- 验证：分析库存与刷新调度相关测试通过；未部署服务器。

### 2026-11-06 Cockpit 上游组件、默认期间与共同分析预热

- 同步 `iba-demo feature/sml_1106@0dc0cc0` 的 BI UMD 与品牌色板：保留宿主的
  helmet `fitView` 空实例保护，加载顺序固定为 BI UMD → `bi-color-vars.css` → `cockpit.js`；
  未导入该上游分支的临时排序/URL修改和 U+FFFD 乱码标签。`components.json` 保持
  `feature/demo_1021@be99db5` 的宿主适配版本，`source.json` 与 `resources.json` 的提交号、
  哈希、字节数同步，`runtime.json` 重新生成。
- 取消交付筛选中的固定 `2025-10` 默认值：默认筛选为空，live 模式按客户业务时区解析当前年度/月度，
  `backfill` 模式才使用显式 `COCKPIT_ACTIVE_PERIOD`；`/bootstrap` 暴露期间配置，页面空筛选、
  年度/月度切换和表格分析字段统一走同一期间解析。演示快照仍保留原型月份，避免旧 fixture 失效。
- 风险数量统一为结构化 findings 去重后在顶栏和穿透式卡片显示；节点卡、共同分析卡不再把
  `causes.length` 当作风险数，销售额与出货量分别统计，数据缺失时保留上次有效数量。
- 期间目录现在同时预热共同分析卡：从同期间已发布的商机、订单、发货卡片复用已保存 AP 凭据，
  不额外查询 AP/PG；不足两个环节时进入等待，满足后再生成。期间覆盖接口按六个阶段统计。
- AP 部分成功时继续分析已取得的证据：未返回值进入 `unavailableQueries` 并在卡片限制中披露，
  不再因为部分查询失败整卡等待。交付工具未完全通过时，服务端仍可用已有事实和模型正文生成
  `limited` 卡片；前端只在后台确无活动任务时提示“当前口径暂无可用的已取数证据”，不再把
  正在进行的分析显示成“尚无可用分析结果”。共同分析主动刷新时按商机、订单、发货三个上游
  环节汇总可用查询，不再单独选择没有查询计划的 `combined` 而误报无数据。
- 主要文件：`bi_agent/cockpit/{targets,combined,refresh,main_service,router,periods,ai_tables}.py`、
  `bi_agent/web/static/cockpit/{index.html,cockpit.js,cockpit.css,vendor/*,insight-components/sales-shipment-issues/*}`、
  `bi_agent/web/static/cockpit/metadata/{iba-demo-1021/*,runtime.json}`。
- 验证：全量 Cockpit Python 套件 350 项、前端 Node 套件 94 项通过；Python 编译、JS 语法和
  `git diff --check` 通过。未部署服务器。

### 2026-11-05 分析按期间缓存、合并队列与按环节刷新（第一阶段）

- 新增 `bi_agent/cockpit/periods.py`：从已提交的筛选范围解析业务期间（`YYYY` / `YYYY-MM`），
  以 `COCKPIT_ACTIVE_PERIOD` → 客户业务时区的当前年度/月度 的顺序确定「当前期间」。
  当前期间按 `COCKPIT_REFRESH_INTERVAL_SECONDS` 刷新；上一期间在 `COCKPIT_PERIOD_GRACE_DAYS`
  宽限期内继续刷新，之后冻结；更早和未来期间冻结（`COCKPIT_HISTORY_REFRESH_ENABLED=1` 可改为按天刷新）。
  冻结只写入 `status='frozen'`、`next_check=0`，已发布结果与历史记录保持可读。
- `page_refresh` 增加 `pending`/`pending_since`：运行中的刷新范围再收到请求时只记录一个待更新标记，
  不新开任务；本次运行结束时若存在标记，立即以 `waiting` 重排一次，处理最新数据。
  `refresh_queue_stats()` 新增 `pendingCount`。
- 整页刷新改为按环节判断证据：`stage_evidence()` 拆分各环节指纹与查询集合，只有证据变化的环节
  重新分析，未变化的环节沿用原分析；`build_page()` 接受整页口径、环节口径或上次发布口径，
  保证沿用未变化环节时整页仍可发布。配置版本或数据源身份变化时仍强制全部重算。
- `publication_status()` 增加 `period` 与 `periodPolicy`，便于前端与运维确认该范围的刷新节奏。
- 验收补强（2026-11-05 晚）：
  - 每个环节分析在 `analysis_stage_evidence` 中固定保存自己的证据指纹与查询集合，整页校验不再
    依赖「上一轮整页指纹」，连续多轮刷新可稳定发布；历史分析首次刷新时补写一次环节记录，不调用模型。
  - 冻结的期间在重新变成当前/宽限期间时自动恢复排队；恢复不抢占运行中的任务、不删除历史。
  - `pending` 不再表示立即执行：成功后排到 `COCKPIT_REFRESH_MIN_RECHECK_SECONDS`（默认 60 秒），
    失败时保留原退避时间；`frozen` 不会被 pending 解冻。
  - 新增 `COCKPIT_PERIOD_MODE=live|backfill` 与 `COCKPIT_BUSINESS_TIMEZONE`：默认按客户业务时区的
    系统年月维护，不再由看板默认选中月份隐式决定；回填/演示需显式设置 `backfill` + `COCKPIT_ACTIVE_PERIOD`。
  - `COCKPIT_PERIOD_GRACE_DAYS` 真实生效；上一期间同时覆盖跨年月份与上一年度。
  - 新增期间目录 `COCKPIT_PREHEAT_PERIODS`、期间预热目标（只复用该期间已有查询计划，无计划进入
    `awaiting-plan`）与 `GET /api/cockpit/publications/period-coverage` 覆盖率接口。
  - 第二轮验收修复：
    - 新增 `period_publications` 期间发布索引（权限范围 + 期间 + 节点 + 筛选 + 定义版本 → 分析 ID）；
      `view_scope()` 纳入期间与筛选摘要，不同月份不再互相覆盖，默认卡片入口不被污染。
    - 期间预热可按真实 AP 协议生成查询：把 `YWLN_D044` 的 BETWEEN/DATE 条件改写为目标年/月区间，
      月度取当月首末日、年度取全年；组件模板本身不带期间条件时按同一协议补入
      `commonConfig.filters.children`，只有连 `commonConfig` 都不存在的载荷才拒绝生成。
    - 期间目录注册不再改写 `retry_wait` / `awaiting-plan` 的执行时间，AP 故障时不会每轮重打。
    - 期间解析改为结构化：按最后一次年度/月度粒度选择，残留旧月份不会覆盖新的年度选择。
  - 第三轮验收修复：
    - AI 插槽、表格分析字段和发布状态接通精确期间读取：日期/年度范围先查该期间的分析 ID，
      命中后返回对应卡片并标记 `periodMatch=true`；未命中才回退最近默认卡片并明确标记范围不一致。
    - 期间覆盖统计按当前定义版本、数据身份和可交付分析过滤；配置轮换后的旧索引保留为历史，
      不再把失效缓存计为 ready。
    - 有效期间目录始终包含当前业务月份及其年度，并按宽限期加入上月/上一年度，再合并
      `COCKPIT_PREHEAT_PERIODS`；跨月不再依赖环境变量修改或页面访问。
    - 期间查询计划遇到 `OR` 根筛选时用新的 `AND` 根节点包裹原筛选和日期条件；已有
      `YWLN_D044` 条件仅接受 `BETWEEN` / `DATE` / `ABSOLUTE`，其他操作符拒绝生成，避免扩大查询范围。
    - 期间预热在调度中降为低优先级，不会挤占已到期的页面或单卡维护任务。
    - 新增重启后 2 个年度、3 个月份 × 5 个环节逐期间读取的端到端用例，读取过程不调用模型或 AP。
  - 第四轮验收修复：
    - `default`、空范围和未带日期的月度粒度先解析为客户当前业务年度/月度，
      再读期间索引；`/ai-publications`、`/publications/cards`、`/startup`、表格分析字段和
      发布状态使用同一规则。默认月份已发布后再预热更早月份，默认页面的分析 ID 保持不变；
      只有其他月份时可回退展示，但标记 `scopeMatch=false`。
    - 精确期间命中时，刷新状态只聚合该期间、节点对应的期间任务；当前月任务和通用默认预热
      任务不再让已冻结的历史卡片显示 `update.active=true`。未来才执行的 `waiting` 归为
      `scheduled`，不计为正在更新。
- 验证：`tests/test_cockpit_period_refresh.py` 45 项、期间读取/表格/状态相关目标用例 114 项通过；
  全量 `pytest tests -k cockpit` 344 项通过，前端 `node --test tests/*.test.mjs` 92 项通过。
  全量 Python 套件另有 5 项与本次无关的既有失败（版本 tag 校验、`库存管理演示内容.docx` 缺失、
  Workbench 本地 PG 未完成改动）。

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

### 2026-11-05 本体内容改为命中关系图

- 将本体命中列表改为现有 OntologyGraph 关系图；按用户最终要求，概览只显示命中节点及其真实直接关系，不自动补入上下文节点，点击后才在详情图展示关联上下文。保留业务对象归属布局、类型筛选和图内重置视图按钮。
- 按用户最终要求去掉搜索、下拉选择和查看本体控件，图内右上角只保留重置视图按钮。
- 懒加载、最多四个并发请求、会话/数据源范围缓存；离开页面同步释放渲染器并中止请求。失败保留命中节点，重置可重试；WebGL 不可用时回退原列表。历史快照继续保留卡片数据，不保存图画布。
- 涉及 `ontologyHitsGraph.js`、`ontologyHitsGraphModel.js`、runtime、页面模板、样式及构建产物；新增模型合并、库隔离、筛选和无关系降级测试。
- 验证：前端118项、后端回归222项及生产构建通过；隔离浏览器验证节点点击、图内唯一操作按钮、筛选、缓存复用、页面往返、失败重试、空态、WebGL降级及760px无横向溢出。未调用真实模型、写入用户配置/历史或部署线上。
- 命中范围收紧验证：前端123项和构建通过，新增未命中上下文排除与禁止经中间节点虚构直连的测试；隔离浏览器使用2个命中、3节点上下文，概览只保留2个命中和1条直接关系。

### 2026-11-05 本体平台元素适配与共享图包发布

- 对照 demo2 首页发布脚本中的13种节点，补齐动作、事件、状态、维度派生规则、BusinessRule/PhysicalTable/Field 名称适配；保留活动、流程、实体关系和元模型关系兼容类型。
- 命中解析、筛选、聚类/环形样式和子图请求统一类型；图展示加入焦点直接邻接，不改变模型取数白名单，synthetic 连线不当作真实本体关系。
- 共享 ontology-graph 发布0.1.2到 ai-team npm registry：通用语义节点标签、属性/字段缩放策略、隐藏容器尺寸保护；analytics 改为锁定 registry 版本，不再依赖同级源码目录。未升级 analytics 正式版本或部署服务。
- 验证：共享包9项、前端121项、后端225项及生产构建通过，浏览器隔离夹具确认17种节点/16条关系、图内仅重置按钮。demo2 类型清单来自发布脚本，未声称登录后真实库全类型验收。
- 缩放重叠修复：共享包升级到0.1.3，Sigma 节点/线宽采用屏幕像素，环形图 nodeScaleRatio=0；放大只拉开位置，不同步放大节点，字号保留。analytics 依赖同步锁定0.1.3。共享包9项、前端123项及构建通过；浏览器测得聚类图10倍放大后间距11.44→114.4px、半径/字号均维持12px，环形图4倍放大后框尺寸/字号保持不变。未部署线上。

### 2026-11-05 每轮 SOP 与连续工具执行记录

- SOP 移到每轮用户问题后、回答前，默认折叠并保存各轮快照；移除顶部和看板重复 SOP。
- 连续工具跨模型迭代合并追加，仅实际正文输出形成新段；工具 id 按轮次隔离。结束上一段流式光标、隐藏空占位并收紧段落留白，详情和本体图点击保持原状。
- 涉及 main.jsx、runtime.js、workbench.css 及构建产物。隔离流式回放验证两轮问题各有独立 SOP，并分别形成6项连续工具段、正文、2项工具段和最终正文。

### 2026-11-05 亿纬锂能 V3.1 本体元素定义

- 在原 Excel 同目录新增本体元素定义 Markdown，按元素目录整理23类元素的定义、编码前缀、示例和边界，补充目标／基线／阈值、异常／问题／风险、建议与任务令及定义／运行实例的区别。
- 文档区分元素类型与关系、映射、编排、运行契约等辅助配置；未修改原Excel、模型、程序或运行数据。
- 验证：与原Excel的23项元素名称逐项核对，Markdown表格及git diff --check通过。
### 2026-11-02 18:30 Cockpit 风险去重与提示样式上线

- 用户可见变化：顶栏风险数量改按业务风险事项去重，同一指标上的不同风险独立计数；客户表内的
  客户等级、商机类型、投标状态和客户商机筛选不再触发整页重建。旧口径提示统一为灰色 `ⓘ`
  辅助文字，不再使用橙色警告块。
- 发布：合并 MR `!36`、`!37` 后部署 `master` `53c4662`，8765 release
  `process360-cockpit-53c4662-20261102-1823`，PID `1561973`；8876 继续代理 8765。
- 验证：两个角色 15/15 个 AI 插槽可渲染；风险计数总裁销售 9／发货 3、分析员销售 8／发货 2；
  三页两角色在 8765 与 8876 均 200，启动日志无异常。合并后前端 92 项、Python 1876 项及
  1072 个子测试通过。GitLab runner 因外部依赖网络超时未完成流水线，未修改 CI。

### 2026-11-03 Workbench本地Excel与公司PostgreSQL数据源

- 新增固定“PostgreSQL · ywln_crm”数据源，选择后原子绑定已配置的本地Excel；也可用`--db postgres`直接启动，不依赖远程本体／Doris。已有SQLite／Doris及其他会话保持隔离。
- PG连接只从独立WORKBENCH_PG_*变量读取，不继承客户PROCESS360_PG_*；本机实际env及本地PG版Excel已准备，不提交密码与客户文件。
- 本地本体加载新增物理表／属性映射和V3.1关系编码支持，读取40条关系；缺少真实来源的属性不提供旧字段名。
- 三个数据库工具提供PG只读事务、search_path、超时、行数限制和安全校验，取证元数据标明PostgreSQL。已只读匹配2319个真实字段，实测只读事务及schema正确。
- 主要文件：`bi_agent/workbench_pg.py`、`bi_agent/tools/sql_tools.py`、`bi_agent/ontology/store.py`、`bi_agent/web/{app,__main__}.py`；新增及原回归233项、12个子测试通过，catalog／MCP回归15项通过，隔离浏览器数据源下拉验证通过。未部署、未重启现有服务、未改客户ZIP。
