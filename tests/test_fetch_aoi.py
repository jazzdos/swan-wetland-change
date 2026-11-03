"""Tests for the AOI fetch helper and its timeStamp-independent checksum."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import scripts.fetch_aoi as fetch_aoi
from scripts.fetch_aoi import fetch, stable_geojson_checksum


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


def test_fetch_with_stable_checksum_writes_raw_bytes_and_returns_stable_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    content = _dump(_collection())
    monkeypatch.setattr(
        "scripts.fetch_aoi.requests.get", lambda *_args, **_kwargs: _Response(content)
    )
    dest = tmp_path / "waterbodies.geojson"
    result = fetch(
        "https://example.test/wfs", {}, dest, checksum=stable_geojson_checksum
    )
    assert dest.read_bytes() == content
    assert result == stable_geojson_checksum(content)
    assert result != hashlib.sha256(content).hexdigest()


def test_fetch_without_checksum_returns_raw_sha256(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    content = _dump(_collection())
    monkeypatch.setattr(
        "scripts.fetch_aoi.requests.get", lambda *_args, **_kwargs: _Response(content)
    )
    dest = tmp_path / "ramsar.geojson"
    assert (
        fetch("https://example.test/query", {}, dest)
        == hashlib.sha256(content).hexdigest()
    )
    assert dest.read_bytes() == content


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


def test_fetch_keeps_destination_when_checksum_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "scripts.fetch_aoi.requests.get",
        lambda *_args, **_kwargs: _Response(b"<ServiceExceptionReport/>"),
    )
    dest = tmp_path / "waterbodies.geojson"
    dest.write_bytes(b"previous good content")
    with pytest.raises(ValueError, match="not valid JSON"):
        fetch("https://example.test/wfs", {}, dest, checksum=stable_geojson_checksum)
    assert dest.read_bytes() == b"previous good content"


def test_main_prints_stable_waterbodies_and_raw_ramsar_checksums(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ramsar = _dump({"type": "FeatureCollection", "features": []})
    waterbodies = _dump(_collection())
    bodies = {
        fetch_aoi.RAMSAR_URL: ramsar,
        fetch_aoi.WATERBODIES_URL: waterbodies,
    }
    monkeypatch.setattr(
        "scripts.fetch_aoi.requests.get",
        lambda url, *_args, **_kwargs: _Response(bodies[url]),
    )
    monkeypatch.setattr(fetch_aoi, "OUT", tmp_path)
    assert fetch_aoi.main() == 0
    rows = capsys.readouterr().out.splitlines()
    ramsar_row = next(r for r in rows if r.startswith("| DBCA-010"))
    wb_row = next(r for r in rows if r.startswith("| DEA Waterbodies"))
    assert hashlib.sha256(ramsar).hexdigest() in ramsar_row
    assert stable_geojson_checksum(waterbodies) in wb_row
    assert hashlib.sha256(waterbodies).hexdigest() not in wb_row
    assert (tmp_path / "dea_waterbodies_v3_swan.geojson").read_bytes() == waterbodies
    assert (tmp_path / "dbca_010_ramsar_sites.geojson").read_bytes() == ramsar
