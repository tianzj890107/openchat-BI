# openchat-BI 变更记录（2026-08-17 至 2026-08-21）

> 本文档记录本周已完成的最终用户可见功能变化，已合并 8 月 17、18、19、20、21 日每日变更记录。

## 维护规则

- 每组相关修改合并为一条记录，不记录中间尝试或单纯文件同步。
- 周记录使用高于日报的颗粒度，保留用户可见变化、影响范围、主要文件和验证结果。
- 本周每日 changelog 已完成归档合并，后续只维护本周周 changelog。

## 2026-08-17 至 2026-08-21

### 1. 图表统一为 Pro UI 组件并规范数字展示

- 会话、历史会话、看板和多维图表统一改用 Pro UI 默认图表组件（`ProBarChart`/`ProHorizontalBarChart`/`ProLineChart`/`ProAreaChart`/`ProPieChart`），图表标题由组件内部渲染，移除外层重复标题与旧 Ant Design 结果气泡，保留历史恢复、看板、导出、维度切换、数据来源和口径说明。
- 图表保存链接（`saved: chart-...html`）移至图表下方，不再占用标题区域；看板图表画布高度与会话统一。
- 全局数字展示规范：大数千位分隔、数值列右对齐、金额达万用 `¥12.34万`、零值固定 `¥0.00`。
- 8 月 21 日将 `pro-bi-ui.min.js` 升级到 Pro UI 文档站最新 UMD 产物（`?v=2`），`vue.global.js` 保持不变。
- 主要文件：`frontend/src/runtime.js`、`frontend/public/lib/`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/lib/pro-bi-ui.min.js`、`bi_agent/web/static/index.html`。

### 2. 单双栏布局演进：从地址参数到容器尺寸自适应

- 8 月 17 日先支持竖屏单页切换与 `?layout=two/one` 地址参数控制（含首页重定向保留参数）；8 月 21 日改为由 `ResizeObserver` 监听 `.split` 容器实际尺寸自动判定，宽 > 高进双栏、高 > 宽进单栏，URL 参数仅作首次测量前兜底。
- 判定增加 ±10% 滞回缓冲与 200ms 稳定防抖，宽高接近时不再反复跳闪；无显式参数时默认单栏，避免打开时先闪双栏。
- 单栏模式改为顶部居中统一切换器“会话｜看板”（真实按钮 + aria 状态），移除面板标题栏独立切换按钮；双栏模式隐藏切换器，且会话/看板默认等宽（1fr/1fr），拖拽宽度仍可持久化覆盖。
- 双栏切回单栏保留用户上一次选择的会话/看板；左侧导航栏从“完全隐藏/仅图标/展开”两级折叠收敛为“折叠图标栏/展开完整栏”两态，移除完全隐藏。
- 单栏看板新增“分析 SOP / 任务清单”面板（默认展开），样式与会话完全一致（纯白背景、透明底绿色对勾等）；标题行按布局精简。
- 主要文件：`frontend/src/runtime.js`、`frontend/src/shell.html`、`frontend/src/workbench.css`、`frontend/src/main.jsx`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`、`bi_agent/web/static/index.html`。

### 3. 任务定位与双栏滚动联动

- 任务清单点击改为以 turn 为唯一语义锚点：会话定位 `.msg-user[data-turn]`，看板定位同一 turn 第一个可见结果卡片（排除隐藏问题卡），统一用各自滚动容器显式坐标，不再使用 `scrollIntoView`。
- 程序化任务导航期间暂停滚动联动，`scrollend` + 超时兜底结束，连续快速点击 last-click-wins；同步滚动增加来源标记，消除双向回弹。
- React 任务清单统一走 `bi-question-navigate` 事件入口，不再模拟 click 隐藏 DOM；历史会话恢复后任务点击仍有效。
- 主要文件：`frontend/src/runtime.js`、`frontend/src/main.jsx`、`bi_agent/web/static/vendor/antd/workbench.js`、`tests/test_regressions.py`。

