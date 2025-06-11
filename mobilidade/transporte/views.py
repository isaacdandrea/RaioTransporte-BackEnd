from django.shortcuts import render

# Create your views here.
# transporte/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from .algorithms.raio_alcance import calcular_raio

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from datetime import datetime
import pytz

class AlcanceAPIView(APIView):
    def get(self, request):
        lat = float(request.query_params.get('lat'))
        lon = float(request.query_params.get('lon'))
        tempo = int(request.query_params.get('tempo'))

        geojson = calcular_raio(lat, lon, tempo)
        return Response(geojson)

@csrf_exempt
def raio_de_alcance_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido'}, status=405)

    try:
        dados = json.loads(request.body)
        lat = float(dados['lat'])
        lon = float(dados['lon'])
        tempo = int(dados['tempo'])

        agora = datetime.now(pytz.timezone("America/Sao_Paulo"))
        dia_semana = agora.strftime('%A').lower()  # exemplo: 'monday'
        hora_inicio = agora.hour * 60 + agora.minute

        geojson = calcular_raio(lat, lon, tempo, dia_semana, hora_inicio)
        return JsonResponse(geojson, safe=False)

    except (KeyError, ValueError) as e:
        return JsonResponse({'error': f'Entrada inválida: {e}'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Erro interno: {e}'}, status=500)