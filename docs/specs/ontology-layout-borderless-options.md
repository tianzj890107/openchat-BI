# Spec：布局下拉项去按钮边框与样式隔离

状态：已完成（2026-09-03，TDD Red → Green → Refactor）

关联 Spec：

- `docs/specs/ontology-layout-option-hover-hints.md`
- `docs/specs/ontology-layout-keyboard-and-toolbar-height-fixes.md`

## 1. 缺陷与根因

当前下拉面板中的两个 option 使用 `<button>`，并同时命中工具栏通用规则：

```css
.ontology-graph-toolbar button {
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  padding: 6px 12px;
  background: #fff;
}
```

虽然 `.ontology-layout-option` 声明了 `border: 0`，但 `.ontology-graph-toolbar button` 的选择器优先级更高，导致 option 仍呈现为带边框、带明显倒角的独立按钮。

智能建模 Agent 的下拉项是 Ant Design Select 的无边框列表行：默认无边框、无独立白色按钮底板，hover/活动/选中状态只通过整行浅色背景和文字颜色表达。

## 2. 最终视觉口径

布局下拉面板本身保留：

- 白色背景；
- 浅灰外边框；
- `8px` 左右外层圆角；
- 轻量阴影。

面板内部每个 option 必须是无边框列表行：

- `border: 0`；
- `outline` 仅在 `:focus-visible` 时出现；
- 默认 `background: transparent`；
- 默认无 `box-shadow`；
- 不显示独立按钮外框或白色卡片底板；
- 两行之间不增加卡片式间距或分隔边框；
- option 可保留最多 `4px`～`6px` 的轻微背景圆角，只用于 hover/活动态的整行底色，不得形成默认状态的圆角按钮观感；
- hover/`.is-active`：整行浅蓝背景 `#eff6ff`，蓝色文字；
- `.is-selected`：蓝色文字及现有勾选标识，可与活动态叠加；
- option 的点击区域仍覆盖整行。

## 3. CSS 隔离方案

优先收窄工具栏通用按钮规则，使它只影响工具栏直属业务按钮：

```css
.ontology-graph-toolbar > button {
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  padding: 6px 12px;
  background: #fff;
  color: #334155;
  cursor: pointer;
}

.ontology-graph-toolbar > button.active { ... }
.ontology-graph-toolbar > button:disabled { ... }
```

布局 trigger 继续由 `.ontology-graph-toolbar .ontology-layout-trigger` 独立控制；option 由 `.ontology-layout-option` 独立控制。

同时为 option 明确声明完整重置：

```css
.ontology-layout-menu .ontology-layout-option {
  appearance: none;
  border: 0;
  outline: 0;
  box-shadow: none;
  background: transparent;
  border-radius: 4px;
}
```

说明：这里的 `appearance: none` 只用于普通 `<button>` 的样式归一化，不得恢复或伪装原生 `<select>`。

若不采用直属子选择器，必须使用明确高于通用规则的 option 选择器完成隔离；禁止依赖 `!important` 掩盖优先级问题。

## 4. 不得回退的行为

- 自定义 combobox/listbox 不得恢复为原生 select；
- trigger 本身继续保留边框、圆角、自绘 chevron 和 `26px` 高度；
- “重新布局”按钮继续保持 `26px` 高度；
- option 的 DOM 仍为 `role="option"`、稳定 id、`tabIndex=-1`；
- `aria-selected`、`.is-active`、`aria-activedescendant` 键盘闭环不得回退；
- 问号及问号 Tooltip 必须按照最新 Spec 删除；
- 说明只在鼠标悬浮具体 option 时显示白色气泡；
- option 和 trigger 均不得使用原生 `title`；
- 布局切换不得发新请求。

## 5. TDD

### 5.1 Red：先写失败测试

先扩展测试并运行，禁止先改 CSS。

扩展 `tests/test_regressions.py`，新增独立契约测试：

1. 不允许继续存在会命中所有后代按钮的 `.ontology-graph-toolbar button {`；
2. 工具栏通用规则必须收窄为 `.ontology-graph-toolbar > button`，或有等价的明确作用域隔离；
3. option 的最终有效规则必须包含 `border: 0`、`background: transparent`、`box-shadow: none`；
4. option 默认规则不得包含非零 border；
5. option 默认规则不得包含白色实体背景；
6. option 不得使用 `!important` 修正边框；
7. option hover/`.is-active` 必须保留浅蓝整行背景；
8. `.is-selected` 必须保留选中颜色和勾选标识；
9. focus-visible 必须仍有可见焦点环；
10. trigger 必须继续有边框、圆角和 `height: 26px`；
11. `[data-graph-relayout]` 必须继续为 `height: 26px`；
12. 最新 option-hover Tooltip、无问号、键盘 ARIA 和无请求切换契约不得删除或放宽。

