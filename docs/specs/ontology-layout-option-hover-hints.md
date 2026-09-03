# Spec：布局选项悬浮说明与问号入口移除

状态：已完成（2026-09-03）

关联 Spec：

- `docs/specs/ontology-layout-selector-white-tooltip.md`
- `docs/specs/ontology-layout-selector-acceptance-fixes.md`
- `docs/specs/ontology-layout-keyboard-and-toolbar-height-fixes.md`

## 1. 最终产品口径

布局说明只保留一个入口：展开布局下拉面板后，鼠标悬浮在具体选项行上时显示对应的白色说明气泡。

必须删除：

- 布局选择器右侧的 `?`；
- `[data-graph-layout-help]` 按钮；
- `aria-describedby="ontology-layout-tooltip"`；
- 原问号 Tooltip DOM、事件监听器和专用 CSS；
- 布局 trigger 自身的悬浮提示。

不得在 trigger 或 option 上使用原生 `title`，避免出现浏览器黑色提示框。

## 2. 唯一文案

`frontend/src/ontologyLayoutOptions.js` 是布局名称和说明文案的唯一来源：

| value | 名称 | 悬浮说明 |
|---|---|---|
| `cluster` | 关系聚类可视化 | ForceAtlas2 是一种先进的力导向图布局，适合查看节点之间的关系聚类。 |
| `radial` | 语义环形可视化 | 以当前锚点为中心，按照最短关系距离由内向外分环排列。 |

要求：

- `cluster` 必须使用上表完整句子，不再使用“ForceAtlas2 力导向布局……”旧文案；
- `radial` 文案保持不变；
- Runtime、HTML 模板、CSS、测试和 changelog 不得另建第三套提示文案；
- 旧文案不得继续出现在源码或构建产物中。

## 3. 下拉选项悬浮提示

自定义 listbox 中只创建一个可复用的白色提示气泡，禁止每个 option 各创建一个气泡：

```html
<div data-graph-layout-menu role="listbox">
  <button role="option" data-graph-layout-option="cluster"></button>
  <button role="option" data-graph-layout-option="radial"></button>
  <div data-graph-layout-option-tooltip role="tooltip" hidden></div>
</div>
```

允许等价 DOM，但必须满足：

1. `pointerenter`/`mouseenter` 具体 option 时，从 `ONTOLOGY_LAYOUT_OPTIONS` 查找该 value 的 hint 并显示气泡；
2. 从 option 或 listbox 离开时隐藏气泡；
3. 从一个 option 移动到另一个 option 时，气泡立即切换对应文案，不闪现旧内容；
4. 选择 option、关闭 listbox、点击外部、按 Escape/Tab、进入 busy、关闭本体弹窗时均隐藏气泡；
5. 重新打开 listbox 时气泡默认隐藏，不保留上次 hover 状态；
6. trigger 的 `mouseenter`、`focus`、点击和键盘打开菜单均不得显示说明气泡；
7. option 不设置 `title`；只使用页面自绘白色气泡；
8. 重复开关弹窗或菜单不得重复创建 Tooltip 或累加监听器。

“仅在下拉列表悬浮时提示”指只有鼠标指针位于某个展开的 option 行上时才可见。键盘活动项仍需保留 `aria-activedescendant`、`aria-selected` 等可访问状态，但不因键盘 focus/active 自动弹出视觉气泡。

## 4. 气泡视觉与定位

- 白色背景 `#fff`；
- 深色文字 `#334155` 或更深；
- `1px solid #e2e8f0` 边框；
- `6px`～`8px` 圆角和轻量阴影；
- 最大宽度 `280px`，允许自然换行；
- 箭头为白色并带浅灰边框；
- 默认显示在当前 hover option 的右侧；右侧空间不足时翻转到左侧；
- 气泡和箭头必须指向当前 option 行，不能指向 trigger、整个 listbox 或已删除的问号位置；
- `z-index` 高于 listbox、工具栏和图画布；
- 桌面与 `720px` 以下窄屏均不得超出视口或被 `.ontology-graph-dialog` 裁切；必要时使用弹窗级浮层和 `getBoundingClientRect()` 做边界定位；
- Tooltip 使用 `pointer-events: none`，避免鼠标进入气泡导致 hover 状态卡住。

