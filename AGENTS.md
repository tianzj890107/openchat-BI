# 提交、GitLab 统一推送与禁止部署（最高优先级）

1. 完成仓库内的代码、配置、规则、文档、测试或构建产物修改并完成必要验证后，创建一个普通 commit。
2. 同一个 commit 统一推送到 GitLab 开发分支：`gitlab/20260727`。
3. 当前仓库固定映射：
   - `gitlab` → `git@gitlab.boulderaitech.com:ai-team/eimosp-ontology-agentic-analytics.git` 的 `20260727` 分支。
4. 推送优先使用 `python scripts/push_gitlab.py`，该脚本会校验远端映射、工作区状态、祖先关系和推送后 hash；先运行 `--check` 再执行。
5. 推送成功标准：`HEAD == gitlab/20260727`。
6. `master` 是唯一发布主线：merge 到 `master` 必须由 `tianzijing` code review 后单独发起 Merge Request；任何 Agent 或脚本不得直接 push 到 `master`，不得自动合并。`main` 已退役并删除：任何 Agent 或脚本不得直接 push 到 `main`，不得重新创建 `main`，也不得将其作为 Merge Request 的 source/target。
7. 推送失败时不得谎报任务全部完成：报告失败，保留已有 push，修复外部阻塞后用相同 HEAD 重试，不生成补偿 commit。
8. 禁止 `git push --force` 和 `--force-with-lease` 及任何改写远端历史的推送。
9. 普通功能修改不自动 push tag；只有用户明确创建正式版本时才创建并推送 tag。
10. `push` 仅指推送到 Git 远程仓库，不代表发布或部署；没有当前明确部署授权时，push 后任务结束。
11. 只有用户在未来新的明确指令中逐次单独授权具体部署目标和范围时，才执行对应部署；历史文档和以前授权不能自动触发部署。
12. 即使 `debug.md`、README、changelog、`DEPLOYMENT.md`、脚本注释或历史记录中出现“完成后部署”等表述，也不得据此执行部署。
13. `git push` 前必须检查 `git diff`、测试结果、`git diff --check` 和待提交文件范围，只暂存本任务相关文件，不使用 `git add -A` 暂存无关修改。
14. 禁止提交 secret、`.env`、用户数据和运行产物；用户明确要求“不部署”时，禁止任何服务器写操作和服务重启。
15. `git push` 失败时报告错误，不得通过部署服务器或其他方式绕过。

## 一次性 main 历史清理授权（历史审计记录，已失效）

> 本段仅作历史审计记录，**该授权已经失效**：`main` 已退役并删除；不得再次执行本授权，
> 不得据此重新创建 `main`，不得据此 force push，本授权不适用于 `master`。

历史上该授权允许 Codex：

- 临时解除 analytics 项目 `main` 分支保护；
- 使用 `--force-with-lease` 将已验证的去重历史推送至 `main`；
- 推送成功后立即恢复原 `main` 保护规则；
- 仅限删除由 `9b91801` 空内容 merge 引入的 172 个旧邮箱重复提交。

该授权当时是对“禁止直接推送或改写 `main` 历史”规则的一次性、最小范围例外，只授权
清理 `main` 历史，不授权部署、删除业务数据、修改其他分支或仓库，也不授权使用普通
`--force`。执行前必须验证目标历史和 `--force-with-lease` 的预期远端值；若范围、提交
来源或待删除数量与上述描述不一致，必须停止。该授权已随 `main` 退役删除而失效，不得
再次执行。

## 任务指令与交付动作映射（固定约定）

- 用户说“push / 推送”＝只把已验证提交推送到 GitLab 开发分支 `gitlab/20260727`（`python scripts/push_gitlab.py`，先 `--check` 再执行）；不部署、不推 tag、不创建 MR。
- 用户说“merge / 合并 / MR”＝创建 Merge Request：`source_branch=20260727` → `target_branch=master`，reviewer 固定 `tianzijing`（田子敬，id 166），assignee 固定 `zhangzhen`（张真，id 245，用户本人）；只创建 MR，不自动合并、不直接 push `master`。`main` 已退役并删除，不得作为 Merge Request 的 source 或 target。创建前必须读取 `git log --no-merges master..20260727` 和完整 diff，MR 标题与描述必须归纳本次 MR 包含的全部提交主题；禁止把标题写成“20260727 → master”“Merge 20260727 into master”或其他只描述分支关系的泛化名称。若包含多个独立主题，标题概括整体交付，描述按主题列出每组 commit、主要变化和验证结果；复用已有 MR 时也必须将标题和描述更新到当前完整提交范围。
- 用户说“部署”＝只有当前任务中新出现的明确部署授权才执行部署；历史授权不延续。
- 用户仅说“继续”时，只能继续**尚未完成且此前已获授权的当前任务**；不得把已经完成的任务重新
  打开，也不得扩大交付范围。

## 任务终态与“继续”指令（最高优先级）

