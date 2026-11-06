"""Read-only: why the pipeline is wetter than DEA S2 WO on ramsar-12 (hypotheses G1 to G5).

Hypotheses, grid, edge definition and reading rule are fixed by LEARNINGS.md
"Pre-registered hypotheses (st-7047, 2026-11-06)", Part B. Anonymous public
reads of Earth Search and DEA only; the stored observations are read from the
local backfill and nothing is written outside --out and --report. Never calls
verify_run.

  uv run python docs/research/2026-11-06-ramsar-12-gap.py --ramsar <geojson> --data-root <dir>

--ramsar is the DBCA-010 Ramsar layer (config aoi.ramsar_path is relative and
absent in a worktree). --data-root holds outputs/observations for G5.

For each of the 12 scene-tiles of ramsar-12 in 2026-11-05-wet-area-gap.csv the
stack and the WO raster are read once. clear is clear_mask(...) & inside and
the WO clear rule is `(wo & WO_EXCLUDE) == 0`, as in wo_check. The mutually
clear pixels are the n pixels where both hold. a counts the pixels the
pipeline calls wet and WO calls dry, b the reverse, and
gap_pp = 100 * (a - b) / n.

The edge ring (G3) pads the window with outside pixels before eroding, so
polygon pixels on the window border count as edge. The outputs hold no
timestamps, so a rerun on the same data is deterministic.
"""

from __future__ import annotations

import argparse
import csv
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from wetland_change.aoi import load_ramsar, union_bbox_4326
from wetland_change.catalogue.search import discover, open_client
from wetland_change.config import WaterSetting, load_config
from wetland_change.mask import clear_mask
from wetland_change.raster.read import RasterioReader, read_stack
from wetland_change.stats import rasterise, water_pixels
from wetland_change.store import OutputStore
from wetland_change.verify.wo import WO_EXCLUDE, WO_WET, dea_reader, find_wo_href
from wetland_change.windows import plan_window

logger = logging.getLogger(__name__)

HERE: Final = Path(__file__).resolve().parent
REPO: Final = HERE.parents[1]
GAP_CSV: Final = HERE / "2026-11-05-wet-area-gap.csv"
POLYGON: Final = "ramsar-12"
SCENE_TILE_COUNT: Final = 12
MNDWI_GRID: Final = (-0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20)
LIMIT_PP: Final = 5.0
REPRODUCTION_TOLERANCE_PP: Final = 0.01
EDGE_ITERATIONS: Final = 2
EDGE_RATIO_MIN: Final = 2.0
VEGETATION_SHARE_MIN: Final = 0.50
HISTORY_SHARE_MIN: Final = 0.75
SCL_CLASS_COUNT: Final = 12
SCL_NAMES: Final = (
    "no data",
    "saturated or defective",
    "dark area pixels",
    "cloud shadows",
    "vegetation",
    "not vegetated",
    "water",
    "unclassified",
    "cloud medium probability",
    "cloud high probability",
    "thin cirrus",
    "snow or ice",
)
FIELDS: Final = (
    "item_id",
    "pass_date",
    "tile",
    "method",
    "threshold",
    "n_mutually_clear",
    "a_pipeline_only",
    "b_wo_only",
    "gap_pp",
    "agreement",
    "csv_n",
    "csv_gap_pp",
)
GLOBAL_THRESHOLD: Final = -0.10


@dataclass(frozen=True, slots=True)
class GapRow:
    item_id: str
    pass_date: str
    tile: str
    method: str
    threshold: float | None
    n_mutually_clear: int
    a_pipeline_only: int
    b_wo_only: int
    gap_pp: float
    agreement: float
    csv_n: int | None = None
    csv_gap_pp: float | None = None


@dataclass(frozen=True, slots=True)
class SceneExtras:
    """Global-setting detail of one scene-tile used by the report."""

    pipeline_wet: int
    wo_wet: int
    ring_mutually_clear: int
    ring_a: int
    scl_histogram_of_a: np.ndarray


