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

# Set de demostracion (fallback). Usa jugadores que el motor conoce (mismos del
# set sintetico) para que el analisis se vea diferenciado incluso sin red.
# (tour, torneo, superficie, home, away, home_odds, away_odds)
DEMO_MATCHES = [
    ("wta", "WTA Canadian Open", "Hard", "Iga Swiatek", "Viktorija Golubic", 1.06, 8.00),
    ("wta", "WTA Canadian Open", "Hard", "Aryna Sabalenka", "Shuai Zhang", 1.11, 6.20),
    ("wta", "WTA Canadian Open", "Hard", "Naomi Osaka", "Iga Swiatek", 4.50, 1.18),
    ("atp", "ATP Masters 1000", "Hard", "Carlos Alcaraz", "Alexei Popyrin", 1.12, 5.50),
    ("atp", "ATP Masters 1000", "Hard", "Jannik Sinner", "Sebastian Baez", 1.15, 4.80),
    ("atp", "ATP 250", "Clay", "Daniil Medvedev", "Sebastian Baez", 1.70, 2.10),
]


def _api_key():
    return os.getenv("ODDS_API_KEY", "")


def _demo():
    return [{"tour": to, "tournament": t, "surface": s, "home": h, "away": a,
             "home_odds": ho, "away_odds": ao, "demo": True}
            for (to, t, s, h, a, ho, ao) in DEMO_MATCHES]


def _surface_from_key(sk: str) -> str:
    # Ingles (Hard/Clay/Grass) para cuadrar con Sackmann; la UI lo puede traducir.
    s = sk.lower()
    if any(x in s for x in ("french", "roland", "clay", "madrid", "rome", "monte", "hamburg")):
        return "Clay"
    if any(x in s for x in ("wimbledon", "grass", "queens", "halle", "eastbourne")):
        return "Grass"
    return "Hard"


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
                        "tour": "wta" if "wta" in sk.lower() else "atp",
                        "tournament": sk.replace("tennis_", "").replace("_", " ").title(),
                        "surface": _surface_from_key(sk),
                        "home": home, "away": away,
                        # MEJOR cuota disponible (la mas alta = mejor pago), no el
                        # promedio: es la que realmente conseguirias al apostar, y
                        # la correcta para calcular el EV.
                        "home_odds": round(max(h_odds), 2),
                        "away_odds": round(max(a_odds), 2),
                        "books": max(len(h_odds), len(a_odds)),
                        "demo": False,
                    })
        return matches or _demo()
    except Exception:
        return _demo()
