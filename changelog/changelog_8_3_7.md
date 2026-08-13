# openchat-BI 变更记录（2026-08-03 至 2026-08-07）

> 本文档记录本项目在本周内完成的最终用户可见功能变化。

## 维护规则

- 每次发布或一组相关修改按日期追加，不记录单个操作步骤或中间尝试。
- 每条记录只描述相对于上一版本的最终用户可见差异；同一功能的多次调整合并为一条。
- 每条记录至少说明：用户可见变化、涉及页面、主要文件。
- 不记录重启、部署、文件同步或浏览器刷新等运行操作。

## 2026-08-03

### 1. 新对话欢迎区与空分析 SOP

- 新开智能分析对话中的三个示例问题统一为 8px 圆角，和工作台其他可点击提示保持一致。
- 即使尚未发送问题也显示折叠的“分析 SOP”入口；展开后提示“开始一轮智能分析后，这里会显示本次对话的六步执行进度”，开始分析后自动替换为实时进度和 ThoughtChain 步骤。
- 页面：智能分析新对话欢迎区、对话区顶部。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 2. 任务清单联动看板定位

- 点击任务清单中的任一用户提问时，对话区定位到对应用户问题，看板同时定位到该轮首个可见分析结果；看板已隐藏的用户问题卡片不再作为滚动目标。
- 页面：智能分析、报表分析任务清单、对话区和右侧看板。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/index.html`。

### 3. 本体命中记录与本体内容完整性

- 智能分析过程现在可以识别本地和远程本体常见编码（指标、术语、维度、活动、流程、规则及元模型关系），远程本体中不在本地 Excel 回退文件里的命中项也会保留在本体内容和系统调用记录中。
- 本体内容接口补充返回业务属性、实体关系、维度、流程和本体元模型关系，不再只返回基础业务对象和指标集合。
- 主要文件：`bi_agent/web/session.py`、`bi_agent/web/app.py`、`tests/test_regressions.py`。

### 4. 团队模型网关接入

- 默认模型提供商切换为团队 OpenAI-compatible 网关，默认模型为 `direct-deepseek-v4-flash`。
- 团队网关通过 `TEAM_API_KEY`、`TEAM_BASE_URL`、`TEAM_MODEL` 和 `TEAM_MODELS` 配置；模型选择器会展示团队网关中的全部候选模型，并在额度或限流时按配置顺序自动切换。
- 原有 Qwen、Anthropic 和 DeepSeek 提供商仍保留，可通过模型选择器或环境配置切换。
- 主要文件：`bi_agent/llm/provider_team.py`、`bi_agent/llm/provider.py`、`bi_agent/llm/registry.py`、`bi_agent/llm/runtime_config.py`、`bi_agent/web/app.py`、`bi_agent/web/static/app.js`。

### 5. 设置页控件尺寸与圆角统一

- 模型参数页的“恢复默认”“返回”“保存”按钮统一高度和内边距，并与模型、最大输出长度和 API 密钥输入框统一采用 8px 圆角。
- 数据源、本体适配、角色选择、记忆管理和个人账号设置页同步使用同一套圆角控件样式，避免不同设置页面出现直角/小圆角混用。
- 页面：模型参数及全部设置页。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 6. 数据源读取后的保存提示

- 在数据源页点击“读取当前数据源”后，读取到的 Doris 库名现在明确标记为“尚未保存”，并提示点击“保存并切换”后才会真正生效。
- 读取结果使用待保存状态，不再误显示为已完成状态，避免用户以为读取动作已经完成数据源切换。
- 同步更新脚本版本号，确保已部署页面加载最新的保存提示逻辑。
- 页面：数据源。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/index.html`。

### 7. 本体内容与远程 OntologyQuery 结果统一

