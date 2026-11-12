from datetime import date, datetime
from html import escape as esc
from pathlib import Path

from quant import datos

NOMBRES = {"US500": "SP500", "BTCUSDT": "Bitcoin", "ETHUSDT": "Ethereum", "XRPUSDT": "XRP", "DOGEUSDT": "Dogecoin"}
TICKER = ("US500", "BTCUSDT", "ETHUSDT")
_LOGOS = {
    "US500": ("#24324F", '<text x="20" y="25" text-anchor="middle" font-size="12" font-weight="600" fill="#E9EEF6">500</text>'),
    "BTCUSDT": ("#F7931A", '<text x="20" y="27" text-anchor="middle" font-size="20" font-weight="600" fill="#fff">₿</text>'),
    "ETHUSDT": ("#627EEA", '<path d="M20 7l-7 13 7 4 7-4z" fill="#fff" opacity=".9"></path>'
                           '<path d="M20 26l-7-4 7 11 7-11z" fill="#fff" opacity=".7"></path>'),
    "XRPUSDT": ("#2A2F36", '<path d="M12 12l8 7 8-7M12 28l8-7 8 7" fill="none" stroke="#fff" stroke-width="2.6" '
                           'stroke-linecap="round"></path>'),
    "DOGEUSDT": ("#C2A633", '<text x="20" y="27" text-anchor="middle" font-size="19" font-weight="600" fill="#fff">Ð</text>'),
}
_MERCADO_CACHE = {}


def nombre(instrumento):
    return NOMBRES.get(instrumento, instrumento)


def num(v, dec=2):
    return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def firmar(v, dec=2):
    return ("+" if v > 0 else "−" if v < 0 else "") + num(abs(v), dec)


def logo(instrumento, px):
    fondo, dibujo = _LOGOS.get(instrumento, ("#2A2F36", '<text x="20" y="24" text-anchor="middle" font-size="10" '
                                                       f'font-weight="600" fill="#E9EBEE">{esc(instrumento[:4])}</text>'))
    return (f'<svg class="logo" width="{px}" height="{px}" viewBox="0 0 40 40" aria-hidden="true">'
            f'<circle cx="20" cy="20" r="20" fill="{fondo}"></circle>{dibujo}</svg>')


def mercado_mini(raiz):
    clave = (str(raiz), date.today())
    if clave not in _MERCADO_CACHE:
        salida = []
        for inst in TICKER:
            try:
                c = datos.cargar(inst, "D1", Path(raiz) / "datos")["close"][-100:]
            except (datos.ErrorDatos, OSError, KeyError):
                continue
            if len(c) < 2:
                continue
            salida.append({"instrumento": inst, "nombre": nombre(inst), "ultimo": float(c[-1]),
                           "cambio_pct": float(c[-1] / c[-2] - 1) * 100, "cierres": [float(v) for v in c]})
        _MERCADO_CACHE.clear()
        _MERCADO_CACHE[clave] = salida
    return _MERCADO_CACHE[clave]


def _fondo(mercado):
    lineas = []
    for j, (m, off) in enumerate(zip(mercado, (20, 70, 120))):
        c = m["cierres"]
        mn, mx = min(c), max(c)
        paso = 800 / max(len(c) - 1, 1)
        t = [(i * paso, off + (1 - (v - mn) / ((mx - mn) or 1)) * 90) for i, v in enumerate(c)]
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in t + [(x + 800, y) for x, y in t])
        lineas.append(f'<polyline points="{pts}" opacity="{1 - j * 0.2:.1f}"></polyline>')
    return f'<svg class="fondo" viewBox="0 0 1600 220" preserveAspectRatio="none" aria-hidden="true">{"".join(lineas)}</svg>'


_MARCA = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17l5-6 4 3 7-9" fill="none" stroke="currentColor" '
          'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"></path></svg>')


