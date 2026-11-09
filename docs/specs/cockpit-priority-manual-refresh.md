# Cockpit manual refresh: independent combined analysis and light publications

Updated 2026-11-09. Customer fixed-annual mode remains manual-only. Opening, scrolling, filter changes and polling cannot start a model round. Saved AI cards display immediately on opening, without a first-click visibility gate. Refresh actions are blue text when enabled and gray when disabled.

## Execution and priority

The existing sales/shipment combined card stays in place. Clicking its action prioritizes an independent combined analysis immediately; it no longer waits for successful opportunity/order/shipment AI cards. The period executor builds its own dated plan from the five delivered node plans, selects at most three queries per node (aggregate plus structure coverage), deduplicates exact requests and discloses the selected coverage. Unsupported/missing AP combinations are reported, never replaced with invented fields or different scopes.

One sequential worker still refreshes six stages for 15 slots. Clicked/visible slots reorder pending work only; active work is not interrupted and completed stages are not rerun within a round. Each valid stage publishes immediately. Failed stages retain their previous cards. Empty-evidence completions are not counted as effective updates and do not replace a previous useful card. Common analysis no longer fails because another AI stage failed; it can still fail when its own evidence or model execution fails.

Unexpired exact AP query successes and failures are reused within a manual round, keyed by identity, credential/connection fingerprint, query kind and exact payload. Observation times are preserved; caches reset on the next explicit round. Failed identical queries are not hammered repeatedly within the round. `COCKPIT_FETCH_BUDGET_SECONDS` defaults to 240 seconds per stage collection; its monotonic deadline is propagated through the internal AP proxy, including queue wait. Each AI-only AP query additionally has a 10-second deadline, including queue wait; ordinary frontend chart requests and helmet metadata keep their existing deadlines. Unattempted queries after the budget are excluded/disclosed; obtained evidence can still be analysed. `COCKPIT_MANUAL_ANALYSIS_TIMEOUT_SECONDS` defaults to 600 seconds for model completion (bounded 60–1800); timeout invokes existing cooperative cancellation. Upstream AP responsiveness is still outside this service's control.

Model-facing tool responses omit duplicated raw response trees, expose at most 24 rows / 16,000 row characters per query, and explicitly state sample coverage. Raw AP receipts remain in server storage. Repeat reads return prior evidence references instead of repeating the full result in context. The directory asks the model to request up to six distinct query IDs in one model response, then deliver when sufficient evidence is available. No extra model rewrites are introduced.

`manualUpdate` includes phase, progress, analysisId where available and heartbeatAt. A heartbeat means the coordinator is alive, not that business analysis has advanced. Already published stages survive process restart; interrupted rounds do not automatically resume.

## Browser delivery

New clients request `GET /api/cockpit/ai-publications?format=manifest&id=1`. The response contains slot metadata, per-stage content versions, risk counts and manual progress; it contains no card payload or evidence. Heavy immutable projections are cached per publication head and role, and computed outside the ASGI event loop.

`GET /api/cockpit/ai-publications/stages/{stage}?id=1` returns the changed stage only, with shared evidence once for all of its slots. Stage ETags support 304. Unchanged stages are not fetched and keep the same frontend payload object, avoiding table/watch remounts. Failed downloads retain the previous payload and timestamp and retry on a later poll. The client still accepts the legacy full envelope for rolling compatibility.

During a round the client polls at 5 seconds; terminal/idle rounds use 60 seconds. Hidden tabs issue no publication requests and refresh status on visibility return. Fixed-annual tabs do not separately fetch legacy full cards/status snapshots. The customer ASGI boundary enables gzip for JSON/HTML, including the frozen publication routes. The manifest is no-store; stage payloads are private and revalidated by version.

Full proof is read only on demand from `GET /api/cockpit/ai-publications/stages/{stage}/evidence?id=1&analysisId=...`. A stale analysisId returns 409 rather than labelling newer evidence as the old analysis. The shared risk cards and combined card expose this read-only link. Existing history, receipts and annual releases are never removed.

Offline fixture measurement using the supplied ai-publications4 capture: original 8,827,437 bytes, manifest 14,655 bytes; all six compact stage responses total 619,084 bytes before gzip. A warm local manifest request took about 1 ms in the fixture. This is a payload/implementation measurement, not a customer network or live-model latency promise.

## DeepSeek and component compatibility

The outgoing DeepSeek/Team projection preserves valid tool-call/result pairs. Missing results become explicit unavailable/interrupted tool errors, not fabricated data; duplicate results are sent once, and orphan historical results are labelled as historical user observations. Stored conversations remain unchanged. The preceding empty-assistant and same-DeepSeek-family fallback fixes remain included.

ProBIUI is synced from iba-demo feature/demo_1021 commit 325ffcd1022250affac987015b766d20d735efd6. The new index integration order is preserved: BI bundle then bi-color-vars.css; that palette is byte-identical to the previous delivery. Existing null-instance fitView protection is reapplied. Host routes, dashboard metadata, card ordering and inherited component styles are preserved. Vendor hashes and cache key are updated.

Validation: full Cockpit/LLM regression run passed 631 Python tests plus 42 subtests, and 103 Node tests. Additional focused tests cover the final credential-sensitive round cache adjustment. Offline Chrome smoke loaded the new bundle, created its runtime and mounted Vue. No live model calls, task dispatch, upstream SQL changes, customer env edits, tar replacement or server deployment in this task. AP query-combination gaps and unavailable quotation metrics remain upstream data/configuration work; they are diagnosed rather than hidden.
