"""DEA Waterbodies v3 wet fraction vs ga_ls_wo_3 wet fraction, Thomsons Lake (st-2522).

Record: 2026-10-30-waterbodies-tolerance.csv is the record of the original run. The
inputs of that run may have changed (the DEA Waterbodies time series, the ga_ls_wo_3
items, the polygon file), so a rerun differs from the committed CSV. The output name
carries the run date, so a rerun on a later day writes a new file and does not
overwrite the record.

2026-10-30-waterbodies-tolerance-extra.csv holds the same passes with the extra
columns n_items and n_px. A rerun writes that file only when --extra-out is given.

Run from the repo root:
  uv run python docs/research/2026-10-30-waterbodies-tolerance.py [--extra-out PATH.csv]
"""
import argparse
import datetime as dt
import io
import os
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("AWS_REGION", "ap-southeast-2")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from pystac_client import Client
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from shapely.geometry import box, shape

UID = "qd635epws_v3"
EXPECTED_PX = 2147
START = "2022-12-01"
CSV_URL = f"https://data.dea.ga.gov.au/derivative/dea_waterbodies/3-0-0/timeseries/qd63/{UID}.csv"
STAC_URL = "https://explorer.dea.ga.gov.au/stac"
today = dt.datetime.now().date().isoformat()
OUT = Path(f"docs/research/{today}-waterbodies-tolerance.csv")

parser = argparse.ArgumentParser(description="Compare DEA Waterbodies v3 with ga_ls_wo_3 wet fractions.")
parser.add_argument("--extra-out", type=Path, default=None,
                    help="optional CSV for the full table with n_items and n_px (default: not written)")
args = parser.parse_args()

# (1) polygon
gdf = gpd.read_file("data/external/dea_waterbodies_v3_swan.geojson")
row = gdf[gdf.uid == UID]
assert len(row) == 1 and row.crs.to_epsg() == 4326
poly4326 = row.geometry.iloc[0]
print("polygon area_m2", row.area_m2.iloc[0], "bounds", poly4326.bounds)

# (2) waterbodies csv
r = requests.get(CSV_URL, timeout=120)
r.raise_for_status()
wb = pd.read_csv(io.StringIO(r.text))
wb["date"] = pd.to_datetime(wb["date"], utc=True).dt.strftime("%Y-%m-%d")
wb = wb[wb["date"] >= START]
valid = wb[wb["pc_wet"].notna()].copy()
print(f"waterbodies rows since {START}: {len(wb)}; valid {len(valid)}; blank {len(wb) - len(valid)}")
dup_wb = valid["date"].duplicated().sum()
print("duplicate valid waterbodies dates:", dup_wb)
valid = valid.drop_duplicates("date", keep="first")
valid["waterbodies_wet_fraction"] = valid["pc_wet"] / 100.0

# (3) STAC
cat = Client.open(STAC_URL)
items = list(
    cat.search(
        collections=["ga_ls_wo_3"],
        bbox=list(poly4326.bounds),
        datetime=f"{START}/{today}",
        max_items=None,
    ).items()
)
by_date = defaultdict(list)
for it in items:
    by_date[it.datetime.strftime("%Y-%m-%d")].append(it)
print("STAC items:", len(items), "dates:", len(by_date))


def to_https(href):
    if href.startswith("s3://"):
        b, k = href[5:].split("/", 1)
        return f"/vsis3/{b}/{k}"
    return href


def read_item(it, crs_cache={}):
    """Return (values array uint8, polygon mask, window transform) or None if no intersect."""
    epsg = it.properties["proj:code"]
    poly = gpd.GeoSeries([poly4326], crs=4326).to_crs(epsg).iloc[0]
    with rasterio.open(to_https(it.assets["water"].href)) as src:
        if not box(*src.bounds).intersects(poly):
            return None
        win = from_bounds(*poly.bounds, transform=src.transform)
        win = Window(
            int(np.floor(win.col_off + 1e-6)),
            int(np.floor(win.row_off + 1e-6)),
            int(np.ceil(win.width - 1e-6)),
            int(np.ceil(win.height - 1e-6)),
        )
        arr = src.read(1, window=win, boundless=True, fill_value=1)
        wtf = src.window_transform(win)
    mask = geometry_mask([poly], out_shape=arr.shape, transform=wtf, all_touched=False, invert=True)
    return arr, mask, wtf


