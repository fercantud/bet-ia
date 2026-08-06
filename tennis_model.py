"""Motor deportivo de tenis: la PROBABILIDAD sale del analisis, NO del momio.

Calcula, por jugador y a partir del historial real de partidos (Sackmann):
  - Elo general y Elo por superficie
  - Forma reciente ponderada por calidad del rival
  - Rendimiento en la superficie actual
  - Head to head
  - Nivel de saque y de devolucion
  - Fatiga (partidos recientes, jugo ayer, 3 sets)

Cada factor es un score 0-100 para el jugador A frente a B (50 = parejo). La
probabilidad es la suma ponderada (pesos del spec) pasada por una logistica. El
momio se usa SOLO al final para EV, VALUE y SOBREVALORADO. Lesiones no tienen
fuente libre: quedan neutrales (marcado en la salida).
"""
import math
import unicodedata
from collections import defaultdict
import tennis_data

WEIGHTS = {"forma": 0.30, "superficie": 0.20, "h2h": 0.10, "saque": 0.10,
           "devolucion": 0.10, "elo": 0.10, "fisico": 0.05, "contexto": 0.05}

_clip = lambda v, lo=5.0, hi=95.0: max(lo, min(hi, v))


def _elo_exp(a, b):
    return 1.0 / (1.0 + 10 ** (-(a - b) / 400.0))


class PlayerDB:
    def __init__(self, tour="atp"):
        self.tour = tour
        self.elo = defaultdict(lambda: 1500.0)
        self.elo_surf = defaultdict(lambda: defaultdict(lambda: 1500.0))
        self.log = defaultdict(list)                 # jugador -> partidos (cronologico)
        self.h2h = defaultdict(lambda: defaultdict(int))  # h2h[a][b] = veces que A vencio a B
        self.rank = {}                               # nombre_normalizado -> ranking actual
        self.real = False
        self._build()

    def _build(self):
        matches = tennis_data.get_matches(self.tour)
        self.real = tennis_data.hay_datos_reales(self.tour)
        self.rank = tennis_data.get_rankings(self.tour)
        for m in matches:
            w, l, s, dt = m["winner"], m["loser"], m["surface"], m["date"]
            ew, el = self.elo[w], self.elo[l]
            ews, els = self.elo_surf[w][s], self.elo_surf[l][s]
            exp = _elo_exp(ew, el)
            exp_s = _elo_exp(ews, els)
            K = 32.0
            self.elo[w] = ew + K * (1 - exp)
            self.elo[l] = el - K * (1 - exp)
            self.elo_surf[w][s] = ews + K * (1 - exp_s)
            self.elo_surf[l][s] = els - K * (1 - exp_s)

            def rec(pl, opp, opp_elo, won, mine, his):
                svpt = mine["svpt"] or 1
                serve = (mine["1stWon"] + mine["2ndWon"]) / svpt          # % pts ganados al saque
                ret = ((his["bpFaced"] - his["bpSaved"]) / his["bpFaced"]) if his["bpFaced"] else 0.20
                self.log[pl].append({"date": dt, "surface": s, "won": won, "opp": opp,
                                      "opp_elo": opp_elo, "serve": serve, "ret": ret,
                                      "sets3": (m.get("score", "").count("-") >= 3)})
            mine_w = {k: m[f"w_{k}"] for k in ("svpt", "1stWon", "2ndWon", "bpFaced", "bpSaved")}
            mine_l = {k: m[f"l_{k}"] for k in ("svpt", "1stWon", "2ndWon", "bpFaced", "bpSaved")}
            rec(w, l, el, True, mine_w, mine_l)
            rec(l, w, ew, False, mine_l, mine_w)
            self.h2h[w][l] += 1

    # ---- estimacion de fuerza (respaldo por ranking/Elo si falta historial) ----
    def _nrm(self, p):
        return unicodedata.normalize("NFKD", p or "").encode("ascii", "ignore").decode().lower().strip()

    @staticmethod
    def elo_from_rank(rank):
        # ranking -> Elo aprox. rank1~2130, 10~1880, 50~1705, 100~1630, 300~1510.
        if not rank or rank < 1:
            return 1500.0
        return max(1300.0, min(2150.0, 2130.0 - 250.0 * math.log10(rank)))

    def eff_elo(self, p, surface=None):
        """Elo efectivo: historial si existe; si no, ranking; si no, 1500 (promedio)."""
        if self.log.get(p):
            if surface:
                return 0.6 * self.elo_surf[p][surface] + 0.4 * self.elo[p]
            return self.elo[p]
        r = self.rank.get(self._nrm(p))
        return self.elo_from_rank(r) if r else 1500.0

    def _implied(self, p):
        """Calidad implicita 0-1 desde el Elo efectivo (0.5 = promedio del circuito)."""
        return _elo_exp(self.eff_elo(p), 1500.0)

    def nivel_dato(self, p):
        """2 = historial de partidos; 1 = solo ranking; 0 = nada."""
        if self.log.get(p):
            return 2
        return 1 if self.rank.get(self._nrm(p)) else 0

    # ---- agregados por jugador (real con historial; estimado si no lo hay) ----
    def _recent(self, p, surface=None, n=15):
        log = self.log.get(p, [])
        if surface:
            log = [x for x in log if x["surface"] == surface]
        return log[-n:]

    def forma(self, p):
        r = self._recent(p, n=15)
        if not r:
            return self._implied(p)                    # sin historial: estimado
        num = sum((1.0 if x["won"] else 0.0) * (x["opp_elo"] / 1500.0) for x in r)
        den = sum(x["opp_elo"] / 1500.0 for x in r)
        return num / den if den else self._implied(p)

    def surf_win(self, p, surface):
        r = self._recent(p, surface=surface, n=20)
        if r:
            return sum(1 for x in r if x["won"]) / len(r)
        gen = self._recent(p, n=20)                    # sin partidos en esa superficie
        if gen:
            return sum(1 for x in gen if x["won"]) / len(gen)
        return self._implied(p)

    def serve(self, p):
        r = self._recent(p, n=15)
        if r:
            return sum(x["serve"] for x in r) / len(r)
        return 0.60 + 0.12 * (2 * self._implied(p) - 1)    # estimado desde la calidad

    def ret(self, p):
        r = self._recent(p, n=15)
        if r:
            return sum(x["ret"] for x in r) / len(r)
        return 0.19 + 0.10 * (2 * self._implied(p) - 1)    # estimado desde la calidad

    def fatiga(self, p):
        """Penalizacion 0..1 (mas alto = mas cansado)."""
        r = self.log.get(p, [])[-6:]
        if not r:
            return 0.0
        ult = r[-1]["date"]
        semana = sum(1 for x in r if _dias(ult, x["date"]) <= 7)
        ayer = 1 if len(r) >= 1 and _dias(ult, r[-1]["date"]) <= 1 and len(r) >= 2 else 0
        tres = sum(1 for x in r[-3:] if x["sets3"])
        pen = 0.10 * max(0, semana - 2) + 0.06 * tres
        return min(1.0, pen)

    def h2h_rate(self, a, b):
        aw, bw = self.h2h[a][b], self.h2h[b][a]
        tot = aw + bw
        return (aw / tot, tot) if tot else (0.5, 0)


