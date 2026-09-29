# 图 1 · 端到端总览

> 智能分析 Agent 全链路流程图 · 第 1/9 张 —— 数据源 → 会话 → 单轮策略 → 工具循环 → 交付与门禁的整体拓扑，含不依赖渲染器的 ASCII 兜底图。
> 基线 2026-09-20，仓库工作区当前代码；不含真实凭据、密钥或内部绝对路径。
> 返回 [图目录](README.md) ｜ 节点 → 代码位置见 [README §10](README.md#10-节点--代码位置索引)。

---

```mermaid
flowchart TD
    subgraph SRC["① 数据源（启动期 / 设置页）"]
        S1["环境变量<br/>ONTOLOGY_BASE_URL · DORIS_API_URL"]
        S2["GET /api/sources<br/>列本体库 + Doris 库 + 图库"]
        S3["原子配对<br/>repository ⇄ doris / meta / knowledge / namespace"]
        S4["PUT /api/sources<br/>比对 _source_binding_signature"]
        S5["build_source_executors<br/>重建工具注册表（16 个工具）"]
        S1 --> S2 --> S3 --> S4 --> S5
    end

    subgraph SES["② 会话（每个会话一个 WebSession）"]
        C1["create_session<br/>注入原子数据源上下文头"]
        C2{"RETRIEVAL_MODE"}
        C3["semantic 模式<br/>14 个基础工具"]
        C4["graph 模式<br/>基础工具 + GraphContext / GraphExpand"]
        C1 --> C2
        C2 -->|semantic| C3
        C2 -->|graph| C4
    end

    subgraph POL["③ 单轮决策（确定性 · 无 IO）"]
        P1["build_cognitive_policy_decision"]
        P2{"安全拒绝？"}
        P3{"对象/目标为空？"}
        P4{"无主语预测？"}
        P5{"L2 / 根因 / 行动 / 预测推演？"}
        P6{"元数据信号？"}
        P7{"事实信号？"}
        P8["GENERAL_RESPONSE"]
    end

    subgraph RUN["④ 工具循环（模型 + 工具运行时）"]
        R1{"refusal_category 非空？"}
        R2["_refusal_turn<br/>预置话术 · 不进模型循环 · 工具被封"]
        R3["_run_loop<br/>模型流式 + 工具调用"]
        R4["_execute_tool<br/>越权校验 → 限流 → 调用"]
        R5["工具：本体语义 / MetricQuery / FactQuery / 图表"]
    end

    subgraph OUT["⑤ 交付与门禁"]
        O1["回答合同校验<br/>schema / 证据 / 未支撑数字"]
        O2["真实性约束<br/>因果越界 · 代理披露 · 预测假设"]
        O3["会话落库 + 恢复快照"]
        O4["评测门禁<br/>smoke / adversarial / regression / release"]
    end

    S5 --> C1
    C3 --> P1
    C4 --> P1
    P1 --> P2
    P2 -->|是| R1
    P2 -->|否| P3
    P3 -->|是| P8
    P3 -->|否| P4
    P4 -->|是| P8
    P4 -->|否| P5
    P5 -->|是| R1
    P5 -->|否| P6
    P6 -->|是| R1
    P6 -->|否| P7
    P7 -->|是| R1
    P7 -->|否| P8
    P8 --> R1
    R1 -->|是| R2
    R1 -->|否| R3
    R3 --> R4
    R4 --> R5
    R5 --> R3
    R3 --> O1
    R2 --> O1
    O1 --> O2 --> O3 --> O4
```

### 1.1 无渲染器时的 ASCII 兜底

```text
        ┌────────────────────── ① 数据源（启动期 / 设置页） ──────────────────────┐
        │ 环境变量 → GET /api/sources → 本体库 ⇄ Doris/meta/knowledge/namespace  │
        │            → PUT /api/sources（签名变化才重建）→ build_source_executors │
        └───────────────────────────────────┬─────────────────────────────────────┘
                                            ▼
        ┌────────────────────── ② 会话（每会话一个 WebSession） ───────────────────┐
        │ 上下文头（repository_id / namespace / doris_database）                  │
        │ RETRIEVAL_MODE = semantic（14 工具） ┊ graph（+GraphContext/GraphExpand）│
        └───────────────────────────────────┬─────────────────────────────────────┘
                                            ▼
        ┌──────────── ③ 单轮决策 build_cognitive_policy_decision（无 IO）─────────┐
        │ 0 安全拒绝 → 1 空/泛问 → 1b 无主语预测 → 2 L2/根因/行动/预测推演        │
        │ → 3 元数据本体 → 4 事实查询 → 5 兜底 GENERAL_RESPONSE                   │
        └───────────────────────────────────┬─────────────────────────────────────┘
                                            ▼
        ┌────────────────────── ④ 工具循环（模型 + 工具运行时） ───────────────────┐
        │ refusal_category 非空 → _refusal_turn（不进模型循环 · 工具被封）        │
        │ 否则 _run_loop → _execute_tool（越权校验/限流）→ 工具 → 回灌模型        │
        └───────────────────────────────────┬─────────────────────────────────────┘
                                            ▼
        ┌──────────────────────── ⑤ 交付与门禁 ──────────────────────────────────┐
        │ 回答合同（schema/证据/未支撑数字）→ 真实性（因果/代理/预测假设）        │
        │ → 会话落库与恢复快照 → 评测门禁（smoke/adversarial/regression/release） │
        └────────────────────────────────────────────────────────────────────────┘
```
