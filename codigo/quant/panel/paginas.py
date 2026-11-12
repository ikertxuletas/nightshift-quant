# lightweight-charts 4.2.0 (static/lightweight-charts.standalone.production.js)
# sha256 46fc69534ec098f095bbcd1d9a26d693d39a8b9eeff7343536765b3dd28c2bdf
# from https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js
import json
from datetime import datetime, timedelta, timezone
from html import escape as esc
from pathlib import Path

import numpy as np

from quant import costes as mcostes
from quant import criterios as mcriterios
from quant import datos, familias, motor, universo
from quant import ranking as rk
from quant.demo import desvio, diario
from quant.familias import propias
from quant.panel import ficha_html, ficha_stats, hoy_datos, nota as mnota, piezas, precalcular
from quant.investigacion import contratos, diagnostico, noche

TABS = (("hoy", "/", "Hoy"), ("demo", "/demo", "Demo"), ("ranking", "/ranking", "Ranking"), ("glosario", "/glosario", "Glosario"))
VERDICT_ES = {"pasa": "Pasa", "dudosa": "Dudosa", "no_pasa": "No pasa", "en_prueba": "En prueba",
              "control": "Control", "pendiente_datos": "Sin datos"}
_EQUITY_CACHE = {}
_PNL_CACHE = {}
_RANKING_CACHE = {}
_SISTEMA_CACHE = {}
_HOY_CACHE = {}
_RITMO_CACHE = {}
SISTEMA_TTL = timedelta(minutes=5)
MAX_POINTS = 600

GRUPOS_GLOSARIO = ("Rentabilidad", "Riesgo", "Validación", "Por qué gana o pierde", "Demo", "Laboratorio")
GLOSARIO = (
    ("Rentabilidad", "Rentabilidad anual",
     "Lo que ganaría de media cada año, con interés compuesto. Sirve para comparar estrategias con "
     "historiales de distinta longitud.",
     "Donchian en TPL gana un +758 % en 36,8 años, que es un 6,0 % al año."),
    ("Rentabilidad", "Profit factor",
     "Lo que suman las operaciones ganadoras dividido por lo que suman las perdedoras. Por encima de 1"
     " gana dinero; por debajo, pierde.",
     "Una estrategia que gana 1.500 € en sus operaciones buenas y pierde 1.000 € en las malas tiene un profit factor de 1,5."),
    ("Rentabilidad", "Nota Quant",
     "Nota de 0 a 100 que resume 8 aspectos de una estrategia (riesgo, aguante, caídas, robustez, "
     "costes, experiencia, consistencia y ventaja frente a comprar y mantener). Ordena y explica; no "
     "aprueba ni suspende.",
     "TPL saca 74: muy buena en aguante y robustez, floja frente a comprar y mantener."),
    ("Riesgo", "Sharpe",
     "Mide cuánta rentabilidad consigue una estrategia por cada unidad de riesgo (las subidas y "
     "bajadas de su curva). Por encima de 1 se considera bueno; por debajo de 0 pierde dinero. "
     "Ejemplo: dos estrategias ganan un 10 % al año, pero una se mueve poco y otra da sustos enormes; "
     "la tranquila tiene el Sharpe más alto.",
     "TPL con ruptura Donchian tiene 0,83 en todo el periodo y 1,07 en los años que no vio."),
    ("Riesgo", "Drawdown",
     "Es la mayor caída desde un máximo de la curva hasta el punto más bajo posterior. Indica cuánto "
     "habrías visto bajar tu dinero en el peor momento. Ejemplo: si la cuenta llega a 10.000 y baja a "
     "8.000, el drawdown es del 20 %.",
     "TPL llegó a caer un 16,8 % desde su máximo, hasta el 25-ago-2010."),
    ("Riesgo", "Montecarlo",
     "Se reordenan al azar las operaciones del backtest miles de veces para ver qué rachas malas "
     "podrían haber ocurrido. Así se estima el peor drawdown razonable y no solo el que tocó en el "
     "pasado. Ejemplo: aunque el backtest tuvo una caída del 12 %, las mezclas pueden mostrar que una "
     "caída del 25 % también era plausible.",
     "TPL: en el 5 % peor de los barajados cae un 24,8 %; el límite es un 30 %."),
    ("Riesgo", "Tiempo sin un nuevo máximo",
     "Cuánto tiempo pasa una estrategia sin superar su mejor momento anterior. Es lo que más cuesta "
     "aguantar: meses o años viendo la cuenta por debajo de donde estuvo.",
     "En la ruptura de máximos sobre Apple llegó a pasar 1.665 días, unos cuatro años y medio, sin un "
     "nuevo máximo."),
    ("Validación", "Dentro y fuera de muestra",
     "Los datos se dividen en dos partes. Con la primera (dentro de muestra) se diseña y ajusta la "
     "estrategia; la segunda (fuera de muestra) no se toca y sirve de examen. Ejemplo: se ajusta con "
     "2013-2022 y se examina con 2023-2026; si el examen sale mucho peor, la estrategia probablemente "
     "solo se aprendió el pasado.",
     "TPL se midió de 1990 a 2015 y se comprobó de 2015 a 2026."),
    ("Validación", "Robustez",
     "Se cambian un poco los parámetros de la estrategia (por ejemplo un 20 % arriba y abajo) y se "
     "mira si sigue ganando. Una estrategia sólida aguanta esos cambios; una frágil solo funciona con "
     "un número exacto. Ejemplo: una media de 20 días que gana, pero con 18 o 22 días pierde, no es de"
     " fiar.",
     "Las 6 variantes de los parámetros de TPL siguen ganando."),
    ("Validación", "Costes x2",
     "Se repite el backtest con comisiones, diferencial y deslizamiento multiplicados por dos. Si aun "
     "así gana, el resultado no depende de unos costes demasiado optimistas. Ejemplo: una estrategia "
     "que gana un 1 % con costes normales y pierde con costes dobles es muy ajustada y peligrosa.",
     "Un experimento que gana un 1 % con costes normales y pierde con costes dobles no pasa."),
    ("Validación", "Veredictos",
     "Pasa: cumple todos los criterios. Dudosa: falla por poco alguno. No pasa: falla claramente. En "
     "prueba y Control son etiquetas neutras de la demo. Ejemplo: con 20 de 400 combinaciones que "
     "'pasan' puede ser pura suerte, porque con tantas pruebas algunas salen bien por azar.",
     "Del primer barrido, 202 de 31.349 combinaciones pasan y 44 salen dudosas."),
    ("Validación", "Validador",
     "El programa que decide si una estrategia pasa, sale dudosa o no pasa, comparando sus cifras con "
     "criterios fijos: caída máxima, robustez, costes dobles, años que no vio… Nadie lo ajusta a mano "
     "estrategia por estrategia.",
     "Las variantes del laboratorio que lo superan llevan la etiqueta «Pasa el validador»; aún les falta "
     "el examen."),
    ("Por qué gana o pierde", "Mapa de días y horas",
     "Una cuadrícula con una casilla por cada hora de cada día de la semana, en hora de Madrid. Verde "
     "donde la estrategia gana, rojo donde pierde y vacía donde casi no opera. Sirve para ver si la "
     "ventaja depende de unas pocas horas.",
     "Está en la página de cada estrategia y de cada experimento, en «Lo nuevo»."),
    ("Por qué gana o pierde", "Probabilidad de azar",
     "La probabilidad de que una estrategia sin ninguna ventaja real diera, por pura suerte, un "
     "resultado tan bueno con el mismo número de operaciones. Cuanto más baja, más creíble es la "
     "ventaja.",
     "En la ruptura de máximos sobre Apple, con 152 operaciones: menos del 0,1 %."),
    ("Por qué gana o pierde", "Costes sobre el beneficio",
     "Qué parte de lo que gana una estrategia antes de costes se llevan las comisiones, el diferencial"
     " y el deslizamiento. Si pasa de la mitad, cada operación apenas merece la pena.",
     "En la ruptura de máximos sobre Apple, los costes se llevan el 12 % de lo ganado."),
    ("Por qué gana o pierde", "Lo que deja por el camino",
     "Cuánto llegó a ir a favor una operación antes de cerrarse y cuánto de eso devolvió. Si deja "
     "mucho, quizá el objetivo o la salida están mal puestos.",
     "En la ruptura de máximos sobre Apple, la operación típica llega a ir a favor 1,68 veces lo que "
     "arriesga y devuelve 1,58 antes de cerrarse."),
    ("Por qué gana o pierde", "Correlación con el SP500",
     "Cuánto se mueve la estrategia a la vez que el índice SP500. Cerca de 1 es casi lo mismo que "
     "tener el índice; cerca de 0 va por su cuenta; negativa, va al revés. Lo que va por su cuenta "
     "suaviza el conjunto.",
     "En la ruptura de máximos sobre Apple: 0,12, casi independiente del índice."),
    ("Demo", "Demo",
     "Una cuenta con dinero de mentira donde las estrategias que pasan las pruebas operan sobre "
     "precios reales. Sirve para ver si en el mercado de verdad se comportan como en su backtest.",
     "Empezó el 3 de noviembre con 5.000 € repartidos entre 7 estrategias."),
    ("Demo", "Percentil 5",
     "Es el valor por debajo del cual cae solo el 5 % de los casos simulados. Se usa como límite de lo"
     " normalmente malo. Ejemplo: si el percentil 5 del resultado esperado es -50 € y la demo va en "
     "-80 €, va peor que el 95 % de los escenarios y hay que sospechar.",
     "Es el límite bajo de la banda con la que se vigila cada estrategia de la demo."),
    ("Demo", "Desvío",
     "Diferencia entre lo que hace la demo y lo que el backtest hacía prever. Si la demo cae por "
     "debajo de la banda esperada (percentiles 5 a 95), la estrategia se retira sola. Ejemplo: tras 10"
     " operaciones la demo pierde más de lo que el 95 % de las simulaciones habría perdido.",
     "Ninguna estrategia de la demo se ha desviado todavía."),
    ("Demo", "Etiquetas de la demo",
     "Cada estrategia de la demo lleva una etiqueta: en prueba (se está observando), control (comprar "
     "y mantener, sirve de comparación) o retirada (se apartó por desvío). Ejemplo: si todas las "
     "estrategias ganan menos que el control, no están aportando nada frente a simplemente comprar y "
     "esperar.",
     "Los controles de la demo son comprar y mantener US500 y BTC."),
    ("Laboratorio", "Entrenamiento y examen",
     "Los datos de una estrategia propia se parten en dos. Con el entrenamiento el laboratorio prueba "
     "y ajusta ideas; el examen son años que nunca ha visto y se usa una sola vez, al final.",
     "Las estrategias propias se entrenan hasta finales de 2022 y se examinan de 2023 en adelante."),
    ("Laboratorio", "Examen final",
     "Datos que el agente del laboratorio nunca ve. Una versión solo es ganadora si aprueba con ellos.",
     "Para las estrategias propias, el examen es de 2023 en adelante."),
    ("Laboratorio", "Cambios",
     "Cuánto se aleja una versión de la estrategia original. Cuantos más cambios, más profit factor se"
     " le exige en el examen.",
     "El #42 tiene 3 cambios: necesitaría un PF de al menos 1,15 en el examen."),
    ("Laboratorio", "Variante",
     "Una versión de una estrategia con algún cambio: otro stop, otro filtro, otras horas. El "
     "laboratorio prueba muchas y se queda con las que mejoran sin volverse frágiles.",
     "El laboratorio prueba cada noche nuevas variantes de cada estrategia propia; en Ranking › Propias se ve la "
     "mejor con al menos 200 operaciones."),
    ("Laboratorio", "Asesor",
     "Un agente que cada domingo lee todos los experimentos y escribe qué funciona, qué no y qué "
     "probar después. Solo propone: no cambia nada por su cuenta.",
     "Su último informe aparece en Ranking › Propias, encima de las tarjetas de experimentos."),
)


def _json_for_script(obj):
    return json.dumps(obj).replace("<", "\\u003c")


def _num(v, fmt="{:.2f}", pct=False):
    if v is None:
        return "–"
    return (fmt + " %").format(v * 100) if pct else fmt.format(v)


