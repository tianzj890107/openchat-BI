# openchat-BI 变更记录

> 本文档记录本项目的用户可见功能、接口、模型、数据源和运行方式变更。

## 维护规则

- 每次发布或一组相关修改按日期追加，不记录单个操作步骤或中间尝试。
- 每条记录只描述相对于上一版本的最终用户可见差异；同一功能的多次调整合并为一条。
- 每条记录至少说明：用户可见变化、涉及页面、主要文件、是否需要重启后端。
- HTML/CSS/JS 静态资源修改：刷新浏览器即可；Python、模型、接口、依赖或数据源实现修改：需要重启后端。
- 本地后端地址：`http://127.0.0.1:8765`。

## 2026-07-30

### 1. Ant Design 迁移第一阶段：左侧导航栏

- 新增 React + Vite + Ant Design 构建入口，左侧导航栏先迁移为 Ant Design `Layout/Sider/Menu`，支持收起/展开、智能分析/报表分析切换、内容与设置页面跳转、最近会话和账号入口。
- 通过事件桥接保留原有导航 ID、`data-view`、`data-mode` 和历史会话逻辑；对话 SSE、看板、本体、系统调用和后端接口未改变，便于逐步迁移和回退。
- 主要文件：`frontend/package.json`、`frontend/vite.config.js`、`frontend/src/main.jsx`、`bi_agent/web/static/index.html`、`bi_agent/web/static/styles.css`。
- 类型：前端构建与静态资源变更；本阶段本地构建验证通过，服务器暂不部署，待确认导航栏效果后继续迁移。

### 2. Ant Design 迁移第二阶段：SOP 与任务清单

- 对话区顶部的“分析 SOP”和“任务清单”改为 React + Ant Design `Collapse/List/Progress/Tag`，SOP 节点使用 Ant Design X `ThoughtChain` 展示；两个面板默认折叠，用户提问仍可点击定位到对话。
- 旧版 SOP/任务清单 DOM 继续保留为隐藏数据桥，现有回合进度、问题列表、历史恢复和原生事件不变；本阶段只迁移展示层。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/index.html`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/vendor/antd/sidebar.js`。
- 类型：前端静态资源变更；本地构建验证后需刷新浏览器，不部署服务器。

### 3. Ant Design 迁移第三阶段：对话消息气泡

- 用户消息和 Agent 文本输出改为 Ant Design X `Bubble` 渲染，分别使用右侧蓝色气泡和左侧浅灰气泡；迭代标题和流式文本继续由原有 SSE DOM 数据驱动。
- 原消息节点、回合定位、滚动、工具步骤和历史恢复逻辑保留；React 渲染失败时旧消息仍可作为回退路径。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更；本地构建验证后需刷新浏览器，不部署服务器。

### 4. Ant Design 迁移第四阶段：工具调用思维链

- 对话中的 OntologyQuery、SQLRun、图表生成等工具步骤改为 Ant Design `Collapse` 展示，保留工具名、摘要、耗时以及输入/输出详情；步骤仍支持展开查看。
- 原工具节点继续保留为隐藏回退 DOM，SSE 工具结果、本体命中项和历史恢复逻辑不变。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更；本地构建验证后需刷新浏览器，不部署服务器。

### 5. Ant Design 迁移第五阶段：结果卡片

- 对话中的图表、表格和多维图表结果改为使用 Ant Design `Card` 作为外层容器；原 ECharts 画布、表格滚动区、维度选择和摘要节点继续复用，交互和数据不变。
- 结果卡片保留原有隐藏回退 DOM，历史恢复和旧浏览器路径不会因 React 加载失败而丢失。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更；本地构建验证后需刷新浏览器，不部署服务器。

### 6. Ant Design 迁移第六阶段：看板结果卡片

- 右侧看板中新生成的结论、图表、表格、根因和行动结果统一使用 Ant Design `Card` 外层容器，保留原有内容、按钮、图表画布和定位行为。
- 看板旧 DOM 继续作为回退路径，历史恢复、对话联动和后端数据契约不变。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更；本地构建验证后需刷新浏览器，不部署服务器。

### 7. 历史内容兼容迁移

