"""Motor de tenis: encuentra el PICK MAS SEGURO del dia (mayor probabilidad).

A diferencia de MLB (un juego topa ~62-72%), en tenis un favoritazo llega a
85-92%+ de forma normal, asi que los niveles de seguridad se calibran mas altos y
el 'Bloqueo Total' (90%+) si es alcanzable.

Probabilidad del MVP = mercado de-vig (estimador mas fino disponible sin una API
de stats de jugadores). Un Elo por superficie se puede sumar despues.
"""
from tennis_api import get_today_matches

# Umbral de "pick seguro" en tenis (mas alto que MLB porque los favoritos lo son).
SAFE_THRESHOLD_TENNIS = 0.72


def nivel_tenis(p):
    """Prob. real -> nivel de seguridad (calibrado a TENIS) e icono."""
    if p >= 0.90:
        return ("BLOQUEO TOTAL", "🔒")
    if p >= 0.82:
        return ("MUY SEGURO", "🟢")
    if p >= 0.72:
        return ("SEGURO", "🟢")
    if p >= 0.64:
        return ("ACEPTABLE", "🟡")
    return ("NO SEGURO", "⚪")


def _devig(home_odds, away_odds):
    ph, pa = 1.0 / home_odds, 1.0 / away_odds
    return ph / (ph + pa)


def get_tennis_picks():
    """Construye y ordena los picks de tenis del dia (mas seguro primero)."""
    bets = []
    for m in get_today_matches():
        try:
            ho, ao = float(m["home_odds"]), float(m["away_odds"])
            p_home = _devig(ho, ao)
            fav_home = p_home >= 0.5
            fav = m["home"] if fav_home else m["away"]
            rival = m["away"] if fav_home else m["home"]
            safety = round(max(p_home, 1.0 - p_home), 4)
            odds = ho if fav_home else ao
            bets.append({
                "matchup": f'{fav} vs {rival}',
                "market": "Ganador",
                "selection": fav,
                "rival": rival,
                "odds": round(odds, 2),
                "safety": safety,
                "prob_model": safety,
                "prob_market": round(1.0 / odds, 4),
                "tournament": m.get("tournament", ""),
                "surface": m.get("surface", "Dura"),
                "odds_real": not m.get("demo", False),
            })
        except Exception:
            continue
    return rank_tennis(bets)


def rank_tennis(bets):
    bets = sorted(bets, key=lambda b: b["safety"], reverse=True)
    for i, b in enumerate(bets, 1):
        b["rank"] = i
        p = b["safety"]
        nombre, icono = nivel_tenis(p)
        b["conf_nivel"] = nombre
        b["conf_pct"] = round(p * 100, 1)
        b["tag"] = f"{icono} {nombre}"
        # Stake por nivel de seguridad (mismo criterio que MLB: mas seguro = mas stake)
        if p >= 0.90:
            b["stake"] = "30%"
        elif p >= 0.82:
            b["stake"] = "20%"
        elif p >= 0.72:
            b["stake"] = "10%"
        elif p >= 0.64:
            b["stake"] = "5%"
        else:
            b["stake"] = "0%"
        b["approved"] = p >= SAFE_THRESHOLD_TENNIS
    return bets