## 5. 与键盘及等高修复的关系

本变更不得回退 `ontology-layout-keyboard-and-toolbar-height-fixes.md` 的要求：

- trigger 焦点模型继续使用 `aria-activedescendant`；
- Enter/Space/方向键/Home/End/Escape/Tab 能完整工作；
- 键盘活动项与已提交选中项分离；
- 布局 trigger 与“重新布局”按钮计算高度均为 `26px`；
- busy 会禁用 trigger 并关闭 listbox；
- 布局切换只重排已加载数据，不发新请求。

## 6. TDD

### 6.1 Red：先写失败测试

先修改测试并运行，禁止先改实现。

新增或扩展前端纯逻辑测试，建议创建：

```text
frontend/tests/ontologyLayoutOptionTooltipState.test.mjs
```

推荐纯状态接口：

```js
createOntologyLayoutOptionTooltipState()
showOntologyLayoutOptionTooltip(state, value)
hideOntologyLayoutOptionTooltip(state)
```

测试至少覆盖：

1. 默认隐藏且没有 active value/hint；
2. hover `cluster` 后显示完整新文案；
3. hover `radial` 后显示保持不变的环形文案；
4. `cluster → radial` 直接切换时不保留旧 hint；
5. leave、select、Escape、Tab、outside click、busy、modal close 均回到隐藏状态；
6. 未知 value 不显示气泡；
7. hide 幂等；
8. 选项配置不可修改，Tooltip 状态不反向修改配置对象。

扩展 `frontend/tests/ontologyLayoutOptions.test.mjs`：

- 精确断言 `cluster` 新文案；
- 精确断言 `radial` 原文案；
- 明确断言旧的 `ForceAtlas2 力导向布局，适合查看节点之间的关系聚类。` 不再存在。

扩展 `tests/test_regressions.py`：

1. Runtime 不得存在 `data-graph-layout-help`、`ontology-layout-helpbox`、问号按钮及 `aria-describedby="ontology-layout-tooltip"`；
2. CSS 不得存在 `.ontology-layout-help`、`.ontology-layout-helpbox` 和旧 `.ontology-layout-tooltip`；
3. trigger 不得绑定说明 Tooltip 的 mouseenter/focus，也不得设置 `title`；
4. option 不得设置 `title`；
5. 必须存在唯一 `[data-graph-layout-option-tooltip][role="tooltip"]`；
6. option hover 显示对应 hint，option/listbox leave 隐藏；
7. select、Escape、Tab、outside click、busy、modal close 均进入统一隐藏路径；
8. tooltip 文案必须通过 option value 从 `ONTOLOGY_LAYOUT_OPTIONS` 获取；Runtime 不得复制两段说明；
9. CSS 必须是白底深色、自绘箭头、option 锚定、左右边界翻转和 `pointer-events:none`；
10. 旧 cluster 提示文案不得存在，新文案在配置模块中恰好一处；
11. 自定义 combobox/listbox、键盘闭环和两个 `26px` 等高契约继续成立；
12. 不删除、不跳过或放宽现有测试。

有效 Red 必须正常加载，并至少因以下当前行为失败：

- 问号按钮及其 Tooltip 仍存在；
- option hover 没有说明气泡；
- cluster 仍为旧提示文案；
- trigger 仍绑定问号 Tooltip 逻辑。

保存未经修改的 Red 原始输出及非零退出码：

```text
docs/test-evidence/ontology-layout-option-hover-hints-red.txt
```

禁止使用 `|| true` 或其他方式把失败退出码改成 0；若使用管道必须启用 `pipefail`。

### 6.2 Green

