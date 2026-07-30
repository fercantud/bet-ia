import math
from pydantic import BaseModel

LEAGUE_XERA = 4.20   # xERA promedio de un abridor MLB
HFA_LOGIT = 0.15     # ventaja de localia (~+3.5% sobre 50/50)

class PitcherStats(BaseModel):
    name: str
    era: float
    xera: float
    whip: float
    k_pct: float
    bb_pct: float

class MatchupInput(BaseModel):
    game_id: str
    home_pitcher: PitcherStats
    away_pitcher: PitcherStats

class ProbabilityEngine:
    def estimate_home_win_prob(self, matchup: MatchupInput) -> float:
        """Prob. de victoria local, calibrada y ACOTADA a [0.34, 0.66].

        Antes era un cociente 1/xERA que daba ~69% con un buen abridor: un duelo de
        pitchers NO decide un juego de beisbol (bullpen, 8 bateadores y varianza
        pesan igual). Ahora la diferencia de calidad de los abridores (xERA ya
        regresado a la media en mlb_api) se convierte en un empujon logistico
        acotado. El bono de comando K%-BB% se conserva pero pesa poco.
        """
        def prevencion(p: "PitcherStats") -> float:
            # carreras prevenidas vs la liga + pequeño bono de comando (centrado en 10%)
            return (LEAGUE_XERA - p.xera) + 2.0 * ((p.k_pct - p.bb_pct) - 0.10)

        diff = prevencion(matchup.home_pitcher) - prevencion(matchup.away_pitcher)
        logit = 0.45 * diff + HFA_LOGIT
        p = 1.0 / (1.0 + math.exp(-logit))
        return round(min(0.66, max(0.34, p)), 4)
