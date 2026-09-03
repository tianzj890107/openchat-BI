# eimosp-ontology-agentic-analytics 变更记录（2026-09-03）

> 本文档只记录 2026-09-03 当天完成的最终变更。
> 本文件由用户当天明确要求创建，补录当日此前未写入 changelog 的变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。

## 变更

### 1. 本体子图弹窗新增“语义环形可视化”（Spec + 实现 + 验收修复，已完成）

- 用户可见变化：本体子图弹窗工具栏现提供两个布局选项——默认“关系聚类可视化”
  （Sigma + ForceAtlas2，行为不变）与新增“语义环形可视化”；环形视图将当前锚点置于
  中心，其余节点按与锚点的最短关系距离分环展示（`distance:0..N`、`unrelated`），
  支持滚轮缩放、拖动画布与按当前视口重新布局；布局切换与重新布局只复用已加载子图
  数据，不重新请求 `/api/ontology/subgraph`、不调用 LLM、不写聊天历史、不推进 SOP。
- Context/Expand 子图检索仍走原接口，响应到达后保持当前布局偏好；无关系边、空图、
  ECharts 加载失败、环形契约错误等边界均有可读提示且不会关闭弹窗。
- 异步控件与生命周期修复：子图请求与渲染期间，strategy/layout/relayout 三类控件统一
  禁用；请求与渲染分别用 `requestEpoch`/`renderToken` 守卫，旧请求或迟到渲染不能解锁
  新任务或覆盖新状态；Sigma `kill()` 与 ECharts `dispose()` 收敛为幂等 renderer
  handle，关闭弹窗、切换策略、切换布局、失败路径都先销毁旧实例再操作 canvas。
- 跨弹窗异步身份修复（验收修复）：`openOntologyGraphView` 不再从全新状态重建
  `requestEpoch`/`renderToken`，而是从上一个弹窗状态继续递增；关闭实体 A 后打开
  实体 B，A 的迟到请求或 ECharts 渲染无法通过 B 的当前身份判断，避免旧任务覆盖
  新弹窗（新增 5 项 reopen 单调性/不碰撞测试与 1 项 Runtime 契约回归测试）。
- 数据转换：`buildRadialGraph(data)` 在分析端保持纯函数，无向 BFS 分环、稳定
  `parentId`、样式沿用 `NODE_STYLE`；共享环形算法只从 `@boulderaitech/ontology-graph/radial`
  导入，分析仓库内无算法副本，共享包未修改。
- 主要文件：`docs/specs/ontology-radial-visualization.md`、
  `docs/specs/ontology-radial-visualization-acceptance-fixes.md`（新增 Spec）；
  `frontend/src/ontologyGraphModel.js`、`frontend/src/ontologyGraphViewState.js`（新增）、
  `frontend/src/ontologyGraphRendererHandle.js`（新增）、`frontend/src/runtime.js`、
  `frontend/src/workbench.css`；`frontend/tests/ontologyRadialGraphModel.test.mjs`、
  `frontend/tests/ontologyGraphViewState.test.mjs`、
  `frontend/tests/ontologyGraphRendererHandle.test.mjs`（新增）；`tests/test_regressions.py`。
- 验证：共享包 `npm test` 6 passed；前端单测 41 passed；`npm run build` 成功；
  `pytest tests/test_regressions.py -q` 215 passed（含新增契约测试）；
  `git diff --check` 通过。未部署、未发包。

### 2. 本体布局控件：自定义选择面板 + 键盘闭环 + 白色说明气泡 + 工具栏等高 + 下拉项去按钮边框（Spec + 实现 + 验收修复，已完成）

- 用户可见变化：本体子图弹窗工具栏将原来的“关系聚类可视化 / 语义环形可视化”两个并列
  按钮收敛为控件组“布局 [选择器 ▼]”：默认“关系聚类可视化”，可切换“语义环形
  可视化”，沿用 `cluster`/`radial` 状态值与原切换逻辑（复用已加载子图，不重新请求
  接口、不调 LLM、不写聊天历史）。选择器为页面自绘自定义 combobox + listbox（曾用
  原生 `<select>`，验收修复后移除）：点击或键盘打开自绘白色选项面板，选项为完整可点击
  行，当前项有选中态与勾选，hover/活动项浅蓝反馈；点击外部或关闭弹窗自动收起；busy
  时 trigger 禁用并自动收起面板，结束后恢复。
- 键盘闭环（本轮验收修复）：所有按键统一走 trigger 的纯键盘转换入口
  `handleOntologyLayoutPickerKey`，DOM 焦点始终留在 trigger，menu 不再承担需要焦点才
  能工作的 keydown 导航（菜单仅响应鼠标点击）；Enter/Space 打开或提交、ArrowDown/Up
  循环移动、Home/End 首末项、Escape 取消不提交、Tab 关闭菜单并按正常顺序离开；纯键盘
  可完成 cluster → radial → cluster，全程子图请求增量为 0。
