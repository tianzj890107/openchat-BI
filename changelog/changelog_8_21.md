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
- 影响范围：会话/看板中“行动建议”卡片的“转督办”操作。
- 主要文件：`bi_agent/web/app.py`（新增代理端点与幂等保护）、`frontend/src/runtime.js`（`dispatchSupervise` 重写，删除 `localTaskSeq`/ACK 伪成功逻辑）、`bi_agent/web/static/vendor/antd/workbench.js`（构建产物，缓存版本升至 v=150）、`bi_agent/web/static/index.html`、`.env.example`、`tests/test_regressions.py`（新增 `TaskAlertProxyTests` 14 项测试）。
