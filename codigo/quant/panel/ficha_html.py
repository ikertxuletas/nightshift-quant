"""HTML pieces for the strategy and experiment pages and the Ranking cards (plans 14-15)."""
from html import escape as esc


def franja(nota):
    if nota is None:
        return "sin nota", "nota-0"
    if nota >= 75:
        return "muy alta", "nota-4"
    if nota >= 70:
        return "alta", "nota-3"
    if nota >= 65:
        return "media", "nota-2"
    return "baja", "nota-1"


def circulo(nota):
    nombre, clase = franja(nota)
    return f'<span class="circulo {clase}" title="Nota {nombre}">{nota if nota is not None else "–"}</span>'


def franja_pf(pf):
    if pf is None:
        return "nota-0"
    return "nota-4" if pf >= 1.3 else "nota-3" if pf >= 1.0 else "nota-2" if pf >= 0.9 else "nota-1"


def circulo_pf(pf):
    texto = "–" if pf is None else f"{pf:.2f}".replace(".", ",")
    return f'<span class="circulo pf {franja_pf(pf)}" title="Gana por cada euro que pierde">{texto}</span>'


CRITERIOS_CORTOS = {"sharpe_vs_comprar_mantener": "No supera a comprar y mantener", "sharpe_fuera_de_muestra": "Falla con datos que no vio",
                    "operaciones": "Muy pocas operaciones", "operaciones_fuera_de_muestra": "Pocas operaciones en datos no vistos",
                    "sharpe_fuera_vs_dentro": "Rinde mucho peor fuera que dentro", "drawdown": "Caída máxima demasiado grande",
                    "rentabilidad_costes_x2": "No aguanta costes dobles", "robustez": "Poco robusta",
                    "montecarlo_dd_p95": "Caída posible demasiado grande"}


def casillas(criterios_l):
    if not criterios_l:
        return "<span></span>"
    return ('<span class="casillas" role="img" aria-label="Criterios del validador">' + "".join(
        f'<i class="{"si" if c.get("cumple") else "no"}" title="{esc(CRITERIOS_CORTOS.get(c.get("criterio"), str(c.get("criterio"))))}: '
        f'{"cumple" if c.get("cumple") else "no cumple"}"></i>' for c in criterios_l) + "</span>")


def _tono_attr(v):
    return "b-pos" if v >= 7 else "b-mid" if v >= 4 else "b-neg"


def minibarras(atributos):
    if not atributos:
        return ""
    w = 100 / len(atributos)
    rects = "".join(f'<rect x="{i * w + w * .12:.1f}" y="{40 - max(2, a["valor"] * 3.8):.1f}" width="{w * .76:.1f}" '
                    f'height="{max(2, a["valor"] * 3.8):.1f}" class="{_tono_attr(a["valor"])}">'
                    f'<title>{esc(a["nombre"])}: {a["valor"]:.1f}</title></rect>' for i, a in enumerate(atributos))
    return f'<svg viewBox="0 0 100 40" class="minibars" role="img" aria-label="Las 8 notas que forman la nota">{rects}</svg>'


def _num(v, d=2):
    return "–" if v is None else f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(v, d=1):
    return "–" if v is None else f"{_num(v * 100, d)} %"


def _firmar(v, d=2):
    return "–" if v is None else ("+" if v > 0 else "−" if v < 0 else "") + _num(abs(v), d)


def _ayuda(ident, titulo, texto, glosario=None):
    from quant.panel import piezas
    return "".join(piezas.ayuda(ident, titulo, texto, glosario))


def gauge(nota):
    import math
    if nota is None:
        return '<p class="vacio">Sin nota: solo la tienen las que pasan o casi.</p>'
    v = max(0, min(100, nota))
    largo = math.pi * 70
    return (f'<svg viewBox="0 0 180 110" class="gauge" role="img" aria-label="Nota {nota} de 100">'
            '<path d="M20 95 A70 70 0 0 1 160 95" class="g-bg"></path>'
            f'<path d="M20 95 A70 70 0 0 1 160 95" class="g-val {franja(nota)[1]}" stroke-dasharray="{largo * v / 100:.1f} {largo:.1f}"></path>'
            f'<text x="90" y="84" text-anchor="middle" class="g-num">{nota}</text>'
            '<text x="90" y="104" text-anchor="middle" class="g-sub">de 100</text></svg>')


