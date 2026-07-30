import json
import os
import sqlite3
from datetime import datetime, timedelta

import requests

# Zona horaria fija: sin esto, la app usa el reloj del servidor. En Streamlit Cloud
# ese reloj es UTC, asi que a las 18:00 de Mexico ya seria "manana" y la nube
# generaria una jornada distinta a la de tu PC. Con esto ambas ven el mismo dia.
APP_TZ = "America/Chicago"   # Hora Central (misma que tu equipo)
try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo(APP_TZ)
except Exception:
    _TZ = None


def now_local():
    """Fecha y hora en la zona horaria de la app (no la del servidor)."""
    return datetime.now(_TZ) if _TZ else datetime.now()

import pandas as pd
import streamlit as st

from main import get_analyzed_bets, rank_bets
from mlb_api import MLBDataFetcher

DB_NAME = "bet_ia_performance.db"          # BD antigua (solo para migrar una vez)
VERSION = "2.6.0"

# --- Ligas disponibles -------------------------------------------------------
# MLB conserva EXACTAMENTE sus archivos y su fuente de datos. LMB se agrega
# aparte, con su propio historial y su propio analisis; comparten el motor.
LIGAS = {
    "MLB": {
        "nombre": "MLB",
        "fuente": "mlb",
        "sport_id": 1, "league_id": None,
        "odds_sport": "baseball_mlb",
        "historial": "historial_apuestas.json",
        "analisis": "analisis_hoy.json",
        "cuotas_reales": True,
        "logo_id": 1,                          # logo de liga en mlbstatic
    },
    "LMB": {
        "nombre": "LMB",
        "fuente": "mlb",
        "sport_id": 23, "league_id": 125,      # Liga Mexicana de Beisbol
        "historial": "historial_apuestas_lmb.json",
        "analisis": "analisis_hoy_lmb.json",
        "cuotas_reales": False,                # sin mercado publicado: cuotas estimadas
        "odds_sport": None,
        "logo_id": 125,
    },
}
if "liga" not in st.session_state:
    st.session_state.liga = "MLB"
LIGA = LIGAS[st.session_state.liga]

HISTORY_FILE = LIGA["historial"]
ANALYSIS_CACHE = LIGA["analisis"]


def fecha_jornada(clave=None):
    """Fecha de la jornada de la liga. Normalmente es hoy, pero una liga puede
    declarar un desfase en `offset_dias` si juega de madrugada en hora Central."""
    cfg = LIGAS[clave or st.session_state.liga]
    return (now_local() + timedelta(days=cfg.get("offset_dias", 0))).strftime("%Y-%m-%d")


@st.cache_data(ttl=86400)
def stats_genericas_liga(clave):
    """Abridor 'promedio' de la liga, para partidos sin lanzador anunciado.

    El generico de siempre (ERA 4.15) esta calibrado para MLB, cuya ERA real de
    liga es 4.21. En la LMB, con ERA de liga 5.08, ese numero hacia que el modelo
    esperara 9.49 carreras por partido cuando la liga anota 10.34: casi una
    carrera menos, y en la mitad de los partidos porque los abridores rara vez
    se anuncian.

    MLB conserva sus constantes exactas (regla del proyecto: no se toca).
    """
    cfg = LIGAS[clave]
    if clave == "MLB" or cfg.get("fuente") != "mlb":
        return None                            # None => el fetcher usa el generico de MLB
    try:
        liga = f"&leagueId={cfg['league_id']}" if cfg.get("league_id") else ""
        url = (f"https://statsapi.mlb.com/api/v1/teams/stats?stats=season&group=pitching"
               f"&sportId={cfg['sport_id']}{liga}&season={now_local().year}")
        splits = requests.get(url, timeout=15).json().get("stats", [{}])[0].get("splits", [])
        eras = [float(s["stat"]["era"]) for s in splits
                if str(s.get("stat", {}).get("era", "")).replace(".", "").isdigit()]
        whips = [float(s["stat"]["whip"]) for s in splits
                 if str(s.get("stat", {}).get("whip", "")).replace(".", "").isdigit()]
        if len(eras) < 4:                      # muestra pobre: mejor el generico de siempre
            return None
        era = round(sum(eras) / len(eras), 2)
        return {"era": era, "xera": round(era * 0.95, 2),
                "whip": round(sum(whips) / len(whips), 2) if whips else 1.28,
                "k_pct": 0.22, "bb_pct": 0.08}
    except Exception:
        return None


def _crear_fetcher(clave):
    cfg = LIGAS[clave]
    fetcher = MLBDataFetcher(sport_id=cfg["sport_id"], league_id=cfg["league_id"])
    # El generico se asigna DESPUES de construir, no como argumento. Streamlit
    # relanza app.py cuando cambia, pero reutiliza los modulos ya importados: si
    # aqui se pasara stats_genericas= y mlb_api siguiera siendo el viejo, el
    # TypeError tumbaria la app entera hasta reiniciar el proceso. Asignando el
    # atributo, un modulo desactualizado solo ignora el ajuste y sigue con el
    # generico de MLB; la app no se cae y se corrige sola al reiniciar.
    generico = stats_genericas_liga(clave)
    if generico:
        fetcher.stats_genericas = dict(generico)
    return fetcher


def fetcher_liga():
    return _crear_fetcher(st.session_state.liga)

# En Streamlit Cloud la API key de The Odds API se guarda en "Secrets" (no en el código).
# Aquí la pasamos a variable de entorno para que odds_api.py la lea. En local esto se ignora.
try:
    if hasattr(st, "secrets") and "ODDS_API_KEY" in st.secrets:
        os.environ["ODDS_API_KEY"] = str(st.secrets["ODDS_API_KEY"])
except Exception:
    pass

# Logo oficial: basta con dejar el archivo en la carpeta del proyecto.
# Se acepta logo.png / logo.jpg / logo.webp / logo.svg (en ese orden).
LOGO_FILE = next((f for f in ("logo_small.png", "logo.png", "logo.jpg", "logo.jpeg",
                              "logo.webp", "logo.svg") if os.path.exists(f)), None)


def _logo_data_uri():
    """El logo embebido en la pagina (no depende de rutas externas)."""
    if not LOGO_FILE:
        return None
    try:
        import base64
        mime = "image/svg+xml" if LOGO_FILE.endswith(".svg") else                ("image/webp" if LOGO_FILE.endswith(".webp") else
                ("image/jpeg" if LOGO_FILE.endswith((".jpg", ".jpeg")) else "image/png"))
        with open(LOGO_FILE, "rb") as f:
            return f"data:{mime};base64," + base64.b64encode(f.read()).decode()
    except Exception:
        return None


st.set_page_config(page_title="BET IA · Radar", page_icon=(LOGO_FILE or "⚾"),
                   layout="wide", initial_sidebar_state="expanded")

