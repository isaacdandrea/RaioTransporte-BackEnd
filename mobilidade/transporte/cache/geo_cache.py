"""Geo-spatial request/response caching utilities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Mapping, MutableMapping, Optional

from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D, Distance as MeasureDistance
from django.utils import timezone

from ..models import GeoRequestCache


def _normalize_request_params(params: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a JSON-serialisable dict with sorted keys for hashing."""

    if isinstance(params, MutableMapping):
        normalized: Dict[str, Any] = {}
        for key in sorted(params):
            value = params[key]
            if isinstance(value, Mapping):
                normalized[key] = _normalize_request_params(value)
            elif isinstance(value, (list, tuple)):
                normalized[key] = [
                    _normalize_request_params(item) if isinstance(item, Mapping) else item
                    for item in value
                ]
            else:
                normalized[key] = value
        return normalized
    return dict(params)


@dataclass(frozen=True)
class CacheConfig:
    """Configuration values for the geo cache service."""

    distance_threshold_m: float = 100.0
    reuse_time_window: timedelta = timedelta(hours=24)
    max_entry_age: timedelta = timedelta(days=7)
    max_entries: int = 500
    cleanup_interval: timedelta = timedelta(minutes=5)

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "CacheConfig":
        if not data:
            return cls()

        def _parse_timedelta(value: Any, default: timedelta) -> timedelta:
            if value is None:
                return default
            if isinstance(value, timedelta):
                return value
            return timedelta(seconds=float(value))

        return cls(
            distance_threshold_m=float(data.get("distance_threshold_m", cls.distance_threshold_m)),
            reuse_time_window=_parse_timedelta(
                data.get("reuse_time_window") or data.get("reuse_time_window_seconds"),
                cls.reuse_time_window,
            ),
            max_entry_age=_parse_timedelta(
                data.get("max_entry_age") or data.get("max_entry_age_seconds"),
                cls.max_entry_age,
            ),
            max_entries=int(data.get("max_entries", cls.max_entries)),
            cleanup_interval=_parse_timedelta(
                data.get("cleanup_interval") or data.get("cleanup_interval_seconds"),
                cls.cleanup_interval,
            ),
        )


@dataclass
class CacheHit:
    payload: Any
    distance_m: float
    entry_id: int
    created_at: datetime


class GeoRequestCacheService:
    """Service responsible for storing and retrieving cached responses."""

    def __init__(self, config: Optional[CacheConfig] = None) -> None:
        if config is None:
            config_data = getattr(settings, "TRANSPORTE_CACHE_CONFIG", None)
            config = CacheConfig.from_dict(config_data)
        self.config = config
        self._last_cleanup: Optional[timezone.datetime] = None

    def get_cached_response(
        self,
        *,
        latitude: float,
        longitude: float,
        request_params: Mapping[str, Any],
    ) -> Optional[CacheHit]:
        """Return a cached response if one exists that matches the criteria."""

        self._purge_expired_entries()
        normalized_params = _normalize_request_params(request_params)
        signature = self._build_signature(normalized_params)
        point = Point(float(longitude), float(latitude), srid=4326)
        now = timezone.now()
        reuse_cutoff = now - self.config.reuse_time_window

        queryset = (
            GeoRequestCache.objects.filter(
                request_signature=signature,
                created_at__gte=reuse_cutoff,
                location__distance_lte=(point, D(m=self.config.distance_threshold_m)),
            )
            .annotate(distance=Distance("location", point))
            .order_by("distance")
        )

        entry = queryset.first()
        if not entry:
            return None

        GeoRequestCache.objects.filter(pk=entry.pk).update(last_accessed_at=now)
        payload = entry.response_data
        distance_value = getattr(entry, "distance", None)
        if isinstance(distance_value, MeasureDistance):
            distance_m = float(distance_value.m)
        elif distance_value is None:
            distance_m = 0.0
        else:
            distance_m = float(distance_value)
        return CacheHit(payload=payload, distance_m=distance_m, entry_id=entry.pk, created_at=entry.created_at)

    def store_response(
        self,
        *,
        latitude: float,
        longitude: float,
        request_params: Mapping[str, Any],
        response_payload: Any,
        request_timestamp: Optional[timezone.datetime] = None,
    ) -> GeoRequestCache:
        """Persist a new cached response for future reuse."""

        self._purge_expired_entries()
        normalized_params = _normalize_request_params(request_params)
        signature = self._build_signature(normalized_params)
        point = Point(float(longitude), float(latitude), srid=4326)
        timestamp = request_timestamp or timezone.now()

        entry = GeoRequestCache.objects.create(
            request_timestamp=timestamp,
            location=point,
            latitude=float(latitude),
            longitude=float(longitude),
            request_parameters=normalized_params,
            request_signature=signature,
            response_data=json.loads(json.dumps(response_payload)),
        )
        return entry

    def _purge_expired_entries(self) -> None:
        now = timezone.now()
        if (
            self._last_cleanup is not None
            and now - self._last_cleanup < self.config.cleanup_interval
        ):
            return

        cutoff = now - self.config.max_entry_age
        GeoRequestCache.objects.filter(created_at__lt=cutoff).delete()

        if self.config.max_entries > 0:
            total = GeoRequestCache.objects.count()
            if total > self.config.max_entries:
                keep_ids = list(
                    GeoRequestCache.objects.order_by("-last_accessed_at")
                    .values_list("id", flat=True)[: self.config.max_entries]
                )
                if keep_ids:
                    GeoRequestCache.objects.exclude(id__in=keep_ids).delete()
                else:
                    GeoRequestCache.objects.all().delete()

        self._last_cleanup = now

    @staticmethod
    def _build_signature(params: Mapping[str, Any]) -> str:
        payload = json.dumps(params, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
