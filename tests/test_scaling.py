from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import pytest

from tests.conftest import FIXTURE_DIR, REQUIRED_ASSETS
from wetland_change.catalogue.item import BandSpec, parse_item
from wetland_change.raster.scaling import (
    EsaScaling,
    ScalingMismatch,
    check_band_scaling,
    parse_product_metadata,
    to_reflectance,
)

XML = (FIXTURE_DIR / "product_metadata.xml").read_text()


def test_parse_fixture_xml() -> None:
    esa = parse_product_metadata(XML)
    assert esa == EsaScaling(quantification=10000.0, add_offset=-1000.0)
    assert esa.scale == pytest.approx(1e-4)
    assert esa.offset == pytest.approx(-0.1)


def test_fixture_item_bands_match_xml(fixture_item: dict[str, Any]) -> None:
    scene = parse_item(
        fixture_item, collection="sentinel-2-c1-l2a", required_assets=REQUIRED_ASSETS
    )
    esa = parse_product_metadata(XML)
    for band in scene.bands.values():
        check_band_scaling(band, esa)


def test_tampered_offset_is_refused(fixture_item: dict[str, Any]) -> None:
    scene = parse_item(
        fixture_item, collection="sentinel-2-c1-l2a", required_assets=REQUIRED_ASSETS
    )
    bad = dataclasses.replace(scene.bands["green"], offset=0.0)
    with pytest.raises(ScalingMismatch, match="offset"):
        check_band_scaling(bad, parse_product_metadata(XML))


def test_xml_without_quantification_is_refused() -> None:
    with pytest.raises(ScalingMismatch, match="BOA_QUANTIFICATION_VALUE"):
        parse_product_metadata("<root><BOA_ADD_OFFSET>-1000</BOA_ADD_OFFSET></root>")


def test_xml_with_mixed_offsets_is_refused() -> None:
    xml = (
        "<root><BOA_QUANTIFICATION_VALUE>10000</BOA_QUANTIFICATION_VALUE>"
        "<BOA_ADD_OFFSET>-1000</BOA_ADD_OFFSET><BOA_ADD_OFFSET>0</BOA_ADD_OFFSET></root>"
    )
    with pytest.raises(ScalingMismatch, match="BOA_ADD_OFFSET"):
        parse_product_metadata(xml)


def test_to_reflectance_scales_and_masks_nodata() -> None:
    band = BandSpec("green", "x", nodata=0, scale=1e-4, offset=-0.1, resolution=10)
    dn = np.array([[0, 1000], [11000, 6000]], dtype=np.uint16)
    out = to_reflectance(dn, band)
    assert out.dtype == np.float32
    assert np.isnan(out[0, 0])
    np.testing.assert_allclose(out[0, 1], 0.0, atol=1e-6)
    np.testing.assert_allclose(out[1, 0], 1.0, atol=1e-6)
    np.testing.assert_allclose(out[1, 1], 0.5, atol=1e-6)


def test_to_reflectance_rejects_float_input() -> None:
    band = BandSpec("green", "x", nodata=0, scale=1e-4, offset=-0.1, resolution=10)
    with pytest.raises(TypeError):
        to_reflectance(np.zeros((2, 2), dtype=np.float32), band)
