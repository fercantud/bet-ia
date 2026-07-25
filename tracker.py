import csv
import os
from datetime import datetime

class BetIATracker:
    FILE_NAME = "bet_ia_audit_tracker.csv"

    @classmethod
    def initialize_tracker(cls):
        if not os.path.exists(cls.FILE_NAME):
            with open(cls.FILE_NAME, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Fecha", "Matchup", "Mercado", "Seleccion", 
                    "Cuota_Entrada", "Cuota_Cierre", "CLV_Status", 
                    "Resultado", "ROI_Parcial", "Banca_Actual"
                ])

    @classmethod
    def log_bet(cls, matchup, market, selection, entry_odds, closing_odds, result, profit_loss, current_bankroll):
        cls.initialize_tracker()
        
        # Cálculo de Closing Line Value (CLV)
        # Si la cuota de entrada es mayor o igual a la de cierre (ej. 1.55 vs 1.45), ganaste valor de mercado
        clv_beaten = entry_odds >= closing_odds
        clv_status = "🟩 Ganado (CLV+)" if clv_beaten else "🟥 Perdido (CLV-)"
        
        roi_parcial = (profit_loss / 1.0) * 100

        with open(cls.FILE_NAME, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d"),
                matchup,
                market,
                selection,
                f"{entry_odds:.2f}",
                f"{closing_odds:.2f}",
                clv_status,
                result,
                f"{roi_parcial:+.1f}%",
                f""
            ])
