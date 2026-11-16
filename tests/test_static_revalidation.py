"""Unversioned static modules must be revalidated, not reused heuristically."""
from fastapi.testclient import TestClient

from bi_agent.web.app import app

MODULE = '/static/cockpit/insight-components/number-highlight.js'


def test_unversioned_module_is_revalidated_and_versioned_url_is_untouched():
    client = TestClient(app)
    first = client.get(MODULE)
    assert first.status_code == 200
    assert 'export function stripOntologyCodes' in first.text
    assert first.headers['cache-control'] == 'no-cache'
    etag = first.headers['etag']
    again = client.get(MODULE, headers={'If-None-Match': etag})
    assert again.status_code == 304

    versioned = client.get(MODULE + '?v=1')
    assert versioned.status_code == 200
    assert 'cache-control' not in versioned.headers
