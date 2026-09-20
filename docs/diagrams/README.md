# 智能分析 Agent 全链路流程图 · 目录

> 现状图（as-is）集合。基线：2026-09-20，仓库工作区当前代码。
> 这里只画**已经实现的真实行为**，每张图的节点都能在 §10 代码索引里找到位置。
> 不含任何真实凭据、密钥、环境变量密文或内部绝对路径。
>
> 配套文档：`docs/analysis-agent-data-source-and-ontology-consumption.md`（文字版现状说明）。
> 本目录是它的**图形版**，两者应同步维护。
> **编号约定**：§ 编号沿用拆分前的原始编号 —— §0 格式建议、§10 代码索引、§11 维护约定在本 README，
> §1–§9 各自独立成文件（文件序号与 § 编号一致）。

---

## 图目录

| 文件 | 图 | 内容 |
|---|---|---|
| [01-end-to-end-overview.md](01-end-to-end-overview.md) | 图 1 · 端到端总览 | 数据源 → 会话 → 单轮策略 → 工具循环 → 交付与门禁的整体拓扑，含不依赖渲染器的 ASCII 兜底图。 |
| [02-data-source-binding.md](02-data-source-binding.md) | 图 2 · 数据源原子配对 | 设置页 GET/PUT `/api/sources`、目录字段归一化、配对指纹比较与运行态重建。 |
| [03-cognitive-policy-decision.md](03-cognitive-policy-decision.md) | 图 3 · 单轮策略决策 | `build_cognitive_policy_decision` 的 0→5 分支顺序、mode / reason_code / required_tools，以及安全分类内部合成规则。 |
| [04-turn-sequence.md](04-turn-sequence.md) | 图 4 · 单轮时序 | 用户 / API / WebSession / analysis_policy / LLM / tool_runtime / 本体 MAL / Doris 的完整交互时序。 |
| [05-tool-transport-mapping.md](05-tool-transport-mapping.md) | 图 5 · 工具与端点映射 | 16 个模型可见工具、新旧双栈路径、以及 MetricQuery 优先 / FactQuery 兜底的取数规则。 |
| [06-graph-retrieval-mode.md](06-graph-retrieval-mode.md) | 图 6 · 图库检索模式 | 锚点消歧 → 有界邻域 → OpenCypher 只读补边 → 降级 → GraphExpand 扩散探索。 |
| [07-answer-truthfulness.md](07-answer-truthfulness.md) | 图 7 · 回答真实性约束 | 回答合同、未支撑数字、因果越界、代理指标披露、预测假设披露的判定顺序。 |
| [08-cache-concurrency-degradation.md](08-cache-concurrency-degradation.md) | 图 8 · 缓存并发与降级 | 本体缓存 TTL、三个进程级 limiter、准入控制、超时与各类降级路径。 |
| [09-eval-and-release-gate.md](09-eval-and-release-gate.md) | 图 9 · 评测与发布门禁 | CI 作业链、release gate 的六类必过门与被阻断条件、live canary 的边界。 |
| [10-business-panorama-16x9.md](10-business-panorama-16x9.md) | 图 10 · 业务全景架构（16:9 横版） | 面向业务侧的全景海报：六段业务主线 + 线条与色块图例。图形源为 `10-business-panorama-16x9.svg`，由 `build_business_panorama_16x9.py` 生成；正文只用业务语言，不含技术细节。 |
| [11-platform-architecture.md](11-platform-architecture.md) | 图 11 · 企业智能体平台整体架构 | 面向业务与产品视角的四层全景架构：应用接入层 / 智能体与能力层 / 语义层 / 数据层，四层通栏铺满画布。图形源为 `archify/platform-architecture.architecture.json`，由 Archify 生成可交互 HTML；正文只用业务语言，不含技术细节。 |
| [12-analytics-agent-architecture.md](12-analytics-agent-architecture.md) | 图 12 · 智能分析 Agent 整体架构 | 面向业务与产品视角的六层全景架构：提问受理层 / 安全与合规把关层 / 判断与分流层 / **本体语义层** / 取数与洞察层 / 交付与守门层，共 23 个能力块，六层通栏铺满画布。**本体**作为业务说法与指标口径的唯一出处单独成层（本体统一说法 → 指标口径与定义 → 业务对象与关系 → 业务到数据的映射 → 权限与可见范围），取数前必须先过本体；第五、第六层按 **L1 取数 → L2 找问题 → L3 根因 → L4 行动建议 → L5 执行监督** 逐级递进，并用加粗连线标出“根因升到行动建议”。图形源为 `archify/analytics-agent-architecture.architecture.json`，由 Archify 生成可交互 HTML；正文只用业务语言，不含技术细节。 |

阅读顺序建议：`01` → `03` → `04` 先建立整体认识，其余按需查阅。

---

## 0. 文件格式建议