- 历史会话和历史看板恢复的旧 HTML 会自动重新挂载到 React/Ant Design 展示层，历史消息、工具步骤、图表、表格和结果卡片不再因恢复路径不同而继续使用旧样式。
- 新生成内容与历史恢复内容共用同一套增强观察器，旧 DOM 仍保留作回退。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/index.html`、`CHANGELOG.md`。
- 类型：前端静态资源变更；本地构建验证后需刷新浏览器，不部署服务器。

### 8. IBA 外层导航默认收起

- CEO 驾驶舱、驾驶舱和 i-Agent 页面进入时默认收起最左侧 IBA 外层导航，内容区域直接铺开；顶部菜单按钮仍可手动展开，原有拖拽宽度和页面跳转不变。
- 页面：`ceo_dashboard_standalone.html`、`dashboard.html`。
- 类型：HTML/CSS 状态变更；刷新页面即可生效，本次部署服务器后无需重启后端。

### 9. IBA 外层导航展开动画统一

- CEO 驾驶舱和驾驶舱/i-Agent 的 IBA 侧栏展开、收起、内容区左边距同步使用平滑缓动，侧栏不再瞬间出现，和内容区滑动保持一致。
- 页面：`ceo_dashboard_standalone.html`、`dashboard.html`。
- 类型：HTML/CSS 静态资源变更；刷新页面即可生效。

### 10. 侧栏拖拽条默认透明

- 移除 IBA 侧栏展开前短暂出现的灰色竖条；拖拽条默认透明，仅在悬停或拖拽时显示蓝色提示线。
- 页面：`ceo_dashboard_standalone.html`、`dashboard.html`。
- 类型：HTML/CSS 静态资源变更；刷新页面即可生效。

### 11. 仅保留 React/Ant Design 工作台侧栏

- 隐藏旧版静态侧栏，只保留后续迁移的 React + Ant Design 侧栏作为唯一可见导航；旧 DOM 仅保留为不可见事件桥，避免重复显示并保持原有页面跳转兼容。
- 页面：`bi_agent/web/static/index.html`、`bi_agent/web/static/styles.css`。
- 类型：HTML/CSS 静态资源变更；刷新页面即可生效。

## 2026-07-29

### 15. 看板气泡统一与来源信息隐藏

- 右侧看板用户问题改为右对齐蓝紫气泡，结论、表格、图表和多维图表改为与会话一致的浅灰气泡。
- 隐藏看板中的 Source、表名和技术来源提示；这些信息仍保留在数据元信息中，不再干扰用户阅读。
- 缩小图表内部绘图区左侧网格留白，柱状图更靠左对齐；历史图表加载时也会移除旧的 Source 图形标记。
- 页面：智能分析、报表分析右侧看板及图表 HTML。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/app.js`、`bi_agent/web/static/index.html`、`bi_agent/tools/chart_tools.py`、`tests/test_regressions.py`。
- 类型：前端静态资源与图表生成后端变更；本次仅本地启动和验证，不部署服务器。

### 16. CEO 驾驶舱配色与操作按钮统一

