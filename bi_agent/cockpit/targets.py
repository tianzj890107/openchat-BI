"""Configured AI slots, mapped to the page and business stage they analyse.

The delivered dashboard is the source of truth: ``insights.json`` lists every
slot and its embed path, and the tab in that path names the page.  The slot id
itself carries the business meaning, so the slot -> stage mapping stays an
explicit host contract.  ``slot_registry`` is the single registry used by the
read API, preheat scheduler, frontend bootstrap and acceptance tests.  A new
delivered slot cannot silently drop out of it.
"""
from __future__ import annotations

import json

from .cards import CONTRACT
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
    'sales-shipment-issues': 'combined',
    'opportunity-risk': 'opportunity',
    'opportunity-coverage-note': 'opportunity',
    'order-risk-summary': 'order',
    'shipment-risk-summary': 'shipment',
    'shipment-overdue-note': 'shipment',
    'shipment-cause-breakdown': 'shipment',
    'shipment-task-order': 'shipment',
}

# Output contract is deliberately explicit.  Several slots share one business
# stage (and therefore one analysis), but the dashboard still needs a stable
# slot-level identity for independent reads and acceptance counts.
SLOT_OUTPUT_TYPES = {
    'star-product-order-list': 'table',
    'affected-order-list': 'table',
    'overdue-order-list': 'table',
    'shipment-task-order': 'table',
}
REGISTRY_VERSION = 'cockpit-ai-slots-v1'


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


def slot_registry() -> list[dict]:
    """The fixed 15-slot contract used by every server/browser consumer."""
    result = []
    for slot in slots():
        slot_id = slot.get('id', '')
        result.append(dict(
            slotId=slot_id,
            page=page_of_slot(slot),
            stage=SLOT_STAGES[slot_id],
            outputType=SLOT_OUTPUT_TYPES.get(slot_id, 'card'),
            contractVersion=CONTRACT,
        ))
    return result


def maintenance_targets() -> list[tuple[int, str, str]]:
    """Distinct page/stage work units for both delivered roles.

    One analysis result is shared by every slot in a stage; keeping the target
    at stage level avoids spending a model call per card while the public API
    still exposes all 15 slot ids.
    """
    seen = set()
    result = []
    for identity in (1, 2):
        for slot in slot_registry():
            if slot['stage'] == 'combined':
                continue  # Explicit cached-only preheat; no component SQL fan-out.
            # The same stage can be rendered on operations and analysis.  A
            # stage card is shared by both pages, so preheating it twice would
            # spend a second model call for the same business analysis.
            key = (identity, slot['stage'])
            if key not in seen:
                seen.add(key)
                result.append((identity, slot['page'], slot['stage']))
    return result


def target_page(stage: str) -> str:
    """Canonical page that owns a stage-level refresh target.

    One stage card can be rendered on several pages, but the refresh scheduler
    registers it once under the first configured page.  Status readers must use
    the same page or they will look up an unrelated (usually empty) task.
    """
    return next((page for identity, page, item in maintenance_targets()
                 if identity == 1 and item == stage), '')


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
