# Analytics 整合管理清单

日期：2026-10-30。统一仓库：`eimosp-ontology-agentic-analytics`；整合分支：`feature/analytics-unified-service`。

## 保留与排除决定

- Cockpit 整合基线固定为 `edbd912`；包含后续部署记录。
- 合入 URL 入口、PDT fallback、本地 Excel 文档与 Process360 skill 拆分。
- 旧 Fuxi 实现已有补丁等价后续版本，不重复合并；LangGraph 暂留实验分支。
- 原主目录 MAL API 修改含大量格式及内容调整；SQL 执行说明大幅删减。两者与本轮执行引擎收敛无直接依赖，保留原处，不并入。
- 原主目录未跟踪压缩包、业务资料不自动提交，不删除。
- Process360 已跟踪的匿名测试示例与接收人配置说明纳入；原工作区不改写。

## 未提交成果指纹

以下哈希用于核对原文件，非清理授权。

- `eimosp-ontology-agentic-analytics/API/本体MAL层API.md`：`09db06862dcf3e7848b9f4d268c82f174f53d04e3d269276ca0f9f600cbea3c6`
- `eimosp-ontology-agentic-analytics/docs/specs/executed-sql-management-units-2800-101701.md`：`d82f9f5c53bf83a22dab4457e37cfa6648e0b7d3358378bd61d8d719005cbc0b`
- `eimosp-ontology-agentic-analytics/API/risk-todo-source-api.md`：`09c798452b6560c0993794e85cf78d0311e4c279a30d4866ec8ecdcbdd87e025`
- `eimosp-ontology-agentic-analytics/ontology-analytics-skill.zip`：`297911caba6a992560b6c0aee66be5bb38a59cf02522a2c65fd2a83247cb3d84`
- `eimosp-ontology-agentic-analytics/亿纬锂能_流程360本体元模型_V3.1_新增数据表联动版.xlsx`：`8ee68d1e357d55930b2c9292c20ad582e4ed10745367ebfba19ce232f4e4a344`
- `eimosp-ontology-agentic-analytics/流程360本体检索与闭环Skills设计方案_V1.2_问题分类SOP版.docx`：`a00558c3ef270d8b65567bb34800955666e6931d48b6a2bc94d1eeb3a2265da2`
- `eimosp-process360-acceptance-worktree/.env.example`：`bbf1e45bbdc1c8c11a1c870f96b368c30eb143b5e8533bb15c2b8a734b1929c1`
- `eimosp-process360-acceptance-worktree/DEPLOYMENT.md`：`b69b5d639f2c1e4e672e42fd7a93afe8a6b26884e2147d137d671bcab2efb2d5`
- `eimosp-process360-acceptance-worktree/changelog/changelog_10_26_30.md`：`2e948fdf3d5edac3982d692efa4db900ed2c3a920b1cd7f5551268adae0f3080`
- `eimosp-process360-acceptance-worktree/docs/specs/process360-fuxi-sop-execution-rerun-2026-10-28.md`：`e3c84abc99c33c6721111c2ece317f8a814faa7744df91a13f4e7dc6d202a972`
- `eimosp-process360-acceptance-worktree/tests/test_process360_artifact_and_dispatch_failure_red.py`：`add3a056c5a13782c41d58f41fbf91ff0ad7ceb0593def57a0d7e42b914934ef`
- `eimosp-process360-acceptance-worktree/tests/test_process360_dispatch.py`：`7402500fec88aee3d49b94299a6a1107fb66732efd72fcb5e2accac55e9023ba`
- `eimosp-process360-acceptance-worktree/tests/test_process360_dispatch_unified_red.py`：`bf824072f634ad15b7b983bb89b22c21bd64ea7101f9deaa8feb465a0a091c76`
- `eimosp-process360-acceptance-worktree/tests/test_process360_engine.py`：`afa7e2f4ab0b0f7a65da78ffa0686be2ba6d99c6c601fa4c2de7408d298caf83`
- `eimosp-process360-acceptance-worktree/tests/test_process360_execution.py`：`bd202cef84520777bdceb902504babfca7e7e7db09e5b8c1ac75df127190698a`
- `eimosp-process360-acceptance-worktree/tests/test_process360_risk_dispatch.py`：`51a8bf85615cb4dd843082aa11f0077c5aeeb8d2316758479da4b87ff490c3d0`
- `eimosp-process360-acceptance-worktree/process360-analytics-skill.zip`：`158c0af5a436a1bb146541ec0b46ed1640d2c0b8791fc1aef3449f2587407e44`

## 仍待执行

- MCP 委托分析的任务契约与统一生命周期尚未实现；当前仍保留基础工具型调用。
- 旧实例调用方核对、统一部署和旧端口退役尚未执行。
- worktree 只有确认无独有成果、忽略文件和运行依赖后才清理。
