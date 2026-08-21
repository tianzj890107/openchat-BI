# openchat-BI 变更记录（2026-08-21）

> 本文档只记录 2026-08-21 当天完成的最终变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、被回滚或未验证的事项不要写成已完成。

## 2026-08-21

今天的 changelog 已启用。后续今天完成的修改将持续同步到本文件，并按最终功能状态合并记录。

### 竖屏单栏左侧栏改为折叠/展开两态

- 竖屏单栏页面（`?layout=single`/`?columns=1`/`/one`、`/single`）的左侧导航栏不再完全隐藏，改为“折叠图标栏 / 展开完整栏”两种状态：折叠时保留 72px 图标栏，展开时显示完整标签；移除了完全隐藏状态及顶部的浮动展开按钮。
- 影响范围：竖屏单栏布局的左侧导航栏（智能分析/报表分析、内容、设置、最近会话等入口），双栏布局行为不变。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`。

### 默认大模型切换为 Qwen/Qwen3-80B-AWQ

- 默认大模型从 DeepSeek 改为 `Qwen/Qwen3-80B-AWQ`（团队 API 网关，UI 显示为“团队 API（环境配置） · Qwen/Qwen3-80B-AWQ”）；DeepSeek 系列仍保留为可选模型，可在模型参数中手动切换。
- 影响范围：所有新会话的默认模型选择，以及模型参数设置页的默认高亮。
- 主要文件：`bi_agent/llm/registry.py`、`.env`（本地部署配置，`TEAM_MODEL` 与 `TEAM_MODELS`）。

### 模型选择列表将团队 API 模型置顶

- 模型参数设置页的大语言模型下拉框中，团队 API 网关的全部模型（`Qwen/Qwen3-80B-AWQ`、`direct-deepseek-v4-flash`、`direct-deepseek-v4-pro`、`qwen3.7-plus`、`glm-5.1`、`kimi-k2.6`、`glm-5.2`、`glm-5-turbo`）调整到列表最上方，默认模型保持列表第一项；Claude、Qwen、DeepSeek 等其他模型保持原有顺序跟在后面。
- 影响范围：模型参数设置页的大语言模型下拉框。
- 主要文件：`bi_agent/llm/registry.py`（`list_models()` 排序）。

### 团队网关 thinking 参数按模型族路由（修复 Qwen 400）

- 修复：团队 API 网关（LiteLLM）切到 `Qwen/Qwen3-80B-AWQ` 后，只要设置过 `TEAM_ENABLE_THINKING`（无论 true/false）就会给所有模型发 DeepSeek 专属 `{"thinking":{"type":"enabled/disabled"}}` 参数，导致 Qwen 返回 `litellm.UnsupportedParamsError: openai does not support parameters: ['thinking']`（HTTP 400）。
- 现在按模型族路由：只有 DeepSeek 模型携带 thinking 参数；Qwen（含 qwen3.7-plus）、GLM、Kimi 及其他模型绝不携带 DeepSeek 风格 thinking。Qwen 仅在显式配置 `TEAM_QWEN_ENABLE_THINKING=true` 时才发送自己的 `enable_thinking` 参数。
- 环境变量拆分：新增 `TEAM_DEEPSEEK_ENABLE_THINKING`（DeepSeek 专属，当前部署为 true）、`TEAM_QWEN_ENABLE_THINKING`（默认空，不启用）；旧全局 `TEAM_ENABLE_THINKING` 仅作为 DeepSeek 的兼容项，不再影响任何其他模型。
- 错误恢复：当网关返回 `UnsupportedParamsError ... ['thinking']` 400 时，仅把当前 LLM 请求以 thinking=false 重试一次，不重跑工具调用、不从回合开头重来、不无限重试；其他错误原样返回。不使用 `litellm.drop_params=True` 掩盖。
- 影响范围：所有团队 API 模型请求（会话、看板、报表分析）。
- 主要文件：`bi_agent/llm/provider_team.py`、`bi_agent/web/session.py`、`tests/test_regressions.py`、`.env`（本地与服务器部署配置）。

### 竖屏单栏看板分析SOP/任务清单样式与会话对齐

- 修复：竖屏单栏模式下，看板里的“分析 SOP / 任务清单”面板背景不是纯白（看板窗底色为浅灰），且 SOP 步骤图标被 Ant Design 状态样式画成蓝/绿实心圆（进行中=蓝底、已完成=绿勾+绿底），与会话视图不一致。
- 现在看板与会话完全一致：面板纯白背景；完成步骤为透明底绿色对勾，进行中/待办为白底蓝/灰圆圈标记；蓝色数量标签保留。
- 影响范围：竖屏单栏布局的看板（`?layout=single`/`?columns=1`/`/one`/`/single`），双栏与聊天窗行为不变。
- 主要文件：`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`（构建产物，缓存版本升至 v=120）、`bi_agent/web/static/index.html`。

### 行动 → 转督办接入真实任务令接口

- “行动建议 → 转督办”从原来的“本地假任务号/父页面 ACK 伪成功”改为调用 ChatBI 后端代理 `POST /api/task-alert/manual-create`，由后端转发到真实任务令服务 `POST http://pdt-dev.eimos.com/api/x360/v1/task-alert/manual-create`，浏览器不再直接跨域调用。
- 请求体字段映射：`title`（来源 + 行动摘要前 40 字）、`content`（行动建议、分析来源、象限、回合、提交时间）、`assignee`、`level`、`bpDefinitionId`；前端只传 `title/content/clientRequestId`，`assignee` 临时写死为 `400`、`level=WARNING` 由后端默认，前端也可显式传入覆盖；`bpDefinitionId` 临时按行动内容关键词匹配（如“回款”→ `2081949636213985282`、“销售项目/投标”→ `2081949636117516289`、“开票/合同/订单/生产/发货/签收/验收/线索/项目/关闭/履约单”各有对应 ID），未命中则不传，前端显式传入优先。
- 状态流转：创建中（按钮禁用防重复提交）→ 创建成功（展示上游返回的真实 `taskId`）；创建失败显示真实错误（连接失败/超时/上游 HTTP 错误），可重试；只有外部接口真实返回成功才显示“任务令创建成功”。
- 防重复提交：前端提交中禁用该条“转督办”；每次请求生成 `clientRequestId`，后端对同一 `clientRequestId` 做进程内幂等（成功缓存、进行中互斥、失败不缓存允许重试）。
- 后端校验：`title`/`content` 非空、`level` 仅允许 `ALERT`/`WARNING`、`assignee` 缺失时用环境变量默认值；`bpDefinitionId` 可选但必须是数字（上游为 `java.lang.Long`），留空则不上传该字段；功能开关 `TASK_ALERT_API_ENABLED=true` 默认并保持开启，即使当前运维网络未打通也不自动关闭。
- 上游响应契约：上游即使业务失败也返回 HTTP 200（`{"success":false,"code":500,"message":...}`），因此代理按响应体 `success`/`code` 判定成功，只有 `success=true` 才返回 `ok=true`；任务号取 `data`（UUID 字符串）。线上实测通过代理创建任务令返回真实 `taskId`（如 `a4bf7909-...`）。
- 服务启动时启用应用日志（`logging.basicConfig(INFO)`），任务令创建、thinking 参数重试等非敏感审计日志现在会写入服务器日志文件。
- 影响范围：会话/看板中“行动建议”卡片的“转督办”操作。
- 主要文件：`bi_agent/web/app.py`（新增代理端点与幂等保护）、`frontend/src/runtime.js`（`dispatchSupervise` 重写，删除 `localTaskSeq`/ACK 伪成功逻辑）、`bi_agent/web/static/vendor/antd/workbench.js`（构建产物，缓存版本升至 v=150）、`bi_agent/web/static/index.html`、`.env.example`、`tests/test_regressions.py`（新增 `TaskAlertProxyTests` 14 项测试）。

