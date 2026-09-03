# Spec：窄屏布局选项悬浮提示验收证据修复

状态：已完成（2026-09-03，TDD Red → Green → Refactor）

前置 Spec：`docs/specs/ontology-layout-borderless-options.md`

## 1. 验收缺口

无边框 option 的代码、计算样式、桌面截图和全量测试已经通过，但窄屏悬浮提示证据无效：

- `g3-narrow-menu.png` 与 `g4-narrow-hover.png` 的 SHA-256 完全相同；
- `g4-narrow-hover.png` 没有显示白色说明气泡；
- `ontology-layout-borderless-browser-acceptance.json` 没有“窄屏 hover option 后 Tooltip 可见”的独立检查；
- 本轮浏览器脚本位于 `/tmp`，仓库中没有可重复执行的验收入口。

本次不预设前端功能有缺陷。先用可重复浏览器测试判断：若真实功能通过，只修复验收脚本和证据；若真实功能失败，再做最小前端修复。

## 2. 目标

- 将浏览器验收脚本纳入仓库，能够重复验证桌面和窄屏；
- 在 `700x900` 窄屏下真实 hover 一个 option，并断言白色气泡可见、文案正确、未裁切；
- 生成内容不同且场景真实的“菜单打开”和“选项悬浮”截图；
- JSON 记录窄屏 Tooltip 的可见性、文案、位置、边界和截图哈希；
- 不为补证据伪造、复制、重命名或图像编辑截图。

## 3. 可重复浏览器脚本

新增仓库脚本，例如：

```text
scripts/verify_ontology_layout_borderless_ui.mjs
```

脚本必须：

1. 接受可配置的页面 URL，默认 `http://127.0.0.1:8765/workbench`；
2. 使用本机 Chrome/Chromium 的真实 DOM、事件和 `getComputedStyle()`；
3. 不依赖 `/tmp/browser-borderless-*.mjs`；
4. 对测试本体实体的构造和打开方式可重复，不删除或修改历史会话；
5. 任一断言失败时以非零退出码结束；
6. 输出结构化 JSON 到：
   `docs/test-evidence/ontology-layout-borderless-browser-acceptance.json`；
7. 生成桌面和窄屏截图，不复制已有文件；
8. 报告浏览器版本、页面 URL、视口、运行时间和每项结果。

如脚本需要本地服务，文档必须写明启动与停止方式；不得部署或写服务器。

## 4. 窄屏悬浮验收步骤

视口固定为 `700x900`：

1. 打开本体子图弹窗；
2. 点击布局 trigger 展开 listbox；
3. 等待菜单可见和布局稳定；
4. 在未 hover option 的状态生成 `g3-narrow-menu.png`；
5. 将真实鼠标指针移动到 `radial` option 行中心，不允许只添加 class 或直接调用 Tooltip 函数；
6. 等待 `mouseenter` 处理与定位完成；
7. 断言 `[data-graph-layout-option-tooltip]`：
   - `hidden === false`；
   - 计算样式 `display !== "none"`、`visibility !== "hidden"`、`opacity !== "0"`；
   - 文案精确等于“以当前锚点为中心，按照最短关系距离由内向外分环排列。”；
   - 宽高均大于 0；
   - `left >= 0`、`top >= 0`、`right <= viewportWidth`、`bottom <= viewportHeight`；
   - 与被 hover option 的矩形相邻，且箭头方向/class 与左右翻转结果一致；
8. 保持 hover 状态生成 `g4-narrow-hover.png`；
9. 移出 listbox，断言 Tooltip 再次隐藏；
10. 断言 `g3` 与 `g4` 的 SHA-256 不同。

桌面 `1440x900` 的无边框、hover、新 ForceAtlas2 文案、按钮 `26px` 等既有检查必须保留。

## 5. TDD

### 5.1 Red

先新增证据契约测试，例如：

```text
tests/test_ontology_layout_browser_evidence.py
```

测试必须断言：

1. 仓库内浏览器验收脚本存在，不引用 `/tmp/browser-borderless`；
2. JSON 包含独立检查 `narrow hover tooltip visible`；
3. JSON 包含窄屏 Tooltip 的精确 radial 文案；
4. JSON 包含 Tooltip rect、viewport rect 和 `insideViewport=true`；
5. JSON 包含 hover 前后截图的 SHA-256；
6. `g3-narrow-menu.png` 与 `g4-narrow-hover.png` 文件哈希不同；
7. 两张图片尺寸一致、均非空；
8. `g4` 对应检查明确记录 `hidden=false` 和非零宽高；
9. JSON `failedCount === 0`；
10. 前置 Spec 最终证据不得继续声称两张相同图片证明了窄屏 hover。