- 远程本体源启用时，本体内容页现在以当前远程仓库返回的对象为准，不再被本地 Excel 中同编码对象覆盖。
- 本体命中按“来源 + 仓库 + 类型 + 编码”区分，补充表节点、列、维度、流程和元模型关系等远程类型；SQL、图表和表格中的来源编码不再误计为本体命中。
- 历史会话恢复时会重建本体去重索引，保留远程命中来源，避免继续追问时重复或错配。
- 页面：本体内容、系统调用记录、智能分析和报表分析。
- 主要文件：`bi_agent/web/session.py`、`bi_agent/web/app.py`、`bi_agent/web/static/app.js`、`tests/test_regressions.py`。

### 8. 历史会话本体卡片迁移

- 打开已有历史会话时，从会话保存的 OntologyQuery 等本体工具结果重新生成本体卡片。
- 旧卡片会按当前远程来源、仓库、类型和编码重新绑定，缺失或过期的本体快照会被纠正；迁移不会改变会话的更新时间和历史排序。
- 无法从历史工具结果安全确认的内容不自动改名，避免把普通数据库字段误改成本体对象。
- 页面：历史会话、本体内容、系统调用记录。
- 主要文件：`bi_agent/web/app.py`、`bi_agent/web/conversations.py`、`tests/test_regressions.py`。

### 9. 本体类型徽标倒角

- 本体内容中的术语、逻辑实体、属性、指标等类型徽标统一增加圆角，和页面其他标签样式保持一致。
- 页面：本体内容。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 10. 思维链步骤间距收紧

- 收紧思维链步骤标题、步骤内容、代码区域和 Ant Design ThoughtChain 项目的上下留白，整体间距约缩减一半。
- 页面：智能分析、报表分析会话区。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 11. 思维链折叠状态去除内容留白

- 折叠时只保留思维链标题行，不再让隐藏的内容区域或代码区域占用上下间距。
- 展开后再恢复内容区的上下留白，保持内容可读性。
- 页面：智能分析、报表分析会话区。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 12. 本体类型筛选

- 本体内容页顶部新增类型筛选按钮，可按术语、业务对象、逻辑实体、属性、指标等类型显示或隐藏实体卡片。
- 表节点和列默认隐藏，其他类型默认显示；关闭类型后按钮变灰，再次点击即可恢复。
- 业务对象类型统一改为红色，筛选按钮、类型徽标和卡片色条保持一致。
- 页面：本体内容。
- 主要文件：`bi_agent/web/static/index.html`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`。

## 2026-08-04

### 13. 数据源与图表生成的边界校验

- Doris 数据库名在保存数据源前统一校验为安全标识符，非法值会直接返回可读的表单错误，不再进入后续元数据 SQL。
- Doris HTTP 查询统一识别 `success=false` 和非 200 业务码，并兼容令牌已经带 `Bearer` 前缀的配置；SQL 结果行数限制在有效范围内，避免负数或超大输出。
- SQL 查询继续支持用于结构检查的只读 `PRAGMA`，但会拒绝带赋值的 PRAGMA，保持 SQLRun 的只读约束。
- 独立图表 HTML 对标题和脚本内 JSON 做上下文转义，避免标题内容破坏页面脚本；同一秒生成同名图表时自动追加序号，不再覆盖旧图表。
- 页面：数据源设置、智能分析/报表分析图表及历史图表链接。
- 主要文件：`bi_agent/tools/sql_tools.py`、`bi_agent/ontology/remote.py`、`bi_agent/tools/chart_tools.py`、`bi_agent/tools/chart_multidim_tools.py`、`bi_agent/web/app.py`、`tests/test_regressions.py`。

## 2026-08-05

### 14. IBA 内部侧栏展开宽度对齐

- IBA 内部智能分析功能栏展开时固定为 230px，使其从外部收起的 72px 导航轨道开始，右边界准确落在顶部 EIMOS 与“产品功能”的中缝。
- 侧栏收起时仍保持原有 72px 窄栏和图标布局，不改变外部导航栏的折叠行为。
- 页面：i-Agent 智能分析工作台（会话、看板及内容设置页）。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 15. 对话输入区单行化

- 输入框与操作区合并为一行，移除中间分隔线；提示文字与发送控件保持同一行显示。
- 发送控件改为单独的大箭头按钮，不再显示“发送”文字；报表模式的辅助操作仍在同一行横向排列。
- 页面：智能分析、报表分析对话输入区。
- 主要文件：`bi_agent/web/static/index.html`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/app.js`。

