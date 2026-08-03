# openchat-BI 变更记录（2026-08-03 至 2026-08-07）

> 本文档记录本项目在本周内完成的最终用户可见功能变化。

## 维护规则

- 每次发布或一组相关修改按日期追加，不记录单个操作步骤或中间尝试。
- 每条记录只描述相对于上一版本的最终用户可见差异；同一功能的多次调整合并为一条。
- 每条记录至少说明：用户可见变化、涉及页面、主要文件。
- 不记录重启、部署、文件同步或浏览器刷新等运行操作。

## 2026-08-03

### 1. 新对话欢迎区与空分析 SOP

- 新开智能分析对话中的三个示例问题统一为 8px 圆角，和工作台其他可点击提示保持一致。
- 即使尚未发送问题也显示折叠的“分析 SOP”入口；展开后提示“开始一轮智能分析后，这里会显示本次对话的六步执行进度”，开始分析后自动替换为实时进度和 ThoughtChain 步骤。
- 页面：智能分析新对话欢迎区、对话区顶部。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 2. 任务清单联动看板定位

- 点击任务清单中的任一用户提问时，对话区定位到对应用户问题，看板同时定位到该轮首个可见分析结果；看板已隐藏的用户问题卡片不再作为滚动目标。
- 页面：智能分析、报表分析任务清单、对话区和右侧看板。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/index.html`。

### 3. 本体命中记录与本体内容完整性

- 智能分析过程现在可以识别本地和远程本体常见编码（指标、术语、维度、活动、流程、规则及元模型关系），远程本体中不在本地 Excel 回退文件里的命中项也会保留在本体内容和系统调用记录中。
- 本体内容接口补充返回业务属性、实体关系、维度、流程和本体元模型关系，不再只返回基础业务对象和指标集合。
- 主要文件：`bi_agent/web/session.py`、`bi_agent/web/app.py`、`tests/test_regressions.py`。

### 4. 团队模型网关接入

- 默认模型提供商切换为团队 OpenAI-compatible 网关，默认模型为 `direct-deepseek-v4-flash`。
- 团队网关通过 `TEAM_API_KEY`、`TEAM_BASE_URL`、`TEAM_MODEL` 和 `TEAM_MODELS` 配置；模型选择器会展示团队网关中的全部候选模型，并在额度或限流时按配置顺序自动切换。
- 原有 Qwen、Anthropic 和 DeepSeek 提供商仍保留，可通过模型选择器或环境配置切换。
- 主要文件：`bi_agent/llm/provider_team.py`、`bi_agent/llm/provider.py`、`bi_agent/llm/registry.py`、`bi_agent/llm/runtime_config.py`、`bi_agent/web/app.py`、`bi_agent/web/static/app.js`。

### 5. 设置页控件尺寸与圆角统一

- 模型参数页的“恢复默认”“返回”“保存”按钮统一高度和内边距，并与模型、最大输出长度和 API 密钥输入框统一采用 8px 圆角。
- 数据源、本体适配、角色选择、记忆管理和个人账号设置页同步使用同一套圆角控件样式，避免不同设置页面出现直角/小圆角混用。
- 页面：模型参数及全部设置页。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
