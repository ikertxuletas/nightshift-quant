import copy
import re

import numpy as np

from quant import metricas, motor

_TOKEN_ARGS = re.compile(r"(?<![A-Za-z_])([A-Z_]+)\(([^)]*)\)")
_ENTEROS = {"max_barras", "cada_barras"}
_METRICAS_COMPARABLES = ("sharpe", "drawdown", "cagr", "acierto", "profit_factor")


def _es_numero(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _hojas(obj, ruta):
    if isinstance(obj, dict):
        for k, val in obj.items():
            yield from _hojas(val, ruta + (k,))
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            yield from _hojas(val, ruta + (i,))
    else:
        yield ruta, obj


def _permite_corto(costes):
    if isinstance(costes, dict):
        return any(c.permite_corto for c in costes.values())
    return costes.permite_corto


def ficha_efectiva(ficha, costes):
    if ficha["forma"] == "transversal":
        return {k: val for k, val in ficha.items() if k not in ("entrada", "salida", "gestion", "horario")}
    nueva = {k: val for k, val in ficha.items() if k != "transversal"}
    lados = ("largo", "corto") if _permite_corto(costes) else ("largo",)
    entrada = {lado: val for lado, val in (ficha.get("entrada") or {}).items() if lado in lados}
    salida = {lado: val for lado, val in (ficha.get("salida") or {}).items() if lado in entrada}
    return {**nueva, "entrada": entrada, "salida": salida}


def parametros(ficha):
    rutas, tokens = [], set()
    for seccion in ("entrada", "salida", "transversal", "gestion"):
        for ruta, valor in _hojas(ficha.get(seccion) or {}, (seccion,)):
            if isinstance(valor, str):
                tokens.update(m.group(0) for m in _TOKEN_ARGS.finditer(valor))
            elif _es_numero(valor) and valor != 0 and "tamano" not in ruta and ruta[-1] not in ("top", "bottom"):
                rutas.append(("ruta", ruta))
    args = [("arg", t, i) for t in sorted(tokens) for i, arg in enumerate(_TOKEN_ARGS.match(t).group(2).split(","))
            if float(arg.strip()) != 0]
    return rutas + args


def _variar(valor, factor, entero):
    x = valor * factor
    if not entero:
        return x
    x = max(1, int(round(x)))
    if x == valor:
        x = valor + 1 if factor > 1 else max(1, valor - 1)
    return x


def _formato(x):
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def _reemplazar_token(obj, viejo, nuevo):
    patron = re.compile(r"(?<![A-Za-z_])" + re.escape(viejo))
    if isinstance(obj, dict):
        return {k: _reemplazar_token(val, viejo, nuevo) for k, val in obj.items()}
    if isinstance(obj, list):
        return [_reemplazar_token(val, viejo, nuevo) for val in obj]
    return patron.sub(nuevo, obj) if isinstance(obj, str) else obj


def variante(ficha, parametro, factor):
    nueva = copy.deepcopy(ficha)
    if parametro[0] == "ruta":
        *padre, clave = parametro[1]
        destino = nueva
        for k in padre:
            destino = destino[k]
        original = destino[clave]
        destino[clave] = _variar(original, factor, clave in _ENTEROS)
        return nueva
    _, token, indice = parametro
    nombre, args = _TOKEN_ARGS.match(token).groups()
    partes = [p.strip() for p in args.split(",")]
    original = float(partes[indice])
    entero = indice == 0
    partes[indice] = _formato(_variar(int(original) if entero else original, factor, entero))
    return _reemplazar_token(nueva, token, f"{nombre}({','.join(partes)})")


def montecarlo_dd(pnls, capital, n, semilla=12345):
    if len(pnls) == 0:
        return 0.0
    rng = np.random.default_rng(semilla)
    caidas = [metricas.drawdown_max(np.concatenate(([capital], capital + np.cumsum(rng.permutation(pnls)))))
              for _ in range(n)]
    return float(np.percentile(caidas, 95))


def criterio(nombre, valor, umbral, sentido, estricto=False):
    if estricto:
        cumple = valor < umbral if sentido == "max" else valor > umbral
    else:
        cumple = valor <= umbral if sentido == "max" else valor >= umbral
    if umbral == 0:
        distancia = 0.0 if cumple else 999.0
    else:
        escala = abs(umbral)
        distancia = (valor - umbral) / escala if sentido == "max" else (umbral - valor) / escala
    return {"criterio": nombre, "valor": round(float(valor), 4), "umbral": umbral, "sentido": sentido,
            "cumple": bool(cumple), "distancia": round(float(distancia), 4)}


def veredicto(evaluados, margen):
    fallos = [c for c in evaluados if not c["cumple"]]
    if not fallos:
        return "pasa"
    if len(fallos) == 1 and fallos[0]["distancia"] <= margen:
        return "dudosa"
    return "no_pasa"


def referencias(total, ficha):
    prometido = ficha.get("prometido") or {}
    vs_fuente = {m: round(total[m] - prometido[m], 4) for m in ("sharpe", "drawdown", "cagr", "acierto") if m in prometido}
    vs_tipo = [{**criterio(u["metrica"], total[u["metrica"]], u["valor"], u["sentido"]), "fuente": u["fuente"]}
               for u in ficha.get("umbrales_tipo") or []]
    return {"vs_fuente": vs_fuente, "vs_tipo": vs_tipo}


def comparar(anterior, actual):
    a, b = anterior["metricas"]["total"], actual["metricas"]["total"]
    return {m: {"antes": a[m], "ahora": b[m], "mejora": b[m] < a[m] if m == "drawdown" else b[m] > a[m]}
            for m in _METRICAS_COMPARABLES if m in a and m in b}


def _tramo(res, desde, hasta):
    return metricas.resumen(res.equity[desde:hasta], res.ts[desde:hasta],
                            [o for o in res.operaciones if desde <= o.i_entrada < hasta])


def _dias_medios(res):
    cerradas = [o for o in res.operaciones if o.motivo != "fin"]
    if not cerradas:
        return 0.0
    return float(np.mean([(res.ts[o.i_salida] - res.ts[o.i_entrada]) / np.timedelta64(1, "D") for o in cerradas]))


def evaluar(ficha, ejecutar, costes, escalar, sharpe_referencia, criterios):
    base = ejecutar(ficha, costes)
    n = len(base.equity)
    corte = int(n * (1 - criterios["fraccion_oos"]))
    total, dentro, fuera = (metricas.resumen(base.equity, base.ts, base.operaciones),
                            _tramo(base, 0, corte), _tramo(base, corte, n))
    caros = ejecutar(ficha, escalar(costes, criterios["costes_multiplicador"]))
    rent_caros = float(caros.equity[-1] / caros.capital - 1)
    var = criterios["robustez_variacion"]
    variantes = [fv for p in parametros(ficha_efectiva(ficha, costes)) for f in (1 - var, 1 + var)
                 for fv in [variante(ficha, p, f)] if fv != ficha]
    robustez = float(np.mean([ejecutar(fv, costes).equity[-1] > base.capital for fv in variantes])) if variantes else 1.0
    avisos = []
    if not variantes:
        avisos.append("robustez sin variantes: la ficha no tiene parámetros que variar")
    mc = montecarlo_dd(np.array([o.pnl for o in base.operaciones]), base.capital, criterios["montecarlo_n"])
    posicional = ficha["universo"]["plazo"] == "W1" or _dias_medios(base) >= criterios["dias_posicional"]
    ratio = fuera["sharpe"] / dentro["sharpe"] if dentro["sharpe"] > 0 else (1.0 if fuera["sharpe"] > 0 else 0.0)
    sufijo = "_posicional" if posicional else ""
    evaluados = [
        criterio("drawdown", total["drawdown"], criterios["drawdown_max"], "max"),
        criterio("sharpe_fuera_de_muestra", fuera["sharpe"], criterios["sharpe_oos_min"], "min"),
        criterio("sharpe_fuera_vs_dentro", ratio, criterios["sharpe_oos_ratio_min"], "min"),
        criterio("rentabilidad_costes_x2", rent_caros, 0.0, "min", estricto=True),
        criterio("robustez", robustez, criterios["robustez_min"], "min"),
        criterio("operaciones", total["operaciones"], criterios["operaciones_min" + sufijo], "min"),
        criterio("operaciones_fuera_de_muestra", fuera["operaciones"], criterios["operaciones_oos_min" + sufijo], "min"),
        criterio("sharpe_vs_comprar_mantener", total["sharpe"] - sharpe_referencia, criterios["benchmark_margen"],
                 "min", estricto=True),
        criterio("montecarlo_dd_p95", mc, criterios["montecarlo_p95_dd_max"], "max"),
    ]
    return {
        "veredicto": veredicto(evaluados, criterios["margen_dudosa"]),
        "criterios": evaluados,
        "metricas": {"total": total, "dentro": dentro, "fuera": fuera, "rentabilidad_costes_x2": round(rent_caros, 4),
                     "robustez": round(robustez, 4), "variantes": len(variantes), "montecarlo_dd_p95": round(mc, 4),
                     "sharpe_comprar_mantener": round(float(sharpe_referencia), 4), "posicional": bool(posicional)},
        "referencias": referencias(total, ficha),
        "avisos": avisos,
    }


def _sharpe_cartera_igual(barras):
    ts = None
    for b in barras.values():
        ts = b["ts"] if ts is None else np.intersect1d(ts, b["ts"])
    normalizadas = [b["close"][np.isin(b["ts"], ts)] / b["close"][np.isin(b["ts"], ts)][0] for b in barras.values()]
    return metricas.sharpe(np.mean(normalizadas, axis=0), ts)


def validar(ficha, barras, costes, criterios):
    capital = criterios["capital"]
    if ficha["forma"] == "transversal":
        res = evaluar(ficha, lambda f, c: motor.backtest_transversal(f, barras, c, capital), costes,
                      lambda c, k: {i: x.escalar(k) for i, x in c.items()}, _sharpe_cartera_igual(barras), criterios)
        if any(c.clase == "accion" for c in costes.values()):
            res["avisos"].append("con sesgo de supervivencia (universo de acciones actual)")
        return {"_cartera": res}
    salida = {}
    for instrumento, b in barras.items():
        c = costes[instrumento]
        referencia = 0.0 if c.clase == "forex" else metricas.sharpe(b["close"], b["ts"])
        res = evaluar(ficha, lambda f, cc, inst=instrumento, bb=b: motor.backtest_serie(f, inst, bb, cc, capital),
                      c, lambda cc, k: cc.escalar(k), referencia, criterios)
        if c.clase == "accion":
            res["avisos"].append("con sesgo de supervivencia (universo de acciones actual)")
        if (ficha.get("entrada") or {}).get("corto") and not c.permite_corto:
            res["avisos"].append("cortos ignorados: el bróker no los permite")
        salida[instrumento] = res
    return salida
