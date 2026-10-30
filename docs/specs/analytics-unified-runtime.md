# Analytics 统一运行时与入口收敛

## 范围

Analytics 单仓库统一承载工作台、Cockpit、Process360 和 MCP；本体建模、表达式、映射不纳入本运行时。LangGraph 实验分支暂不引入。

## 第一阶段验收

- 工作台与 Cockpit main 路线使用 `bi_agent.runtime.session.AgentSession` 的同一执行实现，任务上下文、工具及证据分别隔离。
- 运行时模块不依赖 FastAPI、Web 应用 STATE 或 HTTP Request。
- `bi_agent.web.session` 保留为同一模块的兼容入口，旧调用和 provider patch 不产生两份实现。
- 通用分析和 Process360 MCP profile 保持工具隔离；MCP 基础工具不启动模型循环。
- 保留会话、产物与原工作区，不自动启停服务或部署。

## 后续任务接口

MCP 委托完整分析与 Web 入口应共用任务生命周期；通过独立工具提供提交、状态、取消与产物事件契约。MCP 协议会话与 Agent 执行任务分别管理；任务入口已在第二阶段实现。

## 迁移边界

Cockpit 的证据冻结、刷新调度、缓存、交付校验及发布保留在业务层。standalone 路线须在调用方与行为验收后退役。部署及旧实例停用单独进行。

## 委托分析任务验收（第二阶段）

- 新增 `/api/mcp/tasks`，只提供 AnalysisTaskSubmit/Get/Cancel，不改变现有基础工具清单。
- 任务调用复用工作台的数据源装配、AgentSession 和全局 admission/turn scope，使用独立 session key。
- 有界排队；持久化任务状态和分页事件；状态包括 queued/running/completed/failed/needs_input/cancelling/cancelled/interrupted。
- 每任务随机 capability token，查询和取消必须验证；不接受调用方指定工作台 session、身份或数据源。
- 取消不删除数据；重启不自动重放未知外部作用的任务，标记 interrupted。
- 此版本单进程任务所有者；不允许多个实例共享同一个任务数据库。
- 不自动派发风险或待办；需要用户交互时交付 needs_input，不自动替用户回答。
- 不重启或停用现有任何服务；standalone 在完成真实环境对照验收前保留。

## 本轮验收边界

本轮使用离线 provider 回放与 FastAPI 内存请求进行验收，不监听新端口、不调用线上删除接口。
验证委托任务通过真实 AgentSession 产生路由与澄清事件，浏览器既有会话保持原样；
校验未授权工具拦截、MCP 鉴权、容量限制、排队取消、分页、重启中断及存储单所有者。
`limited` 表示交付门禁返回受限结果，`max_tokens` 等非完成终态不算成功。
这些验证不等于 PDT/demo2 的真实模型和业务数据验收，后者必须在切换或退役前单独完成。