- 可访问性：trigger 为真实 button（`role="combobox"`、`aria-haspopup="listbox"`、
  `aria-expanded`、`aria-controls`、`aria-activedescendant`）；option 使用稳定唯一 id
  （`ontology-layout-option-*`）、`role="option"`、`tabIndex=-1`；打开时
  `aria-activedescendant` 指向活动项、关闭时移除；`aria-selected`/`.is-selected` 只表示
  已提交布局，键盘临时活动项只反映为 `.is-active`，二者不混淆。
- 工具栏等高：layout trigger 与“重新布局”按钮统一为显式 `height:26px` +
  `box-sizing:border-box`（relayout 另设 `min-height:26px`、inline-flex 垂直居中），
  不依赖 transform/scale/负 margin；disabled 前后与 720px 以下换行后仍等高。
- 说明气泡（最终口径，问号入口已移除）：布局控件右侧不再存在 `?` 按钮与旧 Tooltip
  DOM/CSS/监听器；布局 trigger 悬浮、聚焦或键盘打开菜单均不显示说明。说明气泡只在
  下拉列表展开后鼠标悬浮具体 option 时出现：listbox 内唯一复用的
  `[data-graph-layout-option-tooltip][role="tooltip"]` 白色气泡（白底、深色文字、
  浅灰边框、8px 圆角、轻阴影、`max-width:280px`、`pointer-events:none`），默认显示在
  当前 option 右侧并带指向该 option 的箭头，右侧空间不足时自动翻转左侧；option/listbox
  leave、选择、Escape、Tab、外部点击、busy、关闭弹窗均隐藏，重开默认不残留；trigger 与
  option 均无原生 `title`。cluster 说明文案已更新为完整新句（“ForceAtlas2 是一种先进的
  力导向图布局，适合查看节点之间的关系聚类。”），radial 环形文案保持不变；两段说明只存于
  `ontologyLayoutOptions.js`。
- 实现：`frontend/src/ontologyLayoutOptions.js` 为布局名称与说明文案唯一来源；
  `frontend/src/ontologyLayoutPickerState.js` 提供 picker 开关/活动项/统一键盘转换/
  busy 纯状态转换；`frontend/src/ontologyLayoutOptionTooltipState.js`（新增）提供气泡
  显隐纯状态转换且不反向修改配置；`frontend/src/runtime.js` 只负责 DOM 渲染、事件、
  文案查询与定位（option 右锚 + `flip` 翻转 + dialog/视口钳制）；原生 select、旧双按钮
  及问号 Tooltip 的 DOM/CSS/监听器已清除。
- 主要文件：Spec 与证据包括 `docs/specs/ontology-layout-selector-white-tooltip.md`、
  `docs/specs/ontology-layout-selector-acceptance-fixes.md`、
  `docs/specs/ontology-layout-keyboard-and-toolbar-height-fixes.md`、
  `docs/specs/ontology-layout-option-hover-hints.md`（本轮新增，已完成）；
  `docs/test-evidence/ontology-layout-keyboard-height-red/green.txt`、
  `docs/test-evidence/ontology-layout-browser-acceptance.json` 与 `k1..k5-*.png`、
  `docs/test-evidence/ontology-layout-option-hover-hints-red.txt`、
  `docs/test-evidence/ontology-layout-option-hover-hints-green.txt`、
  `docs/test-evidence/ontology-layout-option-hover-browser-acceptance.json` 与
  `h1..h9-*.png`（本轮新增）。实现与测试：`frontend/src/ontologyLayoutPickerState.js`、
  `frontend/src/ontologyLayoutOptions.js`、`frontend/src/runtime.js`、
  `frontend/src/workbench.css`、`frontend/src/ontologyLayoutOptionTooltipState.js`（新增）、
  `frontend/tests/ontologyLayoutPickerState.test.mjs`、
  `frontend/tests/ontologyLayoutOptions.test.mjs`、
  `frontend/tests/ontologyLayoutOptionTooltipState.test.mjs`（新增）、
  `tests/test_regressions.py`；构建产物 `bi_agent/web/static/vendor/antd/*` 同步更新。
- 验证：本轮（option hover 提示）Red 退出码 1（前端 15 tests / 9 pass / 6 fail：气泡纯状态
  未实现 + cluster 旧文案；回归 -k ontology_layout 3 failed：问号 DOM/CSS/函数仍在、option
  气泡缺失）；Green 后前端单测 76 passed（picker 20 项、options 7 项、option tooltip 纯状态
  8 项及全部既有 66 项未减少）、`npm run build` 成功（workbench.js 1,283.49 kB）、共享包
  `npm test` 6 passed、`pytest tests/test_regressions.py -q` 218 passed（新增
  `test_ontology_layout_option_hover_tooltip_contract`）、`git diff --check` 通过；真实
  Chrome headless 152 验收：桌面 1440px 与窄屏 700px/460px——页面无 `?` 与旧 Tooltip，
  hover cluster option 显示新 ForceAtlas2 完整文案、hover radial 显示环形文案，气泡在
  option 右侧、窄屏自动翻转且不被 dialog 裁切，键盘闭环全程无视觉气泡，trigger 与
  “重新布局”计算高度均 26px、切换布局请求增量为 0。未部署、未发包。
