"""Pago anticipado: el moneyline se cobra al ir 5+ carreras arriba.

La casa liquida la apuesta como ganada en cuanto el equipo elegido alcanza esa
ventaja, aunque el partido se voltee después. El caso que importa es
justamente ese: ganar la apuesta y perder el partido.

La ventaja NO se lee del marcador final, sino reconstruida medio inning a medio
inning desde las carreras por entrada. Así se detecta aunque la app no
estuviera abierta en ese momento, y también en partidos ya terminados.

LIMITACIÓN CONOCIDA: la reconstrucción avanza por medias entradas, así que una
ventaja que aparece y desaparece DENTRO de la misma entrada no se detecta
(p.ej. van +5 con dos outs y el rival empata en esa misma entrada). Para eso
haría falta el play-by-play.
"""


def _partido(innings, away="Colorado Rockies", home="San Diego Padres", final=True):
    a = sum(i[0] for i in innings)
    h = sum(i[1] for i in innings)
    return {"away_team": away, "home_team": home,
            "away_score": a, "home_score": h,
            "innings_runs": innings, "innings_played": len(innings),
            "away_f5": 0, "home_f5": 0,
            "is_final": final, "is_live": not final}


# --- ventaja_maxima -----------------------------------------------------------

def test_reconstruye_la_ventaja_maxima_no_el_marcador_final():
    from app_logica import ventaja_maxima
    # visitante se va 6-0 y acaba perdiendo 6-7
    g = _partido([(6, 0), (0, 3), (0, 4)])
    assert (g["away_score"], g["home_score"]) == (6, 7), "el visitante PIERDE"
    assert ventaja_maxima(g)[0] == 6, "pero llego a ir 6 arriba"


def test_cuenta_la_media_entrada_alta():
    """Tras la parte alta el visitante va +5 aunque el local responda abajo."""
    from app_logica import ventaja_maxima
    g = _partido([(5, 5)])
    assert ventaja_maxima(g)[0] == 5


def test_ventaja_del_local():
    from app_logica import ventaja_maxima
    g = _partido([(0, 5), (0, 0)])
    assert ventaja_maxima(g) == (0, 5)


def test_sin_desglose_usa_el_marcador():
    from app_logica import ventaja_maxima
    g = _partido([])
    g["away_score"], g["home_score"] = 9, 1
    assert ventaja_maxima(g)[0] == 8


# --- cobro_anticipado ---------------------------------------------------------

def test_cobra_con_cinco_de_ventaja():
    from app_logica import cobro_anticipado
    g = _partido([(5, 0)])
    assert cobro_anticipado("Colorado Rockies", g) is True


def test_no_cobra_con_cuatro():
    from app_logica import cobro_anticipado
    g = _partido([(4, 0)])
    assert cobro_anticipado("Colorado Rockies", g) is False


def test_no_cobra_el_equipo_contrario():
    from app_logica import cobro_anticipado
    g = _partido([(6, 0)])
    assert cobro_anticipado("San Diego Padres", g) is False


# --- settle_pick --------------------------------------------------------------

def test_gana_la_apuesta_aunque_pierda_el_partido():
    """El caso real de la promocion."""
    from app_logica import settle_pick
    g = _partido([(6, 0), (0, 3), (0, 4)])           # visitante pierde 6-7
    assert settle_pick("Colorado Rockies @ San Diego Padres",
                       "Colorado Rockies", "ML", [g]) == "WON"


def test_sin_la_ventaja_manda_el_marcador_final():
    from app_logica import settle_pick
    g = _partido([(4, 0), (0, 3), (0, 4)])           # solo llego a +4
    assert settle_pick("Colorado Rockies @ San Diego Padres",
                       "Colorado Rockies", "ML", [g]) == "LOST"


def test_se_marca_en_vivo_sin_esperar_al_final():
    from app_logica import settle_pick
    g = _partido([(5, 0)], final=False)
    assert settle_pick("Colorado Rockies @ San Diego Padres",
                       "Colorado Rockies", "ML", [g]) == "WON"


def test_un_partido_en_vivo_sin_ventaja_sigue_sin_resolverse():
    from app_logica import settle_pick
    g = _partido([(2, 0)], final=False)
    assert settle_pick("Colorado Rockies @ San Diego Padres",
                       "Colorado Rockies", "ML", [g]) is None


def test_la_promocion_no_aplica_a_totales():
    """Un Under no se cobra por ventaja: 11 carreras superan la linea."""
    from app_logica import settle_pick
    g = _partido([(6, 0), (0, 5)])
    assert settle_pick("Colorado Rockies @ San Diego Padres",
                       "Under 9.5", "TOTAL", [g]) == "LOST"


def test_la_promocion_no_aplica_a_f5():
    from app_logica import settle_pick
    g = _partido([(6, 0), (0, 0), (0, 0), (0, 0), (0, 0), (0, 7)])
    g["away_f5"], g["home_f5"] = 6, 0
    assert settle_pick("Colorado Rockies @ San Diego Padres",
                       "Colorado Rockies F5", "F5", [g]) == "WON"   # por el parcial, no por la ventaja
