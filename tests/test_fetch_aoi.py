"""Tests for the AOI fetch helper and its timeStamp-independent checksum."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import scripts.fetch_aoi as fetch_aoi
from scripts.fetch_aoi import (
    PolygonIdentity,
    check_override_ids,
    fetch_bytes,
    require_feature_collection,
    stable_geojson_checksum,
)

from wetland_change.config import load_config


def _collection(**overrides: Any) -> dict[str, Any]:
    features = [
        {
            "type": "Feature",
            "id": "wb.1",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[115.8, -32.0], [115.9, -32.0], [115.9, -32.1], [115.8, -32.0]]
                ],
            },
            "properties": {"uid": "r3f0", "area_m2": 1200.5},
        },
        {
            "type": "Feature",
            "id": "wb.2",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[116.0, -32.5], [116.1, -32.5], [116.1, -32.6], [116.0, -32.5]]
                ],
            },
            "properties": {"uid": "r3f1", "area_m2": 800.0},
        },
    ]
    body: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": features,
        "totalFeatures": 2,
        "numberMatched": 2,
        "numberReturned": 2,
        "timeStamp": "2026-10-29T11:21:48.987Z",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}},
    }
    body.update(overrides)
    return body


def _dump(body: dict[str, Any]) -> bytes:
    return json.dumps(body).encode("utf-8")


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


def test_stable_geojson_checksum_ignores_top_level_timestamp() -> None:
    first = _dump(_collection(timeStamp="2026-10-29T11:21:48.987Z"))
    second = _dump(_collection(timeStamp="2026-11-03T02:00:00.001Z"))
    assert hashlib.sha256(first).hexdigest() != hashlib.sha256(second).hexdigest()
    assert stable_geojson_checksum(first) == stable_geojson_checksum(second)


def test_stable_geojson_checksum_matches_payload_without_timestamp() -> None:
    body = _collection()
    del body["timeStamp"]
    assert stable_geojson_checksum(_dump(body)) == stable_geojson_checksum(
        _dump(_collection())
    )


def test_stable_geojson_checksum_changes_when_a_vertex_changes() -> None:
    changed = _collection()
    changed["features"][1]["geometry"]["coordinates"][0][1][0] = 116.1001
    assert stable_geojson_checksum(_dump(_collection())) != stable_geojson_checksum(
        _dump(changed)
    )


def test_stable_geojson_checksum_changes_when_a_property_changes() -> None:
    changed = _collection()
    changed["features"][0]["properties"]["area_m2"] = 1200.6
    assert stable_geojson_checksum(_dump(_collection())) != stable_geojson_checksum(
        _dump(changed)
    )


def test_stable_geojson_checksum_changes_when_another_top_level_field_changes() -> None:
    changed = _collection(numberMatched=3)
    assert stable_geojson_checksum(_dump(_collection())) != stable_geojson_checksum(
        _dump(changed)
    )


def test_stable_geojson_checksum_ignores_formatting_and_key_order() -> None:
    body = _collection()
    reordered = dict(reversed(list(body.items())))
    pretty = json.dumps(reordered, indent=2).encode("utf-8")
    assert stable_geojson_checksum(pretty) == stable_geojson_checksum(_dump(body))


def test_stable_geojson_checksum_rejects_invalid_json() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        stable_geojson_checksum(b"<html>not json</html>")


def test_stable_geojson_checksum_rejects_non_object_json() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        stable_geojson_checksum(b"[1, 2, 3]")


def test_stable_geojson_checksum_known_answer() -> None:
    # Canonical form: sorted keys, "," and ":" separators, UTF-8 without \u
    # escapes, top-level timeStamp dropped, nested timeStamp kept.
    canonical = (
        b'{"features":[{"properties":{"name":"Yalgorup \xc3\xa9tang",'
        b'"timeStamp":"keep"},"type":"Feature"}],"type":"FeatureCollection"}'
    )
    raw = (
        b'{"type": "FeatureCollection", "timeStamp": "2026-10-29T00:00:00Z", '
        b'"features": [{"type": "Feature", "properties": '
        b'{"timeStamp": "keep", "name": "Yalgorup \xc3\xa9tang"}}]}'
    )
    assert stable_geojson_checksum(raw) == hashlib.sha256(canonical).hexdigest()


ARCGIS_ERROR = {"error": {"code": 400, "message": "Unable to complete operation."}}
PEEL = "Peel-Yalgorup System"
FORRESTDALE = "Forrestdale & Thomsons Lakes"
PREFIXES = [FORRESTDALE, PEEL]
BBOX_A = (115.7098, -32.688, 115.7165, -32.6734)
BBOX_B = (115.6838, -32.5718, 115.7086, -32.5599)


def _rect(bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    x0, y0, x1, y1 = bbox
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def _ramsar_feature(
    objectid: int, name: str, bbox: tuple[float, float, float, float]
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"objectid": objectid, "ram_ramsarname": name},
        "geometry": _rect(bbox),
    }


def _ramsar(*features: dict[str, Any]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(features)}


def _shift(bbox: tuple[float, float, float, float], d: float) -> Any:
    return (bbox[0] + d, bbox[1] + d, bbox[2] + d, bbox[3] + d)


IDENTITIES = {
    "ramsar-15": PolygonIdentity(PEEL, BBOX_A),
    "ramsar-28": PolygonIdentity(PEEL, BBOX_B),
}


def _ramsar_two() -> dict[str, Any]:
    return _ramsar(
        _ramsar_feature(15, PEEL, BBOX_A),
        _ramsar_feature(28, PEEL, BBOX_B),
        _ramsar_feature(5, "Lake Warden System", (121.98, -33.8, 122.0, -33.79)),
    )


def _check(
    ramsar: dict[str, Any] | None = None,
    waterbodies: dict[str, Any] | None = None,
    overrides: tuple[str, ...] = ("ramsar-15", "ramsar-28", "dea-r3f0"),
    identities: dict[str, PolygonIdentity] | None = None,
) -> None:
    check_override_ids(
        ramsar if ramsar is not None else _ramsar_two(),
        waterbodies if waterbodies is not None else _collection(),
        overrides,
        PREFIXES,
        identities if identities is not None else IDENTITIES,
    )


def test_require_feature_collection_accepts_a_valid_collection() -> None:
    body = require_feature_collection(_dump(_collection()))
    assert body["type"] == "FeatureCollection"


def test_require_feature_collection_rejects_arcgis_error_body() -> None:
    with pytest.raises(ValueError, match="Unable to complete operation"):
        require_feature_collection(_dump(ARCGIS_ERROR))


def test_require_feature_collection_rejects_html() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        require_feature_collection(b"<html>Service unavailable</html>")


def test_require_feature_collection_rejects_non_object_json() -> None:
    with pytest.raises(ValueError, match="not a JSON object"):
        require_feature_collection(b"[1, 2]")


def test_require_feature_collection_rejects_wrong_type() -> None:
    with pytest.raises(ValueError, match="FeatureCollection"):
        require_feature_collection(_dump(_collection(type="Feature")))


@pytest.mark.parametrize("features", [None, "x", {}, []])
def test_require_feature_collection_rejects_missing_or_empty_features(
    features: Any,
) -> None:
    body = _collection()
    if features is None:
        del body["features"]
    else:
        body["features"] = features
    with pytest.raises(ValueError, match="features"):
        require_feature_collection(_dump(body))


def test_require_feature_collection_rejects_non_dict_features() -> None:
    with pytest.raises(ValueError, match="features"):
        require_feature_collection(_dump(_collection(features=[1, 2])))


def test_fetch_bytes_returns_the_raw_body(monkeypatch: pytest.MonkeyPatch) -> None:
    content = _dump(_collection())
    monkeypatch.setattr(
        "scripts.fetch_aoi.requests.get", lambda *_args, **_kwargs: _Response(content)
    )
    assert fetch_bytes("https://example.test/wfs", {}) == content


def test_fetch_bytes_rejects_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.fetch_aoi.requests.get",
        lambda *_args, **_kwargs: _Response(_dump(ARCGIS_ERROR)),
    )
    with pytest.raises(ValueError, match="Unable to complete operation"):
        fetch_bytes("https://example.test/query", {})


def test_check_override_ids_passes_when_all_present_and_matching() -> None:
    _check()


def test_check_override_ids_passes_with_bbox_shifted_within_tolerance() -> None:
    ramsar = _ramsar(
        _ramsar_feature(15, PEEL, _shift(BBOX_A, 0.0005)),
        _ramsar_feature(28, PEEL, BBOX_B),
    )
    _check(ramsar=ramsar)


def test_check_override_ids_fails_when_ramsar_id_missing() -> None:
    ramsar = _ramsar(
        _ramsar_feature(115, PEEL, BBOX_A), _ramsar_feature(28, PEEL, BBOX_B)
    )
    with pytest.raises(ValueError, match="ramsar-15"):
        _check(ramsar=ramsar)


def test_check_override_ids_fails_when_id_exists_only_on_non_prefix_site() -> None:
    with pytest.raises(ValueError, match="ramsar-5"):
        _check(overrides=("ramsar-5",), identities={})


def test_check_override_ids_fails_when_dea_uid_missing() -> None:
    with pytest.raises(ValueError, match="dea-zzzz"):
        _check(overrides=("ramsar-15", "dea-zzzz"))


def test_check_override_ids_fails_when_id_sits_on_a_different_polygon_same_site() -> (
    None
):
    ramsar = _ramsar(
        _ramsar_feature(15, PEEL, BBOX_B),
        _ramsar_feature(28, PEEL, BBOX_A),
    )
    with pytest.raises(ValueError, match="bounding box") as err:
        _check(ramsar=ramsar)
    assert "ramsar-15" in str(err.value)
    assert "ramsar-28" in str(err.value)


def test_check_override_ids_fails_when_bbox_shifted_just_past_tolerance() -> None:
    # The nearest real same-site polygon to ramsar-15 is 0.028 deg away, so the
    # tolerance must stay close to 0.001 deg.
    ramsar = _ramsar(
        _ramsar_feature(15, PEEL, _shift(BBOX_A, 0.0015)),
        _ramsar_feature(28, PEEL, BBOX_B),
    )
    with pytest.raises(ValueError, match="bounding box") as err:
        _check(ramsar=ramsar)
    assert "ramsar-15" in str(err.value)


@pytest.mark.parametrize("edge", [0, 1, 2, 3])
def test_check_override_ids_fails_when_a_single_edge_moves(edge: int) -> None:
    moved = list(BBOX_A)
    moved[edge] += 0.0015
    ramsar = _ramsar(
        _ramsar_feature(15, PEEL, (moved[0], moved[1], moved[2], moved[3])),
        _ramsar_feature(28, PEEL, BBOX_B),
    )
    with pytest.raises(ValueError, match="bounding box") as err:
        _check(ramsar=ramsar)
    assert "ramsar-15" in str(err.value)


def test_check_override_ids_fails_when_site_name_changed_but_bbox_same() -> None:
    ramsar = _ramsar(
        _ramsar_feature(15, FORRESTDALE, BBOX_A),
        _ramsar_feature(28, PEEL, BBOX_B),
    )
    with pytest.raises(ValueError, match="site name") as err:
        _check(ramsar=ramsar)
    assert PEEL in str(err.value)
    assert FORRESTDALE in str(err.value)


def test_check_override_ids_fails_for_ramsar_override_without_identity_row() -> None:
    with pytest.raises(ValueError, match="OVERRIDE_POLYGONS") as err:
        _check(identities={"ramsar-28": IDENTITIES["ramsar-28"]})
    assert "ramsar-15" in str(err.value)


def test_check_override_ids_fails_when_geometry_unusable() -> None:
    bad = _ramsar_feature(15, PEEL, BBOX_A)
    bad["geometry"] = None
    ramsar = _ramsar(bad, _ramsar_feature(28, PEEL, BBOX_B))
    with pytest.raises(ValueError, match="geometry"):
        _check(ramsar=ramsar)


def test_check_override_ids_skips_features_missing_properties() -> None:
    ramsar = _ramsar_two()
    ramsar["features"].append({"type": "Feature", "geometry": None})
    ramsar["features"].append({"type": "Feature", "properties": {}})
    waterbodies = _collection()
    waterbodies["features"].append({"type": "Feature"})
    _check(ramsar=ramsar, waterbodies=waterbodies)


def test_check_override_ids_reports_every_problem_in_one_message() -> None:
    ramsar = _ramsar(_ramsar_feature(28, FORRESTDALE, BBOX_A))
    with pytest.raises(ValueError, match="pipeline.toml") as err:
        _check(ramsar=ramsar, overrides=("ramsar-15", "ramsar-28", "dea-zzzz"))
    message = str(err.value)
    assert "ramsar-15" in message
    assert "dea-zzzz" in message
    assert "site name" in message
    assert "bounding box" in message
    assert "OVERRIDE_POLYGONS" in message


def test_every_repo_ramsar_override_has_a_pinned_identity() -> None:
    cfg = load_config(Path("config/pipeline.toml"))
    ramsar_keys = {k for k in cfg.water.overrides if k.startswith("ramsar-")}
    assert ramsar_keys == set(fetch_aoi.OVERRIDE_POLYGONS)


RAMSAR_BODY = _ramsar(
    _ramsar_feature(15, PEEL, BBOX_A), _ramsar_feature(28, PEEL, BBOX_B)
)

PIPELINE_TOML = """
[stac]
endpoint = "https://earth-search.aws.element84.com/v1"
collection = "sentinel-2-c1-l2a"
cloud_cover_max = 20.0
watermark_overlap_days = 1
initial_lookback_days = 30
required_assets = ["green", "red", "nir", "swir16", "scl", "product_metadata"]

