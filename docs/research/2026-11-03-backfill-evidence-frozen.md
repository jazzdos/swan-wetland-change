# Backfill evidence JSON is frozen

`2026-11-03-backfill-evidence.json` is a frozen record. It was produced at commit
114459b with config sha256 9ce8408cb8c554248cd8a8c03a6531405c56fe26b9ca899607625a13b340134f
and `spearman_min` 0.9. The committed JSON is the record.

`2026-11-02-backfill-analysis.py` is unchanged. Regenerating the JSON with it on the
current head and config (`spearman_min` 0.83 in `config/pipeline.toml`) gives a file
that differs in these fields:

- `h4.lakes[*].passed`: false becomes true for all four lakes, because the threshold
  moved from 0.9 to 0.83.
- `h4` `rho`, `n_pairs`, `n_unpaired` and the `per_pass` counts. Commit 00e8fb0
  explains the `rho` change only; the other three also differ on the current head.
- `runs.backfill_calls`, `runs.backfill_seconds_sum` and
  `runs.seconds_per_processed_scene`: null unless `--progress-log` is given.
- `config_sha256`, `git_head`, `date` and `reference.searched_at`: these record the
  regeneration run, not the original.

Do not overwrite the committed JSON. To compare, write a regenerated copy to a new
path and diff the fields above.
