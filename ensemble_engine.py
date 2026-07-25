class EnsembleEngine:
    def __init__(self):
        # Pesos institucionales del modelo Ensemble
        self.weights = {
            "pitching": 0.35,
            "offense": 0.25,
            "bullpen": 0.15,
            "park_weather": 0.15,
            "market_signals": 0.10
        }

    def evaluate_matchup(self, p_pitching: float, p_offense: float, p_bullpen: float, p_weather: float, p_market: float) -> dict:
        """
        Calcula la probabilidad Ensemble ponderada combinando sub-modelos independientes.
        """
        p_ensemble = (
            (p_pitching * self.weights["pitching"]) +
            (p_offense * self.weights["offense"]) +
            (p_bullpen * self.weights["bullpen"]) +
            (p_weather * self.weights["park_weather"]) +
            (p_market * self.weights["market_signals"])
        )

        # Explainability Engine (SHAP-style Feature Importance Attribution)
        # Calcula la contribución porcentual de cada modelo a la desviación sobre la media (0.50)
        base_line = 0.50
        diff_p = p_pitching - base_line
        diff_o = p_offense - base_line
        diff_b = p_bullpen - base_line
        diff_w = p_weather - base_line
        diff_m = p_market - base_line

        total_abs_diff = max(0.001, (abs(diff_p)*0.35 + abs(diff_o)*0.25 + abs(diff_b)*0.15 + abs(diff_w)*0.15 + abs(diff_m)*0.10))

        attr_pitching = round((abs(diff_p) * 0.35 / total_abs_diff) * 100, 1)
        attr_offense = round((abs(diff_o) * 0.25 / total_abs_diff) * 100, 1)
        attr_bullpen = round((abs(diff_b) * 0.15 / total_abs_diff) * 100, 1)
        attr_weather = round((abs(diff_w) * 0.15 / total_abs_diff) * 100, 1)
        attr_market = round((abs(diff_m) * 0.10 / total_abs_diff) * 100, 1)

        return {
            "p_ensemble": round(p_ensemble, 4),
            "shap_attribution": {
                "Pitching Model": f"{attr_pitching}%",
                "Offense Model": f"{attr_offense}%",
                "Bullpen Model": f"{attr_bullpen}%",
                "Park/Weather": f"{attr_weather}%",
                "Market Model": f"{attr_market}%"
            }
        }

class RiskEngine:
    @staticmethod
    def assess_risk(dqi_score: int, wind_speed: float, bullpen_usage_high: bool, edge: float) -> dict:
        """
        Evalúa el perfil de riesgo del pick (BAJO, MEDIO, ALTO).
        """
        risk_score = 0
        reasons = []

        if dqi_score < 85:
            risk_score += 2
            reasons.append("Data Quality incompleta (<85)")
        if wind_speed > 25:
            risk_score += 2
            reasons.append("Alta volatilidad por viento fuerte (>25 km/h)")
        if bullpen_usage_high:
            risk_score += 1
            reasons.append("Bullpen fatigado (alto uso reciente)")
        if edge > 0.12:
            risk_score += 2
            reasons.append("Edge atípicamente alto (>12%)")

        if risk_score == 0:
            rating = "BAJO"
        elif risk_score <= 2:
            rating = "MEDIO"
        else:
            rating = "ALTO"

        return {
            "risk_rating": rating,
            "risk_score": risk_score,
            "risk_factors": reasons if reasons else ["Condiciones estables de baja varianza"]
        }