先运行测试并保存 Red：

```text
docs/test-evidence/ontology-layout-narrow-hover-evidence-red.txt
```

有效 Red 应至少因为“脚本缺失、JSON 缺少窄屏 hover 项、两张截图哈希相同”失败，shell 退出码必须非零。禁止 `|| true`；使用管道时启用 `pipefail`。

### 5.2 Green

- 新增可重复浏览器脚本；
- 运行真实窄屏 hover 流程；
- 若功能正常，只更新 JSON、截图、Spec 和测试；
- 若 Tooltip 不显示或越界，先保存失败证据，再最小修复 Runtime/CSS 并重跑；
- 不通过复制图片、图像编辑、手工修改哈希或伪造 JSON 通过测试。

### 5.3 Refactor

- 删除对 `/tmp` 一次性脚本的交付依赖；
- 浏览器脚本中的 DOM 选择器和断言集中定义；
- 失败时输出足够诊断信息；
- 不改动与此验收缺口无关的业务代码。

## 6. 验收标准

| ID | 场景 | 预期结果 |
|---|---|---|
| AC-E1 | 运行仓库脚本 | 可重复完成桌面和窄屏浏览器验收 |
| AC-E2 | 窄屏菜单打开 | `g3` 显示无边框菜单且无 Tooltip |
| AC-E3 | 窄屏真实 hover radial | Tooltip 可见且显示精确环形文案 |
| AC-E4 | Tooltip 定位 | 宽高非零、完全位于视口内、锚定 option |
| AC-E5 | 窄屏 hover 截图 | `g4` 清楚显示 option 与白色气泡 |
| AC-E6 | 证据独立性 | `g3`/`g4` SHA-256 不同 |
| AC-E7 | 鼠标离开 | Tooltip 恢复隐藏 |
| AC-E8 | 原视觉契约 | option 无边框、trigger/重新布局均 26px |
| AC-E9 | 证据真实性 | JSON、截图与脚本同次运行生成，无复制或伪造 |
| AC-E10 | 全量回归 | 前端、Python、共享包、构建、diff check 全通过 |

## 7. 验证命令

```bash
cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics
.venv/bin/python -m pytest tests/test_ontology_layout_browser_evidence.py -q
node scripts/verify_ontology_layout_borderless_ui.mjs

cd frontend
node --test tests/*.test.mjs
npm run build

cd /Users/sher/Boulderaitech/ontology-graph
npm test

cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics
.venv/bin/python -m pytest tests/test_regressions.py -q
.venv/bin/python -m pytest tests/test_ontology_layout_browser_evidence.py -q
git diff --check
git status --short
```

## 8. 完成定义

- AC-E1～AC-E10 全部通过；
- Red/Green 原始输出和真实退出码可复核；
- 仓库内脚本可以重新生成 JSON 与截图；
- `g3` 与 `g4` 哈希不同，`g4` 肉眼可见白色气泡；
- JSON 明确验证窄屏 Tooltip 文案、可见性、尺寸、边界和离开后隐藏；
- 前置 Spec 修正为最终事实；
- 若未发现产品代码缺陷，不制造无意义 Runtime/CSS 修改；
- 不覆盖无关工作区修改，不删除历史会话；
- 不部署、不创建 MR、不直接推送 `main`。

---

## 9. 验收证据（2026-09-03）

### Red（实现前运行，退出码非零）

- 新增证据契约测试：`tests/test_ontology_layout_browser_evidence.py`（11 项）。
- 命令：
  `.venv/bin/python -m pytest tests/test_ontology_layout_browser_evidence.py -q --tb=line`
- 结果：`9 failed, 1 passed in 0.02s`，SHELL EXIT CODE 1。
- 核心失败断言：
  - 仓库内脚本缺失：`scripts/verify_ontology_layout_borderless_ui.mjs` 不存在；
  - JSON 缺少独立检查 `narrow hover tooltip visible` 及窄屏 Tooltip
    rect/viewport/文案/离开后隐藏等记录；
  - `g3-narrow-menu.png` 与 `g4-narrow-hover.png` SHA-256 相同
    （`6bf23ec9…570c5`），两张图片不是有效 hover 证据。
- 原始输出：`docs/test-evidence/ontology-layout-narrow-hover-evidence-red.txt`

### 真实功能结论（先判断产品代码，再决定是否修改）

- 用仓库内脚本在真实 Chrome 中运行后确认：窄屏 `700x900` 下真实鼠标
  hover radial option 时白色 Tooltip 正常显示、文案精确、完全位于视口内，
  鼠标移出 listbox 后正常隐藏。
- 未发现产品代码缺陷：本轮不修改 `runtime.js`、不修改 `workbench.css`，
  只补齐可重复脚本、JSON、截图、测试与文档。

