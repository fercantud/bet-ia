"""Protege el bug silencioso que dejó a la LMB analizando a ciegas.

La consulta de estadísticas de abridores no llevaba sportId, así que la API
respondía solo con estadísticas de MLB. Para los abridores de la LMB no había
nada y get_pitcher_stats() caía al ERA genérico de 4.15 en LOS DOS lados de
cada partido: el modelo no tenía con qué diferenciar y todas las probabilidades
quedaban pegadas al 50% (rango real observado: 0.514-0.541 en 11 partidos).

Lo peligroso es que fallaba en silencio, con valores plausibles. Estos tests
comprueban que la consulta lleva la liga del fetcher y que el valor genérico se
distingue de uno real.
"""
import mlb_api
from mlb_api import MLBDataFetcher

GENERICO = {"era": 4.15, "xera": 4.10, "whip": 1.28, "k_pct": 0.22, "bb_pct": 0.08}


class _RespuestaFalsa:
    """Responde como la API, registrando la URL que se pidió."""

    def __init__(self, url):
        self.url = url

    def json(self):
        return {"people": [{"stats": [{"splits": [{"stat": {"era": "5.10", "whip": "1.36"}}]}]}]}


def _url_consultada(fetcher, monkeypatch):
    visto = {}

    def falso_get(url, **kw):
        visto["url"] = url
        return _RespuestaFalsa(url)

    monkeypatch.setattr(mlb_api.requests, "get", falso_get)
    fetcher.get_pitcher_stats(542413)
    return visto["url"]


def test_la_consulta_lleva_la_liga_del_fetcher(monkeypatch):
    """Sin sportId, la LMB devuelve vacío y el motor cae al ERA genérico."""
    url = _url_consultada(MLBDataFetcher(sport_id=23, league_id=125), monkeypatch)
    assert "sportId=23" in url, f"la consulta de la LMB debe pedir su liga: {url}"
    assert "season=" in url, f"sin temporada la API no acota el dato: {url}"


def test_mlb_pide_su_propia_liga(monkeypatch):
    url = _url_consultada(MLBDataFetcher(), monkeypatch)
    assert "sportId=1" in url, f"MLB debe seguir pidiendo sportId=1: {url}"


def test_devuelve_lo_que_responde_la_api(monkeypatch):
    stats = MLBDataFetcher(sport_id=23, league_id=125)
    monkeypatch.setattr(mlb_api.requests, "get", lambda url, **kw: _RespuestaFalsa(url))
    s = stats.get_pitcher_stats(542413)
    assert s["era"] == 5.10 and s["whip"] == 1.36
    assert s != GENERICO, "no debe caer al genérico cuando la API sí respondió"


def test_sin_id_usa_el_generico():
    assert MLBDataFetcher(sport_id=23).get_pitcher_stats(0) == GENERICO


def test_la_lmb_recibe_stats_reales():
    """Contra la API de verdad. Si no hay red o jornada, no falla."""
    f = MLBDataFetcher(sport_id=23, league_id=125)
    ids = []
    for g in f.get_todays_games():
        ids += [g["away_pitcher_id"], g["home_pitcher_id"]]
    ids = [i for i in ids if i][:5]
    if not ids:
        return
    reales = [i for i in ids if f.get_pitcher_stats(i) != GENERICO]
    assert reales, "ningún abridor de LMB trajo stats: la consulta volvió a romperse"
