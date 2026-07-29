"""Los dos casos de devolución que dejaban picks colgados para siempre.

Ambos aparecieron analizando la KBO, pero no eran problemas de esa liga: son
reglas de cierre que valen igual para MLB y LMB. settle_pick() devolvía None
—"no se puede decidir"— y el pick se quedaba PENDING sin que nada volviera a
mirarlo, porque el partido ya estaba finalizado y no iba a cambiar.

El caso del total exacto es el que más importa: las casas ofrecen líneas
enteras (8, 9, 10) todo el tiempo y en MLB son de las más comunes.
"""


def _settle(selection, market, away, home, entradas=9,
            visitante="NC Dinos", local="SSG Landers"):
    """Réplica de settle_pick() sin importar app.py (que arranca Streamlit).

    Si esta lógica y la de app.py se separan, los tests dejan de proteger nada:
    por eso test_no_se_separo_de_la_app comprueba que las reglas sigan ahí.
    """
    import re
    sel, mkt = selection.lower(), market.upper()
    if mkt == "TOTAL":
        line = float(re.search(r"(\d+(?:\.\d+)?)", selection).group(1))
        total = away + home
        if total == line:
            return "PUSH"
        return ("WON" if total < line else "LOST") if "under" in sel else \
               ("WON" if total > line else "LOST")
    if home == away:
        return "PUSH"
    ganador = local if home > away else visitante
    return "WON" if selection.strip().lower() in ganador.lower() else "LOST"


def test_total_exacto_en_la_linea_es_push():
    """KT 10 - 0 NC con Under 10: se quedó pendiente para siempre el 28/07."""
    assert _settle("Under 10", "TOTAL", 10, 0) == "PUSH"
    assert _settle("Over 9", "TOTAL", 4, 5) == "PUSH"


def test_empate_final_es_push():
    """Un final empatado no tiene ganador: la apuesta se devuelve."""
    assert _settle("SSG Landers", "ML", 5, 5) == "PUSH"


def test_los_casos_normales_no_cambiaron():
    assert _settle("Under 10", "TOTAL", 3, 5) == "WON"
    assert _settle("Under 11", "TOTAL", 5, 12) == "LOST"
    assert _settle("Over 8.5", "TOTAL", 6, 5) == "WON"
    assert _settle("Over 8.5", "TOTAL", 2, 1) == "LOST"
    # visitante NC 2 - 1 SSG local: gana el visitante
    assert _settle("NC Dinos", "ML", 2, 1) == "WON"
    assert _settle("SSG Landers", "ML", 2, 1) == "LOST"


def test_no_se_separo_de_la_app():
    """Las dos reglas deben seguir vivas en settle_pick(), no solo aquí."""
    import os
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
    codigo = open(ruta, encoding="utf-8").read()
    cuerpo = codigo[codigo.index("def settle_pick("):]
    cuerpo = cuerpo[:cuerpo.index("\n@st.cache_data")]
    assert cuerpo.count('return "PUSH"') >= 2, (
        "settle_pick perdio alguna devolucion: el total exacto en la linea y el "
        "empate final deben cerrar como PUSH, no quedarse pendientes")
