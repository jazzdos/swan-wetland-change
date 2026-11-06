"""Items since 2022-01-01 over the AOI, Earth Search c1 vs CDSE.

Record: 2026-10-29-backfill-count.csv is the record of the original run. The inputs of
that run may have changed (both catalogues keep adding and reprocessing items), so a
rerun differs from the committed CSV. The script writes that path, so a rerun
overwrites it; restore it with git afterwards.

Run from the repo root:  uv run python docs/research/2026-10-29-backfill-count.py
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pystac_client

from wetland_change.aoi import load_ramsar, union_bbox_4326
from wetland_change.config import load_config

CDSE = "https://stac.dataspace.copernicus.eu/v1"
OUT = Path("docs/research/2026-10-29-backfill-count.csv")
START, END = "2022-01-01", "2026-10-29"

cfg = load_config(Path("config/pipeline.toml"))
bbox = list(union_bbox_4326(load_ramsar(
    cfg.aoi.ramsar_path, site_prefixes=cfg.aoi.site_prefixes, operation_epsg=cfg.aoi.operation_epsg
)))
print("bbox", [round(b, 3) for b in bbox])

es = pystac_client.Client.open(cfg.stac.endpoint)
es_items = list(es.search(
    collections=[cfg.stac.collection], bbox=bbox, datetime=f"{START}/{END}",
    query={"eo:cloud_cover": {"lt": cfg.stac.cloud_cover_max}},
).items_as_dicts())
es_count = Counter(
    (i["properties"]["grid:code"][-5:], i["properties"]["datetime"][:7]) for i in es_items
)
print("Earth Search c1 items under cloud limit:", len(es_items))

cd = pystac_client.Client.open(CDSE)
cd_items = [
    i for i in cd.search(
        collections=["sentinel-2-l2a"], bbox=bbox, datetime=f"{START}/{END}"
    ).items_as_dicts()
    if float(i["properties"].get("eo:cloud_cover", 101)) < cfg.stac.cloud_cover_max
]
cd_count = Counter(
    (i["properties"].get("grid:code", "?")[-5:], i["properties"]["datetime"][:7]) for i in cd_items
)
print("CDSE sentinel-2-l2a items under cloud limit:", len(cd_items))

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["tile", "month", "earth_search_c1", "cdse"])
    for key in sorted(es_count.keys() | cd_count.keys()):
        w.writerow([*key, es_count.get(key, 0), cd_count.get(key, 0)])
gaps = [(k, es_count.get(k, 0), cd_count[k]) for k in cd_count if es_count.get(k, 0) < cd_count[k]]
print("tile-months where c1 has fewer items than CDSE:", len(gaps))
for k, a, b in sorted(gaps)[:20]:
    print("  ", k, a, b)
print("->", OUT)
