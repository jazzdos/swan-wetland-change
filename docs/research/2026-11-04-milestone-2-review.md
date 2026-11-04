# Milestone 2 review: code paths that have never run

Date: 2026-11-04
Scope: `src/`, `.github/workflows/`, `infra/` at `2049247` (origin/main), reviewed against
`docs/plans/2026-10-29-swan-wetland-change-design.md` and the Milestone 2 epics
(st-70d1, st-93a8, st-f849, st-1d45).
Status: read-only review. Nothing was fixed.

## Method

`kit:code-review` ships a workflow that reviews only a diff, so an inline workflow of the
same shape ran over the whole tree. Six reviewers ran: one per question 1 to 4, a design
conformance reviewer for question 5 on claude-opus-5-5 at xhigh, and a runtime reviewer
covering stdout, exit codes, GDAL reads and public data exposure. Every finding then went
to an adversarial verifier on claude-opus-5-5 at xhigh. The verifier was told to refute
the finding and could return CONFIRMED, PLAUSIBLE, REFUTED or KNOWN. A final quality gate,
also on claude-opus-5-5 at xhigh, re-read the code, re-ran the reproductions, merged
duplicates and ranked the survivors. Of 40 raw findings, 35 survived verification and
5 were refuted. The gate merged the 35 into 7 ranked findings and 9 lower-priority items.

Verdicts:

- CONFIRMED means the code path is unambiguous or the failure was reproduced offline.
- PLAUSIBLE means the code path is real, but the outcome depends on AWS, GitHub or network
  behaviour that cannot be checked offline.

The reproduction scripts cited below were written to `scratch/` in the review session.
`scratch/` is gitignored, so they are not in this commit. Each finding gives the command
and its output.

The known items (st-7432, st-1731, st-06a8, and DEA reachability from runners) are not
reported again. What the workflows do when DEA is unreachable is in finding 5.

## Answers by question

1. S3.
   - First run against an empty bucket: it does not converge (finding 1).
   - Partial upload: it cannot leave a truncated object. A kill before the ledger write
     loses the run's progress (findings 1 and 3). A failure after the ledger write loses
     the run's change files and its manifest (finding 2).
   - Rerun after a completed run: it is incremental and sound.
   - Permissions: the role covers every call that pyarrow makes. This was checked against
     a fake S3 that denies every other action.
2. OIDC and credentials.
   - Every S3 step comes after the credential step, and the job permissions match what
     each step does.
   - The one-hour session against the 120-minute job is a gap (finding 3).
3. Schedule.
   - First scheduled run: see finding 1.
   - Step failures: covered in findings 1, 2 and 5 and in lower-priority items 1 and 7.
   - Both workflows queued at once: the shared concurrency group serialises them, and the
     two crons are 12 hours apart. A pending run that is replaced in the group is
     cancelled without an issue (lower-priority item 7).
   - Report commit: under the pushed state of main it stages only the new report, and its
     rebase and push work from the depth-1 checkout (reproduced against a local bare
     repo). It runs only on days that processed a scene, so while finding 1 holds no
     commit lands.
4. Incremental behaviour.
   - Backfill resumes correctly.
   - The daily run does not resume after an interrupt (finding 1).
   - It permanently loses scoring after a late failure (finding 2).
   - It drops exhausted scenes with no way to requeue them (finding 6).
   - It leaves change files stale when scenes arrive out of order (finding 6).
5. Design conformance.
   - Success criterion 1 is blocked by findings 1 and 3, criterion 2 by finding 4,
     criterion 3 by lower-priority item 2, and criterion 4 by finding 5.
   - Seven matrix rows have no check in the verification JSON: index arithmetic,
     GeoParquet, STAC, incremental, change detection, scheduled job alive and end to end.
     The water history Spearman row always skips in steady state (finding 5).

## Findings

### 1. First scheduled run on an empty bucket crawls the whole archive with no checkpoint and never converges

- Location: `src/wetland_change/pipeline.py:293`
- Severity: critical
- Verdict: CONFIRMED

What fails on a real run:

With no ledger, watermark() returns None (ledger.py:199-200), so created_from is None (pipeline.py:269-271). build_search_kwargs then sends only the eo:cloud_cover query, with no created or datetime bound (catalogue/search.py:121-123, 132-135). The first `run` discovers the whole Collection 1 history over the AOI: at least 1147 scenes (docs/research/2026-11-03-backfill-hypotheses.md:31). run_once processes them one at a time and keeps ledger entries in memory (pipeline.py:291-308). Its only write_ledger is at :319 and write_manifest is at :331. The CLI echoes the manifest only after run_once returns (cli.py:132). pipeline.yml:38 cancels the job at 120 minutes. The cancel arrives as SIGINT, which raises KeyboardInterrupt; `except Exception` at pipeline.py:148 does not catch it. A hard kill has the same effect. Either way no ledger, manifest or catalogue is written. Observation files stay in the public bucket with no ledger row. The next day sees the same empty ledger, sorts by created ascending (search.py:214) and redoes the same oldest scenes, so the schedule never progresses. Catalogue, verify and the report commit never run, so no daily commit lands. The same stall applies to any backlog bigger than one job can finish, about 50 scenes at the measured single-process rate. infra/README.md, the workflows and the Milestone 2 stories have no seeding step. Milestone 1 seeded its watermark by hand (docs/handoffs/2026-10-29-milestone-1.md:113-115). The failure is not silent: on an empty ledger the weekly verify exits 2, freshness fails, and an issue opens.

