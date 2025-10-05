import heapq
from collections import defaultdict
from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt
from typing import Dict, List, Optional, Tuple

from scipy.spatial import KDTree
from shapely.geometry import MultiPolygon, Point as ShpPoint, mapping
from shapely.ops import unary_union, transform as shp_transform
from pyproj import Transformer

from transporte.models import Calendar, Stop, StopTime, Frequency

"""
• CSA para encontrar o earliest‑arrival em cada parada.
• Para cada parada alcançada: cria um buffer de caminhada proporcional
  ao tempo *restante* até atingir o horizonte.
• Une (unary_union) todos os buffers, obtendo MultiPolygon que descreve
  exatamente tudo que se consegue alcançar no tempo dado, incluindo
  deslocamentos a pé depois de desembarcar.
"""

# ---------------- Configurações ----------------
CAMINHADA_MAX_METROS = 300
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


# ------------- Estrutura CSA Connection Scan Algorithm -------------
@dataclass(slots=True)
class Connection:
    dep_stop: str
    arr_stop: str
    dep_min: int
    arr_min: int


# ------------- connections -------------

def _add_trip(rows, conns, offs, stps):
    """Adiciona conexões válidas de uma viagem ordenada por stop_sequence."""

    cumulative = 0
    offsets = []
    stops = []

    for s1, s2 in zip(rows, rows[1:]):
        if not s1.departure_time or not s2.arrival_time:
            cumulative = 0
            offsets = []
            stops = []
            continue

        dep = hhmm_para_min(s1.departure_time)
        arr = hhmm_para_min(s2.arrival_time)
        if arr < dep:
            cumulative = 0
            offsets = []
            stops = []
            continue

        if not stops:
            stops.append(s1.stop_id)
            offsets.append(0)

        conns.append(Connection(s1.stop_id, s2.stop_id, dep, arr))
        cumulative += arr - dep
        offsets.append(cumulative)
        stops.append(s2.stop_id)

    if stops:
        tid = rows[0].trip_id
        offs[tid] = offsets
        stps[tid] = stops


