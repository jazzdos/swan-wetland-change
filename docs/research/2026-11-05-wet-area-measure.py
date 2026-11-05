"""Read-only: pipeline vs DEA S2 WO agreement and wet-area gap per polygon-scene.

Sample fixed by LEARNINGS.md "Pre-registered hypotheses (st-9aff)". Anonymous
public reads only. Never calls verify_run. Resumable: skips rows in the CSV.

  uv run python docs/research/2026-11-05-wet-area-measure.py run --ramsar <geojson> [--budget-min 45] [--sanity]
  uv run python docs/research/2026-11-05-wet-area-measure.py summarize

--ramsar defaults to the config's aoi.ramsar_path. The run on 2026-11-05 ran as
scratch/st-9aff/measure_wet_gap.py with the Ramsar layer outside the repository;
only the file paths and the post hoc block in summarize() differ from that copy.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from wetland_change.aoi import AoiPolygon, load_ramsar, union_bbox_4326
from wetland_change.catalogue.search import discover, open_client
from wetland_change.config import load_config
from wetland_change.mask import clear_mask
from wetland_change.raster.read import RasterioReader, read_stack
from wetland_change.stats import rasterise, water_pixels
from wetland_change.verify.wo import (
    WO_EXCLUDE,
    WO_WET,
    dea_reader,
    find_wo_href,
    wo_agreement,
    wo_check,
)
from wetland_change.windows import plan_window

HERE = Path(__file__).parent
CSV = HERE / "2026-11-05-wet-area-gap.csv"
MISSING = HERE / "2026-11-05-wet-area-missing.csv"
SUMMARY = HERE / "2026-11-05-wet-area-summary.txt"
CALIB = Path("docs/research/2026-10-29-polygon-calibration.csv")
COLS = [
    "polygon_id", "tile", "item_id", "pass_date", "method", "threshold",
    "agreement_min", "n_mutually_clear", "agreement", "pipeline_wet_share",
    "wo_wet_share", "gap_pp", "passes_agreement",
]
MINPX = 100


class CachingReader:
    """Wraps the DEA reader so wo_check and the share calculation share a read."""

    def __init__(self, inner):
        self.inner = inner
        self.cache = {}

    def open_grid(self, href):
        return self.inner.open_grid(href)

    def read(self, href, window):
        key = (href, window.col_off, window.row_off, window.width, window.height)
        if key not in self.cache:
            self.cache[key] = self.inner.read(href, window)
        return self.cache[key]


def done_keys():
    keys = set()
    for path in (CSV, MISSING):
        if path.exists():
            for r in csv.DictReader(path.open()):
                keys.add((r["polygon_id"], r["item_id"]))
    return keys


def append(path, cols, row):
    new = not path.exists()
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        if new:
            w.writeheader()
        w.writerow(row)
        fh.flush()


def log(msg):
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def run(budget_min, sanity, ramsar):
    t0 = time.monotonic()
    deadline = t0 + budget_min * 60
    cfg = load_config(Path("config/pipeline.toml"))
    if ramsar is not None:
        cfg = cfg.model_copy(
            update={"aoi": cfg.aoi.model_copy(update={"ramsar_path": Path(ramsar)})}
        )
    assert cfg.stac.collection == "sentinel-2-c1-l2a"
    polys = load_ramsar(
        cfg.aoi.ramsar_path,
        site_prefixes=cfg.aoi.site_prefixes,
        operation_epsg=cfg.aoi.operation_epsg,
    )
    log(f"{len(polys)} polygons: {[p.polygon_id for p in polys]}")
    calib = pd.read_csv(CALIB)
    dates = sorted(calib["pass_date"].unique(), reverse=True)
    assert len(dates) == 12
    new6 = set(dates[:6])
    ids = sorted(calib["item_id"].unique())
    client = open_client(cfg.stac.endpoint)
    bbox = union_bbox_4326(polys)
    scenes = {}
    for d in dates:
        day = datetime.fromisoformat(d).replace(tzinfo=UTC)
        found = discover(
            client, cfg.stac, bbox=bbox,
            polygons_4326=[p.geometry_4326 for p in polys],
            created_from=None, seen=set(),
            retry_ids=[i for i in ids if i.split("_")[2][:8] == d.replace("-", "")],
            datetime_range=(day, day + timedelta(days=1) - timedelta(seconds=1)),
        )
        for s in found.scenes:
            scenes[s.item_id] = s
        log(f"{d}: {[s.item_id for s in found.scenes]} rejected={found.rejected}")
    ordered = sorted(scenes.values(), key=lambda s: (s.datetime, s.item_id), reverse=True)
    reader = RasterioReader()
    grids, wo_hrefs = {}, {}
    # Task list: phase 1 ramsar-28 on all dates, phase 2 the rest on new6.
    tasks = []
    for phase in (1, 2):
        for s in ordered:
            day = s.datetime.date().isoformat()
            for p in polys:
                is28 = p.polygon_id == "ramsar-28"
                if (phase == 1) != is28:
                    continue
                if phase == 2 and day not in new6:
                    continue
                tasks.append((phase, s, p))
    log(f"{len(tasks)} candidate polygon-scene tasks")
    seen = done_keys()
    sanity_done = False
    dea_cache = {}
    for phase, s, p in tasks:
        if (p.polygon_id, s.item_id) in seen:
            continue
        if time.monotonic() > deadline:
            log("BUDGET EXHAUSTED; stopping")
            break
        day = s.datetime.date().isoformat()
        try:
            if s.item_id not in grids:
                grids[s.item_id] = reader.open_grid(s.bands["green"].href)
            grid = grids[s.item_id]
            planned = plan_window(p.geometry, grid)
            if planned is None:
                continue
            if s.item_id not in wo_hrefs:
                wo_hrefs[s.item_id] = find_wo_href(s, bbox)
            href = wo_hrefs[s.item_id]
            if href is None:
                append(MISSING, ["polygon_id", "item_id", "tile", "pass_date", "reason"],
                       dict(polygon_id=p.polygon_id, item_id=s.item_id, tile=s.tile,
                            pass_date=day, reason="no DEA WO scene"))
                log(f"MISSING {p.polygon_id} {s.item_id}")
                continue
            dea = dea_cache.setdefault(s.item_id, CachingReader(dea_reader()))
            stack = read_stack(s, planned, reader)
            inside = rasterise(p.geometry, stack.transform, stack.shape)
            check = wo_check(s, stack, planned, inside, water=cfg.water, wo_href=href,
                             reader=dea, scene_grid=grid, polygon_id=p.polygon_id)
            setting = cfg.water.for_polygon(p.polygon_id)
            if check.detail.get("reason"):
                append(MISSING, ["polygon_id", "item_id", "tile", "pass_date", "reason"],
                       dict(polygon_id=p.polygon_id, item_id=s.item_id, tile=s.tile,
                            pass_date=day, reason=check.detail["reason"]))
                log(f"SKIP {p.polygon_id} {s.item_id} {check.detail['reason']}")
                continue
            # Same inputs and definitions as wo_check.
            wo = dea.read(href, planned.window10)
            clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
            pw = water_pixels(setting, stack, clear)
            agreement, n = wo_agreement(pw, clear, wo)
            both = clear & ((wo & WO_EXCLUDE) == 0)
            if n:
                pipe_share = float(pw[both].mean())
                wo_share = float(((wo & WO_WET) > 0)[both].mean())
                gap = (pipe_share - wo_share) * 100
                passes = bool(agreement >= setting.agreement_min)
            else:
                pipe_share = wo_share = gap = float("nan")
                passes = None
            if n and abs(agreement - check.measured) > 1e-12:
                log(f"MISMATCH {p.polygon_id} {s.item_id}: mine={agreement} wo_check={check.measured}")
                sys.exit(2)
            if sanity and not sanity_done and p.polygon_id == "ramsar-28" and n:
                log(f"SANITY {p.polygon_id} {s.item_id}: agreement={agreement!r} "
                    f"wo_check.measured={check.measured!r} equal={agreement == check.measured}")
                sanity_done = True
            append(CSV, COLS, dict(
                polygon_id=p.polygon_id, tile=s.tile, item_id=s.item_id, pass_date=day,
                method=setting.method, threshold=setting.threshold,
                agreement_min=setting.agreement_min, n_mutually_clear=n,
                agreement=agreement if n else "", pipeline_wet_share=pipe_share if n else "",
                wo_wet_share=wo_share if n else "", gap_pp=gap if n else "",
                passes_agreement=passes if n else ""))
            log(f"ok {p.polygon_id} {s.item_id} n={n} agr={agreement:.4f} gap={gap:.2f}")
            if len(dea.cache) > 40:
                dea.cache.clear()
        except Exception as exc:  # recorded, not filled in
            log(f"ERROR {p.polygon_id} {s.item_id}: {type(exc).__name__}: {exc}")
            append(MISSING, ["polygon_id", "item_id", "tile", "pass_date", "reason"],
                   dict(polygon_id=p.polygon_id, item_id=s.item_id, tile=s.tile,
                        pass_date=day, reason=f"error {type(exc).__name__}: {exc}"))
    log(f"done in {(time.monotonic() - t0) / 60:.1f} min")


def stats(df):
    a = df["gap_pp"].abs()
    return (f"rows={len(df)} pass_agreement={int(df.passes_agreement.sum())}")


def rate_block(sub, label):
    p = sub[sub.passes_agreement]
    ok = int((p.gap_pp.abs() <= 5).sum())
    rate = ok / len(p) if len(p) else float("nan")
    ag = sub.gap_pp.abs()
    return (f"{label}: rows={len(sub)} pass_agreement={len(p)} within_5pp={ok} "
            f"rate={rate:.4f} median_abs_gap={ag.median():.3f} p95_abs_gap={ag.quantile(.95):.3f} "
            f"median_signed_gap={sub.gap_pp.median():.3f}"), rate, len(p), ok


def summarize():
    df = pd.read_csv(CSV)
    miss = pd.read_csv(MISSING) if MISSING.exists() else pd.DataFrame()
    df["passes_agreement"] = df["passes_agreement"].astype(str).eq("True")
    small = df[df.n_mutually_clear < MINPX]
    d = df[df.n_mutually_clear >= MINPX].copy()
    out = []
    _, r1, n1, k1 = rate_block(d, "ALL")
    out.append(f"H1: rows passing agreement={n1}, with abs gap <= 5 pp={k1}, rate={r1:.4f}, "
               f"H1 {'held' if r1 >= 0.90 else 'did not hold'} (threshold 0.90)")
    r28 = d[d.polygon_id == "ramsar-28"]
    _, r2, n2, k2 = rate_block(r28, "ramsar-28")
    out.append(f"H2: ramsar-28 rows passing agreement={n2}, with abs gap <= 5 pp={k2}, rate={r2:.4f}, "
               f"H2 {'held' if r2 >= 0.90 else 'did not hold'} (threshold 0.90)")
    out.append("")
    out.append("By polygon group (rows with n >= 100):")
    grp = d.polygon_id.where(d.polygon_id.isin(["ramsar-15", "ramsar-28", "ramsar-56"]), "other (pooled)")
    for g in ["ramsar-15", "ramsar-28", "ramsar-56", "other (pooled)"]:
        sub = d[grp == g]
        if len(sub):
            out.append(rate_block(sub, g)[0])
        else:
            out.append(f"{g}: no rows")
    out.append("other polygons by id: " + ", ".join(
        f"{k}={len(v)}" for k, v in d[grp == "other (pooled)"].groupby("polygon_id")))
    out.append("")
    d["fail_agree"] = ~d.passes_agreement
    d["fail_either"] = d.fail_agree | (d.gap_pp.abs() > 5)
    sc = d.groupby("item_id").agg(a=("fail_agree", "any"), b=("fail_either", "any"))
    out.append(f"Per scene (scenes with at least one row, n >= 100): scenes={len(sc)}, "
               f"share with >=1 polygon failing agreement={sc.a.mean():.4f} ({int(sc.a.sum())}/{len(sc)}), "
               f"share with >=1 failing agreement or 5 pp clause={sc.b.mean():.4f} ({int(sc.b.sum())}/{len(sc)})")
    sc28 = d[d.polygon_id == "ramsar-28"].groupby("item_id").agg(a=("fail_agree", "any"), b=("fail_either", "any"))
    out.append("")
    clause = d[d.passes_agreement & (d.gap_pp.abs() > 5)].sort_values("pass_date", ascending=False)
    out.append(f"Rows failing the 5 pp clause while passing agreement: {len(clause)} (up to 20 shown)")
    for _, r in clause.head(20).iterrows():
        out.append(f"  {r.polygon_id} {r.pass_date} n={r.n_mutually_clear} agreement={r.agreement:.4f} gap_pp={r.gap_pp:.3f}")
    out.append("")
    out.append("Post hoc, not pre-registered:")
    per_date = d.groupby("pass_date").agg(
        a=("fail_agree", "any"), b=("fail_either", "any"), polygons=("polygon_id", "nunique")
    )
    full = per_date[per_date.polygons > 1]
    out.append(f"  dates with every polygon measured={len(full)}, with >=1 row failing agreement="
               f"{int(full.a.sum())}, with >=1 row failing agreement or the clause={int(full.b.sum())}")
    passed = d[d.passes_agreement]
    dry = int(((d.pipeline_wet_share == 0) & (d.wo_wet_share == 0)).sum())
    out.append(f"  rows dry in both sources={dry} of {len(d)}")
    wet = passed[passed[["pipeline_wet_share", "wo_wet_share"]].max(axis=1) >= 0.01]
    within = int((wet.gap_pp.abs() <= 5).sum())
    out.append(f"  rows passing agreement with >=1 percent wet in either source={len(wet)}, "
               f"within 5 pp={within}, rate={within / len(wet):.4f}")
    can = passed[(1 - passed.agreement) * 100 > 5]
    out.append(f"  rows passing agreement where the clause can bind={len(can)}, "
               f"failing it={int((can.gap_pp.abs() > 5).sum())}")
    out.append("")
    out.append("Coverage:")
    out.append(f"  rows in CSV={len(df)}, rows with n>=100 used={len(d)}, excluded for n<100={len(small)}")
    out.append("  rows per pass_date (n>=100): " + ", ".join(f"{k}={v}" for k, v in d.groupby("pass_date").size().sort_index(ascending=False).items()))
    r28all = df[df.polygon_id == "ramsar-28"]
    out.append(f"  ramsar-28 scene rows measured={len(r28all)}; dates={sorted(r28all.pass_date.unique(), reverse=True)}")
    if len(miss):
        out.append(f"  missing/skipped polygon-scenes={len(miss)}")
        for k, v in miss.groupby(["pass_date", "reason"]).size().items():
            out.append(f"    {k[0]} {k[1]}: {v}")
    else:
        out.append("  missing/skipped polygon-scenes=0")
    SUMMARY.write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "summarize"])
    ap.add_argument("--budget-min", type=float, default=45)
    ap.add_argument("--sanity", action="store_true")
    ap.add_argument("--ramsar", default=None)
    a = ap.parse_args()
    run(a.budget_min, a.sanity, a.ramsar) if a.mode == "run" else summarize()