Evidence:

The gate re-ran the offline repro: `env -u PROJ_LIB uv run --no-sync python scratch/adv_firstrun_cancel.py`. It uses the shipped config and 10 fixture copies, with a reader that raises KeyboardInterrupt on the 6th scene. Run 1 and run 2 print the same lines: `search query={'eo:cloud_cover': {'lt': 20.0}} datetime_in_kwargs=False`, `scenes finished before cancel=5`, `store after: {'ledger': 0, 'runs': 0, 'observations': 5, 'stac': 0, 'changes': 0}`, `ledger rows=0 watermark=None`.

Scale: fitting 1147 scenes into 7200 s needs about 6.3 s per scene. The repo records 138.7 to 152.3 s of single-process runner time per scene (backfill-hypotheses.md:49). Its optimistic estimate was 25 s per scene, about 8 h in total.

backfill_once checkpoints after every scene (pipeline.py:431-434); run_once does not.

Counter-check: `scratch/adv_firstrun_backfill_seeded.py` shows that a ledger holding succeeded backfill rows lets the first run skip those items through seen_keys (ledger.py:217-225), even though watermark() stays None (ledger.py:201). Copying the local backfill root to S3 is therefore a workable seed, but no document describes it.

The only external input is runner speed. A GitHub runner would need to be more than 20 times faster than any figure the repo records.

Proposed story: Make the daily run converge on an empty or far-behind output root

Acceptance criteria:

- run_once checkpoints the ledger after each scene so a cancelled run keeps its finished scenes
- run on a ledger with no daily watermark bounds discovery to a configured lookback window
- infra/README.md documents seeding the S3 output root from the backfill before the first scheduled run
- A test interrupts run_once after some scenes and shows the next run starts after the last finished scene

### 2. Ledger is committed before scoring and the manifest, so a failure after line 319 permanently loses change files and the run record

- Location: `src/wetland_change/pipeline.py:319`
- Severity: important
- Verdict: CONFIRMED

What fails on a real run:

write_ledger at pipeline.py:319 marks the run's scenes succeeded. Three steps come after it with no handler: score_changes (322-329, which first GETs every observation file at pipeline.py:207), write_manifest (331) and build_and_write (332). Any of these can fail: an S3 error that outlasts pyarrow's SDK retries, expired credentials, the 120 minute job timeout, or a scoring or catalogue validation error. When one raises, the CLI exits 1 with empty stdout (cli.py:132). The manifest step then reads processed=0 (pipeline.yml:92-96), and catalogue, verify and commit are skipped.

On the next run seen_keys (pipeline.py:278) skips those scenes. written_dates (292, 306-307) is empty, so score_changes is never called for their dates. The run's change files, runs/<run_id>.json and verification/<run_id>.json are never written, and latest_run_id (verify/run.py:83-93) cannot see a run that has no manifest. The crash day is red. Every later day is green with processed=0, and nothing detects the gap. Recovery needs a manual `score --start --end`.

The catalogue does recover on the next run, because build_and_write rebuilds it from the ledger (stac/catalogue.py:275-281), but without a change asset. A failure in build_and_write alone loses nothing, but still skips that day's verify and commit. This contradicts the design's statement that reruns are safe (design.md:93).

Evidence:

The gate re-ran the offline repro: `PYTHONPATH=. env -u PROJ_LIB uv run --no-sync python scratch/adv_ledger_score/repro.py | grep -E '^(CONTROL|CRASH|NEXT|DAY)'`. It seeds six prior Octobers so the fixture date is flagged, then runs the real CLI `run` with score_changes raising OSError. Output:
- `CONTROL: processed 1 change_rows 2 change_files ['changes/year=2026/tile=50HLK/chg_S2C_T50HLK_20261027T022351_L2A.parquet'] runs/ ['runs/20261105T100000Z.json']`
- `CRASH CLI exit 1 | stdout bytes 0`
- `CRASH ledger status: ['succeeded']`
- `CRASH runs/ [] changes/ [] latest_run_id None`
- `NEXT: discovered 0 skipped_seen 1 processed 0 failed 0 change_rows 0 change_files []`
- `DAY+4: processed 0 changes/ []`

backfill_once never scores, so the loss is specific to the ordering in run_once.

Proposed story: Make change scoring survive a failure after the ledger write

Acceptance criteria:

- A failure in score_changes or write_manifest leaves the run's scenes eligible for scoring on the next run
- The next run writes the change files and a manifest that the crashed run left unwritten
- A test forces score_changes to raise once and shows the change file exists after the following run

### 3. OIDC credentials last one hour against a 120 minute job and are never refreshed, so any run past 60 minutes writes nothing and repeats