def gauge_pf(pf):
    import math
    if pf is None:
        return '<p class="vacio">– Sin datos: no llegó a evaluarse.</p>'
    largo = math.pi * 70
    frac = max(0.0, min(pf, 2.0)) / 2
    texto = ("Por encima de 1: gana dinero en el entrenamiento" if pf >= 1
             else "Por debajo de 1: pierde dinero (la raya marca el 1)")
    return (f'<svg viewBox="0 0 180 110" class="gauge" role="img" aria-label="Gana {_num(pf)} por cada euro que pierde">'
            '<path d="M20 95 A70 70 0 0 1 160 95" class="g-bg"></path>'
            f'<path d="M20 95 A70 70 0 0 1 160 95" class="g-val {franja_pf(pf)}" stroke-dasharray="{largo * frac:.1f} {largo:.1f}"></path>'
            '<line x1="90" y1="16" x2="90" y2="34" class="marca-uno"></line>'
            f'<text x="90" y="86" text-anchor="middle" class="g-num">{_num(pf)}</text></svg>'
            f'<span class="suave peq">{texto}</span>')


def anual(anual_d):
    if not anual_d:
        return ""
    a = sorted(anual_d.items())
    mx = max(abs(v) for _, v in a) or 1
    w = 100 / len(a)
    neg = any(v < 0 for _, v in a)
    cero, alto = (50, 45) if neg else (96, 90)
    rects = "".join(f'<rect x="{i * w + w * .15:.2f}" y="{cero - abs(v) / mx * alto if v >= 0 else cero:.2f}" width="{w * .7:.2f}" '
                    f'height="{max(.4, abs(v) / mx * alto):.2f}" class="{"b-pos" if v >= 0 else "b-neg"}">'
                    f'<title>{esc(y)}: {_firmar(v * 100, 1)} %</title></rect>' for i, (y, v) in enumerate(a))
    return (f'<svg viewBox="0 0 100 100" preserveAspectRatio="none" class="anual" role="img" aria-label="Rentabilidad por año">'
            f'{rects}<line x1="0" x2="100" y1="{cero}" y2="{cero}" class="axis"></line></svg>'
            f'<div class="anual-ejes suave peq"><span>{esc(a[0][0])}</span><span>{esc(a[-1][0])}</span></div>')


def _celda_mes(v):
    if v is None:
        return '<td class="h-none">·</td>'
    if v == 0:
        return '<td class="h-0">·</td>'
    nivel = min(4, int(abs(v) * 100 / 2) + 1)
    return f'<td class="h-{"p" if v > 0 else "n"}{nivel}" title="{_firmar(v * 100, 2)} %">{_num(v * 100, 1)}</td>'


def meses(meses_d, anual_d, ultimos=None):
    anios = sorted(meses_d or {}, reverse=True)[:ultimos or None]
    cab = "".join(f'<th scope="col">{m}</th>' for m in "EFMAMJJASOND")
    filas = "".join(f'<tr><th scope="row">{esc(y)}</th>{"".join(_celda_mes(v) for v in meses_d[y])}'
                    f'<td class="tot {"sube" if (anual_d.get(y) or 0) >= 0 else "baja"}">{_firmar((anual_d.get(y) or 0) * 100, 1)} %</td></tr>'
                    for y in anios)
    return (f'<div class="scroll"><table class="heat"><thead><tr><th scope="col">Año</th>{cab}<th scope="col">Total</th></tr></thead>'
            f'<tbody>{filas}</tbody></table></div>')


_TONO_TXT = {"b-pos": "sube", "b-mid": "aviso", "b-neg": "baja"}


def medidor(puntos):
    filas = []
    for a in puntos["atributos"]:
        t = _tono_attr(a["valor"])
        filas.append(f'<div><div class="row-head"><b>{esc(a["nombre"])}</b><b class="{_TONO_TXT[t]}">{_num(a["valor"], 1)}</b></div>'
                     f'<svg viewBox="0 0 100 4" preserveAspectRatio="none" class="sbar" aria-hidden="true">'
                     f'<rect width="100" height="4" class="s-bg"></rect><rect width="{a["valor"] * 10:.1f}" height="4" class="{t}"></rect></svg>'
                     f'<span class="suave peq">{esc(a["por_que"])}</span></div>')
    return f'<div class="medidor3">{"".join(filas)}</div>'


CRIT_ES = {
    "drawdown": ("La peor caída no pasa del {u}.", True),
    "sharpe_fuera_de_muestra": ("En los años reservados gana con un Sharpe de al menos {u}.", False),
    "sharpe_fuera_vs_dentro": ("Fuera de muestra conserva al menos {u} veces lo que rendía dentro.", False),
    "rentabilidad_costes_x2": ("Con costes al doble sigue ganando dinero.", True),
    "robustez": ("Al mover sus parámetros un 20 %, ganan al menos el {u} de las variantes.", True),
    "operaciones": ("Tiene al menos {u} operaciones.", False),
    "operaciones_fuera_de_muestra": ("Al menos {u} de ellas en los años reservados.", False),
    "sharpe_vs_comprar_mantener": ("Rinde mejor por riesgo que comprar y mantener.", False),
    "montecarlo_dd_p95": ("Barajando sus operaciones 1.000 veces, la caída del 5 % peor no pasa del {u}.", True),
}


