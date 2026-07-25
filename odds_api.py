import os
import requests

# API key de The Odds API.
# NUNCA se escribe en el código: se lee de la variable de entorno ODDS_API_KEY
# (en local, desde .streamlit/secrets.toml; en Streamlit Cloud, desde "Secrets").
# Si no hay key, el sistema sigue funcionando con cuotas estimadas.


class OddsDataFetcher:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("ODDS_API_KEY", "")
        self.base_url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"

    def get_moneyline_odds(self) -> dict:
        if not self.api_key or self.api_key == "TU_API_KEY_AQUI":
            return {}

        params = {
            "apiKey": self.api_key,
            "regions": "us",              # solo US para gastar créditos mínimos
            "markets": "h2h,totals",      # moneyline + totales (over/under) REALES
            "oddsFormat": "decimal"
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=6)
            if response.status_code != 200:
                return {}

            data = response.json()
            odds_dict = {}

            for game in data:
                home_team = game.get("home_team")
                away_team = game.get("away_team")
                bookmakers = game.get("bookmakers", [])
                if not bookmakers:
                    continue

                home_ml, away_ml, over_ml, under_ml, lines = [], [], [], [], []

                for bm in bookmakers:
                    for market in bm.get("markets", []):
                        key = market.get("key")
                        if key == "h2h":
                            for o in market.get("outcomes", []):
                                if o["name"] == home_team:
                                    home_ml.append(o["price"])
                                elif o["name"] == away_team:
                                    away_ml.append(o["price"])
                        elif key == "totals":
                            for o in market.get("outcomes", []):
                                if o.get("name") == "Over":
                                    over_ml.append(o["price"])
                                    if o.get("point") is not None:
                                        lines.append(o["point"])
                                elif o.get("name") == "Under":
                                    under_ml.append(o["price"])

                if not (home_ml and away_ml):
                    continue

                entry = {
                    "home_odds": round(sum(home_ml) / len(home_ml), 2),
                    "away_odds": round(sum(away_ml) / len(away_ml), 2),
                }
                if over_ml and under_ml:
                    entry["over_odds"] = round(sum(over_ml) / len(over_ml), 2)
                    entry["under_odds"] = round(sum(under_ml) / len(under_ml), 2)
                    entry["total_line"] = round(sum(lines) / len(lines), 1) if lines else 8.5

                odds_dict[f"{away_team} @ {home_team}"] = entry

            return odds_dict
        except Exception:
            return {}
