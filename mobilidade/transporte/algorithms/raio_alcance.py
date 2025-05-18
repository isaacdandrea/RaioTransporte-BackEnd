import heapq
from datetime import datetime
from collections import defaultdict

from scipy.spatial import KDTree
from django.contrib.gis.geos import Point

from transporte.models import Calendar, Stop, StopTime, Frequency

# Configurações
CAMINHADA_MAX_METROS = 300
VELOCIDADE_CAMINHADA_KMH = 5
ESPERA_PADRAO_SEM_FREQ = 5  # minutos

def distancia_em_minutos(distancia_metros):
    return (distancia_metros / 1000) / VELOCIDADE_CAMINHADA_KMH * 60

def calcular_raio(lat, lon, tempo_limite_minutos, dia_semana, hora_inicio):
    print("🔄 Pré-carregando dados...")

    # 1️⃣ Carregar paradas com geom
    stops = {}
    stop_coords = []
    stop_ids = []

    for s in Stop.objects.exclude(geom__isnull=True):
        stops[s.stop_id] = s
        stop_coords.append((s.stop_lon, s.stop_lat))  # ordem: x=lon, y=lat
        stop_ids.append(s.stop_id)

    # Montar KDTree para caminhada
    tree = KDTree(stop_coords)

    # 2️⃣ Filtrar serviços ativos no calendário
    servicos_ativos = set(
        Calendar.objects.filter(**{dia_semana: True}).values_list('service_id', flat=True)
    )

    # 3️⃣ Carregar stoptimes válidos
    stoptimes = StopTime.objects.exclude(arrival_time__isnull=True, departure_time__isnull=True)
    stoptimes = stoptimes.filter(trip__service_id__in=servicos_ativos)
    stoptimes = [st for st in stoptimes if st.departure_time >= hora_inicio]

    # Agrupar stoptimes
    stoptimes_by_stop = defaultdict(list)
    stoptimes_by_trip = defaultdict(list)
    for st in stoptimes:
        stoptimes_by_stop[st.stop_id].append(st)
        stoptimes_by_trip[st.trip_id].append(st)
    for st_list in stoptimes_by_trip.values():
        st_list.sort(key=lambda s: s.stop_sequence)

    # 4️⃣ Frequências
    freq_by_trip = {f.trip_id: f for f in Frequency.objects.all()}

    print(f"✅ {len(stops)} paradas | {len(stoptimes)} stoptimes filtrados | {len(freq_by_trip)} frequencies")

    # 5️⃣ Parada inicial mais próxima
    ponto_inicial = (lon, lat)
    dist_km, idx = tree.query(ponto_inicial)
    parada_inicial_id = stop_ids[idx]

    visitados = {}
    fila = []
    heapq.heappush(fila, (0, parada_inicial_id))  # (tempo, stop_id)

    while fila:
        tempo_atual, stop_id = heapq.heappop(fila)

        if stop_id in visitados and visitados[stop_id] <= tempo_atual:
            continue

        visitados[stop_id] = tempo_atual
        parada = stops.get(stop_id)
        if not parada:
            continue

        # 6️⃣ Caminhada com KDTree
        ponto = (parada.stop_lon, parada.stop_lat)
        idxs = tree.query_ball_point(ponto, CAMINHADA_MAX_METROS / 100000)

        for i in idxs:
            vizinha_id = stop_ids[i]
            if vizinha_id == stop_id:
                continue
            vizinha = stops[vizinha_id]
            dist = parada.geom.distance(vizinha.geom) * 100000
            tempo_caminhada = distancia_em_minutos(dist)
            total = tempo_atual + tempo_caminhada
            if total < tempo_limite_minutos and (vizinha_id not in visitados or total < visitados[vizinha_id]):
                heapq.heappush(fila, (total, vizinha_id))

        # 7️⃣ Transporte coletivo
        for st in stoptimes_by_stop.get(stop_id, []):
            trip_id = st.trip_id
            trip_sts = stoptimes_by_trip[trip_id]
            freq = freq_by_trip.get(trip_id)
            espera = (freq.headway_secs / 60) / 2 if freq and freq.headway_secs else ESPERA_PADRAO_SEM_FREQ

            try:
                idx_atual = next(i for i, s in enumerate(trip_sts)
                                 if s.stop_id == stop_id and s.stop_sequence == st.stop_sequence)
            except StopIteration:
                continue

            saida = st.departure_time
            for prox in trip_sts[idx_atual + 1:]:
                chegada = prox.arrival_time
                if not chegada or not saida:
                    continue
                duracao = (
                    datetime.combine(datetime.today(), chegada) -
                    datetime.combine(datetime.today(), saida)
                ).total_seconds() / 60.0
                if duracao < 0:
                    continue
                total = tempo_atual + espera + duracao
                if total < tempo_limite_minutos and (prox.stop_id not in visitados or total < visitados[prox.stop_id]):
                    heapq.heappush(fila, (total, prox.stop_id))
                    saida = chegada

    # GeoJSON de retorno
    features = []
    for stop_id, tempo in visitados.items():
        stop = stops.get(stop_id)
        if not stop:
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
