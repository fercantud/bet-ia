import os
import requests

# API key de The Odds API.
# NUNCA se escribe en el código: se lee de la variable de entorno ODDS_API_KEY
# (en local, desde .streamlit/secrets.toml; en Streamlit Cloud, desde "Secrets").
# Si no hay key, el sistema sigue funcionando con cuotas estimadas.


class OddsDataFetcher:
    def __init__(self, api_key: str = None, sport: str = "baseball_mlb"):
        # `sport` permite reutilizar el mismo lector para otras ligas que
        # The Odds API publique. Por defecto sigue siendo MLB.
        self.api_key = api_key or os.getenv("ODDS_API_KEY", "")
        self.sport = sport
        self.base_url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"

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

                home_ml, away_ml = [], []
                # Totales agrupados POR LINEA. No se promedian las lineas: cada casa
                # ofrece escalones fijos (7, 7.5, 8, 8.5, 9, 9.5, 10) y promediarlos
                # produce valores inexistentes (9.8, 8.6...) que no se pueden apostar.
                por_linea = {}

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
                                punto = o.get("point")
                                if punto is None:
                                    continue
                                d = por_linea.setdefault(float(punto), {"over": [], "under": []})
                                if o.get("name") == "Over":
                                    d["over"].append(o["price"])
                                elif o.get("name") == "Under":
                                    d["under"].append(o["price"])

                if not (home_ml and away_ml):
                    continue

                entry = {
                    "home_odds": round(sum(home_ml) / len(home_ml), 2),
                    "away_odds": round(sum(away_ml) / len(away_ml), 2),
                }

                # Se toma la linea MAS OFRECIDA (la moda) y, con ella, solo las cuotas
                # de las casas que realmente la ofrecen. Empates: gana la linea menor.
                validas = {ln: d for ln, d in por_linea.items() if d["over"] and d["under"]}
                if validas:
                    linea = sorted(validas, key=lambda ln: (-len(validas[ln]["over"]), ln))[0]
                    d = validas[linea]
                    entry["over_odds"] = round(sum(d["over"]) / len(d["over"]), 2)
                    entry["under_odds"] = round(sum(d["under"]) / len(d["under"]), 2)
                    entry["total_line"] = linea
                    entry["line_books"] = len(d["over"])          # casas que la ofrecen
                    entry["line_total_books"] = sum(len(x["over"]) for x in validas.values())

                odds_dict[f"{away_team} @ {home_team}"] = entry

            return odds_dict
        except Exception:
            return {}
