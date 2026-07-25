from pydantic import BaseModel
from enum import Enum
from typing import List, Optional, Dict

class BetMarket(str, Enum):
    MONEYLINE_HOME = "MONEYLINE_HOME"
    MONEYLINE_AWAY = "MONEYLINE_AWAY"
    RUNLINE_HOME = "RUNLINE_HOME"
    RUNLINE_AWAY = "RUNLINE_AWAY"

class EngineInput(BaseModel):
    game_id: str
    market: BetMarket
    selection: str
    decimal_odds: float
    p_model: float
    confidence_score: float
    data_quality_score: float
    lineup_confirmed: bool = True
    pitcher_confirmed: bool = True

class AnalyzedGame(BaseModel):
    game_id: str
    matchup: str
    selection: str
    decimal_odds: float
    open_odds: float
    p_model: float
    market_prob: float
    edge: float
    ev: float
    dqi: int
    match_score: float
    star_rating: str
    tier_label: str
    rank: int = 0
    confidence: float
    kelly_stake: float
    risk_rating: str
    risk_factors: List[str]
    shap_attribution: Dict[str, str]
    key_reasons: List[str]
    recommendation_note: str
