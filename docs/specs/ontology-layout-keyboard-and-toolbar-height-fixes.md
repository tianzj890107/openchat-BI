# Spec：布局选择器键盘闭环与工具栏等高修复

状态：已完成

前置 Spec：

- `docs/specs/ontology-layout-selector-white-tooltip.md`
- `docs/specs/ontology-layout-selector-acceptance-fixes.md`

## 1. 验收问题

当前自定义布局选择器仍有三个验收缺口，本次一并修复：

1. 菜单打开后焦点仍停留在 combobox trigger，但方向键、Home/End、Enter/Space 的主要处理写在 menu 上；纯键盘用户无法稳定导航和确认布局；
2. “重新布局”按钮使用工具栏通用按钮高度，与 `26px` 的布局 trigger 高度不一致；
3. 上一轮 Red 记录写成“10 fail、退出码 0”，与标准 `node --test` 失败退出语义矛盾，同时缺少桌面和窄屏浏览器验收记录。

## 2. 目标与边界

- 采用单一、完整的 ARIA combobox 键盘模型：焦点始终留在 trigger，通过 `aria-activedescendant` 指示活动 option；
- trigger 负责全部键盘导航和确认，menu 不再承担只有获得焦点才能工作的核心逻辑；
- “重新布局”按钮与布局 trigger 的可见高度统一为 `26px`；
- 保留现有自绘白色 listbox、白色 `?` Tooltip、`cluster/radial` 状态、busy 锁和无请求切换；
- 为本轮留下真实 Red → Green 原始输出，并补齐桌面及窄屏浏览器验收。

不修改图算法、后端接口、共享 `ontology-graph` 包或历史会话；不引入新依赖。

## 3. 键盘焦点模型

### 3.1 DOM 与 ARIA

trigger 必须同时具备：

```html
<button
  role="combobox"
  aria-haspopup="listbox"
  aria-expanded="false"
  aria-controls="ontology-layout-listbox"
  aria-activedescendant=""
>
```

每个 option 必须有稳定且唯一的 id：

```html
<button id="ontology-layout-option-cluster" role="option" tabindex="-1"></button>
<button id="ontology-layout-option-radial" role="option" tabindex="-1"></button>
```

行为要求：

- 菜单关闭时移除 `aria-activedescendant`，或将其设为空；
- 菜单打开时，`aria-activedescendant` 指向当前活动 option 的 id；
- 活动项变化时立即更新该属性及 `.is-active`；
- `aria-selected` 只表示已经提交的布局，不能把键盘临时活动项误当成已选择项；
- 打开、导航、选择和取消过程中，`document.activeElement` 始终为 trigger；
- option 可响应鼠标点击，但不进入 Tab 顺序，避免同时维护两套焦点模型。

### 3.2 trigger 上的完整键盘行为

所有键盘行为统一由 trigger 的 `keydown` 路径处理：

| 按键 | 菜单关闭 | 菜单打开 |
|---|---|---|
| `Enter` / `Space` | 打开，活动项为当前已选项 | 提交活动项、关闭、焦点保持 trigger |
| `ArrowDown` | 打开，并把活动项移动到当前项的下一项 | 移到下一项，末项后循环首项 |
| `ArrowUp` | 打开，并把活动项移动到当前项的上一项 | 移到上一项，首项前循环末项 |
| `Home` | 打开并活动首项 | 活动首项 |
| `End` | 打开并活动末项 | 活动末项 |
| `Escape` | 无变化 | 关闭，不提交，不改变布局 |
| `Tab` | 正常离开 | 关闭后正常离开，不阻止默认行为 |

要求：

- 删除或降级 `onOntologyGraphLayoutMenuKeydown`，不得再依赖 menu 获得焦点；
- `preventDefault()` 只用于会被组件消费的 Enter、Space、方向键、Home、End、Escape；Tab 不得阻止默认行为；
- commit 后调用现有 `switchOntologyGraphLayout(value)`，不发新请求；
- busy 时 trigger disabled，已打开 menu 立即关闭并清除 `aria-activedescendant`。

## 4. 推荐纯状态接口

扩展 `frontend/src/ontologyLayoutPickerState.js`，让 Runtime 使用一个纯键盘转换入口，避免测试只覆盖孤立 helper、却没有覆盖真实键位编排：

```js
export function handleOntologyLayoutPickerKey(state, key, { busy = false } = {}) {
  return {
    state: nextState,
    handled: true,
    commitValue: null,
  };
}
```

返回契约：