def _gen_headway(freq, offs, stps, conns, horizon, stats):
    if (
        not freq.start_time
        or not freq.end_time
        or freq.headway_secs is None
        or freq.headway_secs <= 0
    ):
        return

    head = max(freq.headway_secs // 60, 1)
    start = hhmm_para_min(freq.start_time)
    end = hhmm_para_min(freq.end_time)
    if end < start:
        return

    expansions = 0
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
            expansions += 1
    if stats is not None:
        stats["frequency_records"] = stats.get("frequency_records", 0) + 1
        stats["frequency_connections"] = stats.get("frequency_connections", 0) + expansions


def carregar_conexoes(dia_sem, horizon, stats: Optional[Dict[str, int]] = None):
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
    fixed_segments = 0
    for st in qs.iterator():
        if st.trip_id != cur and buf:
            _add_trip(buf, conns, offs, stps)
            fixed_segments += len(buf) - 1 if len(buf) > 1 else 0
            buf.clear()
        cur = st.trip_id
        buf.append(st)
    if buf:
        _add_trip(buf, conns, offs, stps)
        fixed_segments += len(buf) - 1 if len(buf) > 1 else 0
    if offs:
        for f in Frequency.objects.filter(trip_id__in=offs).iterator():
            _gen_headway(
                f, offs[f.trip_id], stps[f.trip_id], conns, horizon, stats
            )
    if stats is not None:
        stats["fixed_connections"] = stats.get("fixed_connections", 0) + len(conns) - (
            stats.get("frequency_connections", 0)
        )
        stats["fixed_segments"] = stats.get("fixed_segments", 0) + max(fixed_segments, 0)
        stats.setdefault("frequency_records", 0)
        stats.setdefault("frequency_connections", 0)
    conns.sort(key=lambda c: c.dep_min)
    idx_by_stop = defaultdict(list)
    for i, c in enumerate(conns):
        idx_by_stop[c.dep_stop].append(i)
    return conns, idx_by_stop


# ------------- Algoritmo principal -------------

def calcular_raio(lat, lon, max_min, dia_sem, hora_ini_min, debug: bool = False):
    # Stops & spatial index
    stop_queryset = Stop.objects.filter(stop_lat__isnull=False, stop_lon__isnull=False)
    stops_list = list(stop_queryset)
    stops = {s.stop_id: s for s in stops_list}
    if not stops:
        result = {"type": "FeatureCollection", "features": []}
        if debug:
            return result, {
                "walking_network_active": False,
                "walking_network_nodes": 0,
                "connections_built": 0,
                "reachable_stops": 0,
                "feature_count": 0,
                "point_features": 0,
                "polygon_features": 0,
                "buffer_geometries": 0,
                "buffer_area_m2": 0.0,
                "initial_walkable_stops": 0,
                "frequency_connections": 0,
                "frequency_records": 0,
                "fixed_connections": 0,
                "fixed_segments": 0,
            }
        return result

    coords = [(s.stop_lat, s.stop_lon) for s in stops_list]
    ids = [s.stop_id for s in stops_list]
    index_by_stop = {sid: idx for idx, sid in enumerate(ids)}
    tree = KDTree(coords)
    deg_walk = CAMINHADA_MAX_METROS / 111_320

    # CSA connections
    horizon_abs = hora_ini_min + max_min + BUFFER_HORIZONTE_MIN
    metrics: Optional[Dict[str, int]] = {} if debug else None
    conns, idx_by_stop = carregar_conexoes(dia_sem, horizon_abs, metrics)

    eat = defaultdict(lambda: float("inf"))
    pq = []

    # Origin → paradas iniciais indo de caminhada
    initial_walkable = 0
    for i in tree.query_ball_point((lat, lon), deg_walk):
        sid = ids[i]
        arr = hora_ini_min + tempo_caminhada(haversine_m(lat, lon, *coords[i]))
        eat[sid] = arr
        heapq.heappush(pq, (arr, sid))
        initial_walkable += 1
    #Pega a parada sid com menor tempo conhecido (t_cur) para expandir.
    while pq:
        t_cur, sid = heapq.heappop(pq)
        if t_cur > eat[sid] or t_cur - hora_ini_min > max_min:
            continue
        # Caminhada local entre paradas próximas
        base_idx = index_by_stop.get(sid)
        if base_idx is None:
            continue

        for j in tree.query_ball_point(coords[base_idx], deg_walk):
            nsid = ids[j]
            if nsid == sid:
                continue
            tw = tempo_caminhada(haversine_m(*coords[base_idx], *coords[j]))
            arr_nb = t_cur + tw
            if arr_nb < eat[nsid]:
                eat[nsid] = arr_nb
                heapq.heappush(pq, (arr_nb, nsid))
        # Usar conexões de transporte
        for idx in idx_by_stop.get(sid, []):
            c = conns[idx]
            if c.dep_min < t_cur or c.dep_min > horizon_abs:
                continue
            if c.arr_min < eat[c.arr_stop]:
                eat[c.arr_stop] = c.arr_min
                heapq.heappush(pq, (c.arr_min, c.arr_stop))

    # ----------- Build walking buffers -----------
    if not eat:
        result = {"type": "FeatureCollection", "features": []}
        if debug and metrics is not None:
            metrics.update(
                {
                    "walking_network_active": True,
                    "walking_network_nodes": len(stops_list),
                    "initial_walkable_stops": initial_walkable,
                    "connections_built": len(conns),
                    "reachable_stops": 0,
                    "feature_count": 0,
                    "point_features": 0,
                    "polygon_features": 0,
                    "buffer_geometries": 0,
                    "buffer_area_m2": 0.0,
                }
            )
            return result, metrics
        return result

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
        stop = stops.get(sid)
        if not stop:
            continue
        x, y = transformer_to_m.transform(stop.stop_lon, stop.stop_lat)
        buffers.append(ShpPoint(x, y).buffer(dist_m))
    if buffers:
        area_union_m = unary_union(buffers)
    else:
        area_union_m = MultiPolygon([])

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
    reachable = 0
    for sid, arr in eat.items():
        if arr - hora_ini_min <= max_min:
            s = stops.get(sid)
            if not s:
                continue
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
            reachable += 1

    if debug and metrics is not None:
        polygon_features = len(polys)
        point_features = len(features) - polygon_features
        buffer_count = len(buffers)
        buffer_area = getattr(area_union_m, "area", 0.0)
        metrics.update(
            {
                "walking_network_active": True,
                "walking_network_nodes": len(stops_list),
                "initial_walkable_stops": initial_walkable,
                "connections_built": len(conns),
                "reachable_stops": reachable,
                "feature_count": len(features),
                "point_features": max(point_features, 0),
                "polygon_features": polygon_features,
                "buffer_geometries": buffer_count,
                "buffer_area_m2": round(buffer_area, 2),
            }
        )
        return {"type": "FeatureCollection", "features": features}, metrics

    return {"type": "FeatureCollection", "features": features}