- Location: `infra/main.tf:106`
- Severity: important
- Verdict: PLAUSIBLE

What fails on a real run:

aws_iam_role.pipeline (infra/main.tf:106-109) sets no max_session_duration, so the role maximum is the AWS default of 3600 s. pipeline.yml:63-68 sets no role-duration-seconds, and the pinned configure-aws-credentials defaults to 3600 s. Raising only the workflow input would make AssumeRoleWithWebIdentity fail, so both settings need changing.

The action exports static AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_SESSION_TOKEN once, before Fetch AOI. pyarrow's S3FileSystem (store.py:19) reads them and never refreshes them. COG reads stay unsigned (raster/env.py:10), so after expiry each remaining scene still does its full read and only then fails at write_observations. _process_one records each of these as failed (pipeline.py:147-161). write_ledger at :319 then raises outside any handler, leaving no ledger, no manifest, empty stdout and processed=0.

Because nothing is written, attempts never rise and the MAX_ATTEMPTS cap never ends the loop. The next run finds the same backlog and fails the same way. The trigger is any run that reaches S3 more than 60 minutes after the credential step: a catch-up of about 25 or more scenes at the measured 139 s per scene, or a run slowed by the S3 request volume in finding 7. verify.yml is not affected, because it assumes the role late and its later steps total 25 minutes.

Evidence:

The gate re-ran `PYTHONPATH=. env -u PROJ_LIB uv run --no-sync python scratch/vrf_oidc/repro.py`. It drives the real CLI `run` twice with a store that raises an expired-token OSError after three observation writes. Both runs print `exit_code=1 exc=OSError: ... The provided token has expired. (simulated)`, `stdout bytes: 0` and `observation files: 3 ledger rows: 0 manifests: 0`.

`grep -rn duration infra .github` returns nothing.

One verifier read the pinned action source (SHA e1253824): src/index.ts:21 sets `DEFAULT_ROLE_DURATION = 3600`, and src/helpers.ts:93-101 exports the three static variables.

The 3600 s role default and the STS ExpiredToken behaviour are AWS behaviour that was not exercised offline, hence PLAUSIBLE.

Proposed story: Size the OIDC session to the pipeline job

Acceptance criteria:

- aws_iam_role.pipeline sets max_session_duration to at least the pipeline job timeout
- pipeline.yml sets role-duration-seconds equal to the role maximum
- tests/test_infra.py and tests/test_workflows.py assert both values

### 4. The first real run publishes a STAC catalogue whose every link points at example.invalid

- Location: `config/pipeline.toml:46`
- Severity: important
- Verdict: CONFIRMED

What fails on a real run:

config/pipeline.toml:46 sets base_url to the placeholder https://example.invalid/swan-wetland-change. run_once (pipeline.py:332) and build-catalogue (cli.py:323) both use cfg.catalogue.base_url. The CLI has no override option and config.py reads no environment variable. pipeline.yml:78-81 and 103-105 pass only --output-root.

infra/README.md:47-61 sets only AWS_ROLE_ARN, OUTPUT_BUCKET and AWS_REGION. It never says to copy the bucket_url output (infra/outputs.tf:6-9) into the config.

build_catalogue normalises hrefs under base_url/stac (stac/catalogue.py:204) and builds every asset href from base_url (catalogue.py:110, 123, 135, 191). Every root, child, self, item and asset link in s3://<bucket>/stac/ therefore points at a reserved TLD that never resolves. stac-browser can open catalog.json from the bucket URL but cannot follow any link from it, so success criterion 2 and the STAC row are unmet (design.md:230, 344). tests/test_config.py:51-53 asserts the placeholder, so the fix also turns that test red. No workflow in .github/workflows deploys stac-browser to GitHub Pages.

Separately, pipeline.yml builds the catalogue (inside run_once and again at 101-105) before verify writes verification/<run_id>.json. The asset is added only when that file already exists (catalogue.py:129-140), so each run's report is linked one run late.

The catalogue is rebuilt from the ledger on every run, so a corrected base_url fixes every item on the next run.

Evidence:

Offline repro: `PYTHONPATH=. uv run --no-sync python scratch/adv_baseurl/repro.py` runs run_once with the repo's [catalogue] section into a local store. It prints `config base_url: https://example.invalid/swan-wetland-change`. Every catalog, collection and item link, and the observations and items.parquet assets, are under https://example.invalid/. The only other href is the Earth Search derived_from link.

`uv run python scratch/adv_catalogue_verify.py` runs build-catalogue and then write_report, in the order pipeline.yml uses. It prints `verification asset = False | report exists = True`. After the next day's run_once it prints `verification asset = https://example.invalid/swan-wetland-change/verification/20261104T100000Z.json`.

`grep base_url infra/README.md .github/workflows/*` returns nothing.

Proposed story: Publish the catalogue under the real bucket URL

Acceptance criteria:

- Every link and asset href in the published catalogue starts with the bucket_url output of infra
- infra/README.md lists setting catalogue.base_url from the bucket_url output as a deploy step
- tests/test_config.py no longer pins the example.invalid placeholder
- A run's verification asset is linked in the catalogue written by the same workflow run

