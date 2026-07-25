from schemas import EngineInput, DecisionResult

class DecisionEngine:
    def __init__(
        self,
        min_ev: float = 0.05,
        min_confidence: float = 0.75,
        min_data_quality: float = 0.80,
        kelly_fraction: float = 0.25
    ):
        self.min_ev = min_ev
        self.min_confidence = min_confidence
        self.min_data_quality = min_data_quality
        self.kelly_fraction = kelly_fraction

    def evaluate(self, input_data: EngineInput) -> DecisionResult:
        if not input_data.pitcher_confirmed:
            return self._build_rejection(input_data, 0.0, 0.0, "Pitcher no confirmado.")
        
        ev = (input_data.p_model * input_data.decimal_odds) - 1.0

        b = input_data.decimal_odds - 1.0
        p = input_data.p_model
        q = 1.0 - p
        raw_kelly = (b * p - q) / b if b > 0 else 0.0

        if raw_kelly <= 0:
            return self._build_rejection(input_data, ev, raw_kelly, "Esperanza matematica nula o negativa.")

        adjusted_stake = (
            raw_kelly 
            * self.kelly_fraction 
            * input_data.confidence_score 
            * input_data.data_quality_score
        )

        if ev < self.min_ev:
            return self._build_rejection(input_data, ev, raw_kelly, f"EV ({ev:.2%}) bajo el umbral minimo ({self.min_ev:.2%}).")

        if input_data.confidence_score < self.min_confidence:
            return self._build_rejection(input_data, ev, raw_kelly, f"Confianza ({input_data.confidence_score:.2%}) insuficiente.")

        if input_data.data_quality_score < self.min_data_quality:
            return self._build_rejection(input_data, ev, raw_kelly, f"Calidad de datos ({input_data.data_quality_score:.2%}) insuficiente.")

        return DecisionResult(
            game_id=input_data.game_id,
            market=input_data.market,
            selection=input_data.selection,
            status="APPROVED",
            ev=round(ev, 4),
            raw_kelly=round(raw_kelly, 4),
            adjusted_stake_pct=round(adjusted_stake, 4),
            reason="Apuesta aprobada: Cumple con ventaja matematica y calidad de datos."
        )

    def _build_rejection(self, input_data: EngineInput, ev: float, raw_kelly: float, reason: str) -> DecisionResult:
        return DecisionResult(
            game_id=input_data.game_id,
            market=input_data.market,
            selection=input_data.selection,
            status="REJECTED",
            ev=round(ev, 4),
            raw_kelly=round(raw_kelly, 4),
            adjusted_stake_pct=0.0,
            reason=f"RECHAZADO: {reason}"
        )
