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

## Addendum 2026-11-05: compaction and a single ledger read

Daily runs add parts (one per scene, plus one for rejected items), so a read
costs one request per part. Compaction merges them.

- `compact_ledger` writes every row of the read table to
  `ledger/compacted/ledger_compact_<run_id>.parquet`, reads that file back and
  checks the row count, and only then deletes the parts it merged (the paths
  it was given, so a part written after the listing survives). The bucket is
  public and unversioned, so a delete is permanent; a crash between the write
  and the deletes leaves duplicates, never losses.
- Reads drop duplicate rows, compared on the whole row, whenever a compacted
  file is listed beside other parts. Not on `(item_id, run_id, processed_at)`,
  because rows of one run share `processed_at`.
- The threshold is 25 parts (`COMPACT_MIN_PARTS`). `run` and `backfill` check
  it after the manifest is written; a failed compaction is logged and does not
  fail the run. The first run against a bucket seeded by a backfill therefore
  compacts that backfill's parts automatically and deletes them from the
  unversioned bucket. `requeue` does not compact.
- `wetland-change compact-ledger` runs the same merge by hand for any two or more parts.
  Run it when no workflow is running: a concurrent reader that
  lists a deleted part re-lists once and fails on a second miss.
- Because compaction removes part names, a run id is also refused when it
  appears in the ledger's `run_id` column, not only when a part or manifest
  with that id exists.
- A run lists and reads the ledger once, at the start, and holds the final
  table (that read plus the entries the run wrote) in memory. Scoring, the
  catalogue build and compaction use that table instead of reading again.
  Scoring skips an observation file only when the ledger shows all its rows
  fall in UTC months outside the months of the dates being scored; a file with
  no ledger row is always read.
