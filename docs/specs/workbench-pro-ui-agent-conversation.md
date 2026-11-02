# Workbench Pro UI 对话层改造

- 日期：2026-11-02
- 状态：已完成（对话层增量，2026-11-02）
- 范围：分析 Agent 的 `/workbench` 对话前端
- 分支：`feature/workbench-pro-ui-chat`

## 1. 背景

Pro UI 的 Agent Conversation Template 提供了 Pro UI 风格的会话、消息、
Activity、ToolCall、Sender 与右侧面板插槽，但模板本身依赖文档站的服务端
适配器，不能直接替换 Analytics 的请求、SSE、会话恢复和业务卡片协议。

本仓库当前 Workbench 已使用 React + Ant Design X 渲染消息与 ThoughtChain，
但仍由 `runtime.js` 直接操作聊天 DOM。直接整页替换会同时改变后端接口、
历史快照和图表交付，风险过高。

本轮只迁移对话层的状态表达和输入状态，保留以下既有契约：

- `/api/chat`、`/api/report/chat` 及全部 SSE 事件；
- 服务端会话、历史快照、恢复与保存接口；
- 图表、表格、多维图、本体实体和看板；
- 设置页、数据源页、系统日志和驾驶舱。

## 2. 目标

1. 增加 Analytics 专用事件适配器，把现有 SSE 事件转换为稳定的对话活动状态。
2. 工具执行从“结果到达后才出现”改为“开始即显示、同 ID 更新、完成后保留详情”。
3. 明确展示思考、工具执行、等待用户选择、完成、失败、会话重建和中断，
   不把等待选择或断流显示成成功。
4. 发送按钮在生成中变为“停止”，停止后保留已输出内容，不保存为完成回答。
5. 保持旧历史快照可打开；历史文件和用户数据不做迁移、清空或重写。
6. 使用 Pro UI 的语义层级和视觉 token，但不引入不可访问的私有 npm 依赖。

## 3. 非目标

- 不重写后端 `AgentSession`、SSE 协议或模型服务。
- 不批量改写旧历史 HTML、图表或报告。
- 不开放消息编辑、重新生成和消息分支；这些语义需要后端任务边界。
- 不迁移设置页和数据源页；它们仍使用现有 React/Ant Design 实现。
- 不删除演示站依赖的浏览器线程；Analytics 以服务端会话为准。

## 4. Analytics 事件映射

| Analytics 事件 | 对话活动状态 | 展示要求 |
|---|---|---|
| `text_delta` | 追加当前回答正文 | 不创建重复消息 |
| `thinking_delta` | `reasoning` 活动 | 只展示后端真实提供的思考，不补造 |
| `tool_start` | 工具 `running` | 立即出现执行行 |
| `tool_input` | 同 ID 工具参数 | 更新同一条，不新增 |
| `tool_result` | 同 ID 工具 `complete` | 补结果、耗时、图表/表格和本体实体 |
| `sop_progress` | SOP 当前步骤 | 只更新业务进度，不冒充模型思考 |
| `user_choice_requested` | `awaiting_choice` | 停止“执行中”，显示澄清卡片 |
| `awaiting_user_choice` | `awaiting_choice` | 保持等待状态 |
| `user_choice_resolved` | 恢复 `running` | 标记已选择，继续当前轮次 |
| `done` | `completed` | 只有无未决选择时才允许成功 |
| `error` | `failed` | 保留部分正文和工具记录 |
| `session_superseded` | `superseded` | 明确会话重建，不显示成功 |
| `stream_interrupted` | `interrupted` | 明确内容可能不完整 |

## 5. 状态与并发约束

- 每个工具调用使用后端 `id` 作为唯一键；重复 `tool_result` 不得新增第二条活动。
- 每个模式维护独立的活动状态；切换模式不能串流。
- 事件带 `turn_id` 时，晚到的旧 turn 事件必须被忽略。
- `done`、`error`、`session_superseded`、`stream_interrupted` 的终态幂等。
- 已失败、已中断或已重建的 turn 不能被晚到的 `done` 翻转为成功。
- 停止生成只中断当前请求，保留已显示正文；不得触发完成保存、导出或 SOP 收口。

## 6. 组件边界

### 6.1 本轮新增

- `frontend/src/agentActivityModel.js`：纯事件适配器与状态选择器；
- `frontend/src/ProUiAgentStatus.jsx`：Pro UI 风格的活动状态条和停止操作；
- `frontend/tests/agentActivityModel.test.mjs`：适配器红测/回归测试。

### 6.2 本轮调整

- `frontend/src/runtime.js`：发布活动状态、渲染运行中工具、处理停止、切换模式、
  409/429 请求失败、选择提交和显式中断；
- `frontend/src/main.jsx`：挂载状态条；
- `frontend/src/shell.html`：增加状态条挂载点；
- `frontend/src/workbench.css`：Pro UI 状态条和运行中工具样式。

### 6.3 保留

- 现有 `.step`、ThoughtChain、Bubble、聊天 HTML 快照格式；
- 现有聊天输入 DOM 与 `#chat-input`、`#btn-send` 绑定；
- 现有会话恢复、看板和业务卡片代码。

## 7. 验收

### 7.1 自动测试

```bash
node --test frontend/tests/agentActivityModel.test.mjs
node --test frontend/tests/*.test.mjs
cd frontend && npm run build
python -m unittest tests.test_regressions
git diff --check
```

### 7.2 行为验收

- `tool_start` 后立即出现运行中工具，`tool_result` 到达后原位置完成；
- 同一工具 ID 只有一个执行项；
- 等待用户选择时状态条显示“等待选择”，不显示完成；
- 停止后保留正文、工具和图表，状态为停止，后续晚到 `done` 不翻转；
- 失败、会话重建、断流均不触发完成保存/导出；
- 旧历史仍可打开，历史 HTML 不做批量改写；
- 窄屏下状态条和输入区无横向溢出。

### 7.3 本轮验证结果

- 前端 Node 测试 92 项通过（其中活动适配器 11 项）；
- `npm run build` 通过，静态产物已同步到 `bi_agent/web/static/vendor/antd/`；
- `python -m unittest tests.test_regressions` 221 项通过；
- 本地浏览器确认 Workbench 可加载，运行中工具和用户停止状态条显示正确；
- `git diff --check` 通过。

## 8. 后续阶段

1. 将聊天正文和输入框完全迁移到受控 React 消息树；
2. 用结构化消息替换新会话的 HTML 快照，同时保留旧快照只读兼容；
3. 将设置、数据源和结果面板逐步换成 Pro UI 基础组件；
4. 增加浏览器级 SSE 回放与历史恢复验收。

后续阶段需要单独设计和授权，不在本轮实现范围内。
