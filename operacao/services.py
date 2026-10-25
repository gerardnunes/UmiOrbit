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

IMPORTANTE: `ChecklistItem.sistema` é CharField (texto livre),
então a planilha NÃO cria objetos Sistema. O texto da coluna
"Sistema" é copiado direto pro item.
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

    # Sistema
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
    sistema_nome: str = ""
    prioridade: str = ChecklistItem.Prioridade.MEDIA
    responsavel_username: str = ""
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
            # Não deixa a mesma coluna interna ser sobrescrita
            # (ex.: duas colunas viram 'titulo' → mantém a primeira).
            if campo not in mapa.values():
                mapa[idx] = campo
    return mapa


def _pontuar_mapa(mapa: dict[int, str]) -> int:
    """
    Dá uma pontuação pro cabeçalho candidato.
    'Título' vale muito mais que 'Sistema' ou 'Ordem'.
    """
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
def ler_excel(caminho_arquivo) -> ResultadoImport:
    resultado = ResultadoImport()

    # --- Abrir arquivo ---
    try:
        wb = openpyxl.load_workbook(
            caminho_arquivo, data_only=True, read_only=True
        )
    except Exception as exc:
        resultado.erros.append(f"Não foi possível abrir o arquivo: {exc}")
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

    # --- Achar o cabeçalho nas primeiras N linhas ---
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
        # Diagnóstico: mostra o que havia nas primeiras linhas
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

    # --- Percorrer as linhas de dados ---
    ordem_auto = 1
    for n_linha, row in enumerate(rows[melhor_idx + 1:], start=melhor_idx + 2):
        # Linha totalmente vazia → ignora
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

        # Ordem: se vazia/0, usa auto-incremento
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

    - `ChecklistItem.sistema` é CharField, então o texto da planilha
      é copiado direto. NÃO cria objetos Sistema.
    - `criar_faltantes` é mantido por compatibilidade, mas ignorado.
    - Se `autor` for passado, grava um evento CRIADO por item.
    """
    usuarios_cache = {u.username.lower(): u for u in User.objects.all()}

    criados = 0
    for linha in resultado.linhas:
        # Sistema agora é só texto — copia direto, sem criar objeto
        sistema_texto = (linha.sistema_nome or "").strip()

        responsavel = None
        if linha.responsavel_username:
            responsavel = usuarios_cache.get(linha.responsavel_username.lower())

        item = ChecklistItem.objects.create(
            checklist=checklist,
            ordem=linha.ordem,
            titulo=linha.titulo,
            descricao=linha.descricao,
            sistema=sistema_texto,
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