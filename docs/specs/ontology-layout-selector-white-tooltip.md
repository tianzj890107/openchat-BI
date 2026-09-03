# Spec：本体可视化布局下拉框与白色说明气泡

状态：已完成

> 最终产品口径更新（2026-09-03）：本 Spec 中的“布局 [选择器 ▼] (?)”及 `?` 说明入口已被
> `docs/specs/ontology-layout-option-hover-hints.md`（已完成）取代：布局控件右侧不再存在 `?`，
> 说明气泡只在布局下拉列表展开后鼠标悬浮具体 option 时显示。cluster 提示文案同时更新为：
> “ForceAtlas2 是一种先进的力导向图布局，适合查看节点之间的关系聚类。”
> 以下历史正文保留作为实现过程记录，不再代表最终产品口径。

## 1. 背景与目标

智能分析 Agent 当前把“关系聚类可视化”和“语义环形可视化”展示为两个并列按钮，与智能建模 Agent 的布局选择方式不一致。

本次统一为以下结构：

```text
布局  [关系聚类可视化 ▼]  (?)
```

- “布局”为固定标签；
- 两种可视化布局收进同一个下拉框；
- `?` 表示当前所选布局的说明；
- 鼠标悬浮或键盘聚焦 `?` 时显示白色说明气泡，不使用黑色原生提示框；
- 只改变控件呈现和说明方式，不改变图布局算法、接口或默认行为。

## 2. 范围与统一口径

下拉框只允许两个选项，并沿用智能分析 Agent 已有状态值：

| value | 显示名称 | 说明文案 |
|---|---|---|
| `cluster` | 关系聚类可视化 | ForceAtlas2 力导向布局，适合查看节点之间的关系聚类。 |
| `radial` | 语义环形可视化 | 以当前锚点为中心，按照最短关系距离由内向外分环排列。 |

要求：

- 默认值仍为 `cluster`；
- 不把 `cluster` 改名为建模 Agent 使用的内部值 `network`；
- 不照搬建模 Agent“按业务对象、逻辑实体、业务属性分层”的说明，因为分析 Agent 当前环形算法按锚点最短关系距离分环；
- 页面、测试和可访问名称只使用表格中的两组名称，不再出现第三套“布局模式”等零散概念。

## 3. 交互与 DOM 契约

推荐结构如下；允许标签名不同，但 `data-*`、角色和行为必须等价：

```html
<div class="ontology-layout-selector">
  <span class="ontology-layout-label">布局</span>
  <select data-graph-layout-select aria-label="布局">
    <option value="cluster">关系聚类可视化</option>
    <option value="radial">语义环形可视化</option>
  </select>
  <button
    type="button"
    data-graph-layout-help
    aria-label="当前布局说明"
    aria-describedby="ontology-layout-tooltip"
  >?</button>
  <div id="ontology-layout-tooltip" role="tooltip" hidden></div>
</div>
```

行为要求：

1. 下拉框值始终与 `ontologyGraphViewState.layout` 同步。
2. 用户改变选项时调用已有布局切换路径；不得重新请求本体子图接口。
3. 请求或渲染 busy 时禁用下拉框，沿用现有三类控件锁定规则；busy 结束后恢复。
4. `?` 的气泡内容始终对应当前选项；切换布局后立即更新。
5. `mouseenter` 或 `focus` 打开气泡；`mouseleave`、`blur`、`Escape` 关闭气泡。
6. 关闭弹窗时同时关闭气泡；重复打开弹窗不得叠加监听器或创建多个气泡。
7. `?` 必须使用可聚焦的真实按钮，不使用仅有 `role="img"` 的 `span`。
8. `?` 上禁止设置 `title`，避免浏览器同时显示不可定制的黑色原生提示。
9. 气泡必须带 `role="tooltip"`，帮助按钮通过 `aria-describedby` 关联它。

## 4. 白色气泡视觉规范

白色气泡不得继承现有黑色 Tooltip 主题，至少满足：

- 背景：`#fff`；
- 文字：`#334155` 或更深，正文对比度不低于 4.5:1；
- 边框：`1px solid #e2e8f0`；
- 圆角：`6px`～`8px`；
- 阴影：轻量阴影，如 `0 6px 18px rgba(15, 23, 42, .12)`；
- 最大宽度：`280px`，允许自动换行；
- 箭头与气泡同为白色，并保留同色系边框；
- 层级高于本体弹窗内容，且靠近视口边缘时不得被弹窗裁切；
- `?` 保持建模 Agent 的浅灰圆形风格，并提供清晰的 `:focus-visible` 焦点环。

气泡定位可采用 CSS 或小型原生 JS，不为此引入新的 UI 框架依赖。

## 5. 推荐实现边界

新增纯配置模块 `frontend/src/ontologyLayoutOptions.js`，作为名称与说明文案的唯一来源：