# ---------------------------------------------------------------------------
# Design system (dark quant) — basado en tokens de FlightHunter
# ---------------------------------------------------------------------------
st.markdown('''
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{
    --bg:255 255 255; --surface:255 255 255; --surface2:244 246 250;
    --ink:17 24 39; --ink2:107 114 128; --line:229 231 235;
    --accent:239 68 68; --accentink:255 255 255; --purple:139 92 246;
    --save:34 197 94; --warn:245 158 11; --fare:239 68 68; --blue:59 130 246;
    /* tema oscuro para sidebar + header */
    --dk:15 23 42; --dk2:30 41 59; --dkline:38 50 71; --dkink:226 232 240; --dkink2:148 163 184;
}
html, body, [class*="css"]{ font-family:'Inter',system-ui,sans-serif; }
.stApp{ background:rgb(var(--bg)); color:rgb(var(--ink)); }
section[data-testid="stSidebar"]{ background:rgb(var(--dk)); border-right:1px solid rgb(var(--dkline)); }
section[data-testid="stSidebar"] *{ color:rgb(var(--dkink)); }
section[data-testid="stSidebar"] .fh-subtitle{ color:rgb(var(--dkink2)); }
#MainMenu, footer{ visibility:hidden; }
header[data-testid="stHeader"]{ background:transparent; }
.block-container{ padding-top:1.2rem; padding-bottom:4rem; max-width:1440px; }
svg{ display:inline-block; vertical-align:middle; }

/* topbar (header oscuro) */
.fh-top{ display:flex; align-items:center; gap:14px; padding:16px 22px; margin-bottom:30px;
    background:rgb(var(--dk)); border:1px solid rgb(var(--dkline)); border-radius:16px;
    box-shadow:0 1px 3px rgb(16 24 40/.12); }
.fh-top-ico{ width:44px; height:44px; border-radius:12px; background:rgb(var(--accent));
    color:#fff; display:flex; align-items:center; justify-content:center; flex-shrink:0; }
.fh-title{ font-size:20px; font-weight:800; letter-spacing:-.02em; color:#f8fafc; margin:0; }
.fh-subtitle{ font-size:13px; color:rgb(var(--dkink2)); margin:2px 0 0 0; }
.fh-pill{ margin-left:auto; display:inline-flex; align-items:center; gap:6px; background:rgb(var(--dk2));
    border:1px solid rgb(var(--dkline)); border-radius:999px; padding:6px 14px; font-size:12.5px;
    color:rgb(var(--dkink2)); font-variant-numeric:tabular-nums; }

/* cards */
.fh-card{ border:1px solid rgb(var(--line)); background:rgb(var(--surface)); border-radius:16px;
    box-shadow:0 1px 2px rgb(16 24 40/.04),0 2px 8px rgb(16 24 40/.06); margin-bottom:18px; overflow:hidden; }
.fh-card.hl{ border-top:3px solid rgb(var(--accent)); }
.fh-card-header{ display:flex; align-items:center; justify-content:space-between; gap:10px;
    padding:11px 16px; border-bottom:1px solid rgb(var(--line)); }
.fh-ct{ display:flex; align-items:center; gap:9px; min-width:0; }
.fh-ct-ico{ color:rgb(var(--ink2)); display:flex; flex-shrink:0; }
.fh-card-title{ font-size:13px; font-weight:700; letter-spacing:.01em; text-transform:uppercase;
    color:rgb(var(--ink)); margin:0; }
.fh-card-subtitle{ font-size:11.5px; color:rgb(var(--ink2)); margin:1px 0 0 0; text-transform:none; font-weight:400; }
.fh-card-body{ padding:16px; }
/* Streamlit agranda los <p>; los ganamos en especificidad para que no se infle el encabezado */
.fh-card-header p.fh-card-title{ font-size:13px !important; margin:0 !important; line-height:1.25 !important; }
.fh-card-header p.fh-card-subtitle{ font-size:11.5px !important; margin:1px 0 0 0 !important;
    line-height:1.3 !important; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.fh-card-header .fh-badge{ flex-shrink:0; }

/* section header (widgets nativos) */
.fh-sec{ margin:14px 0 16px 0; }
.fh-sec h3{ font-size:16px; font-weight:700; letter-spacing:-.01em; margin:0; color:rgb(var(--ink)); }
.fh-sec p{ font-size:13px; color:rgb(var(--ink2)); margin:3px 0 0 0; }

/* stat tiles */
.fh-stat{ display:flex; gap:14px; align-items:flex-start; border:1px solid rgb(var(--line));
    background:rgb(var(--surface)); border-radius:16px; padding:20px 22px;
    box-shadow:0 1px 2px rgb(16 24 40/.04),0 2px 8px rgb(16 24 40/.06); height:100%; }
.fh-stat-ico{ width:46px; height:46px; border-radius:50%; display:flex; align-items:center;
    justify-content:center; flex-shrink:0; color:#fff; }
.fh-stat-ico.accent{ background:rgb(var(--accent)); }
.fh-stat-ico.fare{ background:rgb(var(--fare)); }
.fh-stat-ico.purple{ background:rgb(var(--purple)); }
.fh-stat-ico.save{ background:rgb(var(--save)); }
.fh-stat-ico.warn{ background:rgb(var(--warn)); }
.fh-stat-label{ font-size:11.5px; font-weight:600; letter-spacing:.06em; text-transform:uppercase; color:rgb(var(--ink2)); }
.fh-stat-value{ font-variant-numeric:tabular-nums; margin:4px 0 0 0; font-size:27px; font-weight:800;
    letter-spacing:-.02em; color:rgb(var(--ink)); line-height:1.05; }
.fh-stat-delta{ margin:5px 0 0 0; font-size:12px; font-weight:500; }
.fh-stat-delta.pos{ color:rgb(var(--save)); } .fh-stat-delta.neg{ color:rgb(var(--fare)); }

/* badges */
.fh-badge{ display:inline-flex; align-items:center; gap:5px; border-radius:999px; padding:4px 11px;
    font-size:11.5px; font-weight:600; letter-spacing:.01em; }
.fh-badge.accent{ background:rgb(var(--accent)/0.15); color:rgb(var(--accent)); }
.fh-badge.save{ background:rgb(var(--save)/0.15); color:rgb(var(--save)); }
.fh-badge.warn{ background:rgb(var(--warn)/0.15); color:rgb(var(--warn)); }
.fh-badge.fare{ background:rgb(var(--fare)/0.15); color:rgb(var(--fare)); }
.fh-badge.purple{ background:rgb(var(--purple)/0.15); color:rgb(var(--purple)); }
.fh-badge.neutral{ background:rgb(var(--surface2)); color:rgb(var(--ink2)); }
.fh-badge.blue{ background:rgb(var(--blue)/0.12); color:rgb(var(--blue)); }
.fh-badge.live{ background:rgb(var(--fare)/0.15); color:rgb(var(--fare)); }
.fh-badge.live::before{ content:""; width:6px; height:6px; border-radius:999px; background:rgb(var(--fare));
    display:inline-block; animation:fhpulse 1.4s ease-in-out infinite; }
@keyframes fhpulse{ 0%,100%{opacity:1} 50%{opacity:.25} }

/* pick cards */
.fh-grid{ display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr)); gap:14px; }
/* rejilla compacta para las tarjetas de picks (Predicciones) */
.fh-grid.picks{ grid-template-columns:repeat(auto-fill,minmax(248px,1fr)); gap:10px; }
.fh-pick{ border:1px solid rgb(var(--line)); background:rgb(var(--surface)); border-radius:11px; padding:11px 12px;
    box-shadow:0 1px 2px rgb(16 24 40/.04); transition:border-color .15s ease, transform .15s ease, box-shadow .15s ease; }
.fh-pick:hover{ border-color:rgb(var(--accent)/0.5); transform:translateY(-2px); box-shadow:0 6px 16px rgb(16 24 40/.09); }
.fh-pick.won{ border-color:rgb(var(--save)); background:rgb(var(--save)/0.12); box-shadow:0 0 0 1px rgb(var(--save)/0.35) inset; }
.fh-pick.lost{ border-color:rgb(var(--fare)/0.6); background:rgb(var(--fare)/0.07); }
.fh-pick-badges{ display:flex; align-items:center; gap:4px; flex-wrap:wrap; }
.fh-pick-badges .fh-badge{ padding:2px 7px; font-size:10px; }
.fh-pick-rank{ margin-left:auto; font-size:10.5px; color:rgb(var(--ink2)); font-variant-numeric:tabular-nums; }
.fh-pick-matchup{ margin-top:7px; font-size:13px; font-weight:700; letter-spacing:-.01em; color:rgb(var(--ink));
    line-height:1.25; }
.fh-pick-selection{ margin-top:1px; font-size:11.5px; color:rgb(var(--ink2)); }
.fh-pick-ev-row{ margin-top:7px; display:flex; align-items:baseline; justify-content:space-between; }
.fh-pick-ev{ font-variant-numeric:tabular-nums; font-size:18px; font-weight:800; letter-spacing:-.02em; }
.fh-pick-ev.pos{ color:rgb(var(--save)); } .fh-pick-ev.neg{ color:rgb(var(--fare)); }
.fh-pick-ev-sub{ font-size:10px; color:rgb(var(--ink2)); font-weight:500; margin-left:3px; }
.fh-pick-meta{ margin-top:7px; padding-top:7px; border-top:1px solid rgb(var(--line)); display:flex;
    flex-wrap:wrap; gap:3px 9px; font-size:10.5px; color:rgb(var(--ink2)); line-height:1.35; }
.fh-pick-meta b{ color:rgb(var(--ink)); font-weight:600; }
/* Streamlit aplica sus propios tamanos a los <p>; aqui los ganamos en especificidad */
.fh-pick p{ margin:0 !important; line-height:1.25 !important; }
.fh-pick p.fh-pick-matchup{ font-size:13px !important; margin-top:7px !important; }
.fh-pick p.fh-pick-selection{ font-size:11.5px !important; margin-top:2px !important; }
.fh-pick p.fh-pick-ev{ font-size:18px !important; }
.fh-pick .fh-pick-ev-row p{ font-size:11px !important; }
.fh-pick .fh-pick-ev-row p.fh-pick-ev{ font-size:18px !important; }

/* scoreboard (2 columnas: equipos+marcador | estado+diamante) */
.fh-score{ display:flex; align-items:stretch; gap:0; border:1px solid rgb(var(--line));
    background:rgb(var(--surface)); border-radius:14px; padding:16px 18px; box-shadow:0 1px 2px rgb(16 24 40/.04); }
.fh-score.live{ border-color:rgb(var(--accent)/0.35); }
.fh-score-main{ flex:1; min-width:0; }
.fh-score-row{ display:flex; align-items:center; gap:10px; padding:5px 0; }
.fh-score-logo{ width:24px; height:24px; object-fit:contain; flex-shrink:0; }
.fh-score-team{ font-size:14px; font-weight:600; color:rgb(var(--ink)); overflow:hidden;
    text-overflow:ellipsis; white-space:nowrap; }
.fh-score-team.lose{ color:rgb(var(--ink2)); font-weight:500; }
.fh-score-runs{ margin-left:auto; font-variant-numeric:tabular-nums; font-size:20px; font-weight:800;
    letter-spacing:-.02em; color:rgb(var(--ink)); padding-left:10px; }
.fh-score-side{ display:flex; flex-direction:column; align-items:center; justify-content:center; gap:7px;
    border-left:1px solid rgb(var(--line)); padding-left:16px; margin-left:16px; min-width:120px; }
.fh-score-st{ font-size:12px; font-weight:700; color:rgb(var(--ink2)); text-align:center; }
.fh-score-st.live{ color:rgb(var(--accent)); }

/* mini tablas del dashboard */
.fh-trow{ display:grid; grid-template-columns:1fr auto auto auto; align-items:center; gap:12px;
    padding:10px 4px; border-bottom:1px solid rgb(var(--line)); }
.fh-trow.up{ grid-template-columns:auto 1fr auto auto; }
.fh-trow:last-child{ border-bottom:none; }
.fh-tteam{ display:flex; align-items:center; gap:9px; min-width:0; }
.fh-tteam img{ width:22px; height:22px; object-fit:contain; flex-shrink:0; }
.fh-tteam .nm{ font-size:13.5px; font-weight:600; color:rgb(var(--ink)); white-space:nowrap; }
.fh-tteam .vs{ font-size:11.5px; color:rgb(var(--ink2)); white-space:nowrap; }
.fh-todds{ font-variant-numeric:tabular-nums; font-size:13.5px; font-weight:700; color:rgb(var(--ink)); }
.fh-tev{ font-variant-numeric:tabular-nums; font-size:13px; font-weight:700; color:rgb(var(--save)); min-width:48px; text-align:right; }
.fh-ttime{ font-variant-numeric:tabular-nums; font-size:12.5px; font-weight:700; color:rgb(var(--ink2)); min-width:44px; }
.fh-tres{ width:22px; height:22px; border-radius:50%; display:flex; align-items:center; justify-content:center;
    font-size:12px; color:#fff; }
.fh-tres.won{ background:rgb(var(--save)); } .fh-tres.lost{ background:rgb(var(--fare)); }
.fh-tres.pend{ background:rgb(var(--surface2)); color:rgb(var(--ink2)); border:1px solid rgb(var(--line)); }
.fh-tres.push{ background:rgb(var(--warn)); }
.fh-tfoot{ text-align:center; padding:12px 0 2px 0; }
.fh-tfoot a, .fh-tfoot span{ color:rgb(var(--accent)); font-size:13px; font-weight:600; cursor:default; }

/* ---- Top Pick: logo del equipo + barras de contexto ---- */
.tp-hero{ display:flex; align-items:center; justify-content:space-between; gap:16px; }
.tp-info{ min-width:0; }
.tp-logo{ display:flex; align-items:center; gap:6px; flex-shrink:0;
    background:rgb(var(--surface2)); border:1px solid rgb(var(--line));
    border-radius:16px; padding:10px 14px; }
.tp-bars{ margin-top:14px; display:flex; flex-direction:column; gap:7px; }
.tp-bar{ display:flex; align-items:center; gap:10px; font-size:11.5px; color:rgb(var(--ink2)); }
.tp-bar span{ width:96px; flex-shrink:0; }
.tp-bar b{ width:38px; text-align:right; color:rgb(var(--ink)); font-variant-numeric:tabular-nums; font-size:12px; }
.tp-track{ flex:1; height:6px; border-radius:999px; background:rgb(var(--surface2)); overflow:hidden; }
.tp-track i{ display:block; height:100%; border-radius:999px; }

/* ---- Pagina Resultados: titulo y tabla de detalle ---- */
.rt-head{ display:flex; align-items:center; gap:13px; margin:2px 0 20px 0; }
.rt-head-ico{ width:42px; height:42px; border-radius:12px; background:rgb(var(--accent)/0.12);
    color:rgb(var(--accent)); display:flex; align-items:center; justify-content:center; flex-shrink:0; }
.rt-head h2{ margin:0; font-size:26px; font-weight:800; letter-spacing:-.025em; color:rgb(var(--ink)); line-height:1.1; }
.rt-head p{ margin:2px 0 0 0 !important; font-size:13px !important; color:rgb(var(--ink2)); }

/* Encabezado de seccion SIN tarjeta: fluye sobre la pagina */
.rt-sec{ display:flex; align-items:baseline; flex-wrap:wrap; gap:10px; margin:30px 0 14px 0; }
.rt-sec h3{ margin:0; font-size:17px; font-weight:700; letter-spacing:-.015em;
    color:rgb(var(--ink)); line-height:1.2; }
.rt-sec p{ margin:0 !important; font-size:12.5px !important; color:rgb(var(--ink2)); line-height:1.3; }
.rt-count{ display:inline-block; margin-left:6px; background:rgb(var(--surface2));
    border:1px solid rgb(var(--line)); border-radius:999px; padding:1px 9px;
    font-size:12px; font-weight:700; color:rgb(var(--ink2)); vertical-align:middle; }

.rt-sub{ font-size:12.5px; color:rgb(var(--ink2)); margin-left:10px; font-weight:400; }
.rt-resumen{ font-size:12.5px; color:rgb(var(--ink2)); margin:10px 2px 12px 2px; }
.rt-resumen b{ font-weight:700; }

.rt-wrap{ overflow-x:auto; border:1px solid rgb(var(--line)); border-radius:12px; }
.rt-table{ width:100%; border-collapse:separate; border-spacing:0; font-size:12.5px; }
.rt-table thead th{ background:rgb(var(--surface2)); color:rgb(var(--ink2)); font-size:10px;
    font-weight:700; letter-spacing:.07em; text-transform:uppercase; text-align:left;
    padding:11px 14px; white-space:nowrap; border-bottom:1px solid rgb(var(--line)); }
.rt-table tbody td{ padding:10px 14px; border-bottom:1px solid rgb(var(--line));
    vertical-align:middle; white-space:nowrap; }
.rt-table tbody tr:last-child td{ border-bottom:none; }
.rt-table tbody tr:hover td{ background:rgb(var(--surface2)/0.5); }
.rt-table .num{ text-align:right; font-variant-numeric:tabular-nums; }
.rt-table .fecha{ color:rgb(var(--ink2)); font-variant-numeric:tabular-nums; }
.rt-game{ display:flex; align-items:center; gap:7px; }
.rt-game img{ width:20px; height:20px; object-fit:contain; flex-shrink:0; }
.rt-nologo{ width:20px; text-align:center; display:inline-block; }
.rt-game span.nm{ color:rgb(var(--ink)); font-weight:500; }
.rt-sel{ font-weight:600; color:rgb(var(--ink)); }
/* Cobrada por pago anticipado (ventaja de 5+ carreras) */
.rt-ant{ margin-left:5px; font-size:12px; cursor:help; opacity:.85; }
.rt-pl.pos{ color:rgb(var(--save)); font-weight:700; }
.rt-pl.neg{ color:rgb(var(--fare)); font-weight:700; }
.rt-pl.zero{ color:rgb(var(--ink2)); }
/* Picks del mismo partido: una fila por pick, unidas visualmente en un bloque */
.rt-table tbody tr.grp td{ border-bottom:none; }
.rt-table tbody tr.grp.grp-end td{ border-bottom:1px solid rgb(var(--line)); }
.rt-table tbody tr.grp td:first-child{ box-shadow:inset 2px 0 0 rgb(var(--accent)/0.55); }
.rt-multi{ margin-left:8px; font-size:10px; font-weight:700; letter-spacing:.03em;
    color:rgb(var(--accent)); background:rgb(var(--accent)/0.12); padding:1px 7px; border-radius:999px; }

/* ---- Chief Tipster: rejilla compacta ---- */
.ct-grid{ margin-top:10px; display:grid; grid-template-columns:1fr 1fr; gap:6px 12px; }
.ct-grid p{ margin:0 !important; font-size:11.5px !important; color:rgb(var(--ink2)); line-height:1.2 !important; }
.ct-grid b{ font-size:13px; font-weight:700; color:rgb(var(--ink)); line-height:1.25; }

/* ---- Parlay del dia (checklist) ---- */
.pl-legs{ padding:4px 16px 0 16px; }
.pl-leg{ display:flex; align-items:center; gap:10px; padding:5px 0;
    border-bottom:1px solid rgb(var(--line)); }
.pl-leg:last-child{ border-bottom:none; }
.pl-check{ width:20px; height:20px; border-radius:6px; flex-shrink:0; display:flex;
    align-items:center; justify-content:center; font-size:12px; font-weight:800; color:#fff;
    border:1.5px solid rgb(var(--line)); background:rgb(var(--surface2)); }
.pl-check.won{ background:rgb(var(--save)); border-color:rgb(var(--save)); }
.pl-check.lost{ background:rgb(var(--fare)); border-color:rgb(var(--fare)); }
.pl-check.push{ background:rgb(var(--warn)); border-color:rgb(var(--warn)); }
.pl-logo img{ width:22px; height:22px; object-fit:contain; display:block; }
.pl-txt{ display:flex; flex-direction:column; min-width:0; flex:1; }
.pl-txt b{ font-size:13px; font-weight:700; color:rgb(var(--ink)); line-height:1.2; }
.pl-txt span{ font-size:11px; color:rgb(var(--ink2)); overflow:hidden;
    text-overflow:ellipsis; white-space:nowrap; }
.pl-prob{ font-size:12.5px; font-weight:700; color:rgb(var(--ink)); font-variant-numeric:tabular-nums; }
.pl-odds{ font-size:12px; color:rgb(var(--ink2)); font-variant-numeric:tabular-nums; min-width:34px; text-align:right; }
.pl-leg.lost .pl-txt b{ color:rgb(var(--fare)); text-decoration:line-through; }
.pl-leg.won .pl-txt b{ color:rgb(var(--save)); }
.pl-foot{ display:flex; gap:8px; padding:6px 16px; margin-top:0;
    border-top:1px solid rgb(var(--line)); background:rgb(var(--surface2)/0.5); }
.pl-foot div{ flex:1; display:flex; flex-direction:column; gap:0; }
.pl-foot span{ font-size:9.5px; text-transform:uppercase; letter-spacing:.04em; color:rgb(var(--ink2)); line-height:1.3; }
.pl-foot b{ font-size:14px; font-weight:800; color:rgb(var(--ink)); font-variant-numeric:tabular-nums; line-height:1.25; }
.pl-foot b.pos{ color:rgb(var(--save)); } .pl-foot b.neg{ color:rgb(var(--fare)); }

/* topbar acciones */
.fh-top-actions{ display:flex; align-items:center; gap:10px; }
.fh-ic-btn{ position:relative; width:38px; height:38px; border-radius:10px; border:1px solid rgb(var(--dkline));
    background:rgb(var(--dk2)); color:rgb(var(--dkink2)); display:flex; align-items:center; justify-content:center; }
.fh-ic-dot{ position:absolute; top:-5px; right:-5px; min-width:17px; height:17px; padding:0 4px; border-radius:999px;
    background:rgb(var(--accent)); color:#fff; font-size:10.5px; font-weight:700; display:flex; align-items:center; justify-content:center; }

/* history rows */
.fh-hrow{ display:flex; align-items:center; justify-content:space-between; gap:10px; padding:11px 0;
    border-bottom:1px solid rgb(var(--line)); font-size:13px; }

/* filter pills (radio) */
div[role="radiogroup"]{ flex-direction:row; flex-wrap:wrap; gap:8px; }
div[role="radiogroup"] > label{ background:rgb(var(--surface2)); border:1px solid rgb(var(--line));
    border-radius:999px; padding:7px 16px; margin:0; cursor:pointer; transition:all .15s; }
div[role="radiogroup"] > label:hover{ border-color:rgb(var(--accent)/0.5); }
div[role="radiogroup"] > label > div:first-child{ display:none !important; }
div[role="radiogroup"] > label div, div[role="radiogroup"] > label p{ font-size:12.5px; font-weight:700;
    letter-spacing:.03em; text-transform:uppercase; color:rgb(var(--ink2)); }
div[role="radiogroup"] > label:has(input:checked){ background:rgb(var(--accent)); border-color:rgb(var(--accent)); }
div[role="radiogroup"] > label:has(input:checked) div, div[role="radiogroup"] > label:has(input:checked) p{ color:#fff; }

/* sidebar system card */
.fh-sys{ border:1px solid rgb(var(--dkline)); background:rgb(var(--dk2)); border-radius:12px; padding:13px 14px; }
.fh-sys-row{ display:flex; align-items:center; justify-content:space-between; }
.fh-sys h4{ margin:0; font-size:13.5px; font-weight:700; color:#f1f5f9; }
.fh-sys .lab{ font-size:10.5px; text-transform:uppercase; letter-spacing:.06em; color:rgb(var(--dkink2)); margin:10px 0 1px 0; }
.fh-sys .val{ font-size:13px; font-weight:600; color:#f1f5f9; font-variant-numeric:tabular-nums; }

/* widget overrides */
div[data-testid="stMetric"]{ display:none; }
/* --- Barra lateral: marca pegada arriba y navegacion a la izquierda --- */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"]{ padding-top:0 !important; }
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{ padding-top:0 !important; }
/* La cabecera del sidebar (boton de colapsar) reservaba 60px de aire */
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"]{
    height:auto !important; min-height:0 !important; padding:6px 0 0 0 !important; }
.sb-brand{ display:flex; align-items:center; gap:12px; padding:0 0 18px 0;
    border-bottom:1px solid rgb(var(--dkline)); margin-bottom:14px; }
.sb-logo{ width:42px; height:42px; border-radius:12px; background:rgb(var(--accent));
    color:#fff; display:flex; align-items:center; justify-content:center; flex-shrink:0; }
.sb-logo-img{ width:46px; height:46px; object-fit:contain; flex-shrink:0; display:block; }
.sb-name{ font-size:19px; font-weight:800; margin:0 !important; letter-spacing:-.02em;
    color:#f8fafc; line-height:1.15; }
.sb-tag{ font-size:12px !important; margin:1px 0 0 0 !important; color:rgb(var(--dkink2)); line-height:1.2; }
.sb-lbl{ font-size:10.5px !important; font-weight:700; letter-spacing:.09em; text-transform:uppercase;
    color:rgb(var(--dkink2)); margin:0 0 6px 0 !important; }
.sb-sep{ border-bottom:1px solid rgb(var(--dkline)); margin:14px 0; }
/* Botones de liga: se oculta el texto y se muestra el logo de la liga */
section[data-testid="stSidebar"] .stButton > button{ border-radius:10px; font-weight:600; font-size:14.5px;
    padding:10px 14px; justify-content:flex-start !important; text-align:left !important; }
/* Streamlit centra el contenido interno del boton: se fuerza a la izquierda */
section[data-testid="stSidebar"] .stButton > button > div,
section[data-testid="stSidebar"] .stButton > button p{
    justify-content:flex-start !important; text-align:left !important; width:100%; }
section[data-testid="stSidebar"] .stButton{ margin-bottom:3px; }

section[data-testid="stSidebar"] [class*="stColumn"] .stButton > button{
    height:54px; padding:6px !important; justify-content:center !important; }
/* el atajo background del boton resetea estas propiedades: se fuerzan */
section[data-testid="stSidebar"] [class*="st-key-liga"] .stButton > button{
    background-repeat:no-repeat !important; background-position:center !important;
    background-size:auto 28px !important; }
section[data-testid="stSidebar"] [class*="stColumn"] .stButton > button p,
section[data-testid="stSidebar"] [class*="stColumn"] .stButton > button div{
    font-size:0 !important; line-height:0 !important; }
section[data-testid="stSidebar"] .st-key-liga_MLB .stButton > button{
    background-image:url("https://www.mlbstatic.com/team-logos/league-on-dark/1.svg") !important; }
section[data-testid="stSidebar"] .st-key-liga_MLB .stButton > button[kind="primary"]{
    background-image:url("https://www.mlbstatic.com/team-logos/league-on-light/1.svg") !important; }
section[data-testid="stSidebar"] .st-key-liga_LMB .stButton > button{
    background-image:url("https://www.mlbstatic.com/team-logos/league-on-dark/125.svg") !important; }
section[data-testid="stSidebar"] .st-key-liga_LMB .stButton > button[kind="primary"]{
    background-image:url("https://www.mlbstatic.com/team-logos/league-on-light/125.svg") !important; }

section[data-testid="stSidebar"] .stButton > button p{
    justify-content:flex-start !important; text-align:left !important; width:100%; }
section[data-testid="stSidebar"] .stButton{ margin-bottom:3px; }
section[data-testid="stSidebar"] .stButton > button[kind="secondary"]{ background:transparent;
    color:rgb(var(--dkink2)); border:1px solid transparent; }
section[data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover{ background:rgb(var(--dk2)); color:#f1f5f9; }
section[data-testid="stSidebar"] .stButton > button[kind="primary"]{ background:rgb(var(--accent));
    color:#fff; border:none; box-shadow:0 4px 14px rgb(var(--accent)/0.35); }
.stButton > button[kind="primary"]{ background:rgb(var(--accent)); color:#fff; border:none; border-radius:10px; font-weight:600; }
.stButton > button[kind="primary"]:hover{ background:rgb(var(--accent)/0.85); color:#fff; }
.block-container .stButton > button[kind="secondary"]{ background:transparent; border:none; color:rgb(var(--accent));
    font-weight:600; font-size:13px; justify-content:center; }
.block-container .stButton > button[kind="secondary"]:hover{ background:rgb(var(--accent)/0.08); color:rgb(var(--accent)); }
div[data-baseweb="select"] > div, .stTextInput > div > div, .stNumberInput > div > div{
    background:rgb(var(--surface2)) !important; border-color:rgb(var(--line)) !important;
    color:rgb(var(--ink)) !important; border-radius:9px !important; }
.stMultiSelect span[data-baseweb="tag"]{ background:rgb(var(--accent)/0.2) !important; color:rgb(var(--accent)) !important; }
[data-testid="stDataFrame"]{ border:1px solid rgb(var(--line)); border-radius:12px; overflow:hidden; }
.stCheckbox label p{ color:rgb(var(--ink2)); font-size:13px; }
hr{ border-color:rgb(var(--line)); }

/* ---- "En vivo": tabla unificada tipo mercado (rediseño) ---- */
.lv-brand{ display:flex; align-items:center; gap:8px; margin-bottom:10px; }
.lv-brand img{ width:22px; height:22px; object-fit:contain; }
.lv-brand b{ font-size:14px; font-weight:800; letter-spacing:-.01em; color:rgb(var(--ink)); }
.st-key-lv_f_todos .stButton>button, .st-key-lv_f_prev .stButton>button,
.st-key-lv_f_live .stButton>button, .st-key-lv_f_final .stButton>button{
    border-radius:999px !important; font-size:11.5px !important; font-weight:700 !important;
    letter-spacing:.02em; padding:7px 6px !important; }
.st-key-lv_f_todos .stButton>button[kind="secondary"], .st-key-lv_f_prev .stButton>button[kind="secondary"],
.st-key-lv_f_live .stButton>button[kind="secondary"], .st-key-lv_f_final .stButton>button[kind="secondary"]{
    background:rgb(var(--surface)); border:1px solid rgb(var(--line)); color:rgb(var(--ink2)); }
.st-key-lv_f_todos .stButton>button[kind="primary"]{ background:rgb(var(--ink)); border-color:rgb(var(--ink)); box-shadow:none; }
.st-key-lv_f_prev .stButton>button[kind="primary"]{ background:rgb(var(--blue)); border-color:rgb(var(--blue)); box-shadow:none; }
.st-key-lv_f_live .stButton>button[kind="primary"]{ background:rgb(var(--fare)); border-color:rgb(var(--fare)); box-shadow:none; }
.st-key-lv_f_final .stButton>button[kind="primary"]{ background:rgb(var(--ink2)); border-color:rgb(var(--ink2)); box-shadow:none; }
.lv-status{ display:flex; align-items:center; gap:6px; font-size:12px; color:rgb(var(--ink2));
    margin:2px 0 14px 0 !important; }
.lv-status svg{ opacity:.6; }
.lv-status .lv-dot{ margin:0 2px; opacity:.5; }
.lv-tablewrap{ border:1px solid rgb(var(--line)); border-radius:12px; overflow-x:auto; }
.lv-cols{ grid-template-columns:78px 104px minmax(300px,1.5fr) 84px 156px 52px 52px 72px 58px 112px 62px; }
.lv-head{ display:grid; column-gap:8px; padding:10px 12px; background:rgb(var(--surface2));
    color:rgb(var(--ink2)); font-size:10.5px; font-weight:700; letter-spacing:.07em;
    text-transform:uppercase; border-bottom:1px solid rgb(var(--line)); white-space:nowrap; }
.lv-head small{ text-transform:none; font-weight:500; font-size:9.5px; opacity:.7; margin-left:3px; }
.lv-row{ min-width:1196px; }
.lv-sum{ display:grid; column-gap:8px; align-items:center; padding:9px 12px; cursor:pointer;
    list-style:none; border-bottom:1px solid rgb(var(--line)); transition:background .12s ease; }
.lv-sum::-webkit-details-marker{ display:none; }
.lv-sum::marker{ content:''; }
.lv-body:hover>.lv-sum{ background:rgb(var(--surface2)/0.55); }
.lv-body.v-win>.lv-sum{ background:rgb(var(--save)/0.06); }
.lv-body.v-lose>.lv-sum{ background:rgb(var(--fare)/0.055); }
.lv-body.v-tie>.lv-sum{ background:rgb(var(--ink2)/0.055); }
.lv-body:last-of-type>.lv-sum{ border-bottom:none; }
.lv-body.live .c-hora{ color:rgb(var(--accent)); font-weight:700; }
.lv-head .num, .lv-sum .num{ text-align:right; font-variant-numeric:tabular-nums; font-weight:700; }
.lv-head .c-det{ text-align:center; }
.lv-sum .c-det{ display:flex; align-items:center; justify-content:center; gap:6px; }
.lv-sum .fh-tres{ width:21px; height:21px; font-size:11px; flex-shrink:0; }
.lv-sum .fh-tres.empty{ background:transparent; border:1px dashed rgb(var(--line)); }
.lv-sum .c-hora{ font-variant-numeric:tabular-nums; font-weight:700; color:rgb(var(--ink2)); white-space:nowrap; }
.lv-sum .teams{ display:flex; align-items:center; gap:7px; min-width:0; }
.lv-sum .teams img{ width:20px; height:20px; object-fit:contain; flex-shrink:0; }
.lv-sum .teams .t{ font-weight:600; color:rgb(var(--ink)); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.lv-sum .teams .vs{ color:rgb(var(--ink2)); font-size:11.5px; margin:0 2px; flex-shrink:0; }
/* Abridores bajo el partido: 'Pitchers: Gusto R. [HOU] (0-2)' */
.lv-pit{ display:flex; align-items:center; flex-wrap:wrap; gap:0 8px; margin-top:3px;
    font-size:10.5px; line-height:1.5; color:rgb(var(--ink2)); font-weight:500; }
.lv-pit em{ font-style:normal; opacity:.65; }
.lv-pit .pit{ white-space:nowrap; }
.lv-pit .pit+.pit::before{ content:'·'; margin-right:7px; opacity:.45; }
.lv-pit i{ font-style:normal; margin-left:4px; padding:0 3px; border-radius:3px;
    background:rgb(var(--ink2)/0.1); font-size:9.5px; letter-spacing:.02em; }
.lv-pit b{ font-weight:700; margin-left:4px; color:rgb(var(--ink)); font-variant-numeric:tabular-nums; }
.lv-marc{ font-variant-numeric:tabular-nums; font-weight:800; font-size:14px; letter-spacing:-.01em; color:rgb(var(--ink2)); }
.lv-marc i{ font-style:normal; opacity:.45; margin:0 1px; }
.lv-marc.live{ color:rgb(var(--accent)); }
.lv-marc.final{ color:rgb(var(--ink)); }
.c-marc small{ display:block; font-size:10px; color:rgb(var(--ink2)); margin-top:1px; font-weight:500; }
.c-pick .pick-nm{ display:block; font-weight:600; color:rgb(var(--ink)); font-size:12.5px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.c-pick .pick-mkt{ display:block; font-size:10.5px; color:rgb(var(--ink2)); margin-top:1px; }
.lv-sum .vacio{ color:rgb(var(--ink2)); opacity:.5; }
.lv-sum .ev.pos{ color:rgb(var(--save)); } .lv-sum .ev.neg{ color:rgb(var(--fare)); }
.lv-sum .stk.on{ color:rgb(var(--accent)); } .lv-sum .stk.off{ color:rgb(var(--ink2)); opacity:.5; }
.c-inicio{ font-size:11.5px; color:rgb(var(--ink2)); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.lv-body.live .c-inicio{ color:rgb(var(--accent)); font-weight:600; }
.lv-chev{ transition:transform .15s ease; color:rgb(var(--ink2)); display:inline-flex; }
.lv-body[open]>.lv-sum .lv-chev{ transform:rotate(180deg); color:rgb(var(--accent)); }
.lv-detail{ padding:14px 20px 16px 20px; background:rgb(var(--surface2)/0.5);
    border-bottom:1px solid rgb(var(--line)); font-size:12.5px; color:rgb(var(--ink2)); }
.lv-body:last-of-type .lv-detail{ border-bottom:none; }
.lv-dgrid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:10px 18px; margin-bottom:10px; }
.lv-dgrid p{ margin:0 !important; font-size:10.5px !important; text-transform:uppercase;
    letter-spacing:.05em; color:rgb(var(--ink2)); }
.lv-dgrid b{ font-size:13.5px; font-weight:700; color:rgb(var(--ink)); }
.lv-notes{ padding-top:8px; border-top:1px dashed rgb(var(--line)); }
.lv-notes p{ margin:3px 0 !important; line-height:1.55 !important; font-size:12px !important; }
.lv-notes b{ color:rgb(var(--ink)); }
.lv-legend{ display:flex; align-items:center; gap:18px; flex-wrap:wrap; font-size:12px;
    color:rgb(var(--ink2)); margin:14px 2px 0 2px !important; }
.lv-legend .dot{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }
.lv-legend .dot.live{ background:rgb(var(--fare)); } .lv-legend .dot.blue{ background:rgb(var(--blue)); }
.lv-legend .dot.neutral{ background:rgb(var(--ink2)); } .lv-legend .dot.warn{ background:rgb(var(--warn)); }
</style>
''', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Iconos SVG (estilo lucide)
# ---------------------------------------------------------------------------
ICONS = {
    "bar": '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    "radio": '<circle cx="12" cy="12" r="2"/><path d="M4.93 19.07a10 10 0 0 1 0-14.14M7.76 16.24a6 6 0 0 1 0-8.48M16.24 7.76a6 6 0 0 1 0 8.48M19.07 4.93a10 10 0 0 1 0 14.14"/>',
    "dollar": '<line x1="12" y1="2" x2="12" y2="22"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "flame": '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
    "briefcase": '<rect width="20" height="14" x="2" y="7" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
    "grid": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    "sensors": '<circle cx="12" cy="12" r="2"/><path d="M6.34 17.66a8 8 0 0 1 0-11.32M17.66 6.34a8 8 0 0 1 0 11.32"/>',
    "receipt": '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M8 7h8M8 11h8M8 15h5"/>',
    "trophy": '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6M18 9h1.5a2.5 2.5 0 0 0 0-5H18M4 22h16M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22M18 2H6v7a6 6 0 0 0 12 0V2Z"/>',
    "contrast": '<circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 0 20z" fill="currentColor" stroke="none"/>',
    "crown": '<path d="M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L21.183 5.5a.5.5 0 0 1 .798.519l-2.834 10.246a1 1 0 0 1-.956.734H5.81a1 1 0 0 1-.957-.734L2.02 6.02a.5.5 0 0 1 .798-.519l4.276 3.664a1 1 0 0 0 1.516-.294z"/><path d="M5 21h14"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 20a8 8 0 0 1 16 0"/>',
    "share": '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="M16 6l-4-4-4 4"/><path d="M12 2v13"/>',
    "calendar": '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18M8 2v4M16 2v4"/>',
    "chevron": '<path d="m6 9 6 6 6-6"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
}


def svg(name, size=20, stroke=2):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" '
            f'fill="none" stroke="currentColor" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round">{ICONS[name]}</svg>')


