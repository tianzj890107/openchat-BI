# Spec：智能分析 Agent 语义环形可视化

状态：待实现（TDD Red）
涉及仓库：`eimosp-ontology-agentic-analytics`
复用包：`@boulderaitech/ontology-graph@0.1.1`

## 1. 背景与已确认事实

- 智能分析端已经通过 `/api/ontology/subgraph` 获取本体子图，并在同一个弹窗中支持“子图检索”和“关系扩散”。
- 当前前端只调用 `createSigmaOntologyRenderer(canvas, buildGraph(graph))`，因此只有 Sigma + ForceAtlas2 的“关系聚类可视化”。
- 工具栏中的“关系聚类可视化”目前是静态按钮，不是布局选择器。
- 共享包已经导出 `layoutOntologyRadial`、`prepareRadialLayout`、`radialGraphOption` 等纯算法；包内测试已通过。
- 分析端已能从 `/static/vendor/echarts.min.js` 加载 ECharts，不需要新增 ECharts npm 依赖。
- 当前 `buildGraph(data)` 返回 graphology 实例；环形算法接收普通 `{ nodes, links }`，且每个节点必须具有 `layer`、`symbolSize`、`name` 等展示属性。因此需要分析端适配层，不能把 graphology 实例直接传给环形算法。

## 2. 目标

在现有本体子图弹窗中提供两种可切换布局：

1. **关系聚类可视化**：继续使用现有 Sigma + ForceAtlas2，保持当前默认行为；
2. **语义环形可视化**：复用共享包的径向算法，以当前锚点为中心，按与锚点的语义/关系距离向外分层。

用户切换布局时不得重新调用 `/api/ontology/subgraph`，不得调用 LLM，不得写入聊天历史，也不得推进 Agent SOP。

## 3. 范围与非目标

### 3.1 本次范围

- 分析端子图数据到共享环形契约的纯转换函数；
- 布局选择 UI 与键盘/ARIA 状态；
- Sigma 和 ECharts 两种渲染器的生命周期管理；
- Context/Expand 两种子图策略下的环形展示；
- 空图、无关系、裁剪、请求失败和渲染失败处理；
- 单元/契约测试和前端构建验证。

### 3.2 非目标

- 不修改 `/api/ontology/subgraph` 的响应协议；
- 不复制或改写共享包中的环形算法；
- 不把分析端业务图层、颜色映射或 DOM 逻辑放入共享包；
- 不发布或升级 `@boulderaitech/ontology-graph`；
- 不改变智能建模 Agent；
- 不删除、迁移或覆盖历史会话和用户数据；
- 不 push、不创建 MR、不部署。

## 4. 术语和布局语义

- **关系聚类**：由边的连接关系和 ForceAtlas2 力导向计算位置，适合探索局部拓扑。
- **语义环形**：中心锚点固定在中心，其余节点按照最短关系距离分环，适合阅读“离当前业务对象有多远”。
- **环层 `layer`**：表示相对锚点的关系距离，不等同于节点业务类型。
- **节点业务类型**：`BusinessObject`、`LogicalEntity`、`Indicator` 等，只决定颜色、尺寸和标签，不决定环层。

## 5. 数据契约

在 `frontend/src/ontologyGraphModel.js` 保留现有 `buildGraph(data)`，新增纯函数：

```js
export function buildRadialGraph(data) {
  return {
    nodes: [],
    links: [],
    layerDefinitions: [],
    centerLayer: "distance:0",
  };
}
```

### 5.1 节点输出

每个节点至少包含：

```js
{
  id: "stable-node-id",
  name: "用户可读名称",
  label: "用户可读名称",
  ontologyType: "Indicator",
  layer: "distance:1",
  parentId: "anchor-id",
  symbol: "roundRect",
  symbolSize: [width, height],
  itemStyle: { color: "#7c3aed" },
  focus: false,
  anchor: false,
}
```

要求：

