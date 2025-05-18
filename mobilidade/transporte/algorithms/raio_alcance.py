from django.db import connections
from datetime import datetime, timedelta
from transporte.models import Stop, StopTime, Trip
from collections import deque
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.contrib.gis.db.models.functions import Distance

# Limite para caminhada entre paradas (em metros)
CAMINHADA_MAX_METROS = 300

# Tempo médio de espera em parada (pode ser calibrado melhor)
TEMPO_ESPERA_PADRAO = 5  # minutos
VELOCIDADE_CAMINHADA = 5  # km/h

def distancia_em_minutos(distancia_metros):
    return (distancia_metros / 1000) / VELOCIDADE_CAMINHADA * 60

def calcular_raio(lat, lon, tempo_limite_minutos):
    ponto_inicial = Point(lon, lat, srid=4326)
    tempo_max = tempo_limite_minutos

    # Encontrar parada mais próxima do ponto inicial
    parada_inicial = Stop.objects.annotate(
        distancia=Distance("geom", ponto_inicial)
    ).order_by("distancia").first()

    if not parada_inicial:
        return {"error": "Nenhuma parada encontrada próxima."}

    visitados = {}
    fila = deque()
    fila.append((parada_inicial, 0))  # (parada, tempo_acumulado)

    while fila:
        parada_atual, tempo_atual = fila.popleft()

        if parada_atual.stop_id in visitados and visitados[parada_atual.stop_id] <= tempo_atual:
            continue

        visitados[parada_atual.stop_id] = tempo_atual

        # CAMINHADA → encontrar outras paradas próximas via PostGIS
        paradas_proximas = Stop.objects.using('geodados').filter(
            geom__distance_lte=(parada_atual.geom, D(m=CAMINHADA_MAX_METROS))
        ).exclude(stop_id=parada_atual.stop_id)

        for vizinha in paradas_proximas:
            dist = parada_atual.geom.distance(vizinha.geom) * 100000  # metros (aproximado)
            tempo_caminhada = distancia_em_minutos(dist)
            total_tempo = tempo_atual + tempo_caminhada

            if total_tempo < tempo_max:
                fila.append((vizinha, total_tempo))

        # VIAGENS dessa parada
        stoptimes = StopTime.objects.filter(stop=parada_atual)

        for st in stoptimes:
            trip = st.trip
            proximos_stoptimes = StopTime.objects.filter(
                trip=trip,
                stop_sequence__gt=st.stop_sequence
            ).order_by('stop_sequence')

            tempo_saida = st.departure_time.hour * 60 + st.departure_time.minute

            for prox in proximos_stoptimes:
                tempo_chegada = prox.arrival_time.hour * 60 + prox.arrival_time.minute
                duracao_viagem = tempo_chegada - tempo_saida

                if duracao_viagem < 0:
                    continue  # ignora viagens quebradas

                total_tempo = tempo_atual + TEMPO_ESPERA_PADRAO + duracao_viagem

                if total_tempo < tempo_max:
                    fila.append((prox.stop, total_tempo))
                    tempo_saida = tempo_chegada
                else:
                    break

    # Montar GeoJSON dos stops acessíveis
    features = []
    for stop_id, tempo in visitados.items():
        stop = Stop.objects.get(stop_id=stop_id)
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