def combine(reads):
    """Combine per-item arrays on the same grid into one polygon-pixel vector."""
    arrs = [a[m] for a, m, _ in reads]
    npx = {len(a) for a in arrs}
    assert len(npx) == 1, npx
    stack = np.stack(arrs)  # items x pixels
    wet_any = (stack == 128).any(axis=0)
    out = np.empty(stack.shape[1], dtype=np.uint8)
    for j in range(stack.shape[1]):
        if wet_any[j]:
            out[j] = 128
        else:
            ok = stack[:, j][(stack[:, j] & 1) == 0]
            out[j] = ok[0] if len(ok) else 1
    return out


records, dropped, notes = [], [], []
px_counts = set()
for d in sorted(valid["date"]):
    cands = by_date.get(d, [])
    reads = []
    for it in cands:
        res = read_item(it)
        if res is not None:
            reads.append((it, *res))
    if not reads:
        dropped.append(d)
        continue
    # items from the same date share the same CRS/grid in practice; check transforms
    tfs = {tuple(r[3])[:6] for r in reads}
    if len(tfs) > 1:
        notes.append(f"{d}: differing window transforms across {len(reads)} items")
        # reproject-free fallback: use the item with most non-nodata polygon pixels
        reads = [max(reads, key=lambda r: (r[1][r[2]] & 1 == 0).sum())]
    vals = combine([(a, m, t) for _, a, m, t in reads])
    px_counts.add(len(vals))
    n = len(vals)
    wet = (vals == 128).sum()
    clean = np.isin(vals, (0, 128)).sum()
    wbrow = valid[valid["date"] == d].iloc[0]
    records.append(
        dict(
            date=d,
            waterbodies_wet_fraction=wbrow["waterbodies_wet_fraction"],
            wo_wet_fraction=wet / n,
            valid_fraction=clean / n,
            n_items=len(reads),
            n_px=n,
        )
    )
print("polygon pixel counts seen:", px_counts)
print("dropped (no WO item):", len(dropped), dropped)
for n in notes:
    print("NOTE", n)

df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
df["difference"] = df["waterbodies_wet_fraction"] - df["wo_wet_fraction"]
df["waterbodies_wet_fraction"] = df["waterbodies_wet_fraction"].round(4)
df["difference"] = (df["waterbodies_wet_fraction"] - df["wo_wet_fraction"]).round(6)
df["wo_wet_fraction"] = df["wo_wet_fraction"].round(6)
df["valid_fraction"] = df["valid_fraction"].round(6)

# sanity
assert not df["date"].duplicated().any()
for c in ["waterbodies_wet_fraction", "wo_wet_fraction", "valid_fraction"]:
    assert df[c].between(0, 1).all(), c
assert len(df) > 50, len(df)
if "2026-10-10" in set(df["date"]):
    r10 = df[df["date"] == "2026-10-10"].iloc[0]
    assert abs(r10.waterbodies_wet_fraction - 0.9041) < 1e-9, r10.waterbodies_wet_fraction
    assert abs(r10.wo_wet_fraction - r10.waterbodies_wet_fraction) <= 0.05, r10.wo_wet_fraction
if px_counts != {EXPECTED_PX}:
    print(
        f"WARNING polygon pixel count differs from {EXPECTED_PX}: {px_counts}. The polygon is aligned to the "
        "30 m EPSG:3577 grid (area 2147.0 px there); in the WO UTM grid (EPSG:32650) it is a rotated shape "
        "of 2145.9 px, so the pixel-centre mask yields 2145 and the denominators differ by 2 px."
    )

OUT.parent.mkdir(parents=True, exist_ok=True)
df[["date", "waterbodies_wet_fraction", "wo_wet_fraction", "difference", "valid_fraction"]].to_csv(OUT, index=False)
if args.extra_out is not None:
    args.extra_out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.extra_out, index=False)

ad = df["difference"].abs() * 100
print(f"\nwrote {OUT}")
print(f"passes: {len(df)}  dropped: {len(dropped)}")
print(f"abs diff pp: median {ad.median():.3f}  p90 {np.percentile(ad, 90):.3f}  max {ad.max():.3f}")
print("passes with abs diff > 5 pp:", int((ad > 5).sum()))
print("five largest abs differences:")
top = df.assign(abs_pp=ad).nlargest(5, "abs_pp")
print(top[["date", "waterbodies_wet_fraction", "wo_wet_fraction", "difference", "valid_fraction", "n_items", "abs_pp"]].to_string(index=False))