### 16. 任务清单只显示用户提问

- 任务清单不再重复显示分析 SOP 步骤，只保留当前会话中的用户提问及其定位入口。
- 分析 SOP 继续在上方作为独立的可折叠区域展示。
- 页面：智能分析、报表分析会话区。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/index.html`、`bi_agent/web/static/vendor/antd/sidebar.js`。

### 17. 分析 SOP 行间距收紧

- 分析 SOP 的六个步骤行间距压缩为原来约一半，保持文字和状态图标可读性。
- 任务清单、对话消息和展开后的详细思考内容间距不变。
- 页面：智能分析、报表分析会话区顶部的分析 SOP。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 18. 结果卡片标题与来源信息布局

- 会话和看板中的表格、柱状图、饼图等结果卡片，标题统一靠左显示，类型徽标移动到标题行右上角。
- `source`、`saved` 等技术来源信息移到结果卡片右下角，不再占用右上角标题位置。
- 历史会话中已保存的旧卡片也会在恢复时使用同一布局。
- 页面：智能分析、报表分析会话和看板。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 19. 历史结果卡片布局迁移

- 恢复旧会话时就地整理旧版结果卡片的标题节点顺序：标题靠左、类型徽标靠右，来源信息放到内容区右下角。
- 保留历史图表实例和表格内容，不再因恢复历史而追加第二层结果卡片。
- 历史恢复流程会同时处理已保存的 Ant Design 卡片和旧版静态卡片，避免已挂载的历史图表被跳过。
- 看板中已保存的旧结果卡片也会同步整理标题与类型徽标顺序，新生成的看板结果沿用相同布局。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/app.js`、`bi_agent/web/static/vendor/antd/sidebar.js`、`bi_agent/web/static/index.html`。

### 20. React 工作台统一入口

- 工作台页面模板、完整样式和会话运行时迁入 `frontend/src`，由 React 根组件统一挂载；旧的独立静态 `app.js`、`styles.css` 和旧版侧栏 bundle 不再作为运行时文件。
- `/workbench` 现在只加载 React 工作台入口、编译后的 `workbench.js`、Ant Design 样式和 ECharts 第三方资源；API、SSE、历史会话、图表和设置行为保持原有契约。
- 报表生成设计文档同步到新的 React 源码路径。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/runtime.js`、`frontend/src/shell.html`、`frontend/src/workbench.css`、`frontend/vite.config.js`、`bi_agent/web/static/index.html`、`docs/skills/报表生成能力_设计文档.md`。

### 21. 会话图表标题留白统一

- 会话中的图表、表格和多维结果卡片标题栏增加与看板气泡一致的顶部留白，标题和类型徽标不再贴着气泡上边界。
- 主要文件：`frontend/src/workbench.css`。

### 22. 工具调用结果时间线与历史会话统一

- 对话中仍只展示已完成的工具调用结果，并使用统一的 Ant Design ThoughtChain 时间线样式：左侧显示折叠/展开箭头，中间显示工具名称和输入摘要，右侧保留当前耗时格式，点击后展开输入、输出和本体命中详情。
- 展开详情后，输入和输出继续分别保留浅色圆角气泡；输入显示格式化 JSON，输出原样保留 SQL 与查询结果内容。
- 工具结果节点去除旧版外层/内层重复结构和深色背景，实时对话与历史会话使用同一套轻量时间线布局。
- 历史会话恢复时会重新挂载工具结果组件，并清理已保存的旧挂载节点，避免出现重复节点或实时/历史样式不一致。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/runtime.js`、`frontend/src/workbench.css`、`bi_agent/web/static/index.html`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`。

### 23. 工具结果标题语义色与时间线节点

- 工具调用结果标题按工具类型使用不同语义色，并与本体内容页面的蓝、绿、黄、红、紫、灰色风格保持一致。
- 工具结果左侧恢复与 ontology-agent 一致的浅色圆形节点，节点内仅显示 `✓`，勾选颜色与工具标题一致，圆形背景使用对应颜色的浅色版本。
- 移除旧版最左侧额外小圆点，步骤容器向右留出约两格；节点之间使用独立时间线元素绘制浅灰色竖线并穿过圆形节点中心；仅工具名称加粗，摘要和耗时保持普通灰色字体。
- 页面：智能分析、报表分析会话区及系统调用记录。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`。

