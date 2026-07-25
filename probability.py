from pydantic import BaseModel

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
        home_score = (1 / matchup.home_pitcher.xera) + (matchup.home_pitcher.k_pct - matchup.home_pitcher.bb_pct)
        away_score = (1 / matchup.away_pitcher.xera) + (matchup.away_pitcher.k_pct - matchup.away_pitcher.bb_pct)
        
        home_score *= 1.05  # Ventaja de localía
        total = home_score + away_score
        return round(home_score / total, 4)
