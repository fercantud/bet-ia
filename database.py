import sqlite3
from datetime import datetime

class PerformanceTracker:
    def __init__(self, db_name="bet_ia_performance.db"):
        self.db_name = db_name
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bet_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                matchup TEXT,
                selection TEXT,
                model_prob REAL,
                market_prob REAL,
                edge REAL,
                odds REAL,
                closing_odds REAL,
                ev REAL,
                kelly_stake REAL,
                model_confidence REAL,
                attribution_json TEXT,
                result TEXT DEFAULT 'PENDING',
                profit_loss REAL DEFAULT 0.0
            )
        ''')
        conn.commit()
        conn.close()

    def record_bet(self, bet_data: dict):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO bet_history (
                date, matchup, selection, model_prob, market_prob, edge, odds,
                ev, kelly_stake, model_confidence, attribution_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            bet_data['matchup'],
            bet_data['selection'],
            bet_data['model_prob'],
            bet_data['market_prob'],
            bet_data['edge'],
            bet_data['odds'],
            bet_data['ev'],
            bet_data['kelly_stake'],
            bet_data['model_confidence'],
            str(bet_data['attribution'])
        ))
        conn.commit()
        conn.close()
