# Spec：本体布局自定义选择面板与验收修复

状态：已完成

前置 Spec：`docs/specs/ontology-layout-selector-white-tooltip.md`

## 1. 验收缺陷

当前实现未通过完整验收，存在三个问题：

1. 布局控件使用原生 `<select>`，展开后的选项列表由浏览器/操作系统绘制，没有实现智能建模 Agent 的前端选择面板样式；
2. 白色说明气泡定位在整个布局容器左侧，箭头指向“布局”文字附近，而不是 `?`；
3. 前置任务没有留下可复核的 Red 运行记录，且前置 Spec 仍标记为“待实现（TDD Red）”。

本次必须修复前两项，并为本次修复留下真实 Red → Green 证据。不得伪造或追补声称此前已经发生过的 Red。

## 2. 参照实现与技术边界

视觉和交互参照智能建模 Agent 的 `OntologyLayoutSelector`：

- 左侧固定文字“布局”；
- 中间为宽度约 `148px` 的选择器；
- 右侧为浅灰圆形 `?`；
- 展开后显示白色、带圆角和阴影的前端选项面板；
- 当前选项有明确的选中态，选项 hover 有浅蓝反馈。

建模 Agent 使用 React + Ant Design `Select`，但分析 Agent 当前本体弹窗由 `runtime.js` 原生 DOM 管理。本次实现行为和视觉等价的原生自定义选择器，不为一个控件引入 React、Ant Design 或其他新依赖。

保留现有状态与文案唯一来源：

| value | 显示名称 | 说明文案 |
|---|---|---|
| `cluster` | 关系聚类可视化 | ForceAtlas2 力导向布局，适合查看节点之间的关系聚类。 |
| `radial` | 语义环形可视化 | 以当前锚点为中心，按照最短关系距离由内向外分环排列。 |

## 3. 自定义选择器 DOM 契约

删除原生 `<select data-graph-layout-select>`，替换为自定义单选 listbox。推荐结构：

```html
<span class="ontology-layout-selector">
  <span class="ontology-layout-label">布局</span>

  <span class="ontology-layout-picker">
    <button
      type="button"
      class="ontology-layout-trigger"
      data-graph-layout-trigger
      role="combobox"
      aria-label="布局"
      aria-haspopup="listbox"
      aria-expanded="false"
      aria-controls="ontology-layout-listbox"
    >
      <span data-graph-layout-value>关系聚类可视化</span>
      <span class="ontology-layout-chevron" aria-hidden="true"></span>
    </button>

    <div
      id="ontology-layout-listbox"
      class="ontology-layout-menu"
      data-graph-layout-menu
      role="listbox"
      aria-label="布局"
      hidden
    >
      <button type="button" role="option" data-graph-layout-option="cluster"
        aria-selected="true">关系聚类可视化</button>
      <button type="button" role="option" data-graph-layout-option="radial"
        aria-selected="false">语义环形可视化</button>
    </div>
  </span>

  <button type="button" data-graph-layout-help
    aria-label="当前布局说明"
    aria-describedby="ontology-layout-tooltip">?</button>
  <span id="ontology-layout-tooltip" role="tooltip" hidden></span>
</span>
```

允许等价 DOM，但必须满足相同的 ARIA、状态和键盘行为。选项必须从 `ONTOLOGY_LAYOUT_OPTIONS` 创建，不得在模板或 Runtime 再复制名称与说明。

## 4. 选择面板交互

### 4.1 打开与选择

- 点击 trigger 打开/关闭 listbox；
- 打开时 `aria-expanded="true"`，关闭时为 `false`；
- 点击选项调用已有 `switchOntologyGraphLayout(value)`，更新 trigger 文案及 `aria-selected`，然后关闭面板并把焦点还给 trigger；
- 切换只复用已有图数据，不得调用 `loadOntologyGraphData()`、`loadOntologyGraph()` 或 `fetch()`；
- 点击选择器以外区域、关闭本体弹窗或按 `Escape`，面板关闭；
- 再次打开时高亮当前状态，不保留陈旧 active option。

### 4.2 键盘与可访问性

- trigger 上按 `Enter`、`Space`、`ArrowDown` 或 `ArrowUp` 打开面板；
- 打开后 `ArrowDown` / `ArrowUp` 在两个选项间循环移动活动项；
- `Home` / `End` 移到首项/末项；
- `Enter` 或 `Space` 选择活动项；
- `Escape` 关闭且不改变布局，并将焦点还给 trigger；
- `Tab` 关闭面板并按正常焦点顺序离开；
- 不依赖鼠标 hover 才能完成选择。

### 4.3 busy 与生命周期

- request 或 render busy 时，trigger 必须 `disabled=true`；
- busy 开始时若面板已打开，立即关闭；
- busy 结束后恢复；
- 弹窗 reopen 时默认仍为 `cluster`，trigger、选中项和状态一致；
- 一个 Runtime 生命周期只能创建一个 menu，事件监听器不得随 reopen 累加；
- document 级 click/keydown 监听器如非 Runtime 全生命周期固定监听，必须在对应 teardown 中移除。