- 更新唯一配置文案；
- 删除问号 DOM、事件和 CSS；
- 实现只属于 option hover 的单例白色 Tooltip；
- 所有菜单关闭路径统一隐藏 Tooltip；
- 仅做使新增及既有测试通过的最小修改。

### 6.3 Refactor

- 清除失效的 help/tooltip 函数、监听器和选择器；
- Tooltip 显隐状态与 picker 选中/活动状态分离；
- 不使用 `innerHTML` 注入说明；
- 不引入依赖，不回退键盘、ARIA、busy、等高及无请求切换能力。

## 7. 浏览器验收

### 桌面

- 页面上完全没有 `?`；
- trigger 悬浮、focus 或打开菜单时不显示说明；
- hover “关系聚类可视化”显示完整 ForceAtlas2 新文案；
- hover “语义环形可视化”显示原环形文案；
- 两个选项来回移动时文案即时切换；
- 离开列表或关闭列表后气泡消失；
- 白色气泡箭头指向当前 option；
- trigger 与“重新布局”均为 `26px`。

### `720px` 以下

- Tooltip 自动选择左/右侧，不溢出或被裁切；
- listbox、键盘交互和按钮等高不回退；
- 页面上没有残留问号占位空隙。

必须记录浏览器、视口、结果和截图/测试产物路径。源码字符串断言不能替代浏览器视觉验收。

## 8. 验收标准

| ID | 场景 | 预期结果 |
|---|---|---|
| AC-H1 | 查看布局控件 | 不存在问号、问号占位或问号 Tooltip |
| AC-H2 | hover/focus trigger | 不显示任何说明气泡 |
| AC-H3 | hover cluster option | 显示完整的新 ForceAtlas2 文案 |
| AC-H4 | hover radial option | 显示保持不变的环形文案 |
| AC-H5 | 两个 option 间移动 | 气泡跟随当前 option，文案无旧值闪现 |
| AC-H6 | 离开/选择/关闭/busy | 气泡立即隐藏且 reopen 不残留 |
| AC-H7 | 桌面与窄屏 | 气泡指向 option，不溢出、不裁切 |
| AC-H8 | 键盘与 ARIA | 键盘闭环正常，但键盘活动不弹视觉提示 |
| AC-H9 | 工具栏尺寸 | trigger 与“重新布局”计算高度均为 26px |
| AC-H10 | TDD 与回归 | Red/Green 证据、全量测试、构建全部通过 |

## 9. 验证命令

```bash
cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics/frontend
node --test tests/ontologyLayoutOptionTooltipState.test.mjs
node --test tests/ontologyLayoutOptions.test.mjs
node --test tests/ontologyLayoutPickerState.test.mjs
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

- AC-H1～AC-H10 全部通过；
- 页面和构建产物中不再存在问号提示入口或旧 cluster 文案；
- 说明气泡只在鼠标 hover 展开的具体 option 时显示；
- Red/Green 原始输出与退出码可复核；
- 桌面和窄屏浏览器验收有记录和截图/产物；
- 键盘闭环、ARIA、busy、按钮等高和无请求布局切换均未回退；
- 前端、Python、共享包测试数量不减少，构建成功；
- 构建产物与源码一致，`git diff --check` 通过；
- 同步更新相关 Spec 状态与当天 changelog 的最终口径；
- 不覆盖无关工作区修改，不删除历史会话；
- 不部署、不创建 MR、不直接推送 `main`。


## 11. 验收证据（2026-09-03）

### Red（实现前运行，退出码非零）

- 证据文件：`docs/test-evidence/ontology-layout-option-hover-hints-red.txt`
- `cd frontend && node --test tests/ontologyLayoutOptionTooltipState.test.mjs tests/ontologyLayoutOptions.test.mjs`
  → 15 tests / 9 pass / 6 fail，shell 退出码 1。失败原因均为行为缺失或旧文案：
  - `hovering cluster shows the full new ForceAtlas2 hint`、`hovering radial shows the unchanged ring hint`、
    `switching cluster to radial never keeps the old hint`、`leave, select, Escape, Tab, outside click, busy and
    modal close all collapse through hide`：空桩 `showOntologyLayoutOptionTooltip` 不显示气泡（visible 保持 false）；
  - `cluster hint uses the full advanced ForceAtlas2 sentence`、`the old ForceAtlas2 hint copy no longer exists`：
    `ontologyLayoutOptions.js` 仍为旧 cluster 文案。
- `cd frontend && node --test tests/ontologyLayoutPickerState.test.mjs` → 20 pass（回归保护，未被放宽）。
- `.venv/bin/python -m pytest tests/test_regressions.py -q -k ontology_layout` → 3 failed / 215 deselected，
  shell 退出码 1：`data-graph-layout-help` 与旧 `#ontology-layout-tooltip` DOM/CSS/监听器仍存在、
  无 `data-graph-layout-option-tooltip`、旧文案仍在 options 模块。3 个失败方法：
  `test_ontology_layout_picker_custom_combobox_and_tooltip_contract`、
  `test_ontology_layout_keyboard_trigger_and_toolbar_height_contract`、
  `test_ontology_layout_option_hover_tooltip_contract`。

