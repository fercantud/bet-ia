"""Los dos casos de devolución que dejaban picks colgados para siempre.

Ambos aparecieron analizando la KBO, pero no eran problemas de esa liga: son
reglas de cierre que valen igual para MLB y LMB. settle_pick() devolvía None
—"no se puede decidir"— y el pick se quedaba PENDING sin que nada volviera a
mirarlo, porque el partido ya estaba finalizado y no iba a cambiar.

El caso del total exacto es el que más importa: las casas ofrecen líneas
enteras (8, 9, 10) todo el tiempo y en MLB son de las más comunes.
"""
from app_logica import settle_pick

PARTIDO = "NC Dinos @ SSG Landers"


def _juego(away, home, entradas=9):
    return [{"away_team": "NC Dinos", "home_team": "SSG Landers",
             "away_score": away, "home_score": home,
             "innings_played": entradas, "innings_runs": [],
             "away_f5": 0, "home_f5": 0, "is_final": True, "is_live": False}]


def test_total_exacto_en_la_linea_es_push():
    """KT 10 - 0 NC con Under 10: se quedó pendiente para siempre el 28/07."""
    assert settle_pick(PARTIDO, "Under 10", "TOTAL", _juego(10, 0)) == "PUSH"
    assert settle_pick(PARTIDO, "Over 9", "TOTAL", _juego(4, 5)) == "PUSH"


def test_empate_final_es_push():
    """Un final empatado no tiene ganador: la apuesta se devuelve."""
    assert settle_pick(PARTIDO, "SSG Landers", "ML", _juego(5, 5)) == "PUSH"


def test_los_casos_normales_no_cambiaron():
    assert settle_pick(PARTIDO, "Under 10", "TOTAL", _juego(3, 5)) == "WON"
    assert settle_pick(PARTIDO, "Under 11", "TOTAL", _juego(5, 12)) == "LOST"
    assert settle_pick(PARTIDO, "Over 8.5", "TOTAL", _juego(6, 5)) == "WON"
    assert settle_pick(PARTIDO, "Over 8.5", "TOTAL", _juego(2, 1)) == "LOST"
    # visitante NC 2 - 1 SSG local: gana el visitante
    assert settle_pick(PARTIDO, "NC Dinos", "ML", _juego(2, 1)) == "WON"
    assert settle_pick(PARTIDO, "SSG Landers", "ML", _juego(2, 1)) == "LOST"


def test_un_partido_sin_terminar_no_se_cierra():
    juego = _juego(3, 5)
    juego[0]["is_final"], juego[0]["is_live"] = False, True
    assert settle_pick(PARTIDO, "Under 10", "TOTAL", juego) is None
