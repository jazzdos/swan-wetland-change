import numpy as np

from wetland_change.mask import (
    CLEAR_CLASSES,
    CLOUD_CLASSES,
    EXCLUDED_CLASSES,
    clear_mask,
    cloud_mask,
    upsample_2x,
    water_mask_scl,
)


def test_class_sets_partition_all_twelve_classes() -> None:
    assert set(CLEAR_CLASSES) | set(EXCLUDED_CLASSES) == set(range(12))
    assert not set(CLEAR_CLASSES) & set(EXCLUDED_CLASSES)
    assert set(CLOUD_CLASSES) <= set(EXCLUDED_CLASSES)


def test_upsample_2x_repeats_each_pixel() -> None:
    a = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)
    up = upsample_2x(a)
    assert up.shape == (4, 6)
    assert up[0, 0] == up[1, 1] == 1
    assert up[3, 5] == up[2, 4] == 6
    assert up.dtype == np.uint8


def test_clear_mask_requires_clear_class_and_finite_bands() -> None:
    scl = np.array([[4, 6], [9, 0]], dtype=np.uint8)
    band = np.array([[0.1, np.nan], [0.2, 0.3]], dtype=np.float32)
    out = clear_mask(scl, band)
    assert out.tolist() == [[True, False], [False, False]]


def test_cloud_and_water_masks() -> None:
    scl = np.array([[8, 9, 10, 6, 4]], dtype=np.uint8)
    assert cloud_mask(scl).tolist() == [[True, True, True, False, False]]
    assert water_mask_scl(scl).tolist() == [[False, False, False, True, False]]
