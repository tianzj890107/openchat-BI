# 本体图类型完整性核对（2026-11-05）

依据 demo2 发布的 [本体首页](http://demo2.eimos.com/ontology/home) 与该页面公开加载的 [首页脚本](http://demo2.eimos.com/ontology/js/pages/(base)/home/index-CvHG92el.js)。本轮直接读取发布资源核对类型定义；浏览器访问该域名失败，没有宣称完成登录后的真实本体库全类型验收。

首页调色板明确列出 13 种节点：BusinessObject、LogicalEntity、BusinessAttribute、Indicator、BusinessRule、Dimension、DimensionDerivedRule、Action、Event、Status、PhysicalTable、Field、Term。

## 核对结论与修复

| 类型 | 原问题 | 当前适配 |
| --- | --- | --- |
| 指标 | 已有节点样式 | 保留并与首页类型统一 |
| 业务规则 | 仅识别旧 Rule；平台是 BusinessRule | 类型、样式、筛选和子图请求均识别 BusinessRule |
| 维度 | 有样式，但共享包默认标签白名单未覆盖 | 共享包语义节点标签策略覆盖 |
| 活动、流程 | 有样式，默认标签未覆盖；不是 Action 的别名 | 保留 Activity/Process，与 Action 分开 |
| 元模型关系、实体关系 | 缺明确样式，子图类型解析不完整；MREL 可能误判指标 | 识别 MetaRelation/EntityRelation；节点或边按接口实际形态展示 |
| 动作、事件、状态、维度派生规则 | 消费端类型清单缺失 | 补齐命中解析、筛选、样式和子图类型请求 |
| 物理表、字段 | 原只认 TableNode/Column，与平台名称不一致 | 识别 PhysicalTable/Field，保留旧名称别名；沿用原默认隐藏的筛选策略 |

- analytics 的 `ontologyTypes.js` 统一消费端类型、旧名称别名、样式与筛选类别；不把业务类型映射塞进渲染器。
- 共享包 `@boulderaitech/ontology-graph@0.1.2` 默认允许所有语义节点显示标签，属性/字段按缩放或高亮显示；后续新增类型不再被固定标签白名单隐藏。消费者可显式恢复严格白名单。
- 图接口的 context 展示增加焦点节点直接关联，覆盖动作、事件、状态等非分析白名单关系；模型取数专用的上下文白名单保持原状。
- 合并图只使用真实关系边，不把 synthetic 邻居连线当作本体关系。
- 活动/流程/元模型关系是现有数据协议的兼容类型，不声称它们都在 demo2 当前首页的 13 种节点调色板中。

边界：本轮补齐图展示与接入适配，不等于新增各元素的建模编辑器、业务执行器或线上权限。关系名称、方向等保留在数据中，共享 Sigma 聚类视图仍沿用既有线条呈现。真实库是否提供具体关系，取决于服务返回，失败或截断仍需明确提示。

验证：消费端类型/图模型单测、服务端类型解析与动作-事件-状态邻接测试，以及隔离浏览器的 17 类型回放。没有改写 demo2 数据或部署服务。
