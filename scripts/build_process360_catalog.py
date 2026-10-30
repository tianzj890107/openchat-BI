#!/usr/bin/env python3
"""Build a versioned Process360 catalog from the V3.1 workbook and design doc.

The raw customer files are not required at runtime and are not committed by
this script.  The generated JSON is the local ontology/catalog consumed by the
Process360 engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bi_agent.process360.catalog import (  # noqa: E402
    CATALOG_SCHEMA,
    CODE_FIELDS,
    NAME_FIELDS,
    SHEET_KEYS,
    _canonical_code,
    _canonical_name,
)


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _header_and_rows(ws) -> tuple[list[str], list[list[Any]]]:
    rows = list(ws.iter_rows(values_only=True))
    header_index = None
    for index, row in enumerate(rows):
        if any(value is not None and str(value).strip() for value in row):
            header_index = index
            break
    if header_index is None:
        return [], []
    header = [str(value).strip() if value is not None else "" for value in rows[header_index]]
    result: list[list[Any]] = []
    for row in rows[header_index + 1:]:
        if not any(value is not None and str(value).strip() for value in row):
            continue
        result.append(list(row[: len(header)]))
    return header, result


def load_workbook_sheets(path: Path) -> dict[str, list[dict[str, Any]]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    result: dict[str, list[dict[str, Any]]] = {}
    try:
        for chinese_name, key in SHEET_KEYS.items():
            if chinese_name not in wb.sheetnames:
                continue
            header, rows = _header_and_rows(wb[chinese_name])
            records: list[dict[str, Any]] = []
            for raw_row in rows:
                row = {header[i]: _json_value(value) for i, value in enumerate(raw_row) if i < len(header) and header[i]}
                row["code"] = _canonical_code(key, row)
                row["name"] = _canonical_name(key, row)
                records.append(row)
            result[key] = records
    finally:
        wb.close()
    return result


def load_design_text(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise RuntimeError("python-docx is required to build the catalog") from exc

    document = Document(path)
    blocks: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            blocks.append(text)
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            if any(cells):
                blocks.append("\t".join(cells))
    return "\n".join(blocks)


SOP_LABELS = {
    "适用问题": "applicableQuestion",
    "必需输入": "requiredInputs",
    "处理步骤": "steps",
    "Skills与工具": "skillsAndTools",
    "分支与停止": "branchesAndStops",
    "交付与验收": "acceptance",
}


def parse_sops(text: str, version: str = "V1.2") -> list[dict[str, Any]]:
    matches = list(re.finditer(r"(?m)^\s*P(\d{2})\s+(.+?)\s*$", text))
    sops: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[start:end]
        if "适用问题" not in section:
            continue
        fields: dict[str, str] = {}
        current: str | None = None
        buffer: list[str] = []
        for line in section.splitlines()[1:]:
            stripped = line.strip()
            if stripped.startswith(("十三 ", "## 十三", "SOP配置与步骤运行契约")):
                break
            label = next((value for label, value in SOP_LABELS.items() if stripped.startswith(label + "：")), None)
            if label:
                if current:
                    fields[current] = " ".join(buffer).strip()
                current = label
                buffer = [stripped.split("：", 1)[1].strip()]
            elif current and stripped:
                buffer.append(stripped)
        if current:
            fields[current] = " ".join(buffer).strip()
        skills = sorted(set(re.findall(r"S0[0-8]", fields.get("skillsAndTools", ""))))
        sops.append({
            "id": f"P{match.group(1)}",
            "version": version,
            "title": match.group(2).strip(),
            "applicableQuestion": fields.get("applicableQuestion", ""),
            "requiredInputs": fields.get("requiredInputs", ""),
            "steps": fields.get("steps", ""),
            "skillsAndTools": fields.get("skillsAndTools", ""),
            "skills": skills,
            "branchesAndStops": fields.get("branchesAndStops", ""),
            "acceptance": fields.get("acceptance", ""),
        })
    return sops


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(model: Path, design: Path, out_dir: Path) -> dict[str, Any]:
    design_text = load_design_text(design)
    sheets = load_workbook_sheets(model)
    sops = parse_sops(design_text)
    payload = {
        "schema": CATALOG_SCHEMA,
        "catalogId": "ywln-process360-v3.1",
        "version": "V3.1",
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "model": {"fileName": model.name, "sha256": sha256(model)},
            "design": {"fileName": design.name, "sha256": sha256(design)},
            "note": "Raw customer files are build inputs; runtime uses this generated catalog.",
        },
        "sops": sops,
        "summary": {key: len(rows) for key, rows in sorted(sheets.items())} | {"sops": len(sops)},
        "sheets": sheets,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "catalog.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path, help="V3.1 ontology workbook (.xlsx)")
    parser.add_argument("--design", required=True, type=Path, help="V1.2 design document (.docx)")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dataset" / "process360" / "ywln-v3.1")
    args = parser.parse_args()
    payload = build(args.model, args.design, args.out_dir)
    print(json.dumps({"target": str(args.out_dir / "catalog.json"), "summary": payload["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
