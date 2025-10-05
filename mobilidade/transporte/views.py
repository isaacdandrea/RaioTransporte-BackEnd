"""Views for the transporte app."""

import json
import logging
import time
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, Tuple

import pytz
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

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
    "DEFAULT": ("thursday", dtime(18, 0)),
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


@csrf_exempt
def raio_de_alcance_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Método não permitido"}, status=405)

    request_started_at = timezone.now()
    request_timer = time.perf_counter()
    debug_metrics: Dict[str, Any] = {}

    try:
        dados = json.loads(request.body)
        lat = float(dados["lat"])
        lon = float(dados["lon"])
        tempo = int(dados["tempo"])

        tz = pytz.timezone("America/Sao_Paulo")

        preset_raw = dados.get("presetsDia")
        preset_key = (
            preset_raw.strip().upper()
            if isinstance(preset_raw, str)
            else "DEFAULT"
        )
        dia_alvo, hora_alvo = PRESET_CONFIGS.get(preset_key, PRESET_CONFIGS["DEFAULT"])

        hoje = datetime.now(tz).date()
        dia_atual_num = hoje.isoweekday()
        dia_alvo_num = WEEKDAY_NAME_TO_ISO[dia_alvo]
        dias_ate_alvo = (dia_alvo_num - dia_atual_num) % 7
        data_alvo = hoje + timedelta(days=dias_ate_alvo)

        agora = tz.localize(datetime.combine(data_alvo, hora_alvo))

        dia_semana = dia_alvo
        hora_inicio = hora_alvo.hour * 60 + hora_alvo.minute

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

        return JsonResponse(geojson, safe=False)

    except (KeyError, ValueError) as e:
        if settings.DEBUG:
            logger.exception("Invalid request payload: %s", e)
        return JsonResponse({"error": f"Entrada inválida: {e}"}, status=400)
    except Exception as e:
        if settings.DEBUG:
            logger.exception("Unhandled error while processing request: %s", e)
        return JsonResponse({"error": f"Erro interno: {e}"}, status=500)