def badge(text, tone="neutral"):
    return f'<span class="fh-badge {tone}">{text}</span>'


TONE_MARKET = {"ML": "accent", "TOTAL": "save", "F5": "warn"}
TONE_RISK = {"BAJO": "save", "MEDIO": "warn", "ALTO": "fare"}
TONE_TAG = {"🔥 ELITE": "save", "✅ VALUE": "accent", "⚠️ MOD": "warn", "🚫 NO": "fare", "🚫 NO BET": "fare"}


def stat_tile(col, label, value, delta, positive, icon, tone):
    d = "pos" if positive else "neg"
    arrow = "↑" if positive else "↓"
    col.markdown(
        f'<div class="fh-stat"><div class="fh-stat-ico {tone}">{svg(icon)}</div>'
        f'<div><div class="fh-stat-label">{label}</div>'
        f'<p class="fh-stat-value">{value}</p>'
        f'<p class="fh-stat-delta {d}">{arrow} {delta}</p></div></div>',
        unsafe_allow_html=True,
    )


def page_section(title, subtitle=""):
    """Encabezado de seccion sin tarjeta: titulo y subtitulo sueltos sobre la pagina."""
    st.markdown(f'<div class="rt-sec"><h3>{title}</h3><p>{subtitle}</p></div>',
                unsafe_allow_html=True)