### 5. verify's exit code and all_passed do not track the matrix: skipped references count as success, several rows never score, and tiny DEA polygons decide WO pass or fail

- Location: `src/wetland_change/cli.py:254`
- Severity: important
- Verdict: CONFIRMED

What fails on a real run:

cli.py:254-258 exits 3 only when a check is False and 4 only when nothing scored. checks.py:79 sets all_passed from the scored checks alone. Every DEA, Planetary Computer and Copernicus failure inside verify becomes passed=None (verify/run.py:100-117, 185-187, 207-209, 405, 432).

What the workflows do when DEA is unreachable (known item d):
- **DEA WFS down during Fetch AOI.** fetch_aoi makes one attempt with no retry (scripts/fetch_aoi.py:84-86, 98-103). pipeline.yml skips `run` (76-81), the manifest step writes processed=0, catalogue, verify and commit are skipped, and the job ends red. No issue opens, because pipeline.yml has no issue step. No state is lost, and the next run catches up from the watermark.
- **Same failure in verify.yml.** The live tests are skipped (84-86, no `if`). verify and freshness still run on the Ramsar file, and failure() opens the issue.
- **DEA reachable at fetch but not during verify.** The WO, NBART, NDVI correlation and waterbody checks skip. verify exits 0, the pipeline job is green, and the committed report says all_passed true.

Independently, water_spearman_vs_dea_waterbodies needs 10 pairs (config/pipeline.toml:53) but sees only the run's own scenes (verify/run.py:416-421), so in steady state it always skips. 7 of the 14 matrix rows have no check in verification/<run_id>.json: index arithmetic, GeoParquet, STAC, incremental, change detection, scheduled job alive and end to end. Freshness only prints its results. Success criterion 4 (design.md:346) therefore cannot be shown.

In the other direction, wo_check passes whenever agreement >= agreement_min and n > 0 (verify/wo.py:119), with no pixel floor. Since st-c6d5 the AOI includes all 1404 DEA Waterbodies polygons (cli.py:63-69), each at the global 0.91 threshold (config.py:104-112). One polygon with a single mutually clear pixel that disagrees fails the run with exit 3.

Evidence:

The gate re-ran `env -u PROJ_LIB uv run --no-sync python scratch/adv_verify_matrix_scl_ok.py`. It makes the DEA, NBART, Planetary Computer and Copernicus calls raise ConnectionError, then runs the CLI `verify`. Output: reflectance_scaling and scl_share_water pass. water_vs_dea_s2_wo, ndvi_vs_dea_nbart, pixels_vs_planetary_computer, ndvi_correlation_vs_dea_nbart and discovery_vs_copernicus print `skip ... check did not run`. The run ends with `exit_code = 0` and `report all_passed = True n_scored = 2 n_skipped = 5`.

`uv run python scratch/adv_verify_matrix.py` part 2 gives `water_spearman_vs_dea_waterbodies None None fewer than 10 paired passes 2`.

The gate re-ran `env -u PROJ_LIB uv run --no-sync python scratch/adv_wo_dea_floor.py`, which calls the real wo_check. Output: `1x1 px polygon, 1 pixel(s) disagree: passed=False measured=0.0 threshold=0.91 n_mutually_clear=1`. dea-qd635epws_v3 resolves to `mndwi -0.1 0.91`.

Recorded data:
- docs/research/2026-10-29-water-calibration.csv:60 gives dea-qd635epws_v3 a pooled agreement of 0.8884 at mndwi -0.1, below its 0.91 threshold.
- docs/research/verification-20261029T131944Z.md has 9 of 79 WO checks failing, on Ramsar polygons alone (counted by the gate).

Skipping when a source is unreachable is specified in st-c6d5, st-d4a8 and st-8c11. The defect is that a skip counts toward success. How often small DEA polygons fail on real passes depends on DEA data that is not available offline.

Proposed story: Make verify's verdict reflect the verification matrix

Acceptance criteria:

- verify exits non-zero when a reference check is skipped because its source raised an error
- WO and NDVI checks skip a polygon below a configured minimum of mutually clear pixels
- The Spearman check scores over stored history and not only the run's scenes
- The weekly report lists every matrix row with a pass or fail or not-run status

### 6. The failed-scene retry path drops a scene after three failed runs with no way back, and a scene that succeeds on retry leaves later change files stale

- Location: `src/wetland_change/ledger.py:238`
- Severity: important
- Verdict: CONFIRMED

What fails on a real run:

(a) Any exception in process_scene, transient or not, becomes a failed entry with attempts = attempts_so_far + 1 (pipeline.py:137, 148-161). After three failed runs, exhausted_keys (ledger.py:238-249) adds the item to `seen` (pipeline.py:278) and retry_ids drops it (ledger.py:228-235). From then on the daily run reports discovered=0 failed=0 and exits 0. The weekly freshness count flags the item only while its sensing date is inside the 30-day window. cli.py has no requeue command, and no ledger edit is documented. Recovery works only through a backfill over the acquisition range, or through a daily run if a republish also bumps `created`. Even then attempts_so_far reads the latest row whatever its status (ledger.py:252-257), so one more failure exhausts the item again. The design says a failing scene is retried on the next three runs (design.md:238-240), but the code makes three attempts in total. The trigger is real: in the backfill, one DNS failure produced 25 failed scenes in a single pass (backfill-hypotheses.md:42).

