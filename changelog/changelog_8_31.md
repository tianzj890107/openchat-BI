# openchat-BI 变更记录（2026-08-31）

> 本文档只记录 2026-08-31 当天完成的最终变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。

## 2026-08-31

### 1. 交付流程统一迁移到 GitLab

- 日常开发交付从多远端推送收敛为 GitLab 统一推送：普通 commit 只推 `gitlab/20260727`（`ai-team/openchat-bi`），`main` 是发布分支，只能由 `tianzijing` code review 后单独发起 Merge Request 合并，任何 Agent 或脚本不得直接 push `main`、不得自动合并。
- 推送脚本改为 `scripts/push_gitlab.py`：支持 `--check` 只校验不推送；校验远端 URL 映射、工作区状态、祖先关系与推送后 hash；禁止 force push；不自动推 tag；推送成功标准为 `HEAD == gitlab/20260727`。
- 本地 git 远端收敛为只保留 `gitlab` 一个远端（已删除双远端配置），`.git/config` 与 `git remote -v` 均只显示 GitLab 仓库。
- 主要文件：`scripts/push_gitlab.py`、`tests/test_push_gitlab.py`、`AGENTS.md`、`README.md`、`debug.md`、`.claude/agents/devops.md`、`docs/gitlab-push-workflow.md`（原双远端工作流文档改为跳转页 `docs/git-dual-remote-workflow.md`）。

### 2. 正式版本与 Release 规则改为 GitLab 方式

- `docs/versions/versioning-policy.md` 的 Release 规则改为 GitLab 单仓：用户授权后基于同名 tag 在 `ai-team/openchat-bi` 仓库创建 Release，tag 指向定版 commit；幂等（只补缺失项）、不覆盖已有 Release、创建失败不回滚。
- `docs/gitlab-push-workflow.md` 的正式版本完成标准同步更新：`HEAD == gitlab/20260727`，tag 推送一致，授权 Release 时 GitLab 仓库存在对应正式 Release。
- 根 `README.md` 与 `docs/versions/v0.1.0.md` 的版本管理、克隆地址与 v0.1.0 Release 链接更新为 GitLab 仓库地址；`docs/versions/README.md` 版本索引不变。
- 周 changelog `changelog/changelog_8_24_28.md` 中关于交付与 Release 的历史条目修订为 GitLab 统一推送与 GitLab Release 的最终状态，不再描述双远端镜像。
- 主要文件：`docs/versions/versioning-policy.md`、`docs/gitlab-push-workflow.md`、`README.md`、`docs/versions/v0.1.0.md`、`changelog/changelog_8_24_28.md`、`tests/test_versioning_policy.py`。

### 3. 验证结论

- `tests/test_versioning_policy.py` 与 `tests/test_push_gitlab.py` 共 30 项断言全部通过；全量测试套件 306 项全部通过。
- `git diff --check` 通过；截至当前，当日提交（`f153b7c`、`bdf5006`、`1e9fa16`、`3b45dcd`、`e616d49`、`72ff3d1`、`4ffae86`）均已推送到 `gitlab/20260727`，推送后 `HEAD == gitlab/20260727`。
- Merge Request `!1`（20260727 → main）已创建并保持 opened，reviewer=`tianzijing`、assignee=`zhangzhen`，等待 code review 后合并；未自动合并、未直接 push `main`。
- 未部署、未重启服务；push 不等于部署。

### 4. 全局复查旧托管平台痕迹并清理本地残留

- 全局扫描确认项目自有文件（文档、脚本、测试、配置）已无任何旧托管平台引用；`git remote -v` 与 `.git/config` 只保留 `gitlab` 一个远端，无 `origin`、CI 工作流目录与 `.gitmodules` 残留，GitLab 相关引用只指向 `gitlab.boulderaitech.com`。
- 剩余旧平台字样仅存在于第三方 vendor 库许可注释（`bi_agent/web/static/vendor/antd/*`、`echarts.min.js`、`frontend/public/lib/*.js`）、`frontend/package-lock.json` 的 npm 赞助链接与历史 commit message 中，属依赖许可归属与历史记录，保留不动。
- 清理本地残留：删除陈旧编译产物 `tests/__pycache__/test_push_dual_remotes.cpython-313.pyc`（对应源文件已随 `d23eb5f` 删除），清除 `.git/config` 中 3 条指向已删除 `origin` 远端的 `vscode-merge-base` 条目。
- 主要文件：`changelog/changelog_8_31.md`。

### 5. GitLab API 凭据位置规范化

- `GITLAB_TOKEN`（仓库 `.env`，已 gitignore）同步到本机固定路径 `~/.config/codex/gitlab_token`（权限 600），供后续会话读取，仓库内不保存明文。
- `AGENTS.md` 增加凭据读取指引：读取命令、回退路径（`.env`）、API 基地址与创建 Merge Request 的固定参数（`source_branch=20260727`、`target_branch=main`、reviewer `tianzijing`）。
- 主要文件：`AGENTS.md`、`changelog/changelog_8_31.md`。

### 6. 交付动作指令固定化

- 固定动作映射并写入 `AGENTS.md`：“push/推送”＝推送到 `gitlab/20260727`；“merge/合并/MR”＝创建 `20260727 → main` 的 Merge Request，reviewer 固定 `tianzijing`，assignee 固定 `zhangzhen`（用户本人）；只创建 MR，不自动合并、不直接 push `main`。
- 分析结论：assignee 固定为用户本人 `zhangzhen`（id 245）符合 GitLab 惯例——assignee 负责推进 MR 至合并，reviewer `tianzijing` 负责评审，两者职责不冲突；MR `!1` 已同步设置 assignee。
- 主要文件：`AGENTS.md`、`changelog/changelog_8_31.md`。

### 7. 本体图渲染抽为共享包

- 将 Sigma + Graphology + ForceAtlas2 的本体图布局与渲染核心从 ChatBI 前端抽为共享包 `@boulderaitech/ontology-graph`（发布到 ai-team 组包 registry，托管项目 `ai-team/ontology-graph`，GitLab 14 不支持纯组级 npm 端点）：布局纯函数（`layoutOntologyForceAtlas` / `FORCE_ATLAS_CONFIG` 等）与框架无关渲染器 `createSigmaOntologyRenderer(container, graph, options)`（hover/click 高亮、相机阈值、双击拦截、ResizeObserver、kill/relayout），并以 README 固化 graphology 图契约（`nodeType/label/color/size/parentId/highlighted/weight`）。
- ChatBI 保留自身图构建 `frontend/src/ontologyGraphModel.js`（`buildGraph` 把 `/api/ontology/subgraph` 服务端子图映射为符合契约的 graphology 图）与 11 类 `NODE_STYLE` 样式映射，删除本地副本 `frontend/src/ontologySigmaGraph.js`，`runtime.js` 改从共享包引用；布局管线与渲染器单测在共享包仓库内。
- 主要文件：共享包源码目录 `../ontology-graph`（组包 registry 托管项目 `ai-team/ontology-graph`）；本仓 `frontend/package.json`、`frontend/src/ontologyGraphModel.js`（新增）、`frontend/src/runtime.js`、`tests/test_regressions.py`、`DEPLOYMENT.md`、`README.md`。