def section_header(title, subtitle=""):
    st.markdown(f'<div class="fh-sec"><h3>{title}</h3><p>{subtitle}</p></div>', unsafe_allow_html=True)


_MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]


def topbar(title, subtitle, icon="grid", bell=None):
    """Encabezado retirado: ocupaba espacio sin aportar (la sección activa ya se
    ve en la barra lateral). Se conserva la función para no tocar las páginas."""
    return


def card_header(title, subtitle, icon, right_badge="", hl=False):
    return (
        f'<div class="fh-card{" hl" if hl else ""}"><div class="fh-card-header">'
        f'<div class="fh-ct"><span class="fh-ct-ico">{svg(icon, 18)}</span><div>'
        f'<p class="fh-card-title">{title}</p><p class="fh-card-subtitle">{subtitle}</p></div></div>'
        f'{right_badge}</div><div class="fh-card-body">'
    )


def hora12(dt, con_segundos=False):
    """Hora en formato de 12 horas: '8:38 p.m.' (sin cero a la izquierda)."""
    h = dt.hour % 12 or 12
    sufijo = "a.m." if dt.hour < 12 else "p.m."
    reloj = f"{h}:{dt.minute:02d}" + (f":{dt.second:02d}" if con_segundos else "")
    return f"{reloj} {sufijo}"


def fmt_start(iso):
    """Hora de inicio del partido en la zona horaria de la app (no la del servidor)."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return hora12(dt.astimezone(_TZ) if _TZ else dt.astimezone())
    except Exception:
        return ""


def team_logo(team_id, nombre=None):
    """Escudo del equipo. Si la liga no tiene logos oficiales (id 0), se genera uno."""
    if not team_id:
        return f'<img class="fh-score-logo" src="{escudo_svg(nombre or "")}" alt=""/>'
    return f'<img class="fh-score-logo" src="https://www.mlbstatic.com/team-logos/{team_id}.svg" alt=""/>'


def inning_abbr(state):
    return {"Top": "Top", "Bottom": "Bot", "Middle": "Mid", "End": "End"}.get(state, (state or "")[:3])


def pick_card_html(row, result=None):
    ev_tone = "pos" if row["EV"] > 0 else "neg"
    cls = {"WON": " won", "LOST": " lost"}.get(result, "")
    res_badge = ""
    if result == "WON":
        res_badge = badge("✅ GANADO", "save")
    elif result == "LOST":
        res_badge = badge("❌ PERDIDO", "fare")
    elif result == "PUSH":
        res_badge = badge("➖ PUSH", "warn")
    return (
        f'<div class="fh-pick{cls}"><div class="fh-pick-badges">'
        f'{badge(row["MERCADO"], TONE_MARKET.get(row["MERCADO"], "neutral"))}'
        f'{badge(row["RIESGO"], TONE_RISK.get(row["RIESGO"], "neutral"))}'
        f'{res_badge or badge(row["TAG"], TONE_TAG.get(row["TAG"], "neutral"))}'
        f'<span class="fh-pick-rank">#{row["RANK"]}</span></div>'
        f'<p class="fh-pick-matchup">{row["PARTIDO"]}</p>'
        f'<p class="fh-pick-selection">{row["SELECCIÓN"]} · Cuota {row["CUOTA"]:.2f}</p>'
        f'<div class="fh-pick-ev-row">'
        f'<p class="fh-pick-ev {ev_tone}">{row["EV"]:+.1%}<span class="fh-pick-ev-sub">EV</span></p>'
        f'<p style="margin:0;font-size:12px;color:rgb(var(--ink2));">Score <b style="color:rgb(var(--ink));">{row["SCORE"]:.1f}</b></p></div>'
        f'<div class="fh-pick-meta">'
        f'<span>Prob. modelo <b>{row["PROB MOD"]:.1%}</b></span>'
        f'<span>Prob. mercado <b>{row["PROB MKT"]:.1%}</b></span>'
        f'<span>Edge <b>{row["EDGE"]:+.1%}</b></span>'
        f'<span>Stake <b>{row["STAKE"]}</b></span></div></div>'
    )


# ---------------------------------------------------------------------------
# Motor analítico (núcleo intacto). El análisis se ejecuta UNA sola vez por día
# y se guarda en disco (analisis_hoy.json). En cada refresco de la página se
# reutilizan esos mismos picks: NO se vuelve a analizar ni cambian los resultados.
# Solo se recalcula cuando cambia la fecha (nueva jornada).
# ---------------------------------------------------------------------------
def _analisis_es_de_hoy(bets):
    """True si los picks corresponden a los partidos programados para hoy.
    Detecta el caso en que la API entrega una jornada distinta a la esperada."""
    if not bets:
        return True
    try:
        juegos = fetcher_liga().get_live_scores()        # ya usa la fecha local
    except Exception:
        return True                                      # sin datos, no bloquear
    if not juegos:
        return True
    def _en(nombre, texto):                              # sin depender de helpers posteriores
        a, b2 = str(nombre).strip().lower(), str(texto).strip().lower()
        return a in b2 or b2 in a

    coinciden = sum(
        1 for b in bets
        if any(_en(g["away_team"], b["matchup"]) and _en(g["home_team"], b["matchup"])
               for g in juegos)
    )
    return coinciden >= max(1, len(bets) // 2)           # al menos la mitad


@st.cache_data(ttl=86400)
def linea_base_liga(clave):
    """Linea de totales a usar cuando la casa no publica una para el partido.

    El 8.5 de siempre esta calibrado para MLB, donde parte los partidos casi por
    la mitad (48.5% los supera). Aplicado a una liga mas anotadora convierte
    cualquier Over en ganador por construccion: en LMB el 59.3% de los partidos
    supera 8.5, asi que el motor "descubria" valor en los Over que en realidad
    venia de la linea equivocada.

    Se usa la MEDIANA de carreras totales de los ultimos 28 dias, que es la
    linea que parte la liga por la mitad. Solo afecta a partidos SIN cuota real:
    en MLB todos los partidos traen su linea, asi que no cambia nada.
    """
    cfg = LIGAS[clave]
    fijo = cfg.get("linea_base")
    if fijo:
        return float(fijo)
    if cfg.get("fuente") != "mlb":            # otras fuentes: sin serie historica barata
        return 8.5
    try:
        import statistics
        fin = now_local().date()
        ini = fin - timedelta(days=28)
        liga = f"&leagueId={cfg['league_id']}" if cfg.get("league_id") else ""
        url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId={cfg['sport_id']}{liga}"
               f"&startDate={ini}&endDate={fin}")
        datos = requests.get(url, timeout=15).json()
        totales = []
        for dia in datos.get("dates", []):
            for g in dia.get("games", []):
                if g.get("status", {}).get("abstractGameState") != "Final":
                    continue
                eq = g.get("teams", {})
                a, h = eq.get("away", {}).get("score"), eq.get("home", {}).get("score")
                if a is not None and h is not None:
                    totales.append(a + h)
        if len(totales) < 30:                 # muestra pobre: mejor no inventar
            return 8.5
        # A la media linea mas cercana, como las cuotas reales (8.5, 9.0, 9.5...)
        return round(statistics.median(totales) * 2) / 2
    except Exception:
        return 8.5


@st.cache_data(ttl=600)
def _partidos_listos(clave, dia):
    """Partidos del día que YA tienen los dos abridores anunciados."""
    try:
        juegos = _crear_fetcher(clave).get_todays_games(date=dia)
    except Exception:
        return []
    return [f'{g["away_team"]} @ {g["home_team"]}'
            for g in juegos if g.get("pitchers_confirmed")]


def get_todays_analysis():
    today = fecha_jornada()
    if os.path.exists(ANALYSIS_CACHE):
        try:
            with open(ANALYSIS_CACHE, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("day") == today and cached.get("bets"):
                guardados = {b["matchup"] for b in cached["bets"]}
                # Los partidos sin abridor anunciado no generan pick. Si alguno
                # ya lo tiene, se analiza AHORA y se suma; los picks que ya
                # estaban no se recalculan, para que no cambien despues de que
                # el usuario los haya visto o apostado.
                nuevos = [m for m in _partidos_listos(st.session_state.liga, today)
                          if m not in guardados]
                if not nuevos:
                    return cached["bets"]       # mismos picks del día, estables
                return _completar_analisis(cached["bets"], nuevos, today)
        except Exception:
            pass
    bets = _correr_motor(today)

    # SALVAGUARDA: verifica que los picks correspondan a los partidos de HOY.
    # Si la fuente de datos devolviera otra jornada (por ejemplo la de ayer, ya
    # jugada), los picks nacerian finalizados. En ese caso no se guardan.
    if not _analisis_es_de_hoy(bets):
        st.error(
            f"⚠️ El análisis no corresponde a la jornada del {today}: los partidos "
            "recibidos son de otra fecha. No se guardaron picks para evitar "
            "registrar resultados falsos. Vuelve a intentar en unos minutos."
        )
        return []

    _guardar_analisis(bets, today)
    return bets


def _correr_motor(dia):
    """Una corrida del motor para la jornada indicada.

    Semilla fija por fecha: el motor usa simulacion Monte Carlo (aleatoria), asi
    que dos equipos distintos daban picks distintos el mismo dia. Con esto, el
    mismo dia produce SIEMPRE el mismo resultado. No cambia ninguna formula:
    solo hace que el sorteo aleatorio sea reproducible.
    """
    try:
        import numpy as _np
        _np.random.seed(int(dia.replace("-", "")))
    except Exception:
        pass
    return get_analyzed_bets(fetcher_liga(),
                             con_cuotas_reales=LIGA["cuotas_reales"],
                             con_demo=(st.session_state.liga == "MLB"),
                             odds_sport=LIGA.get("odds_sport") or "baseball_mlb",
                             linea_por_defecto=linea_base_liga(st.session_state.liga))


def _guardar_analisis(bets, dia):
    try:
        with open(ANALYSIS_CACHE, "w", encoding="utf-8") as f:
            json.dump({"day": dia, "bets": bets}, f, ensure_ascii=False)
    except Exception:
        pass


def _completar_analisis(guardados, nuevos, dia):
    """Suma al analisis del dia los partidos cuyo abridor acaba de anunciarse.

    Los picks que ya estaban se conservan tal cual: solo se renumera el rank,
    que depende del conjunto. Asi un pick no cambia de probabilidad ni de cuota
    despues de que el usuario lo vio.
    """
    por_partido = {b["matchup"]: b for b in _correr_motor(dia)}
    sumados = [por_partido[m] for m in nuevos if m in por_partido]
    if not sumados:
        return guardados                     # anunciado pero aun sin cuotas
    bets = rank_bets(guardados + sumados)
    _guardar_analisis(bets, dia)
    return bets


sorted_bets = get_todays_analysis()
approved_picks = [b for b in sorted_bets if b["approved"]]
top_pick = sorted_bets[0] if sorted_bets else None

board_df = pd.DataFrame([{
    "RANK": b["rank"], "PARTIDO": b["matchup"], "MERCADO": b["market"],
    "SELECCIÓN": b["selection"], "CUOTA": b["odds"], "PROB MOD": b["prob_model"],
    "PROB MKT": b["prob_market"], "EDGE": b["edge"], "EV": b["ev"],
    "CONF": b["confidence"], "STAKE": b["stake"], "SCORE": b["score"],
    "RIESGO": b["risk"], "TAG": b["tag"],
} for b in sorted_bets])


# ---------------------------------------------------------------------------
# Persistencia — historial en un único archivo JSON (historial_apuestas.json).
# Ventajas: es portable (se puede respaldar/restaurar con un clic), sobrevive
# reinicios y no depende de una base de datos. El núcleo analítico no se toca.
# ---------------------------------------------------------------------------
def _read_history_file():
    """Lee el historial de la liga activa. Si no existe el archivo y la liga es
    MLB, migra la BD antigua (que solo contiene datos de MLB). Para el resto de
    ligas se empieza vacio: migrar ahi mezclaria partidos de otra liga."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("bets", []) if isinstance(data, dict) else data
        except Exception:
            return []
    if st.session_state.get("liga", "MLB") != "MLB":
        return []
    return _migrate_from_sqlite()


def _migrate_from_sqlite():
    """Migración única: pasa el historial de la BD SQLite antigua al JSON."""
    if not os.path.exists(DB_NAME):
        return []
    try:
        conn = sqlite3.connect(DB_NAME)
        rows = conn.execute(
            "SELECT id,date,matchup,selection,model_prob,market_prob,edge,odds,ev,"
            "kelly_stake,model_confidence,result,profit_loss FROM bet_history"
        ).fetchall()
        conn.close()
        cols = ["id", "date", "matchup", "selection", "model_prob", "market_prob", "edge",
                "odds", "ev", "kelly_stake", "model_confidence", "result", "profit_loss"]
        bets = [dict(zip(cols, r)) for r in rows]
        if bets:
            _write_history_file(bets)
        return bets
    except Exception:
        return []


