import pytest
from schemas import EngineInput, BetMarket
from engine import DecisionEngine

@pytest.fixture
def engine():
    return DecisionEngine()

def test_approve_valid_bet(engine):
    input_data = EngineInput(
        game_id="NYY_BOS_01",
        market=BetMarket.MONEYLINE_HOME,
        selection="NY Yankees",
        decimal_odds=1.95,
        p_model=0.62,
        confidence_score=0.90,
        data_quality_score=0.95,
        lineup_confirmed=True,
        pitcher_confirmed=True
    )
    result = engine.evaluate(input_data)
    assert result.status == "APPROVED"
    assert result.ev > 0.10

def test_reject_unconfirmed_pitcher(engine):
    input_data = EngineInput(
        game_id="NYY_BOS_01",
        market=BetMarket.MONEYLINE_HOME,
        selection="NY Yankees",
        decimal_odds=2.10,
        p_model=0.60,
        confidence_score=0.90,
        data_quality_score=0.95,
        lineup_confirmed=True,
        pitcher_confirmed=False
    )
    result = engine.evaluate(input_data)
    assert result.status == "REJECTED"
    assert "Pitcher no confirmado" in result.reason