```js
export const ONTOLOGY_LAYOUT_OPTIONS = Object.freeze([
  {
    value: "cluster",
    label: "关系聚类可视化",
    hint: "ForceAtlas2 力导向布局，适合查看节点之间的关系聚类。",
  },
  {
    value: "radial",
    label: "语义环形可视化",
    hint: "以当前锚点为中心，按照最短关系距离由内向外分环排列。",
  },
]);

export function ontologyLayoutOption(value) {
  return ONTOLOGY_LAYOUT_OPTIONS.find((option) => option.value === value) || null;
}
```

Runtime 从该模块生成下拉选项和气泡内容。删除原来的两个 `[data-graph-layout]` 按钮及其 active 状态同步逻辑，改为单一 `[data-graph-layout-select]`。不得保留两套并行控件或重复文案常量。

## 6. TDD

### Red：必须先写并运行失败测试

新增 `frontend/tests/ontologyLayoutOptions.test.mjs`：

1. 断言选项恰好为 `cluster`、`radial`，顺序固定；
2. 断言两组选项名称和说明文案与第 2 节完全一致；
3. 断言 `ontologyLayoutOption()` 对合法值返回对应对象，对未知值返回 `null`；
4. 断言导出的数组和选项不可被意外修改。

扩展 `tests/test_regressions.py` 的本体子图 UI 契约：

1. 必须存在“布局”标签、`[data-graph-layout-select]`、两个 option 和 `[data-graph-layout-help]`；
2. 必须存在唯一的 `[role="tooltip"]`，帮助按钮具备 `aria-describedby`，且帮助按钮没有 `title`；
3. 不再存在 `data-graph-layout="cluster"`、`data-graph-layout="radial"` 两个旧按钮；
4. change 事件进入已有 `switchOntologyGraphLayout(value)`，且该事件路径不调用 `loadOntologyGraphData()` 或 fetch；
5. state → DOM 同步会写入 select value；busy 同步会禁用 select；
6. tooltip 文案来自 `ontologyLayoutOptions.js`，Runtime/CSS/模板中不得再复制两组说明常量；
7. hover/focus 打开，leave/blur/Escape 关闭，弹窗关闭也会关闭；
8. CSS 契约包含白色背景、深色文字、浅色边框、阴影、箭头和 `:focus-visible`；
9. 更新旧测试对双按钮和 `querySelectorAll("[data-graph-layout]")` 的断言，使其验证等价的单下拉框契约；不得删除或放宽 busy、BFS、异步 token、renderer dispose 等原有断言。

Red 的有效证据必须是：测试可正常加载，并因当前仍为“双按钮、无白色自定义气泡”而断言失败。import 错误、语法错误、路径错误不算 Red。记录失败测试名和关键断言。

### Green

- 实现唯一配置模块、下拉框、帮助按钮和白色气泡；
- 复用原 `switchOntologyGraphLayout()`、busy 锁和状态同步；
- 删除被替代的按钮 DOM、监听器、active CSS 与重复文案；
- 仅做使新增及既有测试通过的最小修改。

### Refactor

- 将选项数据、DOM 渲染和气泡显隐职责分开；
- 确保重复开关弹窗不会重复绑定事件；
- 不使用 `innerHTML` 注入说明文案；
- 不引入 Ant Design、React、第三方 Tooltip 或其他新依赖；
- 不修改图算法、共享 `ontology-graph` 包、后端接口或历史会话。

## 7. 验收标准

| ID | 场景 | 预期结果 |
|---|---|---|
| AC-L1 | 打开本体子图 | 显示“布局 + 下拉框 + ?”，默认关系聚类 |
| AC-L2 | 展开下拉框 | 只显示两种规定布局，无并列旧按钮 |
| AC-L3 | 选择语义环形 | 使用现有数据完成环形重排，不发新请求 |
| AC-L4 | 切回关系聚类 | 使用现有数据完成聚类重排，不发新请求 |
| AC-L5 | 悬浮 `?` | 显示当前布局的白底深色说明气泡 |
| AC-L6 | 键盘聚焦 `?` | 显示同一气泡，按 Escape 可关闭 |
| AC-L7 | 切换布局后再次查看 | 气泡文案随当前选择更新 |
| AC-L8 | 请求或渲染中 | 下拉框禁用，完成后恢复且状态一致 |
| AC-L9 | 重复开关弹窗 | 无重复 Tooltip、重复监听器或旧内容闪现 |
| AC-L10 | 回归 | BFS、跨弹窗 token、renderer 释放和既有测试全部通过 |

## 8. 验证命令

```bash
cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics/frontend
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

## 9. 完成定义

- 有可复核的 Red → Green 记录；
- AC-L1～AC-L10 全部通过；
- 前端和 Python 原测试数量不得减少；
- 构建产物与源码一致；
- 只修改本任务所需文件，不覆盖当前工作区其他未提交修改；
- 不修改共享包，不删除历史会话；
- 不部署、不创建 MR、不直接推送 `main`。
