# Spec：本体子图跨弹窗异步身份碰撞修复

状态：待修复（TDD Red）
前置 Spec：`docs/specs/ontology-radial-visualization.md`

## 1. 缺陷与复现

`openOntologyGraphView()` 和 Runtime 打开路径每次使用全新状态，导致关闭 A、打开 B 后异步身份从相同小整数重新开始：

```json
{"oldEpoch":2,"newEpoch":2,"epochCollision":true,"oldToken":3,"newToken":3,"tokenCollision":true,"oldTokenAcceptedByNewState":true}
```

A 的迟到请求/ECharts 渲染可能通过 B 的“当前任务”判断并覆盖 B。现有测试只覆盖单次打开，未覆盖 `open A → close → open B`。

## 2. 目标与边界

- request epoch、render token 在同一 Runtime 生命周期内必须单调递增且不复用；
- reopen 清空旧 entity data、busy、strategy/layout，但不重置异步身份；
- 旧 request/render/finally 永远不能修改新弹窗；
- 保留现有 busy 锁、BFS、布局切换和幂等 kill/dispose。

不修改共享包、接口、图模型和无关功能；不发布、不 push、不建 MR、不部署。

## 3. 推荐最小实现

```js
export function openOntologyGraphView(previousState, entity) {
  const fresh = createOntologyGraphViewState();
  return {
    ...fresh,
    entity: entity ? { ...entity } : null,
    open: true,
    requestEpoch: (previousState?.requestEpoch || 0) + 1,
    renderToken: (previousState?.renderToken || 0) + 1,
  };
}
```

Runtime 必须传现有状态：

```js
ontologyGraphViewState = openOntologyGraphView(ontologyGraphViewState, normalized);
```

禁止继续传 `createOntologyGraphViewState()`。允许 generation 方案，但只有在最小方案不可行时使用，且所有 current/finish 判断必须包含 generation。

## 4. 状态不变量

重新打开后必须同时满足：

- `open=true`，entity 为新实体拷贝；
- `layout=cluster`、`strategy=context`、`data=null`；
- `requestBusy=false`、`renderBusy=false`；
- 新 epoch/token 大于 close 后的值；
- `epochA !== epochB`、`tokenA !== tokenB`；
- `isOntologyGraphRenderCurrent(B, tokenA) === false`；
- `finishOntologyGraphRequest(B, epochA)` 不解除 B busy；
- `finishOntologyGraphRender(B, tokenA)` 不解除 B render busy。

## 5. TDD

### Red

先扩展 `frontend/tests/ontologyGraphViewState.test.mjs`：

1. `open A → begin request/render → close A → open B`：B epoch/token 大于 close A 后的值；
2. A/B request epoch 不相等；用 epochA finish B 不解锁，用 epochB 才解锁；
3. A/B render token 不相等；tokenA 在 B 中不是 current，也不能 finish B；
4. reopen 重置 data、busy、layout、strategy、entity，但身份继续递增；
5. 连续执行 20 次 open/begin/close，全部 epoch/token 严格递增且无重复。

扩展 `tests/test_regressions.py`：

- Runtime 必须出现 `openOntologyGraphView(ontologyGraphViewState, normalized)`；
- 打开路径不得出现 `openOntologyGraphView(createOntologyGraphViewState(), normalized)`；
- open 从 previous state 推进 epoch/token；
- close/request/render 的 token-aware 判断仍保留。

Red 必须正常加载后因 old/new 身份相等而断言失败；import/语法错误不算 Red。

### Green

- open 重置业务状态但继承递增旧身份；
- Runtime open 传入现有 state；
- 不改变其他行为；
- 新旧测试全部转绿。

### Refactor

- 注释明确标识跨 modal 生命周期单调；
- 不引入随机 ID、时间戳或无关重构；
- 不减少、删除或放宽原测试。

## 6. 验收标准

| ID | 场景 | 结果 |
|---|---|---|
| AC-C1 | A 请求中关闭并打开 B | epoch 不同，A 不能进入 B |
| AC-C2 | A 环形加载中关闭并打开 B | token 不同，A 不能挂载 B |
| AC-C3 | A request finally 在 B 中执行 | B request busy 不解除 |
| AC-C4 | A render finally 在 B 中执行 | B render busy 不解除 |
| AC-C5 | reopen | 默认 cluster/context，data 空，控件可用 |
| AC-C6 | 连续 20 次 open/close | 身份严格递增、无重复 |
| AC-C7 | 原 busy 控制 | 三类控件锁测试通过 |
| AC-C8 | 原 renderer handle | kill/dispose 幂等测试通过 |
| AC-C9 | 原环形功能 | BFS、无边图和切换测试通过 |
| AC-C10 | 全量验证 | 包、前端、Python、构建、diff check 全通过 |

## 7. 验证

```bash
cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics/frontend
node --test tests/ontologyGraphViewState.test.mjs
node --test tests/ontologyGraphRendererHandle.test.mjs
node --test tests/ontologyRadialGraphModel.test.mjs
npm run build

cd /Users/sher/Boulderaitech/ontology-graph && npm test

cd /Users/sher/Boulderaitech/eimosp-ontology-agentic-analytics
.venv/bin/python -m pytest tests/test_regressions.py -q
git diff --check
git status --short
```

## 8. 完成定义

- 5 类跨 reopen 测试及真实 Red 证据齐全；
- AC-C1～C10 全部通过，复现脚本不再出现 collision；
- 原 36 项前端测试不得减少；
- 不修改共享包、历史会话、用户数据或无关功能；
- 不 commit、不 push、不建 MR、不发包、不部署。
