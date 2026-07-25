class MarketService:
    @staticmethod
    def analyze_market(opening_odds: float, current_odds: float, public_bet_pct: float = 0.50) -> dict:
        implied_open = 1.0 / opening_odds if opening_odds > 0 else 0.5
        implied_curr = 1.0 / current_odds if current_odds > 0 else 0.5
        line_shift = implied_curr - implied_open

        # Reverse Line Movement: público apuesta masivamente un lado pero la línea se mueve al otro
        rlm = False
        if public_bet_pct >= 0.60 and line_shift < -0.02:
            rlm = True
        elif public_bet_pct <= 0.40 and line_shift > 0.02:
            rlm = True

        steam_move = abs(line_shift) >= 0.03

        return {
            "opening_odds": opening_odds,
            "current_odds": current_odds,
            "line_shift_pct": round(line_shift, 4),
            "reverse_line_movement": rlm,
            "steam_move": steam_move
        }