def cabecera(active, titular, raiz):
    from quant.panel.paginas import TABS
    mercado = mercado_mini(raiz) if raiz is not None else []
    nav = "".join(f'<a href="{href}"{' aria-current="page"' if key == active else ""}>{esc(label)}</a>'
                  for key, href, label in TABS)
    ticker = "".join(f'<span>{logo(m["instrumento"], 20)}<b>{esc(m["nombre"])}</b>{num(m["ultimo"])}'
                     f'<span class="{"sube" if m["cambio_pct"] >= 0 else "baja"}">{firmar(m["cambio_pct"])} %</span></span>'
                     for m in mercado)
    return (f'{_fondo(mercado)}<div class="barra"><a class="marca" href="/">{_MARCA}Quant</a>'
            f'<nav class="pestanas" aria-label="Secciones">{nav}</nav>'
            f'<span class="derecha">Actualizado a las {datetime.now().strftime("%H:%M")}</span></div>'
            + (f'<div class="ticker">{ticker}</div>' if ticker else "")
            + (f'<div class="titular">{titular}</div>' if titular else ""))


def _slug(texto):
    import unicodedata
    plano = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return "-".join("".join(c if c.isalnum() else " " for c in plano).split())


def ayuda(ident, titulo, texto, glosario=None):
    boton = (f'<button type="button" class="ayuda" popovertarget="{esc(ident)}" '
             f'aria-label="{esc("Qué es: " + titulo)}">?</button>')
    enlace = (f'<a href="/glosario#{_slug(glosario)}" class="peq">Ver «{esc(glosario)}» en el glosario</a>'
              if glosario else "")
    parrafos = "".join(f"<p>{esc(p)}</p>" for p in texto.split("\n\n"))
    return boton, f'<div popover id="{esc(ident)}"><h3>{esc(titulo)}</h3>{parrafos}{enlace}</div>'


def cifra(etiqueta, valor, sub, tono="", ayuda=None, grande=False):
    boton, pop = ayuda or ("", "")
    return (f'<div{" class=grande" if grande else ""}><span class="suave peq lbl">{esc(etiqueta)}</span>'
            f'<span class="val {esc(tono)}">{esc(valor)}</span><span class="suave peq sub">{esc(sub)}</span>{boton}{pop}</div>')


def selector(nombre, opciones, actual, deshabilitadas=(), etiqueta=""):
    botones = "".join(
        f'<button type="button" data-{esc(nombre)}="{esc(v)}" aria-pressed="{"true" if v == actual else "false"}"'
        + (' disabled title="Aún no hay datos para este periodo"' if v in deshabilitadas else "")
        + f">{esc(t)}</button>" for v, t in opciones)
    return f'<div class="selector" role="group" aria-label="{esc(etiqueta or nombre)}">{botones}</div>'


def spark(valores, ancho, alto, tono):
    if not valores:
        return ""
    mn, mx = min(valores), max(valores)
    paso = ancho / max(len(valores) - 1, 1)
    pts = " ".join(f"{i * paso:.1f},{alto - 3 - ((v - mn) / ((mx - mn) or 1)) * (alto - 6):.1f}"
                   for i, v in enumerate(valores))
    return (f'<svg class="spark {esc(tono)}" width="{ancho}" height="{alto}" viewBox="0 0 {ancho} {alto}" '
            f'aria-hidden="true"><polyline points="{pts}"></polyline></svg>')


def barra_uno(pf, maximo=2.0):
    lleno = max(0.0, min(pf, maximo)) / maximo * 100
    return (f'<svg class="uno-barra" viewBox="0 0 100 16" preserveAspectRatio="none" aria-hidden="true">'
            f'<rect class="pista" y="6" width="100" height="4"></rect>'
            f'<rect class="lleno{"" if pf >= 1 else " baja"}" y="6" width="{lleno:.1f}" height="4"></rect>'
            f'<rect class="marca1" x="{1 / maximo * 100:.1f}" y="0" width="0.6" height="16"></rect></svg>')


def graficos(specs):
    if not specs:
        return ""
    import json
    datos_js = json.dumps(specs, ensure_ascii=False).replace("<", "\\u003c")
    return ('<script src="/static/lightweight-charts.standalone.production.js"></script>'
            f'<script type="application/json" id="graficos-datos">{datos_js}</script>'
            '<script src="/static/graficos.js"></script>')
