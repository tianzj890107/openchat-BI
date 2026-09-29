# 版本族切换到 ontology-v0.0.x 与历史版本重建（Spec）

> 状态：待用户确认后执行｜日期：2026-09-29｜作者：Codex｜目标版本：`ontology-v0.0.10`
> 相关：`docs/versions/versioning-policy.md`、`docs/git-branch-workflow.md`、`AGENTS.md`

## 1. 背景

产品版本族从 `v0.1.x` 迁移到本体产品线命名 `ontology-v0.0.x`：

- 旧：`v0.1.0` … `v0.1.9`（10 个 annotated tag；10 个 GitLab Release；5 篇版本文档，
  `v0.1.3`–`v0.1.7` 有 Release 但没有版本文档）

> 修正：仓库内的 README 曾把 GitLab Release 记为 5 个；执行前用 API 核实，
> `v0.1.0`–`v0.1.9` 的 10 个 Release 实际都存在（见 §12）。
- 新：`ontology-v0.0.1` … `ontology-v0.0.10`

本次是**命名与清单重建**，不是内容重发：所有 tag 仍指向原来的 commit。

## 2. 用户裁决（本轮）

| # | 决策 |
| --- | --- |
| 1 | 全部映射：`v0.1.0`–`v0.1.9` 按顺序映射为 `ontology-v0.0.1`–`ontology-v0.0.10` |
| 2 | tag 沿用原来的 commit，不改变指向 |
| 3 | 重建：10 个 tag + 10 个 GitLab Release，并让 10 个版本都有版本文档（补齐缺失 5 篇） |
| 4 | 全仓统一为 `ontology-v0.0.10`（2 处强制例外见 §4） |
| 5 | 版本文档文件名采用 `docs/versions/ontology-v0.0.N.md` |
| 6 | 在 `AGENTS.md` 追加限定范围的一次性授权（§8） |

## 3. 映射表

| 旧 tag | 定版 commit（不变） | 新 tag | 新版本文档 |
| --- | --- | --- | --- |
| `v0.1.0` | `e4b0a8f33a8e3343c43e78a38efdc292c14f0a47` | `ontology-v0.0.1` | `docs/versions/ontology-v0.0.1.md` |
| `v0.1.1` | `28bb1d63dfd427d7889de3dde4e83d618028ee2c` | `ontology-v0.0.2` | `docs/versions/ontology-v0.0.2.md` |
| `v0.1.2` | `c8454d82f052a6770bae975a5d865a6f37eff721` | `ontology-v0.0.3` | `docs/versions/ontology-v0.0.3.md` |
| `v0.1.3` | `f9012f383195b9818fa322f8e47837aea4235972` | `ontology-v0.0.4` | `docs/versions/ontology-v0.0.4.md` |
| `v0.1.4` | `51939b2c3e5da755c4bef0df7e665cc5ac01d776` | `ontology-v0.0.5` | `docs/versions/ontology-v0.0.5.md` |
| `v0.1.5` | `99ac6f1f0aaf1235bfdaa49e35957bd59dafd7a6` | `ontology-v0.0.6` | `docs/versions/ontology-v0.0.6.md` |
| `v0.1.6` | `1ae9894df5e2fba190dbadca483ec7a15b1cd216` | `ontology-v0.0.7` | `docs/versions/ontology-v0.0.7.md` |
| `v0.1.7` | `706e0d54af0c3c6604179dc8eaf2862a7faf920e` | `ontology-v0.0.8` | `docs/versions/ontology-v0.0.8.md` |
| `v0.1.8` | `c938fc042b26728c9909dd05e89c65b83fe852e8` | `ontology-v0.0.9` | `docs/versions/ontology-v0.0.9.md` |
| `v0.1.9` | `60fadfcd5d0a93e49034f1a5bfbb4917241f7fc2` | `ontology-v0.0.10` | `docs/versions/ontology-v0.0.10.md` |

说明：`v0.1.0`（`e4b0a8f`）既不在 `master` 也不在当前开发分支上，它来自已退役的历史线；
沿用原 commit 意味着 `ontology-v0.0.1` 同样指向该历史提交。`v0.1.8`（`c938fc0`）在 `master`
上但不在当前开发分支上，同样沿用。

## 4. 命名规则与两处强制例外

统一目标：tag、Release 名称、版本文档、UI 显示、README、`AGENTS.md`、规则文档中的
**当前版本**一律写 `ontology-vX.Y.Z`（本批为 `ontology-v0.0.10`）。

**例外 1 —— PEP 440（`pyproject.toml`）**

- `[project] version` 只能是合法 PEP 440，因此保持 `0.0.10`。
- 实测：`packaging.version.Version("ontology-v0.0.10")` 抛 `InvalidVersion`。

**例外 2 —— npm semver（`frontend/package.json`、`frontend/package-lock.json`）**

- `version` 必须是合法 semver，因此保持 `0.0.10`。
- 实测：`npm pkg fix` 报 `npm error Invalid version: "ontology-v0.0.10"`。

