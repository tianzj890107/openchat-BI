"""Report ingestion — PDF/Word parsing for the smart-report-analysis mode."""

from .parser import ParseResult, parse_report, parser_availability
from .store import ReportRecord, ReportStore

__all__ = [
    "ParseResult",
    "parse_report",
    "parser_availability",
    "ReportRecord",
    "ReportStore",
]
