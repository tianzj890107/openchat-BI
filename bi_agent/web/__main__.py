"""Launch the BI agent web UI.

Usage:
    python -m bi_agent.web [--host 127.0.0.1] [--port 8765] [--ontology ...] [--db ...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


DEFAULT_ONTOLOGY = "超聚变本体元数据.xlsx"
DEFAULT_DB = "HyperFusion.db"
DEFAULT_AGENT = "bi-analyst"


def _resolve(path: str, base: Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (base / p).resolve()


def main() -> None:
    parser = argparse.ArgumentParser(prog="bi-agent-web", description="硕磐 BI 智能分析 Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cwd", default=None, help="工作目录,默认当前目录")
    parser.add_argument("--ontology", default=None)
    parser.add_argument("--db", default=None)
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

    ontology_path = _resolve(args.ontology or DEFAULT_ONTOLOGY, cwd)
    db_path = _resolve(args.db or DEFAULT_DB, cwd)

    if not ontology_path.is_file():
        print(f"Error: 未找到本体文件: {ontology_path}", file=sys.stderr)
        sys.exit(1)
    if not db_path.is_file():
        print(f"Error: 未找到数据库: {db_path}", file=sys.stderr)
        sys.exit(1)

    from .app import app, configure

    configure(
        cwd=str(cwd),
        ontology_path=str(ontology_path),
        db_path=str(db_path),
        agent_name=args.agent,
    )

    print(f"[bi-agent-web] http://{args.host}:{args.port}")
    print(f"[bi-agent-web] agent={args.agent}  ontology={ontology_path.name}  db={db_path.name}")

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
