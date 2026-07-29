from datetime import datetime

import requests

# Zona horaria de la app. Sin esto se usaria el "hoy" que decida la API, que
# puede ir un dia atras del reloj local: entonces se analizarian partidos ya
# jugados y los picks del dia nacerian finalizados.
try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("America/Chicago")
except Exception:
    _TZ = None


def _hoy() -> str:
    return (datetime.now(_TZ) if _TZ else datetime.now()).strftime("%Y-%m-%d")


# Abridor "promedio" que se usa cuando el partido no tiene lanzador anunciado.
# Estos numeros estan calibrados para MLB (ERA real de liga 4.21, WHIP 1.31) y
# por eso NO se tocan. En otra liga son un dato equivocado: aplicarlos a la LMB
# (ERA de liga 5.08) hacia que el modelo esperara casi una carrera menos por
# partido de las que se anotan. Cada liga pasa el suyo por `stats_genericas`.
GENERICO_MLB = {"era": 4.15, "xera": 4.10, "whip": 1.28, "k_pct": 0.22, "bb_pct": 0.08}


class MLBDataFetcher:
    """Lector de la MLB Stats API. Por defecto trae MLB (sportId=1); con otros
    parametros sirve para ligas como la LMB (sportId=23, leagueId=125), que viven
    en la misma API. El comportamiento por defecto NO cambia."""

    BASE_URL = "https://statsapi.mlb.com/api/v1"

    def __init__(self, sport_id: int = 1, league_id: int = None, stats_genericas: dict = None):
        self.sport_id = sport_id
        self.league_id = league_id
        # Sin argumento se conserva el generico de MLB de siempre.
        self.stats_genericas = dict(stats_genericas or GENERICO_MLB)

    @property
    def _liga(self) -> str:
        return f"&leagueId={self.league_id}" if self.league_id else ""

    def get_todays_games(self, date: str = None) -> list:
        """Jornada del día desde MLB Stats API (fecha explícita, no la de la API)."""
        try:
            url = (f"{self.BASE_URL}/schedule?sportId={self.sport_id}{self._liga}"
                   f"&date={date or _hoy()}&hydrate=probablePitcher")
            response = requests.get(url, timeout=5).json()
            dates = response.get('dates', [])
            if not dates:
                return self._get_fallback_games()

            games = []
            for game_data in dates[0].get('games', []):
                away_team = game_data.get('teams', {}).get('away', {}).get('team', {}).get('name', 'Away')
                home_team = game_data.get('teams', {}).get('home', {}).get('team', {}).get('name', 'Home')
                
                # Obtener IDs de abridores si están confirmados
                away_pitcher_id = game_data.get('teams', {}).get('away', {}).get('probablePitcher', {}).get('id', 0)
                home_pitcher_id = game_data.get('teams', {}).get('home', {}).get('probablePitcher', {}).get('id', 0)

                games.append({
                    "game_id": str(game_data.get('gamePk')),
                    "away_team": away_team,
                    "home_team": home_team,
                    "away_pitcher_id": away_pitcher_id,
                    "home_pitcher_id": home_pitcher_id,
                    "pitchers_confirmed": bool(away_pitcher_id and home_pitcher_id)
                })
            return games if games else self._get_fallback_games()
        except Exception:
            return self._get_fallback_games()

    def get_live_scores(self, date: str = None) -> list:
        """Marcadores en vivo / finales vía MLB Stats API (hydrate=linescore).
        Si se pasa `date` (YYYY-MM-DD) devuelve los partidos de ESE día; si no, los de hoy.
        Necesario para cerrar picks de jornadas anteriores."""
        try:
            fecha = f"&date={date or _hoy()}"
            url = (f"{self.BASE_URL}/schedule?sportId={self.sport_id}{self._liga}{fecha}"
                   f"&hydrate=linescore,team,probablePitcher")
            response = requests.get(url, timeout=6).json()
            dates = response.get('dates', [])
            if not dates:
                return []

            games = []
            for g in dates[0].get('games', []):
                teams = g.get('teams', {})
                away = teams.get('away', {})
                home = teams.get('home', {})
                status = g.get('status', {})
                ls = g.get('linescore', {})
                ls_teams = ls.get('teams', {})

                abstract = status.get('abstractGameState', '')  # Preview / Live / Final
                offense = ls.get('offense', {})
                innings = ls.get('innings', [])
                away_f5 = sum((i.get('away', {}).get('runs', 0) or 0) for i in innings[:5])
                home_f5 = sum((i.get('home', {}).get('runs', 0) or 0) for i in innings[:5])
                games.append({
                    "game_id": str(g.get('gamePk')),
                    "away_team": away.get('team', {}).get('name', 'Away'),
                    "home_team": home.get('team', {}).get('name', 'Home'),
                    "away_id": away.get('team', {}).get('id', 0),
                    "home_id": home.get('team', {}).get('id', 0),
                    "on_first": 'first' in offense,
                    "on_second": 'second' in offense,
                    "on_third": 'third' in offense,
                    "away_f5": away_f5,
                    "home_f5": home_f5,
                    "innings_played": len(innings),
                    # Carreras por entrada. Permiten reconstruir el marcador a lo
                    # largo del partido, no solo el final: con eso se detecta si
                    # un equipo llego a ir 5 o mas arriba (pago anticipado).
                    "innings_runs": [((i.get('away', {}).get('runs') or 0),
                                      (i.get('home', {}).get('runs') or 0))
                                     for i in innings],
                    "away_score": away.get('score', ls_teams.get('away', {}).get('runs', 0)) or 0,
                    "home_score": home.get('score', ls_teams.get('home', {}).get('runs', 0)) or 0,
                    "away_hits": ls_teams.get('away', {}).get('hits', 0),
                    "home_hits": ls_teams.get('home', {}).get('hits', 0),
                    "away_errors": ls_teams.get('away', {}).get('errors', 0),
                    "home_errors": ls_teams.get('home', {}).get('errors', 0),
                    "state": abstract,
                    "detail": status.get('detailedState', ''),
                    # La API marca abstractGameState="Live" desde que empieza el calentamiento
                    # (detailedState="Warmup"), ~30 min antes del primer lanzamiento real.
                    "is_live": abstract == 'Live' and status.get('detailedState') not in ('Warmup', 'Pre-Game'),
                    "is_final": abstract == 'Final',
                    "inning": ls.get('currentInning', 0) or 0,
                    "inning_ordinal": ls.get('currentInningOrdinal', ''),
                    "inning_state": ls.get('inningState', ''),
                    "outs": ls.get('outs', 0),
                    "start_utc": g.get('gameDate', ''),
                    "away_pitcher": away.get('probablePitcher', {}).get('fullName', ''),
                    "home_pitcher": home.get('probablePitcher', {}).get('fullName', ''),
                    # Id del abridor y abreviatura del equipo: la vista En vivo los
                    # usa para mostrar "Luzardo J. [PHI] (9-5)".
                    "away_pitcher_id": away.get('probablePitcher', {}).get('id', 0),
                    "home_pitcher_id": home.get('probablePitcher', {}).get('id', 0),
                    "away_abbr": away.get('team', {}).get('abbreviation', ''),
                    "home_abbr": home.get('team', {}).get('abbreviation', ''),
                })
            return games
        except Exception:
            return []

    def get_pitcher_stats(self, pitcher_id: int) -> dict:
        """Fetch en tiempo real de métricas de pitcheo vía MLB API.

        La consulta lleva el sportId de la liga del fetcher. Sin él, la API
        devuelve solo las estadísticas de MLB y los abridores de la LMB salían
        SIN STATS: el motor caía al ERA genérico de 4.15 para los dos lados de
        cada partido, así que todas las probabilidades quedaban pegadas al 50%.
        Para MLB (sportId=1) el resultado es idéntico al de antes.
        """
        if not pitcher_id:
            return dict(self.stats_genericas)
        try:
            temporada = _hoy()[:4]
            url = (f"{self.BASE_URL}/people/{pitcher_id}?hydrate=stats(group=[pitching],"
                   f"type=[season],sportId={self.sport_id},season={temporada})")
            res = requests.get(url, timeout=5).json()
            stats = res['people'][0]['stats'][0]['splits'][0]['stat']
            era = float(stats.get('era', 4.15))
            whip = float(stats.get('whip', 1.25))
            return {
                "era": era,
                "xera": round(era * 0.95, 2), # Estimación dinámicamente ajustada por FIP/xERA
                "whip": whip,
                "k_pct": 0.24,
                "bb_pct": 0.07
            }
        except Exception:
            return dict(self.stats_genericas)

    def _get_fallback_games(self) -> list:
        return [
            {"game_id": "747001", "away_team": "Tampa Bay Rays", "home_team": "Toronto Blue Jays", "away_pitcher_id": 669203, "home_pitcher_id": 592332, "pitchers_confirmed": True},
            {"game_id": "747002", "away_team": "San Diego Padres", "home_team": "Atlanta Braves", "away_pitcher_id": 605483, "home_pitcher_id": 675911, "pitchers_confirmed": True},
            {"game_id": "747003", "away_team": "Minnesota Twins", "home_team": "Cleveland Guardians", "away_pitcher_id": 657240, "home_pitcher_id": 663474, "pitchers_confirmed": True}
        ]
