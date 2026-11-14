---
id: st-75ec
title: "Fix three small review findings: duplicate README sentence, credential source label, S5 bound base"
type: chore
priority: P3
depends_on: []
discovered_from: st-b49e
touches: [LEARNINGS.md, README.md, tests/aws_support.py, tests/test_aws_support.py]
exclusive: false
created: 2026-11-14
updated: 2026-11-14
---

## Description

Three minor review findings were left unfixed when st-b49e and st-747e closed. None changes pipeline behaviour, config, a workflow or any output; the story touches README.md, LEARNINGS.md and two test-support files only.

1. README.md, Limitations. Two bullets carry nearly the same sentence about st-b49e: the bullet that starts 'Verify findings still open' ends with 'A profile created by `aws login` is not read by the DuckDB credential chain; the route (export the credentials to the environment) is given under "Querying with DuckDB", and the two live tests in `tests/test_live_private_outputs.py` name the credential source and that route when DuckDB cannot build the secret (st-b49e).', and the bullet that starts 'The credentialed S3 query in "Querying with DuckDB"' says the same. The sentence is not a verify finding. Remove it from the 'Verify findings still open' bullet, keep the other occurrence word for word, and rewrap only the bullet that lost the sentence (it also has a short ragged line after 'no later than 2026-12-31), and DEA Waterbodies rows are advisory'). No other README words change.

2. tests/aws_support.py. credential_source() returns the first discoverable source only, so with AWS_ACCESS_KEY_ID and AWS_PROFILE both set it returns 'AWS_ACCESS_KEY_ID (environment keys)' and the failure message of create_credential_chain_secret() names the keys when the profile can be the cause (the documented route ends with 'unset AWS_PROFILE'). Make the label name every discoverable source, in the existing order (environment keys, AWS_PROFILE=<name>, AWS_WEB_IDENTITY_TOKEN_FILE, ~/.aws/credentials), joined by '; '. It still returns None when there is none, and the label never holds a credential value. What DuckDB does when both are set is not measured here and must not be claimed; no AWS call is made.

3. LEARNINGS.md, 'S5 runner timing (2026-11-14)', paragraph 'How many scenes fit in the 120 minute job'. The two bounds use different bases: (7200 - 50) / 302.0 = 23.7 for pipeline plus verify, and 7200 / 67.2 = 107 for the pipeline step alone. On the same base the second is (7200 - 50) / 67.2 = 106.4, so 106 scenes. Leave the original paragraph unchanged and add one dated correction line straight after it. No line in any 'Pre-registered hypotheses' section changes.

Out of scope: rewrapping other README lines (the standards set no markdown wrap width), the two reproduction JSON files under docs/research, and anything in the st-dd0d or st-b6bf pre-registrations.

## Acceptance Criteria

- [ ] README.md with whitespace collapsed holds the phrase 'is not read by the DuckDB credential chain' zero times and the phrase "is not read by DuckDB's credential chain" once in Limitations
- [ ] and git diff --word-diff of README.md against main shows no added words and only the one removed sentence
- [ ] credential_source() returns a label containing both 'AWS_ACCESS_KEY_ID' and 'AWS_PROFILE=<name>' in that order when both are set and still returns None when no source is discoverable
- [ ] and tests/test_aws_support.py holds a test for the both-set case that fails before the change
- [ ] The S5 entry in LEARNINGS.md holds one new line dated 2026-11-14 giving 106 scenes for the pipeline step alone on the (7200 - 50) base
- [ ] the original paragraph is byte-identical
- [ ] and git diff of LEARNINGS.md against main shows no changed line above the heading '## Spike results'
- [ ] ruff check and ruff format --check and mypy and pytest all exit 0

## Implementation Plan

Story pointers verified in /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-75ec (branch story/st-75ec, no diff against main yet). README.md: the "Verify findings still open" bullet runs lines 418-433 and ends with the st-b49e sentence ("A profile created by `aws login` is not read by the DuckDB credential chain; ... (st-b49e)."); the "credentialed S3 query" bullet (about line 447) holds the "DuckDB's credential chain" wording to keep. README line 335-336 ("is not read by the\nDuckDB credential chain, so the query below fails") is in "Querying with DuckDB", not Limitations; with whitespace collapsed it reads "is not read by the DuckDB credential chain", so the zero-occurrence criterion must be checked on the Limitations section only (see step 1 note). tests/aws_support.py credential_source() returns on the first source. tests/test_aws_support.py::test_credential_source_names_env_keys_profile_and_none has a final block asserting "AWS_PROFILE" not in source when both are set, which pins the old behaviour. LEARNINGS.md: S5 section at line 788, target paragraph at line 835, "## Spike results" at line 444. Existing correction style at LEARNINGS.md line 605: "Correction (2026-10-30). ...".

