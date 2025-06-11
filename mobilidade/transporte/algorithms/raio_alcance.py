import heapq
from collections import defaultdict
from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt
from typing import Dict, List, Tuple

from scipy.spatial import KDTree
from django.contrib.gis.geos import Point

from transporte.models import Calendar, Stop, StopTime, Frequency

"""
calcular_raio_csa.py — Isócrona precisa usando o Connection Scan Algorithm (CSA)
--------------------------------------------------------------------------
Entrada  | Descrição
---------|---------------------------------------------------------------------
lat/lon  | Coordenadas do ponto de partida (WGS‑84)
max_min  | Horizonte de tempo em minutos (ex.: 30)
dia_sem  | Dia da semana ("monday", "tuesday", …) conforme GTFS Calendar
hora_min | Hora local de partida em minutos desde 0h00

Saída
-----
GeoJSON FeatureCollection com cada parada acessível até `max_min`,
propriedade `tempo_min` indica minutos desde a partida.
"""

# ------------------------------------------------------------
# Parâmetros globais
# ------------------------------------------------------------
CAMINHADA_MAX_METROS = 300         # Raio máximo de caminhada entre paradas
VELOCIDADE_CAMINHADA_KMH = 5       # Velocidade média a pé
BUFFER_HORIZONTE_MIN = 5           # Margem extra para pegar conexões limítrofes


# ------------------------------------------------------------
# Utilidades auxiliares
# ------------------------------------------------------------

