---
id: st-1a5f
title: Reopen public read access to the output bucket in code under ADR 0016
type: feature
priority: P2
complexity: hard
depends_on: [st-1a9c]
touches: [docs/decisions/0011-private-output-bucket.md, docs/decisions/0016-*.md, infra/**, tests/test_infra.py, tests/test_readme.py, tests/test_live_*.py, README.md]
exclusive: false
gates: [test]
created: 2026-11-14
updated: 2026-11-14
---
## Description

Jarrod approved public access to the output bucket on 2026-11-14. This story carries out steps 1, 3, 4 and 5 of "Reopening public access" in `docs/decisions/0011-private-output-bucket.md`, with no apply. Step 2 (licences and attribution) is the story this one depends on; its research note `docs/research/<date>-public-release-licences.md` is the evidence the new ADR cites. Step 6 (the apply) is Jarrod's: ADR 0011 says the apply is run by the operator, never by an agent, after the plan is reviewed.

How the approval was given, for the ADR's decision-making section: on 2026-11-14 the orchestrator told Jarrod that the outputs review was the decision that unblocked spike 6 and the anonymous read test, and Jarrod replied "approved". The orchestrator then stated its reading with the proposed stories (he has reviewed the outputs and approves public access, the new ADR records that as his decision, the apply and the DBCA-010 licence confirmation stay his) and Jarrod approved that set.

What to change:

- ADR. Write `docs/decisions/0016-<slug>.md` superseding 0011. Numbers 0014 and 0015 are reserved by st-b6bf and st-dd0d. Change only the status line of 0011, to name 0016.
- Infra (`infra/main.tf`, `infra/variables.tf`, `infra/outputs.tf`). Set `block_public_policy` and `restrict_public_buckets` to false and keep `block_public_acls` and `ignore_public_acls` true. Add a bucket policy granting anonymous `s3:GetObject` on objects and anonymous `s3:ListBucket` with an `s3:prefix` condition limited to `observations/`, with `depends_on` the access block. Add a CORS rule for GET and HEAD. The pipeline role, the lifecycle rule and the outputs stay as they are. The pre-0011 public configuration is in the git history of st-bbbf (story commit 09f94a9) and of st-58e9.
- Tests. Replace the private-configuration assertions in `tests/test_infra.py` and the `credential_chain` README test in `tests/test_readme.py`. Put an anonymous live test in place of `tests/test_live_private_outputs.py` (anonymous GET of an existing object, anonymous listing under `observations/`, anonymous DuckDB read with one glob, bucket-root listing denied). `tests/aws_support.py` (st-b49e) is the credential helper the private test uses.
- Docs. `README.md` ("Querying with DuckDB", Limitations and the status paragraph), `infra/README.md` and the `infra/variables.tf` description. Four test modules read `README.md`.

Constraints:

- No agent runs `tofu plan`, `tofu apply` or any AWS call. `infra/terraform.tfstate` is not read or changed.
- The new live test is written and collected but not run: it reads observations, which the st-b6bf pre-registration in `LEARNINGS.md` bars until its decision files are committed. No output-store object is read by this story.
- The README must not say the bucket is public before the apply. The wording is that public read takes effect at the operator's apply, and that until then readers need credentials.
- No `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md` is opened, no `git diff`, `git log -p`, `git show` or search output that includes another one is read, and no run log newer than 43475454140 is opened.
- `LEARNINGS.md` is not edited; tests pin the st-b6bf and st-dd0d pre-registrations.
- The GitHub repository's visibility is outside this story.
- Build agents do not commit or push; the orchestrator commits on the story branch.

## Acceptance Criteria

- [ ] `docs/decisions/0016-*.md` exists, names 0011 as superseded, records Jarrod's approval of 2026-11-14 as described above and the result of the licence story with a link to its note, and keeps the operator-only apply and the cost note (anonymous requests are billed to the bucket owner); the status line of `docs/decisions/0011-private-output-bucket.md` names 0016 and no other line of 0011 changes
- [ ] `tests/test_infra.py` asserts `block_public_acls` and `ignore_public_acls` are true and `block_public_policy` and `restrict_public_buckets` are false
- [ ] `tests/test_infra.py` asserts anonymous `s3:GetObject` on objects, anonymous `s3:ListBucket` only with an `s3:prefix` condition limited to `observations/`, `depends_on` the access block, and a CORS rule for GET and HEAD, and fails if the list statement loses its prefix condition
- [ ] `uv run pytest --collect-only -m live -q` lists an anonymous read test and `tests/test_live_private_outputs.py` no longer exists
- [ ] `README.md`, `infra/README.md` and the `infra/variables.tf` description describe public read as taking effect at the operator's apply; `infra/README.md` gives the plan-review and apply steps and a header-only check (status line and `Access-Control-Allow-Origin` of an anonymous HEAD with an Origin header) for the operator to run afterwards
- [ ] `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts` and `uv run pytest -q` all exit 0
