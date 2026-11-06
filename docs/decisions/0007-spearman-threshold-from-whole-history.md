# 0007 Spearman threshold from the whole stored history

Status: accepted, 2026-11-06.

## Context

The design (`docs/plans/2026-10-29-swan-wetland-change-design.md`, line 227)
asks for a Spearman rho of at least 0.9 between the pipeline and DEA
Waterbodies "over the backfill". Hypothesis H4 measured 0.858 to 0.897 on the
2026-11-03 report and was recorded as not supported (LEARNINGS.md, "Backfill
hypotheses").

A window of stored passes is too noisy to gate on. The 2026-11-05 read-only
measurement scored the check over 365 days at 13 monthly run ends from
2025-11-03 to 2026-10-29. Per-lake rho ranged from 0.627 to 0.927, and no run
end had all four lakes at or above 0.9 (3 of 52 lake and run end scores
reached 0.9). Its script and rows are
`docs/research/2026-11-05-spearman-windows.py` and
`docs/research/2026-11-05-spearman-windows.csv`; the script ran against commit
46e0e20, before `history_days` was removed, so it does not run on the branch
head.

Jarrod chose option C on 2026-11-06: score the check over the whole stored
history, as the design says, and calibrate `spearman_min` instead of keeping
0.9.

## Decision

The Spearman check scores every stored succeeded pass up to the newest scene
of the verified run. There is no window, and `[verify.waterbodies]
history_days` is removed. Per-pass checks still cover the verified run only.

`spearman_min` is set by the ADR 0005 rule: the lowest per-lake whole-history
rho minus 0.02, rounded down to two decimals. The lowest rho is 0.8555 (Lake
Clifton), which gives:

```
spearman_min = 0.83
```

`spearman_min_pairs` stays 10 and `max_day_gap` stays 3.

## Evidence

Script `docs/research/2026-11-06-spearman-calibration.py` calls the gate's
own code path per lake: `_history_paths` intersected with the `observations`
listing, `read_observations`, then `waterbody_checks` with `history` set.
Rows are in `docs/research/2026-11-06-spearman-calibration.csv` and the
reconciliation summary is in
`docs/research/2026-11-06-spearman-calibration.txt`.

| lake | rho | n pairs | first datetime | last datetime |
|---|---|---|---|---|
| Forrestdale Lake | 0.8608 | 88 | 2022-12-17 | 2026-09-17 |
| Lake Clifton | 0.8555 | 95 | 2022-12-07 | 2026-10-02 |
| Lake Preston | 0.8568 | 96 | 2022-12-07 | 2026-10-02 |
| Thomsons Lake | 0.8932 | 93 | 2022-12-17 | 2026-10-12 |

The newest scene is 2026-10-29T02:27:01Z. The script read 1147 observation
files, 235,595,220 bytes, holding 333,004 lake rows. The lowest rho is
0.8554980859546633, and floor((0.8554980859546633 - 0.02) * 100) / 100 is
0.83.

The gate's rho and pair counts differ from the H4 report (0.870 with 93,
0.858 with 98, 0.861 with 98, 0.897 with 99 for Forrestdale, Lake Clifton,
Lake Preston and Thomsons). The script reproduces the H4 numbers exactly
with the pairing used before commit 00e8fb0 (datetime-only de-duplication),
and the gate's tile and date de-duplication, committed after the H4 report,
drops 24, 6, 6 and 12 rows, which lowers rho by 0.0088, 0.0028, 0.0038 and
0.0041 and the pair counts by 5, 3, 2 and 6. No stored row falls outside the
H4 date range, so the range does not contribute.

Files, with sha256:

- `docs/research/2026-11-06-spearman-calibration.py` sha256 `2fc319de9b325b614ab66768d3cb2073133abe8ccf8daa759db4341d405c185e`
- `docs/research/2026-11-06-spearman-calibration.csv` sha256 `058314ac22d6309a0d8e9c2a98d5fdd2fb6fbda04280b71eeff726f22d79825e`
- `docs/research/2026-11-06-spearman-calibration.txt` sha256 `027cec5cfc862eddfd0f3b784ea6154860a593a28260014b1984150399b5e6d2`
- `docs/research/2026-11-05-spearman-windows.py` sha256 `5e01fb0e1f5d43b2a6c962428912ff1fb4d6938b4770dfe65b92c99e91f2fbe7`
- `docs/research/2026-11-05-spearman-windows.csv` sha256 `123f00c8a265b0ceeb9f292b4a98127fe045a5316a44f79872dd75cb1f2a13e0`

`tests/test_config.py` checks the values above against the committed files.

## Limits

- The threshold is calibrated on the same backfill it then gates, so passing
  is not an independent test.
- H4 is not supported. The design's 0.9 was met on none of the four lakes,
  under either the legacy pairing (highest 0.897) or the gate's (highest
  0.893).
- Each verify reads every stored observation file. Today that is 1147 files
  and 235,595,220 bytes, and it grows with each pass. Whole objects are
  fetched, so reading only the Spearman columns, which `read_observations`
  already does, cannot reduce the bytes transferred. Column projection is not
  a small change and is not made here.
- S3 read time is unmeasured because AWS calls were out of scope (epic
  st-f849). `verify.yml` gives the verify step a 20 minute timeout.
- DEA Waterbodies is refetched at each verify. A series fetched at a different
  time can shift rho.

## Consequences

Verify passes the Spearman check on the current backfill by construction.
Per-pass checks can still fail: in the H4 report Lake Clifton failed 53 of
98 paired passes under the legacy pairing. Re-calibrate by rerunning the
script when the backfill grows materially, and update `spearman_min` and the
sha256 values here together.