- id 使用现有 `node.id || node.code` 规则，空 id 节点跳过；
- 名称使用 `node.name || node.code || id`；
- 颜色与业务类型沿用 `NODE_STYLE`；
- `symbolSize` 根据标签长度有限放大，并设置最小/最大宽度，不能无限扩张；
- 锚点优先使用 `node.anchor || node.focus`，其次匹配 `data.anchor.id/code`；
- 多个候选锚点时确定性选择第一个，同时仅将选中节点放入 `distance:0`；
- 无候选锚点但存在节点时，以输入第一个合法节点为中心；
- `parentId` 指向最短路径的上一层节点；同距离多父节点时按稳定 id 排序选择，保证结果确定；
- 不修改服务端返回对象。

### 5.2 环层计算

以锚点进行无向 BFS：

- `distance:0`：当前锚点；
- `distance:1`：与锚点直接相连；
- `distance:2` 及以后：按最短路径距离继续外扩；
- 孤立节点统一进入最后一个 `unrelated` 层；
- 无关系边时，锚点在中心，其余节点进入 `unrelated` 环，仍然可以展示；
- `layerDefinitions` 按 `distance:0...N, unrelated` 稳定排序；
- 环层标签分别为“中心”“1 跳”“2 跳”…“未关联”。

### 5.3 边输出

每条边至少包含：

```js
{
  id: "stable-edge-id",
  source: "node-a",
  target: "node-b",
  relation: "relation-name",
  lineStyle: { color: "#94a3b8", width: 1.2 },
}
```

- source/target 不存在或自环时沿用当前子图容错策略，不能使整个弹窗崩溃；
- edge id 使用服务端 id；缺失时用 `source|target|relation|index` 构造稳定 id；
- 不凭常识补造不存在的关系。

## 6. UI 与交互

### 6.1 布局选择

把当前静态“关系聚类可视化”按钮改为一个布局选择控件，包含：

- 关系聚类可视化；
- 语义环形可视化。

要求：

- 默认仍为关系聚类，避免改变现有用户习惯；
- 选择状态通过 `aria-pressed` 或等价可访问属性暴露；
- 切换只使用已加载的 `graph` 数据，不重新请求接口；
- 重新打开弹窗默认关系聚类；无需跨会话持久化用户选择；
- Context 与 Expand 切换后保留当前布局偏好，但使用新数据重新渲染。

### 6.2 工具栏行为

- 关系聚类下“重新布局”调用 Sigma `relayout()`；
- 语义环形下“重新布局”按当前 canvas 尺寸重新执行 `prepareRadialLayout()` 并 `setOption()`；
- 渲染期间禁用布局切换和重新布局按钮；
- 状态栏文案区分两种布局：
  - Sigma：`拖动节点、滚轮缩放；点击节点可高亮相邻关系。`
  - 环形：`滚轮缩放、拖动画布；节点按与锚点的最短关系距离分环。`

## 7. 渲染器生命周期

建议用一个统一句柄替代只面向 Sigma 的 `ontologyGraphRenderer`：

```js
let ontologyGraphView = null;

// 两种布局都实现
// { kind, destroy(), relayout() }
```

必须满足：

- 每次切换布局、切换查询策略、关闭弹窗或渲染失败前，先销毁旧实例；
- Sigma 使用 `kill()`；ECharts 使用 `dispose()`；
- `canvas.replaceChildren()` 只能在旧实例销毁之后执行；
- ECharts 尚未加载完成时关闭弹窗，异步结果不得再次挂载实例；
- 使用递增 render token 或 AbortController 防止旧请求/旧渲染覆盖新状态；
- ResizeObserver 或窗口变化后重新计算环形布局，但应去抖；
- 不允许同一 canvas 同时存在 Sigma 与 ECharts 实例。

## 8. 错误和降级

- 环形转换返回空图：显示“当前没有可展示的本体节点”，不初始化 ECharts；
- ECharts 加载失败：显示可读错误，并允许用户切回关系聚类；
- 环形布局返回 `null`：视为数据契约错误，不静默展示空白；
- `relations_available === false`：环形图仍展示节点，并在状态栏保留服务端关系不可用提示；
- 单一布局失败不得关闭弹窗或破坏另一种布局；
- 错误信息不得包含绝对服务器路径、token 或用户数据。

## 9. TDD 实施顺序

### 9.1 Red：先写失败测试

新增 `frontend/tests/ontologyRadialGraphModel.test.mjs`：

