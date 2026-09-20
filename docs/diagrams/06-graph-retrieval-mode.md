# 图 6 · 图库检索模式

> 智能分析 Agent 全链路流程图 · 第 6/9 张 —— 锚点消歧 → 有界邻域 → OpenCypher 只读补边 → 降级 → GraphExpand 扩散探索。
> 基线 2026-09-20，仓库工作区当前代码；不含真实凭据、密钥或内部绝对路径。
> 返回 [图目录](README.md) ｜ 节点 → 代码位置见 [README §10](README.md#10-节点--代码位置索引)。

---

开启方式：`app.py:3513` 在基础工具后追加 `Ontology-GraphContext` / `Ontology-GraphExpand`，
并注入 `GRAPH_MODE_SOP`（`app.py:862`）；本地图库文件在远程模式下只作为只读兼容提示（`app.py:1737`）。

```mermaid
flowchart TD
    G0["GraphContext / GraphExpand 调用"] --> G1["RemoteOntologyClient.graph_neighborhood<br/>带 TTL 缓存的邻域查询"]
    G1 --> G2{"锚点唯一？"}
    G2 -->|唯一| G3["以锚点为中心取邻域<br/>保留边方向"]
    G2 -->|多个候选| G4["按候选类型消歧<br/>_CANDIDATE_TYPES"]
    G4 --> G3
    G3 --> G5{"邻域边是否完整？"}
    G5 -->|完整| G6["按边分组渲染子树<br/>节点 + 边属性"]
    G5 -->|缺边 / 服务端不支持通用边查询| G7["OpenCypher 只读补边"]
    G7 --> G8{"补边成功？"}
    G8 -->|是| G6
    G8 -->|否| G9["降级：仅顶点 + 已有边<br/>明确说明上下文不完整"]
    G6 --> G10["_context_codes 选出可信子图<br/>含锚点最短路径"]
    G9 --> G10
    G10 --> G11{"L3–L5 证据是否足够？"}
    G11 -->|不足| G12["GraphExpand 扩散探索<br/>depth 上调（有界）"]
    G11 -->|足够| G13["交付：根因 / 决策证据链"]
    G12 --> G11
```
