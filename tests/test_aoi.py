from pathlib import Path

import pytest
from shapely.geometry import Polygon

from wetland_change.aoi import (
    AoiPolygon,
    load_ramsar,
    load_waterbodies,
    union_bbox_4326,
)

FIX = Path(__file__).parent / "fixtures" / "aoi"


def test_load_ramsar_filters_by_prefix_and_reprojects() -> None:
    polys = load_ramsar(
        FIX / "ramsar_mini.geojson",
        site_prefixes=["Forrestdale & Thomsons Lakes"],
        operation_epsg=32750,
    )
    assert [p.polygon_id for p in polys] == ["ramsar-52", "ramsar-56"]
    assert all(p.layer == "ramsar" for p in polys)
    assert all(p.site == "Forrestdale & Thomsons Lakes" for p in polys)
    # EPSG:32750 metres: Thomsons box is about 2.4 km by 2.7 km
    minx, miny, maxx, maxy = polys[0].geometry.bounds
    assert 2000 < maxx - minx < 3000
    assert 2000 < maxy - miny < 3000
    assert isinstance(polys[0].geometry_4326, Polygon)


def test_load_waterbodies_uses_uid() -> None:
    polys = load_waterbodies(FIX / "waterbodies_mini.geojson", operation_epsg=32750)
    assert polys[0].polygon_id == "dea-qd635epws_v3"
    assert polys[0].layer == "dea_waterbody"
    assert polys[0].site == "qd635epws_v3"


def test_union_bbox_4326() -> None:
    polys = load_ramsar(
        FIX / "ramsar_mini.geojson",
        site_prefixes=["Forrestdale"],
        operation_epsg=32750,
    )
    bbox = union_bbox_4326(polys)
    assert bbox == pytest.approx((115.817, -32.168, 115.946, -32.138), abs=1e-6)


def test_missing_crs_is_rejected(tmp_path: Path) -> None:
    nocrs = tmp_path / "nocrs.geojson"
    nocrs.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature",'
        '"properties":{"objectid":1,"ram_ramsarname":"X"},"geometry":'
        '{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}}]}'
    )
    with pytest.raises(ValueError, match="CRS"):
        load_ramsar(nocrs, site_prefixes=["X"], operation_epsg=32750, assume_crs=None)


def test_aoi_polygon_is_frozen() -> None:
    polys = load_waterbodies(FIX / "waterbodies_mini.geojson", operation_epsg=32750)
    with pytest.raises(AttributeError):
        polys[0].site = "other"  # type: ignore[misc]
    assert isinstance(polys[0], AoiPolygon)