def erode4(mask: np.ndarray) -> np.ndarray:
    """One 4-neighbour erosion; pixels outside the array count as False."""
    padded = np.pad(mask, 1, constant_values=False)
    return (
        padded[1:-1, 1:-1]
        & padded[:-2, 1:-1]
        & padded[2:, 1:-1]
        & padded[1:-1, :-2]
        & padded[1:-1, 2:]
    )


def edge_ring(inside: np.ndarray, iterations: int = EDGE_ITERATIONS) -> np.ndarray:
    """Inside pixels within `iterations` pixels of an outside pixel."""
    eroded = inside
    for _ in range(iterations):
        eroded = erode4(eroded)
    ring: np.ndarray = inside & ~eroded
    return ring


def disagreement_counts(
    water: np.ndarray, mutually_clear: np.ndarray, wo_wet: np.ndarray
) -> tuple[int, int, int]:
    """(n, a, b) over the mutually clear pixels."""
    count = int(mutually_clear.sum())
    pipeline_only = int((water & ~wo_wet & mutually_clear).sum())
    wo_only = int((~water & wo_wet & mutually_clear).sum())
    return count, pipeline_only, wo_only


def find_scenes(config, item_ids, bbox, polygons):  # type: ignore[no-untyped-def]
    client = open_client(config.stac.endpoint)
    scenes = {}
    for day_text in sorted({item_id.split("_")[2][:8] for item_id in item_ids}):
        day = datetime.strptime(day_text, "%Y%m%d").replace(tzinfo=UTC)
        found = discover(
            client,
            config.stac,
            bbox=bbox,
            polygons_4326=[polygon.geometry_4326 for polygon in polygons],
            created_from=None,
            seen=set(),
            retry_ids=[i for i in item_ids if i.split("_")[2][:8] == day_text],
            datetime_range=(day, day + timedelta(days=1) - timedelta(seconds=1)),
        )
        for scene in found.scenes:
            scenes[scene.item_id] = scene
    return scenes


