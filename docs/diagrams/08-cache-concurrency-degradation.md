# 图 8 · 缓存并发与降级

> 智能分析 Agent 全链路流程图 · 第 8/9 张 —— 本体缓存 TTL、三个进程级 limiter、准入控制、超时与各类降级路径。
> 基线 2026-09-20，仓库工作区当前代码；不含真实凭据、密钥或内部绝对路径。
> 返回 [图目录](README.md) ｜ 节点 → 代码位置见 [README §10](README.md#10-节点--代码位置索引)。

---

```mermaid
flowchart LR
    subgraph CACHE["缓存"]
        C1["本体对象 / 库目录 / 图邻域<br/>TTL = ONTOLOGY_CACHE_TTL_SECONDS（默认 30s）"]
        C2["5xx 失败短期缓存<br/>4xx 立即重试（指标级）"]
    end

    subgraph LIM["并发（进程级 limiter）"]
        L1["LLM：CHATBI_LLM_CONCURRENCY（默认 6）"]
        L2["Doris：CHATBI_DORIS_CONCURRENCY（默认 12）"]
        L3["本体：CHATBI_ONTOLOGY_CONCURRENCY（默认 12）"]
        L4["准入：active 8 / principal 2 / waiting 32<br/>等待 2.0s 后 429 PRINCIPAL_CONCURRENCY_LIMIT"]
    end

    subgraph DEG["超时与降级"]
        D1["本体 HTTP 超时 ONTOLOGY_TIMEOUT_SECONDS<br/>（默认 30s，钳制 1–120s）"]
        D2["Doris HTTP 超时 60s<br/>MySQL 连接 10s / 读 60s"]
        D3["本体新路径失败 → 旧路径兜底"]
        D4["通用边查询不可用 → 邻域降级"]
        D5["工具不可用 → CAPABILITY_LIMITATION（不虚报能力）"]
    end

    CACHE --> DEG
    LIM --> DEG
```

会话资源（`bi_agent/concurrency.py:123`）：空闲 TTL 7200s、内存会话上限 500。
