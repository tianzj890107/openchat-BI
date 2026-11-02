"""Deterministic customer counts; never infer customers from opportunity samples."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import time

VERSION = 'customer-coverage-v1'
CUSTOMER = 'YWLN_D006'
HAS = 'YWLN_D_CUSTOMER_HAS_OPPORTUNITY'
BID = 'YWLN_D_IS_BIDDING'
COUNT = 'YWLN_M0075'
MAX_CUSTOMERS = 2000


def unavailable(reason):
    return dict(version=VERSION, status='unavailable', reason=reason,
                withOpportunityNotBidding=None, withoutOpportunity=None)


def _raw(value):
    return value.get('value') if isinstance(value, dict) else value


def _flag(value):
    value = _raw(value)
    # Explicit AP boolean vocabulary; missing/unknown never means false.
    if value is True or value in ('是', '有', '有商机', 'true', '1', 1):
        return True
    if value is False or value in ('否', '无', '无商机', 'false', '0', 0):
        return False
    raise ValueError('CUSTOMER_STATE_UNKNOWN')


def queries(selected):
    """Use the exact scope of a frozen customer-count query, without table paging."""
    scopes = {}
    for entry in selected.values():
        if entry.get('source', 'ap') != 'ap':
            continue
        request = entry.get('request') or {}
        if not any(v.get('identifierCode') == COUNT
                   for v in (request.get('analysisConfig') or {}).get('indicators', [])):
            continue
        common = deepcopy(request.get('commonConfig') or {})
        common.pop('pagination', None)
        common.pop('sorts', None)
        scopes[json.dumps(common, sort_keys=True)] = common
    if len(scopes) != 1:
        raise ValueError('CUSTOMER_SCOPE_MISSING_OR_AMBIGUOUS')
    common = next(iter(scopes.values()))
    indicator = dict(fieldType='Indicator', identifierCode=COUNT, label='客户数',
                     valueType='NUMBER', isTree=False)
    total = dict(analysisConfig=dict(dimensions=[], indicators=[indicator]), commonConfig=common)
    detail = deepcopy(total)
    detail['analysisConfig']['dimensions'] = [
        dict(fieldType='Dimension', identifierCode=code, label=label,
             valueType='STRING', isTree=False)
        for code, label in ((CUSTOMER, '具体客户'), (HAS, '客户有无商机'), (BID, '是否投标中'))]
    detail['commonConfig']['pagination'] = dict(pageNum=1, pageSize=MAX_CUSTOMERS)
    return total, detail


def calculate(total_response, detail_response):
    """Reconcile complete customer master count before publishing either badge."""
    total_rows = (total_response.get('result') or {}).get('rows')
    detail = detail_response.get('result') or {}
    rows = detail.get('rows')
    if not isinstance(total_rows, list) or len(total_rows) != 1 or not isinstance(rows, list):
        raise ValueError('CUSTOMER_RESPONSE_INCOMPLETE')
    try:
        number = Decimal(str(_raw(total_rows[0].get(COUNT))))
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            raise ValueError('CUSTOMER_COUNT_INVALID')
        total = int(number)
    except (InvalidOperation, TypeError):
        raise ValueError('CUSTOMER_COUNT_INVALID') from None
    pagination = detail_response.get('pagination') or detail.get('pagination') or {}
    if (detail.get('truncated') or detail_response.get('truncated')
            or len(rows) >= MAX_CUSTOMERS
            or pagination.get('hasMore') is True
            or (pagination.get('total') is not None and int(pagination['total']) != len(rows))):
        raise ValueError('CUSTOMER_RESPONSE_TRUNCATED')
    customers = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('CUSTOMER_RESPONSE_INVALID')
        cell = row.get(CUSTOMER)
        # A customer name is not a unique ID. AP must supply identifierNumber.
        key = cell.get('identifierNumber') if isinstance(cell, dict) else None
        if key is None or not str(key).strip():
            raise ValueError('CUSTOMER_ID_MISSING')
        state = (_flag(row.get(HAS)), _flag(row.get(BID)))
        if not state[0] and state[1]:
            raise ValueError('CUSTOMER_STATE_CONTRADICTED')
        key = str(key)
        if key in customers and customers[key] != state:
            raise ValueError('CUSTOMER_STATE_CONTRADICTED')
        customers[key] = state
    if len(customers) != total:
        raise ValueError('CUSTOMER_UNIVERSE_MISMATCH')
    return dict(version=VERSION, status='ready', totalCustomers=total,
                withOpportunityNotBidding=sum(has and not bid for has, bid in customers.values()),
                withoutOpportunity=sum(not has for has, bid in customers.values()),
                basis='同一AP筛选范围的客户主数据，按客户ID去重；未投标指当前不在投标中，非从未投标。')


def load(context, store, query_receipt):
    """Background-only read, persisted with the analysis, no SQL/model in browser."""
    if context.get('stage') != 'opportunity' or not str(context.get('snapshotId', '')).startswith('ap-'):
        return unavailable('LIVE_CUSTOMER_SOURCE_REQUIRED')
    from .dashboard_source import receipt_material
    try:
        _, selected = receipt_material(context, store, allow_expired=True)
        total, detail = queries(selected)
        deadline = time.monotonic() + 20
        receipts = [query_receipt(context['id'], 'analysis', query, _deadline=deadline)
                    for query in (total, detail)]
        identities = {entry.get('connectionId') for entry in selected.values()
                      if entry.get('source', 'ap') == 'ap' and entry.get('connectionId')}
        if len(identities) > 1 or (identities and any(
                receipt.get('connectionId') not in identities for receipt in receipts)):
            raise ValueError('CUSTOMER_SOURCE_CHANGED')
        coverage = calculate(*(receipt['response'] for receipt in receipts))
        coverage.update(receiptIds=[r['id'] for r in receipts],
                        observedAt=min(r['createdAt'] for r in receipts),
                        queryHash=hashlib.sha256(json.dumps([total, detail], sort_keys=True).encode()).hexdigest())
        return coverage
    except ValueError as exc:
        return unavailable(str(exc))
    except Exception:
        # Do not expose upstream credentials or let an optional count fail the AI card.
        return unavailable('CUSTOMER_QUERY_FAILED')