def measure(
    ramsar: Path,
) -> tuple[list[GapRow], list[str], dict[str, SceneExtras]]:
    """Rows for every method and threshold, reproduction differences, global-setting detail."""
    config = load_config(REPO / "config" / "pipeline.toml")
    config = config.model_copy(
        update={"aoi": config.aoi.model_copy(update={"ramsar_path": ramsar})}
    )
    assert config.stac.collection == "sentinel-2-c1-l2a"
    polygons = load_ramsar(
        config.aoi.ramsar_path,
        site_prefixes=config.aoi.site_prefixes,
        operation_epsg=config.aoi.operation_epsg,
    )
    polygon = next(p for p in polygons if p.polygon_id == POLYGON)
    global_setting = config.water.for_polygon(POLYGON)
    assert global_setting.method == "mndwi"
    assert global_setting.threshold == GLOBAL_THRESHOLD
    reference = pd.read_csv(GAP_CSV)
    reference = reference[reference["polygon_id"] == POLYGON].sort_values(
        ["pass_date", "tile"]
    )
    assert len(reference) == SCENE_TILE_COUNT, len(reference)
    bbox = union_bbox_4326(polygons)
    scenes = find_scenes(config, sorted(reference["item_id"]), bbox, polygons)
    reader = RasterioReader()
    dea = dea_reader()
    agreement_min = global_setting.agreement_min
    settings: list[tuple[str, float | None, WaterSetting]] = [
        (
            "mndwi",
            threshold,
            WaterSetting(
                method="mndwi", threshold=threshold, agreement_min=agreement_min
            ),
        )
        for threshold in MNDWI_GRID
    ]
    settings.append(
        ("scl6", None, WaterSetting(method="scl6", agreement_min=agreement_min))
    )
    rows: list[GapRow] = []
    differences: list[str] = []
    extras: dict[str, SceneExtras] = {}
    for record in reference.itertuples(index=False):
        item_id = str(record.item_id)
        scene = scenes.get(item_id)
        if scene is None:
            differences.append(f"{item_id}: scene not found by discover")
            continue
        grid = reader.open_grid(scene.bands["green"].href)
        planned = plan_window(polygon.geometry, grid)
        wo_href = find_wo_href(scene, bbox)
        if planned is None or wo_href is None:
            differences.append(
                f"{item_id}: no window ({planned is None}) or no WO scene ({wo_href is None})"
            )
            continue
        stack = read_stack(scene, planned, reader)
        inside = rasterise(polygon.geometry, stack.transform, stack.shape)
        wo = dea.read(wo_href, planned.window10)
        clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
        mutually_clear = clear & ((wo & WO_EXCLUDE) == 0)
        wo_wet = (wo & WO_WET) > 0
        ring = edge_ring(inside)
        for method, threshold, setting in settings:
            water = water_pixels(setting, stack, clear)
            count, pipeline_only, wo_only = disagreement_counts(
                water, mutually_clear, wo_wet
            )
            gap_pp = 100 * (pipeline_only - wo_only) / count if count else float("nan")
            is_global = method == "mndwi" and threshold == GLOBAL_THRESHOLD
            rows.append(
                GapRow(
                    item_id=item_id,
                    pass_date=str(record.pass_date),
                    tile=str(record.tile),
                    method=method,
                    threshold=threshold,
                    n_mutually_clear=count,
                    a_pipeline_only=pipeline_only,
                    b_wo_only=wo_only,
                    gap_pp=gap_pp,
                    agreement=1 - (pipeline_only + wo_only) / count
                    if count
                    else float("nan"),
                    csv_n=int(record.n_mutually_clear) if is_global else None,
                    csv_gap_pp=float(record.gap_pp) if is_global else None,
                )
            )
            if not is_global:
                continue
            pipeline_only_mask = water & ~wo_wet & mutually_clear
            extras[item_id] = SceneExtras(
                pipeline_wet=int((water & mutually_clear).sum()),
                wo_wet=int((wo_wet & mutually_clear).sum()),
                ring_mutually_clear=int((ring & mutually_clear).sum()),
                ring_a=int((ring & pipeline_only_mask).sum()),
                scl_histogram_of_a=np.bincount(
                    stack.scl[pipeline_only_mask].astype(int),
                    minlength=SCL_CLASS_COUNT,
                ),
            )
            if count != int(record.n_mutually_clear):
                differences.append(
                    f"{item_id}: n {count} vs csv {int(record.n_mutually_clear)}"
                )
            if not abs(gap_pp - float(record.gap_pp)) <= REPRODUCTION_TOLERANCE_PP:
                differences.append(
                    f"{item_id}: gap_pp {gap_pp:.4f} vs csv {float(record.gap_pp):.4f}"
                )
        logger.info("read %s", item_id)
    return rows, differences, extras


def read_history(data_root: Path) -> tuple[pd.DataFrame, int, int]:
    """Stored ramsar-12 rows, one per item_id, read only.

    Returns the rows, the number of files read and the number of duplicate
    item_id rows dropped (the highest run_id is kept).
    """
    store = OutputStore(str(data_root / "outputs"))
    paths = [p for p in store.list_files("observations") if p.endswith(".parquet")]
    columns = [
        "polygon_id",
        "item_id",
        "datetime",
        "water_ha_index",
        "water_ha_scl",
        "run_id",
    ]
    frames = [
        pd.read_parquet(
            BytesIO(store.read_bytes(path)),
            columns=columns,
            filters=[("polygon_id", "==", POLYGON)],
        )
        for path in paths
    ]
    frame = pd.concat(frames, ignore_index=True)
    frame = frame.sort_values(["item_id", "run_id"], kind="stable")
    deduplicated = frame.drop_duplicates("item_id", keep="last").sort_values("item_id")
    return (
        deduplicated.reset_index(drop=True),
        len(paths),
        len(frame) - len(deduplicated),
    )


