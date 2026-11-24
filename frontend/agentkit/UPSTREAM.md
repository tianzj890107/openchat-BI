# AgentKit 上游来源记录

本体消费展示工作台（`/workbench-agentkit`）复用 AgentKit 的组件与交互规范，
按**固定提交、按文件**从上游导入源码。日常构建只读本仓文件，升级时重新执行
`python scripts/import_agentkit_upstream.py`（先 `--check`）。

- 上游仓库：`git@gitlab.boulderaitech.com:ai-team/spzn-agentkit.git`
- 固定提交：`b8df86dfa3c30de6676cd1d768cda504bf3c3338`（当前对应 `dev`）
- 导入时间：2026-11-24 14:53 +0800
- 导入方式：`git archive --remote` + `git get-tar-commit-id` 校验提交

## 导入文件

| 上游路径 | 字节 | sha256 |
| --- | --- | --- |
| `agentkit-ui/public/r/registry.json` | 10680 | `0c1baa7ea8395acaa45c1ff199b53c030d29a7b333472d7d4e3df9deb12c35ba` |
| `agentkit-ui/public/r/aui-thread.json` | 157077 | `88ffbfd10f0712a73a8edfe7a7e028c297b9479ffc1415fe23f4d4c63e85113a` |
| `agentkit-ui/public/r/aui-thread-list.json` | 21305 | `efbe4f9122422f6dc48f19ec1c5f8d55fdb2877b9a6fbff22cd3617dadf04b4e` |
| `agentkit-ui/public/r/confirm-dialog.json` | 2504 | `83798a935334358793fa3310186e154a140c831bd43481d97fa6581a845a254c` |
| `agentkit-ui/src/components/assistant-ui/elements/thread.aui.tsx` | 64876 | `5cef4f7faedd2799cd8b4a87cbd0eb59ce3b606d4f0701a25bfc4996a8b781f0` |
| `agentkit-ui/src/components/assistant-ui/elements/thread-list.aui.tsx` | 19902 | `91cdbbeb4cdfc658c73ceae01e0179068e34178d01e5c82e5644a8d583d1aa3b` |
| `agentkit-ui/src/components/assistant-ui/elements/tool-group.aui.tsx` | 7455 | `99de5f84182264970021dcaac0d470eeaa0f108d04ab6544dd5b4d61187a2f1f` |
| `agentkit-ui/src/components/assistant-ui/elements/tool-call.tsx` | 2870 | `81d4f857e02e7d33707e8030a3fbdd9980848de186ffc005eb0f4746c5aa06fb` |
| `agentkit-ui/src/components/assistant-ui/elements/markdown-text.tsx` | 7881 | `c62f4713f8a23c8c2b4e232a9a3e77a15f45efda3abfb8fbb61c2bc923f8c6a7` |

## 本仓适配

| 上游对象 | 本仓落点 | 说明 |
| --- | --- | --- |
| `agentkit-ui/public/r/aui-thread.json` | `frontend/agentkit/components/Thread.jsx` | 消息流、工具分组、状态与澄清卡的交互顺序；本仓渲染分析结果与证据 |
| `agentkit-ui/public/r/aui-thread-list.json` | `frontend/agentkit/components/SessionList.jsx` | 会话列表的视觉与新建/切换行为，接本仓 `/api/conversations` |
| `agentkit-ui/src/components/assistant-ui/elements/thread.aui.tsx` | `frontend/agentkit/state.js` | SSE → 单一会话状态的投影（同轮合并、迟到丢弃、终态幂等）|
| `agentkit-ui/src/components/assistant-ui/elements/tool-group.aui.tsx` | `frontend/agentkit/components/Thread.jsx` | 工具调用折叠组与运行状态 |
| `agentkit-ui/public/r/confirm-dialog.json` | `frontend/agentkit/components/HandoffBanner.jsx` | 交接校验失败时的确认与返回入口 |

上游源码原样保存在 `frontend/agentkit/upstream/`，不做本仓改写；
适配逻辑留在 `frontend/agentkit/` 的本地模块里，便于升级时逐文件对照。
