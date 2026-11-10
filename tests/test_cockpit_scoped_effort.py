import pytest
from bi_agent.llm.runtime_config import request_config, scoped_reasoning_effort


def test_cockpit_effort_is_scoped_and_restored():
    assert scoped_reasoning_effort() is None
    with request_config(reasoning_effort='low'):
        assert scoped_reasoning_effort() == 'low'
        with request_config(reasoning_effort='high'):
            assert scoped_reasoning_effort() == 'high'
        assert scoped_reasoning_effort() == 'low'
    assert scoped_reasoning_effort() is None
    with pytest.raises(ValueError):
        with request_config(reasoning_effort='unbounded'):
            pass