def history_section(
    history: pd.DataFrame, files: int, duplicates: int
) -> tuple[list[str], bool]:
    frame = history.copy()
    frame["year"] = pd.to_datetime(frame["datetime"], utc=True).dt.year
    index_ha = frame["water_ha_index"]
    scl_ha = frame["water_ha_scl"]
    wet_rows = frame[(index_ha > 0) | (scl_ha > 0)].copy()
    wet_rows["difference_ha"] = wet_rows["water_ha_index"] - wet_rows["water_ha_scl"]
    over_count = int((wet_rows["difference_ha"] > 0).sum())
    share = over_count / len(wet_rows) if len(wet_rows) else float("nan")
    lines = [
        f"files read={files}, ramsar-12 rows={len(frame)}, duplicate item_id rows dropped="
        f"{duplicates} (kept the highest run_id), null water_ha_index={int(index_ha.isna().sum())}, "
        f"null water_ha_scl={int(scl_ha.isna().sum())}",
        f"rows with water_ha_index or water_ha_scl above 0: {len(wet_rows)}",
        f"rows with water_ha_index > water_ha_scl: {over_count} of {len(wet_rows)}, "
        f"share={share:.4f}",
        "median water_ha_index - water_ha_scl over those rows: "
        f"{wet_rows['difference_ha'].median():.4f} ha",
        "by calendar year (rows with either above 0):",
    ]
    for year, group in wet_rows.groupby("year"):
        year_over = int((group["difference_ha"] > 0).sum())
        lines.append(
            f"  {year}: rows={len(group)}, index>scl={year_over}, "
            f"share={year_over / len(group):.4f}, "
            f"median difference={group['difference_ha'].median():.4f} ha"
        )
    return lines, bool(len(wet_rows)) and share >= HISTORY_SHARE_MIN


def pooled_agreement(group: pd.DataFrame) -> float:
    disagree = group["a_pipeline_only"].sum() + group["b_wo_only"].sum()
    return float(1 - disagree / group["n_mutually_clear"].sum())


def signed_gaps(group: pd.DataFrame) -> str:
    ordered = group.sort_values(["pass_date", "tile"])
    return " ".join(f"{gap:+.2f}" for gap in ordered["gap_pp"])


