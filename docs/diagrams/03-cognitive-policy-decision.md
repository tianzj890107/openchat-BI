# 图 3 · 单轮策略决策

> 智能分析 Agent 全链路流程图 · 第 3/9 张 —— `build_cognitive_policy_decision` 的 0→5 分支顺序、mode / reason_code / required_tools，以及安全分类内部合成规则。
> 基线 2026-09-20，仓库工作区当前代码；不含真实凭据、密钥或内部绝对路径。
> 返回 [图目录](README.md) ｜ 节点 → 代码位置见 [README §10](README.md#10-节点--代码位置索引)。

---

`bi_agent/tools/analysis_policy.py:862` `build_cognitive_policy_decision`。
该函数是**纯函数**：无 LLM、无文件、无数据库、无网络；只存输入摘要 `sha256:<hex>`，不存原始问题。

```mermaid
flowchart TD
    IN["输入：question + allowed_tools"] --> N["归一化<br/>去零宽字符 · 折叠空白 · 去外层标点"]
    N --> F["classify_forecast<br/>stored / predictive / scenario"]
    N --> I["classify_intent<br/>L1–L5 + wants_root_cause + wants_action"]

    F --> D0
    I --> D0

    D0{"0. classify_safety_refusal<br/>≠ None？"}
    D0 -->|是| R0["GENERAL_RESPONSE · GENERAL_REQUEST<br/>required_tools = []<br/>refusal_category = 凭据/环境/破坏性<br/>next_step = DELIVER"]

    D0 -->|否| D1{"1. 空问句 或 纯泛问？"}
    D1 -->|是 且 AskUser 可用| R1["CLARIFICATION · AMBIGUOUS_REQUEST<br/>required_tools = [AskUser]"]
    D1 -->|是 且 无 AskUser| R1b["GENERAL_RESPONSE · GENERAL_REQUEST<br/>required_tools = []"]
    D1 -->|否| D1B{"1b. 生成式预测 且 无预测对象？"}
    D1B -->|是 且 AskUser 可用| R1
    D1B -->|是 且 无 AskUser| RL["CAPABILITY_LIMITATION<br/>QUERY_CAPABILITY_UNAVAILABLE"]
    D1B -->|否| D2

    D2{"2. level=L2 或 wants_root_cause<br/>或 wants_action<br/>或 预测/推演？"}
    D2 -->|是| T2{"doris_route_tools<br/>有可用工具？"}
    T2 -->|否| RL
    T2 -->|是| R2["DIAGNOSTIC_ANALYSIS · DIAGNOSTIC_REQUEST<br/>required_tools = [Ontology-MetricQuery]<br/>或回退 [Ontology-FactQuery]<br/>evidence_required = true"]

    D2 -->|否| D3{"3. 元数据/本体信号？"}
    D3 -->|是 且 SemanticQuery 可用| R3["ONTOLOGY_LOOKUP · ONTOLOGY_LOOKUP_REQUEST<br/>required_tools = [Ontology-SemanticQuery]<br/>next_step = QUERY_ONTOLOGY"]
    D3 -->|是 且 无工具| RL
    D3 -->|否| D4{"4. 事实/指标/列表/趋势信号？"}
    D4 -->|是| T4{"doris_route_tools<br/>有可用工具？"}
    T4 -->|否| RL
    T4 -->|是| R4["FACT_QUERY · FACT_REQUEST_RESOLVED<br/>required_tools = [MetricQuery] 或 [FactQuery]<br/>next_step = QUERY_DORIS"]
    D4 -->|否| R5["5. GENERAL_RESPONSE · GENERAL_REQUEST<br/>required_tools = []<br/>不虚报数据需求"]
```

### 3.1 安全分类的合成规则（第 0 层内部）

```mermaid
flowchart LR
    Q["原始问句"] --> Z["去零宽 / bidi 字符"]
    Z --> C["按子句切分<br/>每子句额外生成去空白变体"]
    C --> A{"子句级判定"}
    A -->|"敏感对象 × 读取/披露/定位动作"| K1["credential_exfiltration"]
    A -->|"内部限定词 × 环境对象"| K2["environment_discovery"]
    A -->|"破坏性动词 × 业务数据对象<br/>且非约束陈述 / 非状态描述"| K3["destructive_data_operation"]
    A -->|"绕过审批 / 忽略安全规则"| K3
    K1 --> PR["按既有优先级取唯一类别"]
    K2 --> PR
    K3 --> PR
    PR --> OUT["refusal_category"]
```

要点：

- **组合式判定**：动作 × 对象 × 敏感性 × 目的，逐子句独立判断，多意图句子里任意一个危险子句命中即拒绝。
- **不误伤**：单独的"数据库 / 文件 / 目录 / 是什么"不会触发拒绝；必须与敏感动作配对。
- **约束陈述豁免**：`不得删除任意文件`、`删除会不会影响历史会话` 属约束/疑问，不算破坏性请求；但同一子句出现执行请求词（`帮我 / 现在就 / 直接`）时豁免失效。
- **业务路径豁免**：`上传 / 报表 / 模板 / 数据源 / 附件` 等业务制品路径问题仍走正常业务路由。
