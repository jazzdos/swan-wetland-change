"""Threshold sweep for NDWI, MNDWI and SCL water against DEA Water Observations.

Record: 2026-10-29-water-calibration.csv is the record of the original run. The
inputs of that run may have changed (Earth Search items, DEA products, the lake
polygons), so a rerun differs from the committed CSV.

The DEA ga_s2_wo_provisional_3 product (provisional WO) keeps about three months of
scenes. The window of the original run has passed, so the committed CSV is the record
and a rerun needs a window inside the current provisional retention. The committed CSV
predates the n_scenes and item_ids columns that this script now writes.

Lakes: the four largest DEA Waterbodies polygons inside the Ramsar sites.
Passes: every c1 item under the configured cloud limit between --start and --end.

Run from the repo root, writing to a new file so the committed CSV is not overwritten:
  uv run python docs/research/2026-10-29-water-calibration.py \
      --start YYYY-MM-DD --end YYYY-MM-DD --out PATH.csv
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from collections.abc import Mapping, Set
from datetime import date
from pathlib import Path

import numpy as np
import pystac_client
from shapely.ops import unary_union

from wetland_change.aoi import load_ramsar, load_waterbodies, union_bbox_4326
from wetland_change.catalogue.item import parse_item
from wetland_change.config import load_config
from wetland_change.indices import mndwi, ndwi
from wetland_change.mask import clear_mask
from wetland_change.raster.read import RasterioReader, read_stack
from wetland_change.stats import rasterise
from wetland_change.verify.wo import WO_EXCLUDE, WO_WET, dea_reader, find_wo_href
from wetland_change.windows import plan_window

THRESHOLDS = np.round(np.arange(-0.30, 0.31, 0.05), 2)
COLUMNS = ["lake", "method", "threshold", "agreement", "n_pixels", "n_scenes", "item_ids"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--start", required=True, type=date.fromisoformat,
                        help="first STAC search date, ISO (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, type=date.fromisoformat,
                        help="last STAC search date, ISO (YYYY-MM-DD)")
    parser.add_argument("--out", required=True, type=Path,
                        help="CSV to write; required so a rerun cannot overwrite the committed CSV")
    return parser


def write_csv(
    tally: Mapping[tuple[str, str, float], list[int]],
    items_by_lake: Mapping[str, Set[str]],
    out: Path,
) -> None:
    """Write one row per (lake, method, threshold) with the scenes that fed the lake."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for (lake, method, threshold), (agree, n_pixels) in sorted(tally.items()):
            item_ids = sorted(items_by_lake.get(lake, ()))
            writer.writerow([lake, method, threshold, f"{agree / n_pixels:.4f}", n_pixels,
                             len(item_ids), ";".join(item_ids)])


def main(args: argparse.Namespace) -> None:
    cfg = load_config(Path("config/pipeline.toml"))
    ramsar = load_ramsar(cfg.aoi.ramsar_path, site_prefixes=cfg.aoi.site_prefixes,
                         operation_epsg=cfg.aoi.operation_epsg)
    ramsar_union = unary_union([p.geometry for p in ramsar])
    lakes = sorted(
        (p for p in load_waterbodies(cfg.aoi.waterbodies_path, operation_epsg=cfg.aoi.operation_epsg)
         if p.geometry.within(ramsar_union)),
        key=lambda p: p.geometry.area, reverse=True,
    )[:4]
    print("lakes:", [(p.polygon_id, round(p.geometry.area / 1e4)) for p in lakes])

    client = pystac_client.Client.open(cfg.stac.endpoint)
    items = list(client.search(
        collections=[cfg.stac.collection], bbox=list(union_bbox_4326(lakes)),
        datetime=f"{args.start}/{args.end}",
        query={"eo:cloud_cover": {"lt": cfg.stac.cloud_cover_max}},
    ).items_as_dicts())
    print(len(items), "items")

    reader, wo_rd = RasterioReader(), dea_reader()
    # key -> [agree, n]; key = (lake, method, threshold)
    tally: dict[tuple[str, str, float], list[int]] = defaultdict(lambda: [0, 0])
    items_by_lake: dict[str, set[str]] = defaultdict(set)
    passes = 0
    for item in items:
        try:
            scene = parse_item(item, collection=cfg.stac.collection, required_assets=cfg.stac.required_assets)
            grid = reader.open_grid(scene.bands["green"].href)
            wo_href = find_wo_href(scene, union_bbox_4326(lakes))
            if wo_href is None:
                print("no WO for", scene.item_id); continue
            if wo_rd.open_grid(wo_href).transform != grid.transform:
                print("WO grid differs for", scene.item_id); continue
            for lake in lakes:
                planned = plan_window(lake.geometry, grid)
                if planned is None or planned.scene_coverage < 0.99:
                    continue
                stack = read_stack(scene, planned, reader)
                inside = rasterise(lake.geometry, stack.transform, stack.shape)
                clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
                wo = wo_rd.read(wo_href, planned.window10)
                both = clear & ((wo & WO_EXCLUDE) == 0)
                if both.sum() < 100:
                    continue
                wo_wet = (wo & WO_WET) > 0
                passes += 1
                items_by_lake[lake.polygon_id].add(scene.item_id)
                nd, mn = ndwi(stack.green, stack.nir), mndwi(stack.green, stack.swir16)
                with np.errstate(invalid="ignore"):
                    for t in THRESHOLDS:
                        for method, arr in (("ndwi", nd), ("mndwi", mn)):
                            agree = int(((arr > t) == wo_wet)[both].sum())
                            tally[(lake.polygon_id, method, float(t))][0] += agree
                            tally[(lake.polygon_id, method, float(t))][1] += int(both.sum())
                agree = int(((stack.scl == 6) == wo_wet)[both].sum())
                tally[(lake.polygon_id, "scl6", 0.0)][0] += agree
                tally[(lake.polygon_id, "scl6", 0.0)][1] += int(both.sum())
            print(scene.item_id, "done")
        except Exception as exc:
            print("skip", item.get("id"), exc)
            continue

    write_csv(tally, items_by_lake, args.out)
    print("lake-scene pairs scored:", passes, "->", args.out)

    overall: dict[tuple[str, float], list[int]] = defaultdict(lambda: [0, 0])
    for (_, method, t), (agree, n) in tally.items():
        overall[(method, t)][0] += agree; overall[(method, t)][1] += n
    print("\nbest by method (pixel-weighted over lakes):")
    for method in ("ndwi", "mndwi", "scl6"):
        best = max(((t, a / n) for (m, t), (a, n) in overall.items() if m == method), key=lambda x: x[1])
        print(f"  {method:5} threshold {best[0]:+.2f} agreement {best[1]:.4f}")


if __name__ == "__main__":
    main(build_parser().parse_args())
