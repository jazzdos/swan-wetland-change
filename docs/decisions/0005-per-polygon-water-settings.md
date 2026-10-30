# 0005 Per-polygon water settings

Status: accepted, 2026-10-30. Amends 0002.

## Context

One global water setting (`[water]`: MNDWI above -0.1, agreement_min 0.91,
from spike S2) fails `water_vs_dea_s2_wo` on three Ramsar polygons. Pooled
agreement with DEA Sentinel-2 Water Observations at the global setting is
0.6311 on ramsar-15, 0.9296 on ramsar-28 and 0.9541 on ramsar-56
(LEARNINGS.md, "Per-polygon water calibration"). There is no agreed
literature or industry method for choosing a water index threshold; the
best threshold varies by site and water type (Ji et al. 2009; Fisher et al.
2016). The threshold is therefore set empirically per polygon against DEA.

No NDWI or MNDWI threshold works on ramsar-15. On the live re-run of the
2026-10-12 pass, green BOA reflectance is at or below 0 on 74 percent of
the pixels DEA calls wet (median -0.0006), and the DEA-wet pixels the
indices miss have MNDWI median -1.2. SCL class 6 agreement with DEA is
between 0.9384 and 1.0000 on all 10 ramsar-15 passes.

## Decision

`config/pipeline.toml` holds per-polygon overrides as
`[water.overrides.<polygon_id>]` tables with `method`, `threshold` and
`agreement_min`. `method` is `ndwi`, `mndwi` or `scl6`. `scl6` counts SCL
class 6 pixels as water, takes no threshold, and is accepted only in an
override. The config loader rejects an unknown method, a threshold outside
[-1, 1], an index method without a threshold, an `scl6` override with one,
and an agreement_min outside [0, 1]. A polygon without an override uses the
global `[water]` method, threshold and agreement_min.

| polygon | method | threshold | pooled agreement | agreement_min |
|---|---|---|---|---|
| ramsar-15 | scl6 | none | 0.9682 | 0.94 |
| ramsar-28 | ndwi | -0.15 | 0.9438 | 0.92 |
| ramsar-56 | mndwi | 0.05 | 0.9795 | 0.95 |
| every other polygon | mndwi | -0.1 | 0.9303 (S2, four lakes) | 0.91 |

agreement_min is pooled agreement minus 0.02, rounded down to two decimals,
the S2 convention. `water_ha_index` for each polygon comes from its own
setting (`summarise` in `src/wetland_change/stats.py`).
`water_vs_dea_s2_wo` (`src/wetland_change/verify/wo.py`) scores each
polygon with its own method and threshold, passes or fails it against its
own agreement_min, and reports that agreement_min as the check threshold.

Jarrod chose SCL class 6 for ramsar-15 on 2026-10-30 (story st-2048,
option a). The alternatives were NDWI above -0.45 (pooled 0.7814, failing
6 of 10 passes at its own agreement_min of 0.76) and leaving ramsar-15 on
the global setting (0.6311).

## Amendment to 0002

0002 defines `water_ha_index` as the configured index and threshold. It now
means the polygon's configured water setting, which for an `scl6` override
is SCL class 6. For ramsar-15 `water_ha_index` equals `water_ha_scl`, so
0002's use of disagreement between the index and SCL as a quality flag
does not apply there. The three water columns and their names are
unchanged.

## Limits

The calibration covers August to October 2026 only: 12 dates or fewer per
polygon (10 passes for ramsar-15, 22 for ramsar-28 and 19 for ramsar-56;
dates seen on two tiles were pooled twice). Leave-one-date-out agreement is
0.9682, 0.9434 and 0.9788, and the winning setting does not change when any
one date is held out. DEA S2 WO is itself unvalidated, so agreement
measures consistency with DEA, not accuracy. The expected result on passes
after 2026-10-29 is pre-registered in LEARNINGS.md (hypothesis 5).

## Consequences

Observation rows do not record the water setting that produced them. Rows
for ramsar-15, ramsar-28 and ramsar-56 written before this change used the
global setting; the run manifest's `config_sha256` identifies the config
behind each row. A change baseline that spans the switch mixes the two
settings for these polygons until those rows are recomputed.

Evidence: `docs/research/2026-10-29-polygon-calibration.csv` (sha256
d453325a537f87e26c121c7c634f7b06b605a2151c58696b8aa5922bc22ed325), produced
by `scratch/spikes/polygon_calibrate.py` (untracked, sha256
99f2cab082da69a4598843b62eafb74f7807372f1ea904fdec86defab43fd14c).