- 对话和看板中的 HTML 图表、历史图表统一采用 CEO 驾驶舱的蓝 `#0B7FF3`、黄 `#E8B339`、绿 `#28C79D`、红 `#F05A5A` 语义色，图表画布与页面结果区保持浅色背景，避免整块黑底。
- “导出本轮报告（HTML）”“导出 Word”“同步到主页”“分享到飞书”以及根因分析、行动建议按钮统一使用 CEO 配色、黑色文字、圆角和轻微阴影，操作状态更容易区分。
- 页面：对话工作台和右侧用户看板；主要文件：`bi_agent/tools/chart_tools.py`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`、`tests/test_regressions.py`。
- 类型：前端静态资源、图表生成后端与离线回归测试变更；本次仅本地启动和验证，不部署服务器。

### 17. 工作台默认浅色画布

- 修复工作台打开后整个页面沿用深色根变量、看起来全黑的问题。新打开或未保存主题偏好的工作台默认使用 CEO 驾驶舱风格的浅色画布、白色面板和浅灰边框；仍可在个人偏好中切换深色主题。
- 通过新的主题偏好键隔离旧版本的深色默认值，避免升级后浏览器缓存把页面重新切回黑色。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更；本次仅本地启动和验证，不部署服务器。

### 18. 用户消息去除重复角色标签

- 对话气泡和右侧看板用户问题不再显示“用户”或 Turn 标签，只保留用户实际输入内容；左右对齐和气泡颜色继续用于区分发言者。
- 历史会话恢复时也通过样式隐藏旧版本已经保存的“用户”角色标题，避免重新打开历史后标签再次出现。
- 会话中的 pie、bar、多维图和 table 类型标签统一使用圆角徽标；pie、bar、多维图卡片补齐与 table 一致的浅色外框。
- 会话区和看板区的外层工作面统一为圆角卡片，内部按钮、操作菜单、深入洞察和维度选择控件统一使用圆角。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更；本次仅本地启动和验证，不部署服务器。

### 19. 会话与看板工作面圆角统一

- 会话区、看板区外层大卡片统一圆角；导出、行动、深入洞察、维度选择、确认等内部操作控件统一圆角，避免同一页面同时出现直角和圆角按钮。
- table、pie、bar 等类型标签调整为适中的 6px 倒角，不再呈现胶囊或圆形外观。
- 根因分析、行动建议等操作按钮同步改为浅色底、深色语义文字和对应边框，降低视觉饱和度。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更；本次仅本地启动和验证，不部署服务器。

### 20. 迭代思维链紧凑间距

- 压缩每次迭代中工具思考条目的上下留白和条目间距；`Ontology query · 业务对象 · 363ms` 等摘要更紧凑，点击展开的详细输入输出不变。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更；本次仅本地启动和验证，不部署服务器。

### 21. 会话与报表存储稳健性

- 会话历史和上传报表的 JSON 快照改为同目录临时文件校验后原子替换，避免并发保存或进程中断留下半截文件导致历史列表、图表恢复失败。
- 会话与报表时间统一按东八区写入，不再依赖运行主机的本地时区；SQL 结果格式化兼容列元数据缺失或行列数不一致的 Doris 返回值。
- 主要文件：`bi_agent/web/conversations.py`、`bi_agent/report/store.py`、`bi_agent/tools/sql_tools.py`、`tests/test_regressions.py`。
- 类型：后端持久化与 SQL 工具变更，需要重启本地和服务器后端；不调用 Qwen API。

### 14. 用户气泡与图表 HTML 全面去黑

- 用户气泡改为 CPQ 的蓝紫渐变并强制白色文字。
- ChartGenerate、ChartGenerateMultiDim、历史图表恢复和独立 HTML 图表统一使用浅色背景、深色文字和浅色边框；图表画布不再被黑色背景包住。
- 多维图表的工具栏、下拉框和图表页面同步改为浅色，保留规范配色的数据系列。
- 页面：智能分析、报表分析对话区、图表 HTML 打开页。
- 主要文件：`bi_agent/tools/chart_tools.py`、`bi_agent/tools/chart_multidim_tools.py`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`、`tests/test_regressions.py`。
- 类型：前端静态资源与图表生成后端变更，需要刷新浏览器并重启后端；本次部署未调用 Qwen API。

### 13. CPQ 浅灰气泡配色校正

- Agent 文本、迭代输出、图表、表格、根因分析和行动建议气泡改为与 `cpq_agent` 一致的浅灰 `#F7F7F8` 背景和浅色边框，文字同步改为深色，避免出现黑色气泡。
- 表格数据区域使用白色数据底和浅灰表头；图表画布保留独立深色绘图区以保证图表文字可读，外层气泡保持浅灰。
- 页面：智能分析、报表分析对话区。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 12. Agent 结果气泡与操作按钮强化

- Agent 的迭代文本、图表、多维图表、表格、根因分析和行动建议统一使用 CPQ 风格的炭灰圆角气泡，不再只有结论有背景。
- 表格数据本体继续保留内部边框；标题仍位于结果气泡内、但不进入表格数据框。
- 导出本轮报告、导出 Word、同步到主页、分享到飞书，以及根因/行动建议按钮改为整块有颜色的按钮，提升可识别性。
- 页面：智能分析、报表分析对话区。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 11. SOP 默认折叠与标题样式统一

- 分析 SOP 默认自动折叠，用户点击标题后可展开完整流程；任务清单继续默认折叠。
- “分析 SOP”和“任务清单”统一使用相同的字体、字号、字重、字间距、箭头和进度计数样式。
- 页面：智能分析、报表分析对话区。
- 主要文件：`bi_agent/web/static/index.html`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 10. SOP 总流程与任务清单分层

