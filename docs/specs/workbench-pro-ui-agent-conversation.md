# Workbench 全页 Pro UI 组件化

- 日期：2026-11-02（初版），2026-11-03（真实 Pro UI 组件接入、页面级控件统一）
- 状态：已完成（导航、历史、欢迎、消息、工具/SOP、输入、状态层和页面级表单控件）
- 范围：分析 Agent 的 `/workbench` 前端
- 分支：`feature/workbench-pro-ui-chat`

## 1. 背景

Pro UI 的 Agent Conversation Template 提供基于 assistant-ui 的会话展示能力：
ProX Sidebar、Conversations、Welcome、Bubble、Sender、ExecutionSteps、
ThreadStatus 等。内部 npm `http://npm.boulderaitech.com/` 已发布
`@pro-ui/x-react`，可用版本为 `0.1.0`、`0.1.1`、`0.1.2`，当前固定 `0.1.2`。
该版本 peer dependency 支持 React 18.2+，仓库使用 React 18.3.1。

`@pro-ui/chat-runtime` 未在内部 registry 发布；本工作台不依赖该包的浏览器线程
持久化，而是继续由 Analytics 的 `runtime.js` 管理请求、SSE、会话历史和业务
状态。Pro UI 只负责可见组件与交互呈现。

安装使用内部 registry。`@assistant-ui/core@0.2.10` 与 npm 默认解析的新版 store/tap
存在构建冲突，因此 `frontend/package.json` 固定：

```json
"overrides": {
  "@assistant-ui/store": "0.2.13",
  "@assistant-ui/tap": "0.5.16"
}
```

构建已使用真实 `@pro-ui/x-react/styles.css` 和 ProX 组件，不再以 Ant Design X
模拟 Pro UI 外观。

内部 npm 的 React 原生页面能力集中在 `@pro-ui/x-react@0.1.2`；`@pro-ui/core` 和
`@pro-ui/bi` 的页面、表单与 BI 组件是 Vue 3 / Element Plus 实现，不能直接嵌入本
React 应用。因此页面表单层使用 `ProXConfigProvider` 的 Pro UI token + Ant Design
控件，业务结果中的图表 canvas、表格、本体图和证据卡片继续由现有业务实现。

## 2. 目标

1. 导航、历史会话、空会话引导、消息气泡、输入框、分析状态和设置页外观统一为
   Pro UI 风格，而不是只替换状态条。
2. 使用 React 组件承载可见界面，移除用户可见的旧 DOM 拼接内容。
3. 保留 `/api/chat`、`/api/report/chat`、全部 SSE 事件、服务端会话、历史恢复、
   图表、表格、多维图、本体实体和业务动作。
4. 旧历史 HTML 快照继续可读；不迁移、不清空、不重写用户历史。
5. 生成中发送按钮变为停止；停止、失败、会话重建和等待选择都不显示为成功。
6. 维持网关子路径、窄屏和单列/双列工作区布局。

## 3. 非目标

- 不重写后端 `AgentSession`、SSE 协议、模型服务或 MCP 架构。
- 不批量改写旧历史 HTML、图表或报告。
- 不开放消息编辑、重新生成和消息分支；这些语义需要后端任务边界。
- 不把 Pro UI 演示站的浏览器临时线程和页面退出清理逻辑引入业务工作台。
- 不让 assistant-ui 前端会话状态成为历史事实来源；服务端会话和旧 HTML 快照仍为准。

## 4. 可见界面与实现映射

| 区域 | 组件 | 说明 |
|---|---|---|
| 左侧导航 | `ProUiSidebar.jsx` + ProX `SidebarNav` / `Conversations` / `UserMenu` | 业务导航、模式切换、最近会话、账号菜单 |
| 空会话 | `ProUiWelcome.jsx` + ProX `Welcome` / `Prompts` | 标题、说明、建议问题和填充输入框 |
| 消息正文 | ProX `Bubble` | 用户/助手气泡、Markdown、助手头像；旧历史快照重挂载为 ProX |
| 工具与 SOP | ProX `ExecutionSteps` + `ProUiAgentStatus.jsx` + ProX `ThreadStatus` | 执行步骤、SOP 进度、活动状态和停止操作 |
| 输入区 | `ProUiComposer.jsx` + ProX `Sender` | 发送、停止、报表上传、数据库开关和附件状态 |
| 业务结果 | ProX `ToolResultCard` + 业务 renderer | 图表、表格、多维图、看板和结论卡使用统一结果外壳，内部保留业务渲染 |
| 设置页面 | `ProUiPageControls.jsx` + Pro UI token + Ant Design | 数据源、本体适配、模型、角色、记忆和账号页的按钮、输入、选择、开关、滑块、步骤条和提示块 |

