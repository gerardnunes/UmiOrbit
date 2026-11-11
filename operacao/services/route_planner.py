"""
Planejador de rotas para missões USV.

Algoritmos suportados:
- Lawn Mower (varredura boustrophedon) dentro de um polígono.
- Waypoint navigation (conectar waypoints em ordem otimizada).

Coordenadas de entrada/saída: (lat, lon) em WGS84.
Projeção interna: equirectangular local (metros) centrada no centróide.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import transform


EARTH_RADIUS_M = 6_371_000.0
NOS_PARA_MS = 0.514444  # 1 nó = 0.514444 m/s


# =========================================================
# PROJEÇÃO LOCAL
# =========================================================
def _to_local(lon: float, lat: float, lat0: float, lon0: float) -> Tuple[float, float]:
    x = math.radians(lon - lon0) * math.cos(math.radians(lat0)) * EARTH_RADIUS_M
    y = math.radians(lat - lat0) * EARTH_RADIUS_M
    return x, y


def _from_local(x: float, y: float, lat0: float, lon0: float) -> Tuple[float, float]:
    lat = lat0 + math.degrees(y / EARTH_RADIUS_M)
    lon = lon0 + math.degrees(x / (EARTH_RADIUS_M * math.cos(math.radians(lat0))))
    return lon, lat


# =========================================================
# RESULTADO
# =========================================================
@dataclass
class RouteResult:
    waypoints: List[Tuple[float, float]]  # [(lat, lon), ...]
    distancia_total_m: float
    area_cobertura_m2: float
    tempo_estimado_min: float
    padrao: str
    avisos: List[str] = field(default_factory=list)


# =========================================================
# HELPERS
# =========================================================
def _haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _compute_length_m(points: Sequence[Tuple[float, float]]) -> float:
    total = 0.0
    for i in range(1, len(points)):
        total += _haversine_m(*points[i - 1], *points[i])
    return total


def _extract_lines(geom) -> List[LineString]:
    if geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    if hasattr(geom, "geoms"):
        return [g for g in geom.geoms if isinstance(g, LineString)]
    return []


def _polygon_from_geojson(area_geojson) -> Optional[Polygon]:
    if not area_geojson:
        return None
    geo = area_geojson
    if isinstance(geo, dict):
        if geo.get("type") == "Feature":
            geo = geo.get("geometry") or {}
        if geo.get("type") == "Polygon":
            coords = geo.get("coordinates") or []
            if not coords:
                return None
            return Polygon(coords[0])
        if geo.get("type") == "MultiPolygon":
            rings = geo.get("coordinates") or []
            if rings:
                return Polygon(rings[0][0])
    return None


# =========================================================
# LAWN MOWER
# =========================================================
def _largest_axis_angle(polygon_local: Polygon) -> float:
    mrr = polygon_local.minimum_rotated_rectangle
    if mrr is None or mrr.is_empty or mrr.geom_type != "Polygon":
        return 0.0
    coords = list(mrr.exterior.coords)[:-1]
    if len(coords) < 4:
        return 0.0
    edges = []
    for i in range(len(coords)):
        p1 = coords[i]
        p2 = coords[(i + 1) % len(coords)]
        length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        angle = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
        edges.append((length, angle))
    edges.sort(reverse=True)
    return edges[0][1]


def _gerar_lawn_mower_local(
    polygon_local: Polygon,
    espacamento_m: float,
    angulo_graus: float,
) -> List[List[Tuple[float, float]]]:
    if espacamento_m <= 0:
        raise ValueError("Espaçamento entre linhas deve ser positivo.")

    a = math.radians(angulo_graus)
    ca, sa = math.cos(a), math.sin(a)

    rotated_coords = [
        (x * ca + y * sa, -x * sa + y * ca)
        for x, y in polygon_local.exterior.coords
    ]
    rotated = Polygon(rotated_coords)
    if not rotated.is_valid:
        rotated = rotated.buffer(0)
    if rotated.is_empty:
        return []

    minx, miny, maxx, maxy = rotated.bounds
    if maxy - miny <= 0:
        return []

    segments: List[LineString] = []
    y = miny + espacamento_m / 2.0
    while y < maxy:
        line = LineString([(minx - 1.0, y), (maxx + 1.0, y)])
        inter = rotated.intersection(line)
        for seg in _extract_lines(inter):
            if seg.length > 1.0:
                segments.append(seg)
        y += espacamento_m

    if not segments:
        return []

    segments.sort(key=lambda s: (round(s.centroid.y, 6), s.centroid.x))

    ordered: List[List[Tuple[float, float]]] = []
    for i, seg in enumerate(segments):
        coords = list(seg.coords)
        if i % 2 == 1:
            coords = coords[::-1]
        ordered.append(coords)

    return ordered


def gerar_rota_lawn_mower(
    area_geojson,
    espacamento_m: float,
    angulo_graus: float = 0.0,
    velocidade_nos: float = 3.0,
) -> RouteResult:
    polygon_lonlat = _polygon_from_geojson(area_geojson)
    if polygon_lonlat is None or polygon_lonlat.is_empty:
        raise ValueError("Área de operação inválida ou vazia.")

    c = polygon_lonlat.centroid
    lat0, lon0 = c.y, c.x

    def _forward(lon, lat, z=None):
        return _to_local(lon, lat, lat0, lon0)

    polygon_local = transform(_forward, polygon_lonlat)
    if not polygon_local.is_valid:
        polygon_local = polygon_local.buffer(0)

    if abs(angulo_graus) < 1e-6:
        angulo_graus = _largest_axis_angle(polygon_local)

    segmentos_local = _gerar_lawn_mower_local(
        polygon_local, espacamento_m, angulo_graus,
    )
    if not segmentos_local:
        raise ValueError("Não foi possível gerar linhas com esse espaçamento.")

    all_local: List[Tuple[float, float]] = []
    for seg in segmentos_local:
        all_local.extend(seg)

    a = math.radians(angulo_graus)
    ca, sa = math.cos(a), math.sin(a)
    unrotated = [(x * ca - y * sa, x * sa + y * ca) for x, y in all_local]

    def _backward(x, y, z=None):
        return _from_local(x, y, lat0, lon0)

    line_lonlat = [_backward(x, y) for x, y in unrotated]
    waypoints_latlon = [(lat, lon) for lon, lat in line_lonlat]

    distancia_m = _compute_length_m(waypoints_latlon)
    area_m2 = polygon_local.area
    speed_ms = velocidade_nos * NOS_PARA_MS
    tempo_min = (distancia_m / speed_ms / 60.0) if speed_ms > 0 else 0.0

    avisos: List[str] = []
    if len(waypoints_latlon) < 2:
        avisos.append("Rota com menos de 2 pontos.")
    if espacamento_m > 500:
        avisos.append(
            "Espaçamento entre linhas acima de 500 m — confira a cobertura."
        )

    return RouteResult(
        waypoints=waypoints_latlon,
        distancia_total_m=distancia_m,
        area_cobertura_m2=area_m2,
        tempo_estimado_min=tempo_min,
        padrao="LAWN_MOWER",
        avisos=avisos,
    )


# =========================================================
# WAYPOINTS
# =========================================================
def gerar_rota_waypoints(
    waypoints_latlon: Sequence[Tuple[float, float]],
    velocidade_nos: float = 3.0,
    fechar_ciclo: bool = False,
) -> RouteResult:
    pts = list(waypoints_latlon)
    if fechar_ciclo and len(pts) > 2:
        pts.append(pts[0])
    if len(pts) < 2:
        return RouteResult(
            waypoints=pts,
            distancia_total_m=0.0,
            area_cobertura_m2=0.0,
            tempo_estimado_min=0.0,
            padrao="WAYPOINTS",
            avisos=["São necessários pelo menos 2 waypoints."],
        )

    distancia_m = _compute_length_m(pts)
    speed_ms = velocidade_nos * NOS_PARA_MS
    tempo_min = (distancia_m / speed_ms / 60.0) if speed_ms > 0 else 0.0

    return RouteResult(
        waypoints=pts,
        distancia_total_m=distancia_m,
        area_cobertura_m2=0.0,
        tempo_estimado_min=tempo_min,
        padrao="WAYPOINTS",
    )


def otimizar_waypoints_nearest_neighbor(
    waypoints_latlon: Sequence[Tuple[float, float]],
    inicio: Optional[Tuple[float, float]] = None,
    fim: Optional[Tuple[float, float]] = None,
) -> List[Tuple[float, float]]:
    """Heurística nearest-neighbor. Obstáculos ficam para a próxima etapa."""
    pendentes = list(waypoints_latlon)
    if not pendentes:
        return []

    ordem: List[Tuple[float, float]] = []
    if inicio is not None:
        atual = inicio
        ordem.append(inicio)
    else:
        atual = pendentes.pop(0)
        ordem.append(atual)

    while pendentes:
        proximo = min(pendentes, key=lambda p: _haversine_m(*atual, *p))
        pendentes.remove(proximo)
        ordem.append(proximo)
        atual = proximo

    if fim is not None and (not ordem or ordem[-1] != fim):
        ordem.append(fim)

    return ordem

# =========================================================
# PREVIEW A PARTIR DO POLÍGONO
# =========================================================
def analisar_area(area_geojson) -> dict:
    """
    Dado o GeoJSON do polígono, retorna:
    - centroide (lat, lon)
    - angulo_ideal_graus (eixo maior do minimum_rotated_rectangle)
    - area_m2
    - bbox_m (largura, altura em metros)
    - espacamento_sugerido_m
    - partida/chegada sugeridas (extremos do eixo maior)
    """
    import math as _m

    polygon = _polygon_from_geojson(area_geojson)
    if polygon is None or polygon.is_empty:
        raise ValueError("Área inválida.")

    c = polygon.centroid
    lat0, lon0 = c.y, c.x

    def _forward(lon, lat, z=None):
        return _to_local(lon, lat, lat0, lon0)

    poly_local = transform(_forward, polygon)
    if not poly_local.is_valid:
        poly_local = poly_local.buffer(0)

    area_m2 = poly_local.area
    minx, miny, maxx, maxy = poly_local.bounds
    largura_m = maxx - minx
    altura_m = maxy - miny

    # Ângulo do eixo maior
    angulo = _largest_axis_angle(poly_local)

    # Pontas do eixo maior (aproximação via bounding box rotacionada)
    a = _m.radians(angulo)
    ca, sa = _m.cos(a), _m.sin(a)
    coords_rot = [
        (x * ca + y * sa, -x * sa + y * ca)
        for x, y in poly_local.exterior.coords
    ]
    xs = [p[0] for p in coords_rot]
    ys = [p[1] for p in coords_rot]
    comprimento_eixo = max(xs) - min(xs) if (max(xs) - min(xs)) > (max(ys) - min(ys)) else max(ys) - min(ys)

    # Converte de volta
    def _backward(x, y, z=None):
        return _from_local(x, y, lat0, lon0)

    # Partida/chegada: extremos do retângulo rotacionado no eixo maior
    if (max(xs) - min(xs)) >= (max(ys) - min(ys)):
        p1_local = (min(xs), (min(ys) + max(ys)) / 2)
        p2_local = (max(xs), (min(ys) + max(ys)) / 2)
    else:
        p1_local = ((min(xs) + max(xs)) / 2, min(ys))
        p2_local = ((min(xs) + max(xs)) / 2, max(ys))

    # Desrotaciona
    def _desrot(xr, yr):
        return (xr * ca - yr * sa, xr * sa + yr * ca)

    p1 = _desrot(*p1_local)
    p2 = _desrot(*p2_local)
    lon1, lat1 = _backward(*p1)
    lon2, lat2 = _backward(*p2)

    # Espaçamento sugerido: ~1/20 da menor dimensão, mínimo 25m, máximo 200m
    menor_dimensao = min(largura_m, altura_m) or 100
    espac_sugerido = max(25.0, min(200.0, round(menor_dimensao / 20.0)))

    return {
        "centroide": {"lat": lat0, "lon": lon0},
        "angulo_ideal_graus": round(angulo, 1),
        "area_m2": round(area_m2, 1),
        "largura_m": round(largura_m, 1),
        "altura_m": round(altura_m, 1),
        "comprimento_eixo_m": round(comprimento_eixo, 1),
        "espacamento_sugerido_m": espac_sugerido,
        "partida": {"lat": lat1, "lon": lon1},
        "chegada": {"lat": lat2, "lon": lon2},
    }