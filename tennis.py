"""Selección de picks seguros de tenis — la PROBABILIDAD sale del ANÁLISIS.

Regla #1: PROHIBIDO ordenar por momio. El ranking se construye con el análisis
deportivo (Elo + forma + superficie + saque + devolución + H2H + fatiga, ver
tennis_model). El momio se usa SOLO al final para EV, VALUE y SOBREVALORADO.
"""
import difflib
import unicodedata
import tennis_model
from tennis_api import get_today_matches

# Umbral de "pick seguro" (nuevo esquema): SEGURO desde 85%.
SAFE_THRESHOLD_TENNIS = 0.85

_DBS = {}


def _db(tour):
    if tour not in _DBS:
        _DBS[tour] = tennis_model.PlayerDB(tour)
    return _DBS[tour]


def nivel_tenis(p):
    """Prob. del ANÁLISIS -> nivel de confianza (esquema del spec)."""
    pct = p * 100
    if pct >= 98:
        return ("BLOQUEO ABSOLUTO", "🟢")
    if pct >= 95:
        return ("BLOQUEO TOTAL", "🟢")
    if pct >= 90:
        return ("MUY SEGURO", "🟢")
    if pct >= 85:
        return ("SEGURO", "🟡")
    if pct >= 80:
        return ("ACEPTABLE", "🟠")
    if pct >= 75:
        return ("RIESGOSO", "🔴")
    return ("NO RECOMENDADO", "❌")


def _norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()


def _find_player(db, name):
    """Resuelve `name` (tal como llega del feed de momios) a la clave real que
    usa el dataset de historial. Intenta, en orden, exacto -> normalizado ->
    apellido unico -> apellido + inicial de nombre -> el mas jugado entre los
    que comparten apellido -> similitud difusa del nombre completo. Devuelve
    None solo si de verdad no hay ningun candidato razonable (jugador sin
    historial en el dataset, p.ej. debut o qualy)."""
    if name in db.log:
        return name
    nn = _norm(name)
    if not nn:
        return None
    for k in db.log:
        if _norm(k) == nn:
            return k
    partes = nn.split()
    ln = partes[-1] if partes else ""
    fi = partes[0][0] if partes else ""
    cands = [k for k in db.log if _norm(k).split()[-1:] == [ln]] if ln else []
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        mismo_inicial = [k for k in cands if _norm(k).split()[:1] == [fi] or
                          (_norm(k).split() and _norm(k).split()[0][:1] == fi)]
        pool = mismo_inicial or cands
        # desempate: el jugador con mas historial es el mas probable (tour actual)
        return max(pool, key=lambda k: len(db.log[k]))
    cercanos = difflib.get_close_matches(nn, [_norm(k) for k in db.log], n=1, cutoff=0.84)
    if cercanos:
        objetivo = cercanos[0]
        for k in db.log:
            if _norm(k) == objetivo:
                return k
    return None


def _devig_home(ho, ao):
    ph, pa = 1.0 / ho, 1.0 / ao
    return ph / (ph + pa)


def get_tennis_picks():
    picks = []
    for m in get_today_matches():
        try:
            picks.append(_pick(m))
        except Exception:
            continue
    return rank_tennis([p for p in picks if p])


