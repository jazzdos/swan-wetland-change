# 0003 Ledger is fixed-schema Parquet, not stac-geoparquet

Status: accepted, 2026-10-29. Deviates from the design doc, which named
stac-geoparquet for the ledger.

## Context

stac-geoparquet infers an Arrow schema from each batch of items. Earth
Search items carry optional properties that vary across baselines and
dates, so ledger files written on different days do not union without
schema reconciliation, and a failed or rejected item has no item at all.

## Decision

`ledger/year=YYYY/ledger_<run_id>.parquet` uses one fixed Arrow schema
(`LEDGER_SCHEMA`) with the full source item as a JSON string column.
stac-geoparquet is used in Milestone 2 for the catalogue's
`items.parquet` asset, where every row is a valid item of one collection.

## Consequences

The ledger reads with one `cast`; watermark, seen keys and retries are
plain column operations. The catalogue is rebuildable from the ledger's
`source_item` column alone.
