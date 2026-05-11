"""
BI Agent CLI — `python -m bi_agent`.

Loads the ontology xlsx, registers BI tools, then launches open-claude's REPL
with the bi-analyst AgentDef. All open_claude CLI flags still work.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


DEFAULT_ONTOLOGY_XLSX = "ChatBI业务元数据_硕磐财务管理.xlsx"
DEFAULT_DB = "guangfeng.db"
DEFAULT_AGENT = "bi-analyst"


def _resolve(path: str, base: Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (base / p).resolve()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bi-agent",
        description="硕磐财务 BI 智能分析助手 (基于 open-claude 和业务本体)",
    )
    parser.add_argument("--cwd", default=None, help="工作目录 (默认当前目录)")
    parser.add_argument("--ontology", default=None, help=f"本体 xlsx 路径 (默认 {DEFAULT_ONTOLOGY_XLSX})")
    parser.add_argument("--db", default=None, help=f"客户数据库路径 (默认 {DEFAULT_DB})")
    parser.add_argument("--agent", default=DEFAULT_AGENT, help=f"AgentDef 名称 (默认 {DEFAULT_AGENT})")
    parser.add_argument("--model", default=None, help="模型覆盖")
    parser.add_argument("-p", "--prompt", default=None, help="单次提问模式")
    parser.add_argument("--dangerously-skip-permissions", action="store_true",
                        help="自动批准所有工具调用")
    parser.add_argument("--list-ontology", action="store_true", help="打印本体加载统计后退出")
    args = parser.parse_args()

    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd()
    if not cwd.is_dir():
        print(f"Error: 工作目录不存在: {cwd}", file=sys.stderr)
        sys.exit(1)

    ontology_path = _resolve(args.ontology or DEFAULT_ONTOLOGY_XLSX, cwd)
    db_path = _resolve(args.db or DEFAULT_DB, cwd)

    if not ontology_path.is_file():
        print(f"Error: 未找到本体文件: {ontology_path}", file=sys.stderr)
        print("用 --ontology <path> 指定,或把 xlsx 放到工作目录下。", file=sys.stderr)
        sys.exit(1)
    if not db_path.is_file():
        print(f"Error: 未找到数据库: {db_path}", file=sys.stderr)
        print("用 --db <path> 指定,或把 sqlite 文件放到工作目录下。", file=sys.stderr)
        sys.exit(1)

    from .ontology.store import OntologyStore
    from .tools import register_all

    print(f"[bi-agent] 加载本体: {ontology_path.name}")
    store = OntologyStore.from_xlsx(ontology_path)
    stats = store.stats()
    print(f"[bi-agent] 本体统计: " +
          ", ".join(f"{k}={v}" for k, v in stats.items()))

    if args.list_ontology:
        return

    registered = register_all(store, db_path)
    print(f"[bi-agent] 注册工具: {', '.join(registered)}")
    print(f"[bi-agent] 数据库: {db_path}")
    print()

    # Hand off to open_claude — reuse its REPL, but with our agent def selected.
    if args.model:
        os.environ["CLAUDE_MODEL"] = args.model

    from open_claude.agent_def import load_agent_defs, get_agent_def_registry
    from open_claude.config import get_api_key

    load_agent_defs(str(cwd))
    registry = get_agent_def_registry()
    agent_def = registry.get(args.agent)
    if not agent_def:
        print(f"Error: 未找到 AgentDef '{args.agent}'.", file=sys.stderr)
        available = registry.list_names()
        if available:
            print(f"Available: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)

    if not get_api_key():
        print("Error: 缺少 API key。设置 ANTHROPIC_API_KEY 或写入 ~/.claude/config.json", file=sys.stderr)
        sys.exit(1)

    permission_mode = "always_allow" if args.dangerously_skip_permissions else "default"

    if args.prompt:
        from rich.console import Console
        from open_claude.repl import Conversation

        console = Console()
        conv = Conversation(str(cwd), permission_mode=permission_mode, agent_def=agent_def)
        conv.add_user_message(args.prompt)
        try:
            conv.run_turn()
        except KeyboardInterrupt:
            console.print("\n[dim](interrupted)[/dim]")
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
            sys.exit(1)
    else:
        from open_claude.repl import run_repl
        run_repl(str(cwd), permission_mode=permission_mode, agent_def=agent_def)


if __name__ == "__main__":
    main()
