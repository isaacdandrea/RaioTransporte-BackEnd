"""Views for the transporte app."""

import json
import logging
import queue
import threading
import time
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, Tuple

import pytz
from django.conf import settings
from django.db import close_old_connections
from django.http import StreamingHttpResponse
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .algorithms.calcular_raio_csa import calcular_raio
from .cache import GeoRequestCacheService

logger = logging.getLogger("transporte.debug")
if settings.DEBUG:
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _log_debug(metrics: Dict[str, Any]) -> None:
    """Emit a structured debug log when DEBUG is enabled."""

    logger.info(
        (
            "Request %(method)s %(path)s completed in %(request_duration_ms)s ms "
            "(algorithm %(algorithm_duration_ms)s ms) | Features: total=%(features_total)s, "
            "points=%(point_features)s, polygons=%(polygon_features)s | "
            "Walking network: computed=%(walking_network_computed)s, reachable_nodes=%(reachable_nodes)s, "
            "reachable_within_horizon=%(reachable_within_horizon)s, buffers=%(buffers_generated)s | "
            "Stops: total=%(stops_total)s, initial_walk=%(initial_walk_stops)s | "
            "Connections processed=%(connections_loaded)s, expanded_nodes=%(expanded_nodes)s, "
            "walk_relax=%(walking_relaxations)s, conn_relax=%(connection_relaxations)s | "
            "Geometry union=%(union_geometry_type)s"
        ),
        metrics,
    )


cache_service = GeoRequestCacheService()


PRESET_CONFIGS: Dict[str, Tuple[str, dtime]] = {
    "DEFAULT": ("tuesday", dtime(15, 0)),
    "DIA_SEMANA_TRAFEGO": ("thursday", dtime(18, 30)),
    "FINAL_DE_SEMANA": ("saturday", dtime(11, 0)),
}

WEEKDAY_NAME_TO_ISO = {
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
    "sunday": 7,
}


def _resolve_raio_params(data: Dict[str, Any]) -> Tuple[float, float, int, str, int, str]:
    """Validate and normalize request data for raio de alcance computations."""

    lat = float(data["lat"])
    lon = float(data["lon"])
    tempo = int(data["tempo"])

    tz = pytz.timezone("America/Sao_Paulo")

    preset_raw = data.get("presetsDia")
    preset_key = (
        preset_raw.strip().upper()
        if isinstance(preset_raw, str)
        else "DEFAULT"
    )
    dia_alvo, hora_alvo = PRESET_CONFIGS.get(
        preset_key, PRESET_CONFIGS["DEFAULT"]
    )

    hoje = datetime.now(tz).date()
    dia_atual_num = hoje.isoweekday()
    dia_alvo_num = WEEKDAY_NAME_TO_ISO[dia_alvo]
    dias_ate_alvo = (dia_alvo_num - dia_atual_num) % 7
    # ``data_alvo`` is not used afterwards but kept for clarity in case we log it later.
    _ = hoje + timedelta(days=dias_ate_alvo)

    dia_semana = dia_alvo
    hora_inicio = hora_alvo.hour * 60 + hora_alvo.minute

    return lat, lon, tempo, dia_semana, hora_inicio, preset_key

class RaioDeAlcanceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request_started_at = timezone.now()
        request_timer = time.perf_counter()
        debug_metrics: Dict[str, Any] = {}

        try:
            dados = request.data
            (
                lat,
                lon,
                tempo,
                dia_semana,
                hora_inicio,
                preset_key,
            ) = _resolve_raio_params(dados)

            cache_params = {
                "tempo": tempo,
                "dia_semana": dia_semana,
                "hora_inicio": hora_inicio,
            }

            cache_hit = False
            cache_distance_m = None

            cache_result = cache_service.get_cached_response(
                latitude=lat, longitude=lon, request_params=cache_params
            )

            if cache_result is not None:
                geojson = cache_result.payload
                algo_duration_ms = 0.0
                cache_hit = True
                cache_distance_m = cache_result.distance_m
            else:
                algo_start = time.perf_counter()
                geojson = calcular_raio(
                    lat,
                    lon,
                    tempo,
                    dia_semana,
                    hora_inicio,
                    debug_callback=(lambda data: debug_metrics.update(data))
                    if settings.DEBUG
                    else None,
                )
                algo_duration_ms = (time.perf_counter() - algo_start) * 1000
                cache_service.store_response(
                    latitude=lat,
                    longitude=lon,
                    request_params=cache_params,
                    response_payload=geojson,
                    request_timestamp=request_started_at,
                )

            if settings.DEBUG:
                request_duration_ms = (time.perf_counter() - request_timer) * 1000
                metrics: Dict[str, Any] = {
                    "method": request.method,
                    "path": request.get_full_path(),
                    "lat": lat,
                    "lon": lon,
                    "tempo_min": tempo,
                    "request_started_at": request_started_at.isoformat(),
                    "request_duration_ms": round(request_duration_ms, 2),
                    "algorithm_duration_ms": round(algo_duration_ms, 2),
                    "cache_hit": cache_hit,
                }
                if cache_distance_m is not None:
                    metrics["cache_distance_m"] = round(cache_distance_m, 2)
                metrics.update(debug_metrics)
                metrics.setdefault("features_total", len(geojson.get("features", [])))
                metrics.setdefault(
                    "point_features",
                    sum(
                        1
                        for f in geojson.get("features", [])
                        if f.get("geometry", {}).get("type") == "Point"
                    ),
                )
                metrics.setdefault(
                    "polygon_features",
                    sum(
                        1
                        for f in geojson.get("features", [])
                        if f.get("geometry", {}).get("type") in {"Polygon", "MultiPolygon"}
                    ),
                )
                metrics.setdefault("walking_network_computed", False)
                metrics.setdefault("reachable_nodes", 0)
                metrics.setdefault("reachable_within_horizon", 0)
                metrics.setdefault("buffers_generated", 0)
                metrics.setdefault("stops_total", 0)
                metrics.setdefault("initial_walk_stops", 0)
                metrics.setdefault("connections_loaded", 0)
                metrics.setdefault("expanded_nodes", 0)
                metrics.setdefault("walking_relaxations", 0)
                metrics.setdefault("connection_relaxations", 0)
                metrics.setdefault("union_geometry_type", None)
                _log_debug(metrics)

            return Response(geojson)

        except (KeyError, ValueError, TypeError) as e:
            if settings.DEBUG:
                logger.exception("Invalid request payload: %s", e)
            return Response(
                {"error": f"Entrada inválida: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:  # pragma: no cover - defensive
            if settings.DEBUG:
                logger.exception("Unhandled error while processing request: %s", e)
            return Response(
                {"error": "Erro interno ao processar a solicitação."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RaioDeAlcanceStreamView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request_started_at = timezone.now()
        request_timer = time.perf_counter()
        debug_metrics: Dict[str, Any] = {}

        try:
            dados = request.data
            (
                lat,
                lon,
                tempo,
                dia_semana,
                hora_inicio,
                _preset_key,
            ) = _resolve_raio_params(dados)

            cache_params = {
                "tempo": tempo,
                "dia_semana": dia_semana,
                "hora_inicio": hora_inicio,
            }

            cache_result = cache_service.get_cached_response(
                latitude=lat, longitude=lon, request_params=cache_params
            )
            if cache_result is not None:
                payload = {
                    "cache_hit": True,
                    "payload": cache_result.payload,
                    "distance_m": cache_result.distance_m,
                }
                return Response(payload)

            sentinel = object()
            event_queue: "queue.Queue[object]" = queue.Queue()
            algo_duration_ms = 0.0

            def enqueue_event(data: Dict[str, Any]) -> None:
                event_queue.put(data)

            def run_algorithm() -> None:
                nonlocal algo_duration_ms
                close_old_connections()
                try:
                    algo_start = time.perf_counter()
                    geojson = calcular_raio(
                        lat,
                        lon,
                        tempo,
                        dia_semana,
                        hora_inicio,
                        debug_callback=(lambda data: debug_metrics.update(data))
                        if settings.DEBUG
                        else None,
                        progress_callback=enqueue_event,
                    )
                    algo_duration_ms = (time.perf_counter() - algo_start) * 1000
                    cache_service.store_response(
                        latitude=lat,
                        longitude=lon,
                        request_params=cache_params,
                        response_payload=geojson,
                        request_timestamp=request_started_at,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.exception("Unhandled error in streaming algorithm", exc_info=exc)
                    enqueue_event({"event": "error", "message": str(exc)})
                finally:
                    event_queue.put(sentinel)
                    close_old_connections()

            threading.Thread(target=run_algorithm, daemon=True).start()

            def event_stream():
                encoder = json.JSONEncoder(ensure_ascii=False)
                try:
                    while True:
                        item = event_queue.get()
                        if item is sentinel:
                            break
                        yield encoder.encode(item).encode("utf-8") + b"\n"
                finally:
                    if settings.DEBUG:
                        request_duration_ms = (time.perf_counter() - request_timer) * 1000
                        metrics: Dict[str, Any] = {
                            "method": request.method,
                            "path": request.get_full_path(),
                            "lat": lat,
                            "lon": lon,
                            "tempo_min": tempo,
                            "request_started_at": request_started_at.isoformat(),
                            "request_duration_ms": round(request_duration_ms, 2),
                            "algorithm_duration_ms": round(algo_duration_ms, 2),
                            "cache_hit": False,
                            "streaming": True,
                        }
                        metrics.update(debug_metrics)
                        _log_debug(metrics)

            response = StreamingHttpResponse(
                event_stream(), content_type="application/x-ndjson"
            )
            response["Cache-Control"] = "no-cache"
            response["X-Accel-Buffering"] = "no"
            return response

        except (KeyError, ValueError, TypeError) as e:
            if settings.DEBUG:
                logger.exception("Invalid request payload for streaming: %s", e)
            return Response(
                {"error": f"Entrada inválida: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:  # pragma: no cover - defensive
            if settings.DEBUG:
                logger.exception("Unhandled error while processing streaming request: %s", e)
            return Response(
                {"error": "Erro interno ao processar a solicitação."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RealTimeMonitorView(TemplateView):
    template_name = "transporte/real_time_monitor.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("stream_endpoint", reverse_lazy("raio-alcance-stream"))
        context.setdefault("api_endpoint", reverse_lazy("raio-alcance"))
        return context