def _valor_crit(v, es_pct, d_pct=1):
    if es_pct:
        return _pct(v, d_pct)
    return _num(v, 0 if isinstance(v, (int, float)) and float(v).is_integer() else 2)


def criterios(lista):
    filas = []
    for c in lista or []:
        texto, es_pct = CRIT_ES.get(c["criterio"], (c["criterio"], False))
        filas.append(f'<li><span class="marca {"sube" if c["cumple"] else "baja"}" aria-label="{"cumple" if c["cumple"] else "no cumple"}">'
                     f'{"✓" if c["cumple"] else "✗"}</span><span class="que">{esc(texto.format(u=_valor_crit(c.get("umbral"), es_pct, 0)))}</span>'
                     f'<b>{esc(_valor_crit(c.get("valor"), es_pct))}</b></li>')
    return f'<ul class="filas criterios">{"".join(filas)}</ul>' if filas else '<p class="vacio">Sin criterios: no llegó a evaluarse.</p>'


def _nivel_pf(p):
    if p >= 1:
        return f"m-p{1 if p < 1.1 else 2 if p < 1.2 else 3 if p < 1.33 else 4}"
    return f"m-n{1 if p > 0.9 else 2 if p > 0.8 else 3 if p > 0.65 else 4}"


def rejilla(celdas_l, nota):
    total = sum(c["ops"] for c in celdas_l or [])
    minimo = 20 if total >= 1000 else 5
    celdas = [c for c in celdas_l or [] if c["ops"] >= minimo and c["pf"] is not None]
    if not celdas:
        return f'<p class="vacio">No hay franjas con {minimo} operaciones o más.</p>'
    dias = [d for d in "LMXJVSD" if any(c["dia"] == d for c in celdas)]
    horas = sorted({c["hora"] for c in celdas})
    por = {(c["dia"], c["hora"]): c for c in celdas}
    h = f'<div class="rejilla dias-{len(dias)}"><span></span>' + "".join(f'<span class="h">{d}</span>' for d in dias)
    for hr in horas:
        h += f'<span class="h">{esc(hr)}</span>'
        for d in dias:
            c = por.get((d, hr))
            h += (f'<span class="c {_nivel_pf(c["pf"])}" title="{c["ops"]} operaciones">{_num(c["pf"])}</span>' if c
                  else '<span class="c vacia">–</span>')
    aviso = ": con tan pocas, tómalo como orientación" if minimo < 20 else ""
    return h + f'</div><p class="explica">{esc(nota)} Solo franjas con {minimo} operaciones o más{aviso}.</p>'


_SALIDAS = {"sesion": "fin de sesión", "senal": "señal", "stop": "stop", "objetivo": "objetivo", "trailing": "stop móvil"}


def _grupo_suerte(g4, probadas):
    p = g4["prob_suerte"]
    vecinos = g4["vecinos"]
    nota = (f"{len(vecinos)} variante(s) vecina(s) probada(s): " + ", ".join(f'{v["etiqueta"]} ({_num(v["pf"])})' for v in vecinos)
            if vecinos else "Sin variantes vecinas probadas: no se sabe si es una meseta o un pico.")
    valor = "–" if p is None else "<0,1 %" if p < .001 else _pct(p, 1 if p < .01 else 0)
    cuantas = (f'<p class="suave peq">Ojo: se eligió entre {_num(probadas, 0)} combinaciones probadas, y entre tantas unas '
               f'{_num(probadas * .05, 0)} saldrían así de bien por puro azar.</p>') if probadas else ""
    return (valor, "sube" if p is not None and p < .01 else "aviso",
            f'<p>Sin ninguna ventaja real, un resultado así de bueno saldría este porcentaje de las veces.</p>{cuantas}'
            f'<p class="suave peq">{esc(nota)}</p>')


