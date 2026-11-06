"""Per-polygon NDWI/MNDWI/SCL6 threshold sweep against DEA S2 WO.

Record: 2026-10-29-polygon-calibration.csv is the record of the original run. The
inputs of that run may have changed (Earth Search items, DEA products, the Ramsar
polygons), so a rerun differs from the committed CSV.

The DEA ga_s2_wo_provisional_3 product (provisional WO) keeps about three months of
scenes. The window of the original run has passed, so the committed CSV is the record
and a rerun needs a window inside the current provisional retention.

Polygons: ramsar-15, ramsar-28, ramsar-56 (the water_vs_dea_s2_wo failures).
Passes: every c1 item under the configured cloud limit between --start and --end.
ramsar-56 straddles the 50HLK/50HMK seam; for dates where both tiles were
scored, extra `seam_overlap` rows use only the ground pixels both windows cover.

Run from the repo root, writing to a new file so the committed CSV is not overwritten:
  uv run python docs/research/2026-10-29-polygon-calibration.py \
      --start YYYY-MM-DD --end YYYY-MM-DD --out PATH.csv [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pystac_client
from affine import Affine

from wetland_change.aoi import load_ramsar, union_bbox_4326
from wetland_change.catalogue.item import parse_item
from wetland_change.config import load_config
from wetland_change.indices import mndwi, ndwi
from wetland_change.mask import clear_mask
from wetland_change.raster.read import RasterioReader, read_stack
from wetland_change.stats import rasterise
from wetland_change.verify.wo import WO_EXCLUDE, WO_WET, dea_reader, find_wo_href
from wetland_change.windows import plan_window

POLYGON_IDS = {"ramsar-15", "ramsar-28", "ramsar-56"}
SEAM_POLYGON = "ramsar-56"
THRESHOLDS = [float(t) + 0.0 for t in np.round(np.arange(-0.50, 0.5001, 0.05), 2)]
MIN_PIXELS = 100
COLUMNS = ["polygon_id", "tile", "item_id", "pass_date", "subset", "method",
           "threshold", "n_mutually_clear", "n_agree", "agreement"]


@dataclass
class Scored:
    """One (polygon, item) window with everything needed to score any pixel subset."""

    polygon_id: str
    tile: str
    item_id: str
    pass_date: str
    transform: Affine
    both: np.ndarray       # clear & inside & WO-clear
    wo_wet: np.ndarray
    layers: dict[tuple[str, float], np.ndarray]  # (method, threshold) -> predicted wet


def predictions(stack) -> dict[tuple[str, float], np.ndarray]:
    nd, mn = ndwi(stack.green, stack.nir), mndwi(stack.green, stack.swir16)
    out: dict[tuple[str, float], np.ndarray] = {}
    with np.errstate(invalid="ignore"):
        for t in THRESHOLDS:
            out[("ndwi", t)] = nd > t
            out[("mndwi", t)] = mn > t
    out[("scl6", 0.0)] = stack.scl == 6
    return out


def rows_for(s: Scored, subset: str, both: np.ndarray, sl=(slice(None), slice(None)),
             wo_wet: np.ndarray | None = None) -> list[list]:
    """CSV rows for one scored window restricted to `both` (already sliced)."""
    n = int(both.sum())
    wet = s.wo_wet[sl] if wo_wet is None else wo_wet
    rows = []
    for (method, t), pred in s.layers.items():
        agree = int(((pred[sl] == wet) & both).sum())
        rows.append([s.polygon_id, s.tile, s.item_id, s.pass_date, subset, method,
                     f"{t:.2f}", n, agree, f"{agree / n:.4f}"])
    return rows


def seam_slices(a: Scored, b: Scored):
    """Index slices into a and b covering the ground pixels both windows contain."""
    ta, tb = a.transform, b.transform
    ha, wa = a.both.shape
    hb, wb = b.both.shape
    xmin = max(ta.c, tb.c)
    xmax = min(ta.c + 10 * wa, tb.c + 10 * wb)
    ymax = min(ta.f, tb.f)
    ymin = max(ta.f - 10 * ha, tb.f - 10 * hb)
    if xmax <= xmin or ymax <= ymin:
        return None
    for t in (ta, tb):
        assert (xmin - t.c) % 10 == 0 and (t.f - ymax) % 10 == 0, "lattices do not align"
    nc, nr = int((xmax - xmin) // 10), int((ymax - ymin) // 10)

    def sl(t: Affine):
        c0, r0 = int((xmin - t.c) // 10), int((t.f - ymax) // 10)
        return (slice(r0, r0 + nr), slice(c0, c0 + nc))

    return sl(ta), sl(tb)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--start", required=True, type=date.fromisoformat,
                        help="first STAC search date, ISO (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, type=date.fromisoformat,
                        help="last STAC search date, ISO (YYYY-MM-DD)")
    parser.add_argument("--out", required=True, type=Path,
                        help="CSV to write; required so a rerun cannot overwrite the committed CSV")
    parser.add_argument("--dry-run", action="store_true",
                        help="load config, list polygons, count STAC items, then exit")
    return parser


def main(args: argparse.Namespace) -> None:
    cfg = load_config(Path("config/pipeline.toml"))
    polys = [p for p in load_ramsar(cfg.aoi.ramsar_path, site_prefixes=cfg.aoi.site_prefixes,
                                    operation_epsg=cfg.aoi.operation_epsg)
             if p.polygon_id in POLYGON_IDS]
    bbox = union_bbox_4326(polys)
    print("polygons:", [(p.polygon_id, round(p.geometry.area / 1e4)) for p in polys])
    print("search bbox:", bbox)

    client = pystac_client.Client.open(cfg.stac.endpoint)
    items = list(client.search(
        collections=[cfg.stac.collection], bbox=list(bbox),
        datetime=f"{args.start}/{args.end}",
        query={"eo:cloud_cover": {"lt": cfg.stac.cloud_cover_max}},
    ).items_as_dicts())
    print(len(items), "items")
    if args.dry_run:
        return

    reader, wo_rd = RasterioReader(), dea_reader()
    scored: list[Scored] = []
    for item in items:
        try:
            scene = parse_item(item, collection=cfg.stac.collection,
                               required_assets=cfg.stac.required_assets)
            grid = reader.open_grid(scene.bands["green"].href)
            wo_href = find_wo_href(scene, bbox)
            if wo_href is None:
                print("skip no WO:", scene.item_id)
                continue
            if wo_rd.open_grid(wo_href).transform != grid.transform:
                print("skip WO grid differs:", scene.item_id)
                continue
            for poly in polys:
                planned = plan_window(poly.geometry, grid)
                if planned is None:
                    print(f"skip no window: {poly.polygon_id} {scene.item_id}")
                    continue
                stack = read_stack(scene, planned, reader)
                inside = rasterise(poly.geometry, stack.transform, stack.shape)
                clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
                wo = wo_rd.read(wo_href, planned.window10)
                both = clear & ((wo & WO_EXCLUDE) == 0)
                if both.sum() < MIN_PIXELS:
                    print(f"skip mutually clear {int(both.sum())} < {MIN_PIXELS}: "
                          f"{poly.polygon_id} {scene.item_id}")
                    continue
                scored.append(Scored(
                    poly.polygon_id, scene.tile, scene.item_id,
                    f"{scene.datetime:%Y-%m-%d}", planned.transform10, both,
                    (wo & WO_WET) > 0, predictions(stack)))
            print(scene.item_id, "done")
        except Exception as exc:
            print("skip", item.get("id"), exc)

    rows: list[list] = []
    for s in scored:
        rows += rows_for(s, "all", s.both)

    by_date: dict[str, dict[str, list[Scored]]] = defaultdict(lambda: defaultdict(list))
    for s in scored:
        if s.polygon_id == SEAM_POLYGON:
            by_date[s.pass_date][s.tile].append(s)
    for date, tiles in sorted(by_date.items()):
        if not {"50HLK", "50HMK"} <= tiles.keys():
            continue
        for a in tiles["50HLK"]:
            for b in tiles["50HMK"]:
                sls = seam_slices(a, b)
                if sls is None:
                    print(f"skip seam: no window overlap on {date}")
                    continue
                for s, sl in ((a, sls[0]), (b, sls[1])):
                    both = s.both[sl]
                    if both.sum() < MIN_PIXELS:
                        print(f"skip seam mutually clear {int(both.sum())}: {s.item_id}")
                        continue
                    rows += rows_for(s, "seam_overlap", both, sl)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        w.writerows(rows)
    print("windows scored:", len(scored), "rows:", len(rows), "->", args.out)

    pooled: dict[tuple[str, str, float], list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        if r[4] == "all":
            p = pooled[(r[0], r[5], float(r[6]))]
            p[0] += r[8]
            p[1] += r[7]
    print("\nbest by polygon and method (pixel-weighted over passes):")
    for pid in sorted(POLYGON_IDS):
        for method in ("ndwi", "mndwi", "scl6"):
            cand = [(t, a / n) for (p, m, t), (a, n) in pooled.items() if p == pid and m == method]
            if cand:
                t, ag = max(cand, key=lambda x: x[1])
                print(f"  {pid:10} {method:5} threshold {t:+.2f} agreement {ag:.4f}")


if __name__ == "__main__":
    main(build_parser().parse_args())
