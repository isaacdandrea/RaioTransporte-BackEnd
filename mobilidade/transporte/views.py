"""Views for the transporte app."""

import json
import logging
import time
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict

import pytz
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .algorithms.calcular_raio_csa import calcular_raio

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

        hoje = datetime.now(tz).date()
        dias_ate_quinta = (3 - hoje.weekday()) % 7
        data_quinta = hoje + timedelta(days=dias_ate_quinta)

        agora = tz.localize(datetime.combine(data_quinta, dtime(18, 0)))

        dia_semana = agora.strftime("%A").lower()
        hora_inicio = 18 * 60

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
            }
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
