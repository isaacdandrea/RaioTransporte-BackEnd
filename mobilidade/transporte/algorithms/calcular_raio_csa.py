import heapq
from collections import defaultdict
from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt
from typing import Callable, Dict, List, Optional, Tuple

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
CAMINHADA_MAX_METROS = 1000
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


def _gen_headway(freq, offs, stps, conns, horizon):
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
    for st in qs.iterator():
        if st.trip_id != cur and buf:
            _add_trip(buf, conns, offs, stps)
            buf.clear()
        cur = st.trip_id
        buf.append(st)
    if buf:
        _add_trip(buf, conns, offs, stps)
    if offs:
        for f in Frequency.objects.filter(trip_id__in=offs).iterator():
            _gen_headway(f, offs[f.trip_id], stps[f.trip_id], conns, horizon)
    conns.sort(key=lambda c: c.dep_min)
    idx_by_stop = defaultdict(list)
    for i, c in enumerate(conns):
        idx_by_stop[c.dep_stop].append(i)
    return conns, idx_by_stop


# ------------- Algoritmo principal -------------

def calcular_raio(
    lat,
    lon,
    max_min,
    dia_sem,
    hora_ini_min,
    debug_callback: Optional[Callable[[Dict[str, object]], None]] = None,
):
    debug_data: Optional[Dict[str, object]] = {} if debug_callback else None
    # Stops & spatial index
    stop_queryset = Stop.objects.filter(stop_lat__isnull=False, stop_lon__isnull=False)
    stops_list = list(stop_queryset)
    stops = {s.stop_id: s for s in stops_list}
    if debug_data is not None:
        debug_data.update({
            "stops_total": len(stops_list),
        })
    if not stops:
        if debug_data is not None:
            debug_data.update(
                {
                    "walking_network_computed": False,
                    "reachable_nodes": 0,
                    "buffers_generated": 0,
                    "features_total": 0,
                    "point_features": 0,
                    "polygon_features": 0,
                }
            )
            debug_callback(debug_data)
        return {"type": "FeatureCollection", "features": []}

    coords = [(s.stop_lat, s.stop_lon) for s in stops_list]
    ids = [s.stop_id for s in stops_list]
    index_by_stop = {sid: idx for idx, sid in enumerate(ids)}
    tree = KDTree(coords)
    deg_walk = CAMINHADA_MAX_METROS / 111_320

    # CSA connections
    horizon_abs = hora_ini_min + max_min + BUFFER_HORIZONTE_MIN
    conns, idx_by_stop = carregar_conexoes(dia_sem, horizon_abs)

    eat = defaultdict(lambda: float("inf"))
    pq = []

    # Origin → paradas iniciais indo de caminhada
    initial_walk_stops = tree.query_ball_point((lat, lon), deg_walk)
    if debug_data is not None:
        debug_data["initial_walk_stops"] = len(initial_walk_stops)

    for i in initial_walk_stops:
        sid = ids[i]
        arr = hora_ini_min + tempo_caminhada(haversine_m(lat, lon, *coords[i]))
        eat[sid] = arr
        heapq.heappush(pq, (arr, sid))
    #Pega a parada sid com menor tempo conhecido (t_cur) para expandir.
    expanded_nodes = 0
    walking_relaxations = 0
    connection_relaxations = 0
    while pq:
        t_cur, sid = heapq.heappop(pq)
        if t_cur > eat[sid] or t_cur - hora_ini_min > max_min:
            continue
        expanded_nodes += 1
        # Caminhada local entre paradas próximas
        base_idx = index_by_stop.get(sid)
        if base_idx is None:
            continue

        neighbors = tree.query_ball_point(coords[base_idx], deg_walk)
        walking_relaxations += max(len(neighbors) - 1, 0)
        for j in neighbors:
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
            connection_relaxations += 1
            c = conns[idx]
            if c.dep_min < t_cur or c.dep_min > horizon_abs:
                continue
            if c.arr_min < eat[c.arr_stop]:
                eat[c.arr_stop] = c.arr_min
                heapq.heappush(pq, (c.arr_min, c.arr_stop))

    # ----------- Build walking buffers -----------
    if debug_data is not None:
        debug_data.update(
            {
                "connections_loaded": len(conns),
                "index_stops": len(idx_by_stop),
                "expanded_nodes": expanded_nodes,
                "walking_relaxations": walking_relaxations,
                "connection_relaxations": connection_relaxations,
            }
        )

    if not eat:
        if debug_data is not None:
            debug_data.update(
                {
                    "walking_network_computed": False,
                    "reachable_nodes": 0,
                    "buffers_generated": 0,
                    "features_total": 0,
                    "point_features": 0,
                    "polygon_features": 0,
                }
            )
            debug_callback(debug_data)
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
        stop = stops.get(sid)
        if not stop:
            continue
        x, y = transformer_to_m.transform(stop.stop_lon, stop.stop_lat)
        buffers.append(ShpPoint(x, y).buffer(dist_m))

    area_union_m = unary_union(buffers) if buffers else None

    # Transforma de volta para WGS‑84
    def to_deg(x, y, z=None):
        return transformer_to_deg.transform(x, y)

    area_union_deg = shp_transform(to_deg, area_union_m) if area_union_m else None

    # Decompõe MultiPolygons separados → features distintas
    polys = []
    if area_union_deg is not None:
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
    reachable_within_horizon = 0
    for sid, arr in eat.items():
        if arr - hora_ini_min <= max_min:
            reachable_within_horizon += 1
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

    if debug_data is not None:
        point_features = sum(
            1
            for f in features
            if f.get("geometry", {}).get("type") == "Point"
        )
        polygon_features = sum(
            1
            for f in features
            if f.get("geometry", {}).get("type") in {"Polygon", "MultiPolygon"}
        )
        debug_data.update(
            {
                "walking_network_computed": True,
                "reachable_nodes": len(eat),
                "reachable_within_horizon": reachable_within_horizon,
                "buffers_generated": len(buffers),
                "features_total": len(features),
                "point_features": point_features,
                "polygon_features": polygon_features,
                "union_geometry_type": area_union_deg.geom_type if area_union_deg else None,
            }
        )
        debug_callback(debug_data)

    return {"type": "FeatureCollection", "features": features}
