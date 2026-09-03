# eimosp-ontology-agentic-analytics 变更记录（2026-09-03）

> 本文档只记录 2026-09-03 当天完成的最终变更。
> 本文件由用户当天明确要求创建，补录当日此前未写入 changelog 的变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。

## 变更

### 1. 语义环形可视化 Spec（新增，TDD Red 待实现；当前未提交）

- 今日新增 Spec `docs/specs/ontology-radial-visualization.md`：复用共享包
  `@boulderaitech/ontology-graph@0.1.1` 的径向纯算法与仓库内 ECharts 静态资源，
  在现有本体子图弹窗“关系聚类可视化”（Sigma + ForceAtlas2）基础上规划可切换的
  “语义环形可视化”；布局切换不得重新请求 `/api/ontology/subgraph`、不调用 LLM、
  不写聊天历史、不推进 Agent SOP。
- 范围要点：新增“子图数据 → 共享环形契约”的纯转换层、布局选择 UI 与键盘/ARIA 状态、
  Sigma 与 ECharts 两种渲染器的生命周期管理、Context/Expand 两种子图策略及空图/
  无关系/失败边界处理；不改子图响应协议、不复制或改写共享包算法、不新增 ECharts
  npm 依赖。
- 状态：Spec 已创建（标记“待实现（TDD Red）”），Red 测试与实现尚未开始；该文件
  当前未提交（`git status` 未跟踪），本条目不将其描述为已完成功能。
- 主要文件：`docs/specs/ontology-radial-visualization.md`（新增，未提交）。
- 验证：无（Spec 阶段，未实现、未验证；未部署）。
