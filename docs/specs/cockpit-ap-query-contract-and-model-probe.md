# Cockpit 已实现 AP 查询与模型回传兼容（2026-11-10）

## AP 查询范围

依据 `docs/亿纬锂能/bp_local_analysis_query_202611100938.csv` 提取 enabled=true 且 SQL 非空的登记项，发布资产为 `bi_agent/cockpit/assets/ap-query-capabilities.json`。资产包含 153 个登记项（107 个指标组合、46 个维度），保留 query_key、columns、filter_contract 与来源哈希，不携带 SQL、不连接数据库执行 SQL。

客户固定年度分析使用该登记资产生成查询计划，而不继续尝试未登记的组件指标组合。指标组合、维度、筛选字段和运算符必须匹配；不按编号前缀猜测别名，不删除不认识的筛选条件，不扩大统计范围。部分指标可由已登记子组合覆盖时，分别请求真实登记组合；未实现部分排除并记入限制与 `AP_QUERY_NOT_IMPLEMENTED` 诊断。

年度/月度计划使用每项登记自身的唯一业务日期字段及 BETWEEN 条件，不一律添加 YWLN_D044；缺少可确认日期、存在多个歧义业务日期或缺少必需筛选值的条目不自动使用。仅使用当前能确定完整请求协议的默认 `_` 组合，不猜测 YEAR/MONTH 特殊 tag 的传参方式。

查询计划去掉相同范围的冗余指标子集，交替安排汇总和维度切片，每环节最多 18 条。共同分析先选已登记的实际/目标销售额等全局口径最多三条，再从各环节选最多三条；独立取证，不依赖其他分析成功。取到多少分析多少，仍披露采样与未覆盖范围。

固定年度分析不再调用 PG 补查，即使环境曾显式开启旧 fallback。上游 AP 仍负责 SQL 执行。本次不修改继承的看板展示组件、展示指标请求、筛选 UI、现有历史结果或客户 env。

## DeepSeek 回传保护

没有新增模型名称名单或更名规则，没有改客户 model/base_url 配置。使用客户的 DeepSeek0731 名称作为兼容测试输入；已有供应商适配器负责处理 DeepSeek 协议，不能将 UI 的“是否展示思考”当作是否保留协议 reasoning 的开关。

- 保留真实 reasoning，即使本轮未开放新工具，也在历史工具轮次中原样回传。
- 团队适配器先发出内部完整 reasoning 块，再发出完整工具参数事件；运行时先提交包含 reasoning 的 assistant 状态，再向消费者发送 llm_response，避免事件消费中断造成协议状态丢失。
- 旧历史缺失真实 reasoning 时，只在本次出站投影中把该工具轮次转换为历史观察材料，保留工具 ID、参数和真实结果；不补造 reasoning、不覆盖历史、不重跑工具。
- 请求尚未开始流式输出时，遇到明确的 400 reasoning 缺失，可将历史工具轮次转换为观察材料后重试；若旧端点明确不支持 thinking/reasoning_effort，则去掉可选参数。两类修复各至多一次，不切换模型或地址。
- 流已经开始后不自动重试，避免重复输出或重复执行工具。无法修复的错误仍正常失败并保留旧发布卡片，不能伪报分析成功。

## 独立模型测试 API

`POST /api/cockpit/model/probe`，带部署前缀时为 `/api/ontology-agentic-analytics/api/cockpit/model/probe`。

```sh
curl -sS -X POST 'http://<服务器IP>:8765/api/cockpit/model/probe' \
  -H 'Content-Type: application/json' \
  -d '{"modelKey":"team-configured","toolRoundtrip":true}'
```

`modelKey` 可省略，默认使用服务当前模型配置；指定时只能选择服务已有模型，不能传 URL 或密钥。接口支持当前客户使用的 team/deepseek 适配器。

默认 `toolRoundtrip=true`：先让模型调用固定只读探测工具，再携带真实 reasoning 和工具结果请求最终响应，最多两个逻辑模型轮次；前述有限的请求前协议修复可能另有被拒绝的 HTTP 尝试。设置 `false` 仅做一个逻辑轮次的基础文本连通性检查。

返回 `ok`、`connected`、`toolRoundtrip`、`model`、`modelKey`、`phase`、`code`、`modelCalls`、`durationSeconds`，失败时可带 `upstreamStatus`。不返回密钥、原始 reasoning 或上游原始报错。只有整体通过才返回 HTTP 200；忙碌为 429、未配置为 503、模型连接或工具回传失败为 502，参数不合法为 422。

错误码包括 `MODEL_NOT_CONFIGURED`、`MODEL_AUTH_FAILED`、`MODEL_REASONING_PROTOCOL`、`MODEL_TIMEOUT`、`MODEL_RATE_LIMITED`、`MODEL_BUSY`、`MODEL_PROBE_TOOL_NOT_CALLED`、`MODEL_EMPTY_RESPONSE`、`MODEL_CONNECTION_FAILED`。`connected=true` 且 `toolRoundtrip=false` 说明首轮已连接，但完整回传没有通过。

接口有独立单并发保护，并遵守共享模型并发限制。探测请求使用局部 20 秒 SDK 超时和零 SDK 自动重试，不改变正常分析配置；不读取 AP、数据库、本体或业务数据，不创建分析任务或历史会话。只有显式调用才消费模型额度。

## 验证与交付

本轮以模拟响应覆盖 reasoning 保留/顺序、未知可选参数、旧工具历史、流中断不重试、事件输出前提交、登记组合筛选、日期口径、禁止 SQL 兜底及 API 成败语义。不批量调用真实模型、不访问客户 AP 或数据库。代码提交与推送不代表已部署或更新 tar。

自动回归：500 项 Python 测试、27 项子测试、107 项 Node 测试通过；`git diff --check` 通过。
