"""Launch the BI agent web UI.

Usage:
    python -m bi_agent.web [--host 127.0.0.1] [--port 8765] [--ontology ...] [--db ...]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from ..paths import DATABASES_DIR, SPREADSHEETS_DIR


DEFAULT_ONTOLOGY = str(SPREADSHEETS_DIR / "本体元素_MetaERP（采购领域）-建模.xlsx")
DEFAULT_DB = str(DATABASES_DIR / "HyperFusion.db")
DEFAULT_AGENT = "bi-analyst"
# Sentinel for --db meaning "use the Apache Doris (MySQL protocol) source".
DORIS_DB = "doris"


def _resolve(path: str, base: Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (base / p).resolve()


def main() -> None:
    # Local deployments conventionally keep provider credentials in a
    # gitignored .env file at the project root/current working directory.
    # Environment variables set by the process still take precedence.
    load_dotenv(override=False)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(prog="bi-agent-web", description="硕磐 BI 智能分析 Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cwd", default=None, help="工作目录,默认当前目录")
    parser.add_argument("--ontology", default=None)
    parser.add_argument(
        "--db",
        default=None,
        help=f"SQLite .db 文件,或 '{DORIS_DB}' 使用 Doris 实时查询(默认)",
    )
    parser.add_argument("--agent", default=DEFAULT_AGENT)
    parser.add_argument("--reload", action="store_true", help="开发模式热更")
    args = parser.parse_args()

    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print("Error: fastapi/uvicorn 未安装。请先 `pip install -e .[web]`", file=sys.stderr)
        sys.exit(1)

    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd()
    if not cwd.is_dir():
        print(f"Error: 工作目录不存在: {cwd}", file=sys.stderr)
        sys.exit(1)

    remote_mode = os.environ.get("ONTOLOGY_BACKEND", "local").strip().lower() in {"production", "remote"}
    # Production never resolves or validates a local workbook. Keep the CLI
    # option solely for explicit local development mode.
    ontology_path = _resolve(args.ontology or DEFAULT_ONTOLOGY, cwd) if not remote_mode else Path("")

    # Default database source is Apache Doris (real-time query). A local SQLite
    # .db is used only when explicitly passed via --db <file>.
    db_choice = args.db if args.db is not None else DORIS_DB
    use_doris = db_choice == DORIS_DB
    db_path = _resolve(DEFAULT_DB, cwd) if use_doris else _resolve(db_choice, cwd)

    if not remote_mode and not ontology_path.is_file():
        print(f"Error: 未找到本体文件: {ontology_path}", file=sys.stderr)
        sys.exit(1)
    if not use_doris and not db_path.is_file():
        print(f"Error: 未找到数据库: {db_path}", file=sys.stderr)
        sys.exit(1)

    from .app import app, configure

    configure(
        cwd=str(cwd),
        ontology_path=str(ontology_path),
        db_path=str(db_path),
        agent_name=args.agent,
        use_doris=use_doris,
    )

    db_label = "Doris(实时查询)" if use_doris else db_path.name
    print(f"[bi-agent-web] http://{args.host}:{args.port}")
    ontology_label = "remote-managed" if remote_mode else ontology_path.name
    print(f"[bi-agent-web] agent={args.agent}  ontology={ontology_label}  db={db_label}")

    import uvicorn
    uvicorn.run(
        "bi_agent.web.app:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
