"""Compatibility import for the shared analytics runtime.

Alias the module itself so existing provider overrides affect the shared loop.
"""
import sys
from ..runtime import session as _session
sys.modules[__name__] = _session
