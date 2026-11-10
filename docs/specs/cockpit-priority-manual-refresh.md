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

## Bounded main-service execution and per-stage progress (2026-11-09)

- Snapshot reads are prepared deterministically after the normal turn policy and use the normal tool boundary, query recording and claim generation. Up to 18 queries are read in batches of six before the first model call. Batch rows retain query identity and each query's request/receipt/coverage. Further reads remain possible; samples and unread coverage are disclosed. No live SQL is generated by this optimization.
- The existing delivery validator remains authoritative. An accepted delivery terminates the loop only when its query-result index still matches the current evidence. Rejected deliveries remain repairable and a later read invalidates an earlier delivery. The model no longer spends a separate round writing a confirmation document. Task-local parameters disable thinking and bound output/iterations without changing other sessions or persisted model settings.
- Defaults: stage fetch budget 60 seconds, per-AP analysis query 10 seconds, six model rounds maximum, 4096 output tokens. Existing explicit fetch-budget overrides remain honored. Successful partial AP data is analyzed; unavailable queries cannot become invented evidence. Cockpit PG supplementation is paused by default and old saved results remain readable.
- `manualUpdate.stageProgress[stage]` is persisted with queue/start/finish timestamps, phase/message and failure diagnosticId. Cards share stage work but display their own stage status. Completed durations stop increasing. UI clocks update locally once per second only while a round runs; existing lightweight manifest polling remains unchanged.
- History lists default to SQLite-projected summaries with pagination. Full single-record evidence remains an explicit read. This avoids deserializing/returning tens of MB just to inspect task state.
- Metadata is synchronized to SDK commit 325ffcd. The duplicate KPI unit is removed upstream. Product-team “其他” is disabled via the public component configuration, without modifying SDK behavior. Helmet fetches no longer use old page snapshots; server reuse keys include the current runtime version. No global cache purge or history deletion occurs.

Offline end-to-end cases exercise one model call for direct validated delivery and two when one invalid delivery needs repair. These are deterministic mock-provider counts, not a live model latency guarantee. Deployment and tar replacement require separate authorization.

Compatibility correction (2026-11-09): server pre-reads are model input observations, not synthetic assistant tool calls. They retain the existing secured execution, evidence IDs and progress events. Only actual model-requested tool exchanges enter assistant/tool history; actual DeepSeek reasoning needed for their replay stays internal even when hidden in the UI. See [DeepSeek compatibility](deepseek-empty-assistant-compatibility.md#server-preloaded-evidence-and-hidden-reasoning-2026-11-09). Card progress display, manual refresh scheduling and page query behavior remain unchanged.

## Fixed-card generation quality (2026-11-10)

Prepared Cockpit turns expose only structured card delivery, followed by a bounded JSON Patch repair tool after rejection. They have a hard two-request limit shared across runtime repairs, no AskUser and no generic essay/action repair loop. The original card is retained if validation still fails. Source and evidence-ID checks, unsupported-cause checks and cross-unit inference checks remain enforced. Explicit independent unit observations and prohibitions on comparison are not themselves unit-conversion claims. Output tokens are capped at 16384; low reasoning effort is task-local, and provider compliance with thinking settings is not guaranteed.

Risk panels render each finding, up to four, in addition to the summary. Counts are never padded: causes need plausible evidence-linked mechanisms; unconfirmed mechanisms remain hypotheses and actions remain investigations. Same business issue across combined and node cards is deduplicated. Display ordering is a deterministic policy, not a quantitative severity score.

Evidence HTML charts use saved query rows only, preserve query scope and units, disclose sampling and sources, and require unambiguous dimensions. There are no new model or AP calls. Missing local chart assets retain tables instead of loading a CDN.

A truncated empty candidate retries full structured delivery on the second request; a populated candidate uses local patch repair. Both share the same two-request ceiling and full validation. The larger output ceiling accommodates gateway-retained DeepSeek reasoning; it is not a required output length.