(b) run_once rescores only the UTC dates written in the current run (pipeline.py:292, 306-307, 321-326). Each date's baseline uses strictly earlier dates from the same month (pipeline.py:224-228). When a retried or late-created scene lands on an earlier date than one already scored, the later date's change file is not recomputed. It then differs from what a full `score` would write, so a flag can be kept or missed wrongly. This breaks the byte-identical-on-rerun row for change files. ADR 0004 covers only the backfill case.

Evidence:

The gate re-ran both repros.

`cd scratch/adv_exhaust && env -u PROJ_LIB uv run --no-sync python check.py` printed `3 backfill, same updated: discovered 0 processed 0 skipped_seen 3` and `3 daily after: discovered 0 processed 0 failed 0 skipped_seen 1`, so there is no supported recovery without a republish. It also printed `1b republished new-created, fails once: failed 1 attempts 4 retry_ids [] exhausted 1`.

`cd scratch/verify_s5 && env -u PROJ_LIB uv run --no-sync python runonce_order.py`: run 1 fails s_000 (2026-01-01) and scores s_001 (2026-01-06), and run 2 retries s_000 successfully. The script then printed `B file after full rescore identical to run_once state: False`. For s_001 water_ha_index, the stored file has z 10.117 (baseline_n 6), while a full rescore gives 7.419 (baseline_n 7).

Proposed story: Complete the failed-scene retry path

Acceptance criteria:

- An exhausted item can be requeued by a CLI command without editing the ledger
- Exhausted items are counted in the run manifest and fail the freshness check while unresolved
- Storing a scene with an earlier acquisition date rescores later stored dates of the same polygon and month
- A test retries a failed scene and shows the stored change files equal a full rescore

### 7. Per-run S3 work is about 30k sequential requests on a backfill-seeded bucket and grows daily, which can exceed the 5 minute freshness step and the credential window

- Location: `src/wetland_change/ledger.py:186`
- Severity: important
- Verdict: PLAUSIBLE

What fails on a real run:

read_ledger (ledger.py:181-187) calls read_bytes once per ledger part, and pyarrow sends a HEAD and a GET for each. The backfill writes one part per scene (pipeline.py:431-434), so a bucket seeded from the local backfill holds about 1172 parts (backfill-hypotheses.md:42).

A daily run does the following:
- reads the whole ledger at pipeline.py:267, at :320 and inside build_and_write (stac/catalogue.py:278);
- GETs every observation file in score_changes (pipeline.py:207);
- rewrites every item JSON, the collection, the catalog and items.parquet on every run, including no-op runs (pipeline.py:332, catalogue.py:256-271).

On a processed day the workflow then rebuilds the catalogue again (pipeline.yml:101-105, cli.py:323), and verify reads the ledger once more (verify/run.py:71).

Each write_bytes costs a HeadBucket, one directory-marker PUT per path level (store.py:29) and a three-call multipart upload. All requests run one after another. At about 1147 items that is roughly 30k requests on a processed day and 15k on a no-op day, growing by about one ledger part and one item per day.

The weekly freshness step (verify.yml:111-116, 5 minute timeout) does one read_ledger, about 2300 requests, so it times out and opens an issue once per-request latency passes about 130 ms. At about 180 ms the daily S3 overhead alone is about 90 minutes. That is past the 60 minute credential window (finding 3), near the 120 minute job limit, and inside the ledger-before-scoring window (finding 2).

Evidence:

The gate re-ran `uv run --no-sync python scratch/s3/probe10.py` against a local fake S3. Output: `N=150 items: build_and_write wrote 153 objects, 1073 requests (7.2/item)`, split as ListObjects 3, GetObject 3, HeadBucket 153, PutObject 608 and multipart 306.

Verifier probes:
- `scratch/s3/probe3.py`: `files 300 rows 300 requests 601 (2.0/file)`.
- `scratch/adv_rt/noop_run_s3.py`: a no-op run_once takes 547 requests at N=40 and 1067 at N=80, a slope of about 13N. build-catalogue takes about 9N and read_ledger 2N+1.
- `scratch/s3verify/latency.py`: wall time grows linearly with injected per-request delay, giving 49, 150 and 350 ms per ledger file at 0, 50 and 150 ms.

The bucket region is an unset variable (infra/variables.tf:16), and runner-to-bucket latency cannot be measured offline, so it is PLAUSIBLE that real runs hit these limits.

Proposed story: Bound per-run S3 requests as history grows

Acceptance criteria:

- A daily run reads the ledger once and passes the table to scoring and catalogue building
- Ledger parts are compacted so read_ledger needs a bounded number of requests
- The pipeline workflow builds the catalogue once per run
- The catalogue writes only items added or changed since the previous run
## Lower-priority findings

