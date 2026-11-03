# Workbench 全页 Pro UI 组件化

- 日期：2026-11-02（初版），2026-11-03（扩展为全页）
- 状态：已完成（可见工作台全页）
- 范围：分析 Agent 的 `/workbench` 前端
- 分支：`feature/workbench-pro-ui-chat`

## 1. 背景

Pro UI 的 Agent Conversation Template 提供了会话、消息、Activity、ToolCall、
Sender、导航与右侧面板插槽。文档源码中的 React 包名为 `@pro-ui/x-react` 和
`@pro-ui/chat-runtime`。

文档 `guide/quickstart` 中的 npm 安装命令对应 Vue 3 / Element Plus 包：

```bash
npm install @pro-ui/core
```

React 文档只给出 `@pro-ui/x-react`、`@pro-ui/chat-runtime` 的 import 路径和
GitLab 仓库链接，没有发布可直接安装的 npm 包。当前已核验：

- `npm view @pro-ui/x-react` 返回 404；
- `registry.npmmirror.com` 返回 `NOT_FOUND`；
- 本机配置的 GitLab npm registry 对该作用域返回 302 到公共 npm，随后 404；
- 文档源码给出的 `gitlab.boulderaitech.com/frontend/pro-ui` 当前账号访问为 404。

因此本轮不能把不存在的依赖写入 `package.json`。可见界面使用仓库已安装的
Ant Design X 1.6.1、Ant Design 5.29.3 和 React 18.3.1，按 Pro UI Agent
模板的 sage 主题、组件语义和交互层级实现。后端和 `runtime.js` 的业务状态机
保持不变。

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
- 不在依赖不可获取时伪造 `@pro-ui/x-react` 安装结果或提交不可构建的 lockfile。

## 4. 可见界面与实现映射

| 区域 | 组件 | 说明 |
|---|---|---|
| 左侧导航 | `ProUiSidebar.jsx` + Ant Design X `Conversations` | 业务导航、模式切换、最近会话、账号菜单 |
| 空会话 | `ProUiWelcome.jsx` + `Welcome` / `Prompts` | 标题、说明、建议问题和填充输入框 |
| 消息正文 | Ant Design X `Bubble` | 用户/助手气泡、Markdown、助手头像 |
| 工具与 SOP | Ant Design X `ThoughtChain` + `ProUiAgentStatus.jsx` | 执行步骤、SOP 进度、活动状态和停止操作 |
| 输入区 | `ProUiComposer.jsx` + `Sender` | 发送、停止、报表上传、数据库开关和附件状态 |
| 业务结果 | Ant Design `Card` / `Collapse` / `Tag` | 图表、表格、多维图、看板和结论卡 |
| 设置页面 | Pro UI sage token + Ant Design 组件样式 | 数据源、本体适配、模型、角色、记忆和账号页 |

设置页的业务动作仍由 `runtime.js` 处理；React 壳通过隐藏的运行时桥接节点同步
输入、选项、状态和按钮点击，避免复制数据源、模型参数和回收站的业务逻辑。

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
- `frontend/src/ProUiComposer.jsx`：Ant Design X Sender 和报表工具条；
- `frontend/src/ProUiWelcome.jsx`：Welcome 与 Prompts 空状态；
- `frontend/src/proUiBridge.js`：输入、欢迎提示和导航高亮的纯适配器；
- `frontend/tests/proUiBridge.test.mjs`：适配器回归测试。

### 7.2 调整

- `frontend/src/main.jsx`：挂载 Pro UI 侧栏、欢迎页、输入区和状态条；将助手消息
  放入 Bubble 头像布局；为静态壳增加全页主题 class；
- `frontend/src/runtime.js`：导航切换事件、输入预填、侧栏默认展开、滚动回调修复；
- `frontend/src/shell.html`：欢迎页/输入框挂载点、页面标题图标；
- `frontend/src/workbench.css`：Pro UI sage 全页主题、侧栏、气泡、输入、设置页、
  看板与响应式样式；
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
- 报表模式显示上传报表、数据库查询和最近报表工具条；旧附件行不重复显示；
- Sender 输入与隐藏的 `#chat-input` 双向同步，输入后发送按钮可用；
- 1440 宽度下工作区无 JS 异常，所有静态资源返回 200；
- 页面退出、保存或取消返回工作区后，侧栏高亮跟随 runtime 当前视图。

### 8.3 已验证结果

- `node --test frontend/tests/proUiBridge.test.mjs`：5 项通过；
- `node --test frontend/tests/*.test.mjs`：98 项通过；
- `npm run build`：通过，构建产物已同步；
- `python -m unittest tests.test_regressions`：221 项通过；
- CDP 浏览器检查：九条导航路由、展开侧栏、数据源/模型参数页面和 Sender 可用；
- CDP 捕获：无 JavaScript 异常，无业务资源 404；favicon 404 已修复；
- 历史清空/恢复路径不会删除 Pro UI 欢迎页和空状态节点；
- `git diff --check`：通过。

## 9. 后续阶段

1. 在 `@pro-ui/x-react` 可获得后，用真实 ProX 组件替换当前 Ant Design X 实现，
   并保留 `proUiBridge.js` 的纯适配边界；
2. 将新会话消息保存为结构化消息，同时继续只读兼容旧 HTML 快照；
3. 将设置页的每个原生控件迁移为受控 Pro UI 表单组件，删除隐藏运行时桥接；
4. 增加浏览器级 SSE 回放、停止、历史恢复和子路径验收。
