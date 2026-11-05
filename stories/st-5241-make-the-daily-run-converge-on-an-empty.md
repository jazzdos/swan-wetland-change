---
id: st-5241
title: Make the daily run converge on an empty or far-behind output root
type: bug
epic: st-f849
priority: P1
depends_on: []
touches: [config/pipeline.toml, infra/README.md, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/pipeline.py, tests/test_infra.py, tests/test_pipeline.py, tests/test_verify.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

With no ledger, watermark returns None, so discovery has no created or datetime bound and finds at least 1147 scenes. run_once writes the ledger only after the whole loop (src/wetland_change/pipeline.py:319) and pipeline.yml cancels the job at 120 minutes, so a cancelled run leaves observation files with no ledger row and the next run repeats the same oldest scenes. backfill_once checkpoints per scene and run_once does not. A ledger seeded from the backfill lets the first run skip those items but no document describes that. Fix before enabling the workflows. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 1.

## Acceptance Criteria

- [ ] run_once checkpoints the ledger after each scene so a cancelled run keeps its finished scenes
- [ ] run on a ledger with no daily watermark bounds discovery to a configured lookback window
- [ ] infra/README.md documents seeding the S3 output root from the backfill before the first scheduled run
- [ ] A test interrupts run_once after some scenes and shows the next run starts after the last finished scene

## Implementation Plan

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-5241)

The story is implementable as written. Pointers checked:
- `run_once` (src/wetland_change/pipeline.py:253-333) keeps entries in a list and calls `write_ledger` once at line 319, after the whole loop. `backfill_once` (351-438) already checkpoints one ledger part per scene (`write_ledger([entry], store, run_id=run_id, part=next_part)`) and calls `_refuse_reused_run_id` first.
- `created_from` is computed in two places: `run_once` (pipeline.py:269-271) and the `discover` CLI command (src/wetland_change/cli.py:~90-97). Both pass `None` when `watermark()` is None.
- `watermark()` (ledger.py:191) ignores `run_kind == "backfill"` rows, so a ledger seeded only from the backfill still has no daily watermark. The lookback window therefore also covers the seeded case, and `seen_keys` makes the run skip items the backfill already ledgered.
- `discover()` (catalogue/search.py) sorts `result.scenes` by `(created, item_id)`, so scenes are processed oldest-created first. After a checkpoint, `watermark` is the `created` of the last finished scene and every earlier scene is done. Retry-by-id scenes sit in the same sorted list.
- `StacConfig` (config.py:27) has `watermark_overlap_days` and no lookback field. config/pipeline.toml `[stac]` mirrors it.
- infra/README.md has no seeding section. The `backfill`, `score` and `build-catalogue` commands accept `--output-root`.
- Deviations from the story's `touches`: src/wetland_change/cli.py (the `discover` command must use the same bound or its preview lies) and tests/test_infra.py (a one-line docs guard). Both are small.
- Out of scope, owned by other review findings: ordering of ledger vs scoring vs manifest (finding 2), OIDC session length (finding 3), base_url (finding 4).

## Steps

1. Config. Add `initial_lookback_days: int = Field(default=30, ge=1)` to `StacConfig` in src/wetland_change/config.py, with a comment saying it bounds the `created` filter of a run that has no daily watermark. Add `initial_lookback_days = 30` to `[stac]` in config/pipeline.toml.
2. Shared bound helper in src/wetland_change/pipeline.py: `discovery_created_from(stac: StacConfig, *, before: datetime | None, now: datetime) -> datetime`. It returns `before - timedelta(days=stac.watermark_overlap_days)` when `before` is set, else `now - timedelta(days=stac.initial_lookback_days)`. It never returns None. Use it in `run_once` and in the `discover` command in src/wetland_change/cli.py (with `datetime.now(UTC)` as `now`, imported from pipeline).
3. Checkpointing in `run_once`:
   - Call `_refuse_reused_run_id(store, run_id)` first. Part numbering restarts at 0, so a reused run id would overwrite parts.
   - Write the rejected entries as part 0, when there are any, before the scene loop. They carry no `created`, so they cannot move the watermark.
   - Inside the scene loop, after `_process_one`, call `write_ledger([entry], store, run_id=run_id, part=next_part)` and add its result to `manifest.ledger_files`. Do this before updating `written_dates` and before `_tally`.
   - Remove the single end-of-loop `write_ledger`. Keep `manifest.watermark_after = watermark(read_ledger(store))`, scoring, the manifest write and the catalogue build exactly as they are.
   - Update the docstring to say the ledger is checkpointed per scene and an interrupted run resumes after its last finished scene.
   - Log at INFO which bound is in use (watermark or lookback) and its value.
