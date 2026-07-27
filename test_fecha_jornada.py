"""Protege contra el bug del 27/07: la app analizaba la jornada de AYER.

Causa: se pedía a la MLB API "los partidos de hoy" sin indicar la fecha, y la
API respondía con su propio día (a veces uno atrás). Los picks se guardaban con
la fecha local, así que nacían ya finalizados.

Regla: toda consulta a la API debe llevar la fecha explícita.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import mlb_api
from mlb_api import MLBDataFetcher, _hoy


def test_hoy_usa_zona_horaria_de_la_app():
    esperado = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    assert _hoy() == esperado, "la fecha debe salir de la zona horaria de la app"


def test_las_urls_llevan_fecha_explicita():
    """Ninguna consulta de calendario puede depender del 'hoy' de la API."""
    codigo = open(mlb_api.__file__, encoding="utf-8").read()
    for linea in codigo.splitlines():
        if "schedule?sportId=1" in linea and "date=" not in linea:
            # la fecha puede ir en la variable de la línea siguiente
            assert "{fecha}" in linea, f"consulta sin fecha explícita: {linea.strip()}"


def test_la_jornada_pedida_es_la_correcta(monkeypatch):
    """Al pedir una fecha, los partidos devueltos son de esa fecha."""
    dia = "2026-07-27"
    juegos = MLBDataFetcher().get_live_scores(date=dia)
    if not juegos:                       # sin conexión o sin jornada: no falla
        return
    # Hora Central va detrás de UTC: un juego nocturno del día D cae en D+1 UTC.
    validas = (dia, _dia_siguiente(dia))
    for g in juegos:
        assert g["start_utc"][:10] in validas, (
            f"partido de otra fecha: {g['start_utc']} (se pidió {dia})"
        )


def _dia_siguiente(dia):
    from datetime import date, timedelta
    y, m, d = map(int, dia.split("-"))
    return (date(y, m, d) + timedelta(days=1)).isoformat()