- 对话区新增可展开/收起的“分析 SOP”总流程栏，显示识别意图、准备上下文、规划取数、执行查询、深度分析和汇总交付的完整状态。
- 原任务清单保留用户问题定位和进度明细，但默认自动收起；需要查看问题列表或任务明细时可手动展开。
- 页面：智能分析、报表分析对话区。
- 主要文件：`bi_agent/web/static/index.html`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 9. Agent 输出气泡与迭代层级

- 每次大模型文本输出单独显示为 CPQ 风格的小型炭灰气泡，避免输出内容和页面背景混在一起。
- 连续迭代仍按原回合顺序显示，工具调用继续使用左侧 ThoughtChain 纵向步骤；不同迭代的文本输出保持独立气泡，任务切换时自然形成新的输出块。
- 页面：智能分析、报表分析对话区。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 8. 对话消息改为气泡与灰色内容块

- 用户消息改为右对齐的科技蓝气泡，Agent 消息改为左对齐的炭灰圆角内容块，底角保持对话气泡的区分样式。
- 保留现有任务跳转、流式输出、历史恢复、表格/图表和工具步骤功能；工具步骤、表格与操作内容继续嵌入对应 Agent 内容块中。
- 页面：智能分析、报表分析对话区。
- 参考实现：上级目录 `cpq_agent/XBOM智能体-配置BOM生成.html` 的 `.message-user` / `.message-ai` 视觉结构。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 7. 对话内容与表格边界分离

- 对话区的用户提问、图表/图片结果、表格标题、根因分析、行动建议和导出操作去掉外层卡片框，保留统一的标题与内容排版；用户提问仍可点击定位。
- 对话区表格只给数据本体增加边框，表格标题、摘要和脚注不再被包进表格框；右侧看板同步采用相同结构，表格边框不再包住标题。
- 页面：智能分析、报表分析对话区与右侧看板。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 6. 看板外层模块与思维链样式调整

- 右侧看板的用户提问、结论等外层模块去掉独立大边框和装饰条，保留内容层级与点击定位；表格恢复独立的圆角外框，确保表格本体仍有清晰边界。
- 左侧工具调用步骤改为 ThoughtChain 风格的纵向时间链：节点、连接线、可展开标题和详情内容更清晰，继续支持点击展开、查看输入输出和本体命中项。
- 页面：智能分析、报表分析对话区与右侧看板。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 5. 图表主题统一到设计规范

- 保留现有对话布局，仅统一对话内图表、历史会话恢复图表和多维图表的字体、文字层级与颜色。
- ChartGenerate/ChartGenerateMultiDim 生成的独立 HTML 图表同步使用科技蓝、活力橙、清新绿等低饱和规范色，以及 PingFang SC/SF Pro Display 字体；旧历史图表加载时也会自动套用同一主题。
- 页面：智能分析、报表分析的对话区、看板及图表 HTML 打开页。
- 主要文件：`bi_agent/tools/chart_tools.py`、`bi_agent/tools/chart_multidim_tools.py`、`bi_agent/web/static/app.js`、`bi_agent/web/static/index.html`、`tests/test_regressions.py`。
- 类型：前端静态资源与图表生成后端变更，需要刷新浏览器并重启后端；本次部署已重启后端，未调用 Qwen API。

### 2. 对话操作归位与低饱和视觉色彩

- 导出本轮报告、导出 Word、同步到主页、分享到飞书及根因分析/行动建议的操作控件统一放到左侧对话区对应 Agent 回合；右侧看板保留结论、图表和表格等结果展示。
- 对话工作台改用规范中的深黑、炭灰、科技蓝、活力橙、清新绿、灰白文字和 PingFang SC/SF Pro Display 字体，降低原有荧光青、荧光紫等高饱和颜色的视觉负担。
- 历史会话中的操作卡片仍可恢复交互，导出和同步内容仍包含对应回合的完整分析结果。
- 页面：智能分析、报表分析对话区与右侧看板。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 3. 看板内容按内容宽度展示

- 右侧看板中的图表、HTML 图形和多维图表使用稳定的可读宽度，不再自动撑满整个看板；窄屏时仍会限制在容器内。
- 用户问题、结论和表格卡片按内容宽度左对齐展示，保留必要的换行和横向滚动，不再全部顶开到最宽。
- 页面：智能分析、报表分析右侧看板。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 4. 看板结果卡片无框展示

