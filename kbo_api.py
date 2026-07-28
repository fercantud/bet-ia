"""Lector de datos para la KBO (liga coreana).

A diferencia de MLB y LMB, la KBO NO tiene datos en la MLB Stats API: esa API
registra la liga (sportId=32) pero devuelve 0 partidos.

La primera versión leía la agenda y los marcadores de The Odds API, pero esa
fuente resultó inservible para llevar historial: publica los partidos poco antes
de empezar y los BORRA sin dejar resultado. El 28/07/2026 pasó de devolver 1 de
5 partidos a devolver 0, y los picks de ese día se quedaron sin poder cerrarse.

Ahora la agenda y los marcadores salen de MyKBO Stats, que expone un bloque por
fecha en /api/v2/games/game-day-block/YYYY-MM-DD. Devuelve un fragmento de HTML
pequeño y estable con los cinco partidos del día, su estado y su marcador, y
—clave— sigue disponible para fechas pasadas, así que los picks atrasados se
pueden cerrar. Su robots.txt lo permite (solo bloquea /stats/compare/) y pide
Crawl-delay: 5; la app cachea estas llamadas, así que se consultan pocas veces.

The Odds API se sigue usando, pero SOLO para las cuotas (ver odds_api.py).

Expone la misma interfaz que MLBDataFetcher, para que el motor no note la
diferencia: get_todays_games(), get_live_scores() y get_pitcher_stats().

LIMITACIONES: esta fuente no publica estadísticas de abridores, así que
get_pitcher_stats() siempre devuelve valores genéricos y el modelo pierde su
insumo principal. Tampoco expone el parcial de 5 entradas, de modo que los picks
F5 no se pueden cerrar (el motor no los elige, ver main.py).
"""
import re
import time
from datetime import datetime

import requests

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("America/Chicago")
except Exception:
    _TZ = None

BLOQUE_DIA = "https://mykbostats.com/api/v2/games/game-day-block/{fecha}"
_UA = {"User-Agent": "BetIA/1.0 (dashboard personal de apuestas)"}

# Valores genéricos: sin stats de abridores disponibles para esta liga.
_PITCHER_DEFAULT = {"era": 4.15, "xera": 4.10, "whip": 1.28, "k_pct": 0.22, "bb_pct": 0.08}

# Caché en memoria del proceso. get_todays_games() y get_live_scores() suelen
# pedir la misma fecha seguidas; sin esto se harían dos descargas por render.
_CACHE = {}
_CACHE_TTL = 120


def _hoy() -> str:
    return (datetime.now(_TZ) if _TZ else datetime.now()).strftime("%Y-%m-%d")


def _texto(html: str) -> str:
    """Quita etiquetas y colapsa espacios."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _descargar(fecha: str) -> str:
    en_cache = _CACHE.get(fecha)
    if en_cache and (time.time() - en_cache[0]) < _CACHE_TTL:
        return en_cache[1]
    try:
        r = requests.get(BLOQUE_DIA.format(fecha=fecha), headers=_UA, timeout=10)
        html = r.text if r.status_code == 200 else ""
    except Exception:
        html = ""
    _CACHE[fecha] = (time.time(), html)
    return html


def _parsear(html: str) -> list:
    """Convierte el fragmento HTML en una lista de partidos.

    Cada tarjeta trae dos bloques ds-game-team (visitante primero, local
    después). El marcador solo existe si el partido ya empezó.
    """
    partidos = []
    for card in re.split(r'<a id="game-line-', html)[1:]:
        try:
            gid = re.match(r"(\d+)", card).group(1)
            equipos = re.findall(r'<div class="ds-game-team[^"]*">(.*?)</div>', card, re.S)
            if len(equipos) != 2:
                continue

            datos = []
            for blk in equipos:
                nombre = re.search(r'__name">(.*?)</span>\s*</span>', blk, re.S)
                marca = re.search(r'__score">\s*(-?\d+)\s*</span>', blk)
                datos.append((_texto(nombre.group(1)) if nombre else "",
                              int(marca.group(1)) if marca else None))
            (away, away_r), (home, home_r) = datos
            if not (away and home):
                continue

            est = re.search(r'ds-game-card__state[^"]*">(.*?)</span>', card, re.S)
            estado_txt = _texto(est.group(1)) if est else ""
            cuando = re.search(r'<time[^>]*datetime="([^"]+)"', card)

            # "Final" o "Final/10" (entradas extra). Si no dice Final pero ya hay
            # marcador, está en curso.
            final = estado_txt.lower().startswith("final")
            empezado = away_r is not None and home_r is not None
            extra = re.search(r"Final/(\d+)", estado_txt)

            partidos.append({
                "game_id": gid,
                "away_team": away, "home_team": home,
                "away_score": away_r or 0, "home_score": home_r or 0,
                "final": final, "empezado": empezado,
                "entradas": int(extra.group(1)) if extra else (9 if final else 0),
                "estado_txt": estado_txt,
                "start_utc": cuando.group(1) if cuando else "",
            })
        except Exception:
            continue
    return partidos


class KBODataFetcher:
    """Agenda y marcadores de la KBO vía MyKBO Stats."""

    def __init__(self, api_key: str = None, fecha: str = None):
        # `api_key` se conserva por compatibilidad con la firma anterior; esta
        # fuente no la necesita. `fecha` fija la jornada a consultar: la app le
        # pasa la fecha con el desfase de la liga (Corea juega de madrugada en
        # hora Central).
        self.api_key = api_key
        self.fecha = fecha

    def _partidos(self, date: str = None) -> list:
        # La fecha del bloque es la coreana. Los partidos empiezan a las 18:30
        # KST = 04:30 Central del MISMO día, así que ambas fechas coinciden y no
        # hace falta convertir.
        return _parsear(_descargar(date or self.fecha or _hoy()))

    def get_todays_games(self, date: str = None) -> list:
        return [{
            "game_id": g["game_id"],
            "away_team": g["away_team"],
            "home_team": g["home_team"],
            # Sin datos de abridores en esta fuente
            "away_pitcher_id": 0,
            "home_pitcher_id": 0,
            "pitchers_confirmed": False,
        } for g in self._partidos(date)]

    def get_live_scores(self, date: str = None) -> list:
        salida = []
        for g in self._partidos(date):
            estado = "Final" if g["final"] else ("Live" if g["empezado"] else "Preview")
            salida.append({
                "game_id": g["game_id"],
                "away_team": g["away_team"], "home_team": g["home_team"],
                "away_id": 0, "home_id": 0,          # sin logos en esta fuente
                "away_score": g["away_score"], "home_score": g["home_score"],
                "away_hits": 0, "home_hits": 0,
                "away_errors": 0, "home_errors": 0,
                "away_f5": 0, "home_f5": 0,          # la fuente no da el parcial de 5
                "innings_played": g["entradas"],
                "on_first": False, "on_second": False, "on_third": False,
                "state": estado,
                "detail": "Final" if g["final"] else ("En juego" if g["empezado"] else "Programado"),
                "is_live": estado == "Live",
                "is_final": g["final"],
                "inning": 0, "inning_ordinal": "", "inning_state": "", "outs": 0,
                "start_utc": g["start_utc"],
                "away_pitcher": "", "home_pitcher": "",
            })
        return salida

    def get_pitcher_stats(self, pitcher_id: int = 0) -> dict:
        """Sin stats de abridores para KBO: siempre valores genéricos."""
        return dict(_PITCHER_DEFAULT)
