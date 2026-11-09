# Completed Cockpit fixes: integration review

2026-11-09. Target: master. Reviewer: tianzijing. No automatic merge or deployment.

## Source branches and deduplication

- feature/cockpit-customer-5f2a615: customer entrypoint, env isolation, connector generation and AP path fix; covers the equivalent customer-bundle and cockpit-ap-x360-base changes.
- feature/cockpit-analysis-inventory: cadence, period indexing and upstream sorting; already contains cockpit-sort-period.
- bugfix/cockpit-table-filter-no-reanalysis: local widget queries are display-only events.
- bugfix/cockpit-frozen-annual-publication: fixed annual release and final UI; retain manual-only customer mode and the full persisted analysis behind short risk lists.
- feature/cockpit-8765-deploy-record: maintained public entry is 8765; retain historical deployment records.
- feature/process360-customer-ontology: generation tools and contracts only; no customer workbook, catalog or credentials.
- feature/ywln-ontology-element-definitions: ontology definitions, without adding runtime capabilities.
- Excluded: feature/releases-0-1-6-to-0-1-10, archived and experimental branches. No version, tag or Release operations.

## Integration resolutions

1. Page filter commits cannot arm automatic analysis in customer fixed-annual mode.
2. Sorting and pagination keep the original AP request and receipt for exact evidence scope validation.
3. Widget notifications keep scope:false; the host does not start analysis from them.
4. Customer Docker builds explicitly require an external seed context, matching the delivered image without committing its data.

## Validation

392 targeted Python tests passed; 98 Cockpit Node tests passed. No live model calls, task dispatch or deployment. Additional final validation is recorded in the MR.
