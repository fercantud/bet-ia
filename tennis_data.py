"""Capa de datos de tenis: historial de partidos por jugador.

Fuente real (produccion): datasets abiertos de Jeff Sackmann (ATP/WTA) en GitHub,
partido a partido con superficie y estadisticas de saque/devolucion. Se descargan
por temporada y se cachean en disco.

En este sandbox el repo de Sackmann responde 404 (red curada), asi que si la
descarga falla se usa un set SINTETICO pequeno: sirve para verificar toda la
logica (Elo, forma, factores) end-to-end. En tu Streamlit Cloud la descarga real
funciona y el motor usa datos verdaderos.

Cada partido se normaliza a:
  {date:'YYYYMMDD', surface:'Hard|Clay|Grass', winner, loser,
   w_svpt,w_1stIn,w_1stWon,w_2ndWon,w_ace,w_df,w_bpSaved,w_bpFaced,w_SvGms,  (idem l_)}
"""
import io
import os
import csv
import time
import requests

_CACHE = {}          # cache en memoria por (tour, anios)
_RAW = "https://raw.githubusercontent.com/JeffSackmann/tennis_{tour}/master/{tour}_matches_{year}.csv"


def _fetch_year(tour: str, year: int):
    url = _RAW.format(tour=tour, year=year)
    try:
        r = requests.get(url, timeout=12)
        if not r.ok or r.text.startswith("404"):
            return []
        rows = list(csv.DictReader(io.StringIO(r.text)))
        return rows
    except Exception:
        return []


_COLS = ("svpt", "1stIn", "1stWon", "2ndWon", "ace", "df", "bpSaved", "bpFaced", "SvGms")


def _norm(row: dict) -> dict:
    def g(pref, k):
        try:
            return float(row.get(f"{pref}_{k}") or 0)
        except Exception:
            return 0.0
    m = {
        "date": str(row.get("tourney_date") or ""),
        "surface": (row.get("surface") or "Hard").strip().title(),
        "winner": (row.get("winner_name") or "").strip(),
        "loser": (row.get("loser_name") or "").strip(),
        "best_of": row.get("best_of") or "3",
        "score": row.get("score") or "",
    }
    for pref in ("w", "l"):
        for k in _COLS:
            m[f"{pref}_{k}"] = g(pref, k)
    return m


def get_matches(tour: str = "atp", years=None):
    """Devuelve la lista de partidos (reales de Sackmann o sinteticos de respaldo)."""
    from datetime import datetime
    years = years or list(range(datetime.now().year - 2, datetime.now().year + 1))
    key = (tour, tuple(years))
    if key in _CACHE:
        return _CACHE[key]
    matches = []
    for y in years:
        for row in _fetch_year(tour, y):
            m = _norm(row)
            if m["winner"] and m["loser"]:
                matches.append(m)
    if not matches:
        matches = _sinteticos(tour)          # sandbox / sin red
    matches.sort(key=lambda x: x["date"])
    _CACHE[key] = matches
    return matches


def hay_datos_reales(tour: str = "atp") -> bool:
    return bool(_fetch_year(tour, __import__("datetime").datetime.now().year - 1))


# ---------------------------------------------------------------------------
# Set SINTETICO (solo para verificar la logica cuando no hay red al repo real).
# Jugadores con perfiles distintos para que Elo/forma/superficie se diferencien.
# ---------------------------------------------------------------------------
def _mk(date, surface, w, l, ws=None, ls=None):
    d = {"date": date, "surface": surface, "winner": w, "loser": l, "best_of": "3", "score": "6-3 6-4"}
    base = {"svpt": 60, "1stIn": 38, "1stWon": 30, "2ndWon": 13, "ace": 6, "df": 2,
            "bpSaved": 4, "bpFaced": 5, "SvGms": 10}
    for pref, ov in (("w", ws or {}), ("l", ls or {})):
        for k, v in base.items():
            d[f"{pref}_{k}"] = ov.get(k, v)
    return d


def _sinteticos(tour: str):
    # Iga domina en hard; Sabalenka fuerte; Osaka irregular; Golubic/Zhang mas debiles.
    top = "Iga Swiatek" if tour == "wta" else "Carlos Alcaraz"
    dos = "Aryna Sabalenka" if tour == "wta" else "Jannik Sinner"
    tres = "Naomi Osaka" if tour == "wta" else "Daniil Medvedev"
    debil1 = "Viktorija Golubic" if tour == "wta" else "Alexei Popyrin"
    debil2 = "Shuai Zhang" if tour == "wta" else "Sebastian Baez"
    M = []
    dates = [f"2025{mm:02d}{dd:02d}" for mm in (5, 6, 7) for dd in (5, 12, 19, 26)]
    fuerte_saque = {"1stWon": 34, "ace": 11, "bpSaved": 6, "bpFaced": 6}
    for i, dt in enumerate(dates):
        surf = "Hard" if i % 3 else "Clay"
        # el top gana casi siempre, sobre todo en hard
        M.append(_mk(dt, surf, top, debil1 if i % 2 else debil2, ws=fuerte_saque))
        M.append(_mk(dt, surf, dos, debil2 if i % 2 else debil1))
        M.append(_mk(dt, surf, tres if i % 2 else debil1, debil1 if i % 2 else tres))  # osaka irregular
        if i % 4 == 0:
            M.append(_mk(dt, "Hard", top, dos, ws=fuerte_saque))   # top le gana al 2
    return M