def _write_history_file(bets):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"bets": bets}, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def sync_today_picks():
    """Registra los partidos analizados del día bajo la fecha de HOY. Funciona POR DÍA:
    si hoy ya se registraron no se duplican, y las jornadas anteriores se conservan
    (nunca se borran). Los picks NO BET (stake 0%) se guardan con beneficio 0."""
    bets = _read_history_file()
    today = fecha_jornada()
    # Deduplica por (partido, MERCADO), no por selección: un partido puede tener
    # a lo más un pick por mercado (ML, TOTAL, F5). Así ML + TOTAL del mismo juego
    # conviven, pero se bloquean picks contradictorios del MISMO mercado —p. ej.
    # Over 7.5 y Under 7.5— que en corridas a distinta hora se colaban como dos
    # selecciones distintas.
    existing_today = {(b["matchup"], b.get("market")) for b in bets
                      if str(b.get("date", "")).startswith(today)}
    next_id = max([int(b.get("id", 0)) for b in bets], default=0) + 1
    added = False
    for i, b in enumerate(sorted_bets):
        key = (b["matchup"], b["market"])
        if key in existing_today:
            continue  # ya registrado HOY: no duplicar mercado dentro del mismo día
        frac = float(str(b["stake"]).replace("%", "").strip() or 0) / 100.0  # "2%" -> 0.02
        bets.append({
            "id": next_id, "date": f"{today} 09:{i:02d}:00",
            "matchup": b["matchup"], "selection": b["selection"], "market": b["market"],
            "model_prob": b["prob_model"], "market_prob": b["prob_market"],
            "edge": b["edge"], "odds": b["odds"], "ev": b["ev"],
            "kelly_stake": frac, "model_confidence": b["confidence"],
            "result": "PENDING", "profit_loss": 0.0,
        })
        next_id += 1
        existing_today.add(key)
        added = True
    if added:
        _write_history_file(bets)


sync_today_picks()


def load_history():
    bets = _read_history_file()
    if not bets:
        return pd.DataFrame(columns=["id", "date", "matchup", "selection", "odds", "ev",
                                     "kelly_stake", "result", "profit_loss"])
    return pd.DataFrame(bets).sort_values("date", ascending=False)


def parse_stake_fraction(v):
    """Devuelve el stake como fracción del bankroll (0.02 = 2%)."""
    try:
        x = float(str(v).replace("%", "").strip())
    except (TypeError, ValueError):
        return 0.0
    return x / 100.0 if x > 1 else x   # "2%"/2 -> 0.02 ; 0.0269 se conserva


def update_result(bet_id, result, odds, kelly_stake):
    """Guarda el resultado y el P&L como FRACCIÓN del bankroll (independiente del monto)."""
    frac = parse_stake_fraction(kelly_stake)
    if result == "WON":
        pl = frac * (odds - 1)
    elif result == "LOST":
        pl = -frac
    else:
        pl = 0.0
    bets = _read_history_file()
    for b in bets:
        if int(b.get("id", -1)) == int(bet_id):
            b["result"] = result
            b["profit_loss"] = pl
            break
    _write_history_file(bets)


def _team_match(a, b):
    a, b = a.strip().lower(), b.strip().lower()
    return a in b or b in a


def find_final(matchup, games):
    for g in games:
        if g["is_final"] and _team_match(g["away_team"], matchup) and _team_match(g["home_team"], matchup):
            return g
    return None


def buscar_partido(matchup, games):
    """El partido del enfrentamiento en CUALQUIER estado (en vivo incluido).
    Con dobles carteleras se prefiere el que ya tiene accion."""
    candidatos = [g for g in games
                  if _team_match(g["away_team"], matchup)
                  and _team_match(g["home_team"], matchup)]
    if not candidatos:
        return None
    return next((g for g in candidatos if g["is_live"] or g["is_final"]), candidatos[0])


VENTAJA_PAGO_ANTICIPADO = 5          # carreras


def ventaja_maxima(g):
    """Mayor ventaja que llego a tener cada equipo -> (visitante, local).

    Se reconstruye medio inning a medio inning desde las carreras por entrada,
    no desde el marcador final. Asi se detecta la ventaja aunque la app no
    estuviera abierta en ese momento, y tambien en partidos ya terminados.
    """
    visitante = local = 0
    mejor_v = mejor_l = 0
    for carreras_v, carreras_l in (g.get("innings_runs") or []):
        visitante += carreras_v                      # cierre de la parte alta
        mejor_v, mejor_l = max(mejor_v, visitante - local), max(mejor_l, local - visitante)
        local += carreras_l                          # cierre de la parte baja
        mejor_v, mejor_l = max(mejor_v, visitante - local), max(mejor_l, local - visitante)
    # Marcador actual, por si la fuente no trae desglose por entradas
    v, l = g.get("away_score", 0) or 0, g.get("home_score", 0) or 0
    return max(mejor_v, v - l), max(mejor_l, l - v)


def cobro_anticipado(selection, g):
    """True si el equipo elegido llego a ir 5+ carreras arriba en algun momento.

    Es la promocion de pago anticipado: la casa liquida el moneyline como
    ganado en cuanto se alcanza esa ventaja, aunque el partido se voltee.
    """
    mejor_v, mejor_l = ventaja_maxima(g)
    if _team_match(selection, g["away_team"]):
        return mejor_v >= VENTAJA_PAGO_ANTICIPADO
    if _team_match(selection, g["home_team"]):
        return mejor_l >= VENTAJA_PAGO_ANTICIPADO
    return False


def settle_pick(matchup, selection, market, games):
    """Determina WON/LOST comparando la selección contra el resultado real.
    Devuelve None si el partido no ha finalizado o no se puede decidir."""
    import re
    sel = selection.lower()
    mkt = (market or "").upper()
    es_total = mkt == "TOTAL" or "under" in sel or "over" in sel
    es_f5 = mkt == "F5" or "f5" in sel or "first 5" in sel

    # PAGO ANTICIPADO (solo moneyline): se comprueba ANTES de exigir que el
    # partido haya terminado, para marcarlo en cuanto ocurre la ventaja.
    if not es_total and not es_f5:
        g = buscar_partido(matchup, games)
        if g and cobro_anticipado(selection, g):
            return "WON"

    g = find_final(matchup, games)
    if not g:
        return None

    if es_total:
        m = re.search(r"(\d+(?:\.\d+)?)", selection)
        line = float(m.group(1)) if m else 8.5
        total = g["away_score"] + g["home_score"]
        if total == line:
            return "PUSH"  # el total cae justo en la linea = devolucion
        if "under" in sel:
            return "WON" if total < line else "LOST"
        return "WON" if total > line else "LOST"   # over

    if es_f5:
        if g["innings_played"] < 5:
            return None
        af5, hf5 = g["away_f5"], g["home_f5"]
        if af5 == hf5:
            return "PUSH"  # empate en las primeras 5 entradas = devolución
        winner = g["home_team"] if hf5 > af5 else g["away_team"]
        return "WON" if _team_match(selection, winner) else "LOST"

    # Moneyline: la selección nombra al equipo
    if g["home_score"] == g["away_score"]:
        return "PUSH"  # finalizado en empate: no hay ganador, se devuelve
    winner = g["home_team"] if g["home_score"] > g["away_score"] else g["away_team"]
    return "WON" if _team_match(selection, winner) else "LOST"


@st.cache_data(ttl=900)
def _scores_date(dia, clave):
    return _crear_fetcher(clave).get_live_scores(date=dia)


def scores_for_date(dia):
    """Resultados de una fecha concreta (para cerrar picks de dias anteriores)."""
    return _scores_date(dia, st.session_state.liga)


def auto_settle_db(games):
    """Cierra automaticamente los picks pendientes cuyo partido ya finalizo.
    Consulta los resultados de LA FECHA de cada pick: los de jornadas anteriores
    ya no aparecen en la agenda de hoy, por eso se piden por separado."""
    bets = _read_history_file()
    hoy = fecha_jornada()
    changed = False
    por_fecha = {}   # cache local: fecha -> partidos de ese dia

    for b in bets:
        if b.get("result") != "PENDING":
            continue
        dia = str(b.get("date", ""))[:10]
        if dia == hoy:
            partidos = games                       # jornada actual, ya la tenemos
        else:
            if dia not in por_fecha:
                try:
                    por_fecha[dia] = scores_for_date(dia)
                except Exception:
                    por_fecha[dia] = []
            partidos = por_fecha[dia]
        if not partidos:
            continue
        r = settle_pick(b["matchup"], b["selection"], b.get("market"), partidos)
        if r in ("WON", "LOST", "PUSH"):
            frac = parse_stake_fraction(b.get("kelly_stake"))
            odds = float(b.get("odds", 0) or 0)
            b["result"] = r
            b["profit_loss"] = frac * (odds - 1) if r == "WON" else (-frac if r == "LOST" else 0.0)
            # Deja constancia de si se cobro por la ventaja de 5 carreras
            if r == "WON" and (b.get("market") or "").upper() not in ("TOTAL", "F5"):
                g = buscar_partido(b["matchup"], partidos)
                if g and cobro_anticipado(b["selection"], g):
                    b["pago_anticipado"] = True
            changed = True
    if changed:
        _write_history_file(bets)


def enrich_history(df, bankroll):
    """Añade columnas en unidades del bankroll: stake, beneficio y saldo acumulado."""
    df = df.sort_values("date").copy()
    df["stake_frac"] = df["kelly_stake"].apply(parse_stake_fraction)
    df["stake_units"] = df["stake_frac"] * bankroll
    df["pl_units"] = df["profit_loss"] * bankroll
    df["saldo"] = bankroll + df["pl_units"].cumsum()
    return df


@st.cache_data(ttl=60)
def _live_scores_mlb(clave):
    return _crear_fetcher(clave).get_live_scores()


def fetch_live_scores():
    return _live_scores_mlb(st.session_state.liga)


BANKROLL_INICIAL = 10000.0     # pesos, desde el dia 1


def bankroll_default():
    return float(st.session_state.get("bankroll_ini", BANKROLL_INICIAL))


def mxn(v, signo=False):
    """Formatea un monto en pesos: $1,234.56 (con separador de miles)."""
    return f"{'+' if signo and v > 0 else ''}${v:,.2f}"


# Cierre automático de picks contra los resultados reales de la MLB
auto_settle_db(fetch_live_scores())
LIVE_COUNT = len([g for g in fetch_live_scores() if g["is_live"]])


@st.cache_data(ttl=86400)
def mlb_team_ids():
    """Mapa nombre de equipo -> id para los logos. Incluye todas las ligas
    configuradas (MLB y LMB), asi los escudos salen en ambas."""
    ids = {}
    urls = ["https://statsapi.mlb.com/api/v1/teams?sportId=1"]
    for cfg in LIGAS.values():
        if cfg["sport_id"] == 1:
            continue
        liga = f"&leagueId={cfg['league_id']}" if cfg["league_id"] else ""
        urls.append(f"https://statsapi.mlb.com/api/v1/teams?sportId={cfg['sport_id']}{liga}")
    for u in urls:
        try:
            r = requests.get(u, timeout=8).json()
            ids.update({t["name"]: t["id"] for t in r.get("teams", [])})
        except Exception:
            pass
    return ids


def escudo_svg(nombre, size=22):
    """Escudo de respaldo para equipos sin logo en mlbstatic: circulo gris con
    las iniciales. Se dibuja como SVG embebido, sin enlaces externos."""
    palabras = [w for w in str(nombre).split() if w[:1].isalnum()]
    abbr = ("".join(w[0] for w in palabras[:3]) or "?").upper()
    color = "#64748B"
    fuente = 30 if len(abbr) <= 2 else 22
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
           f'<circle cx="32" cy="32" r="30" fill="{color}"/>'
           f'<text x="32" y="32" fill="#fff" font-family="Inter,Arial,sans-serif" '
           f'font-size="{fuente}" font-weight="700" text-anchor="middle" '
           f'dominant-baseline="central">{abbr}</text></svg>')
    import base64
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def logos_for_matchup(matchup):
    """Los dos logos de un enfrentamiento 'Visitante @ Local'."""
    ids = mlb_team_ids()
    partes = str(matchup).replace(" @ ", "|").replace(" vs ", "|").split("|")
    out = ""
    for p in partes[:2]:
        p = p.strip()
        tid = ids.get(p) or next((v for k, v in ids.items() if _team_match(k, p)), None)
        src = f"https://www.mlbstatic.com/team-logos/{tid}.svg" if tid else escudo_svg(p)
        out += f'<img src="{src}" alt=""/>'
    return out


def logo_for_team(name, games):
    """Devuelve el <img> del logo del equipo buscándolo en los partidos de la jornada."""
    for g in games:
        if _team_match(g["away_team"], name) and g["away_id"]:
            return team_logo(g["away_id"], g["away_team"])
        if _team_match(g["home_team"], name) and g["home_id"]:
            return team_logo(g["home_id"], g["home_team"])
    return f'<img class="fh-score-logo" src="{escudo_svg(name)}" alt=""/>'


def opponent_of(matchup, selection):
    parts = matchup.replace(" @ ", "|").replace(" vs ", "|").split("|")
    if len(parts) == 2:
        for p in parts:
            if not _team_match(p, selection):
                return p.strip()
    return ""


def board_odds_for(g):
    for _, r in board_df.iterrows():
        if _team_match(g["away_team"], r["PARTIDO"]) and _team_match(g["home_team"], r["PARTIDO"]):
            return float(r["CUOTA"])
    return None


def pick_logos_html(bet, games, size=62):
    """Logo(s) del pick: el equipo elegido (ML/F5) o ambos equipos (TOTAL)."""
    g = next((x for x in games
              if _team_match(x["away_team"], bet["matchup"])
              and _team_match(x["home_team"], bet["matchup"])), None)
    if g is None:
        return ""
    img = ('<img src="https://www.mlbstatic.com/team-logos/{tid}.svg" alt="" '
           f'style="width:{size}px;height:{size}px;object-fit:contain;"/>')
    if bet["market"] == "TOTAL":   # sin equipo elegido: se muestran los dos
        return img.format(tid=g["away_id"]) + img.format(tid=g["home_id"])
    tid = g["home_id"] if _team_match(bet["selection"], g["home_team"]) else g["away_id"]
    return img.format(tid=tid)


def live_pick_status(bet, g):
    """Como va el PICK con el marcador actual, en partidos en vivo.
    Devuelve 'win' (va ganando), 'lose' (va perdiendo), 'tie' (empate/0-0) o None."""
    import re
    if not bet or not g.get("is_live"):
        return None
    sel = str(bet["selection"]).lower()
    mkt = str(bet.get("market") or "").upper()

    if mkt == "TOTAL" or "over" in sel or "under" in sel:
        m = re.search(r"(\d+(?:\.\d+)?)", str(bet["selection"]))
        line = float(m.group(1)) if m else 8.5
        total = g["away_score"] + g["home_score"]
        if total == line:
            return "tie"
        if "under" in sel:
            return "win" if total < line else "lose"
        return "win" if total > line else "lose"

    # ML / F5: se compara el equipo elegido contra quien va arriba
    if g["home_score"] == g["away_score"]:
        return "tie"
    lider = g["home_team"] if g["home_score"] > g["away_score"] else g["away_team"]
    return "win" if _team_match(bet["selection"], lider) else "lose"


