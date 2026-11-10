# Cockpit backend failure diagnostics

2026-11-09. Diagnostics observe failures; they do not rewrite upstream SQL or grant database permissions.

## Read records

After upgrading the image, open the current deployment prefix followed by:

```text
GET /api/cockpit/diagnostics?id=1&limit=20
GET /api/cockpit/diagnostics?id=1&stage=shipment&limit=20
GET /api/cockpit/analyses/<analysisId>
```

`id` follows the existing POC identities. The full analysis record includes `execution.diagnostic`; compact responses intentionally omit it. Manual-round failures also expose a diagnosticId in failedStages. AP errors include `X-Cockpit-Diagnostic-Id` in response headers.

For the known customer endpoint, the first URL is:
`http://172.16.5.230:8765/api/ontology-agentic-analytics/api/cockpit/diagnostics?id=1&limit=20`.

An AP-error diagnostic records one failed attempt, not necessarily a failed analysis: partial evidence may still produce a successful limited card. Use analysisId and task status to distinguish these cases.

The endpoint only reads SQLite. It does not call AP, databases, models or task services. Existing published cards and frontend status messages stay unchanged.

## Container logs

```bash
docker compose logs --since=30m --timestamps cockpit 2>&1 | grep cockpit_diagnostic
```

Each record contains diagnosticId, analysisId (if already created), runId, stage, phase, errorCode, errorType, message, durationSeconds, queryHash, lastTool and timestamps. A blank analysisId is expected for a query that failed before analysis creation. No request body, credentials or stack locals are recorded.

| Phase | Meaning |
| --- | --- |
| page_publication | Whole-page snapshot validation failed; annual publications remain independent |
| request_validation | Our AI-table request filters or fields were rejected before calling AP |
| ap_response | AP returned data that the table adapter could not interpret |
| ap_query_setup | AP configuration, credentials-file or proxy setup failed |
| ap_query | The AP request failed; SQL errors here are from the upstream service |
| fetch_budget | Stage collection time budget expired; obtained evidence is retained, unattempted queries excluded |
| pg_supplement | Optional registered PG supplementation failed; no source SQL is rewritten |
| main_service | Original main-service error event; lastTool is context, not proof that tool caused the error |
| analysis_execution | Other analysis execution or delivery failures |
| stage_execution | A stage could not produce a publishable candidate |
| dependency | Common analysis lacked enough successful same-round inputs |
| publication | A candidate failed publication validation |
| refresh_coordinator | Refresh initialization or orchestration failed |

Messages are redacted and bounded. Long SQL errors retain their beginning and tail to keep the upstream root-cause text where available. Original errors discarded by older versions cannot be recovered retroactively; diagnostics start with new executions after upgrade.

## Confirmed request merge fix

AI-table preset filters for `YWLN_D016` and `YWLN_M_ORDER_OVERDUE_DAYS` could be duplicated by nested SDK conditions. AND groups now flatten recursively, semantic duplicates ignore presentation labels, and supported IN/EQ predicates intersect without widening scope. Contradictions and unsupported repeated predicates are rejected before AP. OR groups are not rewritten. This fixes our table request composition only; upstream SQL/schema/permissions remain unchanged.

Validation: 407 targeted backend tests and 99 Cockpit Node tests passed, followed by five focused diagnostic/redaction tests after the final redaction adjustment. Tests use isolated fixtures; no live AP/model calls.

## Whole-page cache isolation (2026-11-09)

Fixed-annual mode bypasses whole-page snapshot reads/writes and model refreshes in the page client. The host also stops scheduling those merges. The server tolerates old browser bundles posting `/page` by returning an explicit skipped result; it does not publish a snapshot or run analysis. Normal mode uses required-stage inclusion plus allowed-stage and per-card provenance checks, so valid optional order/quotation stages no longer cause a false incomplete-slot error. Rejected builds retain a diagnostic record, including missing/submitted/unexpected stage names when the stage set is invalid.

Validation: 36 backend and 15 frontend regression tests passed. No live AP/model calls, deployment or customer tar changes in this task. Original model/delivery failures from older deployments still require a new run on the diagnostic-enabled image to identify their exact cause.
