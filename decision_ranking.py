import numpy as np
from scipy.stats import poisson

class RankingEngine:
    @staticmethod
    def calculate_exact_scores(exp_home, exp_away, home_team, away_team):
        score_matrix = []
        for h in range(7):
            for a in range(7):
                prob = poisson.pmf(h, exp_home) * poisson.pmf(a, exp_away)
                score_matrix.append({
                    "score": f"{home_team} {h}-{a} {away_team}",
                    "h_runs": h,
                    "a_runs": a,
                    "prob": prob
                })
        score_matrix.sort(key=lambda x: x['prob'], reverse=True)
        return score_matrix[:3]

    @staticmethod
    def evaluate_all_markets(game, p_home_model, odds_dict, exp_home, exp_away, total_line=8.5):
        # total_line: linea REAL de la casa (7.5, 9.0, 10.5...). Antes se asumia
        # siempre 8.5, lo que evaluaba mal casi todos los totales. La formula es
        # la misma; solo se corrige el dato de entrada.
        ml_odds = odds_dict.get('ml_odds', 1.85)
        over_odds = odds_dict.get('over_odds', 1.90)
        under_odds = odds_dict.get('under_odds', 1.90)
        f5_odds = odds_dict.get('f5_odds', 1.75)

        implied_ml = 1.0 / ml_odds
        implied_over = 1.0 / over_odds
        implied_under = 1.0 / under_odds
        implied_f5 = 1.0 / f5_odds

        p_ml = p_home_model
        total_exp = exp_home + exp_away
        p_under = round(0.50 + (total_line - total_exp) * 0.03, 3)
        p_under = min(0.68, max(0.42, p_under))
        p_f5 = round(p_ml + 0.01, 3)

        markets = [
            {
                "market": "Moneyline",
                "selection": f"✅ {game['home_team']} ML" if p_ml >= 0.50 else f"✅ {game['away_team']} ML",
                "prob": round(max(p_ml, 1.0 - p_ml), 4),
                "odds": ml_odds,
                "edge": round(max(p_ml, 1.0 - p_ml) - implied_ml, 4)
            },
            {
                "market": "Total",
                "selection": (f"Under {total_line:g}" if total_exp < total_line else f"Over {total_line:g}"),
                "prob": round(p_under if total_exp < total_line else (1.0 - p_under + 0.1), 4),
                "odds": under_odds if total_exp < total_line else over_odds,
                "edge": round((p_under if total_exp < total_line else (1.0 - p_under + 0.1)) - (implied_under if total_exp < total_line else implied_over), 4)
            },
            {
                "market": "F5",
                "selection": f"{game['home_team']} F5 ML" if p_f5 >= 0.50 else f"{game['away_team']} F5 ML",
                "prob": round(max(p_f5, 1.0 - p_f5), 4),
                "odds": f5_odds,
                "edge": round(max(p_f5, 1.0 - p_f5) - implied_f5, 4)
            }
        ]

        best_market = max(markets, key=lambda x: x['edge'])
        exact_scores = RankingEngine.calculate_exact_scores(exp_home, exp_away, game['home_team'], game['away_team'])

        return best_market, markets, exact_scores

    @staticmethod
    def calculate_bet_ia_total_score(pitching_v, bullpen_v, offense_v, market_v, park_v, form_v):
        total = (pitching_v * 0.25) + (bullpen_v * 0.20) + (offense_v * 0.20) + (market_v * 0.15) + (park_v * 0.10) + (form_v * 0.10)
        score = round(min(100.0, max(0.0, total)), 1)
        confidence = round(min(10.0, max(1.0, score / 10.0)), 1)
        return score, confidence
