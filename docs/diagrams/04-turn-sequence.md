# 图 4 · 单轮时序

> 智能分析 Agent 全链路流程图 · 第 4/9 张 —— 用户 / API / WebSession / analysis_policy / LLM / tool_runtime / 本体 MAL / Doris 的完整交互时序。
> 基线 2026-09-20，仓库工作区当前代码；不含真实凭据、密钥或内部绝对路径。
> 返回 [图目录](README.md) ｜ 节点 → 代码位置见 [README §10](README.md#10-节点--代码位置索引)。

---

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户 / 浏览器
    participant API as FastAPI<br/>POST /api/chat
    participant S as WebSession
    participant P as analysis_policy
    participant L as LLM Provider
    participant T as tool_runtime
    participant O as 本体 MAL 网关
    participant D as Doris 查询网关

    U->>API: 提问（含会话 id）
    API->>S: generate_turn(user_text)
    S->>P: build_cognitive_policy_decision(question, allowed_tools)
    P-->>S: mode / reason_code / required_tools / refusal_category

    alt refusal_category 非空（安全拒绝）
        S->>S: _refusal_turn：置 _refusal_tool_block = true
        S-->>U: 预置免密拒绝话术（不启动模型循环、不暴露任何工具）
    else 正常轮次
        S->>S: 拼装 system prompt（六步 SOP + 上下文头 + 图库 SOP）
        loop 最多 max_iterations 轮
            S->>L: 流式请求（工具白名单 ⊆ 会话 allowed_tools）
            L-->>S: 文本 / 工具调用
            opt 有工具调用
                S->>T: _execute_tool(name, args)
                T->>T: 越权校验 → 限流（llm/doris/ontology）→ 取消检查
                alt 本体类工具
                    T->>O: 新 /api/v1/analysis/** 优先，旧 /agent/** 兜底
                    O-->>T: 结构化结果（失败按 4xx/5xx 分别降级）
                else 事实类工具
                    T->>D: 只读 SQL / 指标数据查询
                    D-->>T: 行集（HTTP 超时 60s）
                end
                T-->>S: 工具输出（截断 + 摘要）
            end
        end
        S->>S: 回答合同校验 + 真实性约束
        S-->>U: 流式回答（结论 / 证据 / 行动 分段）+ 会话落库
    end
```