- 不支持的键：`handled=false`，state 不变；
- 导航键：更新 expanded/activeIndex，`commitValue=null`；
- 打开状态下 Enter/Space：关闭 menu，并返回活动项 `commitValue`；
- Escape/Tab：关闭但 `commitValue=null`；Tab 的 `handled=false`，让浏览器继续移动焦点；
- busy：不打开、不导航、不提交。

允许等价命名，但 Runtime 必须真正调用这个统一入口，不能只为测试新增未使用的函数。

## 5. “重新布局”按钮等高规范

为按钮增加专用 class 或使用现有 `[data-graph-relayout]`：

```css
.ontology-graph-toolbar [data-graph-relayout] {
  height: 26px;
  min-height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
}
```

必须满足：

- 布局 trigger 和“重新布局”按钮的计算高度均为 `26px`；
- 两者在同一工具栏基线垂直居中；
- 不通过 transform、负 margin 或缩放制造视觉假等高；
- busy/disabled 时尺寸不变化；
- `720px` 以下工具栏换行后仍保持等高；
- 不改变“子图检索”“关系扩散”按钮的业务行为。

## 6. TDD

### 6.1 Red：必须先写失败测试

先改测试并运行，禁止先改实现。

扩展 `frontend/tests/ontologyLayoutPickerState.test.mjs`：

1. 关闭时 Enter/Space 打开，活动项为当前选中项；
2. 打开时 Enter/Space 返回活动项并关闭；
3. 关闭和打开状态下 ArrowDown/ArrowUp 均符合第 3.2 节；
4. Home/End 在关闭和打开状态都正确；
5. Escape 关闭、不 commit、不改变 selectedValue；
6. Tab 关闭、`handled=false`、不 commit；
7. 未支持键不处理且保持对象不变；
8. busy 时所有会打开/导航/提交的键均无效；
9. commit 只返回 value，只有外部 `syncOntologyLayoutPicker()` 才改变 selectedValue。

扩展 `tests/test_regressions.py`：

1. trigger 包含并同步 `aria-activedescendant`；
2. 两个动态 option 获得稳定 id 和 `tabIndex=-1`；
3. Runtime trigger keydown 调用统一纯键盘转换函数；
4. trigger 路径覆盖 Enter、Space、ArrowDown、ArrowUp、Home、End、Escape、Tab；
5. Runtime 不再依赖 `layoutMenu.addEventListener("keydown", ...)` 完成核心导航；
6. commit 路径仍调用 `switchOntologyGraphLayout()`，且没有 fetch/load；
7. busy 与关闭弹窗均清除 expanded 和活动后代状态；
8. `[data-graph-relayout]` 与 `.ontology-layout-trigger` 都明确为 `height: 26px`、`box-sizing: border-box`；
9. 不允许 transform、scale 或负 margin 的假等高；
10. 原生 select 不得恢复，白色 menu 和右锚 Tooltip 契约继续成立；
11. 不删除、跳过或放宽任何既有测试。

有效 Red 必须正常加载，并至少因为下列当前缺陷失败：

- 没有统一键盘转换入口；
- trigger 未处理 Home/End/Tab 和已打开状态下的 commit/导航；
- 缺少 `aria-activedescendant` 和稳定 option id；
- “重新布局”按钮没有 `26px` 等高规则。

保存未经改写的 Red 原始输出，例如：

```text
docs/test-evidence/ontology-layout-keyboard-height-red.txt
```

记录实际命令与 shell 退出码。测试失败时退出码必须为非零；如果使用管道，必须启用 `pipefail`，禁止通过 `|| true` 把退出码改成 0。

### 6.2 Green

- 实现统一键盘转换、ARIA 活动项同步和按钮等高；
- 只做令新增与既有测试通过的最小修改；
- 保存 Green 原始输出到对应 evidence 文件；
- 更新本 Spec 的状态和证据摘要。

### 6.3 Refactor

- 删除失效或重复的 menu 键盘代码；
- trigger handler 只负责编排纯函数结果、DOM 同步和 layout commit；
- 不重复布局选项与提示文案；
- 不削弱 busy、异步 token、BFS、renderer dispose 或无请求切换测试。

## 7. 浏览器验收

必须使用实际浏览器验证并留下截图或测试产物路径：

### 桌面宽度

- 鼠标点击能展开、选择、外部关闭；
- 只用键盘完成 `cluster → radial → cluster`；
- 活动态、选中态和 `aria-activedescendant` 同步；
- “重新布局”与布局 trigger 高度均为 26px；
- `?` 白色气泡箭头指向 `?`。

