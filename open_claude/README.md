# Open Claude Runtime

`open_claude` 是本仓库内置的通用 Agent Runtime 和命令行组件，为 openchat-BI 提供模型调用、
流式会话、工具执行、权限控制、Skills、任务管理和 Agent 角色加载能力。

根项目及智能分析 Web 工作台说明见 [../README.md](../README.md)。

## 能力

- 流式对话与交互式 REPL；
- Bash、Read、Write、Edit、Glob、Grep、Skill 等基础工具；
- 工具执行权限控制、上下文压缩、token 与成本统计；
- 项目级和用户级 Skills；
- `CLAUDE.md` 与 `.claude/rules/*.md` 指令加载；
- 子 Agent、任务管理和 `.claude/agents/*.md` 角色定义。

## 安装与使用

Open Claude 与 BI Agent 共用仓库根目录的 Python 包配置。请在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
open-claude
```

单次提示：

```bash
open-claude -p "explain this project"
```

不安装命令入口时：

```bash
python -m open_claude
python scripts/run.py
```

常用参数：

```text
-v, --version
-p, --prompt TEXT
--model MODEL
--cwd PATH
--dangerously-skip-permissions
```

## 配置

CLI 支持环境变量或 `~/.claude/config.json`：

```json
{
  "api_key": "<api-key>",
  "model": "<model-id>"
}
```

常用变量为 `ANTHROPIC_API_KEY`、`CLAUDE_MODEL` 和 `CLAUDE_MAX_TOKENS`。不要把真实密钥写入仓库。

## Skills 与项目指令

Skills 可以放在 `~/.claude/skills/`（用户级）或 `.claude/skills/`（项目级）。项目指令支持：

- `CLAUDE.md`
- `.claude/CLAUDE.md`
- `.claude/rules/*.md`
- `CLAUDE.local.md`
- `~/.claude/CLAUDE.md`

openchat-BI 的业务角色位于根目录 `.claude/agents/`，业务 Tool 位于 `bi_agent/tools/`，
不属于 Open Claude 通用内核。

## 目录

```text
open_claude/
├── __main__.py       # CLI 入口
├── config.py         # 模型、密钥和环境配置
├── api.py            # 模型 API 与流式适配
├── tools.py          # 通用 Tool Schema 与执行器
├── agent_def.py      # Agent 定义加载
├── agent_instance.py # Agent 实例
├── repl.py           # REPL、权限和会话执行
├── prompt.py         # 系统提示组装
├── compact.py        # 上下文压缩
├── tokens.py         # token 与成本统计
├── tasks.py          # 任务管理
└── skills/           # Skills 发现、解析与内置能力
```

## License

MIT