def pick_label(bet):
    """Etiqueta legible del pick: 'Braves ML', 'Over 8.5', 'Guardians F5'."""
    sel, mkt = bet["selection"], bet["market"]
    if mkt == "ML":
        return f"{sel} ML"
    return sel  # TOTAL ('Over 8.5') y F5 ('... F5') ya vienen descriptivos


def build_parlay(bets, games, min_prob=0.50, max_legs=6):
    """BET IA decide cuantas patas lleva el parlay.
    Agrega selecciones (de mayor a menor probabilidad, solo picks aprobados)
    mientras la probabilidad COMBINADA siga por encima del umbral (50% por
    defecto). Si ni siquiera con 2 patas se supera ese umbral, no hay parlay:
    lo correcto es no apostar."""
    aprobados = sorted([b for b in bets if b.get("approved")],
                       key=lambda b: -float(b["prob_model"]))
    if len(aprobados) < 2:
        return None

    patas, prob = [], 1.0
    for b in aprobados[:max_legs]:
        p_next = prob * float(b["prob_model"])
        if len(patas) >= 2 and p_next < min_prob:
            break                      # agregar esta pata bajaria del umbral
        patas.append(b)
        prob = p_next

    if len(patas) < 2 or prob < min_prob:
        return None                    # NO APOSTAR: ninguna combinacion es segura

    cuota = 1.0
    prob_mercado = 1.0
    for b in patas:
        cuota *= float(b["odds"])
        prob_mercado *= 1.0 / float(b["odds"])   # lo que implica la cuota
        b["_res"] = settle_pick(b["matchup"], b["selection"], b["market"], games)

    if any(b["_res"] == "LOST" for b in patas):
        estado = "LOST"
    elif all(b["_res"] == "WON" for b in patas):
        estado = "WON"
    else:
        estado = "PENDING"

    return {
        "patas": patas,
        "prob": prob,                      # segun el MODELO
        "prob_mercado": prob_mercado,      # segun las CUOTAS de las casas
        "cuota": round(cuota, 2),
        "ev": prob * cuota - 1.0,
        "estado": estado,
        "ganadas": sum(1 for b in patas if b["_res"] == "WON"),
    }


def parlay_card_html(p, games):
    """Tarjeta del parlay con checklist por pata."""
    if not p:
        return (card_header("El Parlay de Hoy", "Sin combinación segura", "trophy",
                            badge("🚫 NO APOSTAR", "fare"))
                + '<p style="color:rgb(var(--ink2));margin:0;font-size:13px;">'
                'Ninguna combinación de 2 o más picks supera el 50% de probabilidad. '
                'Lo correcto hoy es no armar parlay.</p></div></div>')

    est = {
        "WON": (badge("✅ GANADO", "save"), "won"),
        "LOST": (badge("❌ PERDIDO", "fare"), "lost"),
        "PENDING": (badge(f'⏳ {p["ganadas"]}/{len(p["patas"])} listas', "warn"), ""),
    }[p["estado"]]

    filas = ""
    for b in p["patas"]:
        r = b.get("_res")
        cls, ico = {"WON": ("won", "✓"), "LOST": ("lost", "✗"),
                    "PUSH": ("push", "=")}.get(r, ("pend", ""))
        filas += (
            f'<div class="pl-leg {cls}">'
            f'<span class="pl-check {cls}">{ico}</span>'
            f'<span class="pl-logo">{logo_for_team(b["selection"], games)}</span>'
            f'<div class="pl-txt"><b>{pick_label(b)}</b>'
            f'<span>{b["matchup"]}</span></div>'
            f'<span class="pl-prob">{b["prob_model"]:.0%}</span>'
            f'<span class="pl-odds">{b["odds"]:.2f}</span></div>'
        )

    return (
        card_header("El Parlay de Hoy",
                    f'{len(p["patas"])} patas · elegidas por BET IA para superar el 50%',
                    "trophy", est[0])
        + f'<div class="pl-legs {est[1]}">{filas}</div>'
        + f'<div class="pl-foot">'
        f'<div><span>Prob. modelo</span><b class="pos">{p["prob"]:.1%}</b></div>'
        f'<div><span>Prob. mercado</span><b>{p["prob_mercado"]:.1%}</b></div>'
        f'<div><span>Cuota</span><b>{p["cuota"]:.2f}</b></div>'
        f'<div><span>EV</span><b class="{"pos" if p["ev"] > 0 else "neg"}">{p["ev"]:+.1%}</b></div>'
        f'</div></div></div>'
    )


@st.cache_data(ttl=1800)
def records_abridores(clave, ids):
    """Récord ganados-perdidos de los abridores, en UNA sola llamada.

    `ids` llega como tupla para que Streamlit pueda cachearlo. El endpoint
    /people acepta hasta la jornada entera de golpe (31 lanzadores en una
    peticion), asi que no se consulta uno por uno.
    """
    cfg = LIGAS[clave]
    ids = tuple(dict.fromkeys(i for i in ids if i))
    if not ids:
        return {}
    try:
        url = (f"https://statsapi.mlb.com/api/v1/people?personIds={','.join(map(str, ids))}"
               f"&hydrate=stats(group=[pitching],type=[season],"
               f"sportId={cfg['sport_id']},season={now_local().year})")
        gente = requests.get(url, timeout=15).json().get("people", [])
    except Exception:
        return {}
    salida = {}
    for p in gente:
        try:
            s = p["stats"][0]["splits"][0]["stat"]
            salida[p["id"]] = f'{int(s.get("wins", 0))}-{int(s.get("losses", 0))}'
        except Exception:
            continue                      # abridor sin temporada registrada
    return salida


def abridor_corto(nombre):
    """'Jesús Luzardo' -> 'Luzardo J.', como en los marcadores deportivos."""
    partes = [w for w in str(nombre).split() if w]
    if len(partes) < 2:
        return partes[0] if partes else ""
    return f"{partes[-1]} {partes[0][0]}."


def pitchers_html(g, records):
    """Linea de abridores bajo el partido: 'Gusto R. [MIA] (0-2)'."""
    trozos = []
    for lado in ("away", "home"):
        nombre = g.get(f"{lado}_pitcher")
        if not nombre:
            continue
        rec = records.get(g.get(f"{lado}_pitcher_id"))
        abbr = g.get(f"{lado}_abbr")
        trozos.append(
            f'<span class="pit">{abridor_corto(nombre)}'
            + (f'<i>{abbr}</i>' if abbr else "")
            + (f'<b>({rec})</b>' if rec else "")
            + '</span>')
    if not trozos:
        return ""
    return f'<small class="lv-pit"><em>Pitchers:</em>{"".join(trozos)}</small>'


def build_matchday_rows(games, bets):
    """Une la agenda real y los picks en UNA fila por partido (sin duplicados).
    Orden: En vivo primero, luego próximos por hora, y al final los finalizados."""
    rows = []
    for g in games:
        bet = next((b for b in bets
                    if _team_match(g["away_team"], b["matchup"])
                    and _team_match(g["home_team"], b["matchup"])), None)
        result = settle_pick(bet["matchup"], bet["selection"], bet["market"], games) if bet else None
        if g["is_live"]:
            estado, orden = "live", 0
        elif g["is_final"]:
            estado, orden = "final", 2
        else:
            estado, orden = "prev", 1
        rows.append({
            "orden": orden, "estado": estado, "game": g, "bet": bet, "result": result,
            "hora": (f'{inning_abbr(g["inning_state"])} {g["inning_ordinal"]}'
                     if g["is_live"] else fmt_start(g["start_utc"])),
            "pick": pick_label(bet) if bet else "",
            "prob": float(bet["prob_model"]) if bet else -1.0,
            "ev": float(bet["ev"]) if bet else -999.0,
        })
    # Orden: mayor EV primero; los partidos sin pick quedan al final
    rows.sort(key=lambda r: (-r["ev"], r["game"].get("start_utc") or ""))
    return rows


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
PAGES = [
    ("space_dashboard", "grid", "Dashboard"),
    ("sensors", "sensors", "En vivo"),
    ("receipt_long", "receipt", "Resultados"),
    ("leaderboard", "trophy", "Rendimiento"),
]
if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

