# eimosp-ontology-agentic-analytics 变更记录（2026-10-05 至 2026-10-09）

> 本文档记录 2026-10-05（周一）至 2026-10-09（周五）当周的最终变更，
> 按周直接维护，不再创建日报。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更

（文件于 2026-10-08 预建：截至建文件时，当周尚无用户可见变更；10-08 有一次 `gitlab/master` 合入当前开发分支的同步合并，属分支同步，未产生新的用户可见变化。）

### 2026-10-08 · 分析逻辑剥离包新增真实工具运行时 `tools/`（方案 C，凭据外置）

- 背景：用户要求剥离包不能只有判定逻辑，要能跑**真实工具**（此前实测缺少工具时只能输出
  「能力限制」）；接收方确认为**公司内网同事**。凭据不随包交付，改为仓库外自建，避免
  secret 进仓库/进压缩包。
- 交付：`ontology-analytics-skill/tools/`
  - `serve.py`：CLI / JSONL 入口，按配置装配本体（远程服务 / 本地 Excel）与取数后端
    （Doris HTTP 网关 / Doris MySQL 协议 / 本地 SQLite），暴露 **17 个真实工具**；
    `--list-tools`、`--call NAME --params JSON`、`--serve` 三种用法。
  - `_vendor/`：真实工具实现原样副本（基线提交 `cc4a134`，31 个文件、约 1.3 万行），
    覆盖 `bi_agent/tools/*`、`bi_agent/ontology/*`、`bi_agent/x360/*`、`open_claude/*` 及
    `concurrency/tool_runtime/paths/display_names/reliability/shared_coordination`；
    仅两处最小改动（`open_claude/tools.py` 的 `anthropic` 依赖改为可缺失、
    `bi_agent/ontology/store.py` 的 `openpyxl` 改为惰性导入），详见 `_vendor/README.md`。
  - `config.example.env`（只有变量名，无值）、`selftest.py`（离线自检）、
    `README.md`（配置形态、依赖、对接方式、安全约束）、`.gitignore`（忽略 `credentials.env`）。
  - 同步更新包内 `README.md`、`SKILL.md` 与 `references/08-tools-and-sources.md`：
    原「未包含工具实现」改为「工具实现已随包，凭据仍外置」。
- 凭据：不写入仓库，由使用者在仓库外自建
  `~/.config/ontology-analytics/credentials.env`（600 权限）；读取优先级为
  进程环境变量 → `tools/credentials.env` → 上述路径。本机已生成该文件供调试。
- 验证（2026-10-08）：
  - `python3 tools/selftest.py` → **ok**（17 个工具、临时 SQLite 端到端取值 `4470000.0`、
    `DELETE` 被只读守卫拒绝）；
  - 内网实测 `python3 tools/serve.py --call ListBusinessObjects` 返回真实业务对象；
  - `python3 scripts/selfcheck.py --quiet` → routing 137/137、gates 23/23、**160/160**；
  - 远程本体 + Doris HTTP 网关形态零第三方依赖；本地 Excel 需 `openpyxl`、Doris MySQL 需
    `pymysql`、多进程协调需 `redis`（后两者源仓库本就是惰性导入）。
- 边界：只**新增** `ontology-analytics-skill/tools/` 与文档/changelog 改动，未改任何现有
  代码、配置或 Prompt；未提交任何 secret；未改版本号、tag/Release；未部署、未重启服务；
  未删除或迁移历史会话与用户数据。