The gate verified these items but left them out of the ranked list to keep it short.
Each one survived adversarial verification.

### L1. Weekly live WO contract test is pinned to a scene DEA deletes after about three months

- Location: `tests/test_live_verify.py:75`
- Severity: important
- Verdict: PLAUSIBLE

What fails on a real run: `remote_scene` loads the 2026-10-27 fixture item, and
`assert wo_href is not None` needs the matching `ga_s2_wo_provisional_3` item. DEA keeps
that product for a rolling three months (design.md, verified facts). From about late
January 2027 the live step at `verify.yml:84-86` fails every Sunday and opens a new
issue. The NDVI live test already searches the newest 60 days.

Evidence: the test fixture is pinned at `tests/test_live_verify.py:41-47`. The retention
is recorded in the design and in LEARNINGS.md. The verifier's repro is
`scratch/wo_retention_repro.py`. DEA's real expiry behaviour cannot be checked offline.

Proposed story: Select the live WO contract scene from the current DEA window

Acceptance criteria:

- The live WO test picks a recent Earth Search scene that has a matching DEA WO item
- The live WO test still passes when the 2026-10-27 DEA item no longer exists

### L2. Success criterion 3 cannot be met by an anonymous DuckDB reader

- Location: `infra/main.tf:29`
- Severity: important
- Verdict: PLAUSIBLE

What fails on a real run: a DuckDB glob over `s3://<bucket>/observations/**` has to list
the bucket. The public policy grants only `s3:GetObject`, and `tests/test_infra.py:77`
asserts that it does not grant `s3:ListBucket`. A single-query read from outside fails.
The GDAL cross-reader GeoParquet test also skips, locally and in CI
(`tests/test_geoparquet.py:126-127`), because the pyogrio wheel has no Parquet driver.
The matrix condition that row counts and bounds agree across readers is never exercised.

Evidence: the code path and the test assertion above. Whether DuckDB has a listing-free
path, such as a published file list, was not tested against S3.

Proposed story: Give public readers a one-query path to the observations

Acceptance criteria:

- A documented DuckDB query reads every observation file from the public bucket without credentials
- The GeoParquet cross-reader check runs in CI with a reader that is installed

### L3. fetch_aoi accepts error bodies and never checks the pinned AOI checksums

- Location: `scripts/fetch_aoi.py:84`
- Severity: minor
- Verdict: CONFIRMED

What fails on a real run: an HTTP 200 response carrying an error body is written as the
AOI file. The fetched file is never compared with the `data/SOURCES.md` checksum.
Polygon ids come from the live `objectid` (`aoi.py:73`). If SLIP renumbers its features,
the ramsar-15, ramsar-28 and ramsar-56 overrides in `config/pipeline.toml` silently
attach to other polygons.

Evidence: `scripts/fetch_aoi.py:84-89` calls only `raise_for_status`. The verifier's repro
is `scratch/verify_aoi/repro_objectid.py`.

Proposed story: Validate the fetched AOI against its recorded source

Acceptance criteria:

- fetch_aoi fails when the response is not a GeoJSON feature collection
- fetch_aoi fails or warns when the polygon ids used by water overrides are missing or renamed

### L4. latest_run_id selects backfill manifests

- Location: `src/wetland_change/verify/run.py:83`
- Severity: minor
- Verdict: PLAUSIBLE

What fails on a real run: `latest_run_id` takes the newest manifest with processed above
0, whatever its kind. On a bucket seeded from the backfill, the weekly verify can target
a backfill chunk of tens of scenes and reach its 20-minute step timeout.

Evidence: `verify/run.py:83-93` never reads `kind`. The run time per scene depends on the
runner.

Proposed story: Make verify default to the latest daily run

Acceptance criteria:

- verify without --run-id selects the newest manifest of kind run with processed above zero
- A test with a newer backfill manifest shows the daily run is selected

### L5. latest_run_id swallows OSError

- Location: `src/wetland_change/verify/run.py:89`
- Severity: minor
- Verdict: CONFIRMED

What fails on a real run: a permission or credential failure while reading a manifest is
skipped silently. Verify then checks an older run, or exits 2 with "no run with processed
scenes".

Evidence: `except (ValueError, TypeError, OSError): continue` at `verify/run.py:89`.

Proposed story: Surface manifest read errors in verify

Acceptance criteria:

- An OSError while reading a run manifest makes verify exit non-zero with the path in the message

### L6. Bucket hygiene

- Location: `infra/main.tf:1`, `src/wetland_change/store.py:29`
- Severity: minor
- Verdict: CONFIRMED

What fails on a real run:

- The bucket has no lifecycle rule to abort incomplete multipart uploads, so parts from
  killed writes are kept and billed.
- Every object is uploaded as `application/octet-stream`, including the STAC JSON.
- Directory marker objects are PUT again on every write.

Evidence: `infra/main.tf:1-3` defines the bucket alone. `store.py:29-31` calls
`create_dir` and `open_output_stream` with no metadata.

Proposed story: Add bucket lifecycle and object content types

Acceptance criteria:

