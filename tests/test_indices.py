from __future__ import annotations

import numpy as np
import pytest

from wetland_change.indices import mndwi, ndvi, ndwi, normalised_difference


def test_known_values() -> None:
    green = np.array([0.3, 0.1], dtype=np.float32)
    nir = np.array([0.1, 0.3], dtype=np.float32)
    np.testing.assert_allclose(ndwi(green, nir), [0.5, -0.5], atol=1e-6)
    np.testing.assert_allclose(ndvi(nir, green), [-0.5, 0.5], atol=1e-6)
    np.testing.assert_allclose(mndwi(green, nir), [0.5, -0.5], atol=1e-6)
    assert ndwi(green, nir).dtype == np.float32


def test_zero_denominator_is_nan_not_warning() -> None:
    with np.errstate(all="raise"):
        out = normalised_difference(np.array([0.0, 0.2]), np.array([0.0, 0.2]))
    assert np.isnan(out[0])
    assert out[1] == 0.0


def test_nan_propagates() -> None:
    out = ndwi(np.array([np.nan, 0.2]), np.array([0.1, 0.1]))
    assert np.isnan(out[0]) and np.isfinite(out[1])


def test_integer_input_is_refused() -> None:
    with pytest.raises(TypeError, match="integer"):
        ndwi(np.array([3000], dtype=np.uint16), np.array([1000], dtype=np.uint16))


def test_matches_spyndex_on_random_reflectance() -> None:
    spyndex = pytest.importorskip("spyndex")
    rng = np.random.default_rng(42)
    g, n, r, s = (rng.uniform(0.0, 0.6, size=(32, 32)) for _ in range(4))
    np.testing.assert_allclose(
        ndwi(g, n), spyndex.computeIndex("NDWI", params={"G": g, "N": n}), atol=1e-6
    )
    np.testing.assert_allclose(
        mndwi(g, s), spyndex.computeIndex("MNDWI", params={"G": g, "S1": s}), atol=1e-6
    )
    np.testing.assert_allclose(
        ndvi(n, r), spyndex.computeIndex("NDVI", params={"N": n, "R": r}), atol=1e-6
    )