- 图表、HTML 图形、多维图表和表格去掉灰色外框及左侧彩色装饰条，保留 `CHART/多维/TABLE` 标签、名称和结果本体。
- 隐藏结果卡片右上角的回合/来源提示，减少与图表内容无关的视觉信息。
- 页面：智能分析、报表分析右侧看板。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 1. 导航栏默认收起与图标栏

- 首次进入工作台时左侧导航默认收起为窄图标栏，不再完全消失。
- 收起后保留新对话、智能分析、报表分析、本体内容、系统调用、设置、历史和账号等入口图标；点击同一顶部图标可在窄图标栏和完整文字导航之间切换。
- 页面：智能分析、报表分析及本体工作台各内容页。
- 主要文件：`bi_agent/web/static/index.html`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

## 2026-07-28

### 5. 对话消息层级区分

- 用户提问增加浅灰背景、边框和内边距；相邻用户消息与 Agent 输出之间增加垂直间隔，减少长对话中的混读。
- 页面：智能分析、报表分析对话区。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 4. 任务清单与看板联动定位

- 点击任务清单中的用户提问时，同时定位聊天区和右侧看板中同一回合的提问卡片，并从各自滚动区域顶部开始展示；看板折叠时会自动展开并高亮对应卡片。
- 保留从看板提问卡片反向定位聊天区的行为，两个入口使用同一回合锚点。
- 页面：智能分析、报表分析的任务清单与右侧看板。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次部署已重启后端。

### 3. 全流程稳定性与安全性修正

- 修复模型流式请求出错后仍被当作正常完成、保存残缺会话的问题；错误回合不再写入完成态历史。
- Qwen/DeepSeek 的 OpenAI 兼容转换现在保留图片消息，视觉模型可以收到原始图片内容。
- 修正 Qwen 3.5 Plus 模型别名指向错误的问题；额度或限流时仍按同类模型自动切换。
- 历史会话 ID、报表 ID、数据源/图库/本体文件路径增加校验，避免非法输入访问工作目录外文件。
- 本体库列表按接口文档的 `total` 分页读取，不再只显示第一页；损坏的历史/报表元数据会被安全跳过。
- 增加不触发大模型的 `/healthz` 服务探针，并修正前端 CSS 缓存版本，保证新交互样式及时生效。
- 主要文件：`bi_agent/llm/provider_qwen.py`、`bi_agent/llm/provider_deepseek.py`、`bi_agent/llm/registry.py`、`bi_agent/web/session.py`、`bi_agent/web/app.py`、`bi_agent/web/conversations.py`、`bi_agent/report/store.py`、`bi_agent/web/static/index.html`、`bi_agent/web/static/styles.css`、`tests/test_regressions.py`。
- 类型：模型、后端接口与前端静态资源变更，需要重启后端；本次未调用 Qwen API。

### 2. 用户提问索引与定位

- 任务清单现在独立展示当前会话的全部用户提问，不再需要从长对话内容中寻找问题。
- 点击任务清单中的问题可跳转到对话中的对应位置；右侧看板的用户提问卡片也支持点击定位。
- 打开历史会话后会根据该会话的对话内容重建问题列表，不会残留上一个会话的问题。
- 页面：智能分析、报表分析、任务清单和右侧看板。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次已重启后端。

### 1. 看板按用户提问组织分析结果

- 每次分析开始时，最右侧看板先显示“用户”和本轮提问内容。
- 该提问卡片之后再追加本轮结论、根因、建议、表格和图表，历史会话恢复后顺序保持一致。
- 页面：智能分析、报表分析右侧看板。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次已重启后端。

## 2026-07-27

### 15. CEO 顶部导航与外层入口修正（历史）

- CEO驾驶舱顶部平台导航恢复深色样式，避免被响应式浅色主题覆盖。
- “驾驶舱”明确跳转 `/dashboard.html`；“i-Agent”明确跳转 `/dashboard.html?view=iagent`。
- 修复从 CEO驾驶舱点击入口时驾驶舱无法进入、i-Agent 无法跳转的问题。
- 主要文件：`ceo_dashboard_standalone.html`、`ceo_dashboard.html`。
- 类型：页面静态资源变更，刷新页面即可；本次已重启后端。