def _dias(d1, d2):
    try:
        from datetime import datetime
        return abs((datetime.strptime(str(d1), "%Y%m%d") - datetime.strptime(str(d2), "%Y%m%d")).days)
    except Exception:
        return 99


def analizar(db: PlayerDB, a: str, b: str, surface: str) -> dict:
    """Devuelve prob de que A venza a B + el desglose de factores (0-100 para A).

    Los agregados (forma/surf_win/serve/ret/fatiga) ya son "auto-fallback": si
    un jugador no tiene historial (nombre no resuelto en el dataset) los
    defaultdicts de PlayerDB lo tratan como un jugador promedio del circuito
    (Elo 1500, 50% forma, etc.) en lugar de romper el calculo. Asi que esta
    funcion SIEMPRE produce un desglose numerico completo, nunca None/"—".

    Cuando a uno de los dos (o ambos) no se le conoce historial real, la
    desviacion del composite respecto al 50 se atenua con `confianza` para no
    sobre-afirmar certeza sobre un rival "inventado" por el valor neutral.
    Con 0 jugadores conocidos no hay senal real: los factores ya salen en 50
    de forma natural (ambos lados usan el mismo default) y prob=0.50 es la
    respuesta honesta, no un placeholder.
    """
    surface = (surface or "Hard").title()
    # Elo EFECTIVO: usa historial si hay; si no, ranking; si no, promedio.
    p_elo = _elo_exp(db.eff_elo(a, surface), db.eff_elo(b, surface))

    f = {}
    f["elo"] = _clip(100.0 * p_elo)
    f["forma"] = _clip(50 + (db.forma(a) - db.forma(b)) * 120)
    f["superficie"] = _clip(50 + (db.surf_win(a, surface) - db.surf_win(b, surface)) * 90)
    f["saque"] = _clip(50 + (db.serve(a) - db.serve(b)) * 260)
    f["devolucion"] = _clip(50 + (db.ret(a) - db.ret(b)) * 260)
    h2h_a, n_h2h = db.h2h_rate(a, b)
    f["h2h"] = _clip(50 + (h2h_a - 0.5) * 80) if n_h2h else 50.0
    f["fisico"] = _clip(50 + (db.fatiga(b) - db.fatiga(a)) * 60)   # menos cansado = mejor
    f["contexto"] = 50.0                                            # sin datos extra: neutral

    composite = sum(WEIGHTS[k] * f[k] for k in WEIGHTS)

    # Confianza segun cuanto dato REAL hay de cada lado (historial > ranking > nada).
    na, nb = db.nivel_dato(a), db.nivel_dato(b)
    if na == 0 and nb == 0:
        confianza, cobertura = 0.0, "sin_datos"
    elif na == 2 and nb == 2:
        confianza, cobertura = 1.0, "completa"
    elif min(na, nb) >= 1:
        confianza, cobertura = 0.82, "parcial"        # ambos con al menos ranking
    else:
        confianza, cobertura = 0.62, "parcial"        # uno conocido, otro sin nada
    composite_final = 50.0 + (composite - 50.0) * confianza

    prob = 1.0 / (1.0 + math.exp(-0.11 * (composite_final - 50.0)))
    prob = max(0.03, min(0.97, prob))
    return {"prob": round(prob, 4), "composite": round(composite, 1),
            "factores": {k: round(v, 1) for k, v in f.items()},
            "h2h_n": n_h2h, "datos_reales": db.real, "cobertura": cobertura}
