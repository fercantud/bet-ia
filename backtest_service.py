import numpy as np

class BacktestEngine:
    def __init__(self, initial_bankroll: float = 10000.0):
        self.initial_bankroll = initial_bankroll

    def run_backtest(self, historical_picks: list) -> dict:
        bankroll = self.initial_bankroll
        peak_bankroll = bankroll
        max_drawdown = 0.0
        
        total_wagered = 0.0
        total_profit = 0.0
        wins = 0
        clv_acc = []

        for pick in historical_picks:
            stake = bankroll * pick['stake_pct']
            odds = pick['taken_odds']
            closing_odds = pick['closing_odds']
            won = pick['won']

            implied_taken = 1.0 / odds
            implied_closing = 1.0 / closing_odds
            clv_pct = (implied_closing - implied_taken) / implied_taken
            clv_acc.append(clv_pct)

            total_wagered += stake

            if won:
                profit = stake * (odds - 1.0)
                wins += 1
            else:
                profit = -stake

            total_profit += profit
            bankroll += profit

            if bankroll > peak_bankroll:
                peak_bankroll = bankroll
            dd = (peak_bankroll - bankroll) / peak_bankroll
            if dd > max_drawdown:
                max_drawdown = dd

        total_picks = len(historical_picks)
        win_rate = wins / total_picks if total_picks > 0 else 0.0
        roi = (total_profit / self.initial_bankroll) * 100
        yield_pct = (total_profit / total_wagered) * 100 if total_wagered > 0 else 0.0
        avg_clv = float(np.mean(clv_acc)) * 100 if clv_acc else 0.0

        # Guardrail de Muestra Estadística
        sample_warning = total_picks < 100

        return {
            "total_picks": total_picks,
            "win_rate": round(win_rate * 100, 2),
            "initial_bankroll": round(self.initial_bankroll, 2),
            "final_bankroll": round(bankroll, 2),
            "total_profit": round(total_profit, 2),
            "roi": round(roi, 2),
            "yield": round(yield_pct, 2),
            "max_drawdown": round(max_drawdown * 100, 2),
            "avg_clv": round(avg_clv, 2),
            "sample_warning": sample_warning
        }