### 14. 驾驶舱与 i-Agent 页面入口和侧栏统一

- 从 CEO驾驶舱点击“驾驶舱”时默认进入真正的驾驶舱，不再自动跳到 i-Agent。
- i-Agent 仅在点击 i-Agent 菜单或访问 `/dashboard.html?view=iagent` 时打开。
- 统一驾驶舱和 i-Agent 外层 IBA 侧栏的搜索栏、菜单项高度、字号、子菜单间距和按钮样式。
- 主要文件：`dashboard.html`、`CHANGELOG.md`。
- 类型：页面静态资源变更，刷新页面即可；本次已重启后端。

### 12. CEO / 驾驶舱外层 IBA 侧栏统一与可调宽度

- 撤销 i-agent 内部侧栏的错误样式改动，恢复 i-agent 自身页面原有侧栏。
- `ceo_dashboard_standalone.html` 和 `dashboard.html` 的外层 IBA 侧栏统一为 CEO 驾驶舱的浅蓝分组样式。
- IBA 侧栏默认宽度为 248px，支持拖拽右侧分隔条调整，宽度在 CEO 驾驶舱和驾驶舱页面之间共享保存。
- 页面：CEO驾驶舱、驾驶舱及其下方的 IBA 菜单（CEO驾驶舱 / 驾驶舱 / 收入 / i-Agent）。
- 主要文件：`ceo_dashboard_standalone.html`、`dashboard.html`、`bi_agent/web/static/styles.css`。
- 类型：外层页面与前端静态资源变更，刷新页面即可；本次已重启后端。

### 13. 修正 IBA 侧栏样式覆盖范围

- 修正驾驶舱页面样式只写在桌面媒体查询内、导致常规桌面宽度未生效的问题。
- 现在 `dashboard.html` 的外层 IBA 侧栏在正常桌面尺寸下也使用 CEO 驾驶舱样式并显示拖拽分隔条。
- 主要文件：`dashboard.html`。
- 类型：页面静态资源变更，刷新页面即可；本次已重启后端。

### 11. 历史会话图表恢复

- 历史会话保存图表的完整 ECharts 配置，不再只保存空的 canvas 容器。
- 恢复历史会话时重新初始化普通图表和多维图表，保留维度切换、深入洞察按钮和自适应尺寸。
- 同时修复聊天区内嵌图表恢复后空白的问题。
- 历史图表 HTML 改用本地 ECharts 资源；旧图表链接也会在服务端自动替换 CDN 地址，点击后可正常自动渲染。
- 页面：最近历史会话、智能分析/报表分析聊天区和看板。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次已重启后端。

### 10. 工作区栏目宽度可拖拽调整

- 保留原有默认布局比例。
- 左侧导航栏和工作区“对话 / 看板”分隔条支持鼠标拖拽调整宽度。
- 宽度保存到浏览器本地存储，重新打开页面后继续使用；独立的本体内容、系统调用页面自动占满剩余空间。
- 页面：主工作区、左侧导航。
- 主要文件：`bi_agent/web/static/index.html`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/app.js`。
- 类型：前端静态资源变更，刷新浏览器即可；本次已重启后端。

### 9. 分析进行中的页面与历史导航

- 智能分析进行中仍可点击“智能分析”“报表分析”“本体内容”“系统调用内容”和最近历史。
- 切换分析模式或恢复历史会取消当前浏览器端流式响应，避免后台输出串入另一个会话页面。
- 不再因为分析中的忙碌状态禁用模式按钮和历史记录。
- 页面：左侧导航、最近历史会话、智能分析/报表分析工作区。
- 主要文件：`bi_agent/web/static/app.js`。
- 类型：前端交互变更，需要刷新浏览器；本次已重启后端。

### 1. Doris 数据源改为 HTTP API 调用

- 数据源设置不再要求填写 JDBC 地址，改为填写 Doris HTTP API 地址。
- 默认接口：`http://172.16.5.181:30834/agent/doris/query`。
- `SQLRun`、`ListTables`、`DescribeTable` 均通过 `POST /agent/doris/query` 执行只读 SQL。
- 数据库库名仍单独填写，默认值为 `ontology_demometaerp_scm_po`。
- 保留旧 JDBC 参数作为兼容展示/配置字段，但活动 Doris 查询不再使用它们。
- 页面：数据源设置、本体适配中的数据库源区域。
- 主要文件：`bi_agent/tools/sql_tools.py`、`bi_agent/web/app.py`、`bi_agent/web/static/index.html`、`bi_agent/web/static/app.js`。
- 类型：后端接口与前端配置变更，需要重启后端。

