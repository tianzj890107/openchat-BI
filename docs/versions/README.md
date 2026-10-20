# 版本历史

正式版本说明按版本号独立维护。工程变更记录只按周维护，统一写入
[changelog](../../changelog/) 下的当前周文件（如 `changelog_9_7_11.md`），
不再创建日报。

- 当前版本：`ontology-v0.1.3`
- 当前 tag 与 Release：`ontology-v0.1.3`（指向定版 commit `a805a66`）、`ontology-v0.1.2`
  （指向定版 commit `3c4de1e`）、`ontology-v0.1.1`
  （指向定版 commit `c82221f`，2026-10-15 事后补建）、`ontology-v0.1.0`（指向定版 commit
  `74fca80`）与 `ontology-v0.0.1`–`ontology-v0.0.10`（共 14 个，均已创建 release，见根
  [README 发布清单](../../README.md)）
- 版本规则：[语义化版本与正式发布规范](./versioning-policy.md)
- 分支模型与 PR 合并流程：[Git 分支与合并工作流规范](../git-branch-workflow.md)
- 版本号由变更性质决定，不按日期机械递增；commit、push、部署不自动触发版本升级。
- 2026-09-29 起版本族由 `v0.1.x` 切换为 `ontology-v0.0.x`：`v0.1.0`–`v0.1.9` 按顺序
  映射为 `ontology-v0.0.1`–`ontology-v0.0.10`，tag 指向的原定版 commit 未变；映射表与
  一次性授权见 `docs/specs/ontology-version-rename-and-rebuild.md`。
- 原本只有 tag、没有版本文档的版本（原 `v0.1.3`–`v0.1.7`），已在本次切换中补齐为
  `ontology-v0.0.4`–`ontology-v0.0.8`，10 个版本现在都有独立版本文档。

| 版本 | 日期 | 状态 | 说明 |
| --- | --- | --- | --- |
| [./ontology-v0.1.3.md](./ontology-v0.1.3.md) | 2026-10-20 | 正式版 / 当前版本 | 主服务内置远程 MCP、Fuxi 零本地凭据接入、16 个受控分析工具、`CanvasGenerate` Artifact URL 交付、demo2 代理与语义检索快路径修复，`ontology-v0.1.2` → `ontology-v0.1.3` PATCH 收口 |
| [./ontology-v0.1.2.md](./ontology-v0.1.2.md) | 2026-10-15 | 正式版（历史版本） | 分析逻辑剥离包 `ontology-analytics-skill` 收尾（真实工具运行时、CanvasGenerate 整页交付）、多步分析中文过程播报、取数证据与双环境对比归档、`20260727` 归档改为临时分支 → `master`，`ontology-v0.1.0` → `ontology-v0.1.2` PATCH 收口 |
| [./ontology-v0.1.1.md](./ontology-v0.1.1.md) | 2026-10-08 | 正式版（历史版本） | 分析逻辑剥离包 `ontology-analytics-skill`：路由 → L1–L5 SOP → 五道闸门、真实工具运行时 `tools/`（17 个真实工具、凭据外置），`ontology-v0.1.0` → `ontology-v0.1.1` PATCH（2026-10-15 补建 tag 与 Release） |
| [./ontology-v0.1.0.md](./ontology-v0.1.0.md) | 2026-09-29 | 正式版（历史版本） | PDT 数据湖切换 PG 引擎端到端修复、本体/MAL 与元数据契约迁移、会话回收站与匿名读取面收敛、X360 流程定义集成，`ontology-v0.0.x` → `ontology-v0.1.0` MINOR 收口 |
| [./ontology-v0.0.10.md](./ontology-v0.0.10.md) | 2026-09-17 | 正式版（历史版本） | 分析 Agent 黄金评测集扩展到 482 条并新增 recorded-provider 回放层、GitLab CI/CD 接入项目 runner、产品版本号统一升级 |
| [./ontology-v0.0.9.md](./ontology-v0.0.9.md) | 2026-09-17 | 正式版（历史版本） | 部署与运行配置固化、`.env` 增量同步契约、字面 IP 与周 changelog 规则（由误发的 `v0.2.0` 更正而来） |
| [./ontology-v0.0.8.md](./ontology-v0.0.8.md) | 2026-09-08 | 正式版（历史版本） | 可配置应用 Base Path；发布主线收口到 `master`，changelog 收敛为按周维护 |
| [./ontology-v0.0.7.md](./ontology-v0.0.7.md) | 2026-09-07 | 正式版（历史版本） | 轻量结构化 cognitive policy 决策记录（`cognitive_policy` SSE 快照） |
| [./ontology-v0.0.6.md](./ontology-v0.0.6.md) | 2026-09-07 | 正式版（历史版本） | 多实例共享并发协调与 fencing 租约（可选 Redis，默认 local 行为不变） |
| [./ontology-v0.0.5.md](./ontology-v0.0.5.md) | 2026-09-07 | 正式版（历史版本） | 轻量 Recovery 状态机与 checkpoint、可重试恢复 |
| [./ontology-v0.0.4.md](./ontology-v0.0.4.md) | 2026-09-07 | 正式版（历史版本） | Tool Runtime 执行边界：执行标识、超时、幂等与 stale-result 拒绝 |
| [./ontology-v0.0.3.md](./ontology-v0.0.3.md) | 2026-09-03 | 正式版（历史版本） | 本体子图语义环形可视化与布局控件体验收敛（自定义选择器、键盘闭环、option 悬浮说明） |
| [./ontology-v0.0.2.md](./ontology-v0.0.2.md) | 2026-09-02 | 正式版（历史版本） | 可靠性硬化、共享本体图包接入、GitLab 交付与容器化端口规范 |
| [./ontology-v0.0.1.md](./ontology-v0.0.1.md) | 2026-08-28 | 正式版（历史版本） | eimosp-ontology-agentic-analytics 智能分析首个完整可用版本 |