def build_report(
    rows: list[GapRow],
    differences: list[str],
    extras: dict[str, SceneExtras],
    history_lines: tuple[list[str], bool],
) -> str:
    frame = pd.DataFrame([asdict(row) for row in rows])
    global_rows = frame[
        (frame["method"] == "mndwi") & (frame["threshold"] == GLOBAL_THRESHOLD)
    ].sort_values(["pass_date", "tile"])
    problems = list(differences)
    if len(global_rows) != SCENE_TILE_COUNT:
        problems.append(f"only {len(global_rows)} of {SCENE_TILE_COUNT} rows measured")
    reproduced = not problems
    out = [
        "ramsar-12 wet-area gap, hypotheses G1 to G5 (LEARNINGS.md st-7047 Part B)",
        "",
        "n is mutually clear pixels, a is pipeline wet and WO dry, b is WO wet and "
        "pipeline dry, gap_pp = 100 * (a - b) / n, agreement = 1 - (a + b) / n.",
        "",
        "== Reproduction ==",
        "global setting mndwi > -0.1, one line per scene-tile",
    ]
    for row in global_rows.itertuples(index=False):
        detail = extras[row.item_id]
        out.append(
            f"{row.item_id} n={row.n_mutually_clear} csv_n={int(row.csv_n)} "
            f"gap_pp={row.gap_pp:.4f} csv_gap_pp={row.csv_gap_pp:.4f} "
            f"a={row.a_pipeline_only} b={row.b_wo_only} agreement={row.agreement:.4f} "
            f"pipeline_wet_share={detail.pipeline_wet / row.n_mutually_clear:.4f} "
            f"wo_wet_share={detail.wo_wet / row.n_mutually_clear:.4f}"
        )
    if reproduced:
        out.append(
            "differences from the CSV: none (n equal and gap_pp within 0.01 pp on all 12 rows)"
        )
    else:
        out.append("differences from the CSV:")
        out.extend(f"  {problem}" for problem in problems)
    out.append(f"reproduction: {'passed' if reproduced else 'failed'}")
    verdicts: dict[str, str] = {}

    def section(name: str, title: str) -> bool:
        out.extend(["", f"== {name}, {title} =="])
        if reproduced:
            return True
        verdicts[name] = "not tested, reproduction failed"
        out.append(f"{name}: {verdicts[name]}")
        return False

    if section("G1", "MNDWI threshold"):
        out.append(
            "threshold: rows within 5 pp, mean abs gap, mean signed gap, pooled agreement, "
            "pooled a, pooled b"
        )
        lowest: tuple[float, float] | None = None
        any_threshold_passes = False
        for threshold in MNDWI_GRID:
            group = frame[
                (frame["method"] == "mndwi") & (frame["threshold"] == threshold)
            ]
            within = int((group["gap_pp"].abs() <= LIMIT_PP).sum())
            mean_abs = float(group["gap_pp"].abs().mean())
            any_threshold_passes |= within == SCENE_TILE_COUNT
            if lowest is None or mean_abs < lowest[1]:
                lowest = (threshold, mean_abs)
            out.append(
                f"{threshold:+.2f}: within5={within}/{SCENE_TILE_COUNT} "
                f"mean_abs_gap={mean_abs:.3f} mean_gap={group['gap_pp'].mean():+.3f} "
                f"pooled_agreement={pooled_agreement(group):.4f} "
                f"a={int(group['a_pipeline_only'].sum())} b={int(group['b_wo_only'].sum())}"
            )
        assert lowest is not None
        out.append(
            f"threshold with the lowest mean abs gap: {lowest[0]:+.2f} ({lowest[1]:.3f} pp)"
        )
        out.append("per-row gap_pp by threshold (rows by pass_date then tile):")
        for threshold in MNDWI_GRID:
            group = frame[
                (frame["method"] == "mndwi") & (frame["threshold"] == threshold)
            ]
            out.append(f"  {threshold:+.2f}: {signed_gaps(group)}")
        out.append(
            "some threshold with abs gap <= 5 pp on all 12 rows: "
            f"{'yes' if any_threshold_passes else 'no'}"
        )
        verdicts["G1"] = "supported" if any_threshold_passes else "not supported"
        out.append(f"G1: {verdicts['G1']}")

    if section("G2", "SCL class 6"):
        group = frame[frame["method"] == "scl6"]
        within = int((group["gap_pp"].abs() <= LIMIT_PP).sum())
        out.append(
            f"within5={within}/{SCENE_TILE_COUNT} mean_abs_gap={group['gap_pp'].abs().mean():.3f} "
            f"mean_gap={group['gap_pp'].mean():+.3f} pooled_agreement={pooled_agreement(group):.4f} "
            f"a={int(group['a_pipeline_only'].sum())} b={int(group['b_wo_only'].sum())}"
        )
        out.append(f"per-row gap_pp: {signed_gaps(group)}")
        verdicts["G2"] = "supported" if within == SCENE_TILE_COUNT else "not supported"
        out.append(f"G2: {verdicts['G2']}")

    if section("G3", "edge ring"):
        item_ids = list(global_rows["item_id"])
        total_clear = int(global_rows["n_mutually_clear"].sum())
        total_a = int(global_rows["a_pipeline_only"].sum())
        ring_clear = sum(extras[i].ring_mutually_clear for i in item_ids)
        ring_a = sum(extras[i].ring_a for i in item_ids)
        share_a = ring_a / total_a
        share_clear = ring_clear / total_clear
        ratio = share_a / share_clear
        out.append(
            "ring = inside & ~(two 4-neighbour erosions of inside), summed over 12 rows"
        )
        out.append(f"a-pixels in ring={ring_a} of {total_a}, share={share_a:.4f}")
        out.append(
            f"mutually clear pixels in ring={ring_clear} of {total_clear}, share={share_clear:.4f}"
        )
        out.append(
            f"ratio of the two shares={ratio:.3f}, rule: at least {EDGE_RATIO_MIN:.1f}"
        )
        verdicts["G3"] = "supported" if ratio >= EDGE_RATIO_MIN else "not supported"
        out.append(f"G3: {verdicts['G3']}")

    if section("G4", "SCL class of the a-pixels"):
        histogram = sum(extras[i].scl_histogram_of_a for i in global_rows["item_id"])
        total = int(histogram.sum())
        out.append(
            f"a-pixels summed over 12 rows={total}; b-pixels summed over 12 rows="
            f"{int(global_rows['b_wo_only'].sum())}"
        )
        for scl_class in range(SCL_CLASS_COUNT):
            count = int(histogram[scl_class])
            out.append(
                f"  class {scl_class} ({SCL_NAMES[scl_class]}): {count} ({count / total:.4f})"
            )
        vegetation_share = (histogram[4] + histogram[5]) / total
        out.append(
            f"share of classes 4 and 5={vegetation_share:.4f}, rule: at least "
            f"{VEGETATION_SHARE_MIN:.2f}"
        )
        verdicts["G4"] = (
            "supported" if vegetation_share >= VEGETATION_SHARE_MIN else "not supported"
        )
        out.append(f"G4: {verdicts['G4']}")

    out.extend(["", "== G5, stored history =="])
    lines, history_supported = history_lines
    out.extend(lines)
    out.append(f"rule: share of rows with index > scl at least {HISTORY_SHARE_MIN:.2f}")
    verdicts["G5"] = "supported" if history_supported else "not supported"
    out.append(f"G5: {verdicts['G5']}")
    out.append("")
    meanings = {
        "G1": "some MNDWI threshold gives abs gap <= 5 pp on all 12 rows",
        "G2": "scl6 gives abs gap <= 5 pp on all 12 rows",
        "G3": "the ring share of the a-pixels is at least twice the ring share of the mutually clear pixels",
        "G4": "at least half of the a-pixels are SCL class 4 or 5",
        "G5": "water_ha_index exceeds water_ha_scl on at least 75 percent of stored rows",
    }
    supported = [name for name in meanings if verdicts.get(name) == "supported"]
    if supported:
        out.append(
            "cause: supported hypotheses: "
            + "; ".join(f"{name} ({meanings[name]})" for name in supported)
            + ". The numbers are in the sections above."
        )
    else:
        checked = ", ".join(f"{name} {verdicts[name]}" for name in meanings)
        out.append(
            f"cause: no cause found. Checked: {checked}. The numbers are in the sections above."
        )
    return "\n".join(out) + "\n"


def write_csv(path: Path, rows: list[GapRow]) -> None:
    ordered = sorted(
        rows,
        key=lambda row: (
            row.pass_date,
            row.tile,
            row.method,
            -1.0 if row.threshold is None else row.threshold,
        ),
    )
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in ordered:
            values = {name: getattr(row, name) for name in FIELDS}
            writer.writerow({k: "" if v is None else v for k, v in values.items()})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ramsar-12 wet-area gap, hypotheses G1 to G5"
    )
    parser.add_argument("--ramsar", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument(
        "--out", type=Path, default=HERE / "2026-11-06-ramsar-12-gap.csv"
    )
    parser.add_argument(
        "--report", type=Path, default=HERE / "2026-11-06-ramsar-12-gap.txt"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    rows, differences, extras = measure(args.ramsar)
    history, files, duplicates = read_history(args.data_root)
    write_csv(args.out, rows)
    args.report.write_text(
        build_report(
            rows, differences, extras, history_section(history, files, duplicates)
        )
    )


if __name__ == "__main__":
    main()