- infra adds a lifecycle rule that aborts incomplete multipart uploads after one day
- JSON and parquet objects are written with their media types

### L7. The verify issue step misses some failure modes and has no de-duplication

- Location: `.github/workflows/verify.yml:120`
- Severity: minor
- Verdict: PLAUSIBLE

What fails on a real run: `if: failure()` does not fire in three cases:

- a job-level timeout;
- a pending run that the shared `pipeline` concurrency group cancels;
- loss of the runner.

The daily pipeline has no issue step at all. Each failing week opens a new issue. Both
crons fire at minute 0, which GitHub can delay.

Evidence: the workflow conditions at `verify.yml:119-128` and `pipeline.yml:21-31`.
GitHub's classification of timeouts and cancellations cannot be checked offline.

Proposed story: Alert on every scheduled run that does not succeed

Acceptance criteria:

- A cancelled or timed-out scheduled run of either workflow produces an alert
- A repeated failure comments on the open failure issue instead of opening a new one
- Both cron schedules use a minute other than zero

### L8. Rejected items are re-logged on every run

- Location: `src/wetland_change/pipeline.py:309`
- Severity: minor
- Verdict: CONFIRMED

What fails on a real run: a guard-rejected item stays in the created window while it is
the newest item, so each run writes another rejected row and another ledger part. The
growth is bounded, and the behaviour is documented in `ledger.py:120`. It adds to the
request growth in finding 7.

Evidence: `pipeline.py:309-318`. `seen_keys` uses succeeded rows only (`ledger.py:221`).

Proposed story: Stop re-logging unchanged rejected items

Acceptance criteria:

- An item rejected with the same updated timestamp is not written to the ledger again

### L9. run_once has no run id reuse guard

- Location: `src/wetland_change/pipeline.py:266`
- Severity: minor
- Verdict: CONFIRMED

What fails on a real run: two `run` calls with the same `--now` overwrite the earlier
ledger file and manifest. Only a manual dispatch with a repeated `--now` reaches this.
`backfill_once` refuses the same case (`pipeline.py:336-348`).

Evidence: `run_once` calls `new_run_id(now)` and writes `ledger_<run_id>.parquet` without
checking for an existing file.

Proposed story: Refuse a reused run id in the daily run

Acceptance criteria:

- run_once raises when the run id already has a manifest or ledger file in the output root

## Refuted during verification

- A wrong bucket name does not read as an empty store. OutputStore construction fails
  with HeadBucket 404 before any work.
- The role does not need `s3:AbortMultipartUpload`, because pyarrow 26.0.0 never sends it.
- The keep-alive commit running only on processed days is the documented design. On
  failure days, verify.yml opens an issue every week.
- An anonymous DEA WFS or SLIP failure skipping the daily run is the documented,
  fail-closed behaviour. The skipped DEA checks that count as success are in finding 5.
- No signed Planetary Computer URL or operator path reaches the public bucket in
  realistic cases.

## Checked and found sound

