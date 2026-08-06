"""Capa de datos de tenis: historial de partidos por jugador.

Fuente real (produccion): datasets abiertos estilo Jeff Sackmann (ATP/WTA),
partido a partido con superficie y estadisticas de saque/devolucion. Se
descargan por temporada y se cachean en memoria.

El repo original github.com/JeffSackmann/tennis_atp (y tennis_wta) dejo de
existir en esa cuenta (404 real, confirmado tambien via la API de GitHub: el
usuario ya no lo lista) asi que se prueban, en orden, varias fuentes con
EXACTAMENTE el mismo esquema de columnas; se usa la primera que responda. Si
ninguna responde (sin red) se usa un set SINTETICO pequeno: sirve para
verificar toda la logica (Elo, forma, factores) end-to-end, aunque con muy
pocos jugadores conocidos.

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
_HEADERS = {"User-Agent": "Mozilla/5.0 (bet-ia tennis data fetcher)"}

# Fuentes por tour, en orden de intento. La primera es el repo historico de
# Sackmann (se deja primero por si algun dia vuelve a existir); la segunda es
# un mirror activo con el mismo esquema de columnas que lo reemplaza hoy.
_SOURCES = {
    "atp": [
        "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_matches_{year}.csv",
        "https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/main/atp/atp_matches_{year}.csv",
    ],
    "wta": [
        "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/wta_matches_{year}.csv",
        "https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/main/wta/wta_matches_{year}.csv",
    ],
}


def _fetch_year(tour: str, year: int):
    for url_tpl in _SOURCES.get(tour, []):
        url = url_tpl.format(year=year)
        try:
            r = requests.get(url, timeout=12, headers=_HEADERS)
            if not r.ok or r.text.lstrip().startswith("404"):
                continue
            rows = list(csv.DictReader(io.StringIO(r.text)))
            if rows:
                return rows
        except Exception:
            continue
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


def _nkey(nombre: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower().strip()


# Bases de los mirrors que exponen players.csv y rankings_current.csv.
_ROSTER = [
    "https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/main/{tour}",
    "https://raw.githubusercontent.com/JeffSackmann/tennis_{tour}/master",
]


def get_rankings(tour: str = "atp") -> dict:
    """Ranking actual por jugador: {nombre_normalizado: rank}. Sirve de respaldo
    para estimar la fuerza de un jugador sin historial de partidos. Cacheado; {}
    si no hay red (entonces el motor usa solo el historial)."""
    key = ("rank", tour)
    if key in _CACHE:
        return _CACHE[key]
    out = {}
    for base_tpl in _ROSTER:
        base = base_tpl.format(tour=tour)
        try:
            pr = requests.get(f"{base}/{tour}_players.csv", timeout=15, headers=_HEADERS)
            rr = requests.get(f"{base}/{tour}_rankings_current.csv", timeout=20, headers=_HEADERS)
            if not (pr.ok and rr.ok):
                continue
            id2name = {}
            for row in csv.DictReader(io.StringIO(pr.text)):
                pid = row.get("player_id")
                nm = f"{row.get('name_first', '')} {row.get('name_last', '')}".strip()
                if pid and nm:
                    id2name[pid] = nm
            best = {}                      # player_id -> (ranking_date, rank)
            for row in csv.DictReader(io.StringIO(rr.text)):
                pid = row.get("player")
                try:
                    rank = int(row.get("rank") or 0)
                except Exception:
                    continue
                dt = row.get("ranking_date") or ""
                if pid and rank and (pid not in best or dt > best[pid][0]):
                    best[pid] = (dt, rank)
            for pid, (_dt, rank) in best.items():
                nm = id2name.get(pid)
                if nm:
                    out[_nkey(nm)] = rank
            if out:
                break
        except Exception:
            continue
    _CACHE[key] = out
    return out


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