Steps (TDD order):
1. README.md: delete the sentence "A profile created by `aws login` is not read by the DuckDB credential chain; the route (export the credentials to the environment) is given under "Querying with DuckDB", and the two live tests in `tests/test_live_private_outputs.py` name the credential source and that route when DuckDB cannot build the secret (st-b49e)." from the "Verify findings still open" bullet, so the bullet ends "...no later than 2027-01-31)." Rewrap only that bullet (about 80 columns, 2-space hanging indent, as its neighbours), joining the ragged short line after "2026-12-31), and DEA Waterbodies rows are advisory". No other word or line changes. Proof: `git diff --word-diff README.md` shows only the removed sentence, no added words; the only remaining "is not read by DuckDB's credential chain" is in the Limitations bullet, and the Limitations section no longer holds "is not read by the DuckDB credential chain" (the "Querying with DuckDB" occurrence at line 335 is outside Limitations and stays).
2. tests/test_aws_support.py: first add a failing test test_credential_source_names_every_source_when_several_are_set (sets AWS_ACCESS_KEY_ID to SENTINEL_KEY, AWS_PROFILE=p, AWS_WEB_IDENTITY_TOKEN_FILE and creates ~/.aws/credentials in the clean_env home; asserts the exact label "AWS_ACCESS_KEY_ID (environment keys); AWS_PROFILE=p; AWS_WEB_IDENTITY_TOKEN_FILE; ~/.aws/credentials", the order of AWS_ACCESS_KEY_ID before AWS_PROFILE=p, and SENTINEL_KEY not in label; a smaller both-set case asserts "AWS_ACCESS_KEY_ID (environment keys); AWS_PROFILE=p"). Add a failure-message test: with keys and profile set and a failing _FakeConnection, the pytest.fail message contains both "AWS_ACCESS_KEY_ID" and "AWS_PROFILE=p". Run pytest tests/test_aws_support.py and confirm the new tests fail for the right reason. Then update the old test's final block: remove `assert "AWS_PROFILE" not in source` (replace with `assert "AWS_PROFILE=p" in source`), keep the None and single-source assertions.
3. tests/aws_support.py: change credential_source() to collect labels in the existing order (environment keys, AWS_PROFILE=<name>, AWS_WEB_IDENTITY_TOKEN_FILE, ~/.aws/credentials) into a list and return "; ".join(labels) or None. Update the docstring to "Label every discoverable AWS credential source, or None if there is none." and note the label never holds a credential value and that which source DuckDB uses when several are set is not measured. Keep label strings unchanged. Do not claim DuckDB behaviour in the failure message; message wording at the `source = credential_source() ...` site may stay as is ("from {source}") or read "from {source}" unchanged. Re-run tests/test_aws_support.py to green.
4. LEARNINGS.md: leave line 835 byte-identical and insert, straight after it, one blank line then one unwrapped line: "Correction (2026-11-14). The two bounds above use different bases. On the same (7200 - 50) base the pipeline step alone gives (7200 - 50) / 67.2 = 106.4, so 106 scenes, not 107; the 23 scenes for pipeline plus verify stands." The line must sit above "## Spike results"? NO: the S5 paragraph is below that heading (line 835 > 444), so the criterion "no changed line above '## Spike results'" holds because only one line is added at about line 836-837. Proof: `git diff LEARNINGS.md` shows a pure addition of two lines (blank plus correction) after line 835 and nothing above line 444.
5. Run, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. All must exit 0. Do not run -m live tests, git add or git commit.

## Implementation Notes

- 2026-11-14T13:38:50.264Z: 2026-11-14, constraints for the planner and every build agent (orchestrator). Blindness, because st-dd0d and st-b6bf have pre-registered samples that nobody may see before their decision files are committed: open no docs/research/verification-*.md other than verification-20261029T131944Z.md and verification-20261111T175303Z.md, no run log of a pipeline or verify.yml run newer than 43475454140, and no object in the output store; do not read git diff, git log -p, git show or search output that includes such a report (scope every grep and diff to the files this story touches). Agents do not run git add or git commit, do not merge or push, do not edit stories/, and use no AWS credentials, aws CLI, S3 output store or terraform; nothing is written under /Users/jarrodbaker/Documents/swan-wetland-change-data. The orchestrator commits on story/st-75ec. LEARNINGS.md keeps one unwrapped line per paragraph. Ruff line length is 88. If a test pins text that this story changes, update the pin in the same task. pytest prints no count line here; judge it by exit code.
- 2026-11-14T13:40:17.911Z: 2026-11-14 (orchestrator): the first acceptance criterion is scoped to the README Limitations section. The 'Querying with DuckDB' section (about line 335) also reads 'is not read by the DuckDB credential chain' with whitespace collapsed; it is the primary statement and stays. The zero count applies to Limitations only.

## Questions
