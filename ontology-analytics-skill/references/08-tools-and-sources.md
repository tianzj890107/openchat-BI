<!-- 来源：bi_agent/tools/*.py 的 SPECS（基线提交 c94d430，自动生成）+ bi_agent/web/app.py 的工具白名单与数据源配置。 -->

# 工具清单与数据源契约

## 工具表（17 个，schema 自动导出）

| 工具 | 用途 | 参数 | 必填 |
| --- | --- | --- | --- |
| `AskUser` | 请用户在若干候选项中做出选择,用于消除模糊性。必须在以下场景使用: (A) 术语消歧 — 当问句中的业务术语在本体里有多个候选口径(例如'客户活跃度'同时对应月活/周活/订单活跃)且无法从上下文唯一确定; (B) 指标/维度下钻选择 ... | - | - |
| `ChartGenerate` | Render a chart for tabular data you already have in hand. Valid sources: an Ontology-FactQuery result set, a table ex... | - | - |
| `ChartGenerateMultiDim` | Render a MULTI-DIMENSIONAL chart with a dimension dropdown for 深入洞察 (deep-insight) drill-down tasks. Use this ONLY af... | - | - |
| `DescribeTable` | Show the physical column list of a table (name, type, nullable). Use this to cross-check ontology attributes against ... | - | - |
| `ListBusinessObjects` | List all business objects in the ontology (code, name, physical table). Use this when the user's question is open-end... | - | - |
| `ListTables` | List all tables in the connected database. Useful when you need to confirm a physical table exists before querying. P... | - | - |
| `MetricCalculation` | Return the full spec of a metric: business formula, scope, SQL components (table/agg_column/agg_type/filter/join), an... | - | - |
| `Ontology-EntityDescribe` | Return a full description of a logical entity: definition, physical table, all attributes with data types, and all re... | - | - |
| `Ontology-FactQuery` | Execute a single read-only SQL statement against the customer database. The active source is either a local SQLite DB... | - | - |
| `Ontology-GraphContext` | 图库检索 · 上下文准备(第3步)。给定一个业务对象或指标锚点,沿图库层级一次性拉取其全部下挂的本体行信息(已剪枝去重),作为回答问题的背景上下文。 - 业务对象锚点 → 该业务对象 + 其下逻辑实体/业务属性 + 其下指标。 - 指... | - | - |
| `Ontology-GraphExpand` | 图库检索 · 扩散探索 skill(仅 L3–L5 根因/决策/执行,且已有上下文不足时使用)。从一个业务对象锚点出发,沿『活动 → 所属流程(取整条流程行信息)』、『活动上下游(活动流流转)』、实体关系及其他已建模关系找到上下游业务... | - | - |
| `Ontology-MetricQuery` | 通过远程 analysis/data/query 按本体指标和维度进行聚合计算。远程模式下应优先于手写 SQL；只有接口不支持或失败时才回退 Ontology-FactQuery。 | - | - |
| `Ontology-RelationQuery` | List all entity relations (ER) that touch a given logical entity. Use this to plan joins or trace upstream/downstream... | - | - |
| `Ontology-SemanticQuery` | Cross-ontology keyword search. Searches terms, business objects, logical entities, metrics, activities, and rules by ... | - | - |
| `Ontology-TermDisambiguate` | Resolve a user-facing word or phrase to its canonical term entry (definition, category, aliases). Call this whenever ... | - | - |
| `TableGenerate` | Render a structured data table for the Web UI. Use this instead of writing Markdown tables whenever you're presenting... | - | - |
| `TodoWrite` | 维护本轮分析的任务清单,会被置顶展示给用户(类似 Claude Code 的待办列表)。用法:在 L2 及以上的多步分析一开始,就先调用一次,把后续步骤拆成 3–6 条任务(取数 / 下钻 / 交叉验证 / 出图 / 给结论等);之后... | - | - |

## 工具白名单

- 默认（数据分析模式，14 个）：`Ontology-SemanticQuery`、`Ontology-TermDisambiguate`、`MetricCalculation`、`Ontology-RelationQuery`、`Ontology-EntityDescribe`、`ListBusinessObjects`、`Ontology-MetricQuery`、`Ontology-FactQuery`、`ListTables`、`DescribeTable`、`ChartGenerate`、`ChartGenerateMultiDim`、`TableGenerate`、`AskUser`。
- 图库检索模式：追加 `Ontology-GraphContext`、`Ontology-GraphExpand`（流程见 `09-graph-mode.md`）。
- 报表分析 · 启用数据库查询：默认 14 个；纯报表模式只有 `ChartGenerate`、`TableGenerate`、`AskUser`。
- `TodoWrite` 不写进白名单，但多步分析（L2 及以上）可用。

## 数据源与配置

| 数据源 | 说明 | 关键配置 |
| --- | --- | --- |
| 本体（本地） | Excel 工作簿经 `OntologyStore` 载入，落成术语/业务对象/逻辑实体/属性/关系/指标/活动/规则/矩阵 | 本体 xlsx 路径 |
| 本体（远程） | 生产模式走本体服务，不再读 Excel；仓库/作用域必须显式注入 | `ONTOLOGY_BASE_URL`、`DORIS_API_URL`、仓库 ID；缺一即拒绝启动 |
| 图库 | 图库检索模式下的图文件 | `GRAPH_PATH`，扩展名 `.graphml/.gml/.kuzu/.graph/.ttl/.rdf` |
| SQL（本地） | SQLite 只读打开（`mode=ro`） | 数据库文件路径 |
| SQL（Doris） | MySQL 协议或 HTTP 网关取数 | `DORIS_API_URL`、库名；网关只接受 `SELECT`/`MATCH` 开头 |
| x360 | 流程定义/环节接口 | 服务地址与凭据从环境变量读取，禁止写进提示词或日志 |

## 调用契约

- 每次调用都必须带作用域（仓库 ID / 数据库名），不得使用"当前默认源"隐式取数。
- 取数一律只读；写操作、DDL、多语句一律拒绝（见 `07-output-gates.md` 第 4 条）。
- 结果必须保留结构化形态（列/行或指标+维度+过滤条件），下游证据闸门依赖它。
- 建议暴露方式（二选一）：CLI 包装（每个工具一条命令，stdin/stdout 走 JSON）或 MCP server；schema 直接沿用上面的参数与必填项。
- 远端并发要有上限；同一会话串行、跨会话并行，避免把本体服务打满。

## 未包含在本包内

- 具体工具实现（`bi_agent/tools/*.py`、`bi_agent/ontology/*`、`bi_agent/x360/*`）：受让方需要自备等价实现或改为调用服务端接口。
- Web 会话/SSE/前端工作台：与宿主 agent 的运行时绑定，不随本包交付。