### Green（实现后全量通过）

- 证据文件：`docs/test-evidence/ontology-layout-option-hover-hints-green.txt`
- `node --test tests/ontologyLayoutOptionTooltipState.test.mjs` → 8 pass；退出码 0
- `node --test tests/ontologyLayoutOptions.test.mjs` → 7 pass；退出码 0
- `node --test tests/ontologyLayoutPickerState.test.mjs` → 20 pass；退出码 0
- `node --test tests/*.test.mjs` → 76 pass；退出码 0（原 66 项未减少，新增 10 项）
- `npm run build` → 成功（workbench.js 1,283.49 kB）；退出码 0
- `cd /Users/sher/Boulderaitech/ontology-graph && npm test` → 6 pass；退出码 0
- `.venv/bin/python -m pytest tests/test_regressions.py -q` → 218 passed；退出码 0（新增
  `test_ontology_layout_option_hover_tooltip_contract`）
- `git diff --check` → 通过
- 构建产物核对：旧 cluster 文案与 `data-graph-layout-help` 均不在
  `bi_agent/web/static/vendor/antd/workbench.js`；新文案恰好 1 处、`data-graph-layout-option-tooltip`
  存在；CSS 产物中旧 `.ontology-layout-helpbox/.ontology-layout-tooltip` 已消失，新增
  `.ontology-layout-option-tooltip`。

### 浏览器验收（真实 Chrome headless 152，2026-09-03）

产物：`docs/test-evidence/ontology-layout-option-hover-browser-acceptance.json` 与截图
`docs/test-evidence/h1..h9-*.png`（h1 桌面开菜单、h2/h3 桌面 hover cluster/radial、
h4 气泡位置、h5 选中态、h6/h7 窄屏 700px 菜单与气泡、h8 窄屏提交、h9 窄屏 460px 左侧翻转）。
共 33 项断言全部通过：

- 桌面 1440×900：工具栏无 `?`/旧 Tooltip DOM/旧 CSS；trigger hover、focus、键盘打开菜单均不弹气泡；
  hover cluster 显示完整新 ForceAtlas2 文案，hover radial 显示环形文案；气泡默认在 option 右侧
  （gap 8px、纵向中心对齐），离开 option/listbox、选择、Escape、外部点击均隐藏；纯键盘
  Enter/ArrowDown/ArrowUp/Home/End/Escape/Enter 完成 cluster→radial→cluster 且全程
  `/api/ontology/subgraph` 请求数不变（1 → 1）；trigger 与“重新布局”计算高度均 26px。