### 24. 工具步骤零间距

- 工具结果步骤之间取消 ThoughtChain 默认链间距、标题行留白和展开容器底部留白，连续步骤按紧凑行排列。
- 展开后的输入、输出气泡保留自身内容间距，不再额外生成包住整个步骤的外层空白框。
- 页面：智能分析、报表分析会话区及历史会话恢复后的工具结果时间线。
- 主要文件：`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`。

### 25. 列表型问题按意图跳过无意义图表

- 对“列出本体里所有业务对象”“可分析业务对象”等枚举型问题增加确定性的意图识别：当候选图表的数值列全部相同（通常每项都是 1）时，不再生成或渲染没有比较意义的柱状图，只保留表格结果。
- 分析型问题仍按数据意义保留表格与图表配对；列表型问题如果误触发了图表工具，会返回表格优先的渲染提示并要求模型补充 `TableGenerate`，避免反复生成同一张无效图。
- 页面：智能分析、报表分析会话和看板。
- 主要文件：`bi_agent/tools/chart_policy.py`、`bi_agent/web/session.py`、`bi_agent/tools/chart_tools.py`、`bi_agent/tools/chart_multidim_tools.py`、`.claude/agents/bi-analyst.md`、`frontend/src/runtime.js`、`tests/test_regressions.py`。

### 26. ThoughtChain 使用 Ant Design 原生连接线

- 工具调用步骤的竖线改为直接使用 Ant Design X `ThoughtChain` 节点自带的连接线伪元素，不再依赖额外的自定义竖线 DOM；步骤之间的连接线在实时对话和历史会话中保持一致，最后一步自动隐藏连接线。
- 保留现有工具语义色、浅色圆形勾选、紧凑行间距和输入/输出展开气泡。
- 页面：智能分析、报表分析会话区及历史会话恢复。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/runtime.js`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`。

### 27. 输入框发送图标统一

- 输入框发送按钮改用统一的 16×16 SVG 发送箭头，替换原来的文本箭头字符。
- 保留原有按钮尺寸、颜色、点击发送逻辑及“发送”无障碍提示，实时对话和历史会话使用同一图标。
- 主要文件：`frontend/src/shell.html`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`。

### 28. 本体命中筛选图标

- 本体内容页面的命中实体筛选栏增加统一的漏斗图标和“筛选”提示，位于术语、业务对象等类型按钮之前。
- 保留原有按本体类型显示/隐藏的筛选逻辑，图标仅作为筛选栏的视觉标识。
- 主要文件：`frontend/src/shell.html`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`。

### 29. 发送按钮图标尺寸与颜色

