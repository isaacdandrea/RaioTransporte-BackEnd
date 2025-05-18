from collections import deque
from datetime import datetime, timedelta

from django.db import connections
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.contrib.gis.db.models.functions import Distance

from transporte.models import Stop, StopTime, Trip

# Configurações
CAMINHADA_MAX_METROS = 300
TEMPO_ESPERA_PADRAO = 5  # minutos
VELOCIDADE_CAMINHADA_KMH = 5

def distancia_em_minutos(distancia_metros):
    return (distancia_metros / 1000) / VELOCIDADE_CAMINHADA_KMH * 60

def calcular_raio(lat, lon, tempo_limite_minutos):
    ponto_inicial = Point(lon, lat, srid=4326)
    tempo_max = tempo_limite_minutos

    # 1️⃣ Buscar parada mais próxima usando PostGIS (banco geodados)
    parada_inicial_geom = Stop.objects.using('geodados').annotate(
        distancia=Distance('geom', ponto_inicial)
    ).order_by('distancia').first()

    if not parada_inicial_geom:
        return {"error": "Nenhuma parada encontrada próxima."}

    parada_inicial_id = parada_inicial_geom.stop_id

    # Estrutura de busca
    visitados = {}
    fila = deque()
    fila.append((parada_inicial_id, 0))  # (stop_id, tempo acumulado)

    while fila:
        stop_id_atual, tempo_atual = fila.popleft()

        if stop_id_atual in visitados and visitados[stop_id_atual] <= tempo_atual:
            continue

        visitados[stop_id_atual] = tempo_atual

        # 2️⃣ CAMINHADA — Buscar paradas próximas via PostGIS
        try:
            parada_geom_atual = Stop.objects.using('geodados').get(stop_id=stop_id_atual)
        except Stop.DoesNotExist:
            continue

        paradas_proximas = Stop.objects.using('geodados').filter(
            geom__distance_lte=(parada_geom_atual.geom, D(m=CAMINHADA_MAX_METROS))
        ).exclude(stop_id=stop_id_atual)

        for vizinha in paradas_proximas:
            dist = parada_geom_atual.geom.distance(vizinha.geom) * 100000  # metros (aproximado)
            tempo_caminhada = distancia_em_minutos(dist)
            total_tempo = tempo_atual + tempo_caminhada

            if total_tempo < tempo_max:
                fila.append((vizinha.stop_id, total_tempo))

        # 3️⃣ VIAGEM — Buscar próximas paradas via StopTimes do banco GTFS (default)
        stoptimes = StopTime.objects.using('default').filter(stop_id=stop_id_atual)

        for st in stoptimes:
            trip = st.trip
            proximos_stoptimes = StopTime.objects.using('default').filter(
                trip=trip,
                stop_sequence__gt=st.stop_sequence
            ).order_by('stop_sequence')

            tempo_saida = st.departure_time.hour * 60 + st.departure_time.minute

            for prox in proximos_stoptimes:
                tempo_chegada = prox.arrival_time.hour * 60 + prox.arrival_time.minute
                duracao_viagem = tempo_chegada - tempo_saida

                if duracao_viagem < 0:
                    continue

                total_tempo = tempo_atual + TEMPO_ESPERA_PADRAO + duracao_viagem

                if total_tempo < tempo_max:
                    fila.append((prox.stop_id, total_tempo))
                    tempo_saida = tempo_chegada
                else:
                    break

    # 4️⃣ Resultado em GeoJSON
    features = []
    for stop_id, tempo in visitados.items():
        try:
            stop = Stop.objects.using('geodados').get(stop_id=stop_id)
        except Stop.DoesNotExist:
            continue

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [stop.stop_lon, stop.stop_lat]
            },
            "properties": {
                "stop_id": stop.stop_id,
                "stop_name": stop.stop_name,
                "tempo_min": round(tempo, 1),
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features
    }