### 2. Doris 默认库名统一

- 默认 Doris JDBC schema 和数据库名统一为 `ontology_demometaerp_scm_po`。
- 不再根据 MetaERP 本体接口返回的 `dorisDatabase` 自动覆盖用户填写的数据库。
- 实际查询使用用户在数据源设置中填写的数据库名；未填写时使用上述默认值。
- 主要文件：`bi_agent/tools/sql_tools.py`、`bi_agent/web/app.py`、`bi_agent/web/static/index.html`。
- 类型：后端数据源配置变更，需要重启后端。

### 3. 默认数据库源改为 API·Doris 实时查询

- 打开网页或新建对话时，默认数据库源为 `API·Doris 实时查询`，不再默认使用 `HyperFusion.db`。
- 本地 SQLite 文件仍保留在数据库源列表中，可手动选择。
- 主要文件：`bi_agent/web/__main__.py`、运行启动参数。
- 类型：启动配置变更，需要以 `--db doris` 启动后端。

### 4. Qwen 模型额度耗尽自动切换

- Qwen 当前模型遇到额度耗尽、429、限流或资源耗尽错误时，自动按环境变量模型列表切换到下一个同类型模型。
- 文本模型只在文本模型之间切换，视觉模型只在视觉模型之间切换。
- 成功切换后保存新的当前模型，后续请求直接使用可用模型。
- 页面：模型设置和对话流状态提示。
- 主要文件：`bi_agent/llm/registry.py`、`bi_agent/llm/provider.py`、`bi_agent/web/session.py`。
- 类型：模型调用逻辑变更，需要重启后端。

### 5. 最近历史会话修复

- 新对话会正确清空标题缓存，不再全部复用最早一条问题作为标题。
- 点击历史会话时不再无条件更新当前会话时间，避免当前会话反复跳到列表最上方。
- 每条历史记录保持自己的标题、内容和排序。
- 会话标题固定为该会话第一条问题的小标题；点击查看历史只读不改变列表，只有追加问题并完成任务后才更新该会话时间并置顶，后续问题不会改标题。
- 历史记录列表和恢复内容也会按已保存消息中的第一条用户问题校正标题，避免旧记录继续显示后续问题生成的名称。
- 最近历史列表条目改为自然展开，标题可换行；侧栏空间不足时只在历史区域滚动，不再压缩条目造成重叠。
- 历史会话增加服务器主来源同步：本地任务完成后推送到服务器，历史列表优先读取服务器数据；服务器不可用时回退本地缓存。
- 本地恢复服务器已有但本地没有缓存的历史时，增加服务器记录回退读取，不再因两端历史生成时间不同而无法打开。
- 恢复历史会话时同步恢复该会话的本体内容、系统调用记录和模型调用记录，并更新对应计数，不再继续显示上一个会话的侧栏数据。
- 页面：左侧“最近”历史会话列表。
- 主要文件：`bi_agent/web/static/app.js`。
- 类型：前端静态资源变更，刷新浏览器即可；本次已随服务重启生效。

### 6. MetaERP 生产本体服务接入与名称统一

- 本体源显示名称统一为 `MetaERP`。
- 生产本体通过 `ONTOLOGY_BASE_URL` 和 `ONTOLOGY_REPOSITORY_ID` 调用团队本体服务。
- 支持本体对象解析、关系查询、脚本查询和元数据查询；本地 Excel 仅作为兼容回退数据结构。
- 检索模式名称恢复为“语义检索模式(基于 Excel 本体)”和“图库检索模式(图库 + Excel 本体)” 。
- 页面：本体适配、检索模式和本体检查器。
- 主要文件：`bi_agent/ontology/remote.py`、`bi_agent/tools/remote_ontology_tools.py`、`bi_agent/web/app.py`、`bi_agent/web/static/app.js`。
- 类型：后端接口与前端配置变更，需要重启后端。