def _layout(active, title, body, scripts="", titular="", raiz=None, recarga=None):
    meta = f'<meta http-equiv="refresh" content="{int(recarga)}">' if isinstance(recarga, int) else ""
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{meta}
<title>{esc(title)} · Quant</title><link rel="icon" href="/static/logo.svg" type="image/svg+xml">
<link rel="preload" href="/static/fonts/Geist-Variable.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/static/panel.css"></head>
<body><header id="arriba" class="arriba">{piezas.cabecera(active, titular, raiz)}</header><main>{body}</main>{scripts}</body></html>"""


def _sample(points):
    if len(points) <= MAX_POINTS:
        return points
    step = len(points) / MAX_POINTS
    return [points[int(i * step)] for i in range(MAX_POINTS)] + [points[-1]]


def backtest_view(raiz, ficha, instrument):
    res, capital = ficha_stats.ejecutar(raiz, ficha, instrument)
    ts = (res.ts.astype("datetime64[s]").astype("int64")).tolist()
    pnl_pct = np.array([o.pnl for o in res.operaciones], float) / capital
    stats = ficha_stats.estadisticas(res.ts, res.equity, res.operaciones, capital)
    return _sample([[t, round(float(v), 2)] for t, v in zip(ts, res.equity)]), pnl_pct, stats


def trade_stats(pnl_pct):
    p = np.asarray(pnl_pct, float)
    if not len(p):
        return None
    wins, losses = p[p > 0], p[p < 0]
    return {"n": len(p), "wins": len(wins), "losses": len(losses), "win_rate": len(wins) / len(p),
            "mean": float(p.mean()),
            "avg_win": float(wins.mean()) if len(wins) else None,
            "max_win": float(wins.max()) if len(wins) else None,
            "avg_loss": float(losses.mean()) if len(losses) else None,
            "max_loss": float(losses.min()) if len(losses) else None,
            "profit_factor": min(float(wins.sum() / -losses.sum()), 999.0) if len(losses) else None}


def _equity_cached(raiz, combo_id, ficha, instrument):
    key = (str(raiz), combo_id, instrument)
    if key not in _EQUITY_CACHE:
        try:
            _EQUITY_CACHE[key] = backtest_view(raiz, ficha, instrument)
        except Exception:
            return None
    return _EQUITY_CACHE[key]


def _backtest_pnls(raiz, strategy):
    key = (str(raiz), strategy["id"])
    if key not in _PNL_CACHE:
        crit = mcriterios.cargar(raiz / "config")
        cfg = mcostes.cargar(raiz / "config" / "costes.json")
        uni = universo.cargar(raiz / "config")
        ficha = json.loads(strategy["ficha_json"])
        inst = strategy["instrument"]
        barras = datos.cargar(inst, strategy["timeframe"], raiz / "datos", desde=universo.desde_de(inst, uni))
        costes = mcostes.costes_de(inst, cfg, clase=universo.clase_de(inst, uni))
        res = motor.backtest_serie(ficha, inst, barras, costes, crit["capital"])
        _PNL_CACHE[key] = np.array([o.pnl for o in res.operaciones], float) / crit["capital"]
        dias = (barras["ts"][-1] - barras["ts"][0]) / np.timedelta64(1, "D") if len(barras["ts"]) > 1 else 0
        _RITMO_CACHE[key] = len(res.operaciones) / dias if dias else 0.0
    return _PNL_CACHE[key]


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


_ETAPA_ES = {"precios": "Precios", "investigar": "Investigar", "canario": "Canario", "demo": "Demo",
             "laboratorio": "Laboratorio", "relator": "Relator", "mentor": "Mentor", "copia": "Copia"}


def _ultimo_parte(raiz):
    partes = sorted((raiz / "informes").glob("parte_*.json"))
    return _safe(lambda: json.loads(partes[-1].read_text(encoding="utf-8")), None) if partes else None


def _que_hizo(nombre, r):
    """One plain sentence per nightly stage, from its stored result."""
    if not isinstance(r, dict):
        return ""
    if r.get("omitido"):
        return f"Omitida: {r['omitido']}"
    fallo = contratos.hay_fallo(r)
    if nombre == "precios":
        inst = r.get("instrumentos") or []
        malos = [i.get("instrumento") for i in inst if isinstance(i, dict) and i.get("error")]
        return f"Bajó {len(inst)} valores" + (f"; avisos en {', '.join(malos[:5])}" if malos else "; sin avisos")
    if fallo:
        return f"Falló: {fallo}"
    if nombre == "investigar":
        lec = r.get("lectura") or {}
        return (f"Leyó {(lec.get('leidos') or 0) + (lec.get('descartados') or 0)} documentos: "
                f"{(r.get('fichas') or {}).get('aprobadas', 0)} fichas y {r.get('validadas', 0)} validadas")
    if nombre == "canario":
        return "Los agentes responden bien" if r.get("ok") else "Prueba de los agentes con problemas"
    if nombre == "demo":
        return f"Evaluó {r.get('evaluated', 0)} estrategias; retiró {r.get('retired', 0)}"
    if nombre == "laboratorio":
        tandas = f"{r['tandas']} tandas, " if r.get("tandas") else ""
        return f"{tandas}{r.get('probados', 0)} experimentos; {r.get('ganadoras', 0)} ganadoras nuevas"
    if nombre == "relator":
        return f"Escribió {r.get('relatados', 0)} relatos y el informe del día"
    if nombre == "mentor":
        return f"Agentes: {(r.get('propuesta') or {}).get('motivo') or 'sin cambios'}"
    if nombre == "copia":
        return "Copia de seguridad en OneDrive"
    return ""


def _duracion(s):
    if s is None:
        return "–"
    return f"{s / 60:.0f} min" if s >= 90 else f"{s:.0f} s"


_PROPIAS_ES = {"manual": "Manual (ejemplo)", "ejemplo": "RSI(2) (ejemplo)"}
_ETIQUETA_ES = {"control": "Control", "en_prueba": "En prueba", "aprobada": "Aprobada", "retirada": "Retirada"}
_MESES_C = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
_TONO = {"verde": "sube", "ambar": "aviso", "rojo": "baja"}
_AYUDAS_HOY = {
    "resultado": ("Resultado de la demo", "Las estrategias que pasan las pruebas operan con dinero de mentira sobre precios "
                  "reales. Empezaron el 3 de noviembre con 5.000 € repartidos entre 7 estrategias.\n\nLa cifra suma lo ganado "
                  "y perdido en las operaciones cerradas más lo que darían hoy las abiertas si se cerraran ahora.", "Demo"),
    "cerrado": ("Lo ya cerrado", "Solo las operaciones terminadas: ese resultado ya no cambia. La diferencia con la cifra "
                "grande son las posiciones aún abiertas.", None),
    "propias": ("Tus estrategias en la demo", "Las estrategias de la demo que no son controles, juntas, en porcentaje "
                "sobre su capital.", None),
    "controles": ("Comprar y mantener", "Los controles compraron el SP500 y Bitcoin el primer día y no hacen nada más. Si "
                  "tus estrategias no superan a «no hacer nada», no aportan valor. Con pocas operaciones aún no significa nada.",
                  "Etiquetas de la demo"),
    "grafico": ("Cómo leer el gráfico", "Curva de la demo: su valor hora a hora desde el 3 de noviembre; la línea fina es "
                "tus estrategias, la discontinua los controles y las punteadas lo esperable según el backtest.\n\nTus "
                "operaciones: tu estrategia manual sobre el SP500 con sus entradas y salidas.\n\nMercado: Bitcoin con su volumen."
                "\n\nLos gráficos usan TradingView Lightweight Charts (tradingview.com).",
                "Percentil 5"),
    "abiertas": ("Posiciones abiertas", "Operaciones abiertas que aún no se han cerrado. El importe es lo que darían si se "
                 "cerraran ahora; el mini gráfico, el precio de los últimos 30 días.", None),
    "estrategias": ("Tus estrategias", "El número es lo que gana su mejor variante por cada euro que pierde. Por encima de 1 "
                    "gana dinero; la raya de la barra marca el 1. Solo cuentan variantes con al menos 200 operaciones.",
                    "Profit factor"),
    "anoche": ("Lo que hace Quant cada noche", "Baja precios, lee documentos, revisa la demo, deja trabajar al laboratorio, "
               "escribe el informe y hace copia de seguridad.", None),
}


def _ayuda_hoy(clave):
    titulo, texto, glosario = _AYUDAS_HOY[clave]
    return piezas.ayuda(f"h-{clave}", titulo, texto, glosario)


def _boton(clave):
    b, pop = _ayuda_hoy(clave)
    return b + pop


def _utc(texto):
    import pandas as pd
    t = pd.Timestamp(texto)
    return t.tz_localize("UTC") if t.tzinfo is None else t


def _hora_madrid(texto):
    return _utc(texto).tz_convert("Europe/Madrid").strftime("%d/%m/%Y %H:%M")


def _dia_corto(texto):
    t = _utc(texto).tz_convert("Europe/Madrid")
    return f"{t.day} {_MESES_C[t.month - 1]}"


def _backtest_ritmo(raiz, strategy):
    pnls = _backtest_pnls(raiz, strategy)
    return pnls, _RITMO_CACHE.get((str(raiz), strategy["id"]), 0.0)


def _partes(raiz, n=3):
    rutas_p = sorted((raiz / "informes").glob("parte_*.json"), reverse=True)[:n]
    return [p for p in (_safe(lambda r=r: json.loads(r.read_text(encoding="utf-8")), None) for r in rutas_p) if isinstance(p, dict)]


def _resumen_sistema(raiz, query):
    cached = _SISTEMA_CACHE.get(str(raiz))
    if cached and _now() - cached[0] < SISTEMA_TTL:
        return cached[1]
    r = _safe(lambda: diagnostico.resumen(raiz, noches=7, sistema=query.get("_sistema")), None)
    if r is not None:
        _SISTEMA_CACHE[str(raiz)] = (_now(), r)
    return r


def _demo_hoy(con, raiz):
    clave = (str(raiz), _catalog_stamp(raiz), _now().strftime("%Y%m%d%H"))
    if _HOY_CACHE.get("clave") != clave:
        desde = np.datetime64(_now(), "D") - np.timedelta64(60, "D")
        cargadas = {}

        def h1(inst):
            if inst not in cargadas:
                cargadas[inst] = datos.cargar(inst, "H1", raiz / "datos", desde=desde)
            return cargadas[inst]
        curva = hoy_datos.curva_demo(con, h1)
        activas = [s for s in diario.active(con) if s["label"] != "control"]
        franja = []
        if activas and curva["total"]:
            ritmos = [_safe(lambda s=s: _backtest_ritmo(raiz, s), (np.array([]), 0.0)) for s in activas]
            pnls = np.concatenate([r[0] for r in ritmos]) if ritmos else np.array([])
            franja = hoy_datos.franja_demo(curva["estrategias"], pnls, sum(r[1] for r in ritmos),
                                           float(np.mean([s["capital"] or 0 for s in activas])))
        _HOY_CACHE.clear()
        _HOY_CACHE.update(clave=clave, curva=curva, resumen=hoy_datos.resumen_demo(con, curva), franja=franja,
                          abiertas=hoy_datos.abiertas(con, h1))
    return _HOY_CACHE


def _titular_hoy(e):
    partes = [f'<strong class="{_TONO[e["nivel"]]}">{esc(e["titular"])}</strong><span class="suave">{esc(e["frase"])}</span>']
    if e["conocidos"]:
        n = len(e["conocidos"])
        b, pop = piezas.ayuda("h-conocidos", "Avisos conocidos",
                              f"{', '.join(e['conocidos'])} traen datos raros desde hace al menos tres noches. Quant no "
                              "sobrescribe nada con ellos y no cambian el estado. Quitarlos del universo es decisión tuya.")
        partes.append(f'<span class="etiqueta aviso">{n} aviso{"s" if n != 1 else ""} conocido{"s" if n != 1 else ""}</span>'
                      f'<span class="con-ayuda">{b}</span>{pop}')
    nuevos = e["avisos"] if e["nivel"] != "rojo" else e["avisos"][1:]
    partes += [f'<span class="aviso peq">{esc(a)}</span>' for a in nuevos[:6]]
    return "".join(partes)


def _cifras_hoy(con, d):
    if d.get("error"):
        return ('<div class="cifras">' + piezas.cifra("Resultado de la demo", "–", _FALLO_DEMO, "", _ayuda_hoy("resultado"), grande=True)
                + piezas.cifra("Ya cerrado", "–", _FALLO_DEMO, "", _ayuda_hoy("cerrado"))
                + piezas.cifra("Tus estrategias", "–", _FALLO_DEMO, "", _ayuda_hoy("propias"))
                + piezas.cifra("Comprar y mantener", "–", _FALLO_DEMO, "", _ayuda_hoy("controles")) + "</div>")
    r = d["resumen"]
    n_e = len([s for s in diario.active(con) if s["label"] != "control"])
    eur = lambda v: f"{piezas.firmar(v)} €" if v is not None else "–"
    pct = lambda v: f"{piezas.firmar(v)} %" if v is not None else "–"
    tono = lambda v: "sube" if (v or 0) > 0 else "baja" if (v or 0) < 0 else ""
    if r["pct_estrategias"] is not None and r["pct_controles"] is not None:
        dif = r["pct_estrategias"] - r["pct_controles"]
        compara = f"Tus estrategias van {piezas.num(abs(dif))} puntos {'mejor' if dif >= 0 else 'peor'}"
    else:
        compara = "Sin controles con los que comparar"
    cerrado_sub = (f"{r['n_cerradas']} operaciones; lo demás puede cambiar" if r["n_cerradas"]
                   else "Aún no hay operaciones cerradas en la demo.")
    return ('<div class="cifras">'
            + piezas.cifra("Resultado de la demo", eur(r["total"]) if r["capital"] else "–",
                           f"{pct(r['pct_total'])} sobre {piezas.num(r['capital'], 0)} € de papel" if r["capital"]
                           else "La demo no tiene estrategias activas.", tono(r["total"]), _ayuda_hoy("resultado"), grande=True)
            + piezas.cifra("Ya cerrado", eur(r["cerrado"]), cerrado_sub, tono(r["cerrado"]), _ayuda_hoy("cerrado"))
            + piezas.cifra("Tus estrategias", pct(r["pct_estrategias"]), f"Las {n_e} de la demo que no son controles",
                           tono(r["pct_estrategias"]), _ayuda_hoy("propias"))
            + piezas.cifra("Comprar y mantener", pct(r["pct_controles"]), compara, tono(r["pct_controles"]),
                           _ayuda_hoy("controles"))
            + "</div>")


def _velas_manual(raiz):
    clave = ("velas", str(raiz), _now().strftime("%Y%m%d%H"))
    if clave not in _HOY_CACHE:
        crit = mcriterios.cargar(raiz / "config")
        uni = universo.cargar(raiz / "config")
        costes = mcostes.costes_de("US500", mcostes.cargar(raiz / "config" / "costes.json"), clase=universo.clase_de("US500", uni))
        barras = datos.cargar("US500", "M15", raiz / "datos", desde=np.datetime64(_now(), "D") - np.timedelta64(40, "D"))
        res = motor.backtest_serie(propias.ficha_base("manual"), "US500", barras, costes, crit["capital"])
        dias = np.unique(barras["ts"].astype("datetime64[D]"))
        corte = np.searchsorted(barras["ts"], dias[-5].astype("datetime64[ns]")) if len(dias) >= 5 else 0
        ts = barras["ts"][corte:].astype("datetime64[s]").astype("int64").tolist()
        velas = [{"time": t, "open": round(float(o), 2), "high": round(float(h), 2), "low": round(float(lo), 2),
                  "close": round(float(c), 2)} for t, o, h, lo, c in
                 zip(ts, barras["open"][corte:], barras["high"][corte:], barras["low"][corte:], barras["close"][corte:])]
        marcas = []
        for op in res.operaciones:
            if op.i_entrada >= corte:
                marcas.append({"time": ts[op.i_entrada - corte], "position": "belowBar" if op.lado > 0 else "aboveBar",
                               "shape": "arrowUp" if op.lado > 0 else "arrowDown", "text": "",
                               "color": "sube" if op.lado > 0 else "baja"})
            if op.i_salida >= corte:
                marcas.append({"time": ts[op.i_salida - corte], "position": "aboveBar", "shape": "circle",
                               "text": f"{piezas.firmar(op.pnl)} €", "color": "sube" if op.pnl > 0 else "baja"})
        _HOY_CACHE[clave] = (velas, sorted(marcas, key=lambda m: m["time"]))
    return _HOY_CACHE[clave]


def _mercado_btc(raiz):
    b = datos.cargar("BTCUSDT", "D1", raiz / "datos")
    n = min(160, len(b["close"]))
    ts = (b["ts"][-n:].astype("datetime64[s]").astype("int64")).tolist()
    velas = [{"time": t, "open": float(o), "high": float(h), "low": float(lo), "close": float(c)}
             for t, o, h, lo, c in zip(ts, b["open"][-n:], b["high"][-n:], b["low"][-n:], b["close"][-n:])]
    volumen = [{"time": v["time"], "value": float(x), "color": "sube" if v["close"] >= v["open"] else "baja"}
               for v, x in zip(velas, b["volume"][-n:])]
    return velas, volumen


def _grafico_hoy(raiz, d):
    curva, franja, specs = d["curva"], d["franja"], []
    total = curva["total"]
    span = (total[-1]["time"] - total[0]["time"]) / 86400 if total else 0
    periodos = [("1", "Día"), ("7", "Semana"), ("30", "Mes"), ("0", "Todo")]
    off = tuple(v for v, _ in periodos if v != "0" and span < int(v))
    tono = "sube" if total and total[-1]["value"] >= 0 else "baja"
    if total:
        series = [{"tipo": "area", "color": tono, "datos": (total)},
                  {"tipo": "linea", "color": "acento", "datos": (curva["estrategias"])},
                  {"tipo": "linea", "color": "tinta-suave", "discontinua": True, "datos": (curva["controles"])}]
        if franja:
            for k in ("bajo", "alto"):
                series.append({"tipo": "linea", "color": "linea-clara", "discontinua": True,
                               "datos": ([{"time": f["time"], "value": f[k]} for f in franja])})
        specs.append({"id": "g-curva", "periodos": True, "series": series, "lineas": [{"valor": 0, "color": "linea-clara"}]})
        sin = (f" Sin precio para {', '.join(curva['sin_precio'])}: su posición abierta cuenta como 0." if curva["sin_precio"] else "")
        curva_html = ('<div class="leyenda">' f'<span><i class="l-{tono}"></i>Total de la demo</span>'
                      '<span><i class="l-acento"></i>Tus estrategias</span><span><i class="l-suave"></i>Controles</span>'
                      + ('<span><i class="l-linea"></i>Lo esperable para tus estrategias</span>' if franja else "")
                      + '</div><div class="grafico" id="g-curva"></div>'
                      f'<p class="explica">Valor de la demo hora a hora, reconstruido con las operaciones y los '
                      f'precios guardados.{esc(sin)}</p>')
    else:
        curva_html = f'<p class="vacio">{_FALLO_DEMO if d.get("error") else "La demo aún no tiene historia que dibujar."}</p>'
    velas = _safe(lambda: _velas_manual(raiz), None)
    if velas and velas[0]:
        specs.append({"id": "g-velas", "series": [{"tipo": "velas", "datos": velas[0], "marcas": velas[1]}]})
        velas_html = ('<div class="leyenda"><span><i class="l-sube"></i>Compra / ganancia</span><span><i class="l-baja"></i>'
                      'Venta / pérdida</span></div><div class="grafico" id="g-velas"></div><p class="explica">Tu estrategia '
                      'manual (versión base) sobre el SP500, velas de 15 minutos de los últimos 5 días.</p>')
    else:
        velas_html = '<p class="vacio">No se pudo calcular: faltan los precios de 15 minutos del SP500.</p>'
    mercado = _safe(lambda: _mercado_btc(raiz), None)
    if mercado:
        specs.append({"id": "g-mercado", "series": [{"tipo": "velas", "datos": mercado[0]},
                                                   {"tipo": "histograma", "escala_propia": True, "datos": mercado[1]}]})
        mercado_html = ('<div class="leyenda"><span><i class="l-sube"></i>Día que sube</span><span><i class="l-baja"></i>Día que '
                        'baja</span><span><i class="l-linea"></i>Volumen</span></div><div class="grafico" id="g-mercado"></div>'
                        '<p class="explica">Bitcoin, velas diarias de los últimos 160 días con el volumen debajo.</p>')
    else:
        mercado_html = '<p class="vacio">Faltan los precios diarios de Bitcoin.</p>'
    html = ('<section aria-labelledby="t-graf"><div class="cab"><h2 id="t-graf">Gráfico</h2>'
            + piezas.selector("g", [("curva", "Curva de la demo"), ("velas", "Tus operaciones"), ("mercado", "Mercado")],
                              "curva", etiqueta="Tipo de gráfico")
            + '<div data-solo="curva">' + piezas.selector("p", periodos, "0", off, etiqueta="Periodo") + "</div>"
            + _boton("grafico") + "</div>"
            f'<div data-vista="curva">{curva_html}</div><div data-vista="velas" hidden>{velas_html}</div>'
            f'<div data-vista="mercado" hidden>{mercado_html}</div></section>')
    return html, specs


def _ultima_revision(con):
    marcas = _safe(lambda: [p["last_checked"] for p in con.execute("SELECT last_checked FROM demo_paper_positions")
                            if p["last_checked"]], []) + _safe(lambda: [
        r[0] for r in con.execute("SELECT value FROM demo_state WHERE key LIKE 'last_bar:%'")], [])
    return _safe(lambda: _hora_madrid(max(marcas, key=_utc)), "") if marcas else ""


def _abiertas_hoy(con, d):
    filas = []
    for a in d["abiertas"]:
        r = a["resultado"]
        tono = "sube" if (r or 0) >= 0 else "baja"
        c = a["cierres30"]
        importe = (f'<span class="importe {tono}">{piezas.firmar(r)} €<span>{piezas.num(a["ahora"])}</span></span>'
                   if r is not None else '<span class="importe suave">sin precio</span>')
        desde = _safe(lambda: ", " + _dia_corto(a["desde"]), "") if a["desde"] else ""
        filas.append(f'<li>{piezas.logo(a["instrumento"], 36)}<span class="que"><b>{esc(piezas.nombre(a["instrumento"]))}</b>'
                     f'<span class="suave peq">{esc(_ETIQUETA_ES.get(a["etiqueta"], str(a["etiqueta"])))}{esc(desde)}</span></span>'
                     f'{piezas.spark(c, 70, 28, "sube" if c and c[-1] >= c[0] else "baja")}{importe}</li>')
    ultima = _ultima_revision(con)
    lista = (f'<ul class="filas">{"".join(filas)}</ul>' if filas else f'<p class="vacio">{_FALLO_DEMO}</p>' if d.get("error")
             else '<p class="vacio">No hay posiciones abiertas.</p>')
    return ('<section aria-labelledby="t-ab"><div class="cab"><h2 id="t-ab">Abiertas ahora</h2>' + _boton("abiertas") + "</div>"
            + lista + '<p class="explica">Lo que darían si se cerraran al último precio, sin el coste de salida. '
            + esc(f"Último precio usado: {ultima}." if ultima else "La demo aún no ha usado ningún precio.") + "</p></section>")


def _propias_hoy(con):
    filas = []
    for clave in sorted(propias.PROPIAS, key=lambda k: k != "manual"):
        p = _safe(lambda: hoy_datos.progreso_propia(con, clave), None)
        nombre = _PROPIAS_ES.get(clave, clave)
        if not p or p["pf"] is None:
            filas.append(f'<div class="estrategia"><div><b>{esc(nombre)}</b><br><span class="suave peq">'
                         'Aún no hay experimentos con suficientes operaciones.</span></div></div>')
            continue
        evo = [v for _, v in p["evolucion"]]
        tono = "sube" if p["pf"] >= 1 else "baja"
        filas.append(f'<div class="estrategia"><div><b>{esc(nombre)}</b> <span class="etiqueta">{esc(p["fase"])}</span><br>'
                     f'<span class="suave peq">Gana {piezas.num(p["pf"])} € por cada euro que pierde. La mejor de '
                     f'{p["variantes"]} variantes.</span></div><div>{piezas.spark(evo, 120, 30, tono if len(set(evo)) > 1 else "suave")}</div>'
                     f'<div class="pf {tono}">{piezas.num(p["pf"])}</div>{piezas.barra_uno(p["pf"])}</div>')
    cuerpo = "".join(filas) if any("pf " in f for f in filas) else '<p class="vacio">Aún no hay experimentos.</p>'
    return ('<section aria-labelledby="t-pr"><div class="cab"><h2 id="t-pr"><a href="/propias">Tus estrategias</a></h2>'
            + _boton("estrategias") + "</div>" + cuerpo + "</section>")


def _anoche_hoy(parte, tareas):
    lineas = hoy_datos.resumen_noche(parte)
    cuerpo = ("".join(f'<p{" class=suave" if i else ""}>{esc(l)}</p>' for i, l in enumerate(lineas))
              + '<a href="#sistema" class="peq">Ver el detalle de la noche</a>') if lineas else \
        '<p class="vacio">Aún no hay ningún parte de la noche.</p>'
    prox = hoy_datos.proximo(tareas, datetime.now())
    return ('<section aria-labelledby="t-no" class="resumen"><div class="cab"><h2 id="t-no">Anoche</h2>' + _boton("anoche")
            + "</div>" + cuerpo + '<div class="proximo"><span class="suave peq">Lo próximo</span><br>'
            + esc(prox or "Sin datos de las tareas programadas.") + "</div></section>")


_FALLO_DEMO = "No se pudo calcular la demo ahora mismo."


def _anotar(raiz, donde, ex):
    import traceback
    _safe(lambda: (raiz / "registro" / "panel_errores.log").open("a", encoding="utf-8").write(
        f"{datetime.now():%Y-%m-%d %H:%M:%S} {donde}: {''.join(traceback.format_exception(ex))[-2000:]}\n"), None)


def hoy(con, raiz, query):
    partes = _partes(raiz)
    r = _resumen_sistema(raiz, query)
    tareas = (r or {}).get("tareas") or {}
    eventos = _safe(lambda: con.execute("SELECT ts, kind, detail_es FROM demo_events ORDER BY id DESC LIMIT 200").fetchall(), [])
    e = hoy_datos.estado(partes, tareas, eventos, datetime.now())
    vacia = {"curva": {"total": [], "estrategias": [], "controles": [], "sin_precio": []}, "franja": [], "abiertas": [],
             "resumen": {"total": 0, "cerrado": 0, "pct_total": None, "pct_estrategias": None, "pct_controles": None,
                         "capital": 0, "n_cerradas": 0}}
    try:
        d = _demo_hoy(con, raiz)
    except Exception as ex:
        _anotar(raiz, "demo de Hoy", ex)
        d = {**vacia, "error": True}
    grafico, specs = _safe(lambda: _grafico_hoy(raiz, d), ('<section><p class="vacio">No se pudo dibujar el gráfico.</p></section>', []))
    body = ('<div class="superficie">' + _safe(lambda: _cifras_hoy(con, d), "")
            + '<div class="zona">' + grafico
            + _safe(lambda: _abiertas_hoy(con, d), '<section><p class="vacio">No hay posiciones abiertas.</p></section>') + "</div>"
            + '<div class="zona">' + _safe(lambda: _propias_hoy(con), '<section><p class="vacio">Aún no hay experimentos.</p></section>')
            + _safe(lambda: _anoche_hoy(partes[0] if partes else None, tareas),
                    '<section><p class="vacio">Aún no hay ningún parte de la noche.</p></section>')
            + "</div></div>"
            + _safe(lambda: _sistema_bloque(r, partes[0] if partes else None, _pruebas(raiz), datetime.now()),
                    '<div class="superficie" id="sistema"><p class="vacio">No se pudo leer el diagnóstico.</p></div>'))
    return _layout("hoy", "Hoy", body, piezas.graficos(specs), titular=_titular_hoy(e), raiz=raiz, recarga=120)


_ETIQUETA_TONO = {"aprobada": "sube", "en_prueba": "aviso", "retirada": "baja"}
_FILTROS_DEMO = (("", "Todas"), ("control", "Controles"), ("aprobada", "Aprobadas"), ("en_prueba", "En prueba"),
                 ("retirada", "Retiradas"))
_MESES_L = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
            "noviembre", "diciembre")
_AYUDA_TABLA_DEMO = ("Las estrategias de la demo", "Control: solo compra y mantiene, para comparar. Aprobada: pasó todas "
                     "las pruebas. En prueba: se está observando antes de decidir. Retirada: se apartó de la demo y ya no "
                     "cuenta en los totales.\n\nFrente al backtest dice si va mejor o peor de lo que prometía su backtest; "
                     "hace falta un mínimo de {n} operaciones para que la comparación signifique algo.", "Desvío")


def _frente_backtest(n, semanas, pnl, pnls, capital, cfg):
    minimo = cfg["drift_min_trades"]
    if n < minimo and semanas < cfg["drift_min_weeks"]:
        return f"faltan {minimo - n} operaciones", "suave"
    if not n:
        return "aún sin operaciones", "suave"
    if not len(pnls):
        return "sin backtest para comparar", "suave"
    bajo, _, alto = desvio.expected_band(pnls, n, capital, pct=cfg["drift_percentile"])
    if pnl < bajo:
        return f"por debajo del {cfg['drift_percentile']} % peor de su backtest", "baja"
    if pnl > alto:
        return "mejor de lo esperable", "sube"
    return "dentro de lo esperable", ""


def _dm(texto):
    t = _utc(texto).tz_convert("Europe/Madrid")
    return f"{t.day:02d}/{t.month:02d}"


_BANDA_CACHE = {}
_CIERRE_ES = {"stop": "por stop", "objetivo": "por objetivo", "senal": "por señal", "retirada": "al retirarla"}


def _fracciones_demo(raiz, s):
    clave = (str(raiz), s["id"], s["added"])
    if clave not in _BANDA_CACHE:
        try:
            _BANDA_CACHE[clave] = np.asarray(noche._backtest_fractions(s, {"raiz": raiz}), float)
        except Exception as ex:
            _anotar(raiz, f"banda de la demo {s['id']}", ex)
            return np.array([])
    return _BANDA_CACHE[clave]


def _etiqueta_demo(s):
    return "retirada" if s["status"] == "retired" else s["label"]


def _regla_retirada(cfg):
    return ('<section aria-labelledby="t-re"><div class="cab"><h2 id="t-re">Cuándo se retira una estrategia</h2></div>'
            f'<p>Mientras una estrategia tenga menos de <b>{cfg["drift_min_trades"]} operaciones</b> y lleve menos de '
            f'<b>{cfg["drift_min_weeks"]} semanas</b> en la demo, solo se observa: es pronto para juzgarla.</p>'
            '<p>Cuando llega a una de las dos, se compara con su backtest. Si su resultado cae por debajo de lo que el '
            f'backtest daba como el {cfg["drift_percentile"]} % de los peores casos, se retira de la demo.</p>'
            f'<p class="suave peq">También se marca si sus costes reales superan en {piezas.num(cfg["cost_ratio_flag"], 1)} '
            'veces lo previsto.</p></section>')


def _fila_demo(s, ops, abierta, cfg, raiz):
    etq = _etiqueta_demo(s)
    n = len(ops)
    cerrado = sum(o["pnl"] or 0 for o in ops)
    total = cerrado + (abierta or 0)
    costes = sum(o["costs"] or 0 for o in ops)
    if etq == "retirada":
        cuando = f" el {_dm(s['retired'])}" if s["retired"] else ""
        frente, tono_f = f"Retirada{cuando}: {s['retire_reason_es'] or 'sin motivo anotado'}", "baja"
    elif s["label"] == "control":
        frente, tono_f = "no se compara: es la referencia", "suave"
    else:
        semanas = (desvio.naive(_now()) - desvio.naive(datetime.fromisoformat(s["added"]))).days / 7
        compara = n and (n >= cfg["drift_min_trades"] or semanas >= cfg["drift_min_weeks"])
        pnls = _fracciones_demo(raiz, s) if compara else np.array([])
        frente, tono_f = _frente_backtest(n, semanas, cerrado, pnls, s["capital"] or 0, cfg)
    inst = str(s["instrument"] or "")
    fam = FAMILIA_ES.get(s["family"], s["family"] or "")
    aciertos = f"{round(sum(1 for o in ops if (o['pnl'] or 0) > 0) / n * 100)} %" if n else '<span class="suave">–</span>'
    tono_r = "sube" if total > 0 else "baja" if total < 0 else "suave"
    return (f'<tr><td><span class="con-logo">{piezas.logo(inst, 28)}<span><b>{esc(piezas.nombre(inst))}</b> '
            f'<span class="suave peq">{esc(s["timeframe"] or "")}</span><br><span class="suave peq">{esc(fam)}</span></span></span></td>'
            f'<td><span class="etiqueta {_ETIQUETA_TONO.get(etq, "")}">{esc(_ETIQUETA_ES.get(etq, str(etq)))}</span></td>'
            f'<td>{n}{" <span class=" + chr(34) + "suave peq" + chr(34) + ">+1 abierta</span>" if abierta is not None else ""}</td>'
            f'<td>{aciertos}</td><td>{piezas.num(costes) + " €" if costes else "<span class=" + chr(34) + "suave" + chr(34) + ">–</span>"}</td>'
            f'<td class="{tono_f} peq">{esc(frente)}</td><td class="{tono_r}"><b>{piezas.firmar(total)} €</b></td></tr>')


def _peor_caida(curva):
    pico, peor = None, 0.0
    for p in curva:
        pico = p["value"] if pico is None else max(pico, p["value"])
        peor = min(peor, p["value"] - pico)
    return peor


def demo(con, raiz, query):
    from quant.demo import config as dconfig
    cfg = dconfig.cargar_de(raiz)
    hay_demo = _tabla(con, "demo_strategies") and _tabla(con, "demo_trades")
    filtro = query.get("etiqueta") or ""
    filtro = filtro if filtro in dict(_FILTROS_DEMO) else ""
    todas = con.execute("SELECT s.*, " + ("c.family FROM demo_strategies s LEFT JOIN combinations c ON c.id = s.combo_id"
                                         if _tabla(con, "combinations") else "NULL AS family FROM demo_strategies s")
                        + " WHERE s.status IN ('active', 'retired') ORDER BY s.status, s.id").fetchall() if hay_demo else []
    activas = [s for s in todas if s["status"] == "active"]
    trades = con.execute("SELECT * FROM demo_trades ORDER BY exit_ts DESC, id DESC").fetchall() if hay_demo else []
    por_s = {}
    for t in trades:
        por_s.setdefault(t["strategy_id"], []).append(t)
    try:
        d = _demo_hoy(con, raiz) if hay_demo else {"resumen": {"total": 0, "cerrado": 0, "pct_total": None, "capital": 0,
                                                              "n_cerradas": 0}, "curva": {"total": []}, "abiertas": []}
        error = False
    except Exception as ex:
        _anotar(raiz, "demo", ex)
        d, error = {"resumen": None, "curva": {"total": []}, "abiertas": []}, True
    abiertas = {a["estrategia"]: a["resultado"] or 0.0 for a in d["abiertas"]}
    if activas:
        inicio = min(datetime.fromisoformat(s["added"][:10]) for s in activas)
        capital = sum(s["capital"] or 0 for s in activas)
        frase = (f"{len(activas)} estrategia{'s' if len(activas) != 1 else ''} operando con {piezas.num(capital, 0)} € de papel "
                 f"desde el {inicio.day} de {_MESES_L[inicio.month - 1]}.")
    else:
        frase = "La demo no tiene estrategias activas."
    titular = f'<h1>Demo</h1><span class="suave">{esc(frase)}</span>'
    r = d["resumen"]
    eur = lambda v: f"{piezas.firmar(v)} €"
    tono = lambda v: "sube" if v > 0 else "baja" if v < 0 else ""
    costes = sum(t["costs"] or 0 for s in activas for t in por_s.get(s["id"], []))
    if error:
        cifras = "".join(piezas.cifra(e, "–", _FALLO_DEMO, "", a, grande=g) for e, a, g in (
            ("Resultado total", _ayuda_hoy("resultado"), True), ("Ya cerrado", _ayuda_hoy("cerrado"), False),
            ("Costes pagados", None, False), ("Peor caída hasta ahora", None, False)))
    else:
        caida = _peor_caida(d["curva"]["total"])
        cifras = (piezas.cifra("Resultado total", eur(r["total"]) if r["capital"] else "–",
                               f"{piezas.firmar(r['pct_total'])} % sobre {piezas.num(r['capital'], 0)} €" if r["capital"]
                               else "La demo no tiene estrategias activas.", tono(r["total"]), _ayuda_hoy("resultado"), grande=True)
                  + piezas.cifra("Ya cerrado", eur(r["cerrado"]), f"{r['n_cerradas']} operaciones terminadas" if r["n_cerradas"]
                                 else "Aún no hay operaciones cerradas en la demo.", tono(r["cerrado"]), _ayuda_hoy("cerrado"))
                  + piezas.cifra("Costes pagados", f"{piezas.num(costes)} €", "Comisiones, diferencial y deslizamiento")
                  + piezas.cifra("Peor caída hasta ahora", eur(caida) if d["curva"]["total"] else "–", "Desde el máximo anterior",
                                 "baja" if caida < 0 else ""))
    vistas = [s for s in todas if not filtro or _etiqueta_demo(s) == filtro]
    filas = "".join(_fila_demo(s, por_s.get(s["id"], []), abiertas.get(s["id"]), cfg, raiz) for s in vistas)
    b, pop = piezas.ayuda("h-tabla-demo", _AYUDA_TABLA_DEMO[0], _AYUDA_TABLA_DEMO[1].format(n=cfg["drift_min_trades"]),
                          _AYUDA_TABLA_DEMO[2])
    selector = ('<div class="selector" role="group" aria-label="Filtrar por etiqueta">' + "".join(
        f'<a href="/demo{"?etiqueta=" + v if v else ""}"{" aria-current=" + chr(34) + "page" + chr(34) if v == filtro else ""}>{t}</a>'
        for v, t in _FILTROS_DEMO) + "</div>")
    if filas:
        tabla = ('<div class="scroll"><table><thead><tr><th>Estrategia</th><th>Etiqueta</th><th>Operaciones</th><th>Aciertos</th>'
                 '<th>Costes pagados</th><th>Frente al backtest</th><th>Resultado</th></tr></thead><tbody>' + filas + "</tbody></table></div>")
    else:
        tabla = ('<p class="vacio">La demo no tiene estrategias activas.</p>' if not todas
                 else '<p class="vacio">Ninguna estrategia de la demo lleva esta etiqueta.</p>')
    ids = {s["id"]: s for s in vistas}
    ops = [t for t in trades if t["strategy_id"] in ids][:50]
    lista = "".join(
        f'<li>{piezas.logo(str(ids[t["strategy_id"]]["instrument"] or ""), 32)}<span class="que"><b>'
        f'{esc(piezas.nombre(str(ids[t["strategy_id"]]["instrument"] or "")))} · {"Compra" if (t["side"] or 0) > 0 else "Venta"}</b>'
        f'<span class="suave peq">{_dm(t["entry_ts"])} → {_dm(t["exit_ts"])}, cerrada {_CIERRE_ES.get(t["reason"], "")}</span></span>'
        f'<span class="importe {"sube" if (t["pnl"] or 0) >= 0 else "baja"}">{piezas.firmar(t["pnl"] or 0)} €'
        f'<span>costes {piezas.num(t["costs"] or 0)} €</span></span></li>' for t in ops)
    cerradas = (f'<ul class="filas">{lista}</ul>' if lista else '<p class="vacio">Aún no hay operaciones cerradas en la demo.</p>')
    body = (f'<div class="superficie"><div class="cifras">{cifras}</div>'
            f'<div class="zona una"><section aria-labelledby="t-es"><div class="cab"><h2 id="t-es">Las estrategias de la demo</h2>'
            f'{selector}{b}{pop}</div>{tabla}</section></div>'
            f'<div class="zona mitades">{_regla_retirada(cfg)}'
            f'<section aria-labelledby="t-op"><div class="cab"><h2 id="t-op">Operaciones cerradas</h2></div>{cerradas}</section>'
            "</div></div>")
    return _layout("demo", "Demo", body, titular=titular, raiz=raiz)


def _select(name, label, options, current):
    opts = '<option value="">Todos</option>' + "".join(
        f'<option value="{esc(o)}"{" selected" if o == current else ""}>{esc(VERDICT_ES.get(o, o))}</option>' for o in options)
    return f'<label>{label} <select name="{name}">{opts}</select></label>'


def _catalog_stamp(raiz):
    return tuple(f.stat().st_mtime_ns if f.exists() else 0 for f in (raiz / "catalogo.db", raiz / "catalogo.db-wal"))


FAMILIA_ES = {"cruce_medias": "Cruce de medias", "recuperacion_media": "Vuelta a la media", "ruptura_donchian": "Ruptura de máximos",
              "rsi_reversion": "Rebote tras caída (RSI)", "bollinger_reversion": "Rebote en bandas", "momentum_rotacion": "Momento",
              "tendencia_cripto": "Tendencia cripto", "zscore_reversion": "Vuelta a la media (z)", "ruptura_maximo_20": "Ruptura de 20 días",
              "control_comprar_mantener": "Comprar y mantener"}
PLAZO_CORTO = {"D1": "diario", "H4": "4 horas", "H1": "1 hora", "M15": "15 min", "M5": "5 min", "W1": "semanal"}
MERCADO_ES = {"cripto": "Cripto", "indice": "Índices", "accion": "Acciones", "forex": "Divisas", "materia": "Materias primas"}
_PARAM_ES = {"fast": "rápida", "slow": "lenta", "kind": "", "stop_atr": "stop ATR", "n": "periodo", "entry": "entrada",
             "exit": "salida", "threshold": "umbral", "z": "z"}
_VERDICTO = {"pasa": ("Pasa", "sube"), "dudosa": ("Dudosa", "aviso"), "no_pasa": ("No pasa", "baja")}
_ORDENES = {"nota": "Nota", "pf": "Gana por € perdido", "cagr": "Rentabilidad al año"}
POR_PAGINA = 50


def _tabla(con, nombre):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nombre,)).fetchone() is not None


def _ranking_cached(con, raiz, uni):
    stamp = (str(raiz), _catalog_stamp(raiz))
    if _RANKING_CACHE.get("stamp") != stamp:
        if not _tabla(con, "combinations"):
            _RANKING_CACHE.clear()
            _RANKING_CACHE.update(stamp=stamp, filas=[], latest=[])
            return []
        latest = rk.latest_results(con)
        cache = _safe(lambda: {r[0]: (json.loads(r[1]), json.loads(r[2])) for r in
                               con.execute("SELECT resultado_id, stats_json, nota_json FROM panel_stats")}, {})
        filas = []
        for r in rk.rows(con, limit=10**9, uni=uni, latest=latest):
            if r["verdict"] not in _VERDICTO:
                continue
            st, puntos = cache.get(r["resultado_id"], (None, None))
            inst = str(r["instrument"])
            filas.append({**r, "_stats": st, "_puntos": puntos, "_nota": puntos["nota"] if puntos else None,
                          "_mercado": inst if inst.startswith("cartera") else (universo.clase_de(inst, uni) or "")})
        _RANKING_CACHE.clear()
        _RANKING_CACHE.update(stamp=stamp, filas=filas, latest=latest)
    return _RANKING_CACHE["filas"]


def _entero(v, defecto, minimo=None, maximo=None):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return defecto
    return max(minimo, n) if minimo is not None and n < minimo else min(maximo, n) if maximo is not None and n > maximo else n


def _ranking_filtrar(filas, query):
    q = (query.get("q") or "").strip().lower()
    ver, mer, fam, pla = (query.get(k) or "" for k in ("veredicto", "mercado", "familia", "plazo"))
    minima = _entero(query.get("nota"), 0, 0, 100)
    orden = query.get("orden") if query.get("orden") in _ORDENES else "nota"

    def pasa(r):
        texto = f'{r["instrument"]} {piezas.nombre(str(r["instrument"]))} {r["family"]} {FAMILIA_ES.get(r["family"], "")}'.lower()
        return ((not q or q in texto) and (not ver or r["verdict"] == ver) and (not fam or r["family"] == fam)
                and (not pla or r["timeframe"] == pla) and (not mer or r["_mercado"] == mer or r["_mercado"].endswith(":" + mer))
                and (not minima or (r["_nota"] is not None and r["_nota"] >= minima)))
    clave = {"nota": "_nota", "pf": "profit_factor", "cagr": "cagr"}[orden]
    lista = [r for r in filas if pasa(r)]
    lista.sort(key=lambda r: (-(r[clave] if r[clave] is not None else -1e9), rk._ORDER.get(r["verdict"], 9),
                              -(r["profit_factor"] if r["profit_factor"] is not None else -1e9)))
    if orden == "nota":
        lista.sort(key=lambda r: rk._ORDER.get(r["verdict"], 9))
    paginas_n = max(1, -(-len(lista) // POR_PAGINA))
    pagina = _entero(query.get("pagina"), 1, 1, paginas_n)
    return lista[(pagina - 1) * POR_PAGINA: pagina * POR_PAGINA], len(lista)


def _params_cortos(params):
    return ", ".join(f"{_PARAM_ES.get(k, k)} {v}".strip() for k, v in params.items()) or "sin parámetros"


def _tarjeta(r):
    st, inst = r["_stats"], str(r["instrument"])
    nombre_v, tono_v = _VERDICTO[r["verdict"]]
    mt = lambda k, v, c="": f'<div><span>{esc(k)}</span><b class="{c}">{esc(v)}</b></div>'
    pct = lambda v, d=1: f"{piezas.firmar(v * 100, d)} %" if v is not None else "–"
    metricas = "".join([
        mt("Anual", pct(r["cagr"]), "sube" if (r["cagr"] or 0) >= 0 else "baja"),
        mt("Periodo", f'{st["desde"][:4]}, {piezas.num(st["anios"], 1)} años' if st else "–"),
        mt("Caída máx.", f'−{piezas.num(abs(r["drawdown"]) * 100, 1)} %' if r["drawdown"] is not None else "–", "baja"),
        mt("Gana por € perdido", piezas.num(r["profit_factor"]) if r["profit_factor"] is not None else "–"),
        mt("Rentabilidad total", pct(r["return_total"]), "sube" if (r["return_total"] or 0) >= 0 else "baja"),
        mt("Acierto", f'{piezas.num(r["win_rate"] * 100, 0)} %' if r["win_rate"] is not None else "–"),
        mt("Sharpe fuera", piezas.num(r["sharpe_oos"]) if r["sharpe_oos"] is not None else "–"),
        mt("Operaciones", str(r["trades"] if r["trades"] is not None else "–"))])
    logo = piezas.logo(inst, 26) if inst in piezas.NOMBRES else ""
    return (f'<a class="tarjeta" href="/estrategia/{int(r["combo_id"])}">{ficha_html.circulo(r["_nota"])}'
            f'<div><div class="nombre">{logo}{esc(piezas.nombre(inst))} <span class="suave peq">'
            f'{esc(PLAZO_CORTO.get(r["timeframe"], str(r["timeframe"])))}</span> <span class="etiqueta {tono_v}">{nombre_v}</span></div>'
            f'<div class="fam">{esc(FAMILIA_ES.get(r["family"], r["family"]))}: {esc(_params_cortos(r["params"]))}</div></div>'
            f'<div class="metricas">{metricas}</div>{ficha_html.minibarras(r["_puntos"]["atributos"] if r["_puntos"] else None) or "<span></span>"}</a>')


def _opciones(nombre, etiqueta, opciones, actual):
    ops = '<option value="">Todos</option>' + "".join(
        f'<option value="{esc(v)}"{" selected" if v == actual else ""}>{esc(t)}</option>' for v, t in opciones)
    return f'<label>{esc(etiqueta)}<select name="{nombre}">{ops}</select></label>'


def _cifras_barrido(raiz):
    ruta = raiz / "registro" / "barrido_ultimo.json"
    b = _safe(lambda: json.loads(ruta.read_text(encoding="utf-8")), None)
    if not isinstance(b, dict):
        return '<div class="cifras">' + piezas.cifra("Último barrido", "–", "Aún no hay un barrido registrado.") + "</div>"
    fecha = _safe(lambda: _dia_corto(datetime.fromtimestamp(ruta.stat().st_mtime, timezone.utc).isoformat()), "")
    n = lambda k: piezas.num(b.get(k) or 0, 0)
    return ('<div class="cifras">' + piezas.cifra("Último barrido", n("tested"), f"combinaciones probadas el {fecha}", grande=True)
            + piezas.cifra("Pasan", n("pasa"), "cumplen todos los criterios", "sube")
            + piezas.cifra("Dudosas", n("dudosa"), "casi; fallan por poco", "aviso")
            + piezas.cifra("Sin datos", n("pendiente_datos"), "falta historia de precios", "suave") + "</div>")


def ranking(con, raiz, query):
    uni = universo.cargar(raiz / "config")
    filas = _ranking_cached(con, raiz, uni)
    lista, total = _ranking_filtrar(filas, query)
    familias_v = sorted({r["family"] for r in filas}, key=lambda f: FAMILIA_ES.get(f, f))
    plazos = sorted({r["timeframe"] for r in filas})
    orden = query.get("orden") if query.get("orden") in _ORDENES else "nota"
    minima = _entero(query.get("nota"), 0, 0, 100)
    form = ('<form class="filtros" method="get" action="/ranking" role="search" aria-label="Filtrar estrategias">'
            f'<label>Buscar<input type="search" name="q" value="{esc(query.get("q") or "")}" placeholder="Activo o familia"></label>'
            + _opciones("veredicto", "Veredicto", [(k, v[0]) for k, v in _VERDICTO.items()], query.get("veredicto") or "")
            + _opciones("mercado", "Mercado", list(MERCADO_ES.items()), query.get("mercado") or "")
            + _opciones("familia", "Familia", [(f, FAMILIA_ES.get(f, f)) for f in familias_v], query.get("familia") or "")
            + _opciones("plazo", "Plazo", [(p, PLAZO_CORTO.get(p, p)) for p in plazos], query.get("plazo") or "")
            + f'<label>Nota mínima<input type="number" name="nota" min="0" max="100" value="{minima or ""}"></label>'
            + '<label>Ordenar por<select name="orden">' + "".join(
                f'<option value="{k}"{" selected" if k == orden else ""}>{esc(v)}</option>' for k, v in _ORDENES.items())
            + '</select></label><button type="submit">Filtrar</button><a class="limpiar" href="/ranking">Quitar filtros</a>'
            f'<span class="cuenta">{piezas.num(total, 0)} de {piezas.num(len(filas), 0)} estrategias</span></form>')
    b, pop = piezas.ayuda("h-nota", "La nota Quant", "Una nota de 0 a 100 que resume ocho aspectos: rentabilidad frente al "
                          "riesgo, aguante con datos no vistos, caída máxima, costes, experiencia acumulada, regularidad, ventaja "
                          "sobre comprar y mantener y robustez. Ordena; no aprueba ni suspende.\n\nSolo la tienen las estrategias "
                          "que pasan o casi.", "Nota Quant")
    leyenda = ('<span class="franjas"><span>Nota:</span><span class="nota nota-4">75+</span>muy alta<span class="nota nota-3">70</span>'
               'alta<span class="nota nota-2">65</span>media<span class="nota nota-1">&lt;65</span>baja</span>')
    paginas_n = max(1, -(-total // POR_PAGINA))
    pagina = _entero(query.get("pagina"), 1, 1, paginas_n)
    from urllib.parse import urlencode
    enlace = lambda p: "/ranking?" + urlencode({**{k: v for k, v in query.items() if k in (
        "q", "veredicto", "mercado", "familia", "plazo", "nota", "orden") and v}, "pagina": p})
    nav = (f'<nav class="paginas" aria-label="Páginas">'
           + (f'<a href="{esc(enlace(pagina - 1))}">Anteriores</a>' if pagina > 1 else "<span></span>")
           + f'<span class="suave peq">Página {pagina} de {paginas_n}</span>'
           + (f'<a href="{esc(enlace(pagina + 1))}">Siguientes</a>' if pagina < paginas_n else "<span></span>") + "</nav>")
    tarjetas = "".join(_tarjeta(r) for r in lista) or '<p class="vacio">Ninguna estrategia cumple estos filtros.</p>'
    body = ('<div class="superficie">' + _cifras_barrido(raiz) + form
            + f'<div class="zona una"><section aria-labelledby="t-top"><div class="cab"><h2 id="t-top">Estrategias probadas</h2>'
            f'{leyenda}{b}</div>{pop}<div class="tarjetas">{tarjetas}</div>{nav}</section></div></div>')
    titular = ('<h1>Ranking</h1><div class="selector" role="group" aria-label="Qué estrategias ver">'
               '<a href="/ranking" aria-current="page">Barrido</a><a href="/propias">Propias</a></div>'
               '<span class="suave">Estrategias de fuentes públicas probadas por el barrido semanal.</span>')
    script = ("<script>document.querySelector('form.filtros').addEventListener('change', function (e) {"
              " if (e.target.name !== 'q') e.currentTarget.requestSubmit(); });</script>")
    return _layout("ranking", "Ranking", body, script, titular=titular, raiz=raiz)


_PLAZO_ES = {"M5": "velas de 5 minutos", "M15": "velas de 15 minutos", "H1": "velas de 1 hora",
             "H4": "velas de 4 horas", "D1": "velas diarias", "W1": "velas semanales"}
_MES_LARGO = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
              "noviembre", "diciembre")
def _pct(v, signo=False, dec=1):
    if v is None:
        return "–"
    return (f"{v * 100:+.{dec}f} %" if signo else f"{v * 100:.{dec}f} %")


def _mes_es(clave):
    y, m = clave.split("-")
    return f"{_MES_LARGO[int(m) - 1]} {y}"


_ANALISIS_CACHE = {}
_PARAM_LARGO = {"fast": "Media rápida", "slow": "Media lenta", "kind": "Tipo", "stop_atr": "Stop", "n": "Periodo",
                "entry": "Entrada", "exit": "Salida", "threshold": "Umbral", "z": "Desviaciones"}
_FALTAN_PRECIOS = "No se pudo calcular: faltan los precios."


def _valor_param(k, v):
    if k == "kind":
        return {"SMA": "simple", "EMA": "exponencial"}.get(v, str(v))
    if k == "stop_atr":
        return f"{v} ATR"
    if k in ("fast", "slow", "n"):
        return f"{v} velas"
    return str(v)


def _analisis_resultado(con, raiz, combo_id, resultado_id, ficha, inst):
    """Stored analysis for the result, else computed now and kept in memory. Raises when prices are missing."""
    fila = _safe(lambda: con.execute("SELECT json FROM panel_analisis WHERE clave = ?", (f"r:{resultado_id}",)).fetchone(), None)
    if fila is not None:
        return json.loads(fila[0])
    clave = (str(raiz), resultado_id)
    if clave not in _ANALISIS_CACHE:
        if len(_ANALISIS_CACHE) >= 200:
            _ANALISIS_CACHE.clear()
        _ranking_cached(con, raiz, universo.cargar(raiz / "config"))
        latest = _RANKING_CACHE["latest"]
        r = next((x for x in latest if x["resultado_id"] == resultado_id), None)
        vecinos = precalcular.vecinos_barrido(latest, r) if r is not None else []
        _ANALISIS_CACHE[clave] = precalcular.analisis_de(raiz, ficha, inst, vecinos)
    return _ANALISIS_CACHE[clave]


def _velas_estrategia(raiz, combo_id, ficha, inst, hasta=None):
    clave = ("velas", str(raiz), combo_id, inst, hasta)
    if clave not in _EQUITY_CACHE:
        crit = mcriterios.cargar(raiz / "config")
        uni = universo.cargar(raiz / "config")
        barras = datos.cargar(inst, ficha["universo"]["plazo"], raiz / "datos", desde=universo.desde_de(inst, uni))
        if hasta is not None:
            antes = barras["ts"] < np.datetime64(hasta)
            barras = {k: v[antes] for k, v in barras.items()}
        costes = mcostes.costes_de(inst, mcostes.cargar(raiz / "config" / "costes.json"), clase=universo.clase_de(inst, uni))
        res = motor.backtest_serie(ficha, inst, barras, costes, crit["capital"])
        t0 = max(0, len(barras["ts"]) - 400)
        ts = barras["ts"][t0:].astype("datetime64[s]").astype("int64").tolist()
        velas = [{"time": t, "open": float(o), "high": float(h), "low": float(lo), "close": float(c)}
                 for t, o, h, lo, c in zip(ts, barras["open"][t0:], barras["high"][t0:], barras["low"][t0:], barras["close"][t0:])]
        marcas = []
        for op in res.operaciones:
            if op.i_entrada >= t0:
                marcas.append({"time": ts[op.i_entrada - t0], "position": "belowBar" if op.lado > 0 else "aboveBar",
                               "shape": "arrowUp" if op.lado > 0 else "arrowDown", "text": "Compra" if op.lado > 0 else "Venta",
                               "color": "sube" if op.lado > 0 else "baja"})
            if op.i_salida >= t0 and op.motivo != "fin":
                marcas.append({"time": ts[op.i_salida - t0], "position": "aboveBar", "shape": "circle",
                               "text": f"{piezas.firmar(op.pnl, 0)} €", "color": "sube" if op.pnl > 0 else "baja"})
        _EQUITY_CACHE[clave] = (velas, sorted(marcas, key=lambda m: m["time"]))
    return _EQUITY_CACHE[clave]


def _kpi8(label, valor, sub, tono=""):
    return (f'<div><span class="suave peq">{esc(label)}</span><span class="val {tono}">{esc(valor)}</span>'
            f'<span class="suave peq">{esc(sub)}</span></div>')


def _caida(v):
    return "–" if v is None else f"−{piezas.num(abs(v) * 100, 1)} %"


def _mes_largo(x):
    return _mes_es(x["mes"]) if x else "–"


def _kpis_estrategia(m, st):
    t, f = m.get("total") or {}, m.get("fuera") or {}
    pct = lambda v, d=1: f"{piezas.firmar(v * 100, d)} %" if v is not None else "–"
    tono = lambda v: "sube" if (v or 0) >= 0 else "baja"
    if not st:
        return "".join([_kpi8("Gana por € perdido", piezas.num(t["profit_factor"]) if t.get("profit_factor") is not None else "–", "con costes"),
                        _kpi8("Rentabilidad anual", pct(t.get("cagr")), "media del backtest", tono(t.get("cagr"))),
                        _kpi8("Caída máxima", _caida(t.get("drawdown")), "peor caída desde un máximo", "baja"),
                        _kpi8("Operaciones", str(t.get("operaciones", "–")), "en todo el periodo"),
                        _kpi8("Sharpe fuera de muestra", piezas.num(f["sharpe"]) if f.get("sharpe") is not None else "–", "en los años que no vio"),
                        _kpi8("Sharpe total", piezas.num(t["sharpe"]) if t.get("sharpe") is not None else "–", "todo el periodo"),
                        _kpi8("Con costes al doble", pct(m.get("rentabilidad_costes_x2"), 0), "rentabilidad total"),
                        _kpi8("Montecarlo", _pc(m.get("montecarlo_dd_p95"), 1), "caída del 5 % peor")])
    total = t.get("rentabilidad")
    return "".join([
        _kpi8("Rentabilidad total", pct(total, 0), f'{st["desde"][:4]} a {st["hasta"][:4]}', tono(total)),
        _kpi8("Rentabilidad anual", pct(t.get("cagr")), "media compuesta por año", tono(t.get("cagr"))),
        _kpi8("Periodo estudiado", f'{piezas.num(st["anios"], 1)} años', f'{st["desde"]} a {st["hasta"]}'),
        _kpi8("Caída máxima", _caida(t.get("drawdown")), "peor caída desde un máximo", "baja"),
        _kpi8("Mejor mes", pct((st.get("mejor_mes") or {}).get("valor")), _mes_largo(st.get("mejor_mes")), "sube"),
        _kpi8("Peor mes", pct((st.get("peor_mes") or {}).get("valor")), _mes_largo(st.get("peor_mes")), "baja"),
        _kpi8("Sharpe fuera de muestra", piezas.num(f["sharpe"]) if f.get("sharpe") is not None else "–", "en los años que no vio"),
        _kpi8("Tiempo en el mercado", f'{piezas.num((st.get("tiempo_mercado") or 0) * 100, 0)} %',
              f'{piezas.num(st["duracion_media_dias"], 0)} días por operación' if st.get("duracion_media_dias") else "–")])


def _pc(v, d, signo=False):
    return "–" if v is None else f"{piezas.firmar(v * 100, d) if signo else piezas.num(v * 100, d)} %"


def _probado(m, st):
    d, f = m.get("dentro") or {}, m.get("fuera") or {}
    texto = (f'{piezas.num(st["anios"], 1)} años de datos, del {st["desde"]} al {st["hasta"]}. ' if st else "") + \
        "El 70 % primero sirve para medir y el 30 % final se reserva para comprobar sin haberlo visto."
    b, pop = piezas.ayuda("h-probado", "Dentro y fuera de muestra", "El backtest se parte en dos: con el 70 % primero se mide la "
                          "estrategia y el 30 % final se reserva para comprobarla sin haberlo visto. Si fuera rinde mucho peor que "
                          "dentro, lo más probable es que esté ajustada a la casualidad.", "Dentro y fuera de muestra")
    sh = lambda x: piezas.num(x["sharpe"]) if x.get("sharpe") is not None else "–"
    return ('<div class="zona una"><section><div class="cab"><h2>Cómo se ha probado</h2>' + b + "</div>" + pop
            + f'<p>{esc(texto)}</p><div class="split"><div class="in">Medición: {esc(str(d.get("operaciones", "–")))} operaciones, '
            f'Sharpe {sh(d)}</div><div class="out">Fuera de muestra: {esc(str(f.get("operaciones", "–")))} operaciones, Sharpe {sh(f)}</div></div>'
            f'<div class="chips"><span class="chip">Costes al doble: {_pc(m.get("rentabilidad_costes_x2"), 0, True)}</span>'
            f'<span class="chip">Variantes que ganan: {_pc(m.get("robustez"), 0)} de {esc(str(m.get("variantes", "–")))}</span>'
            f'<span class="chip">Montecarlo, caída del 5 % peor: {_pc(m.get("montecarlo_dd_p95"), 1)}</span></div></section></div>')


def _ops_html(st_ops, a):
    if not st_ops:
        filas = '<p class="vacio">El backtest no tiene operaciones.</p>'
    else:
        pct = lambda v: f"{piezas.firmar(v * 100)} %" if v is not None else "–"
        fila = lambda l, v, c="": f'<li><span class="que">{esc(l)}</span><b class="{c}">{esc(v)}</b></li>'
        filas = '<ul class="filas">' + "".join([
            fila("Operaciones", str(st_ops["n"])), fila("Ganadoras / perdedoras", f'{st_ops["wins"]} / {st_ops["losses"]}'),
            fila("Rentabilidad media por operación", pct(st_ops["mean"]), "sube" if st_ops["mean"] >= 0 else "baja"),
            fila("Ganancia media / máxima", f'{pct(st_ops["avg_win"])} / {pct(st_ops["max_win"])}', "sube"),
            fila("Pérdida media / máxima", f'{pct(st_ops["avg_loss"])} / {pct(st_ops["max_loss"])}', "baja"),
            fila("Profit factor", piezas.num(st_ops["profit_factor"]) if st_ops["profit_factor"] is not None else "–")]) + "</ul>"
    csb = ((a or {}).get("g1") or {}).get("costes_sobre_bruto")
    costes = ""
    if csb is not None:
        b, pop = piezas.ayuda("h-costes", "Los costes", "Cada operación paga comisión, el diferencial entre precio de compra y de "
                              "venta y el deslizamiento al ejecutar. En estrategias que operan poco y buscan movimientos grandes "
                              "apenas pesan; en las de muchas operaciones pequeñas se lo comen casi todo.", "Costes sobre el beneficio")
        costes = (f'<div class="costes-linea"><div class="cab"><span>Los costes se comen el {piezas.num(min(csb, 9.99) * 100, 0)} % de lo que '
                  f'gana antes de costes</span>{b}</div>{pop}{piezas.barra_uno(min(csb, 1.0) * 2, 2.0)}</div>')
    return ('<section><div class="cab"><h2>Operaciones del backtest</h2></div><p class="suave peq">En % del capital inicial.</p>'
            + filas + costes + "</section>")


def _detalle_estrategia(i, combo, res, view, velas, a, error_analisis):
    m = res.get("metricas") or {}
    series, pnl_pct, st = view if view else (None, None, None)
    verdict = res.get("veredicto")
    puntos = mnota.nota(m, st) if verdict in ("pasa", "dudosa") else None
    specs = []
    if series:
        specs.append({"id": f"g-curva-{i}", "series": [{"tipo": "area", "color": "acento",
                                                        "datos": [{"time": t, "value": v} for t, v in series]}]})
        curva = f'<div class="grafico" id="g-curva-{i}"></div>'
    else:
        curva = '<p class="vacio">No se pudo recalcular la curva: faltan los precios.</p>'
    if velas and velas[0]:
        specs.append({"id": f"g-velas-{i}", "series": [{"tipo": "velas", "datos": velas[0], "marcas": velas[1]}]})
        velas_html = ('<div class="leyenda"><span><i class="l-sube"></i>Compra / ganancia</span><span><i class="l-baja"></i>'
                      f'Venta / pérdida</span></div><div class="grafico" id="g-velas-{i}"></div>'
                      '<p class="explica">Las últimas 400 velas con sus entradas y salidas.</p>')
    else:
        velas_html = '<p class="vacio">Faltan los precios para dibujar las operaciones.</p>'
    medidor_txt = f"Medidor: de dónde sale el {puntos['nota']}" if puntos else "Medidor"
    por_anio, por_mes = _anio_mes(i, st)
    medidor = ('<div class="zona una"><section id="medidor"><div class="cab"><h2>' + esc(medidor_txt) + '</h2><span class="suave peq">'
               'Media de 8 notas de 0 a 10, por 10. Solo ordena y explica: no aprueba ni suspende.</span></div>'
               + (ficha_html.medidor(puntos) if puntos else '<p class="vacio">Sin nota: solo la tienen las que pasan o casi.</p>')
               + "</section></div>")
    nuevo = _lo_nuevo(i, a, error_analisis, "Hora de Madrid por día de la semana, con costes, todo el backtest.",
                      "{n} operaciones del backtest", len(_RANKING_CACHE.get("filas") or []) or None)
    html = ('<div class="superficie">'
            f'<div class="zona"><section><div class="cab"><h2>Cifras clave</h2></div><div class="kpis8">{_kpis_estrategia(m, st)}</div></section>'
            f'<section class="centro"><span class="suave peq">Nota Quant</span>{ficha_html.gauge(puntos["nota"] if puntos else None)}'
            + ('<a href="#medidor" class="peq">Cómo se calcula</a>' if puntos else "") + "</section></div>"
            + _probado(m, st)
            + '<div class="zona"><section><div class="cab"><h2>Crecimiento de la cuenta</h2>'
            + piezas.selector("g", [("curva", "Curva"), ("velas", "Operaciones en velas")], "curva", etiqueta="Gráfico")
            + f'</div><div data-vista="curva">{curva}</div><div data-vista="velas" hidden>{velas_html}</div></section>'
            + _ops_html(trade_stats(pnl_pct) if pnl_pct is not None else None, a) + "</div>"
            + por_anio + por_mes + medidor
            + f'<div class="zona una"><section><div class="cab"><h2>Los criterios del validador, en palabras</h2></div>'
            f'{ficha_html.criterios(res.get("criterios"))}</section></div>'
            '<div class="separador">Lo nuevo: por qué gana o pierde</div>' + nuevo + "</div>")
    return html, specs


def _cartera_estrategia(res):
    m = res.get("metricas") or {}
    return ('<div class="superficie">'
            f'<div class="zona una"><section><div class="cab"><h2>Cifras clave</h2></div><div class="kpis8">{_kpis_estrategia(m, None)}</div>'
            '<p class="explica">El análisis por operación no existe para carteras de varios activos.</p></section></div>'
            + _probado(m, None)
            + f'<div class="zona una"><section><div class="cab"><h2>Los criterios del validador, en palabras</h2></div>'
            f'{ficha_html.criterios(res.get("criterios"))}</section></div></div>')


def estrategia(con, raiz, query):
    if not _tabla(con, "combinations"):
        return None
    combo = con.execute("SELECT * FROM combinations WHERE id = ?", (int(query["id"]),)).fetchone()
    if not combo:
        return None
    fam = familias.FAMILIES.get(combo["family"])
    ficha_row = con.execute("SELECT json FROM fichas WHERE id = ?", (combo["ficha_id"],)).fetchone()
    ficha = json.loads(ficha_row["json"]) if ficha_row else {}
    results = con.execute("SELECT id, instrumento, veredicto, json FROM resultados WHERE ficha_id = ? ORDER BY id",
                          (combo["ficha_id"],)).fetchall()
    partes, specs = [], []
    for i, r in enumerate(results):
        res = json.loads(r["json"])
        if not res.get("metricas"):
            partes.append(f'<div class="superficie"><div class="zona una"><section><h2>{esc(piezas.nombre(r["instrumento"]))}</h2>'
                          f'<p>{esc(str(res.get("motivo", "")))}</p></section></div></div>')
            continue
        if r["instrumento"] == "_cartera":
            partes.append(_cartera_estrategia(res))
            continue
        view = _equity_cached(raiz, combo["id"], ficha, r["instrumento"])
        velas = _safe(lambda: _velas_estrategia(raiz, combo["id"], ficha, r["instrumento"]), None)
        try:
            a, error = _analisis_resultado(con, raiz, combo["id"], r["id"], ficha, r["instrumento"]), None
        except (datos.ErrorDatos, OSError) as ex:
            a, error = None, _FALTAN_PRECIOS
        except Exception as ex:
            _anotar(raiz, f"análisis de la estrategia {combo['id']}", ex)
            a, error = None, "No se pudo calcular (error interno)."
        html, sp = _detalle_estrategia(i, combo, res, view, velas, a, error)
        partes.append(html)
        specs += sp
    instrumentos = json.loads(combo["instruments_json"])
    nombre = ", ".join(piezas.nombre(x) for x in instrumentos)
    verdict = results[0]["veredicto"] if results else None
    nv, tv = _VERDICTO.get(verdict, (VERDICT_ES.get(verdict, str(verdict)), ""))
    titular = (f'<h1>{esc(nombre)} · {esc(_PLAZO_ES.get(combo["timeframe"], combo["timeframe"]))}</h1>'
               f'<span class="etiqueta {tv}">{esc(nv)}</span>')
    params = json.loads(combo["params_json"])
    chips = "".join(f'<span class="chip">{esc(_PARAM_LARGO.get(k, k))}: <b>{esc(_valor_param(k, v))}</b></span>' for k, v in params.items())
    cabeza = ('<p class="volver"><a href="/ranking" class="peq">Volver al ranking</a></p>'
              '<div class="superficie"><div class="zona una"><section>'
              f'<span class="suave peq">{esc(FAMILIA_ES.get(combo["family"], combo["family"]))}, familia del barrido</span>'
              f'<p>{esc(fam.explanation_es) if fam else ""}</p><div class="chips">{chips}</div></section></div></div>')
    return _layout("ranking", "Estrategia", cabeza + "".join(partes), piezas.graficos(specs), titular=titular, raiz=raiz)


LAB_ES = {"invalido": "Inválido", "no_pasa": "No pasa", "pasa_validador": "Pasa el validador", "ganadora": "Ganadora"}
_LAB_TONO = {"no_pasa": "baja", "pasa_validador": "sube", "ganadora": "sube"}
_ORDEN_LAB = {"pf": "Gana por € perdido", "id": "Más recientes", "ops": "Operaciones"}


def _lab_ready(con):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_experimentos'").fetchone()


def _js(texto):
    return (json.loads(texto) if texto else None) or {}


def _total(entreno_json):
    return (_js(entreno_json).get("metricas") or {}).get("total") or {}


def _decimal(v, defecto):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return defecto


def _propias_filtrar(filas, query):
    q = (query.get("q") or "").strip().lower()
    resultado, noche = query.get("resultado") or "", query.get("noche") or ""
    pf_min = max(0.0, _decimal(query.get("pf"), 0.0))
    ops_min = max(0, _entero(query.get("ops"), 0))
    orden = query.get("orden") if query.get("orden") in _ORDEN_LAB else "pf"

    def pasa(e):
        t = e["_t"]
        if resultado == "invalido" and not e["invalido"]:
            return False
        validos = ("pasa_validador", "ganadora") if resultado == "pasa_validador" else (resultado,)
        if resultado and resultado != "invalido" and (e["invalido"] or e["veredicto"] not in validos):
            return False
        return ((not q or q in (e["motivo"] or "").lower()) and (not noche or e["noche"] == noche)
                and (t.get("profit_factor") or 0) >= pf_min and (t.get("operaciones") or 0) >= ops_min)
    clave = {"pf": lambda e: e["_t"].get("profit_factor") or -1, "id": lambda e: e["id"],
             "ops": lambda e: e["_t"].get("operaciones") or -1}[orden]
    lista = sorted((e for e in filas if pasa(e)), key=clave, reverse=True)
    paginas_n = max(1, -(-len(lista) // POR_PAGINA))
    pagina = _entero(query.get("pagina"), 1, 1, paginas_n)
    return lista[(pagina - 1) * POR_PAGINA: pagina * POR_PAGINA], len(lista)


def _tarjeta_exp(e, mejor_id):
    t, m = e["_t"], _js(e["entreno_json"]).get("metricas") or {}
    pct = lambda v, d=1: f"{piezas.firmar(v * 100, d)} %" if v is not None else "–"
    mt = lambda k, v, c="": f'<div><span>{esc(k)}</span><b class="{c}">{esc(v)}</b></div>'
    res = "invalido" if e["invalido"] else e["veredicto"]
    motivo = (e["motivo"] or "")
    metricas = "".join([
        mt("Anual", pct(t.get("cagr")), "sube" if (t.get("cagr") or 0) >= 0 else "baja"),
        mt("Cambios", str(e["cambios"] if e["cambios"] is not None else "–")),
        mt("Caída máx.", _caida(t.get("drawdown")), "baja"),
        mt("Gana por € perdido", piezas.num(t["profit_factor"]) if t.get("profit_factor") is not None else "–"),
        mt("Rentabilidad total", pct(t.get("rentabilidad")), "sube" if (t.get("rentabilidad") or 0) >= 0 else "baja"),
        mt("Acierto", f'{piezas.num(t["acierto"] * 100, 0)} %' if t.get("acierto") is not None else "–"),
        mt("Sharpe fuera", piezas.num((m.get("fuera") or {})["sharpe"]) if (m.get("fuera") or {}).get("sharpe") is not None else "–"),
        mt("Operaciones", str(t.get("operaciones", "–")))])
    noche = e["noche"] or ""
    return (f'<a class="tarjeta" href="/propias/{int(e["id"])}">{ficha_html.circulo_pf(t.get("profit_factor"))}'
            f'<div><div class="nombre">#{int(e["id"])} <span class="suave peq">{esc(noche[8:10])}/{esc(noche[5:7])}</span> '
            f'<span class="etiqueta {_LAB_TONO.get(res, "")}">{esc(LAB_ES.get(res, str(res)))}</span>'
            + (' <span class="etiqueta aviso">La mejor</span>' if e["id"] == mejor_id else "")
            + f'</div><div class="fam">{esc(motivo[:140])}{"…" if len(motivo) > 140 else ""}</div>'
            + (f'<div class="fam">{esc(e["invalido"])}</div>' if e["invalido"] else "")
            + f'</div><div class="metricas">{metricas}</div>{ficha_html.casillas(_js(e["entreno_json"]).get("criterios"))}</a>')


def _asesor_bloque(con, nombre):
    filas = []
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_asesor'").fetchone():
        filas = con.execute("SELECT * FROM lab_asesor WHERE estrategia=? ORDER BY fecha DESC, id DESC", (nombre,)).fetchall()
    b, pop = piezas.ayuda("h-asesor", "El asesor semanal", "Cada domingo un agente lee todos los experimentos y el mapa, y escribe "
                          "qué debe probar el laboratorio la semana siguiente. No ve el examen.", "Asesor")
    if not filas:
        return f'<section><div class="cab"><h2>Lo que pide el asesor esta semana</h2>{b}</div>{pop}<p class="vacio">El asesor aún no ha escrito ningún informe.</p></section>'
    u = filas[0]
    puntos = "".join(f"<li>{esc(x)}</li>" for x in (u["direccion_es"] or "").splitlines() if x.strip())
    propuestas = "".join(f"<li><b>{esc(x.get('que', ''))}</b>: {esc(x.get('motivo', ''))}</li>"
                         for x in (_js(u["propuestas_json"]) if isinstance(_js(u["propuestas_json"]), list) else []) if isinstance(x, dict))
    anteriores = "".join(f'<details><summary>Informe del {esc(f["fecha"])}</summary><div class="informe">{esc(f["informe"] or "")}</div></details>'
                         for f in filas[1:])
    return (f'<section><div class="cab"><h2>Lo que pide el asesor esta semana</h2><span class="etiqueta">{esc(u["fecha"])}</span>{b}</div>{pop}'
            f'<ol class="lista-num">{puntos}</ol>'
            + (f'<h3>Propuestas que esperan tu decisión</h3><ul class="lista-num">{propuestas}</ul>' if propuestas else "")
            + f'<details><summary>Informe completo</summary><div class="informe">{esc(u["informe"] or "")}</div></details>{anteriores}</section>')


def propias_page(con, raiz, query):
    titular_base = ('<h1>Ranking</h1><div class="selector" role="group" aria-label="Qué estrategias ver">'
                    '<a href="/ranking">Barrido</a><a href="/propias" aria-current="page">Propias</a></div>')
    if not _lab_ready(con):
        return _layout("ranking", "Propias", '<div class="superficie"><div class="zona una"><section><h2>Estrategias propias</h2>'
                       '<p class="vacio">El laboratorio aún no ha corrido.</p></section></div></div>', titular=titular_base, raiz=raiz)
    nombre = query.get("estrategia") if query.get("estrategia") in propias.PROPIAS else "manual"
    selector_e = ('<div class="selector" role="group" aria-label="Estrategia">' + "".join(
        f'<a href="/propias?estrategia={k}"{" aria-current=" + chr(34) + "page" + chr(34) if k == nombre else ""}>{esc(_PROPIAS_ES.get(k, k))}</a>'
        for k in sorted(propias.PROPIAS, key=lambda k: k != "manual")) + "</div>")
    filas = [dict(e) | {"_t": _total(e["entreno_json"])} for e in
             con.execute("SELECT * FROM lab_experimentos WHERE estrategia=? ORDER BY id", (nombre,)).fetchall()]
    prog = _safe(lambda: hoy_datos.progreso_propia(con, nombre), None) or {}
    mejor_id = prog.get("mejor_id")
    validador = sum(1 for e in filas if not e["invalido"] and e["veredicto"] in ("pasa_validador", "ganadora"))
    ganadoras = _safe(lambda: con.execute("SELECT * FROM lab_ganadoras WHERE estrategia=? ORDER BY id DESC", (nombre,)).fetchall(), [])
    b1, p1 = piezas.ayuda("h-mejor", "La mejor variante", "De las variantes que ha probado el laboratorio con al menos 200 "
                          "operaciones, la que más gana por cada euro que pierde. Es un resultado de entrenamiento: para llegar a "
                          "ganadora tiene que pasar el validador y después el examen con años que nunca ha visto.", "Variante")
    pf = prog.get("pf")
    cifras = ('<div class="cifras">'
              + piezas.cifra(f"Mejor variante (#{mejor_id})" if mejor_id else "Mejor variante", piezas.num(pf) if pf is not None else "–",
                             f"Gana {piezas.num(pf)} € por cada euro que pierde" if pf is not None else "Aún ninguna con 200 operaciones",
                             "sube" if (pf or 0) >= 1 else "baja", (b1, p1), grande=True)
              + piezas.cifra("Variantes probadas", piezas.num(len(filas), 0), "por el laboratorio")
              + piezas.cifra("Pasan el validador", piezas.num(validador, 0), "cumplen los 9 criterios", "sube" if validador else "suave")
              + piezas.cifra("En examen o demo", piezas.num(len(ganadoras), 0), "ninguna todavía" if not ganadoras else "pasaron el examen",
                             "" if ganadoras else "suave") + "</div>")
    b3, p3 = piezas.ayuda("h-camino", "El camino de una variante", "Cada idea se prueba con datos de entrenamiento. Si cumple los "
                          "criterios pasa el validador; si además aguanta el examen con años no vistos, llega a ganadora y puede ir a la demo.")
    caja = lambda n, v, nota="": f'<div><span class="suave peq">{esc(n)}</span><b>{esc(v)}</b>{nota}</div>'
    embudo = ('<div class="embudo">' + caja("Probadas", piezas.num(len(filas), 0)) + caja("Pasan el validador", piezas.num(validador, 0))
              + caja("Pasan el examen", piezas.num(len(ganadoras), 0))
              + caja("En la demo", "–", '<span class="suave peq">Aún no se puede saber desde el catálogo</span>') + "</div>")
    lista_g = "".join(
        f'<li><a href="/propias/{int(g["experimento_id"])}">#{int(g["experimento_id"])}</a> '
        + ("vigente" if g["estado"] == "vigente" else esc(f"Retirada ({g['retirada'] or ''}): {g['motivo_retiro'] or ''}")) + "</li>"
        for g in ganadoras)
    specs = []
    evo = prog.get("evolucion") or []
    if evo:
        specs.append({"id": "g-evo", "series": [{"tipo": "linea", "color": "sube", "ancho": 2,
                                                 "datos": [{"time": n, "value": v} for n, v in evo]}],
                      "lineas": [{"valor": 1, "color": "tinta-suave"}]})
        evo_html = '<div class="grafico bajo" id="g-evo"></div>'
    else:
        evo_html = '<p class="vacio">Aún no hay experimentos.</p>'
    camino = (f'<section><div class="cab"><h2>El camino de cada variante</h2>{b3}</div>{p3}{embudo}'
              + (f'<ul class="filas ganadoras">{lista_g}</ul>' if lista_g else "")
              + f'<div class="cab sep"><h2>Cómo ha mejorado noche a noche</h2></div>{evo_html}</section>')
    noches = sorted({e["noche"] for e in filas if e["noche"]}, reverse=True)
    lista, total = _propias_filtrar(filas, query)
    orden = query.get("orden") if query.get("orden") in _ORDEN_LAB else "pf"
    pf_txt = query.get("pf") or ""
    form = ('<form class="filtros" method="get" action="/propias" role="search" aria-label="Filtrar experimentos">'
            f'<input type="hidden" name="estrategia" value="{esc(nombre)}">'
            f'<label>Buscar<input type="search" name="q" value="{esc(query.get("q") or "")}" placeholder="RSI, stop, objetivo..."></label>'
            + _opciones("resultado", "Resultado", [("pasa_validador", "Pasa el validador"), ("no_pasa", "No pasa"), ("invalido", "Inválido")],
                        query.get("resultado") or "")
            + _opciones("noche", "Noche", [(n, f"{n[8:10]}/{n[5:7]}") for n in noches], query.get("noche") or "")
            + f'<label>Gana por € perdido, mínimo<input type="number" name="pf" step="0.1" min="0" value="{esc(pf_txt)}"></label>'
            + f'<label>Operaciones, mínimo<input type="number" name="ops" step="50" min="0" value="{esc(query.get("ops") or "")}"></label>'
            + '<label>Ordenar por<select name="orden">' + "".join(
                f'<option value="{k}"{" selected" if k == orden else ""}>{esc(v)}</option>' for k, v in _ORDEN_LAB.items())
            + f'</select></label><button type="submit">Filtrar</button><a class="limpiar" href="/propias?estrategia={esc(nombre)}">Quitar filtros</a>'
            f'<span class="cuenta">{piezas.num(total, 0)} de {piezas.num(len(filas), 0)} experimentos</span></form>')
    b6, p6 = piezas.ayuda("h-tarjetas", "Las tarjetas de experimentos", "El círculo es lo que gana por cada euro que pierde, con el "
                          "color de su franja. Las casillas de la derecha son los 9 criterios del validador: verde si lo cumple, rojo si "
                          "no. Pulsa una tarjeta para ver su ficha completa. Todo es de entrenamiento, hasta finales de 2022.")
    leyenda = ('<span class="franjas"><span>Gana por € perdido:</span><span class="nota nota-4">1,3+</span><span class="nota nota-3">1,0</span>'
               '<span class="nota nota-2">0,9</span><span class="nota nota-1">&lt;0,9</span></span>')
    paginas_n = max(1, -(-total // POR_PAGINA))
    pagina = _entero(query.get("pagina"), 1, 1, paginas_n)
    from urllib.parse import urlencode
    enlace = lambda p: "/propias?" + urlencode({"estrategia": nombre, **{k: v for k, v in query.items() if k in (
        "q", "resultado", "noche", "pf", "ops", "orden") and v}, "pagina": p})
    nav = ('<nav class="paginas" aria-label="Páginas">'
           + (f'<a href="{esc(enlace(pagina - 1))}">Anteriores</a>' if pagina > 1 else "<span></span>")
           + f'<span class="suave peq">Página {pagina} de {paginas_n}</span>'
           + (f'<a href="{esc(enlace(pagina + 1))}">Siguientes</a>' if pagina < paginas_n else "<span></span>") + "</nav>")
    tarjetas = "".join(_tarjeta_exp(e, mejor_id) for e in lista) or '<p class="vacio">Ningún experimento cumple estos filtros.</p>'
    body = ('<div class="superficie">' + cifras + f'<div class="zona mitades">{camino}{_asesor_bloque(con, nombre)}</div>' + form
            + f'<div class="zona una"><section><div class="cab"><h2>Experimentos</h2>{leyenda}{b6}</div>{p6}'
            f'<div class="tarjetas">{tarjetas}</div>{nav}</section></div></div>')
    script = ("<script>document.querySelector('form.filtros').addEventListener('change', function (e) {"
              " if (e.target.name !== 'q') e.currentTarget.requestSubmit(); });</script>")
    return _layout("ranking", "Propias", body, piezas.graficos(specs) + script, titular=titular_base + selector_e, raiz=raiz)


def _anio_mes(i, st, nota=""):
    if not st:
        return "", ""
    b_a, pop_a = piezas.ayuda(f"h-anual-{i}", "Rentabilidad por año", "Cada barra es un año del backtest: verde si ganó, roja si "
                              "perdió. Sirve para ver si gana de forma regular o si todo lo ganó en uno o dos años buenos.")
    sub = f'{st["anios_positivos"]} de {st["n_anios"]} años en positivo' + (f", {nota}" if nota else "")
    por_anio = (f'<div class="zona una"><section><div class="cab"><h2>Rentabilidad por año</h2><span class="suave peq">'
                f'{esc(sub)}</span>{b_a}</div>{pop_a}{ficha_html.anual(st.get("anual"))}</section></div>')
    por_mes = ('<div class="zona una"><section><div class="cab"><h2>Rentabilidad por mes</h2>'
               + piezas.selector("g", [("m3", "Últimos 3 años"), ("mtodos", "Todos")], "m3", etiqueta="Años")
               + f'</div><div data-vista="m3">{ficha_html.meses(st.get("meses"), st.get("anual") or {}, 3)}</div>'
               f'<div data-vista="mtodos" hidden>{ficha_html.meses(st.get("meses"), st.get("anual") or {})}</div>'
               f'<p class="explica">En % de la cuenta. Un punto es un mes sin posición abierta.{esc(" " + nota.capitalize() + "." if nota else "")}</p></section></div>')
    return por_anio, por_mes


def _lo_nuevo(i, a, error, nota_mapa, sub_grupos, probadas):
    if a:
        b_m, pop_m = piezas.ayuda(f"h-mapa-{i}", "Dónde gana y dónde pierde", "Cada casilla es una hora de un día de la semana. Verde: "
                                  "ahí gana más de lo que pierde; rojo: al revés. El número es lo que gana por cada euro perdido. Si solo "
                                  "hay casillas verdes sueltas, no hay una franja buena: el problema es otro.", "Mapa de días y horas")
        return (f'<div class="zona una"><section><div class="cab"><h2>Dónde gana y dónde pierde</h2>{b_m}</div>{pop_m}'
                + ficha_html.rejilla(a["rejilla"], nota_mapa) + "</section></div>"
                '<div class="zona una"><section class="sin-pie"><div class="cab"><h2>Por qué gana o pierde</h2>'
                f'<span class="suave peq">{esc(sub_grupos.format(n=a["n"]))}</span></div></section></div>' + ficha_html.seis_grupos(a, probadas))
    motivo = error or "No tiene operaciones cerradas suficientes para este análisis."
    return ('<div class="zona una"><section><div class="cab"><h2>Dónde gana y dónde pierde</h2></div>'
            f'<p class="vacio">{esc(motivo)}</p></section></div><div class="zona una"><section><div class="cab"><h2>'
            f'Por qué gana o pierde</h2></div><p class="vacio">{esc(motivo)}</p></section></div>')


_PROPIAS_URL = "/propias?estrategia="


def _vista_lab(raiz, e, ficha, inst, corte):
    clave = ("lab", str(raiz), e["id"])
    if clave not in _EQUITY_CACHE:
        if len(_EQUITY_CACHE) >= 200:
            _EQUITY_CACHE.clear()
        res, capital = ficha_stats.ejecutar(raiz, ficha, inst, hasta=corte)
        ts = res.ts.astype("datetime64[s]").astype("int64").tolist()
        pnl_pct = np.array([o.pnl for o in res.operaciones], float) / capital
        st = ficha_stats.estadisticas(res.ts, res.equity, res.operaciones, capital) if len(res.ts) > 1 else None
        _EQUITY_CACHE[clave] = (_sample([[t, round(float(v), 2)] for t, v in zip(ts, res.equity)]), pnl_pct, st)
    return _EQUITY_CACHE[clave]


def _analisis_lab(con, raiz, e, ficha, inst, corte):
    fila = _safe(lambda: con.execute("SELECT json FROM panel_analisis WHERE clave = ?", (f"e:{e['id']}",)).fetchone(), None)
    if fila is not None:
        return json.loads(fila[0])
    clave = (str(raiz), f"e:{e['id']}")
    if clave not in _ANALISIS_CACHE:
        if len(_ANALISIS_CACHE) >= 200:
            _ANALISIS_CACHE.clear()
        hermanas = con.execute("SELECT id, ficha_json, entreno_json FROM lab_experimentos WHERE estrategia = ?", (e["estrategia"],)).fetchall()
        _ANALISIS_CACHE[clave] = precalcular.analisis_de(raiz, ficha, inst, precalcular.vecinos_lab(hermanas, ficha, e["id"]), hasta=corte)
    return _ANALISIS_CACHE[clave]


def _kpis_lab(m):
    t, f = m.get("total") or {}, m.get("fuera") or {}
    pct = lambda v, d=1: f"{piezas.firmar(v * 100, d)} %" if v is not None else "–"
    tono = lambda v: "sube" if (v or 0) >= 0 else "baja"
    num = lambda v: piezas.num(v) if v is not None else "–"
    acierto = f'acierta el {piezas.num(t["acierto"] * 100, 0)} %' if t.get("acierto") is not None else ""
    return "".join([_kpi8("Rentabilidad total", pct(t.get("rentabilidad")), "en el entrenamiento", tono(t.get("rentabilidad"))),
                    _kpi8("Rentabilidad anual", pct(t.get("cagr")), "media compuesta por año", tono(t.get("cagr"))),
                    _kpi8("Caída máxima", _caida(t.get("drawdown")), "peor caída desde un máximo", "baja"),
                    _kpi8("Operaciones", str(t.get("operaciones", "–")), acierto),
                    _kpi8("Sharpe total", num(t.get("sharpe")), "rentabilidad frente al riesgo"),
                    _kpi8("Sharpe fuera de muestra", num(f.get("sharpe")), "en la parte que no vio"),
                    _kpi8("Con costes al doble", pct(m.get("rentabilidad_costes_x2")), "rentabilidad total"),
                    _kpi8("Montecarlo", _pc(m.get("montecarlo_dd_p95"), 1), "caída del 5 % peor")])


def _comparacion(con, e):
    original = con.execute("SELECT id, entreno_json FROM lab_experimentos WHERE estrategia = ? AND cambios = 0 ORDER BY id LIMIT 1",
                           (e["estrategia"],)).fetchone()
    mejor_id = (_safe(lambda: hoy_datos.progreso_propia(con, e["estrategia"]), None) or {}).get("mejor_id")
    mejor = con.execute("SELECT id, entreno_json FROM lab_experimentos WHERE id = ?", (mejor_id,)).fetchone() if mejor_id else None
    columnas = [("Esta variante", e)]
    if original is not None and original["id"] != e["id"]:
        columnas.append((f"Tu original (#{original['id']})", original))
    if mejor is not None and mejor["id"] != e["id"]:
        columnas.append((f"La mejor (#{mejor['id']})", mejor))
    if len(columnas) == 1:
        return ""
    met = [(c, _js(x["entreno_json"]).get("metricas") or {}) for c, x in columnas]
    filas = [("Gana por € perdido", lambda m: piezas.num(m["total"]["profit_factor"]) if (m.get("total") or {}).get("profit_factor") is not None else "–"),
             ("Rentabilidad anual", lambda m: _pc((m.get("total") or {}).get("cagr"), 1, True)),
             ("Caída máxima", lambda m: _caida((m.get("total") or {}).get("drawdown"))),
             ("Operaciones", lambda m: str((m.get("total") or {}).get("operaciones", "–"))),
             ("Sharpe fuera", lambda m: piezas.num(m["fuera"]["sharpe"]) if (m.get("fuera") or {}).get("sharpe") is not None else "–")]
    cab = "".join(f"<th>{esc(c)}</th>" for c, _ in met)
    cuerpo = "".join(f'<tr><td>{esc(n)}</td>{"".join(f"<td>{esc(f(m))}</td>" for _, m in met)}</tr>' for n, f in filas)
    return (f'<div class="zona una"><section><div class="cab"><h2>Comparado con tu original y con la mejor</h2>'
            f'<span class="suave peq">solo entrenamiento</span></div><div class="scroll"><table class="num"><thead><tr><th></th>{cab}</tr></thead>'
            f'<tbody>{cuerpo}</tbody></table></div></section></div>')


def _examen_html(e):
    if e["invalido"] or e["veredicto"] not in ("pasa_validador", "ganadora") or not e["examen_json"]:
        return ""
    t = _total(e["entreno_json"])
    cols = [("Entrenamiento", t), ("Examen", _js(e["examen_json"])), ("Confirmación", _js(e["confirmacion_json"]))]
    filas = [("Gana por € perdido", lambda m: piezas.num(m["profit_factor"]) if m.get("profit_factor") is not None else "–"),
             ("Rentabilidad", lambda m: _pc(m.get("rentabilidad"), 1, True)), ("Caída", lambda m: _caida(m.get("drawdown"))),
             ("Operaciones", lambda m: str(m.get("operaciones", "–")))]
    cab = "".join(f"<th>{esc(c)}</th>" for c, _ in cols)
    cuerpo = "".join(f'<tr><td>{esc(n)}</td>{"".join(f"<td>{esc(f(m))}</td>" for _, m in cols)}</tr>' for n, f in filas)
    return ('<div class="zona una"><section><div class="cab"><h2>Entrenamiento, examen y confirmación</h2>'
            '<span class="suave peq">el examen son años que el laboratorio nunca vio</span></div>'
            f'<div class="scroll"><table class="num"><thead><tr><th></th>{cab}</tr></thead><tbody>{cuerpo}</tbody></table></div></section></div>')


def _hasta_txt(corte):
    if not corte:
        return "solo entrenamiento"
    if corte[5:] == "01-01":
        return f"solo entrenamiento, hasta finales de {int(corte[:4]) - 1}"
    return f"solo entrenamiento, hasta el {corte}"


def experimento(con, raiz, query):
    if not _lab_ready(con):
        return None
    e = con.execute("SELECT * FROM lab_experimentos WHERE id = ?", (int(query["id"]),)).fetchone()
    if not e:
        return None
    from quant.investigacion import laboratorio
    propia = propias.PROPIAS.get(e["estrategia"])
    nombre = _PROPIAS_ES.get(e["estrategia"], e["estrategia"])
    corte = propia.corte if propia else None
    hasta_txt = _hasta_txt(corte)
    ficha = _js(e["ficha_json"])
    res = _js(e["entreno_json"])
    m = res.get("metricas") or {}
    t = m.get("total") or {}
    mejor_id = (_safe(lambda: hoy_datos.progreso_propia(con, e["estrategia"]), None) or {}).get("mejor_id")
    clave_res = "invalido" if e["invalido"] else e["veredicto"]
    noche = e["noche"] or ""
    titular = (f'<h1>Experimento #{int(e["id"])}</h1><span class="etiqueta {_LAB_TONO.get(clave_res, "")}">'
               f'{esc(LAB_ES.get(clave_res, str(clave_res)))}</span>'
               + ('<span class="etiqueta aviso">La mejor variante</span>' if e["id"] == mejor_id else "")
               + f'<span class="suave">{esc(nombre)}, noche del {esc(noche[8:10])}/{esc(noche[5:7])}</span>')
    cambios = _safe(lambda: laboratorio._cambios_vistos(propias.ficha_base(e["estrategia"]), ficha), []) if propia else []
    cambios_html = ('<details><summary>Ver el detalle de los cambios</summary><ul class="filas">'
                    + "".join(f'<li><span class="que mono peq">{esc(c)}</span></li>' for c in cambios) + "</ul></details>"
                    if cambios else '<p class="suave">Es tu estrategia original, sin cambios.</p>')
    cabeza = (f'<p class="volver"><a href="{_PROPIAS_URL}{esc(e["estrategia"])}" class="peq">Volver a Propias</a></p>'
              '<div class="superficie"><div class="zona una"><section>'
              f'<span class="suave peq">{esc(nombre)}: variante con {esc(str(e["cambios"] if e["cambios"] is not None else "–"))} '
              f'cambio(s) respecto a tu original</span><p>{esc(e["motivo"] or "")}</p>'
              + (f'<p class="aviso">{esc(e["invalido"])}</p>' if e["invalido"] else "") + cambios_html + "</section></div>")
    if propia is None:
        body = cabeza + ('<div class="zona una"><section><p class="vacio">Esta estrategia ya no está entre tus estrategias propias: '
                         'sin saber dónde empieza su examen, no se recalcula nada.</p></section></div>'
                         '<div class="zona una"><section><div class="cab"><h2>Los criterios del validador, en palabras</h2></div>'
                         + ficha_html.criterios(res.get("criterios")) + "</section></div></div>")
        return _layout("ranking", "Experimento", body, titular=titular, raiz=raiz)
    if not e["entreno_json"]:
        body = cabeza + ('<div class="zona una"><section><div class="cab"><h2>Los criterios del validador, en palabras</h2></div>'
                         + ficha_html.criterios(None) + "</section></div></div>")
        return _layout("ranking", "Experimento", body, titular=titular, raiz=raiz)
    inst = (ficha.get("universo") or {}).get("instrumentos", [propia.instrument if propia else None])[0]
    view = _safe(lambda: _vista_lab(raiz, e, ficha, inst, corte), None)
    series, pnl_pct, st = view if view else (None, None, None)
    puntos = _safe(lambda: mnota.nota(m, st), None) if st else None
    velas = _safe(lambda: _velas_estrategia(raiz, f"lab{e['id']}", ficha, inst, corte), None)
    try:
        a, error = _analisis_lab(con, raiz, e, ficha, inst, corte), None
    except (datos.ErrorDatos, OSError):
        a, error = None, _FALTAN_PRECIOS
    except Exception as ex:
        _anotar(raiz, f"análisis del experimento {e['id']}", ex)
        a, error = None, "No se pudo calcular (error interno)."
    specs = []
    if series:
        specs.append({"id": "g-curva-0", "series": [{"tipo": "area", "color": "acento", "datos": [{"time": x, "value": v} for x, v in series]}]})
        curva = f'<div class="grafico" id="g-curva-0"></div><p class="explica">Crecimiento de la cuenta, {esc(hasta_txt)}.</p>'
    else:
        curva = f'<p class="vacio">{_FALTAN_PRECIOS}</p>'
    if velas and velas[0]:
        specs.append({"id": "g-velas-0", "series": [{"tipo": "velas", "datos": velas[0], "marcas": velas[1]}]})
        velas_html = ('<div class="leyenda"><span><i class="l-sube"></i>Compra / ganancia</span><span><i class="l-baja"></i>Venta / pérdida'
                      '</span></div><div class="grafico" id="g-velas-0"></div>'
                      f'<p class="explica">Las últimas 400 velas antes del corte con sus entradas y salidas, {esc(hasta_txt)}.</p>')
    else:
        velas_html = '<p class="vacio">Faltan los precios para dibujar las operaciones.</p>'
    por_anio, por_mes = _anio_mes(0, st, hasta_txt)
    b_p, pop_p = piezas.ayuda("h-probado", "Dentro y fuera de muestra", "Con una parte del entrenamiento se mide la variante y con otra "
                              "se comprueba. Si fuera rinde mucho peor que dentro, lo más probable es que esté ajustada a la casualidad.",
                              "Dentro y fuera de muestra")
    d, f = m.get("dentro") or {}, m.get("fuera") or {}
    sh = lambda x: piezas.num(x["sharpe"]) if x.get("sharpe") is not None else "–"
    probado = ('<div class="zona una"><section><div class="cab"><h2>Cómo se ha probado</h2>' + b_p + "</div>" + pop_p
               + '<p>El periodo de entrenamiento se parte en dos: el 70 % primero sirve para medir y el 30 % final para comprobar sin '
               'haberlo visto. El examen con los años más recientes no aparece: el laboratorio no lo ve.</p>'
               f'<div class="split"><div class="in">Medición: {esc(str(d.get("operaciones", "–")))} operaciones, Sharpe {sh(d)}</div>'
               f'<div class="out">Fuera de muestra: {esc(str(f.get("operaciones", "–")))} operaciones, Sharpe {sh(f)}</div></div>'
               f'<div class="chips"><span class="chip">Costes al doble: {_pc(m.get("rentabilidad_costes_x2"), 0, True)}</span>'
               f'<span class="chip">Variantes que ganan: {_pc(m.get("robustez"), 0)} de {esc(str(m.get("variantes", "–")))}</span>'
               f'<span class="chip">Montecarlo, caída del 5 % peor: {_pc(m.get("montecarlo_dd_p95"), 1)}</span></div></section></div>')
    medidor = ('<div class="zona una"><section id="medidor"><div class="cab"><h2>'
               + esc(f"Medidor: de dónde sale el {puntos['nota']}" if puntos else "Medidor")
               + f'</h2><span class="suave peq">Media de 8 notas de 0 a 10, por 10, {esc(hasta_txt)}. Solo ordena y explica.</span></div>'
               + (ficha_html.medidor(puntos) if puntos else f'<p class="vacio">{_FALTAN_PRECIOS}</p>') + "</section></div>")
    probadas = con.execute("SELECT COUNT(*) FROM lab_experimentos WHERE estrategia = ?", (e["estrategia"],)).fetchone()[0]
    body = (cabeza
            + f'<div class="zona"><section><div class="cab"><h2>Cifras clave</h2><span class="suave peq">{esc(hasta_txt)}, con costes</span></div>'
            f'<div class="kpis8">{_kpis_lab(m)}</div></section>'
            f'<section class="centro"><span class="suave peq">Gana por cada euro que pierde</span>{ficha_html.gauge_pf(t.get("profit_factor"))}</section></div>'
            + _comparacion(con, e) + probado + _examen_html(e)
            + '<div class="zona"><section><div class="cab"><h2>Crecimiento de la cuenta</h2>'
            + piezas.selector("g", [("curva", "Curva"), ("velas", "Operaciones en velas")], "curva", etiqueta="Gráfico")
            + f'</div><div data-vista="curva">{curva}</div><div data-vista="velas" hidden>{velas_html}</div></section>'
            + _ops_html(trade_stats(pnl_pct) if pnl_pct is not None else None, a) + "</div>"
            + por_anio + por_mes + medidor
            + f'<div class="zona una"><section><div class="cab"><h2>Los criterios del validador, en palabras</h2></div>'
            f'{ficha_html.criterios(res.get("criterios"))}</section></div>'
            '<div class="separador">Lo nuevo: por qué gana o pierde</div>'
            + _lo_nuevo(0, a, error, f"Esta variante, hora de Madrid, con costes, {hasta_txt}.", "{n} operaciones de entrenamiento", probadas)
            + "</div>")
    return _layout("ranking", "Experimento", body, piezas.graficos(specs), titular=titular, raiz=raiz)


_ERRORES_ES = (("quant-lector", "El lector no respondía",
                "Era el modelo local de Ollama, que ya no se usa: los agentes van ahora por Claude."),
               ("invalid", "Respuestas de agentes mal formadas",
                "Extractos o fichas que no cuadraban con el formato aunque el agente lo reintentara. El documento se descarta y se apunta."),
               ("sin JSON", "Respuestas de agentes sin formato",
                "El agente no devolvió los datos en el formato pedido. Normal en pequeñas cantidades."),
               ("500 Server", "Fallo del servidor del modelo", "El servicio de IA devolvió un error interno; se reintenta la noche siguiente."))
_MESES_CORTOS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def _fecha_corta(f):
    return f"{int(f[6:8])}-{_MESES_CORTOS[int(f[4:6]) - 1]}" if len(f) == 8 and f.isdigit() else f


def _celda_noche(e):
    if e is None:
        return "x", "no existía o no tocaba"
    if e.get("fallo"):
        return "r", f"falló: {e['fallo']}"
    if e.get("omitido"):
        return "a", f"omitida: {e['omitido']}"
    if e.get("errores_contenido"):
        return "a", f"{e['errores_contenido']} errores de contenido"
    return "v", f"bien · {_duracion(e.get('s'))}"


def _sistema_html(r):
    noches = list(reversed(r["noches"]))
    cab = "".join(f'<th scope="col">{esc(_fecha_corta(n["fecha"]))}</th>' for n in noches)
    filas = []
    for etapa in contratos.ETAPAS:
        celdas = []
        for n in noches:
            c, t = _celda_noche(n["etapas"].get(etapa))
            celdas.append(f'<td><span class="dot-{c}" title="{esc(t)}" role="img" aria-label="{esc(t)}"></span></td>')
        filas.append(f'<tr><th scope="row">{esc(_ETAPA_ES.get(etapa, etapa))}</th>{"".join(celdas)}</tr>')
    rev = {"ok": "v", "aviso": "a", "parada": "r", None: "x"}
    filas.append('<tr><th scope="row">Revisión de la mañana</th>' + "".join(
        f'<td><span class="dot-{rev.get(n["revision"], "a")}" title="{esc(str(n["revision"] or "sin revisión"))}" role="img" '
        f'aria-label="{esc(str(n["revision"] or "sin revisión"))}"></span></td>' for n in noches) + "</tr>")
    rejilla = (f'<section class=card><h2>Últimas noches</h2><div class="scroll"><table class="grid-noches"><thead><tr>'
               f'<th scope="col">Etapa</th>{cab}</tr></thead><tbody>{"".join(filas)}</tbody></table></div>'
               '<p class="muted small leyenda"><span class="dot-v"></span> Bien <span class="dot-a"></span> Con avisos '
               '<span class="dot-r"></span> Falló <span class="dot-x"></span> No existía o no tocaba · pasa el ratón por un punto para ver el detalle</p></section>')
    errores = []
    fallos_precios = sum(1 for n in r["noches"] if (n["etapas"].get("precios") or {}).get("fallo"))
    if fallos_precios:
        errores.append((str(fallos_precios), "Precios marcado como fallo",
                        f"En {fallos_precios} de las últimas noches algún valor trajo datos raros y la etapa se dio por fallida.", "neg"))
    for texto, n in r.get("errores_frecuentes") or []:
        titulo, explica = next(((t, x) for clave, t, x in _ERRORES_ES if clave in texto), ("Error de un documento", texto))
        errores.append((str(n), titulo, explica, "mid"))
    errores_html = "".join(f'<li><span class="pill {t}">{esc(n)}</span><span><strong>{esc(ti)}</strong>'
                           f'<span class="small">{esc(x)}</span></span></li>' for n, ti, x, t in errores) or \
        "<li><span>Sin errores en las últimas noches.</span></li>"
    return (rejilla + f'<section class="card"><h2>Qué falló y por qué</h2><ul class="errores">{errores_html}</ul></section>')


_ETAPA_LARGA = {"precios": "Precios", "investigar": "Investigar", "canario": "Comprobar agentes", "demo": "Demo",
                "laboratorio": "Laboratorio", "relator": "Informe", "mentor": "Mentor", "copia": "Copia de seguridad"}
_TAREA_ES = {"Quant_Noche": "Noche", "Quant_Demo": "Demo", "Quant_Revision": "Revisión y correo", "Quant_Vigilante": "Vigilante",
             "Quant_Barrido": "Barrido", "Quant_Asesor": "Asesor", "Quant_Panel": "Panel"}
_AYUDA_TAREAS = ("Tareas programadas", "Programas que Windows lanza solo a su hora: la noche, la demo cada hora, la revisión de "
                 "la mañana, el barrido de los sábados y el asesor de los domingos. «Bien» quiere decir que la última vez "
                 "terminó sin errores.")


def _dia_hora(texto):
    t = _safe(lambda: datetime.fromisoformat(str(texto)), None)
    return f"{t.day} {_MESES_C[t.month - 1]}, {t:%H:%M}" if t else "–"


def _fecha_parte(f):
    return f"{f[6:8]}/{f[4:6]}" if len(str(f)) == 8 else str(f or "–")


def _pruebas(raiz):
    p = _safe(lambda: json.loads((raiz / "registro" / "pruebas.json").read_text(encoding="utf-8")), None)
    return p if isinstance(p, dict) else None


def _sistema_bloque(r, parte, pruebas, ahora):
    etapas = (parte or {}).get("etapas") or {}
    malas = [_ETAPA_LARGA.get(n, n) for n in contratos.ETAPAS
             if n != "precios" and contratos.hay_fallo((etapas.get(n) or {}).get("resultado"))]
    noche = piezas.cifra("Última noche", _fecha_parte(parte.get("fecha")) if parte else "–",
                         ("Fallaron: " + ", ".join(malas) if malas else "todas las etapas terminaron") if parte
                         else "Aún no hay ningún parte de la noche.", "baja" if malas else "", grande=True)
    tareas = (r or {}).get("tareas") or {}
    demo = tareas.get("Quant_Demo") if isinstance(tareas.get("Quant_Demo"), dict) else {}
    precios = piezas.cifra("Precios de la demo", _dia_hora(demo.get("ultima")) if demo.get("ultima") else "–", "revisa cada hora")
    if pruebas:
        fallan = pruebas.get("fallan") or 0
        fecha = _safe(lambda: datetime.fromisoformat(pruebas["fecha"]).strftime("%d/%m/%Y %H:%M"), str(pruebas.get("fecha", "")))
        prueba = piezas.cifra("Pruebas del programa", f'{pruebas.get("pasan", 0)} de {pruebas.get("total", 0)}',
                              (f"pasan; {fallan} fallan · " if fallan else "pasan · ") + fecha, "baja" if fallan else "sube")
    else:
        prueba = piezas.cifra("Pruebas del programa", "–", "Aún no se han ejecutado todas las pruebas.")
    copias = [n for n in (r or {}).get("noches") or [] if (n["etapas"].get("copia") is not None
                                                          and not n["etapas"]["copia"].get("fallo"))]
    copia = piezas.cifra("Copia de seguridad", _fecha_parte(copias[0]["fecha"]) if copias else "–",
                         "en OneDrive, cada noche" if copias else "Sin copia registrada en las últimas noches.")
    fallos = ""
    if pruebas and pruebas.get("fallan"):
        fallos = ('<div class="zona una"><section><ul class="avisos">'
                  + "".join(f"<li class=mono>{esc(str(f))}</li>" for f in pruebas.get("fallos") or []) + "</ul></section></div>")
    top = max([e.get("segundos") or 0 for e in etapas.values() if isinstance(e, dict)] + [1])
    filas, total = [], 0
    for nombre in contratos.ETAPAS:
        e = etapas.get(nombre)
        if not isinstance(e, dict):
            continue
        seg = e.get("segundos") or 0
        total += seg
        filas.append(f'<div class="etapa"><span><b>{esc(_ETAPA_LARGA.get(nombre, nombre))}</b> '
                     f'<span class="suave peq">{esc(_que_hizo(nombre, e.get("resultado")))}</span>'
                     f'<svg class="pista-h" viewBox="0 0 100 6" preserveAspectRatio="none" aria-hidden="true">'
                     f'<rect class="pista" width="100" height="6"></rect>'
                     f'<rect class="lleno" width="{max(1, seg / top * 100):.1f}" height="6"></rect></svg></span>'
                     f'<span>{esc(_duracion(seg))}</span></div>')
    etapas_html = "".join(filas) or '<p class="vacio">Aún no hay ningún parte de la noche.</p>'
    if "error" in tareas:
        tabla = '<p class="vacio">No se pudo consultar las tareas programadas.</p>'
    elif not tareas:
        tabla = '<p class="vacio">Sin datos de las tareas programadas.</p>'
    else:
        cuerpo = []
        for nombre, d in tareas.items():
            d = d if isinstance(d, dict) else {"estado": str(d)}
            res = d.get("resultado")
            ok = res in (0, 267009) or (res is None and d.get("estado") in ("Ready", "Running"))
            proxima = (_dia_hora(d["proxima"]) if d.get("proxima") else
                       '<span class="suave">siempre en marcha</span>' if d.get("estado") == "Running" else "–")
            cuerpo.append(f'<tr><td><span class="etiqueta {"sube" if ok else "baja"}">{"bien" if ok else "falló"}</span> '
                          f'{esc(_TAREA_ES.get(nombre, nombre))}</td><td class="suave">{esc(_dia_hora(d.get("ultima")))}</td>'
                          f'<td>{proxima if proxima.startswith("<") else esc(proxima)}</td></tr>')
        tabla = ('<div class="scroll"><table><thead><tr><th>Tarea</th><th>Última vez</th><th>Próxima</th></tr></thead>'
                 f'<tbody>{"".join(cuerpo)}</tbody></table></div>')
    b, pop = piezas.ayuda("h-tareas", *_AYUDA_TAREAS)
    rejilla = _safe(lambda: _sistema_html(r), "") if r else ""
    return ('<div class="superficie" id="sistema"><div class="zona una"><section class="sin-pie"><div class="cab"><h2>Sistema</h2>'
            '<span class="suave peq">Cómo de frescos están los datos y cómo fue cada pieza.</span></div></section></div>'
            f'<div class="cifras borde">{noche}{precios}{prueba}{copia}</div>{fallos}'
            '<div class="zona mitades"><section><div class="cab"><h2>La última noche, etapa por etapa</h2>'
            f'<span class="suave peq">{esc(_duracion(total))} en total</span></div>{etapas_html}</section>'
            f'<section><div class="cab"><h2>Tareas programadas</h2>{b}</div>{tabla}{pop}</section></div>'
            + (f'<details class="plegado"><summary>Últimas 7 noches</summary>{rejilla}</details>' if rejilla else "")
            + "</div>")
def glosario(con, raiz, query):
    grupos = []
    for g in GRUPOS_GLOSARIO:
        art = "".join(f'<article id="{piezas._slug(t)}"><h3>{esc(t)}</h3><p>{esc(d)}</p>'
                      f'<p class="suave peq">En Quant: {esc(e)}</p></article>' for gg, t, d, e in GLOSARIO if gg == g)
        grupos.append(f'<div class="zona una grupo"><section aria-labelledby="g-{piezas._slug(g)}"><div class="cab">'
                      f'<h2 id="g-{piezas._slug(g)}">{esc(g)}</h2></div><div class="terminos">{art}</div></section></div>')
    chips = "".join(f'<a class="chip" href="#g-{piezas._slug(g)}">{esc(g)}</a>' for g in GRUPOS_GLOSARIO)
    buscador = ('<div class="zona una"><section><label class="buscar">Buscar un término'
                '<input type="search" id="buscar" placeholder="Por ejemplo: caída, demo, costes" autocomplete="off"></label>'
                f'<div class="chips">{chips}</div></section></div>')
    titular = '<h1>Glosario</h1><span class="suave">Cada término del panel, en palabras normales y con un ejemplo de Quant.</span>'
    script = """<script>
(function(){
  var input = document.getElementById('buscar');
  input.addEventListener('input', function(){
    var q = input.value.trim().toLowerCase();
    document.querySelectorAll('.terminos article').forEach(function(t){ t.hidden = q && t.textContent.toLowerCase().indexOf(q) < 0; });
    document.querySelectorAll('.grupo').forEach(function(g){ g.hidden = !g.querySelector('article:not([hidden])'); });
  });
})();
</script>"""
    return _layout("glosario", "Glosario", '<div class="superficie">' + buscador + "".join(grupos) + "</div>", script,
                   titular=titular, raiz=raiz)
