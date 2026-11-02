import pytest
from bi_agent.cockpit.deadline import dispatch_deadline

@pytest.mark.parametrize('value',['建议期限：7 个工作日（待确认）','7 个工作日','','2026-99-99'])
def test_suggestion_or_invalid_date_cannot_be_sent(value):
    with pytest.raises(ValueError):dispatch_deadline(value)

def test_explicit_dates_have_unambiguous_iso_timezone():
    assert dispatch_deadline('2026-12-01') == '2026-12-01T10:00:00Z'
    assert dispatch_deadline('2026-12-01T09:00:00+08:00') == '2026-12-01T01:00:00Z'