- 发送按钮箭头改为白色，并从 16×16 放大为 24×24，提升在蓝色按钮上的可见性。
- 保留按钮尺寸、发送交互和无障碍提示不变。
- 主要文件：`frontend/src/shell.html`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`。

### 30. 收入导航图标

- CEO 驾驶舱、驾驶舱和共享 IBA 侧栏中的“收入”入口改用统一的收入/数据库 SVG 图标。
- 展开侧栏保留“收入”文字和原有链接；收起侧栏显示该 SVG 图标，其他导航项和跳转逻辑不变。
- 主要文件：`dashboard.html`、`ceo_dashboard_standalone.html`、`bi_agent/web/static/iba-shell.css`。

### 31. 侧栏与顶部导航图标统一

- 收起 IBA 侧栏时，CEO 驾驶舱和驾驶舱分别使用新的房屋 SVG 图标，收入图标继续使用已配置的 SVG；展开侧栏仍显示原有文字。
- 搜索入口改用新的放大镜 SVG，右上角待办/消息入口改用信封 SVG，原有点击、弹出和跳转行为保持不变。
- 主要文件：`dashboard.html`、`ceo_dashboard_standalone.html`、`bi_agent/web/static/iba-shell.css`。

### 32. 顶部账号与平台导航图标调整

- 右上角账号入口改用白色用户 SVG，系统语言入口改用六边形语言 SVG。
- 顶部平台导航移除产品功能、任务中心、运维平台、企业架构、开发交付和应用开发前的所有图标，仅保留文字标签。
- 主要文件：`dashboard.html`、`ceo_dashboard_standalone.html`、`bi_agent/web/static/iba-shell.css`。

### 33. 收起/展开图标状态修正

- 修正侧栏图标显示状态：收起时显示 CEO 驾驶舱、驾驶舱和收入 SVG，展开时仅显示原有文字。
- 共享侧栏样式版本更新为 `v=11`，避免浏览器继续使用旧版缓存样式导致显示状态反转。
- 清理旧的伪文字图标规则，保留原有侧栏宽度、折叠动画和导航行为。
- 主要文件：`dashboard.html`、`ceo_dashboard_standalone.html`、`bi_agent/web/static/iba-shell.css`。

### 34. 清空、看板与顶部操作图标

- 看板“清空”按钮的叉号改为垃圾桶 SVG；看板空状态和收起后的看板入口改用统一看板 SVG。
- 右上角系统语言、消息和用户图标统一为黑色 SVG，保留原有弹出和账号操作。
- 主要文件：`frontend/src/shell.html`、`frontend/src/workbench.css`、`dashboard.html`、`ceo_dashboard_standalone.html`、`bi_agent/web/static/iba-shell.css`。

### 35. 结果类型与智能分析导航图标

- 会话和看板中的图表类型徽标统一使用 SVG 图标：chart/pie 使用饼图图标，line/bar 使用柱形图图标；保留原有类型文字、颜色和跳转/渲染逻辑。
- 历史会话中已保存的旧徽标在恢复时同步补齐图标，避免新旧结果显示不一致。
- 外部 IBA 导航栏左上角的展开/收起按钮改用统一的四宫格 SVG 图标；内部智能分析入口和内部折叠按钮恢复原有图标，导航文案和切换行为保持不变。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`。

### 36. 报告操作按钮图标

- “导出本轮报告”“导出 Word”“同步到主页”“分享到飞书”改用统一的 SVG 图标，按钮文字、颜色、圆角和原有操作保持不变。
- 历史会话中已保存的旧操作按钮会在恢复时自动替换为对应图标；Word 报告整合中、完成下载和失败重试状态会继续保留 Word 图标。
- 主要文件：`frontend/src/runtime.js`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`。

### 37. 顶部导航图标与前端资源一致性

- 驾驶舱与 CEO 驾驶舱使用完全一致的四宫格展开/收起图标，修正驾驶舱页面图标路径不完整导致的显示差异。
- React 工作台静态资源版本号同步递增，确保历史浏览器不会继续使用旧版脚本和样式，实时会话、历史会话和看板加载同一份最新资源。
- 主要文件：`dashboard.html`、`bi_agent/web/static/index.html`。

### 38. 折叠看板按钮样式统一

- 看板折叠后显示的“展开看板”按钮改为与“+ 新对话”一致的蓝色背景和白色图标，悬浮状态使用更亮的蓝色，保留原有展开行为。
- 主要文件：`frontend/src/workbench.css`。

### 39. 外部导航与看板折叠图标统一

- 外部导航顶部四宫格图标改为白色；搜索、CEO 驾驶舱、驾驶舱和收入图标统一使用与 i-Agent 一致的蓝色。
- 看板右上角折叠按钮改用统一箭头 SVG，并按看板布局显示为向右箭头。
- 主要文件：`bi_agent/web/static/iba-shell.css`、`dashboard.html`、`ceo_dashboard_standalone.html`、`frontend/src/shell.html`、`frontend/src/workbench.css`。

### 40. 结果徽标与报告操作图标统一

- 会话和看板中的 TABLE 徽标改用统一的文档 SVG；pie、bar、line 等结果图标改为继承对应徽标颜色，不再显示灰色图标。
- “导出本轮报告”“导出 Word”“同步到主页”“分享到飞书”统一使用指定 SVG 图标；历史会话恢复时也会自动应用同一套图标。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/runtime.js`、`frontend/src/workbench.css`。