### 根因分析后强制生成有效行动建议（结构化事件）

- 修复：根因分析完成后不能稳定生成带“行动”菜单的行动建议气泡的问题。现在只要本轮交付了根因章节，就必须至少有一条具体行动建议，并稳定展示“行动建议”气泡。
- 后端新增结构化 SSE 事件 `action_recommendations`（`turn` + `items`，每条含 `title/content/evidence`），根因回合在最终交付时由后端从行动章节解析并下发；前端收到后直接渲染 `dash-actions` 气泡，每条 item 单独显示并带“行动”菜单（转督办/转执行/转模拟/转风险分析），不再依赖模型输出固定标题。
- 强制补写改为独立修复阶段：主循环结束后（含恰好用满 `max_iterations` 的情况），只要检测到根因但无有效行动，就单独补写最多 2 次；补写只接受文本、绝不执行 SQL/图表/表格等工具；仍失败时下发 `delivery_incomplete` 事件并返回“交付不完整”，不再静默完成。
- 有效性校验不再只看标题：空话（“加强管理”“持续关注”“继续观察”等）、已完成声明（“已完成…”“已执行…”）、过短表述都会被过滤，只有含具体动作对象和执行方式且对应根因证据的建议才算有效；L1/L2 回合不强制生成建议。
- 标题变体兼容：`行动建议/管理建议/建议雏形/执行建议/决策建议/决策与建议/改进建议/处置建议/下一步行动/行动方案/建议` 均可触发行动气泡；结构化事件是新会话主路径，文本抽取仅兼容旧历史。
- 前端去重与恢复：同一 turn 同一行动不重复渲染（`actionsSeen` 去重，结构化事件会替换同 turn 文本卡片）；气泡与行动菜单随会话 HTML 持久化，刷新与历史恢复后仍存在。
- 兼容 Claim 校验阻断路径：`answer_blocked` 不再提前中断回合，改为正常收尾（行动门照常运行、`done` 事件照常下发），前端新增“最终回答被阻止”提示气泡，避免根因已展示但无行动气泡且界面卡在忙碌态。
- 影响范围：所有交付根因分析的会话（L3+），看板与聊天窗的行动建议卡片。
- 主要文件：`bi_agent/web/session.py`、`bi_agent/tools/analysis_policy.py`、`frontend/src/runtime.js`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`（构建产物，缓存版本升至 v=152）、`tests/test_regressions.py`。

### 工作区布局按容器尺寸自动切换单双栏，单栏顶部统一切换器

- 布局不再由 URL 的 `layout`/`columns` 参数或 `/single` 路由决定，改为用 `ResizeObserver` 监听会话与看板外层的 `.split` 容器实际尺寸：容器宽 > 高时显示双栏（会话/看板并排），宽 ≤ 高时自动切为单栏；首次测量前保留 URL 参数作为兼容兜底。
- 只在判断结果发生变化时更新 DOM（`data-layout`、`bi-viewport-mode` 事件、`resize` 事件触发图表重算），避免 ResizeObserver 循环和重复渲染；双栏切回单栏时保留用户上一次选择的会话/看板，无历史选择默认“会话”。
- 删除原来位于两个面板标题栏右上角的独立“会话/看板”按钮，改为单栏模式下在工作区顶部居中的统一切换器“会话｜看板”：两个真实 button + 纯分隔竖线，选中项蓝色、未选中灰色，点击立即切换面板；带 `role="tablist"`、`aria-selected`/`aria-pressed` 无障碍状态；双栏模式下隐藏，不影响看板清空、折叠、拖动调宽等既有功能。
- 影响范围：所有工作区页面（智能分析/报表分析），自适应横竖屏容器。
- 主要文件：`frontend/src/shell.html`、`frontend/src/runtime.js`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`（构建产物，缓存版本升至 v=121/v=153）、`bi_agent/web/static/index.html`、`tests/test_regressions.py`。

### “分享到飞书”改为“分享到钉钉”

- 所有用户可见文案、占位提示、注释与内部函数/样式命名从 Feishu/飞书统一改为 DingTalk/钉钉：按钮文案改为“分享到钉钉”，内部类 `dash-feishu-btn` → `dash-dingtalk-btn`、图标键 `feishu` → `dingtalk`、函数 `shareTurnReportToFeishu` → `shareTurnReportToDingTalk`。
- 点击后的提示改为：`「分享到钉钉」为占位入口,暂未接入钉钉开放平台`；仍是占位入口，不虚构或调用钉钉 API。
- 旧会话快照向后兼容：恢复历史会话时若快照仍含 `dash-feishu-btn`，`normalizeExportButtons` 会自动转换为新的 `dash-dingtalk-btn` 并改文案为“分享到钉钉”，按钮点击正常绑定，不会失效。
- 影响范围：会话/看板中“导出本轮报告”卡片上的分享按钮。
- 主要文件：`frontend/src/runtime.js`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`（构建产物）、`tests/test_regressions.py`。
