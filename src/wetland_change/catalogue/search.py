"""Earth Search discovery with bounded retries and client-side re-checks.

Earth Search v1 supports the query and sort extensions and silently ignores
CQL2, so the cloud-cover and `created` filters go in `query`, and every
result is re-checked here before it is trusted.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, Self, cast

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from urllib3.util.retry import Retry

from wetland_change.catalogue.item import (
    ItemGuardError,
    SceneItem,
    parse_item,
    parse_timestamp,
)
from wetland_change.config import StacConfig

logger = logging.getLogger(__name__)

STAC_RETRY_STATUSES: tuple[int, ...] = (429, 502, 503, 504)
STAC_RETRY_TOTAL = 5
STAC_RETRY_BACKOFF = 1.0


class StacSearch(Protocol):
    def items_as_dicts(self) -> Iterator[dict[str, Any]]: ...


class StacClient(Protocol):
    """The slice of `pystac_client.Client` used here; tests inject a fake."""

    def search(self, **kwargs: Any) -> StacSearch: ...


class _LoggingRetry(Retry):
    """A `Retry` that logs each retried status with its attempt number."""

    #: urllib3 retries these when a Retry-After header is present regardless
    #: of status_forcelist; restrict it to the same set.
    RETRY_AFTER_STATUS_CODES = frozenset(STAC_RETRY_STATUSES)

    def increment(
        self,
        method: str | None = None,
        url: str | None = None,
        response: Any = None,
        error: Exception | None = None,
        _pool: Any = None,
        _stacktrace: Any = None,
    ) -> Self:
        new_retry = super().increment(method, url, response, error, _pool, _stacktrace)
        if response is not None and response.status in STAC_RETRY_STATUSES:
            logger.warning(
                "STAC %s %s returned %s; retry attempt %d of %s",
                method,
                url,
                response.status,
                len(new_retry.history),
                len(new_retry.history) + int(new_retry.total or 0),
            )
        return new_retry


def make_stac_retry(
    *, total: int = STAC_RETRY_TOTAL, backoff_factor: float = STAC_RETRY_BACKOFF
) -> Retry:
    """Bounded retry for transient STAC gateway errors; POST search included."""
    return _LoggingRetry(
        total=total,
        status=total,
        status_forcelist=STAC_RETRY_STATUSES,
        allowed_methods=None,
        backoff_factor=backoff_factor,
        raise_on_status=False,
    )


def open_client(endpoint: str) -> StacClient:
    """Open the live client. Imported lazily so unit tests never need it."""
    from pystac_client import Client
    from pystac_client.stac_api_io import StacApiIO

    stac_io = StacApiIO(max_retries=make_stac_retry())
    return cast(StacClient, Client.open(endpoint, stac_io=stac_io))


def _rfc3339(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def build_search_kwargs(
    cfg: StacConfig,
    *,
    bbox: tuple[float, float, float, float],
    created_from: datetime | None,
    ids: list[str] | None = None,
) -> dict[str, Any]:
    """Keyword arguments for `Client.search`, using only query and sort."""
    query: dict[str, Any] = {"eo:cloud_cover": {"lt": cfg.cloud_cover_max}}
    if created_from is not None:
        query["created"] = {"gte": _rfc3339(created_from)}
    kwargs: dict[str, Any] = {
        "collections": [cfg.collection],
        "bbox": list(bbox),
        "query": query,
        "sortby": [{"field": "properties.created", "direction": "asc"}],
    }
    if ids:
        kwargs["ids"] = ids
    return kwargs


@dataclass
class Discovery:
    scenes: list[SceneItem] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    skipped_seen: int = 0
    skipped_filter: int = 0


def discover(
    client: StacClient,
    cfg: StacConfig,
    *,
    bbox: tuple[float, float, float, float],
    polygons_4326: list[BaseGeometry],
    created_from: datetime | None,
    seen: set[tuple[str, datetime]],
    retry_ids: Iterable[str] = (),
) -> Discovery:
    """New scenes since the watermark plus explicit retries, re-checked locally.

    `seen` holds (item id, parsed `updated`) pairs already processed
    successfully; an item republished with a new `updated` is processed again.
    """
    kwargs = build_search_kwargs(cfg, bbox=bbox, created_from=created_from)
    candidates = list(client.search(**kwargs).items_as_dicts())
    retry_list = list(retry_ids)
    if retry_list:
        retry_kwargs = build_search_kwargs(
            cfg, bbox=bbox, created_from=None, ids=retry_list
        )
        candidates.extend(client.search(**retry_kwargs).items_as_dicts())

    result = Discovery()
    done: set[str] = set()
    for item in candidates:
        item_id = str(item.get("id"))
        if item_id in done:
            continue
        done.add(item_id)
        try:
            props: dict[str, Any] = item.get("properties", {})
            updated_raw = props.get("updated")
            if updated_raw and (item_id, parse_timestamp(str(updated_raw))) in seen:
                result.skipped_seen += 1
                continue
            cloud = props.get("eo:cloud_cover")
            if cloud is None or float(cloud) >= cfg.cloud_cover_max:
                result.skipped_filter += 1
                continue
            footprint = shape(item["geometry"])
            if not any(footprint.intersects(poly) for poly in polygons_4326):
                result.skipped_filter += 1
                continue
            scene = parse_item(
                item, collection=cfg.collection, required_assets=cfg.required_assets
            )
        except (ItemGuardError, KeyError, TypeError, ValueError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            logger.warning("rejected %s: %s", item_id, reason)
            result.rejected.append((item_id, reason))
            continue
        result.scenes.append(scene)
    result.scenes.sort(key=lambda s: (s.created, s.item_id))
    return result
