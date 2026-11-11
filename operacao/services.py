"""
Parser tolerante de planilhas Excel para checklist.

Recursos:
- Remove acentos e normaliza caixa nos cabeçalhos.
- Procura o cabeçalho nas primeiras N linhas (padrão: 10),
  então funciona mesmo com logo/título em cima.
- Aceita vários aliases por coluna (Título/Item/Tarefa/Atividade/Nome/etc).
- Detecta separador decimal com vírgula e datas.
- Ignora linhas vazias.
- Retorna diagnóstico legível em caso de erro.

IMPORTANTE: `ChecklistItem.sistema` é FK para `Sistema`.
Os itens importados **herdam o sistema do checklist**
(não da coluna "Sistema" da planilha). A coluna "Sistema"
da planilha é **detectada e ignorada** — serve apenas para
não confundir o parser com planilhas antigas.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

import openpyxl
from django.contrib.auth import get_user_model

from .models import ChecklistItem, ChecklistItemEvento

User = get_user_model()


# =========================================================
# ALIASES DE CABEÇALHO
# Chaves JÁ normalizadas (sem acento, minúsculas).
# =========================================================
CABECALHOS = {
    # Ordem
    "ordem": "ordem",
    "ordem.": "ordem",
    "n": "ordem",
    "nº": "ordem",
    "no": "ordem",
    "num": "ordem",
    "numero": "ordem",
    "número": "ordem",
    "item n": "ordem",
    "seq": "ordem",
    "sequencia": "ordem",

    # Título
    "titulo": "titulo",
    "título": "titulo",
    "item": "titulo",
    "itens": "titulo",
    "tarefa": "titulo",
    "atividade": "titulo",
    "verificacao": "titulo",
    "verificação": "titulo",
    "check": "titulo",
    "checagem": "titulo",
    "nome": "titulo",
    "descricao curta": "titulo",
    "title": "titulo",
    "task": "titulo",
    "name": "titulo",

    # Descrição
    "descricao": "descricao",
    "descrição": "descricao",
    "desc": "descricao",
    "detalhe": "descricao",
    "detalhes": "descricao",
    "observacao": "descricao",
    "observação": "descricao",
    "obs": "descricao",
    "comentario": "descricao",
    "comentário": "descricao",
    "description": "descricao",
    "notes": "descricao",

    # Sistema (detectado, mas IGNORADO no aplicar_import —
    # o sistema do item é sempre o sistema do checklist)
    "sistema": "sistema",
    "sistemas": "sistema",
    "equipamento": "sistema",
    "subsistema": "sistema",
    "componente": "sistema",
    "area": "sistema",
    "área": "sistema",
    "setor": "sistema",
    "system": "sistema",

    # Prioridade
    "prioridade": "prioridade",
    "prio": "prioridade",
    "prior": "prioridade",
    "urgencia": "prioridade",
    "urgência": "prioridade",
    "nivel": "prioridade",
    "nível": "prioridade",
    "priority": "prioridade",
    "level": "prioridade",

    # Responsável
    "responsavel": "responsavel",
    "responsável": "responsavel",
    "resp": "responsavel",
    "encarregado": "responsavel",
    "operador": "responsavel",
    "tecnico": "responsavel",
    "técnico": "responsavel",
    "owner": "responsavel",
    "assigned": "responsavel",
    "usuario": "responsavel",
    "usuário": "responsavel",
    "username": "responsavel",
}


# =========================================================
# PRIORIDADES
# =========================================================
PRIORIDADES = {
    "baixa": ChecklistItem.Prioridade.BAIXA,
    "baixo": ChecklistItem.Prioridade.BAIXA,
    "low": ChecklistItem.Prioridade.BAIXA,
    "1": ChecklistItem.Prioridade.BAIXA,

    "media": ChecklistItem.Prioridade.MEDIA,
    "medio": ChecklistItem.Prioridade.MEDIA,
    "normal": ChecklistItem.Prioridade.MEDIA,
    "medium": ChecklistItem.Prioridade.MEDIA,
    "2": ChecklistItem.Prioridade.MEDIA,

    "alta": ChecklistItem.Prioridade.ALTA,
    "alto": ChecklistItem.Prioridade.ALTA,
    "high": ChecklistItem.Prioridade.ALTA,
    "3": ChecklistItem.Prioridade.ALTA,

    "critica": ChecklistItem.Prioridade.CRITICA,
    "critico": ChecklistItem.Prioridade.CRITICA,
    "urgente": ChecklistItem.Prioridade.CRITICA,
    "critical": ChecklistItem.Prioridade.CRITICA,
    "4": ChecklistItem.Prioridade.CRITICA,
}

# Quantas linhas do topo procurar pelo cabeçalho
MAX_LINHAS_BUSCA_CABECALHO = 10


# =========================================================
# ESTRUTURAS
# =========================================================
@dataclass
class LinhaLida:
    ordem: int
    titulo: str
    descricao: str = ""
    prioridade: str = ChecklistItem.Prioridade.MEDIA
    responsavel_username: str = ""
    # sistema_nome é lido por compatibilidade, mas NÃO é usado
    # no aplicar_import (o sistema do item = sistema do checklist).
    sistema_nome: str = ""
    erro: str = ""


@dataclass
class ResultadoImport:
    linhas: list[LinhaLida] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)
    linha_cabecalho: int = 0
    colunas_reconhecidas: list[str] = field(default_factory=list)

    @property
    def validas(self) -> list[LinhaLida]:
        return [l for l in self.linhas if not l.erro]


# =========================================================
# HELPERS
# =========================================================
def _norm(valor) -> str:
    """Normaliza string: tira espaços, baixa caixa e remove acentos."""
    if valor is None:
        return ""
    texto = str(valor).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto


def _to_int(valor, default: int) -> int:
    if valor is None:
        return default
    try:
        return int(float(str(valor).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return default


def _localizar_cabecalho(linha: Iterable) -> dict[int, str]:
    """Retorna {indice_coluna: campo_interno} para uma linha candidata."""
    mapa: dict[int, str] = {}
    for idx, celula in enumerate(linha):
        chave = _norm(celula)
        if not chave:
            continue
        if chave in CABECALHOS:
            campo = CABECALHOS[chave]
            if campo not in mapa.values():
                mapa[idx] = campo
    return mapa


def _pontuar_mapa(mapa: dict[int, str]) -> int:
    pesos = {
        "titulo": 10,
        "descricao": 4,
        "sistema": 3,
        "prioridade": 3,
        "responsavel": 3,
        "ordem": 2,
    }
    return sum(pesos.get(c, 1) for c in mapa.values())


# =========================================================
# LEITURA
# =========================================================
def ler_excel(arquivo) -> ResultadoImport:
    resultado = ResultadoImport()

    try:
        wb = openpyxl.load_workbook(
            arquivo, data_only=True, read_only=True
        )
    except Exception as exc:
        resultado.erros.append(
            f"Não foi possível abrir o arquivo: {exc}"
        )
        return resultado

    try:
        ws = wb.active
        if ws is None:
            resultado.erros.append("Planilha vazia.")
            return resultado
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    if not rows:
        resultado.erros.append("Planilha vazia.")
        return resultado

    # Achar o cabeçalho
    melhor_mapa: dict[int, str] = {}
    melhor_idx: int = -1
    melhor_score: int = 0

    limite = min(MAX_LINHAS_BUSCA_CABECALHO, len(rows))
    for i in range(limite):
        mapa = _localizar_cabecalho(rows[i])
        if "titulo" not in mapa.values():
            continue
        score = _pontuar_mapa(mapa)
        if score > melhor_score:
            melhor_score = score
            melhor_mapa = mapa
            melhor_idx = i

    if melhor_idx == -1:
        amostra = []
        for i in range(limite):
            vistos = [str(c).strip() for c in rows[i]
                      if c is not None and str(c).strip()]
            if vistos:
                amostra.append(f"linha {i + 1}: {vistos}")
        detalhe = (
            " | ".join(amostra) if amostra
            else "(planilha vazia nas primeiras linhas)"
        )
        resultado.erros.append(
            "Cabeçalho não reconhecido nas primeiras "
            f"{limite} linhas. Preciso de uma coluna chamada 'Título' "
            "(ou Item, Tarefa, Atividade, Nome, Title). "
            f"O que encontrei — {detalhe}"
        )
        return resultado

    resultado.linha_cabecalho = melhor_idx + 1
    resultado.colunas_reconhecidas = list(melhor_mapa.values())

    # Percorrer linhas de dados
    ordem_auto = 1
    for n_linha, row in enumerate(rows[melhor_idx + 1:], start=melhor_idx + 2):
        if all(c is None or str(c).strip() == "" for c in row):
            continue

        dados: dict[str, object] = {}
        for idx, campo in melhor_mapa.items():
            if idx < len(row):
                dados[campo] = row[idx]

        titulo = str(dados.get("titulo") or "").strip()
        if not titulo:
            resultado.erros.append(f"Linha {n_linha}: sem título, ignorada.")
            continue

        ordem = _to_int(dados.get("ordem"), 0)
        if ordem <= 0:
            ordem = ordem_auto

        prio_raw = _norm(dados.get("prioridade"))
        prioridade = PRIORIDADES.get(prio_raw, ChecklistItem.Prioridade.MEDIA)

        resultado.linhas.append(
            LinhaLida(
                ordem=ordem,
                titulo=titulo,
                descricao=str(dados.get("descricao") or "").strip(),
                # sistema_nome lido por compatibilidade, mas ignorado
                sistema_nome=str(dados.get("sistema") or "").strip(),
                prioridade=prioridade,
                responsavel_username=str(dados.get("responsavel") or "").strip(),
            )
        )
        ordem_auto = max(ordem_auto, ordem) + 1

    if not resultado.linhas:
        resultado.erros.append(
            f"Cabeçalho encontrado na linha {resultado.linha_cabecalho}, "
            "mas nenhuma linha de dados válida abaixo dele."
        )

    return resultado


# =========================================================
# APLICAÇÃO NO BANCO
# =========================================================
def aplicar_import(checklist, resultado, criar_faltantes=False, autor=None):
    """
    Persiste as linhas no banco. Retorna o número de itens criados.

    - `ChecklistItem.sistema` é FK para `Sistema`. Os itens
      **herdam o sistema do checklist** (`checklist.sistema`).
      A coluna "Sistema" da planilha é ignorada.
    - `criar_faltantes` mantido por compatibilidade, mas ignorado.
    - Se `autor` for passado, grava um evento CRIADO por item.
    """
    # Se o checklist não tem sistema, avisa antes de quebrar o banco
    if checklist.sistema_id is None:
        resultado.erros.append(
            "O checklist não tem sistema definido. "
            "Escolha um sistema antes de importar."
        )
        return 0

    usuarios_cache = {u.username.lower(): u for u in User.objects.all()}
    sistema_do_checklist = checklist.sistema

    criados = 0
    for linha in resultado.linhas:
        responsavel = None
        if linha.responsavel_username:
            responsavel = usuarios_cache.get(linha.responsavel_username.lower())

        item = ChecklistItem.objects.create(
            checklist=checklist,
            ordem=linha.ordem,
            titulo=linha.titulo,
            descricao=linha.descricao,
            sistema=sistema_do_checklist,     # <-- herda do checklist
            responsavel=responsavel,
            prioridade=linha.prioridade,
        )

        ChecklistItemEvento.objects.create(
            item=item,
            tipo=ChecklistItemEvento.Tipo.CRIADO,
            autor=autor,
            texto=f"Importado da planilha (linha {linha.ordem})",
        )

        criados += 1

    return criados

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