"""Configured AI slots, mapped to the page and business stage they analyse.

The delivered dashboard is the source of truth: ``insights.json`` lists every
slot and its embed path, and the tab in that path names the page.  The slot id
itself carries the business meaning, so the slot -> stage mapping stays an
explicit host contract.  ``slots()`` and ``unmapped_slots()`` exist so a new
delivered slot cannot silently drop out of the preheat registry.
"""
from __future__ import annotations

import json

from .runtime import METADATA, PAGE_IDS

PAGES = ('overview', 'operations', 'analysis')

# Mirrors SLOT_STAGE in static/cockpit/cockpit.js.  Every delivered slot must
# have an entry; ``unmapped_slots`` is asserted empty by the test suite.
SLOT_STAGES = {
    'bid-status-note': 'bid',
    'quote-summary': 'quotation',
    'bid-summary': 'bid',
    'order-sign-summary': 'order',
    'star-product-order-list': 'order',
    'affected-order-list': 'order',
    'overdue-order-list': 'shipment',
    'sales-shipment-issues': 'shipment',
    'opportunity-risk': 'opportunity',
    'opportunity-coverage-note': 'opportunity',
    'order-risk-summary': 'order',
    'shipment-risk-summary': 'shipment',
    'shipment-overdue-note': 'shipment',
    'shipment-cause-breakdown': 'shipment',
    'shipment-task-order': 'shipment',
}


def slots() -> list[dict]:
    """Delivered AI slots, in dashboard order."""
    return json.loads((METADATA / 'insights.json').read_text(encoding='utf-8'))


def page_of_slot(slot: dict) -> str:
    tabs = {tab: page for page, tab in PAGE_IDS.items()}
    segments = (slot.get('embedPath') or {}).get('segments') or []
    tab = next((item.get('tabId') for item in segments if item.get('kind') == 'tab'), '')
    return tabs.get(tab, '')


def unmapped_slots() -> list[str]:
    """Slots that have no explicit stage mapping or no resolvable page."""
    return [slot.get('id', '') for slot in slots()
            if slot.get('id') not in SLOT_STAGES or not page_of_slot(slot)]


def configured_targets() -> dict[str, tuple[str, ...]]:
    """Every page that shows an AI slot, with its distinct stages.

    A missing page means it has no AI slots (the overview page deliberately
    has none); it is never treated as "not yet loaded".
    """
    found: dict[str, set[str]] = {}
    for slot in slots():
        stage = SLOT_STAGES.get(slot.get('id'))
        page = page_of_slot(slot)
        if stage and page:
            found.setdefault(page, set()).add(stage)
    return {page: tuple(sorted(found.get(page, ()))) for page in PAGES}


def target_stages(page: str) -> tuple[str, ...]:
    return configured_targets().get(page, ())