**桥接规则**

- `scripts/run_analytics_eval.py` 的 `product_version()` 继续从 `pyproject.toml` 读取，读取后补
  `ontology-` 前缀，对外返回显示名 `ontology-v0.0.10`；
- 同文件 `_version_reached()` 先剥离 `ontology-v` 前缀（大小写不敏感）再做 `X.Y.Z` 比较；
  剥离后仍不合法则返回 `False`（维持"无法比较即不判超期"的既有语义）；
- 这样报告与门禁都显示新命名，而两个包管理清单保持合法。

**历史记录边界（重要）**

`changelog/**`、`docs/specs/**` 里已经写下的旧版本号属于当时的事实记录，**不改写**；
"全仓统一"的范围是**当前版本口径的载体**（源码、UI、构建产物、README、`docs/versions/**`、
`AGENTS.md`、`docs/gitlab-push-workflow.md`、`docs/git-branch-workflow.md`、`DEPLOYMENT.md`
的版本口径）。如需连历史规范一起改写，需用户另行指示。

## 5. 版本号入口清单

| # | 文件 | 现在 | 目标 |
| --- | --- | --- | --- |
| 1 | `pyproject.toml` | `version = "0.1.9"` | `version = "0.0.10"`（例外 1） |
| 2 | `bi_agent/__init__.py` | `__version__ = "0.1.9"` | `__version__ = "ontology-v0.0.10"` |
| 3 | `bi_agent/web/app.py` | `APP_VERSION = "0.1.9"` | `APP_VERSION = "ontology-v0.0.10"` |
| 4 | `open_claude/__init__.py` | `__version__ = "0.1.9"` | `__version__ = "ontology-v0.0.10"` |
| 5 | `frontend/package.json` | `"version": "0.1.9"` | `"version": "0.0.10"`（例外 2） |
| 6 | `frontend/package-lock.json` | 根部两处 `0.1.9` | 两处 `0.0.10`（例外 2） |
| 7 | `frontend/src/main.jsx` | `const PRODUCT_VERSION = "v0.1.9";` | `const PRODUCT_VERSION = "ontology-v0.0.10";` |
| 8 | `frontend/src/shell.html` | `<span ... >v0.1.9</span>` | `<span ... >ontology-v0.0.10</span>` |
| 9 | `bi_agent/web/static/vendor/antd/workbench.js` | 构建产物，含 2 处 `v0.1.9` | 重新执行 `cd frontend && npm run build` 生成 |

## 6. 文档与索引改动

- `docs/versions/versioning-policy.md`：版本格式改为 `ontology-vMAJOR.MINOR.PATCH`，当前正式
  版本改为 `ontology-v0.0.10`，补"映射与重建"说明；
- `docs/versions/README.md`：当前版本、索引表 10 行（含补齐的 10 篇文档）；
- 新增 `docs/versions/ontology-v0.0.1.md` … `ontology-v0.0.10.md`（由旧 5 篇扩写/迁移，其余 5 篇
  按对应 tag 的提交内容新写），删除旧 `v0.1.0/1/2/8/9.md`；
- 根 `README.md`：当前版本、版本说明链接、Release 链接（10 条）改为新命名；
- `AGENTS.md`：当前版本口径更新 + §8 一次性授权段；
- `docs/gitlab-push-workflow.md`、`docs/git-branch-workflow.md`：`ontology-vX.Y.Z` 命名与
  `release/ontology-vX.Y.Z` 分支命名；
- `DEPLOYMENT.md`：把"部署 `v0.1.2`，对应 tag `v0.1.2`"改为新 tag 名 `ontology-v0.0.3`；
  服务器目录 `-releases/v0.1.2` 是真实路径，**不改名、不动服务器**。

## 7. tag / Release 重建步骤

顺序原则：**先建新、后删旧**，任一环节失败即停止并报告，不做补偿性改写。

1. 本地为 10 个 commit 建 annotated tag `ontology-v0.0.N`，tag 说明沿用旧 tag 文案并把旧版本号
   替换为新名；
2. 逐个推送新 tag 到 `gitlab`（不 force）；
3. 为 10 个 tag 建 GitLab Release，name = `ontology-v0.0.N`，标题 `智能分析 ontology-v0.0.N`，
   说明取对应版本文档；已存在则只补缺失项，不覆盖；
4. 删除远端旧 10 个 tag（`git push gitlab --delete <tag>`）；
5. 删除本地旧 10 个 tag；
6. 删除旧 10 个 Release（`v0.1.0`–`v0.1.9`；顺序在删 tag 之前，避免 Release 指向已删除的 tag）；
7. 校验：`git ls-remote --tags gitlab` 只剩 10 个新 tag；`git tag --list` 只剩 10 个新 tag。

注意：`.gitlab-ci.yml` 的 `analytics-eval-release-gate` 规则为 `if: $CI_COMMIT_TAG → when: always`，
**每个 tag 都会强制触发发布门禁**；tag 推送后会有 10 次 tag pipeline。