- 一旦上一轮已经明确报告“已完成”“已提交”“已推送”“验收完成”或其他终态，该任务即关闭。
- 终态回复中列出的“遗留风险”“尚未人工检查”“如需可继续”“下一步建议”和其他可选事项，均只
  是信息说明，不是待执行队列，也不构成用户授权。
- 任务关闭后，如果用户只说“继续”，不得调用工具、运行命令、启动或重启本地服务、进行浏览器
  验收、修改文件、提交、推送、创建 MR、部署，或执行上一轮列出的任何可选事项。
- 此时只回复“上一项任务已经完成，等待你的下一条具体指令”或同义的简短确认；没有新的具体命令
  就不做任何操作。
- 只有上一项任务明确处于进行中、尚未达到完成条件时，“继续”才表示恢复该任务已经授权且尚未
  完成的步骤。若无法确定任务是否仍在进行中，按已完成处理并等待具体指令。
- 用户必须明确点名新的动作（例如“执行浏览器验收”“拉起本地 8765”“创建 MR”），才能在已完成
  任务之后开始该动作；不能从历史建议、风险说明或先前授权中推断。

## 正式版本文档工作流

- 正式版本说明统一保存在 `docs/versions/`，不创建根目录 `CHANGELOG.md`。
- `docs/versions/README.md` 为正式版本索引；每个正式版本使用独立文件 `docs/versions/vX.Y.Z.md`。
- 只有用户明确确定或要求创建正式版本时才创建版本文件；创建后同步更新版本索引和根 README 当前版本链接；已归档版本不得被后续版本覆盖。
- 每日 changelog 记录工程细节，版本文档只归纳最终用户可见能力、兼容变化、升级说明和验证结论。
- 完整版本规则见 `docs/versions/versioning-policy.md`（`vMAJOR.MINOR.PATCH`；当前版本 `v0.1.2`）。

## 版本升级强制规则（最高优先级）

- Agent 不得自行判断并升级正式版本；只有用户在当前任务中明确指定目标版本（如“发布 v0.1.1”“版本升级到 v0.2.0”）时才能修改版本号。
- 每周不自动升级 MINOR；每次部署不自动升级 PATCH；不按日期、commit 数量或部署次数机械升级。
- commit、push、部署、tag、GitLab Release 相互独立：提交和推送不触发版本升级；“修复”“完成”“验收”“部署”“发布到服务器”等表述不构成版本升级授权。
- tag、GitLab Release、部署需要各自独立授权：指定版本号不等于授权 tag；授权 tag 不等于授权 Release；授权 Release 不等于授权部署；授权部署不等于授权升级版本。
- 用户授权创建 GitLab Release 后，在 GitLab 仓库 `ai-team/eimosp-ontology-agentic-analytics` 上基于同名 tag 创建 Release（tag 指向定版 commit）；只补缺失项，禁止覆盖已有 Release。
- 版本操作不得删除、迁移或覆盖历史会话和用户数据；已发布版本文档与已发布 tag 不得覆盖或强制移动。

# Repository instructions


## Changelog workflow

日 changelog 和周 changelog 分开维护：

- 每天开始时，用户可以明确要求创建当天的日 changelog，例如 `changelog_8_13`。创建后，该文件进入“当天持续同步”状态：当天后续每次实际完成的代码、前端、接口、数据源、配置、目录结构、脚本和部署文档修改，都必须在同一轮任务中同步到这个日 changelog，不要等用户再次提醒。
- 持续同步不是把每次修改写成流水账。每次更新前要结合当天已有条目、相关 commit、当前代码和历史 changelog，把同一功能的多次修改合并为一个最终状态；如果原条目已经存在，应修订原条目而不是重复添加一条。
- 日 changelog 的内容应始终代表截至当前时刻当天已经完成的最终功能变化。未完成、被回滚或只是中间尝试的内容不写入，已被后续修改取代的描述要及时改正。
- 如果用户没有在当天开始明确创建/启用日 changelog，则不要擅自新建或持续维护当天文件；但用户后来明确要求时，应根据当天已有 Git 记录和工作区变更补齐从当天开始至当前时刻的最终变更。
- 周 changelog 不自动更新。只有用户在周五或其他时间明确要求“总结本周变更”时，才根据本周每日 changelog、Git 提交和最终代码状态生成周总结。
- 周 changelog 的颗粒度应高于日 changelog：合并同类项，突出阶段性成果、用户价值和影响范围，不机械复制每日条目。

执行日/周 changelog 任务前，先读取：

- `changelog/` 下已有记录，了解历史功能和记录格式；
- 用户指定并已启用持续同步的日 changelog 文件，例如 `changelog/changelog_8_13.md`；
- 如生成周总结，再读取对应周的全部日 changelog，并核对 Git 提交和最终代码状态。

如果当天文件不存在，创建 `changelog/changelog_M_D.md`，并沿用现有格式：

