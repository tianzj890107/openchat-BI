"""Canonical project paths for datasets and generated runtime data."""

from __future__ import annotations

from pathlib import Path


DATASET_DIR = Path("dataset")
HTML_DIR = Path("html")
DATABASES_DIR = DATASET_DIR / "databases"
SPREADSHEETS_DIR = DATASET_DIR / "spreadsheets"
GRAPHS_DIR = DATASET_DIR / "graphs"
CHARTS_DIR = DATASET_DIR / "charts"
CONVERSATIONS_DIR = DATASET_DIR / "conversations"
UPLOADED_REPORTS_DIR = DATASET_DIR / "uploaded_reports"


def project_path(cwd: str | Path, relative_path: Path) -> Path:
    """Return an absolute project path rooted at *cwd*."""
    return Path(cwd).resolve() / relative_path
