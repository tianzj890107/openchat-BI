"""Convert an explicitly selected calendar deadline before any external dispatch."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import re


def dispatch_deadline(value):
    text = str(value or '').strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}(?:$|T| )', text):
        raise ValueError('请将建议期限改为具体截止日期（YYYY-MM-DD），例如选择日历日期；工作日建议不是可下发日期')
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('截止日期无效，请填写真实日期（YYYY-MM-DD）') from None
    if len(text) == 10:
        parsed = parsed.replace(hour=18)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    return parsed.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
