"""Footer key-value metadata for observation and change GeoParquet files.

Each file records its CRSs, the units of its numeric columns, the SCL classes
the clear-pixel mask drops, and the water method and threshold of the polygons
it holds. The values are a pure function of the rows and the config, with no
timestamps, run ids or versions, so a rewrite stays byte-identical.

The pipeline refuses any scene whose EPSG differs from the operation EPSG
(`process_scene`), so every stored row's source CRS equals the operation CRS
and `source_epsg` equals `operation_epsg`. In a change file the water settings
are those of the config at scoring time; `config_sha256` in the run manifest
pins that config.
"""

from __future__ import annotations

import json
from typing import Final, Literal

import geopandas as gpd

from wetland_change.config import WaterConfig
from wetland_change.mask import CLEAR_BANDS, CLEAR_CLASSES

Kind = Literal["observation", "change"]

_SCL_CLASS_COUNT = 12
_COUNT_PIXELS = "count of 10 m pixels"
_FRACTION = "fraction (0 to 1)"
_HECTARES = "hectares"
_INDEX = "unitless index"

_OBSERVATION_UNITS: dict[str, str] = {
    "scene_coverage": _FRACTION,
    "n_pixels": _COUNT_PIXELS,
    "n_clear": _COUNT_PIXELS,
    "valid_fraction": _FRACTION,
    "cloud_fraction": _FRACTION,
    "water_ha_index": _HECTARES,
    "water_ha_scl": _HECTARES,
    "ndwi_median": _INDEX,
    "mndwi_median": _INDEX,
    "ndvi_median": _INDEX,
    "dea_wo_agreement": _FRACTION,
}

# value, baseline_median and baseline_mad take the unit of the metric named in
# the row's `metric` column.
_PER_METRIC: dict[str, str] = {"water_ha_index": _HECTARES, "ndvi_median": _INDEX}
_CHANGE_UNITS: dict[str, str | dict[str, str]] = {
    "month": "calendar month 1 to 12",
    "n_scenes": "count",
    "scene_coverage": _FRACTION,
    "valid_fraction": _FRACTION,
    "value": _PER_METRIC,
    "z": "unitless (robust z-score)",
    "baseline_median": _PER_METRIC,
    "baseline_mad": _PER_METRIC,
    "baseline_n": "count",
}

CLEAR_PIXEL_RULE = (
    "a pixel is clear when its SCL class is in scl_classes_clear and every one "
    f"of the bands {', '.join(CLEAR_BANDS)} is finite, for every index"
)
WATER_NOTE = (
    "threshold is a unitless index value; water_ha_index uses the polygon's "
    "method and threshold; water_ha_scl counts clear pixels of SCL class 6; in "
    "a change file the water settings are those of the config at scoring time, and "
    "config_sha256 in the run manifest pins the config"
)


FOOTER_KEYS: Final[tuple[str, ...]] = (
    "source_epsg",
    "operation_epsg",
    "geometry_epsg",
    "units",
    "scl_classes_dropped",
    "scl_classes_clear",
    "clear_pixel_rule",
    "water_settings",
    "water_units_note",
)


def _geometry_epsg(frame: gpd.GeoDataFrame) -> int:
    epsg = frame.crs.to_epsg() if frame.crs is not None else None
    if epsg is None:
        raise ValueError("frame geometry has no EPSG code")
    return int(epsg)


def footer_metadata(
    frame: gpd.GeoDataFrame,
    *,
    kind: Kind,
    water: WaterConfig,
    operation_epsg: int,
) -> dict[str, str]:
    """Footer keys and string values for one observation or change file."""
    units = _OBSERVATION_UNITS if kind == "observation" else _CHANGE_UNITS
    settings = {}
    for polygon_id in sorted(set(frame["polygon_id"])):
        setting = water.for_polygon(polygon_id)
        settings[polygon_id] = {
            "method": setting.method,
            "threshold": setting.threshold,
        }
    return {
        # process_scene refuses scenes whose EPSG differs from the operation
        # EPSG, so the source CRS of every row equals the operation CRS.
        "source_epsg": str(operation_epsg),
        "operation_epsg": str(operation_epsg),
        "geometry_epsg": str(_geometry_epsg(frame)),
        "units": json.dumps(units, sort_keys=True),
        "scl_classes_dropped": json.dumps(
            sorted(set(range(_SCL_CLASS_COUNT)) - set(CLEAR_CLASSES))
        ),
        "scl_classes_clear": json.dumps(list(CLEAR_CLASSES)),
        "clear_pixel_rule": CLEAR_PIXEL_RULE,
        "water_settings": json.dumps(settings, sort_keys=True),
        "water_units_note": WATER_NOTE,
    }