- 下拉项去按钮边框与样式隔离（本轮最终口径）：布局下拉面板本身保留白底、浅灰外边框、
  8px 外层圆角与轻量阴影；面板内两个 option 改为无边框列表行——`border:0`、
  `outline` 仅 `:focus-visible`、默认 `background:transparent`、无 `box-shadow`、
  无独立白色按钮底板或卡片间距，行内 `border-radius:4px` 只用于 hover/活动整行底色；
  hover/`.is-active` 为整行浅蓝 `#eff6ff` + 蓝色文字，`.is-selected` 保留蓝色文字与
  勾选，点击区域仍覆盖整行。工具栏通用按钮规则由 `.ontology-graph-toolbar button`
  收窄为直属业务按钮 `.ontology-graph-toolbar > button`（含 `.active`/`:disabled`），
  另加菜单级重置 `.ontology-layout-menu .ontology-layout-option`，不使用 `!important`；
  trigger 仍为有边框的选择器外观（`1px` 边框 + `26px` 高），与无边框 option 明确区分。
- 实现与文件（本轮）：修改 `frontend/src/workbench.css`（作用域收窄 + 菜单级 option
  重置）、`tests/test_regressions.py`（新增
  `test_ontology_layout_option_borderless_contract`，12 组 subTest）；构建产物
  `bi_agent/web/static/vendor/antd/*` 同步重建。Spec 与证据：
  `docs/specs/ontology-layout-borderless-options.md`（本轮新增，已完成）、
  `docs/test-evidence/ontology-layout-borderless-options-red.txt`、
  `...-green.txt`、`...-browser-acceptance.json`、截图 `r1-*`、`g1..g4-*`。
- 验证（本轮）：Red 退出码 1——静态契约 `5 failed, 1 passed, 218 deselected`
  （通用后代按钮规则仍在、`> button` 收窄缺失、菜单级 option 重置缺失），真实浏览器
  计算样式两个 option 均为 `1px` 四边边框 + `7px` 圆角按钮卡片；Green 后前端单测
  76 passed、`npm run build` 成功、共享包 `npm test` 6 passed、
  `pytest tests/test_regressions.py -q` 219 passed（新增 borderless 契约方法，
  12 subtests 通过）、`git diff --check` 通过；真实 Chrome headless 152 验收
  （桌面 1440px、窄屏 700px）17/17 通过：默认 option 计算样式四边 `0px`、
  `box-shadow:none`、背景透明，hover/活动仅整行浅蓝无边框闪现，选中文字与勾选正常，
  trigger/重新布局均 26px，menu 外框与阴影保留，无“?”、无原生 title，hover option
  白色说明气泡正常。未部署、未发包。
- 窄屏 hover 证据修复（本轮最终口径，同条修订不新增）：早期一次性 `/tmp` 脚本生成的
  `g3-narrow-menu.png`/`g4-narrow-hover.png` 哈希相同且 `g4` 无气泡，属无效证据；
  已新增仓库内可重复验收入口 `scripts/verify_ontology_layout_borderless_ui.mjs`
  （自动启动本机 headless Chrome/Chromium，默认页面 8765 workbench，
  `WORKBENCH_URL`/`CHROME_BIN` 可覆盖，真实 DOM/鼠标/计算样式/矩形，任一断言失败
  非零退出）与证据契约测试 `tests/test_ontology_layout_browser_evidence.py`（11 项）。
  同一次运行重新生成 JSON 与 `g1..g4`：窄屏 700x900 真实 hover radial option 后
  Tooltip 可见——`hidden=false`、`display=block`、`visibility=visible`、
  `opacity=1`、`280x54`、rect `{402,140,682,194}`、完全位于视口内
  （`insideViewport=true`）、文案精确为环形说明、与 option 相邻且 `flip` 一致；
  鼠标移出 listbox 后恢复隐藏。新 `g3`/`g4` 哈希
  `9e81e86d…c95ba49` / `0b44fe2a…bc86c0`（不同），像素差分佐证 `g4` 新增白色气泡
  与浅蓝 hover 行。真实功能无缺陷，本轮未改 `runtime.js`/`workbench.css`；
  Red 证据契约 9 failed / 1 passed（退出码 1），Green 后该测试 11 passed、
  前端 76 passed、构建成功、共享包 6 passed、`pytest tests/test_regressions.py -q`
  219 passed、`git diff --check` 通过。未部署、未发包。
