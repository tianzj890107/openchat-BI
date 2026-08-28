# openchat-BI 变更记录（2026-08-28）

> 本文档只记录 2026-08-28 当天完成的最终变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。

## 2026-08-28

### 请求生命周期终态一致性修复（SSE 中断与行动补写悬空 Tool）

用户可见变化：
- SSE 流在没有后端明确 `done` 时结束（代理/Nginx 截断、浏览器断网、后端异常退出、
  残缺 JSON、用户中断、被新请求取代），不再被伪装成成功：界面按“生成中断”处理，
  已显示的正文保留但明确提示“连接中断，本轮内容可能不完整”，不清算 SOP、不添加
  导出按钮、不保存为已完成回答、不自动重试；只有显式收到后端 `done` 才执行成功
  终态（SOP 完成、导出按钮、保存）。
- 同一 turn 重复 `done` 不再重复保存或重复添加导出按钮；已经以 error /
  session_superseded / 中断结束的 turn，迟到 `done` 不会把它翻转为成功。
- 旧请求的流被新请求取代后保持静默：不会清理新请求的 busy、不会删除新请求的加载
  卡、不会保存或推进新请求的数据，也不会在 EOF 时向新请求注入中断提示。
- 行动建议补写阶段（action repair）模型若返回工具调用：工具不执行、不出现在前端
  `llm_response` 的 `tool_uses`（恒为空）、不产生悬空 Tool 卡片、不写入会话上下文
  和历史；只保留纯文本继续有效性检查。补写连续只返回工具时按既有上限结束并给出
  “交付不完整”提示，已有根因回答仍然交付，不收紧任何输出门禁。
- HTTP 409/429 拒绝请求时，清理本轮“思考中…”占位卡并恢复输入框可操作状态，不额外
  创建错误卡。

实现方式：
- 前端新增纯函数 `frontend/src/streamTerminal.js`（`classifyStreamEof`）：EOF 时按
  “stale / terminal / interrupted” 分类，普通 EOF 一律 `interrupted`，绝不合成
  `done`；`streamResponse` 增加 stale 跟踪（request sequence + turn_id），并在 EOF
  时复核 sequence 防止旧流污染新请求。
- 前端新增 `stream_interrupted` 终态分支：清理 loading / cursor / 空白占位，提示
  中断，不执行成功侧副作用；`done` 分支增加 `lastDoneTurnId` 去重与
  `failedTurnIds` 防迟到 `done` 翻转；模式切换中止的旧流通过递增请求序号保持静默。
- 后端 `bi_agent/web/session.py` 行动补写阶段的 `llm_response` 事件 `tool_uses`
  固定为空数组，工具名（不含 SQL/输入）仅记内部 warning；补写内容依旧只提交文本
  与 thinking，不把工具写入消息历史。

主要文件：`frontend/src/streamTerminal.js`（新增）、`frontend/src/runtime.js`、
`bi_agent/web/session.py`、`bi_agent/web/static/vendor/antd/workbench.js`、
`tests/test_regressions.py`。

测试：新增 EOF 分类纯函数（node）、SSE 终态源码行为断言、action repair 三类生成器
测试（仅工具不执行且 tool_uses 为空、文本+工具只取文本、连续仅工具达到上限后非阻断
结束）；全量 Python 测试共 272 项通过；前端生产构建通过；`git diff --check` 通过。

### 全局交付规范：默认 commit + push，不部署

用户可见变化：
- 仓库级执行规范统一为“修改 → 本地验证 → 复查 Git diff → commit → push 当前远程
  分支 → 结束”，不再默认进入部署阶段。
- 默认禁止部署服务器、SSH/rsync/scp 同步、重启 systemd 或进程、更新生产/测试运行
  目录、调用部署脚本、触发发布流水线、修改服务器 `.env` 或数据。
- 只有用户在当前任务中明确说“部署”“发布到服务器”时才允许部署；历史任务的部署授权
  不延续；“完成”“修复”“验收通过”“继续做”等表述不构成部署授权；用户明确说“不部
  署”时禁止任何服务器写操作和服务重启。
- push 前必须完成合理验证；禁止 force push；禁止提交 secret、`.env`、用户数据和
  运行产物；若 push 会触发仓库已有自动部署流水线，先停止并报告，不得通过 push 间
  接部署。

实现方式：
- 根目录 `AGENTS.md` 新增“Git 推送与部署规则”小节作为仓库级永久规范。
- `debug.md` 全面修订：顶部闭环、默认交付、完成条件、最终报告模板和执行原则总结
  均改为 commit + push 且默认不部署；部署相关章节全部明确标注“仅当用户当前任务明
  确要求部署时适用”。
- 检查确认仓库无 `.github/workflows`、GitLab CI、Jenkinsfile、deploy hooks 等自动
  部署触发配置，普通 push 不会自动部署。

主要文件：`AGENTS.md`、`debug.md`。

验证：`git diff --check` 通过；全局扫描确认残留命中均为条件性部署说明或历史事实，
无“默认自动部署”类规范指令。