## 5. 选择面板视觉规范

选择器需达到建模 Agent 的观感，而不是浏览器原生控件：

- trigger 宽度：`148px`；高度约 `24px`～`28px`；
- 白色背景、浅灰边框、`6px`～`8px` 圆角；
- trigger 右侧为自绘 chevron，不使用系统 `<select>` 箭头；
- 展开时边框/焦点环使用蓝色系，清晰但不过重；
- menu 由页面 CSS 完整控制：白色背景、浅灰边框、`8px` 圆角、轻量阴影、适当内边距；
- menu 宽度不得小于 trigger，且不得显示系统原生选择列表；
- option 为完整可点击行；hover/键盘活动态使用浅蓝背景，选中态使用蓝色文字并可带勾选标记；
- menu 的 `z-index` 高于本体工具栏和画布；
- 在弹窗右边缘或窄屏场景不得横向溢出或被 `.ontology-graph-dialog { overflow: hidden; }` 裁掉；必要时做边界定位或在弹窗级浮层容器中定位；
- 不得用 `<select size>`、`appearance: none` 冒充自定义弹出面板。

## 6. 白色说明气泡定位修复

保留现有白色视觉、hover/focus/Escape 行为，并修复锚点：

- 气泡必须以 `[data-graph-layout-help]` 为定位锚点，而不是以整个 selector 左边缘为锚点；
- 默认在 `?` 下方显示，气泡右边缘与 `?` 附近对齐，箭头明确指向 `?`；
- 禁止继续使用当前 `.ontology-layout-tooltip { left: 6px; }` 与 `::before { left: 16px; }`；
- 可采用 `right: 0; left: auto` 加右侧箭头，或使用基于 `getBoundingClientRect()` 的边界定位；
- 窄屏时气泡保持在弹窗/视口内；
- 切换布局后，气泡 DOM 文案立即同步当前选项，即使气泡当前未打开；
- `?` 不得设置 `title`，继续使用白色自定义 `role="tooltip"` 气泡。

## 7. TDD

### 7.1 Red：先写失败测试

先修改测试，不得先改实现。

新增 `frontend/tests/ontologyLayoutPickerState.test.mjs`，对纯状态/键盘辅助模块进行测试：

1. 默认关闭、当前值为 `cluster`；
2. toggle/open/close 正确改变 expanded；
3. ArrowDown/ArrowUp 循环移动活动项；
4. Home/End 选择首末活动项；
5. Enter/Space 返回待选择 value；
6. Escape 关闭且不改变 value；
7. 外部 state 切换后，活动项、显示名称和 hint 同步；
8. busy 会关闭面板并禁止再次打开；
9. 未知 value 不进入 DOM 状态。

扩展 `tests/test_regressions.py`：

1. 断言不再存在 `<select data-graph-layout-select`；
2. 存在 combobox trigger、listbox、两个 option、`aria-expanded`、`aria-controls`、`aria-selected`；
3. 选项由 `ONTOLOGY_LAYOUT_OPTIONS` 动态生成，不复制文案；
4. 存在 click、outside click、Enter、Space、ArrowDown、ArrowUp、Home、End、Escape、Tab 契约；
5. 选择路径调用 `switchOntologyGraphLayout(value)`，且不发请求；
6. busy 禁用 trigger 并关闭 menu；
7. state → DOM 同步覆盖 trigger 文案、当前 option 和 tooltip 文案；
8. CSS 存在自定义 trigger、chevron、menu、option hover/active/selected、focus-visible 和浮层层级；
9. CSS 不得通过 `select[data-graph-layout-select]` 或 `appearance:none` 实现；
10. Tooltip 不再使用左侧固定锚点，气泡及箭头定位到 `?` 右侧附近；
11. 前置 Spec 状态最终更新为“已完成”，本修复 Spec 在 Green 后更新为“已完成”；
12. 不删除、不跳过、不放宽现有 busy、BFS、异步身份和 renderer dispose 测试。

有效 Red 必须正常加载，并至少因以下旧行为失败：

- Runtime 仍包含原生 `<select>`；
- 不存在自定义 `role="combobox"` / `role="listbox"`；
- Tooltip 仍使用 `left: 6px` 和左侧箭头；
- 没有 picker 键盘状态模块。

把 Red 命令、失败测试名、关键断言和退出码记录到本 Spec 的“Red 证据”小节或提交说明中。不得伪造前一轮 Red，只记录本轮真实运行结果。

### 7.2 Green

- 实现自定义选择器及白色 Tooltip 定位修复；
- 仅做让新增与既有测试通过的最小改动；
- 运行单测、回归和构建；
- 更新两个 Spec 的状态与真实 Red/Green 结果。

### 7.3 Refactor

- 选项配置继续只有一个来源；
- 将 picker 状态/键盘转换保持为纯函数，DOM 层只负责渲染和绑定；
- 统一 menu 与 tooltip 的关闭逻辑，但不得混淆两者的 ARIA 状态；
- 清除旧 select DOM、监听器和 CSS；
- 不引入新依赖，不修改图算法、接口、共享包或历史会话。