def hhmm_para_min(t) -> int:
    """Converte datetime.time → minutos desde 0h00."""
    return t.hour * 60 + t.minute + round(t.second / 60)


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Distância Haversine entre dois pares lat/lon em metros."""
    R = 6_371_000
    φ1, φ2 = radians(lat1), radians(lat2)
    dφ = radians(lat2 - lat1)
    dλ = radians(lon2 - lon1)
    a = sin(dφ / 2) ** 2 + cos(φ1) * cos(φ2) * sin(dλ / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def tempo_caminhada(dist_m: float) -> float:
    """Distância (m) → minutos a pé."""
    return (dist_m / 1000) / VELOCIDADE_CAMINHADA_KMH * 60


# ------------------------------------------------------------
# Estruturas do CSA
# ------------------------------------------------------------
@dataclass(slots=True)
class Connection:
    dep_stop: str
    arr_stop: str
    dep_min: int
    arr_min: int


# ------------------------------------------------------------
# Construção das conexões do dia
# ------------------------------------------------------------

def _add_trip(rows: List[StopTime], conns: List[Connection], offs: Dict[str, List[int]], stps: Dict[str, List[str]]):
    trip_id = rows[0].trip_id
    offs[trip_id] = [0]
    stps[trip_id] = [rows[0].stop_id]

    for s1, s2 in zip(rows, rows[1:]):
        dep = hhmm_para_min(s1.departure_time)
        arr = hhmm_para_min(s2.arrival_time)
        conns.append(Connection(s1.stop_id, s2.stop_id, dep, arr))
        offs[trip_id].append(offs[trip_id][-1] + (arr - dep))
        stps[trip_id].append(s2.stop_id)


def _gen_headway(freq: Frequency, offs: List[int], stps: List[str], conns: List[Connection], horizon_end: int):
    head = freq.headway_secs // 60
    start = hhmm_para_min(freq.start_time)
    end = hhmm_para_min(freq.end_time)
    for k in range(0, (end - start) // head + 1):
        base_dep = start + k * head
        if base_dep > horizon_end:
            break
        for idx in range(len(stps) - 1):
            dep_seg = base_dep + offs[idx]
            arr_seg = base_dep + offs[idx + 1]
            conns.append(Connection(stps[idx], stps[idx + 1], dep_seg, arr_seg))


def carregar_conexoes(dia_semana: str, horizon_end: int) -> Tuple[List[Connection], Dict[str, List[int]]]:
    servicos = set(
        Calendar.objects.filter(**{dia_semana: True}).values_list("service_id", flat=True)
    )

    conns: List[Connection] = []
    offsets: Dict[str, List[int]] = {}
    stopseqs: Dict[str, List[str]] = {}

    # ------------ trips com horários fixos -------------
    qs = (
        StopTime.objects.filter(trip__service_id__in=servicos)
        .exclude(arrival_time__isnull=True, departure_time__isnull=True)
        .select_related("trip")
        .order_by("trip_id", "stop_sequence")
    )

    buf: List[StopTime] = []
    cur = None
    for st in qs:
        if st.trip_id != cur and buf:
            _add_trip(buf, conns, offsets, stopseqs)
            buf.clear()
        cur = st.trip_id
        buf.append(st)
    if buf:
        _add_trip(buf, conns, offsets, stopseqs)

    # ------------- trips com headway (Frequency) -------------
    for f in Frequency.objects.filter(trip_id__in=offsets):
        _gen_headway(f, offsets[f.trip_id], stopseqs[f.trip_id], conns, horizon_end)

    conns.sort(key=lambda c: c.dep_min)

    idx_by_stop: Dict[str, List[int]] = defaultdict(list)
    for i, c in enumerate(conns):
        idx_by_stop[c.dep_stop].append(i)

    return conns, idx_by_stop


# ------------------------------------------------------------
# Algoritmo principal — CSA + caminhada dinâmica
# ------------------------------------------------------------

def calcular_raio(
    lat: float,
    lon: float,
    max_minutos: int,
    dia_semana: str,
    hora_inicio_min: int,
):
    """Retorna FeatureCollection de paradas acessíveis."""

    # -------- stops + KDTree --------
    stops = {s.stop_id: s for s in Stop.objects.exclude(geom__isnull=True)}
    coords = [(s.stop_lat, s.stop_lon) for s in stops.values()]
    ids = list(stops)
    tree = KDTree(coords)
    deg_walk = CAMINHADA_MAX_METROS / 111_320

    # -------- conexões do dia --------
    horizon_abs = hora_inicio_min + max_minutos + BUFFER_HORIZONTE_MIN
    conns, idx_by_stop = carregar_conexoes(dia_semana, horizon_abs)

    # -------- earliest‑arrival --------
    INF = 10 ** 9
    eat: Dict[str, float] = defaultdict(lambda: INF)
    heap = []  # (arr_time, stop_id)

    # ponto de partida → stops caminháveis
    for i in tree.query_ball_point((lat, lon), deg_walk):
        sid = ids[i]
        d = haversine_m(lat, lon, *coords[i])
        arr = hora_inicio_min + tempo_caminhada(d)
        eat[sid] = arr
        heapq.heappush(heap, (arr, sid))

    # -------- relaxação --------
    while heap:
        t_cur, sid = heapq.heappop(heap)
        if t_cur > eat[sid] or t_cur - hora_inicio_min > max_minutos:
            continue

        # 1) Caminhadas locais
        for j in tree.query_ball_point(coords[ids.index(sid)], deg_walk):
            nsid = ids[j]
            if nsid == sid:
                continue
            twalk = tempo_caminhada(haversine_m(*coords[ids.index(sid)], *coords[j]))
            arr_nb = t_cur + twalk
            if arr_nb < eat[nsid]:
                eat[nsid] = arr_nb
                heapq.heappush(heap, (arr_nb, nsid))

        # 2) Conexões desde este stop
        for idx in idx_by_stop.get(sid, []):
            c = conns[idx]
            if c.dep_min < t_cur or c.dep_min > horizon_abs:
                continue
            if c.arr_min < eat[c.arr_stop]:
                eat[c.arr_stop] = c.arr_min
                heapq.heappush(heap, (c.arr_min, c.arr_stop))

    # -------- GeoJSON --------
    features = []
    for sid, arr in eat.items():
        delta = arr - hora_inicio_min
        if delta <= max_minutos:
            s = stops[sid]
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [s.stop_lon, s.stop_lat]},
                    "properties": {"stop_id": sid, "stop_name": s.stop_name, "tempo_min": round(delta, 1)},
                }
            )

    return {"type": "FeatureCollection", "features": features}