结论：**Markdown + Mermaid，一图一文件 + README 目录，进仓库，作为唯一事实源**。理由与备选方案对比：

| 方案 | 是否推荐 | 理由 |
|---|---|---|
| **Markdown + Mermaid**（本目录 §1–§9） | ✅ 推荐，唯一事实源 | GitLab / GitHub / VS Code 原生渲染；纯文本可 `git diff`、可 code review；与代码同仓库同步演进；即使没有渲染器，正文、表格和 `01` 里的 ASCII 兜底图仍然可读 |
| 独立 `.mmd` 文件 | 仅作 CI 产物 | Mermaid CLI 可以直接吃，但 GitLab 不渲染（点开是源码），且会与 md 形成两份副本 → 需要出图时按下方命令从这些 md 抽取即可 |
| PlantUML `.puml` | 不采用 | 需要额外渲染组件（本地 Java / 服务端 PlantUML），本仓库 GitLab 未启用；中文与时序图收益不明显 |
| `.drawio` / `.vsdx` | 不采用 | 二进制不可 diff，评审看不到"改了什么"，长期必然与代码漂移；只在对外汇报时临时另存 |
| 导出的 `.svg` / `.png` | 仅 §10 例外用 `.svg` | 静态快照会过期、二进制 diff 噪声大，所以普通流程图仍按需导出到 `/tmp`；只有 §10 的业务全景海报用**纯文本 SVG**（自动布局无法锁定 16:9 画框与逐块配色），并由脚本重新生成，不引入二进制 |

按需出图（不进仓库，只落在 `/tmp`）：

```bash
# 逐张导出；产物只落在 /tmp，不提交进仓库
for f in docs/diagrams/[0-9]*.md; do
  npx -y @mermaid-js/mermaid-cli \
    -i "$f" -o "/tmp/$(basename "${f%.md}").png"
done
```

> 说明：每个 md 只含本图的 mermaid 代码块，`mermaid-cli` 会逐块渲染。
> 如果环境无 Node / 无外网，跳过这一步即可 —— 本目录的价值在源码，不在图片。
>
> §10 的业务全景海报是手工排版的矢量图（`10-business-panorama-16x9.svg`），本身就是可交付图形，
> 不需要渲染；它由 `build_business_panorama_16x9.py` 生成，改内容请改脚本后重跑。
> §11 的平台整体架构图与 §12 的智能分析 Agent 整体架构图由 Archify 分别从
> `archify/platform-architecture.architecture.json`、`archify/analytics-agent-architecture.architecture.json` 生成
> 对应的 `archify/*.architecture.html`，是自带图例与交互的可交付图形；
> 改内容请改 JSON 后按 §11 第 9 条重新生成并过质量门禁，不要手改 HTML。

---

## 10. 节点 → 代码位置索引

