from django.shortcuts import render

# Create your views here.
# transporte/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from .algorithms.raio_alcance import calcular_raio

class AlcanceAPIView(APIView):
    def get(self, request):
        lat = float(request.query_params.get('lat'))
        lon = float(request.query_params.get('lon'))
        tempo = int(request.query_params.get('tempo'))

        geojson = calcular_raio(lat, lon, tempo)
        return Response(geojson)
