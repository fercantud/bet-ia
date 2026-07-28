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


# --- el genérico y la línea deben ser de la liga, no de MLB ------------------

def test_mlb_conserva_sus_constantes():
    """Regla del proyecto: sin argumentos, MLB se comporta EXACTAMENTE igual."""
    assert MLBDataFetcher().get_pitcher_stats(0) == GENERICO
    assert mlb_api.GENERICO_MLB == GENERICO


def test_cada_liga_puede_traer_su_propio_generico():
    """La LMB tiene ERA de liga 5.08; con el 4.15 de MLB el modelo esperaba
    9.49 carreras donde se anotan 10.34."""
    propio = {"era": 5.08, "xera": 4.83, "whip": 1.51, "k_pct": 0.22, "bb_pct": 0.08}
    f = MLBDataFetcher(sport_id=23, league_id=125, stats_genericas=propio)
    assert f.get_pitcher_stats(0) == propio
    assert f.get_pitcher_stats(0) != GENERICO


def test_el_generico_no_se_comparte_entre_fetchers():
    """Un dict mutable compartido contaminaría una liga con la otra."""
    f = MLBDataFetcher(sport_id=23, stats_genericas={"era": 5.08, "xera": 4.83,
                                                    "whip": 1.51, "k_pct": 0.22, "bb_pct": 0.08})
    f.get_pitcher_stats(0)["era"] = 99.0
    assert f.get_pitcher_stats(0)["era"] == 5.08, "devolvió el dict interno, no una copia"
    assert MLBDataFetcher().get_pitcher_stats(0) == GENERICO


def test_el_generico_no_viaja_en_el_constructor():
    """Streamlit relanza app.py pero reutiliza los módulos ya importados.

    El 28/07 la app se cayó entera (local y en la nube) con
    `TypeError: got an unexpected keyword argument 'stats_genericas'`: app.py ya
    era nuevo y mlb_api seguía siendo el viejo. Asignando el atributo despues de
    construir, un modulo desactualizado solo ignora el ajuste.
    """
    import os
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
    codigo = open(ruta, encoding="utf-8").read()
    assert "stats_genericas=stats_genericas_liga" not in codigo, (
        "no pases el generico al constructor: asignalo despues de construir")
    assert "fetcher.stats_genericas = " in codigo


def test_un_modulo_viejo_no_tumba_la_app():
    """Documenta el modo de falla: el kwarg revienta, el atributo no."""
    class MLBDataFetcherViejo:                       # firma anterior a la mejora
        def __init__(self, sport_id=1, league_id=None):
            self.sport_id, self.league_id = sport_id, league_id

    try:
        MLBDataFetcherViejo(sport_id=23, stats_genericas={"era": 5.08})
        assert False, "la firma vieja deberia rechazar el argumento"
    except TypeError:
        pass

    f = MLBDataFetcherViejo(sport_id=23)             # asi es como lo hace la app
    f.stats_genericas = {"era": 5.08}
    assert f.stats_genericas["era"] == 5.08


def test_la_linea_por_defecto_sigue_siendo_8_5():
    """El 8.5 histórico se conserva salvo que quien llame pase otro valor:
    así MLB no cambia aunque la firma sí."""
    import inspect

    import main
    for fn in (main.get_analyzed_bets, main._build_bets_from_real_games):
        assert inspect.signature(fn).parameters["linea_por_defecto"].default == 8.5


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
