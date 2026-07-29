"""Reglas de cierre de apuestas: quien gana, quien pierde y quien se devuelve.

Vive aparte de app.py porque ahi todo arranca Streamlit al importarse, y estas
reglas deciden dinero: tienen que poder probarse solas, sin levantar la app.
No dependen de Streamlit ni de la red, solo de los partidos que se les pasan.
"""
import re


def _team_match(a, b):
    a, b = a.strip().lower(), b.strip().lower()
    return a in b or b in a


def find_final(matchup, games):
    for g in games:
        if g["is_final"] and _team_match(g["away_team"], matchup) and _team_match(g["home_team"], matchup):
            return g
    return None


def buscar_partido(matchup, games):
    """El partido del enfrentamiento en CUALQUIER estado (en vivo incluido).
    Con dobles carteleras se prefiere el que ya tiene accion."""
    candidatos = [g for g in games
                  if _team_match(g["away_team"], matchup)
                  and _team_match(g["home_team"], matchup)]
    if not candidatos:
        return None
    return next((g for g in candidatos if g["is_live"] or g["is_final"]), candidatos[0])


VENTAJA_PAGO_ANTICIPADO = 5          # carreras


def ventaja_maxima(g):
    """Mayor ventaja que llego a tener cada equipo -> (visitante, local).

    Se reconstruye medio inning a medio inning desde las carreras por entrada,
    no desde el marcador final. Asi se detecta la ventaja aunque la app no
    estuviera abierta en ese momento, y tambien en partidos ya terminados.
    """
    visitante = local = 0
    mejor_v = mejor_l = 0
    for carreras_v, carreras_l in (g.get("innings_runs") or []):
        visitante += carreras_v                      # cierre de la parte alta
        mejor_v, mejor_l = max(mejor_v, visitante - local), max(mejor_l, local - visitante)
        local += carreras_l                          # cierre de la parte baja
        mejor_v, mejor_l = max(mejor_v, visitante - local), max(mejor_l, local - visitante)
    # Marcador actual, por si la fuente no trae desglose por entradas
    v, l = g.get("away_score", 0) or 0, g.get("home_score", 0) or 0
    return max(mejor_v, v - l), max(mejor_l, l - v)


def cobro_anticipado(selection, g):
    """True si el equipo elegido llego a ir 5+ carreras arriba en algun momento.

    Es la promocion de pago anticipado: la casa liquida el moneyline como
    ganado en cuanto se alcanza esa ventaja, aunque el partido se voltee.
    """
    mejor_v, mejor_l = ventaja_maxima(g)
    if _team_match(selection, g["away_team"]):
        return mejor_v >= VENTAJA_PAGO_ANTICIPADO
    if _team_match(selection, g["home_team"]):
        return mejor_l >= VENTAJA_PAGO_ANTICIPADO
    return False


def settle_pick(matchup, selection, market, games):
    """Determina WON/LOST comparando la selección contra el resultado real.
    Devuelve None si el partido no ha finalizado o no se puede decidir."""
    sel = selection.lower()
    mkt = (market or "").upper()
    es_total = mkt == "TOTAL" or "under" in sel or "over" in sel
    es_f5 = mkt == "F5" or "f5" in sel or "first 5" in sel

    # PAGO ANTICIPADO (solo moneyline): se comprueba ANTES de exigir que el
    # partido haya terminado, para marcarlo en cuanto ocurre la ventaja.
    if not es_total and not es_f5:
        g = buscar_partido(matchup, games)
        if g and cobro_anticipado(selection, g):
            return "WON"

    g = find_final(matchup, games)
    if not g:
        return None

    if es_total:
        m = re.search(r"(\d+(?:\.\d+)?)", selection)
        line = float(m.group(1)) if m else 8.5
        total = g["away_score"] + g["home_score"]
        if total == line:
            return "PUSH"  # el total cae justo en la linea = devolucion
        if "under" in sel:
            return "WON" if total < line else "LOST"
        return "WON" if total > line else "LOST"   # over

    if es_f5:
        if g["innings_played"] < 5:
            return None
        af5, hf5 = g["away_f5"], g["home_f5"]
        if af5 == hf5:
            return "PUSH"  # empate en las primeras 5 entradas = devolución
        winner = g["home_team"] if hf5 > af5 else g["away_team"]
        return "WON" if _team_match(selection, winner) else "LOST"

    # Moneyline: la selección nombra al equipo
    if g["home_score"] == g["away_score"]:
        return "PUSH"  # finalizado en empate: no hay ganador, se devuelve
    winner = g["home_team"] if g["home_score"] > g["away_score"] else g["away_team"]
    return "WON" if _team_match(selection, winner) else "LOST"
