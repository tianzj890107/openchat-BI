# openchat-BI 变更记录（2026-08-24）

> 本文档只记录 2026-08-24 当天完成的最终变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。

## 2026-08-24

### Structured Claims 最终答案去重

- 修复 ChatBI 在存在 Structured Claims 时同一轮重复展示多版“结论 / 根因分析 / 行动建议”的问题：此前后端在 Claim 校验前就把每版候选终稿的 `text_delta` 发给前端并写入会话历史，校验失败后追加内部提示让模型重写，导致第一版、第二版、第三版结论和行动建议同时可见并进入历史（线上会话 `f505791c` 即出现“结论”13 次、“行动建议”7 次）。
- 现在存在 Structured Claims 时，无工具调用的回复被视为“候选终稿”：文本增量在后端缓冲，先注入 Structured Claims 上下文，再逐版独立执行 `validate_claims`（只校验当前候选、不再拼接整轮旧草稿）；校验通过后才一次性提交可见 `text_delta`、`llm_response` 并持久化，被拒绝的草稿既不显示也不入库；连续两次校验失败仍正常发出 `answer_blocked` 与 `done`。
- 前端同步清理被丢弃候选留下的空“思考中…”气泡，避免对话流出现幽灵占位；无 Claims 的普通回答仍实时流式输出，工具调用、表格/图表卡片、AskUser 和 `action_recommendations` 行为不变。
- 影响范围：有 Structured Claims 的分析轮次（含历史会话恢复与看板结论卡片）。主要文件：`bi_agent/web/session.py`、`frontend/src/runtime.js`、`bi_agent/web/static/vendor/antd/workbench.js`、`tests/test_regressions.py`。

### Team 模型目录与默认模型

- 从团队 LiteLLM 网关实时获取 28 个可见模型，并逐一执行最小对话请求验证；ChatBI 的模型选择列表更新为其中 24 个已验证可用模型，排除未路由、上游鉴权失败或被上游拒绝的条目，避免用户选中后才发现无法调用。
- Team provider 的默认模型保持为 `Qwen/Qwen3-80B-AWQ`，同步确认本地环境、环境示例和部署文档与该默认一致；经 ChatBI Team provider 实际流式调用验证，该默认模型可正常返回。
- 已发布到测试服务器 `f08a67b` release，原位更新 Team 模型环境配置并重启 ChatBI；线上健康检查正常，`/api/config` 返回 24 个 Team 模型且当前模型为 `Qwen/Qwen3-80B-AWQ`，服务器环境中的实际模型请求也已验证通过。发布前已备份本次覆盖的代码、文档和 `.env`，未触碰历史会话、上传、图表、日志和数据库。
- 影响范围：设置页模型选择、新部署的默认模型与 Team 网关配置。主要文件：`bi_agent/llm/registry.py`、`.env.example`、`.env`、`DEPLOYMENT.md`。