[aoi]
ramsar_path = "data/external/dbca_010_ramsar_sites.geojson"
waterbodies_path = "data/external/dea_waterbodies_v3_swan.geojson"
site_prefixes = ["Peel-Yalgorup System"]
operation_epsg = 32750

[water]
method = "mndwi"
threshold = -0.1
agreement_min = 0.91
min_valid_fraction = 0.8

[water.overrides.ramsar-15]
method = "scl6"
agreement_min = 0.94

[water.overrides.dea-r3f0]
method = "ndwi"
threshold = -0.15
agreement_min = 0.92

[output]
root = "outputs"
"""


def _setup_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ramsar: bytes,
    waterbodies: bytes,
    identities: dict[str, PolygonIdentity] | None = None,
) -> Path:
    out = tmp_path / "external"
    config = tmp_path / "pipeline.toml"
    config.write_text(PIPELINE_TOML)
    bodies = {fetch_aoi.RAMSAR_URL: ramsar, fetch_aoi.WATERBODIES_URL: waterbodies}
    monkeypatch.setattr(
        "scripts.fetch_aoi.requests.get",
        lambda url, *_args, **_kwargs: _Response(bodies[url]),
    )
    monkeypatch.setattr(fetch_aoi, "OUT", out)
    monkeypatch.setattr(fetch_aoi, "CONFIG", config)
    monkeypatch.setattr(
        fetch_aoi,
        "OVERRIDE_POLYGONS",
        identities
        if identities is not None
        else {"ramsar-15": PolygonIdentity(PEEL, BBOX_A)},
    )
    return out


def test_main_prints_stable_waterbodies_and_raw_ramsar_checksums(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ramsar = _dump(RAMSAR_BODY)
    waterbodies = _dump(_collection())
    out = _setup_main(monkeypatch, tmp_path, ramsar, waterbodies)
    assert fetch_aoi.main() == 0
    rows = capsys.readouterr().out.splitlines()
    ramsar_row = next(r for r in rows if r.startswith("| DBCA-010"))
    wb_row = next(r for r in rows if r.startswith("| DEA Waterbodies"))
    assert hashlib.sha256(ramsar).hexdigest() in ramsar_row
    assert stable_geojson_checksum(waterbodies) in wb_row
    assert hashlib.sha256(waterbodies).hexdigest() not in wb_row
    assert (out / "dea_waterbodies_v3_swan.geojson").read_bytes() == waterbodies
    assert (out / "dbca_010_ramsar_sites.geojson").read_bytes() == ramsar


def _assert_main_fails_and_writes_nothing(
    out: Path, capsys: pytest.CaptureFixture[str], expected: str
) -> None:
    assert fetch_aoi.main() == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: ")
    assert expected in captured.err
    assert not (out / "dea_waterbodies_v3_swan.geojson").exists()
    assert not (out / "dbca_010_ramsar_sites.geojson").exists()


def test_main_fails_and_writes_nothing_when_override_id_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    waterbodies = _collection()
    waterbodies["features"][0]["properties"]["uid"] = "other"
    out = _setup_main(monkeypatch, tmp_path, _dump(RAMSAR_BODY), _dump(waterbodies))
    _assert_main_fails_and_writes_nothing(out, capsys, "dea-r3f0")


def test_main_fails_and_writes_nothing_when_override_bbox_moved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    moved = _ramsar(_ramsar_feature(15, PEEL, BBOX_B))
    out = _setup_main(monkeypatch, tmp_path, _dump(moved), _dump(_collection()))
    _assert_main_fails_and_writes_nothing(out, capsys, "bounding box")


def test_main_fails_on_ramsar_error_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _setup_main(monkeypatch, tmp_path, _dump(ARCGIS_ERROR), _dump(_collection()))
    _assert_main_fails_and_writes_nothing(out, capsys, "Unable to complete operation")


def test_main_keeps_existing_good_files_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    moved = _ramsar(_ramsar_feature(15, PEEL, BBOX_B))
    out = _setup_main(monkeypatch, tmp_path, _dump(moved), _dump(_collection()))
    out.mkdir()
    ramsar_dest = out / "dbca_010_ramsar_sites.geojson"
    wb_dest = out / "dea_waterbodies_v3_swan.geojson"
    ramsar_dest.write_bytes(b"previous good ramsar")
    wb_dest.write_bytes(b"previous good waterbodies")
    assert fetch_aoi.main() == 1
    assert "bounding box" in capsys.readouterr().err
    assert ramsar_dest.read_bytes() == b"previous good ramsar"
    assert wb_dest.read_bytes() == b"previous good waterbodies"