### 41. 报告操作按钮图标间距与颜色

- 四个报告操作按钮中的 SVG 图标改为继承按钮文字颜色，不再使用固定灰色。
- 图标与按钮文字之间增加统一间距，实时会话和历史会话保持一致。
- 主要文件：`frontend/src/workbench.css`。

### 42. 分析 SOP 状态标识

- 分析 SOP 移除步骤之间的竖向连接线和 Ant Design 默认圆形节点。
- 已完成步骤显示绿色 `✓` 与绿色标题；当前步骤显示蓝色圆圈与蓝色标题；待执行步骤显示灰色圆圈与灰色标题。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/workbench.css`。

### 43. 历史会话移除残留流式光标

- 完成任务收到终止事件时，先强制结束最后一条助手消息的流式状态，再保存会话。
- 保存会话时过滤临时光标，恢复历史会话时也清理旧快照中的光标，避免已完成任务重新打开后仍显示闪烁光标。
- 主要文件：`frontend/src/runtime.js`。

### 44. 历史会话绑定最后任务的分析 SOP

- 每个会话保存自己最后一条任务的六步分析 SOP；切换到历史会话时恢复该会话的进度，不再沿用当前会话的 SOP 状态。
- 成功收到任务终止事件后，当前任务的 SOP 统一标记为已完成；旧历史记录没有 SOP 数据时按已完成会话展示完整六步，避免最后一步长期显示进行中。
- 页面：智能分析会话区顶部的“分析 SOP”和历史会话恢复。
- 主要文件：`frontend/src/runtime.js`、`bi_agent/web/app.py`、`bi_agent/web/conversations.py`、`tests/test_regressions.py`。

### 45. 结论类结果徽标位置统一

- 会话和看板中的“结论”“根因分析”“行动建议”徽标统一放到对应内容气泡的右上角，正文保持左侧自然阅读顺序。
- 实时生成、历史会话恢复和看板恢复使用同一套位置规则。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/workbench.css`。

### 46. 语义结果徽标图标统一

