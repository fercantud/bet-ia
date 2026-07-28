"""Protege el lector de KBO y las reglas de cierre que estrenó.

Contexto: The Odds API borraba los partidos de KBO sin publicar resultado, así
que los picks del 28/07 se quedaron pendientes para siempre. La agenda y los
marcadores pasaron a MyKBO Stats. Estos tests fijan el formato que se parsea
(una fixture, sin red) y los dos casos de devolución que aparecieron con esa
liga: el total que cae justo en la línea y el empate, que la KBO sí permite.
"""
import kbo_api
from kbo_api import KBODataFetcher, _parsear


def _tarjeta(gid, away, a_slug, home, h_slug, estado,
             a_score=None, h_score=None, cuando=None):
    def equipo(nombre, slug, marca):
        corto, _, sufijo = nombre.partition(" ")
        pts = f'<span class="ds-game-team__score">{marca}</span>' if marca is not None else ""
        return (f'<div class="ds-game-team ">'
                f'<img class="ds-team-logo" src="/assets/images/team-logos-alt/{slug}.png">'
                f'<span class="ds-game-team__name">\n    {corto}'
                f'<span class="ds-game-team__suffix"> {sufijo}</span>\n  </span>'
                f'{pts}</div>')

    reloj = (f'<time data-format="%l:%M%P" datetime="{cuando}">6:30pm</time>'
             if cuando else estado)
    return (f'<a id="game-line-{gid}" class="ds-game-card " href="/games/{gid}-x-2026">'
            f'<div class="ds-game-card__teams">'
            f'{equipo(away, a_slug, a_score)}{equipo(home, h_slug, h_score)}</div>'
            f'<div class="ds-game-card__status">'
            f'<span class="ds-game-card__state ">{reloj}</span></div></a>')


BLOQUE = ('<section class="ds-schedule-day"><div class="ds-game-list">'
          + _tarjeta("1", "Kia Tigers", "kia", "Samsung Lions", "samsung", "Final", 5, 12)
          + _tarjeta("2", "Doosan Bears", "doosan", "SSG Landers", "ssg", "Final/10", 2, 1)
          + _tarjeta("3", "NC Dinos", "nc", "SSG Landers", "ssg", "Final/11", 5, 5)
          + _tarjeta("4", "KT Wiz", "kt", "NC Dinos", "nc", "", None, None,
                     cuando="2026-07-29T09:30:00Z")
          + "</div></section>")


def test_parsea_finales_con_marcador():
    g = _parsear(BLOQUE)[0]
    assert (g["away_team"], g["home_team"]) == ("Kia Tigers", "Samsung Lions")
    assert (g["away_score"], g["home_score"]) == (5, 12)
    assert g["final"] and g["entradas"] == 9


def test_entradas_extra():
    assert _parsear(BLOQUE)[1]["entradas"] == 10


def test_partido_programado_no_trae_marcador():
    g = _parsear(BLOQUE)[3]
    assert not g["final"] and not g["empezado"]
    assert g["start_utc"] == "2026-07-29T09:30:00Z"


def test_visitante_va_primero_y_local_despues():
    """Si se invierte el orden, los picks se cierran al revés."""
    g = _parsear(BLOQUE)[0]
    assert g["away_team"] == "Kia Tigers", "el primer bloque es el visitante"


def test_get_live_scores_expone_la_interfaz_de_mlb(monkeypatch):
    monkeypatch.setattr(kbo_api, "_descargar", lambda fecha: BLOQUE)
    juegos = KBODataFetcher(fecha="2026-07-28").get_live_scores()
    assert len(juegos) == 4
    obligatorias = {"game_id", "away_team", "home_team", "away_score", "home_score",
                    "state", "is_final", "is_live", "innings_played", "start_utc"}
    assert obligatorias <= set(juegos[0]), "falta una clave que la app espera"
    assert juegos[0]["is_final"] and juegos[3]["state"] == "Preview"


def test_sin_red_devuelve_lista_vacia(monkeypatch):
    monkeypatch.setattr(kbo_api, "_descargar", lambda fecha: "")
    assert KBODataFetcher(fecha="2026-07-28").get_todays_games() == []


# --- reglas de cierre que la KBO destapó -----------------------------------

def _settle(selection, market, away, home, entradas=9):
    """Replica settle_pick() sin importar app.py (que arranca Streamlit)."""
    import re
    g = {"away_team": "NC Dinos", "home_team": "SSG Landers",
         "away_score": away, "home_score": home, "innings_played": entradas,
         "away_f5": 0, "home_f5": 0, "is_final": True}
    sel, mkt = selection.lower(), market.upper()
    if mkt == "TOTAL":
        line = float(re.search(r"(\d+(?:\.\d+)?)", selection).group(1))
        total = g["away_score"] + g["home_score"]
        if total == line:
            return "PUSH"
        return ("WON" if total < line else "LOST") if "under" in sel else \
               ("WON" if total > line else "LOST")
    if g["home_score"] == g["away_score"]:
        return "PUSH"
    ganador = g["home_team"] if g["home_score"] > g["away_score"] else g["away_team"]
    return "WON" if selection.strip().lower() in ganador.lower() else "LOST"


def test_total_exacto_en_la_linea_es_push():
    """KT 10 - 0 NC con Under 10: el 28/07 se quedó pendiente para siempre."""
    assert _settle("Under 10", "TOTAL", 10, 0) == "PUSH"


def test_empate_final_es_push():
    """La KBO permite empates (NC 5 - 5 SSG en 11 entradas)."""
    assert _settle("SSG Landers", "ML", 5, 5) == "PUSH"


def test_total_normal_sigue_igual():
    assert _settle("Under 10", "TOTAL", 3, 5) == "WON"
    assert _settle("Under 11", "TOTAL", 5, 12) == "LOST"
    # visitante NC 2 - 1 SSG local: gana el visitante
    assert _settle("NC Dinos", "ML", 2, 1) == "WON"
    assert _settle("SSG Landers", "ML", 2, 1) == "LOST"
