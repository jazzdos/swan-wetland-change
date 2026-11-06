# 0009 Fill dea_wo_agreement at processing time

Status: accepted, 2026-11-06; approved by Jarrod on 2026-11-06.
Amends the Decision of 0002.

## Context

`dea_wo_agreement` is null on every observation row. 0002 said the verify step
fills it while the provisional product retains the pass, but nothing writes it:
`verify` computes the agreement for its own sample and puts it in the report,
not in the observation rows. DEA keeps the Sentinel-2 Water Observations
product (`ga_s2_wo_provisional_3`) for about three months, so a row cannot be
filled long after it is written, and backfill rows for older acquisitions have
no WO item to compare with.

The open question was whether the DEA item exists when the daily run first
processes a scene-tile. If it usually does, the run can store the agreement
when it writes the row. If it usually does not, the column cannot be filled
from the daily run either.

## Decision-making

This decision was made by the orchestrator under Jarrod's delegation of it, using
the rule pre-registered in LEARNINGS.md before the measurement ran. The rule
has two conditions: populate only if the share available at first processing
is at least 0.50, and only if a DEA failure provably cannot fail the daily run,
proven by a test; otherwise amend. The first is met by the measurement below.
The second is met by `test_process_scene_survives_dea_errors` and
`test_run_once_with_failing_lookup_still_processes_the_scene`. It is not
Jarrod's decision; Jarrod approved it on 2026-11-06.

Disclosure: before the pre-registration was written the planner ran an
exploratory, unrecorded pass that found a WO item before the first cron for 49
of 49 scene-tiles. That pass had a pagination bug. The recorded result
therefore matches an outcome the planner already expected, and is not a blind
confirmation.

## Evidence

The hypotheses, sample, timestamps and decision rule are in LEARNINGS.md under
'Pre-registered hypotheses (st-5f74, 2026-11-06)'. The result is under 'DEA WO
availability at first processing (2026-11-06)'. The script ran once live on
2026-11-06 against Earth Search and the DEA explorer.

Files, with sha256:

- `docs/research/2026-11-06-wo-availability.py` sha256 `bf8ad1ec542051b520c85b529b19c895162260e905bd44011636023c1066e9ef`
- `docs/research/2026-11-06-wo-availability.csv` sha256 `5da7dde97a18916b8dbfb0e6610bf6c4b256709574ded8d87d3fd6eca2b418e6`
- `docs/research/2026-11-06-wo-availability.txt` sha256 `bfe20379b9b9a53588497a7251445884594f9089e9b49d071314efd2d938cbe6`

Share available at first processing: 44 of 44
Chosen outcome: populate

- Wilson 95 percent interval for the share: 0.9197 to 1.0000.
- Lag (DEA index time minus the first scheduled run at or after the Earth
  Search `created` time, hours, nearest rank over the 44 scene-tiles): min
  -22.963, p25 -2.824, median -1.942, p75 -1.369, p90 -1.196, max -0.352. The
  smallest margin is 21 minutes.
- Scene-tiles with no WO item at measurement time: 0 of 44. Scene-tiles whose
  WO item arrived after first processing: 0 of 44.
- Sensitivity: with the run instant moved 2 hours later the share is also 44
  of 44.

Limits:

- The bbox `[115.3, -33.2, 116.0, -31.6]` approximates the AOI union bbox, so a
  scene-tile touching only the real AOI edge could differ.
- The cron instant (10:17 UTC) ignores scheduler delay and run duration. A
  delay of more than about 21 minutes on the least favourable scene-tile would
  make that row null.
- A_wo is the DEA STAC index time (`properties.created`), not a documented
  product-ready time.
- The sample is 44 scene-tiles over 81 days of one season, with cloud cover of
  at most 20. It says nothing about a DEA outage or a processing backlog later
  in the year.

`tests/test_config.py` checks the digests and recomputes the share and the
outcome from the committed CSV.

## Decision

The daily `run` fills `dea_wo_agreement` for each polygon and scene when DEA
holds the WO item for that scene at that time.

- The value comes from `src/wetland_change/verify/wo.py`
  (`resolve_scene_wo`, `observation_agreement`). It uses the same `wo_check`,
  the same polygon water setting from `WaterConfig.for_polygon` and the same
  WO clear rule as the verification report, and `run` passes
  `verify.min_clear_pixels` (100 in `config/pipeline.toml`) as the floor, as the
  report does, so it equals the report value for the same polygon and scene
  and is None where the report records a skip for too few clear pixels.
- It is None when there is no WO item, when fewer than `verify.min_clear_pixels`
  pixels are mutually clear (including none), or when the WO grid differs from
  the scene grid.
- Any DEA error is logged as a warning and gives None. A DEA outage cannot
  fail the run or a scene. An error on a scene marks that scene's WO failed, so
  it is not retried for the scene's other polygons and an outage costs at most
  one retry cycle per scene.
- The column means the agreement at first processing. A row whose WO item
  arrives later stays null and is never filled afterwards.
- Backfill rows stay null: `backfill` does not pass the lookup.
- Rows written before this change stay null.
- `n_clear` can differ slightly from the pixel set the agreement is computed
  on, because the agreement mask omits the red band, as `wo_check` does.
- The daily run now makes one DEA STAC call per scene plus a grid open and a
  window read per polygon.

Tests (`tests/test_wo_observation.py`):

- `test_observation_agreement_equals_wo_check_measured`: the stored value is
  the `wo_check` measured value.
- `test_override_changes_the_number`: a per-polygon water setting changes the
  value.
- `test_none_when_wo_grid_differs`, `test_none_without_a_mutually_clear_pixel`
  and `test_resolve_scene_wo_none_when_lookup_finds_nothing`: the None cases.
- `test_none_below_the_min_clear_pixels_floor`,
  `test_process_scene_applies_the_min_clear_pixels_floor` and
  `test_run_once_applies_the_verify_min_clear_pixels_floor`: a count below the
  floor gives None, a count equal to it is scored, and `run` takes the floor
  from `verify.min_clear_pixels`.
- `test_lookup_error_gives_none_and_warns`,
  `test_reader_factory_error_gives_none_and_warns`,
  `test_reader_error_gives_none_and_warns` and
  `test_process_scene_survives_dea_errors`: DEA errors give None and do not
  fail the scene.
- `test_failed_scene_wo_is_not_retried_for_the_next_polygon`: one retry cycle
  per scene.
- `test_process_scene_fills_the_column`: the column is filled and nothing else
  in the row changes.
- `test_run_once_with_failing_lookup_still_processes_the_scene`: a failing
  lookup does not fail the run.
- `test_run_once_stores_agreement_and_is_byte_identical`: the stored value
  round-trips and a rerun is byte identical.
- `tests/test_cli.py::test_only_run_passes_the_dea_wo_lookup`: `run` passes
  the lookup and `backfill` does not.

## Consequences

Observation rows written from this change on carry the agreement at first
processing when DEA held the item then, so a reader can see the third water
signal per row without waiting for `verify`. The `run` stage depends on DEA for
this value but not for success. A late or missing DEA item leaves a null that
cannot be filled later, and the null share is expected to rise if DEA's
processing slows. Whether the share holds beyond one season is not tested here.
