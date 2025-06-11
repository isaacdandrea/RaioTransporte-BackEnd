from django.shortcuts import render

# Create your views here.
# transporte/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from .algorithms.calcular_raio_csa import calcular_raio


from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from datetime import datetime, timedelta, time
import pytz

@csrf_exempt
def raio_de_alcance_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido'}, status=405)

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

        geojson = calcular_raio(lat, lon, tempo, dia_semana, hora_inicio)
        return JsonResponse(geojson, safe=False)

    except (KeyError, ValueError) as e:
        return JsonResponse({'error': f'Entrada inválida: {e}'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Erro interno: {e}'}, status=500)