"""Lector de datos para la KBO (liga coreana).

A diferencia de MLB y LMB, la KBO NO tiene datos en la MLB Stats API: esa API
registra la liga (sportId=32) pero devuelve 0 partidos. Por eso aquí la agenda y
los marcadores se leen de The Odds API, que sí la cubre.

Expone la misma interfaz que MLBDataFetcher, para que el motor no note la
diferencia: get_todays_games(), get_live_scores() y get_pitcher_stats().

LIMITACIÓN IMPORTANTE: esta fuente no publica estadísticas de abridores, así que
get_pitcher_stats() siempre devuelve valores genéricos. El modelo pierde su
insumo principal y sus probabilidades son mucho más débiles que en MLB.
"""
import os
from datetime import datetime

import requests

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("America/Chicago")
except Exception:
    _TZ = None

SPORT = "baseball_kbo"
BASE = "https://api.the-odds-api.com/v4/sports"

# Valores genéricos: sin stats de abridores disponibles para esta liga.
_PITCHER_DEFAULT = {"era": 4.15, "xera": 4.10, "whip": 1.28, "k_pct": 0.22, "bb_pct": 0.08}


def _hoy() -> str:
    return (datetime.now(_TZ) if _TZ else datetime.now()).strftime("%Y-%m-%d")


def _a_local(iso: str) -> str:
    """Fecha local (YYYY-MM-DD) de un instante UTC."""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return (dt.astimezone(_TZ) if _TZ else dt.astimezone()).strftime("%Y-%m-%d")
    except Exception:
        return ""


class KBODataFetcher:
    """Agenda y marcadores de la KBO vía The Odds API."""

    def __init__(self, api_key: str = None, fecha: str = None):
        # `fecha` fija la jornada a consultar. La app le pasa la fecha con el
        # desfase de la liga (Corea juega de madrugada en hora Central).
        self.api_key = api_key or os.getenv("ODDS_API_KEY", "")
        self.fecha = fecha

    def _scores(self, days_from: int = 3) -> list:
        """Consulta cruda. Incluye partidos recientes y próximos."""
        if not self.api_key:
            return []
        try:
            r = requests.get(f"{BASE}/{SPORT}/scores",
                             params={"apiKey": self.api_key, "daysFrom": days_from},
                             timeout=10)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    def get_todays_games(self, date: str = None) -> list:
        dia = date or self.fecha or _hoy()
        salida = []
        for g in self._scores():
            if _a_local(g.get("commence_time")) != dia:
                continue
            salida.append({
                "game_id": str(g.get("id", "")),
                "away_team": g.get("away_team", "Away"),
                "home_team": g.get("home_team", "Home"),
                # Sin datos de abridores en esta fuente
                "away_pitcher_id": 0,
                "home_pitcher_id": 0,
                "pitchers_confirmed": False,
            })
        return salida

    def get_live_scores(self, date: str = None) -> list:
        dia = date or self.fecha or _hoy()
        salida = []
        for g in self._scores():
            if _a_local(g.get("commence_time")) != dia:
                continue

            marcador = {s.get("name"): s.get("score") for s in (g.get("scores") or [])}

            def _n(equipo):
                try:
                    return int(marcador.get(equipo) or 0)
                except (TypeError, ValueError):
                    return 0

            away, home = g.get("away_team", "Away"), g.get("home_team", "Home")
            terminado = bool(g.get("completed"))
            empezado = bool(g.get("scores"))
            estado = "Final" if terminado else ("Live" if empezado else "Preview")

            salida.append({
                "game_id": str(g.get("id", "")),
                "away_team": away, "home_team": home,
                "away_id": 0, "home_id": 0,          # sin logos en esta fuente
                "away_score": _n(away), "home_score": _n(home),
                "away_hits": 0, "home_hits": 0,
                "away_errors": 0, "home_errors": 0,
                "away_f5": 0, "home_f5": 0,
                "innings_played": 0,
                "on_first": False, "on_second": False, "on_third": False,
                "state": estado,
                "detail": "Final" if terminado else ("En juego" if empezado else "Programado"),
                "is_live": estado == "Live",
                "is_final": terminado,
                "inning": 0, "inning_ordinal": "", "inning_state": "", "outs": 0,
                "start_utc": g.get("commence_time", ""),
                "away_pitcher": "", "home_pitcher": "",
            })
        return salida

    def get_pitcher_stats(self, pitcher_id: int = 0) -> dict:
        """Sin stats de abridores para KBO: siempre valores genéricos."""
        return dict(_PITCHER_DEFAULT)