### `720px` 以下

- 工具栏换行后两个控件仍等高；
- menu 和 Tooltip 不溢出、不被 dialog 裁切；
- 键盘路径仍能使用。

若仓库没有浏览器自动化依赖，可以人工验证，但必须记录浏览器、视口尺寸、结果和截图路径；不得只用源码字符串断言代替视觉验收。

## 8. 验收标准

| ID | 场景 | 预期结果 |
|---|---|---|
| AC-K1 | trigger 关闭时按 Enter/Space | menu 打开，焦点留在 trigger |
| AC-K2 | trigger 打开时按方向键/Home/End | 活动项及 `aria-activedescendant` 正确更新 |
| AC-K3 | trigger 打开时按 Enter/Space | 提交活动布局并关闭 |
| AC-K4 | 按 Escape/Tab | 分别取消或正常离开，不误提交 |
| AC-K5 | 鼠标操作 | 打开、选择、外部关闭保持正常 |
| AC-K6 | busy/close/reopen | menu、ARIA、selected state 始终一致 |
| AC-K7 | 工具栏桌面显示 | trigger 与“重新布局”均为 26px 高且垂直居中 |
| AC-K8 | 窄屏换行 | 两控件仍等高，menu/Tooltip 不裁切 |
| AC-K9 | TDD 证据 | Red/Green 原始输出和非零 Red 退出码可复核 |
| AC-K10 | 全量回归 | 前端、Python、共享包、构建及 diff check 全通过 |

## 9. 验证命令

