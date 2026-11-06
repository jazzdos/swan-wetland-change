"""Read-only: per-lake Spearman at history_days for run ends across the backfill.

Frozen at commit 46e0e20. `_history_paths` (src/wetland_change/verify/run.py) no
longer takes `history_days`, so this script does not run on the branch head. It is
not ported. 2026-11-05-spearman-windows.csv is the record.

Calls only read paths of OutputStore. Never calls verify_run, which writes a report.
"""
import csv
import functools
from datetime import timedelta
from pathlib import Path

import pandas as pd

from wetland_change.aoi import load_waterbodies
from wetland_change.config import load_config
from wetland_change.ledger import read_ledger
from wetland_change.store import OutputStore
from wetland_change.verify.run import _history_paths
from wetland_change.verify.waterbodies import (
    SPEARMAN_CHECK_NAME,
    fetch_series,
    read_observations,
    waterbody_checks,
)

DATA = Path("/Users/jarrodbaker/Documents/swan-wetland-change-data")
OUT = Path(__file__).parent / "rho_by_window.csv"
cfg = load_config(Path("config/pipeline.toml"))
wb = cfg.verify.waterbodies
store = OutputStore(str(DATA / "outputs"))
ledger = read_ledger(store)
lakes = load_waterbodies(
    DATA / "aoi" / "dea_waterbodies_v3_swan.geojson", operation_epsg=cfg.aoi.operation_epsg
)
series = functools.lru_cache(maxsize=None)(fetch_series)
stored = set(store.list_files("observations"))
newest = pd.to_datetime(ledger.to_pandas()["datetime"], utc=True).max().to_pydatetime()
print("spearman_min", wb.spearman_min, "min_pairs", wb.spearman_min_pairs, "newest", newest)

all_paths = sorted(_history_paths(ledger, newest=newest, history_days=100000) & stored)
frame = read_observations(store, all_paths)
frame["_dt"] = pd.to_datetime(frame["datetime"], utc=True)
print("files", len(all_paths), "lake rows", len(frame))


def rhos(end, days):
    start = pd.Timestamp(end) - timedelta(days=days)
    history = frame[(frame["_dt"] >= start) & (frame["_dt"] <= pd.Timestamp(end))].drop(columns="_dt")
    checks = waterbody_checks(
        history.iloc[:0], series, lakes, cfg=wb,
        min_valid_fraction=cfg.water.min_valid_fraction, history=history,
    )
    return [c for c in checks if c.name == SPEARMAN_CHECK_NAME]


rows = []
ends = [newest - timedelta(days=30 * i) for i in range(0, 13)]
for days in (365, 730, 100000):
    for end in ends if days == 365 else ends[:1]:
        for c in rhos(end, days):
            d = c.detail
            rows.append(dict(end=end.date().isoformat(), days=days, lake=d.get("lake") or d.get("uid"),
                             passed=c.passed, rho=c.measured, n_pairs=d.get("n_pairs"), reason=d.get("reason")))
with OUT.open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
t = pd.DataFrame(rows)
for days, g in t.groupby("days"):
    print(f"\n== window {days} days ==")
    print(g.pivot(index="end", columns="lake", values="rho").round(3).to_string())
n = t[t.days == 365]
print("\n365-day run ends with every scored lake at or above min:",
      int(n.groupby("end")["passed"].apply(lambda s: s.dropna().all() and s.notna().any()).sum()), "of", n["end"].nunique())
print("n_pairs at newest:", n[n.end == n.end.max()][["lake", "n_pairs"]].to_dict("records"))
