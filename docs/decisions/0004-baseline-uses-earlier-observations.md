# 0004 Change baseline uses only earlier observations

Status: accepted, 2026-10-30.

## Context

Stage 7 scores each new observation against a per-polygon, per-month-of-year
baseline: the median and scaled MAD of `water_ha_index` and `ndvi_median`
(`src/wetland_change/change.py`). The baseline is read from observation
files already in the store. The choice was between building it from all
stored rows or from earlier rows only.

## Decision

The baseline for a scored UTC acquisition date D, polygon P and calendar
month M is built only from stored observation rows of polygon P in month M
acquired on UTC dates strictly before D. The day's own rows, including
partner-tile rows of the same date, and every later row are excluded.

Scoring is done on the daily aggregate (`daily_aggregate`), so a polygon on
a tile seam uses all same-date rows. Flagged rows are written to
`changes/year=YYYY/tile=<MGRS>/chg_<item_id>.parquet` under the aggregate's
primary item.

## Consequences

The scored row never dilutes its own baseline. Rescoring an item over an
unchanged store, or after later observations arrive, gives the same result,
so change files are reproducible and rerunning is byte-identical.

An out-of-order backfill (older dates arriving after newer ones are scored)
changes the newer items' baselines. `wetland-change score --start --end` is
rerun after a backfill, and it deletes a change file whose item is no longer
flagged.

The earliest dates have fewer than the minimum samples
(`MIN_BASELINE_SAMPLES` in `change.py`) and are never flagged.

All observation files are listed and read on each scoring call, which is
acceptable at current store size.

## Addendum 2026-11-05

`run_once` also rescores the later stored dates of the same polygon and month
whenever it stores an earlier-dated observation
(`score_changes(..., rescore_later=True)`). Their baselines gain the new
observation, so the incremental change files equal a full rescore.
