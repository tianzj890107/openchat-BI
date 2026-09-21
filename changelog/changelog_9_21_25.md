# eimosp-ontology-agentic-analytics 变更记录（2026-09-21 至 2026-09-25）

> 本文档记录 2026-09-21（周一）至 2026-09-25（周五）当周的最终变更，按周直接维护
> （2026-09-08 起 changelog 只按周维护，不再创建日报）。本文件于 2026-09-20（周日）
> 预建，当周发生实际修改后直接写入本文件并标注发生日期。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更

### 2026-09-21 · X360 流程定义接口接入：「行动 → 转督办」换真（已完成）

新增只读 X360 客户端，把「行动 → 转督办」的 `bpDefinitionId` 与责任人从 14 条硬编码
关键词表换成 X360 实时数据，并保留一键回退。

- **只读客户端**：新增 `bi_agent/x360/`（`__init__.py` + `client.py`），公开
  `X360ApiError` / `X360Activity` / `X360ProcessDefinition` /
  `X360ProcessDefinitionClient`。只有文档给出的两个 `GET`
  （`/api/gateway2/x360/v1/process-definitions/ai/key/{key}` 与 `.../ai/{id}`），
  无请求体、无任何写接口；ID 一律保持字符串；匹配分级「活动名 → 活动 code（大小写
  不敏感、ASCII 词边界）→ 任务名 → 任务 code」，任务命中返回其父活动、未命中返回
  `None`；`(base_url, selector)` TTL 缓存（`X360_CACHE_TTL_SECONDS`，0=每次回源）+
  失败冷却（`X360_FAILURE_COOLDOWN_SECONDS`）；所有失败（HTTP / 业务 / 非 JSON /
  超时 / 截断响应 / 结构异常）统一归一化成 `X360ApiError`，消息不含 token 与内部地址。
- **转督办解析**：`bi_agent/web/app.py` 新增 `_resolve_task_alert_target`，实现降级
  真值表全部 7 行；`bpDefinitionId` 来源只有三种——请求体显式传入 > X360 命中 > 遗留
  关键词表；响应新增 `source`（`request` / `x360` / `static_fallback` / `default`）、
  `activityName`、`bpDefinitionId`；责任人取命中活动的 `responsiblePerson`，为空才回落
  到 `TASK_ALERT_DEFAULT_ASSIGNEE`；非 `x360` 来源时活动字段一律为 `None`（不把关键词
  猜成活动名）；端点只解析一次，请求体字段集、422/409/502/504 与幂等行为全部不变。
- **口径**：按 API 文档默认取流程定义 ID（`data.id`），活动 ID 始终单独返回在
  `activityId`；`X360_BP_ID_LEVEL=activity` 一键切回活动 ID（纯配置，不需要改码或回滚
  发布）。
- **配置**：`X360_*` 十个变量进 `.env.example`、`Dockerfile`（非密默认值）与本地
  `.env`；`X360_AUTH_TOKEN` 属运行时密钥、`X360_BASE_URL` 属环境相关值，都不烤进镜像；
  默认值里不出现 mock 的 `MOCK_0728` / `2081949112647405570`。
- **文档**：`DEPLOYMENT.md`（task-alert 小节）、`API/智能分析Agent前端API.md` §11 与
  `API/系统接口调用与代码统计.md`（原「未接入 X360」结论作废）。
- **验收**：`tests/test_x360_process_definition_red.py` 由 32 failed / 3 passed 变为
  **35 passed**；`TaskAlertProxyTests` 20 条全绿（未配置 `X360_BASE_URL` 的用例走静态
  回退，行为与接入前逐字一致）；`test_ontology_mal_contract_red.py` 保持 69 passed /
  1 pre-existing failure 不变；评测 `smoke` 140/140、`adversarial` 62/62、
  `recorded-provider` 122/122、`regression` 570/570（P0 147/147）、`all` 570/570，
  known gap 0/0 不变；全量 `pytest -q tests` = **1119 passed / 1 failed / 25 skipped /
  1036 subtests passed**（唯一失败是与本批无关的既有矛盾断言）。
- **红测文件回填 1 处（如实记录）**：`_Harness.setUp` 增加一行环境注入
  （`self.patch_env()`）。原因：生产客户端只从环境变量读 `X360_BASE_URL`，而该 harness
  从不注入，导致 9 条只调用 `from_env()` 的用例对**任何**正确实现都会因「未配置」
  （Spec §5.8 第一/二行）而失败；未改动任何断言、用例名、期望值或用例数量
  （sha256 `eef1105e…` → `3769c88a…`，diff 为纯新增 3 行）。
- **未结清（上线前必须结清，Spec §10）**：`bpDefinitionId` 到底要哪一级 ID 的上游书面
  确认、鉴权方式、生产流程定义 KEY/ID、`responsiblePerson` 取值域、是否需要任务级督办、
  `履约单` 的真实归属。未结清前生产保持现状（`X360_BASE_URL` 留空 = 未接入，或已接入时
  `X360_BP_ID_LEVEL=activity`）。
- 未部署、未重启服务、未创建 MR/tag/Release、未改动 v0.1.9 与版本号、未读取真实凭据；
  live / live-canary 未运行。
