import json
import logging
from datetime import datetime, timedelta, time
from time import perf_counter

import pytz
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .algorithms.calcular_raio_csa import calcular_raio


logger = logging.getLogger(__name__)


@csrf_exempt
def raio_de_alcance_view(request):
    if request.method != 'POST':
        if settings.DEBUG:
            logger.info(
                "Reachability request rejected due to unsupported method: %s",
                request.method,
            )
        return JsonResponse({'error': 'Método não permitido'}, status=405)

    request_started = timezone.now()
    perf_started = perf_counter()

    try:
        dados = json.loads(request.body)
        lat = float(dados['lat'])
        lon = float(dados['lon'])
        tempo = int(dados['tempo'])

        tz = pytz.timezone("America/Sao_Paulo")

        # 1. Descobre a próxima (ou a própria) quinta-feira
        hoje = datetime.now(tz).date()
        # weekday(): segunda=0 … domingo=6  ⇒  quinta=3
        dias_ate_quinta = (3 - hoje.weekday()) % 7
        data_quinta = hoje + timedelta(days=dias_ate_quinta)

        # 2. Constrói o instante exato da quinta-feira às 18h00
        agora = tz.localize(datetime.combine(data_quinta, time(18, 0)))

        # 3. Dia da semana e hora de início em minutos
        dia_semana = agora.strftime("%A").lower()  # sempre 'thursday'
        hora_inicio = 18 * 60  # 1080

        debug_mode = settings.DEBUG
        if debug_mode:
            geojson, metrics = calcular_raio(
                lat, lon, tempo, dia_semana, hora_inicio, debug=True
            )
        else:
            geojson = calcular_raio(lat, lon, tempo, dia_semana, hora_inicio)
            metrics = None

        duration = perf_counter() - perf_started

        if debug_mode:
            metrics = metrics or {}
            metrics.update(
                {
                    "request_started": request_started.isoformat(),
                    "duration_seconds": round(duration, 4),
                    "latitude": lat,
                    "longitude": lon,
                    "tempo_min": tempo,
                    "hora_inicio_min": hora_inicio,
                    "dia_semana": dia_semana,
                }
            )
            metrics["walking_network_active"] = bool(metrics.get("walking_network_nodes"))
            metrics["has_frequency_data"] = metrics.get("frequency_records", 0) > 0
            logger.info("Reachability request metrics: %s", metrics)

        return JsonResponse(geojson, safe=False)

    except (KeyError, ValueError) as e:
        if settings.DEBUG:
            logger.exception("Invalid parameters for reachability request")
        return JsonResponse({'error': f'Entrada inválida: {e}'}, status=400)
    except Exception as e:
        if settings.DEBUG:
            logger.exception("Unexpected error while computing reachability")
        return JsonResponse({'error': f'Erro interno: {e}'}, status=500)