### 7. Qwen 提供商和模型目录

- 增加 Qwen OpenAI-compatible API 调用支持。
- 复用 `QWEN_API_KEY`、`QWEN_BASE_URL`、`QWEN_MODEL`、`QWEN_TEXT_MODEL`、`QWEN_VISION_MODELS`、`QWEN_TEXT_MODELS` 等环境变量。
- 模型选择器动态展示环境变量中的文本和视觉模型。
- 支持 Qwen 视觉模型和文本模型分别配置。
- 主要文件：`bi_agent/llm/provider_qwen.py`、`bi_agent/llm/provider.py`、`bi_agent/llm/registry.py`、`bi_agent/llm/runtime_config.py`、`pyproject.toml`。
- 类型：模型提供商和依赖变更，需要重启后端。

### 8. 服务启动与数据源验证

- 后端当前启动方式：

  ```bash
  .venv/bin/python -m bi_agent.web --host 127.0.0.1 --port 8765 --db doris
  ```

- `/api/sources` 可查看当前生效的数据源、Doris HTTP API 地址和数据库名。
- 已验证 Doris HTTP API 执行 `SELECT 1 AS connection_check` 返回正常。
- 类型：运行配置说明，无代码页面变更；启动配置变更需要重启后端。

## 2026-07-27

### 17. 历史会话中的操作步骤可重新展开

- 修复打开历史会话后，智能体每一步操作、系统调用、本体卡片和模型调用卡片无法点击展开的问题。
- 恢复历史内容后重新绑定步骤标题、工具卡片、本体卡片、模型调用卡片及本体实体跳转事件。
- 页面：智能分析、报表分析及历史会话。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/index.html`。
- 类型：前端静态资源变更，刷新浏览器即可；本次已重启后端。

### 16. 当前版本：CEO、驾驶舱与 i-Agent 外层统一

- 相比上一版，三个入口最终统一为 CEO 驾驶舱的浅色顶部栏：EIMOS 品牌区、圆形汉堡按钮、平台导航图标、激活态、字号间距、语言/通知/账号图标及弹层结构一致。
- 驾驶舱默认进入 `dashboard.html`，i-Agent 使用 `dashboard.html?view=iagent`，两者不再互相误跳；IBA 外层侧栏保留可拖拽宽度并在入口间共享。
- 桌面宽屏不再被旧媒体查询覆盖为黑色顶部栏，搜索区域保持居中。
- 顶部语言、通知和账号内容默认隐藏，只有点击对应图标时才显示 CEO 同款白色弹层，不再直接堆在右侧。
- 修正驾驶舱和 i-Agent 外层搜索栏图标仍被旧 `margin-left:auto` 推到右侧的问题，搜索文字与图标现在整体居中。
- 本体适配现在按文档调用 `/system/manager/ontology-repository?page=1&size=100`，把远程本体库的真实名称（例如“光峰科技本体库-勿动”）全部加入可选列表；选择后使用对应 repository ID 实时调用本体服务，并保留本地 Excel 选项。
- 本体适配中选择远程本体库不会自动改动数据库源；进入数据源后点击“读取当前数据源”，才会将当前本体库的 `dorisDatabase` 填入数据库库名输入框。
- 左侧“设置”菜单顺序调整为“本体适配”在上、“数据源”在下，便于先选择本体库再读取对应数据库库名。
- 本体源下拉框增加未保存提示：切换远程本体库后必须点击“保存并切换”，直接进入数据源页面不会把临时选择当作已生效配置。
- 本体适配的“本体源”保留原有本地 Excel 选项，并追加四个远程真实名称：光峰科技本体库-勿动、测试本体库、开发联调本体库、MetaERP本体库-勿动；`__metaerp_repository__:*` 仅作为内部值，不再显示给用户。
- 数据源的 Doris“数据库(库名)”旁新增“读取当前本体库库名”按钮，可将当前远程本体库的 `dorisDatabase` 自动填入输入框；本地 Excel 源没有该字段时会提示原因。
- 页面：`ceo_dashboard_standalone.html`、`dashboard.html`（驾驶舱及 i-Agent 外层视图）。
- 主要文件：`ceo_dashboard_standalone.html`、`dashboard.html`。
- 类型：前端静态资源变更；已重启后端，浏览器强制刷新即可生效。