静态字符串测试之外，增加一个真实 CSS 级验证，二选一：

- 在现有浏览器验收中读取 option 的 `getComputedStyle()`；或
- 使用已有浏览器测试环境断言计算样式。

必须断言普通、未 hover option 的计算结果：

```text
borderTopWidth = 0px
borderRightWidth = 0px
borderBottomWidth = 0px
borderLeftWidth = 0px
boxShadow = none
backgroundColor = transparent 或 rgba(0, 0, 0, 0)
```

有效 Red 必须正常加载，并因当前 `.ontology-graph-toolbar button` 覆盖 option 重置而失败。仅检查源码里存在 `border: 0` 不算有效 Red，因为当前源码已经有这段声明但计算样式仍错误。

保存 Red 原始输出与非零退出码：

```text
docs/test-evidence/ontology-layout-borderless-options-red.txt
```

禁止使用 `|| true`；若使用管道，必须启用 `pipefail`。

### 5.2 Green

- 收窄工具栏通用 button 规则或建立等价作用域隔离；
- 明确重置 option 的 border/background/shadow；
- 保留 hover、active、selected、focus-visible 行为；
- 只做使本轮及既有测试通过的最小改动。

### 5.3 Refactor

- 工具栏直属业务按钮、布局 trigger、下拉 option 三类控件各自拥有清晰样式边界；
- 删除重复或互相覆盖的声明；
- 不使用 `!important`；
- 不修改布局数据、状态机、图算法、接口或历史会话。

## 6. 浏览器验收

桌面和 `720px` 以下窄屏都必须检查：

- 展开布局菜单后，两个 option 默认均无边框；
- option 不再像两个独立圆角按钮；
- hover 时只有整行浅蓝背景，没有边框闪现；
- 当前选中项文字和勾选清晰；
- trigger 仍是有边框的选择器，能与无边框 option 明确区分；
- 菜单外层边框、圆角和阴影正常；
- option hover 白色说明气泡正常，不出现问号；
- 键盘选择和两个 `26px` 等高不回退。

记录浏览器、视口、截图/产物路径，以及 `getComputedStyle()` 的边框、背景和阴影结果。

## 7. 验收标准

| ID | 场景 | 预期结果 |
|---|---|---|
| AC-B1 | 默认展开菜单 | option 是无边框列表行，不是圆角按钮卡片 |
| AC-B2 | 检查计算样式 | 四边均为 `0px`，shadow 为 none，背景透明 |
| AC-B3 | hover/键盘活动 | 仅出现整行浅蓝背景和蓝色文字 |
| AC-B4 | 当前选中项 | 选中颜色与勾选正常，无独立边框 |
| AC-B5 | trigger | 保留选择器边框、圆角、chevron 和 26px 高度 |
| AC-B6 | 重新布局 | 保持 26px 高度，业务行为不变 |
| AC-B7 | CSS 作用域 | 通用工具栏按钮规则不再污染 option |
| AC-B8 | 最新提示口径 | 无问号，只在 hover option 时显示白色说明 |
| AC-B9 | 键盘与窄屏 | ARIA 键盘闭环、菜单定位均无回退 |
| AC-B10 | TDD 与回归 | Red/Green 证据及全量验证全部通过 |

## 8. 验证命令

```bash
cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics/frontend
node --test tests/*.test.mjs
npm run build

cd /Users/sher/Boulderaitech/ontology-graph
npm test

cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics
.venv/bin/python -m pytest tests/test_regressions.py -q
git diff --check
git status --short
```

## 9. 完成定义

- AC-B1～AC-B10 全部通过；
- 实际浏览器计算样式证明 option 四边为 0、背景透明、无阴影；
- Red/Green 原始输出与退出码可复核；
- 桌面、窄屏均有截图或浏览器验收产物；
- 自定义菜单、option hover 提示、无问号、键盘闭环和按钮等高均未回退；
- 前端、Python、共享包测试数量不减少，构建成功；
- 构建产物与源码一致，`git diff --check` 通过；
- 同步更新相关 Spec 状态与当天 changelog 的最终口径；
- 不覆盖无关工作区修改，不删除历史会话；
- 不部署、不创建 MR、不直接推送 `main`。

---

## 10. 验收证据（2026-09-03）

### Red（实现前运行，退出码非零）

- 静态契约测试：新增
  `OfflineRegressionTests::test_ontology_layout_option_borderless_contract`
  （12 组 subTest）。
- 命令：
  `.venv/bin/python -m pytest tests/test_regressions.py -q -k test_ontology_layout_option_borderless_contract`