1. 锚点进入 `distance:0`；
2. 一跳、二跳节点按 BFS 进入正确环层；
3. 同一节点存在多条最短路径时 `parentId` 选择稳定；
4. 孤立节点进入 `unrelated`；
5. 没有显式锚点时选择首个合法节点；
6. 无边图仍能生成中心层和未关联层；
7. 输出包含 `name/layer/symbolSize/itemStyle`；
8. 输入对象未被修改；
9. 非法端点边不会导致异常；
10. 相同输入两次输出深度相等。

扩展 `tests/test_regressions.py` 的前端契约测试：

1. runtime 从 `@boulderaitech/ontology-graph/radial` 导入 `prepareRadialLayout`、`radialGraphOption`；
2. 仍保留 `createSigmaOntologyRenderer`；
3. 工具栏出现两个布局选项；
4. 切换布局不调用 `loadOntologyGraph` 或 `fetch`；
5. close/strategy change/layout change 都经过统一销毁函数；
6. ECharts 分支真实执行 `setOption(radialGraphOption(prepared))`；
7. 关系不可用状态仍允许环形渲染。

如运行时逻辑难以单测，应把状态转换抽成纯函数，新增 `frontend/tests/ontologyGraphViewState.test.mjs`，覆盖：

- 默认 Sigma；
- layout change 复用数据；
- strategy response 替换数据并保持布局；
- 迟到响应不覆盖较新的 render token；
- close 后异步 ECharts 不挂载。

### 9.2 Green：最小实现

只实现令上述测试通过的最小代码：

- `buildRadialGraph(data)`；
- 布局选择控件；
- 统一 renderer/view 句柄；
- ECharts 环形渲染分支；
- 必要 CSS。

不得复制 `src/radial.js`，不得顺便重构无关工作台代码。

### 9.3 Refactor：收敛职责

- 图数据转换保持纯函数；
- DOM/事件管理留在 runtime；
- 共享算法只从包导入；
- 消除 Sigma/ECharts 重复的销毁与状态文案逻辑；
- 保持函数和变量命名能区分 `strategy`（context/expand）与 `layout`（cluster/radial）。

## 10. 验收标准

| ID | 场景 | 预期结果 |
|---|---|---|
| AC-R1 | 打开任一本体子图 | 默认展示现有关系聚类图 |
| AC-R2 | 切换语义环形 | 不发新请求，锚点居中，其余节点按最短距离分环 |
| AC-R3 | 切回关系聚类 | 环形 ECharts 已 dispose，Sigma 正常创建 |
| AC-R4 | 环形下点“重新布局” | 按当前视口重新计算，不请求服务端 |
| AC-R5 | Context 切 Expand | 只请求一次新子图，保持当前布局偏好 |
| AC-R6 | 无关系边 | 节点仍可见，锚点在中心，状态栏提示关系不可用 |
| AC-R7 | 快速切换/关闭 | 无重复 canvas、无迟到渲染、无控制台生命周期异常 |
| AC-R8 | 包边界 | 分析仓库无环形算法副本，只存在数据适配与 UI |
| AC-R9 | 现有功能 | 两个本体卡片入口、Context/Expand、Sigma 高亮和缩放均无回归 |
| AC-R10 | 可访问性 | 布局控件可由键盘操作并暴露当前选择 |

## 11. 验证命令

```bash
cd /Users/sher/Boulderaitech/ontology-graph
npm test

cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics/frontend
node --test tests/ontologyRadialGraphModel.test.mjs
node --test tests/ontologyGraphViewState.test.mjs
npm run build

cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics
.venv/bin/python -m pytest tests/test_regressions.py -q
git diff --check
```

不存在的测试文件应在 Red 阶段创建；如果仓库实际测试入口不同，可使用等价命令，但必须在交付说明中列出实际执行命令和结果。

## 12. 完成定义

- AC-R1～R10 全部满足，并有自动化测试或明确的人工验收证据；
- 共享包测试、分析端前端测试、回归测试和生产构建全部通过；
- `git diff --check` 通过；
- 未修改共享环形算法、包版本、历史会话、用户数据或运行产物；
- 未 push、未创建 MR、未发布包、未部署。