## 8. 一次性授权文本（写入 `AGENTS.md`）

在 `AGENTS.md` 增加一段带失效条件的有限授权：

> ## 一次性版本族重建授权（限定范围）
>
> 仅在本次 `ontology-v0.0.x` 命名切换任务中，允许 Codex：
>
> - 删除并重建本仓库的 10 个 tag（`v0.1.0`–`v0.1.9` → `ontology-v0.0.1`–`ontology-v0.0.10`），
>   新 tag 必须指向 §3 映射表中登记的同一 commit；
> - 删除并重建这 10 个版本对应的 GitLab Release（其中 5 个为新增）；
> - 迁移 `docs/versions/` 下的版本文档到 `ontology-v0.0.N.md` 命名。
>
> 明确不授权：`master` 的任何写操作、force push、任何部署或服务器写操作、删除或迁移历史会话与
> 用户数据、修改与本次命名无关的 tag/分支。任务完成后本授权自动失效，不得重复使用。

## 9. 契约测试（红测清单）

| 编号 | 断言 |
| --- | --- |
| R1 | Spec 存在，且 §3 映射表的 10 组旧名/commit/新名全部在文中 |
| R2 | `pyproject.toml` 的 version 是合法 PEP 440 且为 `0.0.10`；Spec 记录了该例外 |
| R3 | `frontend/package.json` 与 `package-lock.json` 根部 version 为 `0.0.10`；Spec 记录了该例外 |
| R4 | 9 处版本入口（除两个包管理清单）统一为 `ontology-v0.0.10` |
| R5 | 前端构建产物 `workbench.js` 已重建并含 `ontology-v0.0.10`、不再含 `v0.1.9` |
| R6 | `product_version()` 返回 `ontology-v0.0.10` |
| R7 | `_version_reached()` 支持带前缀与裸 `X.Y.Z`，且越界/空值仍返回 `False` |
| R8 | `versioning-policy.md` 使用 `ontology-vMAJOR.MINOR.PATCH` 与 `ontology-v0.0.10` |
| R9 | `docs/versions/` 恰好为 `README.md` + `versioning-policy.md` + 10 篇 `ontology-v0.0.N.md` |
| R10 | 根 `README.md` 当前版本为 `ontology-v0.0.10`，且无 `v0.1.9` 残留 |
| R11 | `AGENTS.md` 含 §8 一次性授权段与当前版本 `ontology-v0.0.10` |
| R12 | 本任务验收时点：本地 tag 集合恰好是 10 个 `ontology-v0.0.N`，旧 `v0.1.*` 全部不存在。2026-09-29 晚些发布 `ontology-v0.1.0` 后，集合变为这 10 个 + `ontology-v0.1.0`（见 §12 尾注与 `docs/versions/ontology-v0.1.0.md`） |

## 10. 明确不做

- 不部署、不同步服务器、不重启服务；
- 不改服务器 `-releases/` 目录、`.env`、`RELEASE_COMMIT` 记录；
- 不删除或迁移历史会话与用户数据；
- 不 force push、不写 `master`、不重建已退役分支、不删除其他 tag/分支；
- 不改写 `changelog/**` 与 `docs/specs/**` 里历史版本号。

## 11. 风险与回滚

- 只改命名、不改 commit：如误删，可从本地 `git reflog`/其他克隆恢复 tag 指向；
- 远端 tag 可能受保护规则限制：删除失败时停止，保留已完成部分，报告实际状态；
- 删除 Release 后无法通过 UI 恢复同名 Release，需要按 §7 重建（tag 未动即可重建）；
- 打 tag 触发 10 次 tag pipeline：发布门禁未过时不得视为发布完成。

## 12. 执行记录（2026-09-29）

- GitLab 实际状态（执行前核实）：Releases = `v0.1.0`–`v0.1.9` 共 10 个；标签保护规则为空；
  默认分支 `master`；
- 新建 10 个 annotated tag `ontology-v0.0.1`–`ontology-v0.0.10`，逐个指向映射表中的原 commit，
  tag 说明沿用原文并把版本号替换为新名；
- 10 个新 tag 已推送 GitLab；10 个新 Release（名称 `智能分析 ontology-v0.0.N`，说明取对应
  版本文档）已创建；
- 旧 10 个 Release 与旧 10 个 tag（远端 + 本地）已删除；
- 收尾核实：`git tag --list` 与 `git ls-remote --tags gitlab` 都只包含 10 个新 tag。

> 尾注（2026-09-29 晚些，本次命名重建任务之外）：用户单独授权发布 `ontology-v0.1.0`，
> 该版本经 Merge Request `!17` 合入 `master`（定版 commit `74fca80`），annotated tag
> `ontology-v0.1.0` 与新 Release 已创建。因此现在本地与远端的 tag 集合是上面这 10 个
> **加上** `ontology-v0.1.0`（共 11 个），Release 同为 11 个；上面的 R12 验收时点与本节
> 收尾核实结论仍然描述的是**本任务当时**的状态，不是当前状态。