## 8. 验收标准

| ID | 场景 | 预期结果 |
|---|---|---|
| AC-F1 | 点击布局 trigger | 展开页面自绘白色选择面板，不出现系统原生列表 |
| AC-F2 | 查看面板 | 只有两种布局，当前项有选中态，hover/活动态清晰 |
| AC-F3 | 鼠标选择布局 | trigger、状态、选中项同步，复用已有数据重排 |
| AC-F4 | 键盘操作 | Enter/Space/方向键/Home/End/Escape/Tab 行为正确 |
| AC-F5 | 图请求或渲染 busy | trigger 禁用，已打开 menu 自动关闭，结束后恢复 |
| AC-F6 | 点击外部或关闭弹窗 | menu 关闭，无残留浮层或重复监听器 |
| AC-F7 | 悬浮或聚焦 `?` | 白色气泡从 `?` 附近弹出，箭头明确指向 `?` |
| AC-F8 | 切换布局后查看 `?` | 气泡立即使用新布局说明，无旧文案闪现 |
| AC-F9 | 窄屏/弹窗边缘 | menu 和气泡不横向溢出、不被裁切 |
| AC-F10 | TDD 与回归 | 本轮 Red 证据真实，新增与原测试、构建全部通过 |

## 9. 验证命令

```bash
cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics/frontend
node --test tests/ontologyLayoutPickerState.test.mjs
node --test tests/ontologyLayoutOptions.test.mjs
node --test tests/*.test.mjs
npm run build

cd /Users/sher/Boulderaitech/ontology-graph
npm test

cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics
.venv/bin/python -m pytest tests/test_regressions.py -q
git diff --check
git status --short
```

## 10. 完成定义

- AC-F1～AC-F10 全部通过；
- 本轮有真实、可复核的 Red → Green 证据，不伪造历史记录；
- 原生 select、旧 CSS 和旧事件逻辑完全移除；
- 选择面板与白色气泡均经过实际浏览器人工检查，至少覆盖桌面和 `720px` 以下窄屏；
- 前端、共享包、Python 回归数量不得减少；
- 构建产物与源码一致，`git diff --check` 通过；
- 前置 Spec 与本 Spec 状态反映最终事实；
- 不覆盖无关工作区修改，不删除历史会话；
- 不部署、不创建 MR、不直接推送 `main`。

## 11. 本轮 Red → Green 证据（真实运行记录，不追补历史）

### Red（2026-09-03，实现改动前运行）

- 命令 1：`cd frontend && node --test tests/ontologyLayoutPickerState.test.mjs`
  - 结果：10 tests / 0 pass / 10 fail，退出码 0（node:test 报告失败计数）。
  - 关键断言：`picker defaults to closed with cluster selected`（`ontologyLayoutPickerSelectedOption` 解析失败）、
    `toggle opens and closes the listbox`、`ArrowDown and ArrowUp cycle the active option`、
    `busy closes an open menu and prevents reopening`、`unknown values never become the picker value` 等。
  - 原因：`ontologyLayoutPickerState.js` 当时仅存在 Red 空桩（转换函数原样返回、解析函数返回 null）。
- 命令 2：`.venv/bin/python -m pytest tests/test_regressions.py -q`（先更新本轮四个契约方法后运行）
  - 结果：`test_ontology_graph_modal_uses_product_labels_and_synced_cluster_layout`、
    `test_ontology_subgraph_radial_layout_contract`、
    `test_ontology_subgraph_async_controls_and_renderer_handle_contract`、
    `test_ontology_layout_picker_custom_combobox_and_tooltip_contract` 共 4 failed（其余方法通过）。
  - 关键断言：`'<select data-graph-layout-select' 不应存在`、
    `'data-graph-layout-trigger role="combobox"' 缺失`、`role="listbox"` 缺失、
    `syncOntologyGraphControls` 中无 `setOntologyLayoutPickerBusy(`、
    Tooltip CSS 仍含 `left: 6px` / `::before left: 16px`。
  - 原因：实现仍为原生 `<select>` + 左锚 Tooltip，自定义 combobox/listbox 与右锚气泡未实现。

### Green（同一工作区，实现改动后运行）

- `cd frontend && node --test tests/ontologyLayoutPickerState.test.mjs` → 10 passed；
  `node --test tests/*.test.mjs` → 56 passed；
- `cd frontend && npm run build` → 成功（workbench.js 1,282.64 kB）；
- `cd /Users/sher/Boulderaitech/ontology-graph && npm test` → 6 passed；
- `.venv/bin/python -m pytest tests/test_regressions.py -q` → 216 passed；
- `git diff --check` → 通过。

说明：前置 Spec 的“Red 证据”本节只记录本轮真实发生的失败；此前轮次的实现记录见
`ontology-radial-visualization-acceptance-fixes.md` 与本仓库 commit 历史，不在本节追补。
