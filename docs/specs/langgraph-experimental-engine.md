# LangGraph 实验分析引擎 Spec

> 状态：**已实现（显式启用的实验旁路）**。目标是在不替换、不改写现有 `WebSession` 默认链路的前提下，
> 增加一个显式启用、可回退、可与旧引擎逐步比对的 LangGraph 控制面。

## 1. 目标与边界

- 旧引擎 `WebSession._run_loop()` 保持默认，现有 `/api/chat`、`/api/choice`、
  会话恢复和浏览器前端行为不得改变。
- LangGraph 只替换**单轮控制面**：迭代、模型调用、工具调用、AskUser 暂停、Claims
  校验、渲染补做、行动补写和最终交付仍复用生产 `WebSession` 的 helper。
- 模型调用、工具白名单、Tool Runtime、Recovery、数据源隔离、Claims/Evidence 校验
  一律复用旧实现，实验图不得建立第二套业务执行路径。
- 实验依赖使用独立 optional extra，默认启动和旧入口不得因缺少 LangGraph 而失败。
- 实验入口使用独立 session/source 注册表、独立 slot 命名空间，不写
  `dataset/conversations/`；历史会话与用户数据只读或完全不触碰。

## 2. 启用方式

实验默认关闭。满足任一条件才启用实验 HTTP 入口：

- `CHATBI_AGENT_ENGINE=langgraph`（兼容 `graph`、`lg`）；或
- `CHATBI_ENABLE_LANGGRAPH_EXPERIMENT=1`（兼容 `true`、`yes`、`on`）。

关闭时实验入口返回 404；旧入口仍正常使用 `WebSession`。即使实验开启，旧入口也不得
切换到 LangGraph。

安装实验依赖：

```bash
pip install -e '.[web,langgraph]'
```

## 3. HTTP 合同

### `POST /api/experimental/langgraph/chat`

请求体与 `/api/chat` 相同（`message`、`visible_user_text`、`session_id`）。响应为
SSE，事件类型、顺序和字段与旧引擎保持 parity；`turn_id`/`generation` 注解继续由
`_run_turn_stream` 统一添加。

### `POST /api/experimental/langgraph/choice`

请求体与 `/api/choice` 相同，只恢复实验注册表中的 AskUser 暂停会话。

## 4. 隔离合同

- Session 注册表：`STATE.experimental_sessions`，不得与 `STATE.sessions` 混用。
- Source 快照：`STATE.experimental_source_contexts`，不得与
  `STATE.source_contexts` 混用。
- Turn slot：`experimental-langgraph:<session_id>`，不得与 `data:<session_id>` 冲突。
- 端点自身不调用 ConversationStore；测试需断言实验一轮结束后历史目录内容不变。
- 同一个 `session_id` 可同时拥有旧会话和实验会话，消息、claims、query results
  不得互相串写。

## 5. 引擎 parity 合同

以下行为必须与旧引擎一致：

1. 直接回答的 SSE 事件类型顺序；
2. 工具轮次的事件、工具输入、tool result 和持久化消息；
3. `render_enforce` 与渲染工具补做；
4. Claims reject → 重新生成 → 最终仅提交通过校验的候选；
5. AskUser 暂停、sibling tool 顺序和 choice 恢复；
6. 工具 timeout/failure 的 Recovery 终态，以及显式 checkpoint retry；
7. 行动建议补写、forecast limitation/disclosure、最大迭代兜底；
8. golden-set recorded-provider 的工具链、SQL 输入、最终回答和事件序列。

测试只使用 fake provider/fake executor 或离线 recorded fixtures，不调用真实模型、
生产数据库或网络。

## 6. 实施批次与验收

| 批次 | 内容 | 验收 |
| --- | --- | --- |
| B0 | optional extra、factory、实验 HTTP 旁路 | 实验端点隔离测试通过；旧入口不变 |
| B1 | 主循环、工具、AskUser、Recovery | 引擎单测与工具边界回归通过 |
| B2 | Claims、渲染、行动、forecast、迭代兜底 | 与旧引擎逐事件 parity |
| B3 | recorded-provider golden set | 代表用例双引擎工具链和回答一致 |
| B4 | 文档、changelog、全量回归 | `unittest discover` 与 `git diff --check` 通过 |

每批红测先失败、实现后通过，再进入下一批。任一批出现 parity 差异必须先修复。

## 7. 实施结果（2026-10-21）

- `LangGraphWebSession` 仅覆盖 `_run_loop()`；session 消息、Claims、QueryResult、
  Tool Runtime ledger 和 Recovery 仍由生产 `WebSession` 持有。
- 实验端点 `/api/experimental/langgraph/chat`、`/api/experimental/langgraph/choice`
  已接入独立 session/source 注册表和 `experimental-langgraph:` slot。
- recorded-provider 支持 `session_cls` 注入；评测 CLI 新增
  `--engine legacy|langgraph`，默认仍为 `legacy`。
- 同一 runner 全量重放 `recorded-provider`：两引擎均为 122/122 通过，
  34/34 P0 通过；指标值与样本统计完全一致。
- 专项 parity 覆盖直接回答、工具轮次、Claims、渲染补做、行动建议、AskUser sibling、
  timeout/retry、forecast 限制/披露和最大迭代兜底。
- 全量 `unittest discover` 的 3 个失败已用同 commit 的干净 worktree 复现为既有环境问题：
  2 个本地 tag 集合断言、1 个 repeat-stability 顺序 flake，均与 LangGraph 改动无关。

## 8. 非目标

- 不接入 Deep Agents；
- 不把 LangGraph 设为默认引擎；
- 不修改前端默认请求地址；
- 不创建 tag、Release、Merge Request 或部署；
- 不删除、迁移、覆盖历史会话和用户数据。