### 4. 根因分析 → 行动建议 → 转督办全链路打通

- 根因分析完成后强制生成至少一条有效行动建议：后端新增结构化 SSE 事件 `action_recommendations`，主循环结束仍无行动时独立补写最多 2 次（只补文本、不重跑 SQL/图表），仍失败下发“交付不完整”；空泛建议与已完成声明被过滤，L1/L2 不强制。
- “行动 → 转督办”接入真实任务令接口：ChatBI 后端代理 `POST /api/task-alert/manual-create` 转发到 X360 服务，前端不再本地伪造任务号；`clientRequestId` 幂等防重、失败可重试，仅上游 `success=true` 才显示成功。
- `bpDefinitionId` 临时按行动内容关键词匹配业务定义（开票/回款/订单/合同/生产/发货/签收/验收/线索/项目/关闭/履约单），`assignee` 临时写死 400，功能开关保持开启。
- 主要文件：`bi_agent/web/session.py`、`bi_agent/tools/analysis_policy.py`、`bi_agent/web/app.py`、`frontend/src/runtime.js`、`tests/test_regressions.py`、`.env.example`。
- 验证：线上实测通过代理创建任务令返回真实 `taskId`。

### 5. 分析可靠性框架与 Claims 数据源隔离

- 只有真实数据查询（`SQLRun`/`MetricDataQuery`）进入查询结果与 Claims，图表/表格等展示工具不再污染“最新查询结果”或生成数据事实 Claim。
- reconciliation 只对同一指标且明确声明父/子值的查询配对，交错执行不再误配；关系工具仅在存在明确边/路径证据时生成 Association Claim，空结果/错误/降级/零边证据改为 `RELATION_MISSING` 披露。
- 叙述数字校验放宽正常表达（`100` 与 `100.0`、`0.25` 与 `25%`、序号、列表编号、范围、时间周期），虚构业务数字仍被阻止并要求重写。
- 主要文件：`bi_agent/reliability.py`、`bi_agent/web/session.py`、`bi_agent/tools/sql_tools.py`、`bi_agent/tools/chart_tools.py`、`bi_agent/tools/table_tools.py`、`tests/test_reliability.py`。

### 6. 模型与团队网关兼容

- 默认大模型切换为 `Qwen/Qwen3-80B-AWQ`（团队 API 网关），DeepSeek 保留为可选模型；模型选择列表将团队 API 全部模型置顶。
- 修复团队网关切 Qwen 后因错误携带 DeepSeek 专属 `thinking` 参数返回 400 的问题：thinking 参数按模型族路由，仅 DeepSeek 携带，Qwen/GLM/Kimi 及其他模型绝不携带；新增 `TEAM_DEEPSEEK_ENABLE_THINKING`/`TEAM_QWEN_ENABLE_THINKING`，旧 `TEAM_ENABLE_THINKING` 仅作 DeepSeek 兼容项。
- 网关返回 `UnsupportedParamsError ... ['thinking']` 400 时仅将当前请求以 thinking=false 重试一次，不重跑工具、不无限重试、不全局 `drop_params` 掩盖。
- 主要文件：`bi_agent/llm/provider_team.py`、`bi_agent/llm/registry.py`、`bi_agent/web/session.py`、`.env`、`tests/test_regressions.py`。

### 7. 交互细节与历史兼容修复

- 用户选择提交后立即显示绿色“已提交”状态，继续执行期间不再重复“思考中”。
- 发送按钮统一保持初始纸飞机 SVG（忙碌态只切 `is-busy` 类）；表格滚动条细化为 6px。
- “分享到飞书”统一改为“分享到钉钉”（文案、内部命名、占位提示），旧会话快照中的飞书按钮自动规范为钉钉按钮并可点击。
- 会话/看板标题居中，单栏模式会话面板铺满、侧栏展开按钮优化；历史会话恢复、图表元信息展示等旧行为保持兼容。
- 主要文件：`frontend/src/runtime.js`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`、`tests/test_regressions.py`。
