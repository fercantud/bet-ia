import pytest
from pydantic import BaseModel

class PitcherStats(BaseModel):
    name: str
    era: float
    xera: float
    whip: float
    k_pct: float      # % de Strikeouts (0.25 = 25%)
    bb_pct: float     # % de Bases por bola (0.08 = 8%)

class MatchupInput(BaseModel):
    home_pitcher: PitcherStats
    away_pitcher: PitcherStats

class ProbabilityEngine:
    def estimate_win_probability(self, matchup: MatchupInput) -> float:
        # Algoritmo simplificado basado en xERA y K-BB%
        home_score = (1 / matchup.home_pitcher.xera) + (matchup.home_pitcher.k_pct - matchup.home_pitcher.bb_pct)
        away_score = (1 / matchup.away_pitcher.xera) + (matchup.away_pitcher.k_pct - matchup.away_pitcher.bb_pct)
        
        # Le damos un pequeño plus (+5%) al equipo local por ventaja de localía
        home_score *= 1.05

        total = home_score + away_score
        return round(home_score / total, 4)

# --- TESTS ---

def test_superior_home_pitcher():
    engine = ProbabilityEngine()
    
    # Pitcher de casa dominante (xERA bajo, alto K%)
    home = PitcherStats(name="Ace Home", era=2.80, xera=2.65, whip=0.98, k_pct=0.32, bb_pct=0.05)
    # Pitcher visitante promedio
    away = PitcherStats(name="Avg Away", era=4.20, xera=4.50, whip=1.30, k_pct=0.20, bb_pct=0.09)

    matchup = MatchupInput(home_pitcher=home, away_pitcher=away)
    p_home = engine.estimate_win_probability(matchup)

    # El pitcher de casa debería tener una probabilidad claramente superior al 50%
    assert p_home > 0.55
