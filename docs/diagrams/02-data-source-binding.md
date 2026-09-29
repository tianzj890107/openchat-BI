# 图 2 · 数据源原子配对

> 智能分析 Agent 全链路流程图 · 第 2/9 张 —— 设置页 GET/PUT `/api/sources`、目录字段归一化、配对指纹比较与运行态重建。
> 基线 2026-09-20，仓库工作区当前代码；不含真实凭据、密钥或内部绝对路径。
> 返回 [图目录](README.md) ｜ 节点 → 代码位置见 [README §10](README.md#10-节点--代码位置索引)。

---

`bi_agent/web/app.py:1721` `get_sources_endpoint` / `:1869` `put_sources_endpoint`。

```mermaid
flowchart LR
    subgraph UI["设置页 / 会话页"]
        U1["GET /api/sources<br/>列出可选项"]
        U2["用户选「本体库」或「数据库」"]
        U3["PUT /api/sources"]
    end

    subgraph APP["Agent 进程"]
        A1["_remote_repository_catalog<br/>GET /api/v1/analysis/context/ontology-repository"]
        A2["_SOURCE_CONTEXT_FIELDS<br/>归一化字段"]
        A3["_source_binding_signature<br/>配对指纹"]
        A4{"指纹变化？"}
        A5["重建 executors / 会话运行态"]
        A6["沿用现有运行态"]
        A7["STATE.ontology_store = OntologyStore()<br/>生产模式空表（不落本体副本）"]
    end

    subgraph SVC["本体服务（MAL 网关）"]
        V1["dorisDatabase / currentDatabase"]
        V2["metaDatabase"]
        V3["knowledgeDatabase"]
        V4["namespaceCode"]
        V5["id / name / description"]
    end

    U1 --> A1 --> A2
    V1 --> A2
    V2 --> A2
    V3 --> A2
    V4 --> A2
    V5 --> A2
    A2 --> U1
    U2 --> U3 --> A3 --> A4
    A4 -->|是| A5 --> A7
    A4 -->|否| A6
```

关键约束：

- **原子配对**：改"本体库"或"数据库"任意一侧，都会同时改写另一侧；工具只有在下一次重新绑定后才生效。
- **本体内容不落本地**：生产模式 `STATE.ontology_store` 是空表，只用于满足旧接口类型；本体内容 100% 走 HTTP。
- **目录接口失败不阻塞设置页**：有 30s 冷却重试（`app.py:1748` 附近），恢复后无需重启进程。
