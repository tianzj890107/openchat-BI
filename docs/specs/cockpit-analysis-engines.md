# Cockpit 分析路线联调与统一上线

2026-10-23。用户确定：两种路线仅在联调阶段保留；比对后所有AI插槽统一使用一个技术路线。
本轮优先实现主服务效果验证，不新增常驻服务，也不部署。

## 执行边界

| 路线 | 执行器 | 数据 | 输出 |
| --- | --- | --- | --- |
| main（默认） | 主服务既有WebSession.generate_turn | 主服务当前本体库与数据库，使用同一套build_source_executors | 主服务已提交正文、结构化claims、路由与工具轨迹；展示层不再调用模型改写 |
| standalone（联调） | 既有有限轮次工具循环 | 原型／演示数据，或指定main任务的服务端冻结证据 | compact-v1结构化风险、原因、建议；不自动切换到main |

前端12个插槽共用一个全局engine选择，不允许每个插槽自行选择路线。
当前主服务展示适配直接展示原始交付，目的是评估主服务实际质量；暂不从正文猜测责任人、期限、根因ID。
缺少结构化措施时不允许自动创建任务令草稿。

## 接口与入口

- 原接口保留：`POST /api/cockpit/analyses`，增加 `engine=main|standalone`。旧调用不传engine时保留standalone兼容，仅供联调；上线锁定main后该类旧请求会被拒绝。
- 主服务请求：`engine=main, source=service`；支持period、department、repositoryId、filters、clarifications、chartSnapshotId。
- filters目前由任务API或冻结基线传递；交付AP筛选器尚未自动映射，普通页面仍明确按2025-10／全产品部调用，界面披露未联动。
- 服务端核对repositoryId，拒绝与当前配置不一致的本体库；浏览器不能传查询端点或任意证据正文。
- 主服务创建独立临时会话，复用原有准入、会话租约、心跳、取消、恢复、工具运行时和交付校验。
  临时会话与用户聊天隔离，完成后只回收内存对象；不重置或删除会话／用户数据。
- 原聊天SSE与Cockpit共用 `_turn_execution_scope`。后台执行仍经过主服务原有资源控制。
- 8877如果仅安装独立router，main请求返回503，不伪装成主服务执行，也不静默降级。
- `GET /api/cockpit/engines` 返回全局默认路线、是否开放对照及执行器接入情况。
- 历史支持 `GET /api/cockpit/analyses?engine=main|standalone`；引擎、上下文、契约版本参与scope。
- main的数据源指纹不是数据库快照，因此暂不复用main已完成任务；同一进行中任务和当前页面内请求仍去重。
- main增加 `limited`、`needs_input`终态。待确认问题保留主服务AskUser内容，补充口径后新建任务，
  不伪装成已完成根因验证。失败不展示中间模型草稿。
- 执行信息记录durationSeconds、modelRounds、工具调用、provider返回的usage和路由；不把usage当作实际账单。

在已正确配置的主服务入口访问：

- `/cockpit/analysis?id=1&engine=main`：优先查看主服务效果。
- `/cockpit/analysis?id=1&engine=standalone`：原型演示对照，不能与真实数据直接比较业务数字。
- 页内Tab跳转保留全局engine；main按可见插槽按需执行、前端串行排队，不预取全部五个环节。

## 同批材料对照

先完成main任务，再由独立路线读取该任务的冻结证据：

```json
{
  "id": 1,
  "engine": "standalone",
  "source": "service",
  "stage": "shipment",
  "period": "2025-10",
  "department": "全部产品部",
  "baselineAnalysisId": "主服务已交付任务的32位ID"
}
```

服务端验证基线引擎、状态、身份标识、环节、期间、部门、筛选条件和本体库；没有业务证据的受限基线返回409。
从存储读取并复制证据后生成内容哈希，不能由前端伪造或覆盖原始任务。
查询行最多24条，每行超过8000字符则不进入材料包，必须披露抽样限制；原始行标为causeSupport=false，
独立模型只能据此形成待验证假设，不能仅凭引用存在就声称已验证根因。
主服务有证据时，插槽提供“用同一冻结证据对照独立路线”入口并定位基线环节。

此方式比较同批材料的归纳质量与成本，不代表两套完整取数／规划流程的公平竞速；主服务可以有额外调查。
当前普通图表仍来自交付AP快照，尚未与主服务实时数据统一，界面明确标注，不能声称已完成同源对账。
真实销售／发货指标映射和图表查询适配仍需真实数据联调确认，不会用采购指标替代销售指标。

## 上线收口（必须）

联调：`COCKPIT_COMPARISON_ENABLED=true`；默认 `COCKPIT_ANALYSIS_ENGINE=main`。
选型后：设置 `COCKPIT_COMPARISON_ENABLED=false`，全站仅允许配置的一个engine，后端拒绝其他路线请求。
前端忽略试图切换引擎的URL参数；无按插槽混用、无失败后隐式切换。

若主服务效果满足要求，全部AI插槽直接使用主服务入口，静态站代理指向该服务，不再运行8877独立分析服务。
本次没有实施上述代理切换或停服；部署和停服必须获得新的明确授权。

## 验证

- 自动化覆盖真实WebSession路由与AskUser、真实主服务API准入和用户会话隔离、候选草稿拒绝交付、
  缓存隔离、全站引擎锁定、冻结基线权限／范围、原始行禁止升级为已验证根因。
- 本地真实发货任务约32.8秒、9轮模型响应、10次工具调用，经过DIAGNOSTIC_ANALYSIS路由和
  Ontology-SemanticQuery、ListBusinessObjects、数据工具及最终交付。
- 本机无法解析demo2.eimos.com，本体／分析网关未返回业务数据；最终为limited，无根因或建议伪造。
  这验证执行链和限制行为，不能据此宣称真实业务分析正确率或正常网络下的耗时。
- 浏览器回看上述真实受限任务，主服务插槽显示原始受限正文与同源差异标注，没有组件错误；回看未触发额外模型请求。
- 后续应评估失败时重复探测、上下文成本和原始正文长度；本轮没有复制提示词绕过主服务流程以追求短输出。
