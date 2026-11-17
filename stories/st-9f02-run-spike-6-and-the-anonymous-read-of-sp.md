---
id: st-9f02
title: Run spike 6 and the anonymous read of spike 7 against the public bucket
type: spike
priority: P3
depends_on: [st-1a5f, st-b6bf]
touches: [LEARNINGS.md, README.md, docs/research/**]
exclusive: false
gates: [test]
created: 2026-11-14
updated: 2026-11-17
---
## Description

Two design spikes were blocked while the output bucket was private (`docs/decisions/0011-private-output-bucket.md`). After Jarrod's apply of the public-read infra (the story this one depends on, ADR 0016), this story closes them:

- Spike 6: the catalogue opens in stac-browser from a bucket with CORS. The design (`docs/plans/2026-10-29-swan-wetland-change-design.md`, "Static catalogue: hand-written catalog.json on a bucket with CORS, opened in stac-browser") planned a hand-written catalogue; the pipeline's catalogue now exists (st-1990, st-a868, st-30ad), so the spike opens the published one. It unblocks success criterion 2 and the STAC row of the verification matrix (bucket returns `Access-Control-Allow-Origin`, catalogue opens in stac-browser).
- Spike 7, anonymous half: DuckDB reads the observations from S3 with one glob and no credentials. It unblocks success criterion 3. The credentialed half is recorded under st-b49e.

Why it depends on st-b6bf: the st-b6bf pre-registration in `LEARNINGS.md` ("Blindness. Until the decision files are committed") bars reading any object in the output store (observations, catalogue, run manifests, `verification/`) until its decision files are committed. This story reads the catalogue and the observations, so it cannot start before st-b6bf is done.

Constraints:

- While st-dd0d is not done, no `verification/` object, sample report or run log of a sample run is read, and no query selects or prints `verification/` content.
- The GitHub repository is private, so stac-browser on GitHub Pages is not available. Use the hosted stac-browser or a local build pointed at the bucket's catalogue URL (`catalogue.base_url` in `config/pipeline.toml`).
- New `LEARNINGS.md` entries are added as dated sections; earlier entries, including the "Other spikes" paragraph of "S5 runner timing (2026-11-14)", are not edited. The README status paragraph that says the two spikes "stay blocked while the bucket is private (ADR 0011)" is updated.
- No `tofu` command is run. Build agents do not commit or push; the orchestrator commits on the story branch.

## Acceptance Criteria

- [ ] If an anonymous HEAD of the catalogue root does not return 200, the story is parked with the question "apply not run: has the public-read apply in infra/README.md been done?"
- [ ] `uv run pytest -m live -q` on the anonymous read test passes (anonymous GET of an existing object, anonymous listing under `observations/`, anonymous DuckDB read with one glob, bucket-root listing denied)
- [ ] A response from the bucket to a request with an Origin header carries `Access-Control-Allow-Origin`, and stac-browser opens the catalogue root and one item; the header output and a screenshot are saved under `docs/research/`
- [ ] `LEARNINGS.md` has dated S6 and S7 entries with the measured results, and the README status paragraph no longer says either spike is blocked
- [ ] `uv run pytest -q` passes

## Implementation Notes

- 2026-11-17T11:19:24.779Z: 2026-11-17: Shelved to backlog. Jarrod directed the output bucket private again (st-90b4, ADR 0017). Spike 6 (stac-browser over CORS) and the anonymous half of spike 7 need anonymous read, which the private bucket denies. Reopen only if public read returns.