- 结果：`5 failed, 1 passed, 218 deselected`，SHELL EXIT CODE 1。
- 核心失败断言：
  - `.ontology-graph-toolbar button {` 仍存在（通用规则命中所有后代按钮）；
  - `.ontology-graph-toolbar > button` 收窄规则不存在；
  - `.ontology-layout-menu .ontology-layout-option` 菜单级重置不存在
    （`border: 0` / `background: transparent` / `box-shadow: none` 缺失）。
- 真实 CSS 级 Red（headless Chrome 152，CDP，修复前 bundle，
  `http://127.0.0.1:8765/workbench`，1440x900）：
  `getComputedStyle()` 两个 option 均为 `border-*-width: 1px`、
  `border-radius: 7px`、白色/浅蓝底 —— `.ontology-graph-toolbar button`
  （0-1-1）覆盖 `.ontology-layout-option`（0-1-0）重置，option 呈现为
  带边框圆角按钮卡片。截图 `docs/test-evidence/r1-red-options-bordered.png`。
- 原始输出：`docs/test-evidence/ontology-layout-borderless-options-red.txt`

### Green（实现后全量通过）

- 命令与结果：
  - `cd frontend && node --test tests/*.test.mjs` → 76 tests / 76 pass；
  - `cd frontend && npm run build` → 成功（workbench.js 1,283.49 kB）；
  - `cd /Users/sher/Boulderaitech/ontology-graph && npm test` → 6 tests / 6 pass；
  - `.venv/bin/python -m pytest tests/test_regressions.py -q` → 219 passed
    （含新增 borderless 契约方法，12 subtests 全通过）；
  - `git diff --check` → 干净。
- 原始输出：`docs/test-evidence/ontology-layout-borderless-options-green.txt`

### 浏览器验收（真实 Chrome headless 152，2026-09-03）

- 视口：桌面 1440x900、窄屏 700x900；页面 `http://127.0.0.1:8765/workbench`。
- 结果：17 项检查全部通过（0 失败），详见
  `docs/test-evidence/ontology-layout-borderless-browser-acceptance.json`；
  截图 `g1-desktop-menu.png`、`g2-desktop-hover-row.png`、
  `g3-narrow-menu.png`、`g4-narrow-hover.png`。
- 计算样式关键值：
  - 默认 option：四边 `border 0px`、`box-shadow: none`、
    `background-color: rgba(0, 0, 0, 0)`、`border-radius: 4px`；
  - hover/`.is-active`：整行 `#eff6ff` 背景 + 蓝色文字，边框仍 `0px`；
  - `.is-selected`：`#2563eb` 文字 + `::after "✓"`；
  - trigger：`height 26px`、保留 `1px` 边框（有边框选择器外观）；
  - “重新布局”：`height/min-height 26px`；
  - menu：外框 `1px` 边框、`8px` 圆角、轻阴影；option 为无边框列表行；
  - 无“?”入口、无原生 `title`；hover option 仍显示白色说明气泡
    （cluster 新 ForceAtlas2 句 / radial 环形句）。

### AC-B 对照

- AC-B1：默认展开菜单时 option 是无边框列表行而非圆角按钮卡片 — 通过。
- AC-B2：计算样式四边 0px、shadow none、背景透明 — 通过（浏览器实测）。
- AC-B3：hover/键盘活动仅整行浅蓝背景和蓝色文字 — 通过。
- AC-B4：选中项蓝色文字与勾选正常、无独立边框 — 通过。
- AC-B5：trigger 保留边框、圆角、chevron、26px — 通过。
- AC-B6：重新布局按钮 26px、业务行为不变 — 通过。
- AC-B7：工具栏通用按钮规则收窄为 `> button`，不再污染 option — 通过。
- AC-B8：无问号，仅在 hover option 时显示白色说明 — 通过。
- AC-B9：键盘 ARIA 闭环、菜单定位与窄屏无回退 — 通过（既有 76 项前端
  测试与 219 项回归全部通过）。
- AC-B10：Red/Green 证据与全量验证通过 — 通过（本文件 + evidence 文件）。

### 实现与文件

- `frontend/src/workbench.css`：工具栏通用规则收窄为
  `.ontology-graph-toolbar > button`（含 `.active`/`:disabled`），新增菜单级
  option 重置 `.ontology-layout-menu .ontology-layout-option`
  （`appearance:none; border:0; outline:0; box-shadow:none;
  background:transparent; border-radius:4px`），无 `!important`。
- `tests/test_regressions.py`：新增
  `test_ontology_layout_option_borderless_contract`。
- 构建产物 `bi_agent/web/static/vendor/antd/*` 同步重建。
- 证据：`docs/test-evidence/ontology-layout-borderless-options-red.txt`、
  `...-green.txt`、`...-browser-acceptance.json`、截图 `r1-*`、`g1..g4-*`。