```bash
cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics/frontend
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

- AC-K1～AC-K10 全部通过；
- 键盘可独立完成布局切换，且代码只使用一种焦点模型；
- 两个控件实际计算高度均为 `26px`；
- Red 和 Green 原始输出、退出码可复核；
- 桌面和窄屏浏览器验收有记录及截图/产物；
- 前置修复 Spec 中错误的“失败但退出码 0”记录被更正为事实，不伪造历史；
- 前端、Python、共享包原测试数量不减少，构建成功；
- 构建产物与源码一致，`git diff --check` 通过；
- 不覆盖无关工作区修改，不删除历史会话；
- 不部署、不创建 MR、不直接推送 `main`。


## 11. 本轮 Red → Green 证据（真实运行记录，2026-09-03）

原始输出（未经改写）：

- Red：`docs/test-evidence/ontology-layout-keyboard-height-red.txt`
- Green：`docs/test-evidence/ontology-layout-keyboard-height-green.txt`
- 浏览器验收 JSON：`docs/test-evidence/ontology-layout-browser-acceptance.json`
- 浏览器截图：`docs/test-evidence/k1-desktop-radial-committed.png`、
  `k2-desktop-cluster-committed.png`、`k3-desktop-tooltip.png`、
  `k4-narrow-menu.png`、`k5-narrow-tooltip.png`

### Red（实现改动前运行，非零退出码）

- 命令 1：`cd frontend && node --test tests/ontologyLayoutPickerState.test.mjs`
  - shell 退出码：1；20 tests / 11 pass / 9 fail。
  - 失败测试（均为新增统一键盘入口用例，因空桩 `handleOntologyLayoutPickerKey`
    只返回 `handled=false` 而失败）：`closed Enter/Space opens the listbox on the
    current selection without committing`、`open Enter/Space commits the active option
    and closes without self-selecting`、`ArrowDown/ArrowUp from closed open and step
    relative to the current selection`、`ArrowDown/ArrowUp keep cycling while the
    listbox is open`、`Home/End open when closed and jump when open`、`Escape closes
    without commit or layout change`、`Tab closes the listbox, stays unhandled and
    never commits`、`busy blocks opening, navigation and commit and closes an open
    listbox`、`keyboard commit stays separate from syncOntologyLayoutPicker`。
- 命令 2：`.venv/bin/python -m pytest tests/test_regressions.py -q -k ontology_layout`
  - shell 退出码：1；2 failed / 215 deselected。
  - 失败方法：`test_ontology_layout_picker_custom_combobox_and_tooltip_contract`（menu
    keydown 监听仍存在、无 `aria-activedescendant` 同步、option 无稳定 id/tabIndex、
    trigger 未委托统一键盘入口）；
    `test_ontology_layout_keyboard_trigger_and_toolbar_height_contract`（统一键盘入口、
    aria 同步与 26px 等高 CSS 均缺失）。
- 说明：Red 前仅新增空桩保证测试可加载；Runtime/CSS 未改动。

### Green（实现改动后运行，全量通过）

- `cd frontend && node --test tests/ontologyLayoutPickerState.test.mjs` → 20 passed（退出码 0）
- `cd frontend && node --test tests/*.test.mjs` → 66 passed（退出码 0）
- `cd frontend && npm run build` → 成功（退出码 0；workbench.js 1,282.97 kB）
- `cd /Users/sher/Boulderaitech/ontology-graph && npm test` → 6 passed（退出码 0）
- `.venv/bin/python -m pytest tests/test_regressions.py -q` → 217 passed（退出码 0，含新增
  `test_ontology_layout_keyboard_trigger_and_toolbar_height_contract`）
- `git diff --check` → 通过

## 12. 浏览器验收（真实 Chrome headless，2026-09-03）

浏览器：Google Chrome（`--headless=new`）；桌面视口 1440×900，窄屏 700×900。
页面：`http://127.0.0.1:8765/workbench`（本地 8765 服务）；本体子图弹窗经本体实体卡片
入口打开（本地本体数据为空时注入演示卡片触发同一委托入口，弹窗与工具栏为真实运行时）。

- 键盘闭环：Enter 打开后焦点始终在 trigger（`document.activeElement` 为 trigger），
  ArrowDown/ArrowUp/Home/End 驱动活动项并同步 `aria-activedescendant`（cluster/radial
  交替、循环回绕正确）；Enter 提交、Escape 取消不改变布局、Tab 关闭菜单并正常移焦；
  纯键盘完成 cluster → radial → cluster，全程 `/api/ontology/subgraph` 调用增量为 0。
- 鼠标：点击打开、点击选项行提交（radial）、点击外部关闭，全部正常，请求增量为 0。
- ARIA/选中态：菜单关闭时移除 `aria-activedescendant`；`aria-selected`/`.is-selected`
  只随已提交布局变化，键盘活动项只改 `.is-active`；option 为稳定 id +
  `tabIndex=-1`（实测 `ontology-layout-option-cluster/radial`）。
- 等高：桌面与 700px 窄屏下 layout trigger 与“重新布局”计算高度均为 26px
  （enabled/disabled 一致），两者中线与工具栏中线一致（实测 midY 126/126/126）；
  不依赖 transform/scale/负 margin。
- Tooltip：白色气泡右缘与 `?` 右侧对齐（rightGap 0）、位于 `?` 下方、在 dialog 内；
  箭头实测 `right:6px; top:-5px` 45° 旋转指向 `?`；无 `title` 原生气泡。
- 窄屏：工具栏换行后两控件仍等高 26px；自绘 menu（实测 251→399px）与 Tooltip
  （145→425px）均在 700px 视口与 dialog 内，无溢出/裁切；键盘选择可用。

### AC-K 对照

- AC-K1：Enter/Space 打开菜单且焦点留 trigger — 通过（实测 Enter 后 expanded=true、
  activedesc=option-cluster、activeElement=trigger）。
- AC-K2：方向键/Home/End 更新活动项与 aria-activedescendant — 通过（逐键实测同步）。
- AC-K3：Enter/Space 提交活动布局并关闭 — 通过（cluster→radial→cluster 纯键盘完成）。
- AC-K4：Escape 取消、Tab 正常离开 — 通过（Escape 后仍 radial 且 expanded=false；
  Tab 后 activeElement 离开 trigger，菜单关闭）。
- AC-K5：鼠标打开/选择/外部关闭 — 通过。
- AC-K6：busy/close/reopen 状态一致 — 通过（busy 纯状态单测 20 passed；close/reopen
  由既有 busy/身份契约测试覆盖）。
- AC-K7：桌面 26px 等高且垂直居中 — 通过（实测高度与中线）。
- AC-K8：窄屏换行等高、menu/Tooltip 不裁切 — 通过（700px 实测）。
- AC-K9：Red/Green 原始输出与非零 Red 退出码可复核 — 通过（evidence 文件均非零退出码记录）。
- AC-K10：全量回归 — 通过（前端 66、Python 217、共享包 6、构建成功、diff check 干净）。

前置修复 Spec（`ontology-layout-selector-acceptance-fixes.md`）中“10 fail、退出码 0”
的记录已在 2026-09-03 更正为事实：`node --test` 存在失败用例时退出码为非零；旧数值不可
复现（当时为未提交空桩状态），以本文件与 evidence 中可复核的非零退出码为准。
