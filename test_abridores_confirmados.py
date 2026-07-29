"""Sin los dos abridores anunciados no se emite pick.

El 29/07 el partido Colorado @ San Diego no tenía abridor local anunciado. Al
que faltaba se le rellenaba con un lanzador promedio (ERA 4.15) y el modelo lo
tomaba por un dato real: comparó ese relleno contra el abridor de Colorado
(2.65 xERA) y publicó Rockies 62% con +39.1% de EV. El mercado los tenía en
44%. Todo el "valor" salía del hueco.

El pick no se pierde: en cuanto se anuncia el abridor, el partido se analiza y
se suma a los del día (get_todays_analysis en app.py). Lo que ya estaba no se
recalcula, para que un pick no cambie después de que el usuario lo vio.
"""
import numpy as np

import main


class FetcherFalso:
    """Agenda mínima con la interfaz que espera el motor."""

    def __init__(self, confirmados):
        self.confirmados = confirmados

    def get_todays_games(self, date=None):
        return [{
            "game_id": "1", "away_team": "Colorado Rockies",
            "home_team": "San Diego Padres",
            "away_pitcher_id": 687312,
            "home_pitcher_id": 605483 if self.confirmados else 0,
            "pitchers_confirmed": self.confirmados,
        }]

    def get_pitcher_stats(self, pitcher_id=0):
        if pitcher_id == 687312:                      # abridor real de Colorado
            return {"era": 2.79, "xera": 2.65, "whip": 1.14, "k_pct": .24, "bb_pct": .07}
        return {"era": 4.15, "xera": 4.10, "whip": 1.28, "k_pct": .22, "bb_pct": .08}


def _picks(confirmados):
    np.random.seed(20260729)
    return main.get_analyzed_bets(fetcher=FetcherFalso(confirmados),
                                  con_cuotas_reales=False, con_demo=False,
                                  odds_sport=None)


def test_sin_abridor_anunciado_no_hay_pick():
    assert _picks(False) == [], "un abridor sin anunciar no puede generar pick"


def test_con_los_dos_abridores_si_hay_pick():
    """El filtro no debe apagar los partidos normales."""
    bets = _picks(True)
    assert len(bets) == 1
    assert bets[0]["matchup"] == "Colorado Rockies @ San Diego Padres"


def test_el_motor_no_se_apoya_en_el_flag_cuando_no_existe():
    """Fuentes sin el campo (p.ej. los partidos de respaldo) siguen analizandose."""
    class SinFlag(FetcherFalso):
        def get_todays_games(self, date=None):
            g = super().get_todays_games(date)
            g[0].pop("pitchers_confirmed")
            return g

    np.random.seed(20260729)
    bets = main.get_analyzed_bets(fetcher=SinFlag(True), con_cuotas_reales=False,
                                  con_demo=False, odds_sport=None)
    assert len(bets) == 1, "sin el campo se asume analizable, como antes"


# --- al anunciarse el abridor, el pick se suma sin tocar los que ya estaban ---

def _falso(matchup, ev, score):
    return {"matchup": matchup, "ev": ev, "score": score, "confidence": 7.0,
            "prob_model": 0.60, "odds": 2.0, "rank": 99}


def test_rank_bets_renumera_el_conjunto():
    bets = main.rank_bets([_falso("A @ B", 0.10, 70), _falso("C @ D", 0.30, 80)])
    assert [b["matchup"] for b in bets] == ["C @ D", "A @ B"]
    assert [b["rank"] for b in bets] == [1, 2]


def test_sumar_un_pick_no_altera_los_calculos_de_los_previos():
    """Lo unico que puede cambiar de un pick ya publicado es su rank."""
    previos = [_falso("A @ B", 0.10, 70), _falso("C @ D", 0.05, 68)]
    antes = {b["matchup"]: (b["prob_model"], b["odds"], b["ev"]) for b in previos}

    juntos = main.rank_bets(previos + [_falso("E @ F", 0.50, 90)])

    assert len(juntos) == 3
    assert juntos[0]["matchup"] == "E @ F", "el nuevo entra por EV, no al final"
    for b in juntos:
        if b["matchup"] in antes:
            assert (b["prob_model"], b["odds"], b["ev"]) == antes[b["matchup"]]


def test_rank_bets_con_lista_vacia():
    assert main.rank_bets([]) == []
