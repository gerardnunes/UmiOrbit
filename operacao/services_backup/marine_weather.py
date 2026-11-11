"""
Cliente para condições meteorológicas e oceanográficas em tempo real.

Fontes:
- Open-Meteo Marine API: ondas, correntes, temperatura da superfície.
- Open-Meteo Forecast API: vento e rajadas.

AVISO: dados de modelo global. Não substitui boletim oficial da Marinha (PAM/CHM)
nem CPTEC/INPE. Correntes e marés têm resolução de ~8 km e precisão limitada
em áreas costeiras [citation:1].
"""
from __future__ import annotations

import requests
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 8


@dataclass
class MarineConditions:
    lat: float
    lon: float
    fetched_at: str = ""
    # Ondas
    wave_height_m: Optional[float] = None
    wave_period_s: Optional[float] = None
    wave_direction_deg: Optional[float] = None
    swell_height_m: Optional[float] = None
    # Correntes
    current_speed_kmh: Optional[float] = None
    current_direction_deg: Optional[float] = None
    # Temperatura
    sea_surface_temp_c: Optional[float] = None
    # Vento (da Forecast API)
    wind_speed_kmh: Optional[float] = None
    wind_gust_kmh: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    # Série horária (próximas 24h) para análise de janela
    hourly: list[dict] = field(default_factory=list)
    # Metadados
    fonte: str = "Open-Meteo"
    aviso: str = (
        "Dados de modelo global. Não substitui boletim oficial da Marinha "
        "(PAM/CHM) nem CPTEC/INPE. Use como triagem, confirme antes de aprovar."
    )
    erro: str = ""


def _classificar_onda(altura_m: Optional[float]) -> tuple[str, str]:
    """Retorna (nivel, cor) para semáforo."""
    if altura_m is None:
        return ("indisponivel", "cinza")
    if altura_m < 0.5:
        return ("calmo", "verde")
    if altura_m < 1.0:
        return ("moderado", "amarelo")
    if altura_m < 1.8:
        return ("alto", "laranja")
    return ("critico", "vermelho")


def _classificar_vento(kmh: Optional[float]) -> tuple[str, str]:
    if kmh is None:
        return ("indisponivel", "cinza")
    if kmh < 20:
        return ("calmo", "verde")
    if kmh < 35:
        return ("moderado", "amarelo")
    if kmh < 50:
        return ("alto", "laranja")
    return ("critico", "vermelho")


def _classificar_corrente(kmh: Optional[float]) -> tuple[str, str]:
    if kmh is None:
        return ("indisponivel", "cinza")
    if kmh < 1.0:
        return ("fraca", "verde")
    if kmh < 2.0:
        return ("moderada", "amarelo")
    if kmh < 3.5:
        return ("forte", "laranja")
    return ("muito_forte", "vermelho")


def fetch_marine_conditions(lat: float, lon: float) -> MarineConditions:
    """
    Busca condições atuais + série horária curta para um ponto.
    Faz duas chamadas: Marine (ondas/correntes) e Forecast (vento).
    """
    cond = MarineConditions(lat=lat, lon=lon)
    cond.fetched_at = datetime.now(timezone.utc).isoformat()

    # ---- Marine API ----
    try:
        params_marine = {
            "latitude": lat,
            "longitude": lon,
            "current": [
                "wave_height", "wave_period", "wave_direction",
                "swell_wave_height",
                "ocean_current_velocity", "ocean_current_direction",
                "sea_surface_temperature",
            ],
            "hourly": [
                "wave_height", "wave_period", "wave_direction",
                "ocean_current_velocity", "ocean_current_direction",
            ],
            "forecast_days": 2,
            "timezone": "auto",
        }
        r = requests.get(MARINE_URL, params=params_marine, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()

        cur = data.get("current", {})
        cond.wave_height_m = cur.get("wave_height")
        cond.wave_period_s = cur.get("wave_period")
        cond.wave_direction_deg = cur.get("wave_direction")
        cond.swell_height_m = cur.get("swell_wave_height")
        cond.current_speed_kmh = cur.get("ocean_current_velocity")
        cond.current_direction_deg = cur.get("ocean_current_direction")
        cond.sea_surface_temp_c = cur.get("sea_surface_temperature")

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        cond.hourly = [
            {
                "time": times[i],
                "wave_height_m": (hourly.get("wave_height") or [None] * len(times))[i],
                "wave_period_s": (hourly.get("wave_period") or [None] * len(times))[i],
                "current_speed_kmh": (hourly.get("ocean_current_velocity") or [None] * len(times))[i],
            }
            for i in range(min(len(times), 24))
        ]
    except Exception as exc:
        cond.erro = f"Marine API: {exc}"

    # ---- Forecast API (vento) ----
    try:
        params_forecast = {
            "latitude": lat,
            "longitude": lon,
            "current": ["wind_speed_10m", "wind_gusts_10m", "wind_direction_10m"],
            "wind_speed_unit": "kmh",
            "timezone": "auto",
        }
        r = requests.get(FORECAST_URL, params=params_forecast, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        cur = data.get("current", {})
        cond.wind_speed_kmh = cur.get("wind_speed_10m")
        cond.wind_gust_kmh = cur.get("wind_gusts_10m")
        cond.wind_direction_deg = cur.get("wind_direction_10m")
    except Exception as exc:
        cond.erro = (cond.erro + "; " if cond.erro else "") + f"Forecast API: {exc}"

    return cond


def conditions_to_dict(cond: MarineConditions) -> dict:
    """Serializa para JSON, incluindo semáforos."""
    onda_nivel, onda_cor = _classificar_onda(cond.wave_height_m)
    vento_nivel, vento_cor = _classificar_vento(cond.wind_speed_kmh)
    corrente_nivel, corrente_cor = _classificar_corrente(cond.current_speed_kmh)

    return {
        "ok": not cond.erro,
        "erro": cond.erro,
        "lat": cond.lat,
        "lon": cond.lon,
        "fetched_at": cond.fetched_at,
        "ondas": {
            "altura_m": cond.wave_height_m,
            "periodo_s": cond.wave_period_s,
            "direcao_deg": cond.wave_direction_deg,
            "swell_m": cond.swell_height_m,
            "nivel": onda_nivel,
            "cor": onda_cor,
        },
        "vento": {
            "velocidade_kmh": cond.wind_speed_kmh,
            "rajada_kmh": cond.wind_gust_kmh,
            "direcao_deg": cond.wind_direction_deg,
            "nivel": vento_nivel,
            "cor": vento_cor,
        },
        "corrente": {
            "velocidade_kmh": cond.current_speed_kmh,
            "direcao_deg": cond.current_direction_deg,
            "nivel": corrente_nivel,
            "cor": corrente_cor,
        },
        "temperatura_mar_c": cond.sea_surface_temp_c,
        "hourly": cond.hourly,
        "fonte": cond.fonte,
        "aviso": cond.aviso,
    }