"""
On-disk store for uploaded reports.

Layout under <cwd>/uploaded_reports/:
    <id>.pdf | <id>.docx        original uploaded file
    <id>.json                   metadata + parsed text

Each <id>.json:
    {
        "id":           "ab12cd34",
        "filename":     "2024-Q3-financials.pdf",
        "ext":          ".pdf",
        "size_bytes":   182431,
        "uploaded_at":  "2026-04-22T14:12:03+08:00",
        "page_count":   24,
        "text_length":  48210,
        "tables_count": 6,
        "preview":      "first ~180 chars of text, for the history list",
        "text":         "<full parsed text, possibly long>",
        "tables_markdown": ["### Page 1 · Table 1 ...", ...],
        "warnings":     ["..."]
    }
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .parser import ParseResult, parse_report


ALLOWED_EXT = {".pdf", ".docx"}
STORE_DIRNAME = "uploaded_reports"
# Hard cap to keep accidental 500MB uploads from taking the server down.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024   # 50 MB
REPORT_ID_RE = re.compile(r"^[0-9a-f]{8,64}$", re.IGNORECASE)


@dataclass
class ReportRecord:
    """Public shape of a stored report."""
    id: str
    filename: str
    ext: str
    size_bytes: int
    uploaded_at: str
    page_count: int
    text_length: int
    tables_count: int
    preview: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReportStore:
    """Filesystem-backed report store. One instance per app."""

    def __init__(self, cwd: str) -> None:
        self.root = Path(cwd) / STORE_DIRNAME
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def save(self, *, filename: str, data: bytes) -> ReportRecord:
        """Persist an uploaded file, parse it, return the public record."""
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(
                f"文件过大 ({len(data) / 1024 / 1024:.1f} MB),"
                f"上限 {MAX_UPLOAD_BYTES // 1024 // 1024} MB"
            )
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXT:
            raise ValueError(f"不支持的文件类型: {ext}  (仅支持 .pdf / .docx)")

        rid = self._new_id()
        file_path = self.root / f"{rid}{ext}"
        file_path.write_bytes(data)

        meta_path: Optional[Path] = None
        try:
            parsed: ParseResult = parse_report(str(file_path))
        except Exception:
            # If parse fails, drop the file so we don't orphan it.
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        try:
            preview = _preview(parsed.text)
            meta = {
                "id": rid,
                "filename": filename,
                "ext": ext,
                "size_bytes": len(data),
                "uploaded_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
                    timespec="seconds"
                ),
                "page_count": parsed.page_count,
                "text_length": parsed.text_length,
                "tables_count": parsed.tables_count,
                "preview": preview,
                "text": parsed.text,
                "tables_markdown": parsed.tables_markdown,
                "warnings": parsed.warnings,
            }
            meta_path = self._meta_path(rid)
            if meta_path is None:  # generated IDs always satisfy REPORT_ID_RE
                raise RuntimeError("生成了无效的报表 ID")
            payload = json.dumps(meta, ensure_ascii=False, indent=2)
            temp_path: Optional[str] = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.root, prefix=f".{rid}.",
                    suffix=".tmp", delete=False
                ) as tmp:
                    temp_path = tmp.name
                    tmp.write(payload)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                os.replace(temp_path, meta_path)
                temp_path = None
            finally:
                if temp_path:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
            return self._public_record(meta)
        except Exception:
            # Parsing or metadata persistence can fail after the original
            # upload is written. Clean both artifacts so a failed request
            # cannot leave an unreachable file behind.
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass
            if meta_path is not None:
                try:
                    meta_path.unlink(missing_ok=True)
                except Exception:
                    pass
            raise

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def list(self) -> list[ReportRecord]:
        """Return all stored reports, newest first."""
        records: list[ReportRecord] = []
        for p in self.root.glob("*.json"):
            meta = self._load_meta(p)
            if meta is None:
                continue
            try:
                records.append(self._public_record(meta))
            except (KeyError, TypeError, ValueError):
                continue
        records.sort(key=lambda r: r.uploaded_at, reverse=True)
        return records

    def get(self, rid: str) -> Optional[dict[str, Any]]:
        """Return the full meta dict (including text + tables) or None."""
        path = self._meta_path(rid)
        meta = self._load_meta(path) if path is not None else None
        if meta is None:
            return None
        try:
            self._public_record(meta)
        except (KeyError, TypeError, ValueError):
            return None
        return meta

    def get_prompt_block(self, rid: str, max_chars: int = 60_000) -> Optional[str]:
        """Convenience: assembled content ready to inject into a system prompt."""
        meta = self.get(rid)
        if not meta:
            return None
        result = ParseResult(
            ext=meta.get("ext", ""),
            page_count=int(meta.get("page_count", 0)),
            text=meta.get("text", "") or "",
            tables_markdown=list(meta.get("tables_markdown", []) or []),
            warnings=list(meta.get("warnings", []) or []),
        )
        return result.to_prompt_block(max_chars=max_chars)

    def delete(self, rid: str) -> bool:
        """Remove both the original file and the metadata. Idempotent."""
        meta_path = self._meta_path(rid)
        if meta_path is None:
            return False
        meta = self._load_meta(meta_path)
        if meta is None:
            return False
        ext = meta.get("ext", "")
        file_path = self.root / f"{rid}{ext}" if ext in ALLOWED_EXT else None
        try:
            if file_path is not None:
                file_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            meta_path.unlink(missing_ok=True)
        except Exception:
            pass
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _meta_path(self, rid: str) -> Optional[Path]:
        safe = str(rid or "").strip()
        if not REPORT_ID_RE.fullmatch(safe):
            return None
        return self.root / f"{safe}.json"

    def _new_id(self) -> str:
        """Return an id with no existing metadata or source file."""
        for _ in range(16):
            rid = secrets.token_hex(4)
            if (
                self._meta_path(rid) is not None
                and not (self.root / f"{rid}.json").exists()
                and not any(
                    (self.root / f"{rid}{candidate_ext}").exists()
                    for candidate_ext in ALLOWED_EXT
                )
            ):
                return rid
        raise RuntimeError("无法生成唯一报表 ID")

    def _load_meta(self, path: Path) -> Optional[dict[str, Any]]:
        if not path.is_file():
            return None
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            return meta if isinstance(meta, dict) else None
        except Exception:
            return None

    @staticmethod
    def _public_record(meta: dict[str, Any]) -> ReportRecord:
        rid = str(meta.get("id") or "")
        if not REPORT_ID_RE.fullmatch(rid):
            raise ValueError("invalid report metadata id")
        ext = str(meta.get("ext") or "").lower()
        if ext not in ALLOWED_EXT:
            raise ValueError("invalid report metadata extension")
        return ReportRecord(
            id=rid,
            filename=meta.get("filename", ""),
            ext=ext,
            size_bytes=int(meta.get("size_bytes", 0)),
            uploaded_at=meta.get("uploaded_at", ""),
            page_count=int(meta.get("page_count", 0)),
            text_length=int(meta.get("text_length", 0)),
            tables_count=int(meta.get("tables_count", 0)),
            preview=meta.get("preview", "") or "",
            warnings=list(meta.get("warnings", []) or []),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _preview(text: str, limit: int = 180) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"