4. Docs in infra/README.md: a new section "Seeding the output root before the first scheduled run", placed after "Repository variables". It covers:
   - why: an empty root means no watermark, so the first run is bounded only by `stac.initial_lookback_days` (default 30) and a larger backlog takes several jobs;
   - the sequence, run once by the operator with write access to the bucket: `uv run wetland-change backfill --start 2022-12-01 --end <today> --output-root s3://<bucket>/`, then `score --start ... --end ... --output-root ...`, then `build-catalogue --output-root ...`;
   - choose an `--end` no earlier than today minus `initial_lookback_days`, or scenes acquired after the backfill end and created before the lookback start are never seen;
   - backfill rows are tagged `backfill`, so the daily watermark stays empty. The first scheduled run applies the lookback window and skips everything already ledgered;
   - a cancelled or timed-out run keeps its finished scenes, so rerun the workflow to continue;
   - the scenes of a cancelled run are not scored until `wetland-change score` is run over their dates.
5. Tests (write first, see red, then implement).

## Tests and what each proves (tests/test_pipeline.py unless stated)

- `test_run_once_interrupted_keeps_finished_scenes_and_resumes`: four copies of the fixture item with distinct ids, product_uris, `created` and `updated`. A `RasterioReader` subclass raises `KeyboardInterrupt` in `open_grid` on the 3rd scene, and run 1 raises it through `run_once`. The test proves the ledger has exactly 2 succeeded rows (one part file each) and 2 observation files, no `runs/<id>.json`, and `watermark` equals the 2nd scene's `created`. Run 2, with a normal reader at `NOW + 1 day` and a recording client, proves `skipped_seen == 2`, `processed == 2`, `manifest.observation_files` holds only scenes C and D, the first run's observation files are byte-identical, the search `created.gte` equals `watermark - 1 day`, and the ledger ends with 4 succeeded rows.
- `test_run_without_watermark_bounds_discovery_to_lookback`: an empty store with a recording client proves the main search sends `query.created.gte == NOW - 30 days` in RFC3339 `Z` form. With `initial_lookback_days=7` set via `model_copy` it sends `NOW - 7 days`.
- `test_run_after_backfill_only_ledger_uses_lookback_and_skips_seeded_items`: `backfill_once` on the fixture item, then `run_once`. It proves the run still has `watermark_before is None`, sends the lookback bound, and gets `processed == 0` and `skipped_seen == 1`. This backs the README seeding claim.
- `test_stac_config_rejects_zero_lookback`: `initial_lookback_days=0` raises `ValidationError`.
- Update `test_run_once_tags_rows_and_manifest_as_run`: `ledger_files` becomes `[f"ledger/year=2026/ledger_{run_id}_00000.parquet"]`.
- `test_run_once_refuses_reused_run_id`: a second `run_once` with the same `now` on the same store raises `ValueError` matching "run id". If an existing test reruns with an identical `now`, bump that test's `now` and keep the guard.
- tests/test_infra.py `test_readme_documents_seeding_from_backfill`: `_read("README.md")` contains "backfill", "initial_lookback_days" and "--output-root s3://".

## Verification (AGENTS.md order, one per line)

```
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src scripts
uv run pytest -q
```

Keep `PROJ_LIB` unset. Watch tests/test_golden_run.py and tests/test_cli.py, which exercise `run_once` and `discover`.

## Implementation Notes

- 2026-11-05T09:33:19.274Z: Gates on the story branch: ruff check, ruff format --check and mypy pass; pytest 460 passed, 1 skipped in default mode and with GITHUB_ACTIONS=true. Touches beyond the planned list: src/wetland_change/cli.py (discover uses the same bound), tests/test_infra.py (docs guard), tests/test_verify.py (run id). run_once now refuses a reused run id, which overlaps st-fbe8. Scenes finished by a cancelled run are ledgered but not scored by the next run; infra/README.md tells the operator to run score over their dates, and st-ca25 owns the code fix.

## Questions