设置页的业务动作仍由 `runtime.js` 处理；React 壳通过隐藏的运行时桥接节点同步
输入、选项、状态和按钮点击，避免复制数据源、模型参数和回收站的业务逻辑。

### 4.1 页面级组件清单

`@pro-ui/x-react@0.1.2` 直接提供并已使用的 React 组件：

`SidebarLayout`、`SidebarNav`、`Conversations`、`UserMenu`、`SearchDialog`、
`Sender`、`Attachments`、`Bubble`、`Activity`、`ExecutionSteps`、`ToolCall`、
`ToolResultCard`、`Prompts`、`Welcome`、`ThreadStatus`、`Button`、
`ConfigProvider`。

通过 `ProXConfigProvider` 的 Pro UI token 统一、并由 `ProUiPageControls.jsx`
桥接的 Ant Design 页面控件：

输入框、密码框、数字框、多行文本、Select、Checkbox、Radio、Switch、Slider、
Steps、Alert、Divider、Tabs、Segmented、可勾选 Tag 筛选、Modal、Table、
Tooltip、Dropdown 和 Portal。

仍是业务实现、没有伪称为 Pro UI 组件的部分：

- SSE、turn 生命周期、请求取消、历史恢复和旧 HTML 快照兼容；
- 分析 SOP 状态机、工具执行事件、证据和业务结果数据；
- ECharts canvas 图表、业务表格、本体关系图和导出/报告内容。

## 5. Analytics 事件映射

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

## 6. 状态与并发约束

- 每个工具调用使用后端 `id` 作为唯一键；重复 `tool_result` 不得新增第二条活动。
- 每个模式维护独立的活动状态；切换模式不能串流。
- 事件带 `turn_id` 时，晚到的旧 turn 事件必须被忽略。
- `done`、`error`、`session_superseded`、`stream_interrupted` 的终态幂等。
- 已失败、已中断或已重建的 turn 不能被晚到的 `done` 翻转为成功。
- 停止生成只中断当前请求，保留已显示正文；不得触发完成保存、导出或 SOP 收口。
- 导航高亮以 runtime 的 `bi-view-changed` 和 `bi-mode-changed` 为准；页面内
  “返回/保存后回工作区”也必须同步侧栏。

## 7. 组件边界

### 7.1 新增

- `frontend/src/ProUiSidebar.jsx`：Pro UI 风格导航、会话历史与账号区；
- `frontend/src/ProUiComposer.jsx`：ProX Sender 和报表工具条；
- `frontend/src/ProUiPageControls.jsx`：页面级控件的 Pro UI/AntD 桥接层；
- `frontend/src/ProUiWelcome.jsx`：ProX Welcome 与 Prompts 空状态；
- `frontend/src/proUiTheme.js`：ProXConfigProvider 的统一主题 token，以及 Button、
  Input、InputNumber、Select、Checkbox、Radio、Switch、Slider、Steps、Alert、
  Divider、Modal、Table、Tabs、Segmented、Card、Tooltip、Dropdown、Form token；
- `frontend/src/proUiBridge.js`：输入、欢迎提示和导航高亮的纯适配器；
- `frontend/tests/proUiBridge.test.mjs`：适配器回归测试；
- `frontend/tests/proUiTheme.test.mjs`：主题与页面控件 token 回归测试。

### 7.2 调整

- `frontend/src/main.jsx`：挂载 ProX 侧栏、欢迎页、输入区、状态和 ExecutionSteps；
  消息使用 ProX Bubble；结果卡使用 ProX ToolResultCard；页面控件挂载
  `mountProUiPageControls`；旧历史中的 Ant Bubble/ThoughtChain 快照在恢复时原位替换；
- `frontend/src/runtime.js`：导航切换事件、输入预填、侧栏默认展开、滚动回调修复；
- `frontend/src/shell.html`：欢迎页/输入框挂载点、页面标题图标；
- `frontend/src/workbench.css`：Pro UI sage 全页主题、ProX 组件适配、侧栏、气泡、
  输入、设置页、看板与响应式样式；输入/Select 的 hover、focus、选中态；
