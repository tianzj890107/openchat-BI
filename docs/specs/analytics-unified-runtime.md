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

MCP 委托完整分析与 Web 入口应共用任务生命周期；需要实现明确的创建、状态、取消和产物契约。当前 MCP 协议会话不等于 Agent 执行任务，不能以改名替代任务实现。

## 迁移边界

Cockpit 的证据冻结、刷新调度、缓存、交付校验及发布保留在业务层。standalone 路线须在调用方与行为验收后退役。部署及旧实例停用单独进行。