| 图 | 节点 | 代码位置 |
|---|---|---|
| §1 / §4 | 数据源启动与运行态 | `bi_agent/web/app.py:540`、`:600` |
| §2 | 列数据源 | `bi_agent/web/app.py:1721` `get_sources_endpoint` |
| §2 | 改数据源（原子配对） | `bi_agent/web/app.py:1869`、`:1916` `_put_sources_endpoint_impl` |
| §2 | 本体库目录归一化 | `bi_agent/web/app.py:1348` `_remote_repository_catalog`、`:1393` `_SOURCE_CONTEXT_FIELDS` |
| §2 | 配对指纹 | `bi_agent/web/app.py:1702` `_source_binding_signature` |
| §3 | 单轮决策入口 | `bi_agent/tools/analysis_policy.py:862` `build_cognitive_policy_decision` |
| §3 | 安全拒绝 | `bi_agent/tools/analysis_policy.py:767` `classify_safety_refusal` |
| §3 | 子句切分 / 约束豁免 | 同文件 `:651` `_safety_clauses`、`:672` `_is_constraint_statement`、`:684` `_destructive_action_in_clause` |
| §3 | 意图分级 | 同文件 `:307` `classify_intent`、`:155` `classify_forecast`、`:270` `wants_root_cause`、`:279` `wants_action` |
| §3 | 事实取数优先级 | 同文件 `:899` `doris_route_tools` |
| §4 | 会话生成 | `bi_agent/web/session.py:851` `generate_turn`、`:1136` `_run_loop` |
| §4 | 拒绝轮次 | `bi_agent/web/session.py:1098` `_refusal_turn`、`:476` `allowed_tools`（`_refusal_tool_block`） |
| §4 | 工具执行 | `bi_agent/web/session.py:1779` `_execute_tool`、`:1900` `_run_tool_and_emit`、`bi_agent/tool_runtime.py:483` `execute` |
| §5 | 工具注册 | `bi_agent/tools/__init__.py:48` `build_source_executors`、`:81` `register_all` |
| §5 | 工具 schema 清单 | `bi_agent/tools/ontology_tools.py:24/78/116/157/198/245`、`graph_tools.py:34/93`、`sql_tools.py:387/476/543` |
| §5 | 远程工具绑定 | `bi_agent/tools/remote_ontology_tools.py:732` `remote_specs` |
| §5 | 白名单 | `.claude/agents/bi-analyst.md:5` |
| §5 | 新旧路径双栈 | `bi_agent/ontology/remote.py:204` `_dual_request` |
| §5 | MAL 端点 | 同文件 `:476` scriptQuery、`:499` metadataQuery、`:507` dataQuery、`:530` listRepositories、`:265` findRelated、`:280` graphNeighborhood |
| §5 | Doris 只读校验 | `bi_agent/tools/sql_tools.py:289` `_ALLOWED_LEAD`、`:296` `_validate_sql`、`:179` `_doris_query` |
| §6 | 图库模式 SOP | `bi_agent/web/app.py:862` `GRAPH_MODE_SOP`、`:857` `GRAPH_PATTERNS` |
| §6 | 图库工具注入 | `bi_agent/web/app.py:3513` |
| §6 | 图检索实现 | `bi_agent/ontology/remote_retriever.py:132`、`:418`、`:496` |
| §7 | 回答真实性 | `bi_agent/web/session.py:302` `forecast_disclosure_missing`、`:1692` `_blocked_answer_fallback`、`:1708` `_no_narrative_fallback` |
| §7 | 指标定义 | `scripts/run_analytics_eval.py:1391`–`:1397`、`:3548` `RELEASE_REQUIRED_METRICS` |
| §8 | 缓存与超时 | `bi_agent/ontology/remote.py:128`（TTL）、`:142`（超时）、`bi_agent/tools/sql_tools.py:213`、`:270` |
| §8 | 并发与准入 | `bi_agent/concurrency.py:62` `Limits`、`:884` 三个 limiter、`:596` 准入拒绝 |
| §9 | CI 作业 | `.gitlab-ci.yml`（`unit-tests` / `eval-*` / `repeat-stability` / `release-gate` / `live-canary`） |
| §9 | 门禁计算 | `scripts/run_analytics_eval.py:3610` 起（P0、指标门、known-gap 治理） |

---

## 11. 维护约定

1. **本目录是图形版事实源**：`docs/analysis-agent-data-source-and-ontology-consumption.md` 是文字版，
   两侧改动必须同轮同步，不能只改一边。
2. **只画已实现行为**：未落地、被回滚、仅设计的方案不进图；如确需预留，另开 `*-proposed.md`。
3. **图与代码同 PR**：任何触及策略、工具、传输层、门禁的改动，必须检查对应图文件里的节点是否仍准确。
4. **Mermaid 语法自检**：提交前确认每个 md 的代码围栏成对闭合（`grep -c '^```' <文件>` 应为偶数），
   并用 §0 的 `mermaid-cli` 命令本地渲染一次；渲染失败视为文档缺陷。
5. **不写入敏感信息**：图中只出现环境变量**名**与端点**路径**，不得出现真实 Key、连接串、
   内部绝对路径或生产主机名。
6. **节点编号稳定**：§3 的 0 → 5 分支顺序与 `build_cognitive_policy_decision` 的注释编号一致，
   调整优先级时必须同步改图与 README §10 索引。
7. **一图一文件**：新增流程图时在 `docs/diagrams/` 下新建 `NN-<slug>.md`，并更新 README 图目录；
   不要把多张图重新塞回同一个文件。
8. **手工排版的海报**：`10-business-panorama-16x9.svg` 由 `build_business_panorama_16x9.py` 生成，
   改内容请改脚本后重跑，不要直接手改 SVG；改动后必须复核画布仍为 1920 × 1080、文字不溢出容器、
   连线不穿过色块。
9. **Archify 交付图**：`archify/*.architecture.html`（平台整体架构 `platform-architecture`、
   智能分析 Agent 整体架构 `analytics-agent-architecture`）由同目录 JSON 图形源生成，
   改内容请改 JSON 后用 `deliver --quality showcase` 重新生成，不要手改 HTML；提交前必须复核
   `validate` 为 9/9 通过且 0 error / 0 warning，并对输出跑 `visual-check`，确认 1440×900 等四个视口
   均无横向或纵向溢出；每层能力区块要保持左右边界一致，避免出现大片空白。
   **默认主题**：Archify 没有“默认主题”选项（产物在深色系统上就是深色），因此 `deliver` 之后要再执行
   `python docs/diagrams/archify/apply_default_theme.py <输出 HTML>` 把默认主题固定为浅色
   （同时把 CSS 变量底座从深色换成浅色，避免不执行脚本的预览/缩略图退回深色）；脚本幂等，
   重新生成 HTML 后需要重跑。智能分析 Agent 整体架构已应用该步骤，平台整体架构尚未应用。