- “根因分析”“结论”“行动建议”使用统一的 SVG 图标，实时会话、历史会话和看板保持一致。
- 图标使用 `currentColor` 跟随徽标文字和边框颜色，避免图标与徽标颜色不一致。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/workbench.css`。

### 47. 对话气泡与思维链展示调整

- 助手、结论、根因分析、行动建议、图表结果和工具输入输出统一使用更有层次的冷灰色气泡，并保留轻边框和阴影。
- 思维链工具步骤的可点击行高调整为原来的约两倍，展开和收起操作更容易点击。
- 增加模型回答格式约束，并在前端兼容清理装饰性表情符号前缀；结论、徽标等由界面统一展示，避免回答中重复出现图标。
- 主要文件：`frontend/src/workbench.css`、`frontend/src/runtime.js`、`frontend/src/main.jsx`、`bi_agent/web/session.py`。

### 48. 发送按钮与 SOP 行高统一

- 发送箭头固定为原始 SVG 的 1.5 倍尺寸（24px），避免不同浏览器或缓存样式造成大小漂移。
- 分析 SOP 的六个步骤统一使用约 40px 的可点击行高，展开和收起时保持一致。
- 主要文件：`frontend/src/workbench.css`。

### 49. 智析品牌图标统一

- 新建智能分析对话时不再显示原来的大号菱形空状态占位图标。
- 外部 IBA 侧栏的 i-Agent 图标与内部功能栏“智析”左侧标记统一使用新的四象限 SVG 图标。
- 图标保持原有显示尺寸，并沿用外部导航蓝色和内部功能栏蓝色的颜色体系。
- 主要文件：`frontend/src/shell.html`、`frontend/src/runtime.js`、`frontend/src/main.jsx`、`frontend/src/workbench.css`、`dashboard.html`、`ceo_dashboard_standalone.html`、`bi_agent/web/static/iba-shell.css`。

### 50. 内部功能栏图标统一

- 智能分析、报表分析、内容区、设置区和底部分析员入口统一替换为指定 SVG 图标。
- 图标保持原有 16px 尺寸，并使用菜单当前状态的灰色/蓝色继承色，选中状态与文字同步高亮。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/workbench.css`。

### 51. SOP 行高与功能图标显示修正

- 分析 SOP 步骤行高调整为原来的约 75%，保留完整点击区域和文字对齐。
- 修复内部功能栏 SVG 画布被继承颜色填充导致显示为黑色方块的问题；图标现在按菜单状态显示黑色或蓝色。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/workbench.css`。

### 52. 功能栏图标间距与分析员对齐

- 本体内容和模型参数图标保持 SVG 的镂空轮廓，不再将透明画布或内部空白误填为黑色。
- 内部功能栏所有图标与文字统一保留一格间距；底部分析员图标和文字改为垂直居中排列。
- 主要文件：`frontend/src/workbench.css`。

### 53. 智能分析图标替换

- 智能分析入口改用指定的线条式 SVG 图标，尺寸和菜单状态颜色保持不变。
- 主要文件：`frontend/src/main.jsx`。

### 54. 本体内容与模型参数图标改为描边

- 本体内容、模型参数图标改为透明填充的外轮廓和内圆描边，闭合线之间保持透明，不再出现整体黑色填充。
- 保留菜单未选中黑色、选中蓝色的状态颜色。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/workbench.css`。

### 55. 用户选择卡片圆角统一

- “需要您选择”徽标、选择卡片外框、1/2/3/4 数字标记和选项按钮统一增加圆角。
- 选择卡片的确认按钮也使用同一套圆角，和会话区其他操作控件保持一致。
- 主要文件：`frontend/src/workbench.css`。

### 56. 本体与模型图标线宽统一

- 本体内容和模型参数图标恢复指定 SVG 的 even-odd 轮廓渲染，外圈与内圈保持一致线宽，中心区域继续透明。
- 主要文件：`frontend/src/workbench.css`。

### 57. 会话与看板图表标题去重

- 会话和看板中的图表卡片统一保留卡片标题栏，移除 ECharts HTML 内重复渲染的同名标题。
- 对旧历史记录中只有 Canvas、没有图表配置的图表，保留 Canvas 内标题并隐藏新增卡片标题，避免历史会话出现两次标题。
- 仅影响应用内的图表展示，导出或单独打开的 HTML 图表仍保留原始标题。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/runtime.js`、`frontend/src/workbench.css`。

### 58. 本体内容与模型参数图标改为纯描边

- 本体内容和模型参数图标的外轮廓、内圈统一使用描边渲染，去除两条闭合线之间的填充色。
- 保留菜单未选中黑色、选中蓝色的状态颜色和原有图标尺寸。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/workbench.css`。

### 59. 图标内圈线宽统一

- 将本体内容和模型参数图标的内圈从复合填充路径拆为独立圆形描边，内圈与外轮廓使用完全一致的线宽。
- 两条闭合线之间保持透明，不再出现内圈过粗或区域被填黑的问题。
- 主要文件：`frontend/src/main.jsx`。

