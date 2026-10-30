"""Shared runtime preserves the existing event loop and legacy provider patching."""
import importlib


def test_web_compatibility_import_is_the_same_runtime_module():
    runtime = importlib.import_module('bi_agent.runtime.session')
    legacy = importlib.import_module('bi_agent.web.session')
    assert legacy is runtime
    assert legacy.WebSession is runtime.AgentSession


def test_provider_override_is_shared_across_entry_points(monkeypatch):
    runtime = importlib.import_module('bi_agent.runtime.session')
    legacy = importlib.import_module('bi_agent.web.session')
    provider = object()
    monkeypatch.setattr(legacy, 'stream_message', provider)
    assert runtime.stream_message is provider