- 窄屏 700×900：工具栏换行后两控件仍 26px；气泡在视口与 dialog 内不裁切；键盘提交正常。
- 窄屏 460×900：右侧空间不足时气泡自动翻转到左侧（`.flip`，实测 left 14 / right 294，
  在 460px 视口与 dialog 内），无溢出/裁切。

### AC-H 对照

- AC-H1：页面不存在问号、问号占位或问号 Tooltip — 通过（源码/CSS/构建产物均无
  `data-graph-layout-help`、`ontology-layout-helpbox`、旧 `.ontology-layout-tooltip`；浏览器实测工具栏文本
  `子图检索|关系扩散|布局|关系聚类可视化|重新布局`）。
- AC-H2：hover/focus trigger 不显示说明 — 通过（桌面与键盘打开均实测 bubble hidden）。
- AC-H3：hover cluster option 显示完整新文案 — 通过（浏览器实测全文一致）。
- AC-H4：hover radial option 显示保持不变的环形文案 — 通过（浏览器实测全文一致）。
- AC-H5：option 间移动即时切换、无旧值闪现 — 通过（mouseenter 直接读取注册表 hint 覆盖 textContent，
  DOM 单实例复用；桌面实测两文案均正确显示）。
- AC-H6：离开/选择/关闭/busy/弹窗关闭立即隐藏且 reopen 不残留 — 通过（统一
  `hideOntologyGraphLayoutOptionHint()`：option/listbox mouseleave、sync 非展开态、
  close 路径；浏览器实测 leave/Escape/select/outside click/modal close 后 hidden=true）。
- AC-H7：桌面与窄屏气泡指向 option、不溢出不裁切 — 通过（1440 右侧定位 gap/中心对齐几何断言；
  700 与 460 视口内、dialog 内；460 自动翻转）。
- AC-H8：键盘与 ARIA 闭环不回退且键盘活动不弹视觉气泡 — 通过（`aria-activedescendant`、
  Enter/Space/方向键/Home/End/Escape/Tab 由既有 20 项 picker 单测覆盖；浏览器实测键盘全程 bubble hidden）。
- AC-H9：trigger 与“重新布局”计算高度均为 26px — 通过（桌面与窄屏实测）。
- AC-H10：Red/Green 证据、全量测试、构建全部通过 — 通过（本文件 + evidence 文件；前端 76、
  Python 218、共享包 6、构建成功、`git diff --check` 干净）。

### 实现与文件

- `frontend/src/ontologyLayoutOptions.js`：cluster 文案更新为完整新句；名称/说明仍为唯一来源。
- `frontend/src/ontologyLayoutOptionTooltipState.js`（新增）：纯状态 `create/show/hide` 转换，
  无 DOM；不修改配置对象。
- `frontend/src/runtime.js`：删除 `?` 按钮、`ontology-layout-helpbox`、`#ontology-layout-tooltip`、
  `aria-describedby`、`show/hide/syncOntologyGraphLayoutTooltip`、`onOntologyGraphTooltipKeydown`；
  在 listbox 内新增唯一 `[data-graph-layout-option-tooltip][role="tooltip"]`；option
  mouseenter/mouseleave 与 listbox mouseleave 走统一显隐；位置按 option `getBoundingClientRect()`
  右锚定并支持 `flip`，以 dialog 边界与视口钳制。
- `frontend/src/workbench.css`：删除旧 help/tooltip 样式，新增 option 气泡（白底、深色文字、
  浅灰边框、8px 圆角、阴影、`max-width:280px`、`pointer-events:none`、左右箭头）。
- 测试：`frontend/tests/ontologyLayoutOptionTooltipState.test.mjs`（新增）、
  `frontend/tests/ontologyLayoutOptions.test.mjs`（更新为精确新文案断言）、
  `tests/test_regressions.py`（更新旧契约并新增 `test_ontology_layout_option_hover_tooltip_contract`）。
- 未删除/迁移任何历史会话与用户数据；未修改共享 `ontology-graph` 包；本任务未 commit、未 push、
  未创建 MR、未部署。
