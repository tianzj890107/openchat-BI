# 图 5 · 工具与端点映射

> 智能分析 Agent 全链路流程图 · 第 5/9 张 —— 16 个模型可见工具、新旧双栈路径、以及 MetricQuery 优先 / FactQuery 兜底的取数规则。
> 基线 2026-09-20，仓库工作区当前代码；不含真实凭据、密钥或内部绝对路径。
> 返回 [图目录](README.md) ｜ 节点 → 代码位置见 [README §10](README.md#10-节点--代码位置索引)。

---

工具注册：`bi_agent/tools/__init__.py:48` `build_source_executors`、`:81` `register_all`；
白名单：`.claude/agents/bi-analyst.md:5`（14 个基础工具）+ 图库模式追加 2 个。

```mermaid
flowchart LR
    subgraph LLM["模型可见工具（16）"]
        direction TB
        subgraph ONT["本体 / 语义（5）"]
            T1["Ontology-SemanticQuery"]
            T2["Ontology-TermDisambiguate"]
            T3["MetricCalculation"]
            T4["Ontology-RelationQuery"]
            T5["Ontology-EntityDescribe"]
        end
        subgraph LIST["目录（1）"]
            T6["ListBusinessObjects"]
        end
        subgraph FACT["事实取数（4）"]
            T7["Ontology-MetricQuery"]
            T8["Ontology-FactQuery"]
            T9["ListTables"]
            T10["DescribeTable"]
        end
        subgraph GPH["图库（2 · 仅 graph 模式）"]
            T11["Ontology-GraphContext"]
            T12["Ontology-GraphExpand"]
        end
        subgraph PRES["呈现与澄清（4）"]
            T13["ChartGenerate"]
            T14["ChartGenerateMultiDim"]
            T15["TableGenerate"]
            T16["AskUser"]
        end
    end

    subgraph TX["传输层"]
        X1["RemoteOntologyClient<br/>_dual_request：新路径优先 · 旧路径兜底"]
        X2["DorisHttpConn<br/>只读 SQL 方言校验 + 网关"]
        X3["本地回退（仅非生产）<br/>SQLite / xlsx / graphml"]
    end

    subgraph EP["服务端点"]
        E1["POST /api/v1/analysis/data/query"]
        E2["POST /api/v1/analysis/meta/query"]
        E3["GET /api/v1/analysis/context/ontology-repository"]
        E4["GET /api/v1/analysis/context/expand-ontology-context"]
        E5["POST /api/v1/analysis/context/resolve-ontology-object"]
        E6["旧 /agent/ontology/**<br/>旧 /system/manager/**"]
        E7["Doris 查询网关"]
    end

    T1 --> X1
    T2 --> X1
    T3 --> X1
    T4 --> X1
    T5 --> X1
    T6 --> X1
    T7 --> X1
    T11 --> X1
    T12 --> X1
    T8 --> X2
    T9 --> X2
    T10 --> X2
    T13 --> X3
    T14 --> X3
    T15 --> X3
    T16 --> X3

    X1 --> E1
    X1 --> E2
    X1 --> E3
    X1 --> E4
    X1 --> E5
    X1 -.失败兜底.-> E6
    X2 --> E7
```

事实取数优先级（`analysis_policy.py:899` `doris_route_tools`）：

```mermaid
flowchart LR
    A["需要事实数据"] --> B{"Ontology-MetricQuery<br/>在会话白名单内？"}
    B -->|是| C["required_tools = [Ontology-MetricQuery]<br/>（指标语义查询，首选）"]
    B -->|否| D{"Ontology-FactQuery<br/>在会话白名单内？"}
    D -->|是| E["required_tools = [Ontology-FactQuery]<br/>（手写只读 SQL，兜底）"]
    D -->|否| F["required_tools = []<br/>→ CAPABILITY_LIMITATION"]
    C --> G["两者绝不同时声明为必需"]
    E --> G
```