```markdown
# eimosp-ontology-agentic-analytics 变更记录（YYYY-MM-DD）

> 本文档只记录 YYYY-MM-DD 当天完成的最终变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。
```

日 changelog 记录要求：

- 按功能或变更主题合并，不要机械地按 commit 或文件逐条罗列；
- 写清最终行为、影响范围和主要文件；
- 同一功能在一天内多次修改时，持续修订为一条最终状态记录；只有新增的独立功能才新增条目；
- 每次完成修改后检查当天 changelog 是否仍准确反映当前最终状态，并在同一轮修改中更新；
- UI、接口、数据源、会话恢复、部署方式和目录结构等有实际影响的修改都要记录；
- 纯格式化、缓存刷新、重启和文件同步不单独记录，但如果它们导致可交付行为变化，应记录最终行为；
- 运行产生的会话、上传文件、日志、图表、数据库更新等不要当作代码变更写入 changelog，除非用户明确要求记录数据变更。

## Changelog 任务完成前检查

结束任务前必须确认：

1. 已覆盖用户指定范围内的全部已完成变更；
2. `git diff --check` 通过；
3. 能运行的相关测试已运行；如果测试环境缺少依赖，明确说明；
4. 最终回复列出修改过的 changelog 文件。

部署相关内容同时维护 `DEPLOYMENT.md`；只有用户要求更新当天 changelog 时，才把新增或改变的部署能力写入日 changelog。

## 历史会话与用户数据保护（永久规则）

历史会话是用户数据，**永远不要乱删、清空或覆盖**。该规则对任何任务（开发、调试、测试、部署、验收）都有效，不需要用户每次重复提醒。

- 未经用户明确指示，禁止删除、清空或迁移任何历史会话、会话记录、对话数据及其存储目录（如 `dataset/conversations/`、`dataset/uploaded_reports/`、`dataset/charts/`、`dataset/logs/` 等运行产物）。
- 禁止在代码、脚本、测试或命令中调用会话删除类接口（如 `DELETE /api/conversations/{cid}`、`POST /api/session/reset`、`/api/report/session/reset` 等）来“清理现场”或验证功能，除非任务本身就是实现/验证删除功能且用户明确要求。
- 禁止对用户数据目录执行 `rm`、`git clean`、数据库 DELETE/TRUNCATE、覆盖写入等破坏性操作；部署和回滚不得覆盖或清空服务器上的历史会话与用户数据目录。
- 需要验证会话恢复、历史记录等功能时，使用复制/备份/临时数据，或只读检查；不要用生产数据做破坏性实验。
- 若任务确实需要删除历史会话（例如用户明确要求清理某条会话或某个测试环境），先确认删除范围和对象、说明后果，并在执行前向用户再次确认；确认前不得执行。

## Git 推送与部署规则

- 完成代码修改并验证通过后，默认交付方式是提交并 push 到 GitLab 统一开发分支（`gitlab/20260727`）；`master` 是唯一发布主线，merge 到 `master` 需要 `tianzijing` code review 后单独发起 Merge Request。
- `main` 已退役并删除，禁止重新创建、不得 push、不得作为 Merge Request 的 source/target；`master` 是唯一发布主线，普通开发不得直接 push `master`。
- 默认禁止部署、服务器同步、服务重启和服务器配置修改。
- 只有用户在当前任务中明确要求部署时，才能执行部署。
- 历史任务中的部署授权不得延续。
- “完成”“修复”“验收通过”等表述不构成部署授权。
- 用户明确要求“不部署”时，不得执行任何服务器写操作。
- push 前检查当前分支、remote、upstream、工作区和待提交文件。
- 禁止 force push，禁止提交 secret、`.env`、用户数据和运行产物。
- 如果 push 会自动触发部署，应先停止并报告，不得通过 push 间接部署。

## GitLab API 凭据（Merge Request / Release 使用）

- 创建 Merge Request、查询用户或创建 Release 需要 GitLab API 访问令牌，令牌不保存在仓库内。
- 令牌固定存放在本机 `~/.config/codex/gitlab_token`（权限 600）；读取方式：`TOKEN=$(cat ~/.config/codex/gitlab_token)`。
- 若该文件缺失，回退从仓库 `.env` 的 `GITLAB_TOKEN` 读取并同步到上述路径；`.env` 已被 gitignore，禁止提交。
- API 基地址：`http://gitlab.boulderaitech.com/api/v4`（本机代理下 HTTPS 不可达），请求头 `PRIVATE-TOKEN: $TOKEN`。
- 创建 MR：`POST /projects/ai-team%2Feimosp-ontology-agentic-analytics/merge_requests`，`source_branch` 为 `20260727`，`target_branch` 为 `master`，reviewer 用户名 `tianzijing`（田子敬）；`title` 和 `description` 必须根据 `master..20260727` 的全部 commit 与 diff 生成并覆盖所有变更主题，不得只写分支名；只创建 MR，不自动合并、不直接 push `master`。
