# openchat-BI 变更记录（2026-08-20）

> 本文档只记录 2026-08-20 当天完成的最终变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、被回滚或未验证的事项不要写成已完成。

## 2026-08-20

### 分析数据源与 Structured Claims 可靠性修复

- 只有真实数据查询（`SQLRun`/`MetricDataQuery`）才会进入会话查询结果与 Claims；图表、表格等展示工具和元数据/本体工具不再成为后续分析的数据来源，也不再生成数据事实 Claim，避免“最新查询结果”被展示产物污染。
- reconciliation 只对明确声明 `parent_value`/`child_values` 且属于同一指标的结果配对；多查询交错或展示工具插入查询之间时仍能正确配对，不同指标的父子值不再误配。
- 关系工具（`RelationLookup`/`GraphContext`/`GraphExpand`）仅在输出包含明确边/路径证据时生成 Association Claim；空结果、工具错误、降级（方向/关系类型不可用）或零边证据的结果改为生成 `RELATION_MISSING` 披露，不再误报“存在关联路径”。
- 叙述数字校验放宽正常表达：`100` 与 `100.0`、`0.25` 与 `25%`、序号（第 2 步）、列表编号（1、2、3）、范围（1–2 条）、时间周期（第 3 季度、12 月）等不再被错误拦截；虚构业务数字仍会被阻止并要求重写。
- 主要文件：`bi_agent/reliability.py`、`bi_agent/web/session.py`、`tests/test_reliability.py`。

### 前端调试残留清理

- 移除 `frontend/src/runtime.js` 中的 `console.debug` 调试输出，并重新生成受版本控制的前端构建产物（`bi_agent/web/static/vendor/antd/workbench.js`）。
