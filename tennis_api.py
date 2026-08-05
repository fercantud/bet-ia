"""Fuente de partidos de tenis para BET IA.

Usa The Odds API (misma key que MLB, ODDS_API_KEY) para traer los partidos ATP/WTA
del dia con sus cuotas h2h (ganador del partido). Si no hay key o no hay torneos
activos, cae a un set de demostracion para que la pestana siempre muestre algo.

No hay una API oficial gratis de stats de jugadores; para el MVP la probabilidad
del pick sale del mercado de-vig (el estimador mas fino disponible). Un Elo por
superficie se puede sumar despues como senal independiente.
"""
import os
import requests

BASE = "https://api.the-odds-api.com/v4"

# Set de demostracion (fallback). Cuotas realistas de favoritos de distinto nivel.
DEMO_MATCHES = [
    ("ATP Masters 1000", "Dura", "Novak Djokovic", "Lorenzo Musetti", 1.14, 5.75),
    ("ATP Masters 1000", "Dura", "Carlos Alcaraz", "Frances Tiafoe", 1.20, 4.60),
    ("ATP 500", "Dura", "Jannik Sinner", "Karen Khachanov", 1.28, 3.80),
    ("ATP 500", "Arcilla", "Alexander Zverev", "Sebastian Baez", 1.45, 2.75),
    ("ATP 250", "Arcilla", "Casper Ruud", "Ugo Humbert", 1.62, 2.30),
    ("ATP 250", "Pasto", "Taylor Fritz", "Ben Shelton", 1.90, 1.90),
    ("Challenger", "Dura", "Tomas Machac", "Jakub Mensik", 2.15, 1.70),
    ("ATP 250", "Dura", "Daniil Medvedev", "Alexei Popyrin", 1.33, 3.40),
]


def _api_key():
    return os.getenv("ODDS_API_KEY", "")


def _demo():
    return [{"tournament": t, "surface": s, "home": h, "away": a,
             "home_odds": ho, "away_odds": ao, "demo": True}
            for (t, s, h, a, ho, ao) in DEMO_MATCHES]


def _surface_from_key(sk: str) -> str:
    s = sk.lower()
    if any(x in s for x in ("french", "roland", "clay", "madrid", "rome", "monte", "hamburg")):
        return "Arcilla"
    if any(x in s for x in ("wimbledon", "grass", "queens", "halle", "eastbourne")):
        return "Pasto"
    return "Dura"


def get_today_matches() -> list:
    """Partidos de tenis del dia con cuotas h2h. Cae a demo si no hay datos."""
    key = _api_key()
    if not key or key == "TU_API_KEY_AQUI":
        return _demo()
    try:
        sports = requests.get(f"{BASE}/sports/", params={"apiKey": key}, timeout=6).json()
        tenis_keys = [s["key"] for s in sports if isinstance(s, dict)
                      and str(s.get("key", "")).startswith("tennis_") and s.get("active")]
        matches = []
        for sk in tenis_keys[:8]:                 # limita el gasto de creditos
            data = requests.get(
                f"{BASE}/sports/{sk}/odds",
                params={"apiKey": key, "regions": "us", "markets": "h2h",
                        "oddsFormat": "decimal"}, timeout=6).json()
            if not isinstance(data, list):
                continue
            for gm in data:
                home, away = gm.get("home_team"), gm.get("away_team")
                h_odds, a_odds = [], []
                for bm in gm.get("bookmakers", []):
                    for mk in bm.get("markets", []):
                        if mk.get("key") != "h2h":
                            continue
                        for o in mk.get("outcomes", []):
                            if o.get("name") == home:
                                h_odds.append(o["price"])
                            elif o.get("name") == away:
                                a_odds.append(o["price"])
                if home and away and h_odds and a_odds:
                    matches.append({
                        "tournament": sk.replace("tennis_", "").replace("_", " ").title(),
                        "surface": _surface_from_key(sk),
                        "home": home, "away": away,
                        "home_odds": round(sum(h_odds) / len(h_odds), 2),
                        "away_odds": round(sum(a_odds) / len(a_odds), 2),
                        "demo": False,
                    })
        return matches or _demo()
    except Exception:
        return _demo()