- `frontend/package.json` / `package-lock.json`：接入 `@pro-ui/x-react@0.1.2`，
  移除 `@ant-design/x`，固定 assistant-ui store/tap 兼容版本；
- `bi_agent/web/static/index.html`：默认展开、favicon、静态资源缓存版本；
- `bi_agent/web/static/vendor/antd/`：前端构建产物同步。

### 7.3 保留

- 现有 SSE 事件、会话恢复、看板和业务卡片代码；
- 旧历史 HTML 快照格式及其只读兼容；
- 设置页的数据源、模型参数、角色和回收站业务接口；
- 聊天输入 DOM 的 `#chat-input`、`#btn-send` 运行时绑定，由 React 输入框同步。

## 8. 验收

### 8.1 自动测试

```bash
node --test frontend/tests/proUiBridge.test.mjs
node --test frontend/tests/*.test.mjs
cd frontend && npm run build
python -m unittest tests.test_regressions
git diff --check
```

### 8.2 浏览器验收

- 1440×1000 下侧栏默认展开，导航文字、历史会话和账号区可见；
- 智能分析、报表分析、本体内容、系统调用记录、本体适配、数据源、模型参数、
  角色选择、记忆管理九条路由都能切换到可见页面；
- 会话/看板切换为 Segmented，本体类型筛选为可勾选 Tag，系统调用记录为 Tabs；
- 模型参数页的 Select、输入、数字框、滑块和开关全部由 Pro UI token 下的
  Ant Design 控件呈现，原 HTML 控件只作为隐藏运行时锚点；
- 报表向导步骤条、提示块、单选/复选和自定义规则 TextArea 使用统一控件，隐藏
  面板中的锚点不会留下空壳控件；
- 输入框和 Select 的 hover/focus 有可见的 sage 边框或外圈；Select 的焦点外圈
  单独由包装元素承载，避免 rc-select 内部 selector 的样式丢失；
- 报表模式显示上传报表、数据库查询和最近报表工具条；旧附件行不重复显示；
- Sender 输入与隐藏的 `#chat-input` 双向同步，输入后发送按钮可用；
- 1440 宽度下工作区无 JS 异常，所有静态资源返回 200；
- 页面退出、保存或取消返回工作区后，侧栏高亮跟随 runtime 当前视图。

### 8.3 已验证结果

- `node --test frontend/tests/proUiBridge.test.mjs`：6 项通过；
- `node --test frontend/tests/*.test.mjs`：100 项通过；
- `npm run build`：通过，构建产物已同步；
- `python -m unittest tests.test_regressions`：222 项通过；
- CDP 浏览器检查：九条导航路由、展开/收起侧栏、数据源页面和 Sender 可用；
- 历史会话恢复：6 条消息均为 ProX Bubble，旧 `.ant-bubble` 和旧 ThoughtChain 为 0；
- ProX 执行步骤无旧轨道线重复；页面无横向溢出；输入后发送启用、清空后禁用；
- 页面级控件浏览器检查：Segmented 1 个、Select 1 个、输入 3 个、数字框 1 个、
  滑块 1 个、开关 1 个；报表向导 TextArea、4 个 Radio 和 25 个 Checkbox 正常；
- 截图像素对比：Select 悬浮前后 980 个像素发生变化，外圈颜色为 Pro UI
  `rgb(170, 197, 181)`；输入框 hover 与 focus ring 均可见；
- CDP 捕获：无 JavaScript 异常，无业务资源 404；favicon 404 已修复；
- 历史清空/恢复路径不会删除 Pro UI 欢迎页和空状态节点；
- `git diff --check`：通过。

## 9. 后续阶段

1. 在保持现有页面路由和业务接口不变的前提下，逐步把隐藏运行时锚点改为结构化
   React 表单状态；当前桥接层先保证行为、历史和数据口径不被改写；
2. 将分析结果 Card、表格和图表逐步替换为 Pro UI/BI 组件适配层；
3. 将新会话消息保存为结构化消息，同时继续只读兼容旧 HTML 快照；
4. 增加浏览器级 SSE 回放、停止、历史恢复和子路径验收。