def seis_grupos(a, probadas=None):
    g1, g2, g3, g4, g5, g6 = (a.get(k) for k in ("g1", "g2", "g3", "g4", "g5", "g6"))
    meses_n = round(g3["dias_sin_maximo"] / 30)
    csb = g1["costes_sobre_bruto"]
    salidas = ", ".join(f"{_SALIDAS.get(k, k)} {_pct(v, 0)}" for k, v in g2["salidas"].items())
    suerte = _grupo_suerte(g4, probadas)
    if g6:
        rel = ("Casi independiente del índice." if abs(g6["corr_sp500"]) < .2 else
               "Tiende a ir al revés que el índice." if g6["corr_sp500"] < 0 else "Tiende a ir con el índice.")
        aporta = f'<p>Cómo se mueve frente al SP500 (de −1 a 1).</p><p class="suave peq">{rel}</p>'
    else:
        aporta = "<p>No se pudo comparar con el SP500: faltan sus precios o hay pocos días con operaciones en común.</p>"
    cuando = ('<p>Lo que gana por euro perdido según cómo se movió el mercado ese día.</p><table class="mini-t">'
              f'<tr><td>Días movidos</td><td>{_num(g5["volatil"]["pf"])}</td></tr>'
              f'<tr><td>Días tranquilos</td><td>{_num(g5["tranquilo"]["pf"])}</td></tr>'
              f'<tr><td>Días laterales</td><td>{_num(g5["lateral"]["pf"])}</td></tr>'
              f'<tr><td>Días de tendencia</td><td>{_num(g5["tendencia"]["pf"])}</td></tr></table>') if g5 else \
        "<p>No se pudo calcular: faltan los precios diarios.</p>"
    grupos = [
        ("¿Merece la pena cada operación?", _pct(csb, 0), "baja" if (csb or 0) > .5 else "sube",
         (f"<p>De lo que gana antes de costes, los costes se comen el {_pct(csb, 0)}.</p>" if csb is not None
          else "<p>Antes de costes ya pierde: no hay beneficio que repartir.</p>")
         + f'<p class="suave peq">Gana {_num(g1["bruto_por_op_pts"])} puntos por operación y paga {_num(g1["coste_por_op_pts"])} de costes.</p>',
         "Compara lo que gana antes de costes con lo que pagan comisiones, diferencial y deslizamiento. Si los costes se llevan "
         "la mayor parte, hacen falta operaciones que se muevan más.", "Costes sobre el beneficio"),
        ("¿Están bien puestos el stop y el objetivo?", f'{_num(g2["pts"]["dejado"], 1)} pts', "",
         f'<p>Lo que deja por el camino: llegan a ir +{_num(g2["pts"]["mfe"], 1)} puntos a favor y acaban en '
         f'{_firmar(g2["pts"]["resultado"], 1)}.</p><p class="suave peq">Stop a {_num(g2["pts"]["stop"], 0)} puntos. '
         f'Salidas: {esc(salidas)}.</p>',
         "Mide cuánto llegan a ir a favor las operaciones antes de cerrarse y cuánto se pierde de eso. Si deja mucho por el "
         "camino, un objetivo más cercano o una salida antes podrían capturarlo.", "Lo que deja por el camino"),
        ("¿La aguantarías operándola?", f"{meses_n} meses", "baja" if meses_n > 12 else "",
         f'<p>El tiempo más largo sin superar su mejor momento.</p><p class="suave peq">Peor racha: {g3["peor_racha"]} pérdidas '
         f'seguidas. Opera {_num(g3["ops_semana"])} veces por semana.</p>',
         "Un periodo largo sin recuperar el máximo es lo que hace abandonar una estrategia aunque sea buena: el «factor humano».",
         "Tiempo sin un nuevo máximo"),
        ("¿Es real o es suerte?", suerte[0], suerte[1], suerte[2],
         "Con el número de operaciones y lo que varían, calcula cada cuánto una estrategia sin ninguna ventaja daría un "
         "resultado así de bueno. Un porcentaje bajo es buena señal, pero no garantiza nada: entre miles de combinaciones "
         "probadas, algunas salen bien por azar, y por eso además tiene que pasar el validador y la demo.", "Probabilidad de azar"),
        ("¿Cuándo funciona?", f'{_num(g5["volatil"]["pf"])} / {_num(g5["tranquilo"]["pf"])}' if g5 else "–", "", cuando,
         "Separa los días según cómo se movió el mercado: más o menos movimiento que la media de 20 días, y con tendencia clara o "
         "laterales. Una diferencia grande sugiere un filtro.", None),
        ("¿Aporta algo al conjunto?", _num(g6["corr_sp500"]) if g6 else "–", "", aporta,
         "Cerca de 1 sería lo mismo que tener el índice; cerca de 0, independiente; negativo, lo contrario. Lo independiente o "
         "negativo es lo que más aporta a una cartera.", "Correlación con el SP500"),
    ]
    return '<div class="grupos">' + "".join(
        f'<div><h3>{esc(t)}</h3><span class="val {tono}">{esc(v)}</span>{cuerpo}{_ayuda(f"g-{i}", t, ay, gl)}</div>'
        for i, (t, v, tono, cuerpo, ay, gl) in enumerate(grupos)) + "</div>"
