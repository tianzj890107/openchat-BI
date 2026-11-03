"""Launch the BI agent web UI.

Usage:
    python -m bi_agent.web [--host 127.0.0.1] [--port 8765] [--ontology ...] [--db ...]

非容器本地直接启动默认端口为 8765；容器内统一由 APP_PORT/--port 指定 8080。
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
def _env_port(name: str, default: int) -> int:
    """读取环境变量端口；缺省或非法时回退 default。"""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# 非容器本地直接启动默认端口 8765；容器镜像内由 Dockerfile ENV APP_PORT=8080
# 显式注入，默认端口随之切换为 8080，本地默认约定不受影响。
DEFAULT_PORT = _env_port("APP_PORT", 8765)


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
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="监听端口,默认 8765(非容器);容器内由 APP_PORT 注入 8080")
    parser.add_argument("--cwd", default=None, help="工作目录,默认当前目录")
    parser.add_argument("--ontology", default=None)
    parser.add_argument(
        "--db",
        default=None,
        help=f"SQLite .db 文件、postgres(本地Excel+PG)，或 '{DORIS_DB}' 使用Doris(默认)",
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

    from ..workbench_pg import SOURCE_VALUE as PG_SOURCE, preset as pg_preset
    pg_mode = args.db in {"postgres", PG_SOURCE}
    if pg_mode:
        try:
            pg_config, pg_workbook = pg_preset(cwd)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        os.environ["ONTOLOGY_BACKEND"] = "local"
    remote_mode = os.environ.get("ONTOLOGY_BACKEND", "local").strip().lower() in {"production", "remote"}
    # Production never resolves or validates a local workbook. Keep the CLI
    # option solely for explicit local development mode.
    ontology_path = pg_workbook if pg_mode else (_resolve(args.ontology or DEFAULT_ONTOLOGY, cwd) if not remote_mode else Path(""))

    # Default database source is Apache Doris (real-time query). A local SQLite
    # .db is used only when explicitly passed via --db <file>.
    db_choice = args.db if args.db is not None else DORIS_DB
    use_doris = db_choice == DORIS_DB
    db_path = PG_SOURCE if pg_mode else (_resolve(DEFAULT_DB, cwd) if use_doris else _resolve(db_choice, cwd))

    if not remote_mode and not ontology_path.is_file():
        print(f"Error: 未找到本体文件: {ontology_path}", file=sys.stderr)
        sys.exit(1)
    if not use_doris and not pg_mode and not db_path.is_file():
        print(f"Error: 未找到数据库: {db_path}", file=sys.stderr)
        sys.exit(1)

    from .app import app, configure, set_runtime_port

    configure(
        cwd=str(cwd),
        ontology_path=str(ontology_path),
        db_path=str(db_path),
        agent_name=args.agent,
        use_doris=use_doris,
    )
    # /healthz 的 port 字段必须反映进程实际监听端口（容器内为 8080）。
    set_runtime_port(args.port)

    db_label = ("PostgreSQL · " + pg_config.schema) if pg_mode else ("Doris(实时查询)" if use_doris else db_path.name)
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
