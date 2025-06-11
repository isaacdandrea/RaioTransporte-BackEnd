import heapq
from collections import defaultdict
from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt
from typing import Dict, List, Tuple

from scipy.spatial import KDTree
from shapely.geometry import MultiPolygon, Point as ShpPoint, mapping
from shapely.ops import unary_union, transform as shp_transform
from pyproj import Transformer

from transporte.models import Calendar, Stop, StopTime, Frequency

"""
calcular_raio_csa.py — Isócrona precisa com polígonos residuais de caminhada
-----------------------------------------------------------------------------
• CSA para encontrar o earliest‑arrival em cada parada.
• Para cada parada alcançada: cria um buffer de caminhada proporcional
  ao tempo *restante* até atingir o horizonte.
• Une (unary_union) todos os buffers, obtendo MultiPolygon que descreve
  exatamente tudo que se consegue alcançar no tempo dado, incluindo
  deslocamentos a pé depois de desembarcar.
"""

# ---------------- Configurações ----------------
CAMINHADA_MAX_METROS = 300  # raio para ligações entre paradas
VELOCIDADE_CAMINHADA_KMH = 5
BUFFER_HORIZONTE_MIN = 5

# ------------- Funções auxiliares -------------

def hhmm_para_min(t):
    return t.hour * 60 + t.minute + round(t.second / 60)


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    φ1, φ2 = radians(lat1), radians(lat2)
    dφ = radians(lat2 - lat1)
    dλ = radians(lon2 - lon1)
    a = sin(dφ / 2) ** 2 + cos(φ1) * cos(φ2) * sin(dλ / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def tempo_caminhada(d_m):
    return (d_m / 1000) / VELOCIDADE_CAMINHADA_KMH * 60


# ------------- Estrutura CSA -------------
@dataclass(slots=True)
class Connection:
    dep_stop: str
    arr_stop: str
    dep_min: int
    arr_min: int


# ------------- Build connections -------------

def _add_trip(rows, conns, offs, stps):
    tid = rows[0].trip_id
    offs[tid] = [0]
    stps[tid] = [rows[0].stop_id]
    for s1, s2 in zip(rows, rows[1:]):
        dep = hhmm_para_min(s1.departure_time)
        arr = hhmm_para_min(s2.arrival_time)
        conns.append(Connection(s1.stop_id, s2.stop_id, dep, arr))
        offs[tid].append(offs[tid][-1] + (arr - dep))
        stps[tid].append(s2.stop_id)


def _gen_headway(freq, offs, stps, conns, horizon):
    head = freq.headway_secs // 60
    start = hhmm_para_min(freq.start_time)
    end = hhmm_para_min(freq.end_time)
    for k in range(0, (end - start) // head + 1):
        base = start + k * head
        if base > horizon:
            break
        for i in range(len(stps) - 1):
            conns.append(
                Connection(
                    stps[i], stps[i + 1], base + offs[i], base + offs[i + 1]
                )
            )


def carregar_conexoes(dia_sem, horizon):
    servs = set(
        Calendar.objects.filter(**{dia_sem: True}).values_list("service_id", flat=True)
    )
    conns, offs, stps = [], {}, {}
    qs = (
        StopTime.objects.filter(trip__service_id__in=servs)
        .exclude(arrival_time__isnull=True, departure_time__isnull=True)
        .select_related("trip")
        .order_by("trip_id", "stop_sequence")
    )
    buf, cur = [], None
    for st in qs:
        if st.trip_id != cur and buf:
            _add_trip(buf, conns, offs, stps)
            buf.clear()
        cur = st.trip_id
        buf.append(st)
    if buf:
        _add_trip(buf, conns, offs, stps)
    for f in Frequency.objects.filter(trip_id__in=offs):
        _gen_headway(f, offs[f.trip_id], stps[f.trip_id], conns, horizon)
    conns.sort(key=lambda c: c.dep_min)
    idx_by_stop = defaultdict(list)
    for i, c in enumerate(conns):
        idx_by_stop[c.dep_stop].append(i)
    return conns, idx_by_stop


# ------------- Algoritmo principal -------------

def calcular_raio(lat, lon, max_min, dia_sem, hora_ini_min):
    # Stops & spatial index
    stops = {s.stop_id: s for s in Stop.objects.exclude(geom__isnull=True)}
    coords = [(s.stop_lat, s.stop_lon) for s in stops.values()]
    ids = list(stops)
    tree = KDTree(coords)
    deg_walk = CAMINHADA_MAX_METROS / 111_320

    # CSA connections
    horizon_abs = hora_ini_min + max_min + BUFFER_HORIZONTE_MIN
    conns, idx_by_stop = carregar_conexoes(dia_sem, horizon_abs)

    eat = defaultdict(lambda: float("inf"))
    pq = []

    # Origin → reachable stops by walking
    for i in tree.query_ball_point((lat, lon), deg_walk):
        sid = ids[i]
        arr = hora_ini_min + tempo_caminhada(haversine_m(lat, lon, *coords[i]))
        eat[sid] = arr
        heapq.heappush(pq, (arr, sid))

    while pq:
        t_cur, sid = heapq.heappop(pq)
        if t_cur > eat[sid] or t_cur - hora_ini_min > max_min:
            continue
        # Local walks
        base_idx = ids.index(sid)
        for j in tree.query_ball_point(coords[base_idx], deg_walk):
            nsid = ids[j]
            if nsid == sid:
                continue
            tw = tempo_caminhada(haversine_m(*coords[base_idx], *coords[j]))
            arr_nb = t_cur + tw
            if arr_nb < eat[nsid]:
                eat[nsid] = arr_nb
                heapq.heappush(pq, (arr_nb, nsid))
        # Transit connections
        for idx in idx_by_stop.get(sid, []):
            c = conns[idx]
            if c.dep_min < t_cur or c.dep_min > horizon_abs:
                continue
            if c.arr_min < eat[c.arr_stop]:
                eat[c.arr_stop] = c.arr_min
                heapq.heappush(pq, (c.arr_min, c.arr_stop))

    # ----------- Build walking buffers -----------
    if not eat:
        return {"type": "FeatureCollection", "features": []}

    transformer_to_m = Transformer.from_crs("epsg:4326", "epsg:3857", always_xy=True)
    transformer_to_deg = Transformer.from_crs("epsg:3857", "epsg:4326", always_xy=True)

    buffers = []
    for sid, arr in eat.items():
        delta = arr - hora_ini_min
        if delta > max_min:
            continue
        # tempo restante para caminhar a partir desta parada
        restante = max_min - delta
        dist_m = restante * VELOCIDADE_CAMINHADA_KMH * 1000 / 60
        if dist_m < 10:  # ignora buffers minúsculos
            dist_m = 10
        x, y = transformer_to_m.transform(stops[sid].stop_lon, stops[sid].stop_lat)
        buffers.append(ShpPoint(x, y).buffer(dist_m))

    area_union_m = unary_union(buffers)

    # Transforma de volta para WGS‑84
    def to_deg(x, y, z=None):
        return transformer_to_deg.transform(x, y)

    area_union_deg = shp_transform(to_deg, area_union_m)

    # Decompõe MultiPolygons separados → features distintas
    polys = []
    if area_union_deg.geom_type == "Polygon":
        polys = [area_union_deg]
    elif area_union_deg.geom_type == "MultiPolygon":
        polys = list(area_union_deg.geoms)

    features = [
        {
            "type": "Feature",
            "geometry": mapping(p),
            "properties": {"tipo": "isocrona", "tempo_min": max_min},
        }
        for p in polys
    ]

    # Pontos opcionais para debug/visualização
    for sid, arr in eat.items():
        if arr - hora_ini_min <= max_min:
            s = stops[sid]
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [s.stop_lon, s.stop_lat]},
                    "properties": {
                        "stop_id": sid,
                        "stop_name": s.stop_name,
                        "tempo_min": round(arr - hora_ini_min, 1),
                    },
                }
            )

    return {"type": "FeatureCollection", "features": features}