### 60. 历史会话恢复本体与数据源

- 会话保存本次实际使用的本体源、数据库源、检索模式、图库源及 Doris 连接参数（不保存密码）。
- 打开历史会话时先恢复对应数据源，因此进入“本体适配”或“数据源”看到的是该会话使用的配置，后续追问也继续使用同一数据源。
- 对没有数据源快照的旧历史记录，按历史 SQL 中的 ontology_* schema 做兼容推断；无法识别时继续沿用当前配置，不影响已有会话打开。
- 主要文件：`frontend/src/runtime.js`、`bi_agent/web/app.py`、`bi_agent/web/conversations.py`、`tests/test_regressions.py`。

### 61. 历史图表渲染稳定性

- 修复历史会话恢复时 React 卡片尚未完成挂载就初始化 ECharts，导致图表偶尔空白的问题。
- 图表、看板图表和多维图表统一采用挂载后重试、实例复用和尺寸监听，避免重复初始化并在卡片完成布局后自动重绘。
- 主要文件：`frontend/src/runtime.js`。

### 62. 日报文件纳入版本管理

- 移除 `.gitignore` 对 `日报.md` 的忽略规则，日报内容现在可以被 Git 跟踪和提交。
- 主要文件：`.gitignore`、`日报.md`。

### 63. Doris 凭据不再回传前端

- 数据源接口不再在浏览器端返回已保存的 Doris 密码，避免密码出现在 API 响应和浏览器开发者工具中。
- 数据源保存时，空密码输入表示保留原有密码；只有用户明确输入新密码时才更新。
- 主要文件：`bi_agent/web/app.py`、`frontend/src/runtime.js`、`tests/test_regressions.py`。

### 64. 数据源切换失败自动回滚

- 本体、数据库、检索模式和图库源的切换现在按一个状态事务执行；后续校验或工具重绑定失败时恢复切换前的完整状态。
- 避免出现“本体已经切换、数据库仍是旧源”的半成功状态，历史会话恢复遇到失效源时也能继续保持当前可用配置。
- 主要文件：`bi_agent/web/app.py`、`tests/test_regressions.py`。

### 65. 内部功能栏统一滚动

- 修复 `dashboard.html?view=iagent` 左侧内部导航栏只有历史会话可以滚动的问题。
- 整个功能栏现在使用统一的纵向滚动区域，顶部搜索、功能菜单、历史会话和底部菜单在较小屏幕上都可以正常查看。
- 同步更新共享侧栏资源版本，避免浏览器继续使用旧版样式。
- 主要文件：`dashboard.html`、`bi_agent/web/static/iba-shell.css`。

### 66. 内层工作台功能栏资源同步

- 修复外层 `dashboard.html?view=iagent` 已更新，但内层 `/workbench` 仍加载旧版 `v=31` 静态资源，导致功能栏滚动修复实际未生效的问题。
- 重新构建并同步工作台的 HTML、CSS、JavaScript 资源，内层功能栏统一使用 `v=35`，顶部功能、任务清单、历史会话和底部账号区域共用同一滚动容器。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/workbench.css`、`bi_agent/web/static/index.html`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`。

### 67. 新会话按钮高度统一

- 固定“+ 新会话”按钮展开和收起状态均为 40px 高，与侧栏其他菜单按钮保持一致。
- 覆盖 Ant Design 默认按钮高度，保留原有宽度、圆角和交互效果。
- 主要文件：`frontend/src/workbench.css`。

### 68. 最近会话独立滚动

- 最近会话区域增加独立的内嵌纵向滚动，最多占用约 140–260px 的高度，历史会话较多时不会把顶部功能和底部账号区域推得很远。
- 外层功能栏的统一滚动仍然保留，最近会话区域使用独立滚动边界，避免滚轮操作相互串联。
- CSS 资源版本更新为 `v=36`，避免浏览器继续使用旧缓存。
- 主要文件：`frontend/src/workbench.css`。