### Green（仓库内可重复脚本 + 全量通过）

- 新增 `scripts/verify_ontology_layout_borderless_ui.mjs`：
  自动启动本机 headless Chrome/Chromium（`CHROME_BIN` 可覆盖），默认页面
  `http://127.0.0.1:8765/workbench`（`WORKBENCH_URL` 可覆盖），真实 DOM、
  真实鼠标事件、`getComputedStyle()`/`getBoundingClientRect()`，桌面
  `1440x900` 与窄屏 `700x900` 共 21 项检查全部通过（0 失败），输出 JSON 与
  `g1..g4` 四张截图（同一次运行），任一断言失败退出码非零。
- 命令与结果：
  - `node scripts/verify_ontology_layout_borderless_ui.mjs` → 21 pass / 0 fail；
  - `.venv/bin/python -m pytest tests/test_ontology_layout_browser_evidence.py -q`
    → 11 passed（契约测试）；
  - `cd frontend && node --test tests/*.test.mjs` → 76 tests / 76 pass；
  - `cd frontend && npm run build` → 成功；
  - `cd /Users/sher/Boulderaitech/ontology-graph && npm test` → 6 tests / 6 pass；
  - `.venv/bin/python -m pytest tests/test_regressions.py -q` → 219 passed；
  - `git diff --check` → 干净。
- 原始输出：`docs/test-evidence/ontology-layout-narrow-hover-evidence-green.txt`

### 窄屏 Tooltip 关键数值（浏览器实测，Chrome/Chromium headless 152.0.7977.65）

- hover option：`radial`；文案精确为
  “以当前锚点为中心，按照最短关系距离由内向外分环排列。”
- `hidden=false`、`display=block`、`visibility=visible`、`opacity=1`；
- `rect = {left:402, top:140, right:682, bottom:194, width:280, height:54}`；
- `viewport = 700x900`，`insideViewport=true`（`left>=0`、`top>=0`、
  `right<=700`、`bottom<=900`）；
- Tooltip 与 radial option 相邻（option 右缘 394 ≤ Tooltip 左缘 402），
  `flip=false`（右侧空间充足，未翻转，与 class 一致）；
- 鼠标移出 listbox 后：`hidden=true`、`display=none`；
- 截图哈希（同一次脚本运行重新计算）：
  - `g3-narrow-menu.png` = `9e81e86de230fc023df8e506ca231b66ab30aaa0b07232af377110219c95ba49`
  - `g4-narrow-hover.png` = `0b44fe2aef1db3252b045b3c4fdc4e77ccecae2e63948777b2baaf814fbc86c0`
- 像素差分（仅分析、不修改图片）：g4 相对 g3 新增 12,213 个纯白像素
  （白色气泡与箭头）与 3,411 个 `#eff6ff` 浅蓝像素（hover 整行），差异包围盒
  `(256,105)-(697,215)` 与 CDP 记录的 Tooltip rect 吻合，完全位于视口内。

### AC-E 对照

- AC-E1：运行仓库脚本可重复完成桌面与窄屏验收 — 通过（21/21，0 失败）。
- AC-E2：窄屏 `g3` 显示无边框菜单且无 Tooltip — 通过。
- AC-E3：窄屏真实 hover radial 后 Tooltip 可见且文案精确 — 通过。
- AC-E4：Tooltip 宽高非零、完全位于视口内、锚定 option — 通过。
- AC-E5：`g4` 清楚显示 option 与白色气泡 — 通过（像素差分佐证）。
- AC-E6：`g3`/`g4` SHA-256 不同 — 通过。
- AC-E7：鼠标离开 listbox 后 Tooltip 恢复隐藏 — 通过。
- AC-E8：原视觉契约（无边框 option、trigger/重新布局 26px 等）— 通过。
- AC-E9：JSON、截图与脚本同一次运行生成，无复制或伪造 — 通过。
- AC-E10：前端、Python、共享包、构建、diff check 全通过 — 通过。

### 实现与文件

- `scripts/verify_ontology_layout_borderless_ui.mjs`（新增，仓库内可重复验收入口）。
- `tests/test_ontology_layout_browser_evidence.py`（新增，证据契约测试 11 项）。
- `docs/test-evidence/ontology-layout-borderless-browser-acceptance.json`（重生成，
  含窄屏 Tooltip 独立检查与截图哈希）；`g1..g4-*.png`（重生成，g3/g4 来自
  同一次真实 hover 流程）。
- 证据：`docs/test-evidence/ontology-layout-narrow-hover-evidence-red.txt`、
  `...-green.txt`。
- 前置 Spec `ontology-layout-borderless-options.md` 的证据说明已按最终事实修正。