- All S3 calls pyarrow makes are covered by the role's ListBucket, GetObject, PutObject and DeleteObject grants: ListObjectsV2, HeadBucket, directory-marker PUTs, the multipart upload calls, HeadObject, GetObject and DeleteObject. A first run, a no-op rerun, verify and freshness against a fake S3 that denies everything else produced no denied requests. Nothing needs CreateBucket, GetBucketLocation or AbortMultipartUpload.
- pyarrow S3FileSystem picks up AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN (sent as x-amz-security-token) and AWS_REGION from the environment that configure-aws-credentials exports.
- An object only appears once its multipart upload completes. A killed or failed write never leaves a truncated object, and a failed overwrite keeps the old bytes.
- Zero-byte directory-marker objects do not affect behaviour: list_files keeps only FileType.File, every caller also filters by suffix, and anonymous users have no ListBucket.
- The public policy grants only s3:GetObject on objects. Public ACLs are blocked and ownership is BucketOwnerEnforced. Every SOURCES.md row has redistribute_public true, so the published ledger, observations, changes and STAC content are licence-consistent.
- Bad bucket variables fail before any work. An empty OUTPUT_BUCKET gives s3:/// and OutputStore raises ArrowInvalid. A bucket that does not exist fails at OutputStore construction (HeadBucket 404) before the ledger is read.
- Raster reads are unsigned: AWS_NO_SIGN_REQUEST=YES is set inside rasterio.Env and the hrefs are https, so the exported AWS credentials never reach Earth Search or DEA reads. Read timeouts and retries are bounded.
- An empty bucket raises nothing: read_ledger returns the empty schema table, and watermark and latest_run_id are None. On the first Sunday verify exits 2 and freshness fails with 'ledger holds no succeeded item', so an issue opens. Neither command writes to the bucket.
- Job permissions match the steps. pipeline.yml has contents: write and id-token: write. verify.yml has contents: read, id-token: write and issues: write. In verify.yml the role is assumed after the live tests, and verify plus freshness finish well inside the one-hour session.
- Every S3-touching step in pipeline.yml comes after the credential step. Fetch AOI and the live tests need no AWS credentials.
- The stdout of `run` is exactly one JSON document, because logging goes to stderr. The redirect keeps run's exit code: 2 when any scene failed, after the manifest is written.
- Gating on !cancelled() plus processed > 0 works. A run that wrote a manifest with some failed scenes still reaches catalogue, verify and commit. An empty or missing manifest gives processed=0. The commit step runs even when verify exits non-zero.
- The report commit is correct. `git add --all -- docs/research` stages only the new verification-<run_id>.md. On a depth-1 checkout, pull --rebase then push from a detached HEAD works after main has moved (reproduced with a local bare repo).
- In verify.yml, step-level timeouts fail the step, so failure() fires and the issue opens on any step failure.
- The shared `pipeline` concurrency group serialises both workflows, and the scheduled runs are 12 h apart.
- A rerun after a completed run is incremental: it reports skipped_seen. Observation file names are keyed by item id, so reprocessing overwrites rather than duplicates.
- The watermark ignores backfill rows and treats a null run_kind as a daily row. The retry-by-id search has no created filter, discover dedupes the main and retry results, and scenes are processed in (created, item_id) order.
- backfill_once checkpoints one ledger part per scene, refuses a reused run id and resumes after an interrupt.
- The latest_entries tie-break is chronological. Equal keys arise only from a manual reuse of a run id.
- Same-date seam tiles that arrive on different days are rescored, and the stale change file is deleted or rewritten.
- Earth Search discovery cannot truncate silently: a non-200 page raises APIError. Cloud cover, footprint and datetime are re-checked client-side.
- Timezone handling uses aware UTC values throughout: run ids, ledger year, watermark, the created filter and acquisition dates.
- Reflectance scaling is asserted for every item at run time (pipeline.py:74-76, rel_tol 1e-9) and again in verify.
- The SCL row matches the design: full-resolution SCL with no overviews, within 1 pp for water, vegetation, not vegetated and cloud.
- The reads-the-right-bytes row matches the design: identical transform and bit-identical green DN against Planetary Computer. planetary-computer is installed by uv sync --locked through the dev group.
- NDVI tolerances match the design (median within 0.05, Pearson r above 0.95 over at least 5 rows), and so do the water-history numbers (10 pp per pass, max_day_gap 3, Spearman 0.9).
- CI (test.yml) runs the spyndex index test, the golden run, the same-now rerun and the overlap tests.
- The freshness check (newest item under 7 days, 30-day per-tile counts against Earth Search and CDSE with 24 h latency) runs weekly at verify.yml:111-116 and exits 4 on any skip.
- The ledger source_item holds only public Earth Search JSON. Ledger error text carries only unsigned Earth Search hrefs, and the Markdown report leaves out error detail.
- catalogue.base_url is validated (https only, trailing slash stripped), and the catalogue is rebuilt from the ledger on every run.
- DuckDB reads the hive-partitioned observation layout locally, including the duplicate tile column.

## Cannot be determined offline

- Seconds per scene on a GitHub-hosted runner, because spike 5 was not run. All repo figures (25 s estimated, 138.7 to 152.3 s measured) come from the operator's Mac.
- Per-request S3 latency from a runner to the bucket. The bucket region is an unset variable.
- The 3600 s session defaults and what happens at expiry. The action default comes from one verifier's read of the pinned source, and the role default from AWS documentation; STS and pyarrow behaviour at expiry was never exercised against AWS.
- Whether GitHub reports a job-level timeout as cancelled or as failed. This only decides which !cancelled() steps run; the outcome is the same.
- Whether a push made with GITHUB_TOKEN counts as activity for the 60-day schedule rule. Also whether branch protection or rulesets on main reject the bot push, and whether Issues are enabled.
- Whether GitHub runners can reach the SLIP, DEA, Planetary Computer and CDSE hosts (known item d).
- How real S3 paginates listings over 1000 keys. The fake servers never paginated.
- Whether stac-browser loads JSON served as application/octet-stream, and whether S3 returns Access-Control-Allow-Origin to anonymous requests with the CORS rule applied.
- Whether an account-level S3 Block Public Access setting blocks the bucket policy at apply time.
- Whether Earth Search honours query.created and sortby, and how a republish changes created and updated.
- Real WO agreement on small DEA Waterbodies polygons, and the publication latency of the DEA Waterbodies CSV.
- Whether expired ga_s2_wo_provisional_3 items disappear from DEA STAC or stay listed with dead hrefs.
- Whether SLIP maxRecordCount or the DEA WFS truncates features, and whether SLIP objectids and DEA uids stay stable.
- The exact unbounded Collection 1 count over the AOI (at least 1147), and how often CDSE and Earth Search cloud cover straddle 20 percent.
- Whether the libcurl and OpenSSL bundled in the rasterio wheel and the AWS SDK in pyarrow 26.0.0 coexist without a crash or a hang on exit.
- Whether Planetary Computer ever returns 200 with a non-TIFF body. That is the only path that would put a SAS URL into the public verification JSON.
- Whether score_changes and verify would pick up orphan observation files from a killed run whose item is later excluded from discovery.