def _pick(m):
    db = _db(m.get("tour", "atp"))
    surface = (m.get("surface") or "Hard").title()
    ho, ao = float(m["home_odds"]), float(m["away_odds"])
    pa = _find_player(db, m["home"])
    pb = _find_player(db, m["away"])
    # Si no se resuelve el nombre, se usa tal cual llego del feed: PlayerDB
    # trata a un nombre sin historial como jugador promedio del circuito
    # (Elo 1500, forma/superficie/saque/devolucion neutrales) en vez de
    # abortar el analisis. analizar() ya atenua la confianza cuando falta
    # historial de alguno de los dos (ver tennis_model.analizar).
    home_pl, away_pl = pa or m["home"], pb or m["away"]

    rh = tennis_model.analizar(db, home_pl, away_pl, surface)   # prob de HOME
    if rh["prob"] >= 0.5:
        fav_side, fav, riv, odds = "home", m["home"], m["away"], ho
        prob, fac, cobertura = rh["prob"], rh["factores"], rh["cobertura"]
        fav_pl, riv_pl = home_pl, away_pl
    else:
        ra = tennis_model.analizar(db, away_pl, home_pl, surface)
        fav_side, fav, riv, odds = "away", m["away"], m["home"], ao
        prob, fac, cobertura = ra["prob"], ra["factores"], ra["cobertura"]
        fav_pl, riv_pl = away_pl, home_pl
    fatiga = round(db.fatiga(fav_pl), 2)
    _, n_h2h = db.h2h_rate(fav_pl, riv_pl)
    datos_reales = rh["datos_reales"]
    # "Sin datos" real solo cuando NINGUNO de los dos jugadores tiene
    # historial (no hay ninguna senal deportiva, ni siquiera parcial).
    sin_datos = cobertura == "sin_datos"

    # --- El momio SOLO aquí: EV, VALUE y SOBREVALORADO ---
    p_home_mkt = _devig_home(ho, ao)
    p_mkt = p_home_mkt if fav_side == "home" else (1 - p_home_mkt)
    ev = round(prob * odds - 1.0, 4)
    if sin_datos:
        valor = "SIN DATOS"
    elif prob - p_mkt >= 0.04:
        valor = "VALUE"
    elif p_mkt - prob >= 0.06:
        valor = "SOBREVALORADO"
    else:
        valor = "JUSTO"

    return {
        "tour": m.get("tour", "atp").upper(),
        "tournament": m.get("tournament", ""),
        "surface": surface,
        "matchup": f"{fav} vs {riv}",
        "market": "Ganador",
        "selection": fav, "rival": riv,
        "odds": round(odds, 2),
        "safety": round(prob, 4),          # RANKING = probabilidad del análisis
        "prob_ia": round(prob, 4),
        "prob_mkt": round(p_mkt, 4),
        "ev": ev, "valor": valor,
        "forma": fac.get("forma"), "hard": fac.get("superficie"),
        "h2h": fac.get("h2h"), "elo_hard": fac.get("elo"),
        "saque": fac.get("saque"), "devolucion": fac.get("devolucion"),
        "fatiga": fatiga, "h2h_n": n_h2h,
        "lesiones": "N/D",                 # sin fuente libre (manual)
        "sin_datos": sin_datos,
        "cobertura": cobertura,            # completa | parcial | sin_datos
        "datos_reales": datos_reales,
    }


def rank_tennis(bets):
    # ORDEN por probabilidad del ANÁLISIS (no por momio).
    bets = sorted(bets, key=lambda b: b["safety"], reverse=True)
    for i, b in enumerate(bets, 1):
        b["rank"] = i
        p = b["safety"]
        nombre, icono = nivel_tenis(p)
        # Sobrevalorado: aunque la prob sea alta, si el momio la infla, se marca.
        if b["valor"] == "SOBREVALORADO":
            b["tag"] = f"⚠️ {nombre} · sobrevalorado"
        elif b["valor"] == "VALUE":
            b["tag"] = f"🔥 {nombre} · VALUE"
        else:
            b["tag"] = f"{icono} {nombre}"
        b["conf_nivel"] = nombre
        b["conf_pct"] = round(p * 100, 1)
        if p >= 0.95:
            b["stake"] = "30%"
        elif p >= 0.90:
            b["stake"] = "20%"
        elif p >= 0.85:
            b["stake"] = "10%"
        elif p >= 0.80:
            b["stake"] = "5%"
        else:
            b["stake"] = "0%"
        b["approved"] = p >= SAFE_THRESHOLD_TENNIS and b["valor"] != "SIN DATOS"
    return bets