with st.sidebar:
    st.markdown(
        '<div class="sb-brand">'
        + (f'<img class="sb-logo-img" src="{_logo_data_uri()}" alt="BET IA"/>'
           if _logo_data_uri() else '<div class="sb-logo">' + svg("bar", 22) + '</div>')
        + '<div><p class="sb-name">BET IA</p>'
        '<p class="sb-tag">Radar multideporte · Quant</p></div></div>',
        unsafe_allow_html=True,
    )

    # --- Selector de liga ---
    st.markdown('<p class="sb-lbl">Liga</p>', unsafe_allow_html=True)
    cols = st.columns(len(LIGAS))
    for col, (clave, cfg) in zip(cols, LIGAS.items()):
        activa = st.session_state.liga == clave
        if col.button(cfg["nombre"], key=f"liga_{clave}", use_container_width=True,
                      type="primary" if activa else "secondary"):
            st.session_state.liga = clave
            st.rerun()
    st.markdown('<div class="sb-sep"></div>', unsafe_allow_html=True)
    for micon, _, label in PAGES:
        active = st.session_state.page == label
        if st.button(f":material/{micon}: {label}", key=f"nav_{label}", use_container_width=True,
                     type="primary" if active else "secondary"):
            st.session_state.page = label
            st.rerun()

    live_now = [x for x in fetch_live_scores() if x["is_live"]]
    now = hora12(now_local(), con_segundos=True)
    st.markdown(
        f'<div style="margin-top:16px;padding-top:14px;border-top:1px solid rgb(var(--dkline));">'
        f'<p style="font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;'
        f'color:rgb(var(--dkink2));margin-bottom:8px;">Estado de la jornada</p>'
        f'<p style="font-size:13.5px;margin:3px 0;">🟢 <b>{len(live_now)}</b> en vivo ahora</p>'
        f'<p style="font-size:13.5px;margin:3px 0;">🎯 <b>{len(approved_picks)}</b> picks aprobados</p>'
        f'<p style="font-size:12px;color:rgb(var(--dkink2));margin-top:6px;">Sync: {now}</p></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="fh-sys" style="margin-top:16px;">'
        f'<div class="fh-sys-row"><h4>Sistema</h4>{badge("Operativo", "save")}</div>'
        f'<p class="lab">Última actualización</p><p class="val">{now}</p>'
        f'<p class="lab">Versión</p><p class="val">{VERSION}</p></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# PÁGINA: Dashboard
# ---------------------------------------------------------------------------
def render_dashboard():
    topbar("Dashboard Ejecutivo", "Motor multi-agente → Chief Tipster", "share")

    live = fetch_live_scores()
    live_now = [g for g in live if g["is_live"]]
    prev = [g for g in live if not g["is_live"] and not g["is_final"]]
    hist = load_history()
    settled = hist[hist["result"] != "PENDING"] if not hist.empty else hist
    net = (hist["profit_loss"].sum() * bankroll_default()) if not hist.empty else 0.0

    c = st.columns(4, gap="large")
    stat_tile(c[0], "Partidos analizados", str(len(sorted_bets)), "jornada de hoy", True, "contrast", "fare")
    stat_tile(c[1], "Picks aprobados", str(len(approved_picks)), "+EV detectado", True, "target", "fare")
    stat_tile(c[2], "En vivo ahora", str(len(live_now)), "marcadores activos", len(live_now) > 0, "radio", "save")
    stat_tile(c[3], "P&L acumulado", mxn(net, signo=True), "pesos netos", net >= 0, "dollar", "warn")
    st.markdown("<div style='height:32px'></div>", unsafe_allow_html=True)

    tp, dg = st.columns(2, gap="large")
    with tp:
        st.markdown(
            card_header("Top Pick del Día", top_pick["matchup"], "flame",
                        badge(top_pick["market"], TONE_MARKET.get(top_pick["market"], "neutral"))
                        + badge("MLB", "neutral"), hl=True)
            + '<div class="tp-hero"><div class="tp-info">'
            + f'<p style="font-size:30px;font-weight:800;letter-spacing:-.02em;color:rgb(var(--save));margin:0;">'
            f'{top_pick["ev"]:+.1%} <span style="font-size:12px;font-weight:500;color:rgb(var(--ink2));">EV esperado</span></p>'
            f'<p style="margin:8px 0 0 0;font-size:13.5px;color:rgb(var(--ink2));">'
            f'Selección: <b style="color:rgb(var(--ink));">{top_pick["selection"]}</b> · Cuota {top_pick["odds"]:.2f} · '
            f'Prob. modelo {top_pick["prob_model"]:.1%} · Score {top_pick["score"]}/100 · Confianza {top_pick["confidence"]}/10</p>'
            + '</div>'
            + f'<div class="tp-logo">{pick_logos_html(top_pick, live)}</div></div>'
            + f'<div class="tp-bars">'
            f'<div class="tp-bar"><span>Prob. modelo</span><div class="tp-track">'
            f'<i style="width:{min(100, top_pick["prob_model"]*100):.0f}%;background:rgb(var(--save));"></i></div>'
            f'<b>{top_pick["prob_model"]:.0%}</b></div>'
            f'<div class="tp-bar"><span>Prob. mercado</span><div class="tp-track">'
            f'<i style="width:{min(100, top_pick["prob_market"]*100):.0f}%;background:rgb(var(--ink2));"></i></div>'
            f'<b>{top_pick["prob_market"]:.0%}</b></div>'
            f'<div class="tp-bar"><span>Score</span><div class="tp-track">'
            f'<i style="width:{min(100, top_pick["score"]):.0f}%;background:rgb(var(--accent));"></i></div>'
            f'<b>{top_pick["score"]:.0f}</b></div></div>'
            f'<div style="border-top:1px solid rgb(var(--line));margin-top:14px;padding-top:12px;font-size:13px;color:rgb(var(--ink2));line-height:1.7;">'
            f'<p style="margin:0;">🎯 <b style="color:rgb(var(--ink));">Pitching:</b> {top_pick["pitching"]}</p>'
            f'<p style="margin:0;">🛡️ <b style="color:rgb(var(--ink));">Bullpen:</b> {top_pick["bullpen"]}</p>'
            f'<p style="margin:0;">⚔️ <b style="color:rgb(var(--ink));">Ofensiva:</b> {top_pick["offense"]}</p>'
            f'<p style="margin:0;">🏛️ <b style="color:rgb(var(--ink));">Mercado:</b> {top_pick["movement"]}</p></div></div></div>',
            unsafe_allow_html=True,
        )
    with dg:
        roi = "+4.2%" if approved_picks else "0.0%"
        status = "Oportunidades encontradas" if approved_picks else "Sin valor detectado"
        st_tone = "save" if approved_picks else "fare"
        wr = (settled["result"].eq("WON").sum() / len(settled) * 100) if len(settled) else 0.0
        st.markdown(
            card_header("Chief Tipster Decision", "Director general del sistema multi-agente", "crown",
                        badge(status, st_tone))
            + f'<p style="font-size:22px;font-weight:800;letter-spacing:-.02em;color:rgb(var(--ink));margin:0;line-height:1.1;">'
            f'{len(approved_picks)} <span style="font-size:11.5px;font-weight:500;color:rgb(var(--ink2));">picks aprobados hoy</span></p>'
            f'<div class="ct-grid">'
            f'<div><p>Mejor mercado</p><b>{top_pick["market"]}</b></div>'
            f'<div><p>ROI esperado</p><b style="color:rgb(var(--save));">{roi}</b></div>'
            f'<div><p>Win rate histórico</p><b>{wr:.0f}%</b></div>'
            f'<div><p>Riesgo global</p><b style="color:rgb(var(--save));">Controlado</b></div>'
            f'</div></div></div>',
            unsafe_allow_html=True,
        )
        # El parlay va aqui, aprovechando el espacio libre bajo el Chief Tipster
        st.markdown(parlay_card_html(build_parlay(sorted_bets, live), live),
                    unsafe_allow_html=True)

    # Los marcadores en vivo viven en la pestaña "En Vivo".

    if st.button("Ver todos los partidos", key="see_games", type="secondary", use_container_width=True):
        st.session_state.page = "En vivo"
        st.rerun()


# ---------------------------------------------------------------------------
# PÁGINA: En Vivo
# ---------------------------------------------------------------------------
MARKET_LABEL = {"ML": "Moneyline", "TOTAL": "Total", "F5": "Primeros 5"}


def start_countdown(g):
    """Texto de la columna Inicio: cuenta regresiva, inning en curso o 'Finalizado'."""
    if g["is_live"]:
        return f'{inning_abbr(g["inning_state"])} {g["inning_ordinal"]}'
    if g["is_final"]:
        return "Finalizado"
    try:
        dt = datetime.fromisoformat(g["start_utc"].replace("Z", "+00:00"))
        dt = dt.astimezone(_TZ) if _TZ else dt.astimezone()
        mins = int((dt - now_local()).total_seconds() // 60)
    except Exception:
        return ""
    if mins <= 0:
        return "Por comenzar"
    h, m = divmod(mins, 60)
    return f"Empieza en {h} h {m} min" if h else f"Empieza en {m} min"


def live_detail_html(r):
    """Panel expandible (DETALLE) de una fila: desglose del pick o abridores."""
    g, bet = r["game"], r["bet"]
    pitchers = (f'<div><p>Abridor visitante</p><b>{g["away_pitcher"] or "Por confirmar"}</b></div>'
                f'<div><p>Abridor local</p><b>{g["home_pitcher"] or "Por confirmar"}</b></div>')
    if not bet:
        return (f'<div class="lv-detail"><div class="lv-dgrid">{pitchers}</div>'
                '<p style="margin:8px 0 0 0;">Sin pick del modelo para este partido.</p></div>')
    return (
        '<div class="lv-detail"><div class="lv-dgrid">'
        f'<div><p>Prob. mercado</p><b>{bet["prob_market"]:.1%}</b></div>'
        f'<div><p>Edge</p><b>{bet["edge"]:+.1%}</b></div>'
        f'<div><p>Score</p><b>{bet["score"]:.0f}/100</b></div>'
        f'<div><p>Confianza</p><b>{bet["confidence"]:.1f}/10</b></div>'
        f'<div><p>Riesgo</p><b>{bet["risk"]}</b></div>'
        f'{pitchers}</div>'
        '<div class="lv-notes">'
        f'<p>🎯 <b>Pitcheo:</b> {bet["pitching"]}</p>'
        f'<p>🛡️ <b>Bullpen:</b> {bet["bullpen"]}</p>'
        f'<p>⚔️ <b>Ofensiva:</b> {bet["offense"]}</p>'
        f'<p>🏛️ <b>Mercado:</b> {bet["movement"]}</p></div></div>'
    )


def live_table_row(r, records=None):
    """Fila expandible: Hora/Estado/Partido/Marcador/Pick IA/Prob/Cuota/EV/Inicio/Detalle."""
    g, bet = r["game"], r["bet"]
    estado_badge = {
        "live": badge("EN VIVO", "live"),
        "prev": badge("PRÓXIMO", "blue"),
        "final": badge("FINALIZADO", "neutral"),
    }[r["estado"]]

    if r["estado"] in ("live", "final"):
        marc_cls = "live" if r["estado"] == "live" else "final"
        marcador = f'<span class="lv-marc {marc_cls}">{g["away_score"]}<i>-</i>{g["home_score"]}</span>'
        marc_sub = f'{inning_abbr(g["inning_state"])} {g["inning_ordinal"]}' if r["estado"] == "live" else "Final"
    else:
        marcador = '<span class="lv-marc">-<i>-</i>-</span>'
        marc_sub = "Por comenzar"

    if bet:
        ev_cls = "pos" if bet["ev"] > 0 else "neg"
        pick_html = (f'<span class="pick-nm">{r["pick"]}</span>'
                     f'<span class="pick-mkt">{MARKET_LABEL.get(bet["market"], bet["market"])}</span>')
        prob_td, odds_td = f'{bet["prob_model"]:.0%}', f'{bet["odds"]:.2f}'
        ev_td = f'<span class="ev {ev_cls}">{bet["ev"]:+.1%}</span>'
        stake_val = str(bet.get("stake", "0%"))
        stk_cls = "off" if stake_val.strip() in ("0%", "0", "") else "on"
        stake_td = f'<span class="stk {stk_cls}">{stake_val}</span>'
    else:
        pick_html = '<span class="vacio">—</span>'
        prob_td = odds_td = ev_td = stake_td = '<span class="vacio">—</span>'

    vivo = live_pick_status(bet, g)
    res_cls = {"WON": " v-win", "LOST": " v-lose", "PUSH": " v-tie"}.get(r["result"], "")
    if not res_cls and vivo:
        res_cls = f" v-{vivo}"

    if bet is None:
        resultado_dot = '<span class="fh-tres empty"></span>'
    else:
        res_ico_cls, res_ico = {"WON": ("won", "✓"), "LOST": ("lost", "✗"),
                                 "PUSH": ("push", "=")}.get(r["result"], ("pend", "•"))
        resultado_dot = f'<span class="fh-tres {res_ico_cls}">{res_ico}</span>'

    return (
        f'<details class="lv-row lv-body {r["estado"]}{res_cls}">'
        f'<summary class="lv-sum lv-cols">'
        f'<span class="c-hora">{r["hora"]}</span>'
        f'<span class="c-est">{estado_badge}</span>'
        f'<span class="c-part"><span class="teams">{team_logo(g["away_id"], g["away_team"])}'
        f'<span class="t">{g["away_team"]}</span><span class="vs">vs</span>'
        f'{team_logo(g["home_id"], g["home_team"])}<span class="t">{g["home_team"]}</span></span>'
        f'{pitchers_html(g, records or {})}</span>'
        f'<span class="c-marc">{marcador}<small>{marc_sub}</small></span>'
        f'<span class="c-pick">{pick_html}</span>'
        f'<span class="c-prob num">{prob_td}</span>'
        f'<span class="c-cuota num">{odds_td}</span>'
        f'<span class="c-ev num">{ev_td}</span>'
        f'<span class="c-stake num">{stake_td}</span>'
        f'<span class="c-inicio">{start_countdown(g)}</span>'
        f'<span class="c-det">{resultado_dot}<span class="lv-chev">{svg("chevron", 15)}</span></span>'
        f'</summary>{live_detail_html(r)}</details>'
    )


def render_en_vivo():
    """Radar de partidos: tabla unificada con marcador, pick IA y detalle expandible."""
    live = fetch_live_scores()
    if not live:
        st.markdown('<div class="fh-card"><div class="fh-card-body">'
                    '<p style="color:rgb(var(--ink2));margin:0;">No hay datos de la jornada '
                    'disponibles ahora mismo.</p></div></div>', unsafe_allow_html=True)
        return

    if "lv_filter" not in st.session_state:
        st.session_state.lv_filter = "todos"
    if "lv_last_fetch" not in st.session_state:
        st.session_state.lv_last_fetch = now_local()

    en_vivo_n = sum(1 for g in live if g["is_live"])
    prox_n = sum(1 for g in live if not g["is_live"] and not g["is_final"])
    fin_n = sum(1 for g in live if g["is_final"])

    top_l, top_r = st.columns([3, 2], gap="large")
    with top_l:
        liga_logo = f'https://www.mlbstatic.com/team-logos/league-on-light/{LIGA["logo_id"]}.svg'
        st.markdown(f'<div class="lv-brand"><img src="{liga_logo}" alt=""/>'
                    f'<b>{LIGA["nombre"]}</b></div>', unsafe_allow_html=True)
        pc = st.columns(4, gap="small")
        for col, (clave, etiqueta, n) in zip(pc, [
            ("todos", "PARTIDOS", len(live)), ("prev", "PRÓXIMOS", prox_n),
            ("live", "EN VIVO", en_vivo_n), ("final", "FINALIZADOS", fin_n),
        ]):
            activo = st.session_state.lv_filter == clave
            if col.button(f"{n} {etiqueta}", key=f"lv_f_{clave}", use_container_width=True,
                          type="primary" if activo else "secondary"):
                st.session_state.lv_filter = clave
                st.rerun()
    with top_r:
        s1, s2, s3 = st.columns([3, 1, 1.3])
        busqueda = s1.text_input("Buscar", key="lv_search", placeholder="Buscar partido o equipo...",
                                  label_visibility="collapsed")
        if s2.button("🔄", key="lv_refresh", use_container_width=True, help="Actualizar"):
            fetch_live_scores.clear()
            st.session_state.lv_last_fetch = now_local()
            st.rerun()
        with s3.popover("⚙️ Filtros", use_container_width=True):
            st.checkbox("Solo partidos con Pick IA", key="lv_solo_pick")
            st.multiselect("Mercado", ["ML", "TOTAL", "F5"], default=["ML", "TOTAL", "F5"], key="lv_mercados")

    elapsed = int((now_local() - st.session_state.lv_last_fetch).total_seconds())
    st.markdown(
        f'<p class="lv-status">{svg("target", 13)} Ordenados por EV'
        f'<span class="lv-dot">·</span>{svg("info", 13)} Actualizado hace {elapsed}s'
        f'<span class="lv-dot">·</span>{now_local().strftime("%d/%m/%Y")}</p>',
        unsafe_allow_html=True)

    juegos = live
    filtro = st.session_state.lv_filter
    if filtro == "prev":
        juegos = [g for g in juegos if not g["is_live"] and not g["is_final"]]
    elif filtro == "live":
        juegos = [g for g in juegos if g["is_live"]]
    elif filtro == "final":
        juegos = [g for g in juegos if g["is_final"]]
    if busqueda.strip():
        q = busqueda.strip().lower()
        juegos = [g for g in juegos if q in g["away_team"].lower() or q in g["home_team"].lower()]

    md_rows = build_matchday_rows(juegos, sorted_bets)
    if st.session_state.get("lv_solo_pick"):
        md_rows = [r for r in md_rows if r["bet"]]
    mercados_sel = st.session_state.get("lv_mercados") or ["ML", "TOTAL", "F5"]
    md_rows = [r for r in md_rows if not r["bet"] or r["bet"]["market"] in mercados_sel]

    # Records de los abridores de TODA la jornada de una sola vez (no por fila)
    ids = tuple(g[k] for g in live for k in ("away_pitcher_id", "home_pitcher_id")
                if g.get(k))
    records = records_abridores(st.session_state.liga, ids)

    st.markdown(
        '<div class="lv-tablewrap">'
        '<div class="lv-head lv-cols">'
        '<span class="c-hora">Hora <small>Local</small></span><span class="c-est">Estado</span>'
        '<span class="c-part">Partido</span><span class="c-marc">Marcador</span>'
        '<span class="c-pick">Pick IA</span><span class="c-prob num">Prob.</span>'
        '<span class="c-cuota num">Cuota</span><span class="c-ev num">EV</span>'
        '<span class="c-stake num">Stake</span>'
        '<span class="c-inicio">Inicio</span><span class="c-det">Detalle</span></div>'
        + ("".join(live_table_row(r, records) for r in md_rows) if md_rows else
           '<p style="padding:18px;color:rgb(var(--ink2));margin:0;">Sin partidos para este filtro.</p>')
        + '</div>',
        unsafe_allow_html=True)

    st.markdown(
        '<p class="lv-legend">'
        '<span><span class="dot live"></span>En Vivo</span>'
        '<span><span class="dot blue"></span>Próximo</span>'
        '<span><span class="dot neutral"></span>Finalizado</span>'
        '<span><span class="dot warn"></span>Retrasado</span>'
        '</p>', unsafe_allow_html=True)
    st.caption(f"Datos en caché 60s · última lectura {hora12(now_local(), con_segundos=True)}")


# ---------------------------------------------------------------------------
# PÁGINA: Resultados
# ---------------------------------------------------------------------------
def result_badge(r):
    if r == "WON":
        return badge("✅ Ganado", "save")
    if r == "LOST":
        return badge("❌ Perdido", "fare")
    return badge("⏳ Pendiente", "warn")


RES_MAP = {"WON": "Ganado", "LOST": "Perdido", "PENDING": "Pendiente", "PUSH": "Push"}


def table_height(n_filas):
    """Alto para mostrar todas las filas sin scroll interno.
    Formula de Streamlit: encabezado 38px + 35px por fila (+2 de margen)."""
    return 40 + 35 * max(1, int(n_filas))


def _style_pl(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x > 0:
        return "color:#0e9e63;font-weight:700;"
    if x < 0:
        return "color:#d63838;font-weight:700;"
    return ""


def _style_res(v):
    if v == "Ganado":
        return "background-color:rgba(14,158,99,.16);color:#0e9e63;font-weight:700;"
    if v == "Perdido":
        return "background-color:rgba(214,56,56,.14);color:#d63838;font-weight:700;"
    return "color:#b97b00;font-weight:600;"


def render_resultados():
    st.markdown(
        f'<div class="rt-head"><div class="rt-head-ico">{svg("receipt", 22)}</div>'
        f'<div><h2>Resultados</h2><p>Resumen de rendimiento y detalle por apuesta</p></div></div>',
        unsafe_allow_html=True)

    hist = load_history()
    if hist.empty:
        st.info("Aún no hay picks registrados en el historial.")
        return

    live = fetch_live_scores()
    auto_settle_db(live)  # cierra lo que ya finalizó
    hist = load_history()

    ini = st.number_input("Bankroll inicial (pesos)", min_value=100.0,
                          value=bankroll_default(), step=500.0, format="%.2f",
                          key="bankroll_ini")

    en = enrich_history(hist, ini)
    settled = en[en["result"] != "PENDING"]
    wins = int((en["result"] == "WON").sum())
    losses = int((en["result"] == "LOST").sum())
    pend = int((en["result"] == "PENDING").sum())
    wr = (wins / len(settled) * 100) if len(settled) else 0.0
    net = float(en["pl_units"].sum())
    saldo = float(en["saldo"].iloc[-1])

    st.markdown(
        f'<p style="color:rgb(var(--ink2));font-size:13px;margin:2px 0 12px 0;">'
        f'✅ El sistema cierra los picks solo cuando el partido finaliza (moneyline, total y F5). '
        f'{pend} pendiente(s) · {wins} ganado(s) · {losses} perdido(s).</p>',
        unsafe_allow_html=True)

    c = st.columns(4, gap="large")
    stat_tile(c[0], "Ganados", str(wins), "resultados +", True, "trophy", "save")
    stat_tile(c[1], "Perdidos", str(losses), "resultados -", False, "target", "warn")
    stat_tile(c[2], "Win rate", f"{wr:.1f}%", f"{len(settled)} resueltos", wr >= 50, "bar", "accent")
    stat_tile(c[3], "Saldo actual", mxn(saldo), f"{mxn(net, signo=True)} neto", net >= 0, "dollar", "warn")

    # ---- Tabla Excel 1: resumen diario ----
    en["dia"] = en["date"].astype(str).str[:10]

    def agg_day(d):
        st_settled = d[d["result"] != "PENDING"]["stake_units"].sum()
        ben = d["pl_units"].sum()
        return pd.Series({
            "Apuestas": len(d),
            "Ganados": int((d["result"] == "WON").sum()),
            "Perdidos": int((d["result"] == "LOST").sum()),
            "Pendientes": int((d["result"] == "PENDING").sum()),
            "Beneficio": ben,
            "ROI %": (ben / st_settled * 100) if st_settled else 0.0,
        })

    daily = en.groupby("dia").apply(agg_day, include_groups=False).reset_index().rename(columns={"dia": "Fecha"})
    daily = daily.sort_values("Fecha")
    daily["Saldo"] = ini + daily["Beneficio"].cumsum()
    daily = daily[["Fecha", "Apuestas", "Ganados", "Perdidos", "Pendientes", "Beneficio", "Saldo", "ROI %"]]
    for col in ["Apuestas", "Ganados", "Perdidos", "Pendientes"]:
        daily[col] = daily[col].astype(int)

    page_section("Resumen diario", "Haz clic en una fila para ver el detalle de ese día")
    daily_style = (daily.style
                   .map(_style_pl, subset=["Beneficio", "ROI %"])
                   .format({"Apuestas": "{:d}", "Ganados": "{:d}", "Perdidos": "{:d}", "Pendientes": "{:d}",
                            "Beneficio": "{:+.2f}", "Saldo": "{:.2f}", "ROI %": "{:+.1f}%"}))
    # La clave cambia al limpiar, para poder deseleccionar la fila
    if "daily_key" not in st.session_state:
        st.session_state.daily_key = 0
    ev = st.dataframe(daily_style, use_container_width=True, hide_index=True,
                      height=table_height(len(daily)),
                      on_select="rerun", selection_mode="single-row",
                      key=f"daily_sel_{st.session_state.daily_key}")
    dia_click = None
    try:
        filas = ev.selection.rows if ev is not None else []
        if filas:
            dia_click = str(daily.iloc[filas[0]]["Fecha"])
    except Exception:
        dia_click = None
    st.download_button("⬇ Descargar resumen (CSV)", daily.to_csv(index=False).encode("utf-8-sig"),
                       "bet_ia_resumen_diario.csv", "text/csv")

    # ---- Tabla Excel 2: detalle por pick ----
    det = pd.DataFrame({
        "Fecha": en["date"],
        "Partido": en["matchup"],
        "Selección": en["selection"],
        "Cuota": en["odds"],
        "Stake %": en["stake_frac"] * 100,
        "Resultado": en["result"].map(RES_MAP).fillna(en["result"]),
        "Beneficio": en["pl_units"],
        "Saldo": en["saldo"],
    })
    # Marca las ganadas por pago anticipado: sin esto, una apuesta cobrada con
    # 5 carreras de ventaja que luego se voltea aparece como Ganada junto a un
    # marcador perdido, y no hay forma de saber por que.
    det["Anticipado"] = (en["pago_anticipado"].fillna(False).astype(bool)
                         if "pago_anticipado" in en.columns else False)

    page_section("Detalle por apuesta", "Cada pick con su beneficio y saldo acumulado")

    # ---- Filtro de periodo (Hoy · Ayer · Semana · Mes · Calendario) ----
    det["_dia"] = pd.to_datetime(en["date"].astype(str).str[:10], errors="coerce").dt.date
    hoy = pd.to_datetime(fecha_jornada()).date()   # respeta el desfase de la liga

    # Si se hizo clic en una fila del resumen, ese dia manda sobre el filtro
    if dia_click:
        d = pd.to_datetime(dia_click).date()
        c1, c2 = st.columns([4, 1])
        c1.markdown(
            f'<p style="margin:6px 0;font-size:13.5px;">📌 Mostrando el detalle del '
            f'<b>{d.strftime("%d/%m/%Y")}</b> <span style="color:rgb(var(--ink2));">'
            f'(seleccionado en el resumen)</span></p>', unsafe_allow_html=True)
        if c2.button("✕ Quitar filtro", use_container_width=True):
            st.session_state.daily_key += 1      # deselecciona la fila
            st.rerun()
        periodo, rango, desde, hasta = "Dia", None, d, d
    else:
        fc = st.columns([5, 3])
        with fc[0]:
            periodo = st.radio("periodo", ["Todo", "Hoy", "Ayer", "Esta semana", "Este mes", "Calendario"],
                               index=1,  # predeterminado: HOY
                               horizontal=True, label_visibility="collapsed", key="det_periodo")
        rango = None
        if periodo == "Calendario":
            with fc[1]:
                rango = st.date_input("Rango de fechas", value=(hoy - timedelta(days=7), hoy),
                                      format="DD/MM/YYYY", key="det_rango")

    if periodo == "Dia":
        pass                                     # ya definido arriba
    elif periodo == "Hoy":
        desde = hasta = hoy
    elif periodo == "Ayer":
        desde = hasta = hoy - timedelta(days=1)
    elif periodo == "Esta semana":
        desde, hasta = hoy - timedelta(days=hoy.weekday()), hoy   # desde el lunes
    elif periodo == "Este mes":
        desde, hasta = hoy.replace(day=1), hoy
    elif periodo == "Calendario" and rango:
        if isinstance(rango, (list, tuple)):
            desde = rango[0]
            hasta = rango[1] if len(rango) > 1 else rango[0]
        else:
            desde = hasta = rango
    else:
        desde, hasta = None, None

    det_f = det if desde is None else det[(det["_dia"] >= desde) & (det["_dia"] <= hasta)]
    det_f = det_f.drop(columns=["_dia"])

    if len(det_f):
        n_gan = int((det_f["Resultado"] == "Ganado").sum())
        n_per = int((det_f["Resultado"] == "Perdido").sum())
        ben = float(det_f["Beneficio"].sum())
        color = "var(--save)" if ben >= 0 else "var(--fare)"
        st.markdown(
            f'<p class="rt-resumen">{len(det_f)} apuestas &nbsp;·&nbsp; ✅ <b>{n_gan}</b> ganadas '
            f'&nbsp;·&nbsp; ❌ <b>{n_per}</b> perdidas &nbsp;·&nbsp; beneficio '
            f'<b style="color:rgb({color});">{mxn(ben, signo=True)}</b></p>',
            unsafe_allow_html=True)
        # Tabla propia (HTML) para poder mostrar logos y el resultado como badge.
        # Los picks del mismo partido se agrupan en filas consecutivas (ancladas
        # donde el partido aparece por primera vez): cada pick conserva su fila y
        # sus cifras reales, solo se ocultan Fecha/Partido repetidos y se unen
        # visualmente en un bloque.
        tone = {"Ganado": "save", "Perdido": "fare", "Push": "warn"}
        grupos = {}
        for _, r in det_f.iterrows():
            grupos.setdefault(r["Partido"], []).append(r)

        filas = ""
        for partido, rows in grupos.items():
            n = len(rows)
            for j, r in enumerate(rows):
                pl = float(r["Beneficio"])
                cls = "pos" if pl > 0 else ("neg" if pl < 0 else "zero")
                primero, ultimo = (j == 0), (j == n - 1)
                tr_cls = ""
                if n > 1:
                    tr_cls = " grp" + (" grp-end" if ultimo else "")
                fecha_td = f'<td class="fecha">{r["Fecha"] if primero else ""}</td>'
                if primero:
                    multi = (f'<span class="rt-multi">{n} picks</span>' if n > 1 else "")
                    partido_td = (f'<td><span class="rt-game">{logos_for_matchup(r["Partido"])}'
                                  f'<span class="nm">{r["Partido"]}</span>{multi}</span></td>')
                else:
                    partido_td = '<td></td>'      # continuacion: no repetir partido/logos
                filas += (
                    f'<tr class="{tr_cls.strip()}">' + fecha_td + partido_td
                    + f'<td class="rt-sel">{badge(r["Selección"], tone.get(r["Resultado"], "neutral"))}'
                    + ('<span class="rt-ant" title="Pago anticipado: el equipo llegó a ir '
                       '5 o más carreras arriba">⚡</span>' if r.get("Anticipado") else "")
                    + '</td>'
                    + f'<td class="num">{r["Cuota"]:.2f}</td>'
                    + f'<td class="num">{r["Stake %"]:.2f}%</td>'
                    + f'<td class="num rt-pl {cls}">{pl:+,.2f}</td>'
                    + f'<td class="num">{mxn(float(r["Saldo"]))}</td></tr>'
                )
        st.markdown(
            '<div class="rt-wrap"><table class="rt-table"><thead><tr>'
            '<th>Fecha</th><th>Partido</th><th>Selección</th><th class="num">Cuota</th>'
            '<th class="num">Stake %</th><th class="num">Beneficio</th>'
            '<th class="num">Saldo</th></tr></thead><tbody>'
            + filas + '</tbody></table></div>',
            unsafe_allow_html=True)
    else:
        st.info("No hay apuestas en el periodo seleccionado.")

    st.download_button("⬇ Descargar detalle (CSV)", det_f.to_csv(index=False).encode("utf-8-sig"),
                       "bet_ia_detalle_picks.csv", "text/csv")

    # ---- Respaldo del historial (clave en la nube: el disco es efímero) ----
    page_section("Respaldo del historial",
                 "Descarga el archivo para conservarlo; restáuralo tras un redeploy")
    rb1, rb2 = st.columns(2)
    with rb1:
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                backup_bytes = f.read().encode("utf-8")
        except Exception:
            backup_bytes = json.dumps({"bets": _read_history_file()}, ensure_ascii=False).encode("utf-8")
        st.download_button("⬇ Descargar respaldo (JSON)", backup_bytes,
                           HISTORY_FILE, "application/json", use_container_width=True)
    with rb2:
        up = st.file_uploader("Restaurar respaldo (JSON)", type="json", label_visibility="collapsed")
        if up is not None:
            try:
                data = json.load(up)
                restored = data.get("bets", []) if isinstance(data, dict) else data
                if isinstance(restored, list) and restored:
                    _write_history_file(restored)
                    st.success(f"Historial restaurado: {len(restored)} picks.")
                    st.rerun()
                else:
                    st.error("El archivo no contiene un historial válido.")
            except Exception as e:
                st.error(f"No se pudo leer el archivo: {e}")

    # ---- Ajuste manual (para partidos aún no finalizados) ----
    pending = hist[hist["result"] == "PENDING"]
    if len(pending):
        with st.expander(f"✏️ Ajuste manual ({len(pending)} pendientes)"):
            for _, row in pending.iterrows():
                c1, c2, c3 = st.columns([4, 2, 2])
                c1.markdown(f"**{row['matchup']}** — {row['selection']} @ {row['odds']:.2f}")
                choice = c2.selectbox("Resultado", ["PENDING", "WON", "LOST"],
                                      key=f"res_{row['id']}", label_visibility="collapsed")
                if c3.button("Guardar", key=f"save_{row['id']}", type="primary"):
                    update_result(row["id"], choice, row["odds"], row["kelly_stake"])
                    st.rerun()

    page_section("Evolución del saldo", "Bankroll en pesos a lo largo del tiempo")
    st.line_chart(en.set_index("date")["saldo"])


# ---------------------------------------------------------------------------
# PÁGINA: Rendimiento
# ---------------------------------------------------------------------------
def render_rendimiento():
    topbar("Rendimiento", "Analítica del sistema: EV proyectado, edge y resultados", "trophy")

    # La proyeccion solo existe si hay jornada publicada. La analitica historica
    # de mas abajo no depende de ella y debe verse igual en dias sin partidos.
    if not board_df.empty:
        section_header("Proyección de la jornada de hoy", "Valor esperado y score por pick (salida del motor)")
        proj = board_df.set_index("PARTIDO")
        a, b = st.columns(2, gap="large")
        with a:
            st.markdown('<p style="font-size:13px;color:rgb(var(--ink2));margin-bottom:4px;">EV por partido</p>', unsafe_allow_html=True)
            st.bar_chart(proj["EV"])
        with b:
            st.markdown('<p style="font-size:13px;color:rgb(var(--ink2));margin-bottom:4px;">Score por partido</p>', unsafe_allow_html=True)
            st.bar_chart(proj["SCORE"])

    hist = load_history()
    if hist.empty:
        st.info("Registra resultados en la sección Resultados para ver la analítica histórica.")
        return

    en = enrich_history(hist, bankroll_default())
    settled = en[en["result"] != "PENDING"]

    staked = float(settled["stake_units"].sum())
    net = float(en["pl_units"].sum())
    roi = (net / staked * 100) if staked else 0.0
    avg_ev = float(en["ev"].mean()) * 100
    avg_odds = float(en["odds"].mean())

    section_header("Métricas históricas", "Sobre el total de picks registrados")
    c = st.columns(4, gap="large")
    stat_tile(c[0], "Total apostado", mxn(staked), "picks cerrados", True, "dollar", "accent")
    stat_tile(c[1], "Beneficio neto", mxn(net, signo=True), "pesos", net >= 0, "trophy", "save")
    stat_tile(c[2], "ROI / Yield", f"{roi:+.1f}%", "sobre lo apostado", roi >= 0, "bar", "purple")
    stat_tile(c[3], "Cuota media", f"{avg_odds:.2f}", f"EV medio {avg_ev:+.1f}%", avg_ev >= 0, "target", "warn")

    if len(settled):
        section_header("P&L por apuesta cerrada", "Ganancia/pérdida individual (pesos)")
        st.bar_chart(settled.sort_values("date").set_index("date")["pl_units"])

    section_header("Evolución del saldo", "Curva acumulada")
    st.line_chart(en.set_index("date")["saldo"])


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def _sin_jornada():
    st.info(f"Hoy no hay jornada publicada para **{LIGA['nombre']}**. "
            "El historial sigue disponible en **Resultados** y **Rendimiento**.")


ROUTES = {
    "Dashboard": render_dashboard,
    "En vivo": render_en_vivo,
    "Resultados": render_resultados,
    "Rendimiento": render_rendimiento,
}

# Paginas que viven del historial guardado, no de la jornada del dia: deben
# abrirse aunque la liga no tenga partidos publicados hoy.
HISTORICAS = {"Resultados", "Rendimiento"}

pagina = st.session_state.page
if sorted_bets or pagina in HISTORICAS:
    ROUTES.get(pagina, render_dashboard)()
else:
    _sin_jornada()
