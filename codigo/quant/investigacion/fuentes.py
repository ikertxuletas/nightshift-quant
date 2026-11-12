import html as _html
import io
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from quant.fuentes import http

URL_ARXIV = ("https://export.arxiv.org/api/query?search_query=cat:q-fin.TR+OR+cat:q-fin.PM+OR+cat:q-fin.ST"
             "&sortBy=submittedDate&sortOrder=descending&max_results={n}")
URL_QUANTPEDIA = "https://quantpedia.com/strategies/"
URL_REDDIT = "https://www.reddit.com/r/{sub}/top/.rss?t=week"
URL_MQL5 = "https://www.mql5.com/en/code/mt5/experts"
MINIMO_QUANTPEDIA = 1500
CABECERAS_REDDIT = {"User-Agent": "windows:quant-investigacion:1.0 (uso personal)"}


def texto_plano(texto):
    sin_bloques = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", texto, flags=re.S | re.I)
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", sin_bloques))).strip()


def _campo(bloque, etiqueta):
    encontrado = re.search(rf"<{etiqueta}[^>]*>(.*?)</{etiqueta}>", bloque, re.S)
    return _html.unescape(re.sub(r"\s+", " ", encontrado.group(1))).strip() if encontrado else ""


def _titulo_html(pagina, limite=120):
    for etiqueta in ("h1", "title"):
        encontrado = re.search(rf"<{etiqueta}[^>]*>(.*?)</{etiqueta}>", pagina, re.S | re.I)
        titulo = texto_plano(encontrado.group(1))[:limite] if encontrado else ""
        if titulo:
            return titulo
    return ""


def _pdf(contenido):
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(contenido)).pages)


def arxiv(sesion, max_n=20, dormir=time.sleep):
    crudo = http.descargar(URL_ARXIV.format(n=max_n), sesion, dormir=dormir).decode("utf-8", "ignore")
    documentos = []
    for bloque in re.findall(r"<entry>(.*?)</entry>", crudo, re.S):
        url = _campo(bloque, "id")
        texto = f"{_campo(bloque, 'title')}\n\n{_campo(bloque, 'summary')}"
        dormir(1.0)
        try:
            texto += "\n\n" + _pdf(http.descargar(url.replace("/abs/", "/pdf/"), sesion, dormir=dormir))
        except Exception:
            pass
        documentos.append({"fuente": "arxiv", "url": url, "titulo": _campo(bloque, "title"),
                           "fecha": _campo(bloque, "published"), "texto": texto})
    return documentos


def quantpedia(sesion, max_n=20, dormir=time.sleep):
    listado = http.descargar(URL_QUANTPEDIA, sesion, dormir=dormir).decode("utf-8", "ignore")
    documentos = []
    for slug in dict.fromkeys(re.findall(r'href="/strategies/([a-z0-9-]+)"', listado)):
        if len(documentos) >= max_n:
            break
        dormir(1.0)
        url = f"https://quantpedia.com/strategies/{slug}"
        texto = texto_plano(http.descargar(url, sesion, dormir=dormir).decode("utf-8", "ignore"))
        if len(texto) >= MINIMO_QUANTPEDIA:
            documentos.append({"fuente": "quantpedia", "url": url, "titulo": slug,
                               "fecha": datetime.now(timezone.utc).date().isoformat(), "texto": texto})
    return documentos


def reddit(sesion, subs=("algotrading", "quant"), max_n=20, dormir=time.sleep):
    documentos = []
    for sub in subs:
        dormir(10.0)
        crudo = http.descargar(URL_REDDIT.format(sub=sub), sesion, dormir=dormir,
                               cabeceras=CABECERAS_REDDIT).decode("utf-8", "ignore")
        for bloque in re.findall(r"<entry>(.*?)</entry>", crudo, re.S)[:max_n]:
            enlace = re.search(r'<link[^>]*href="([^"]+)"', bloque)
            documentos.append({"fuente": "reddit", "url": enlace.group(1) if enlace else "",
                               "titulo": _campo(bloque, "title"), "fecha": _campo(bloque, "updated"),
                               "texto": f"{_campo(bloque, 'title')}\n\n{texto_plano(_campo(bloque, 'content'))}"})
    return documentos


def mql5(sesion, max_n=10, dormir=time.sleep):
    listado = http.descargar(URL_MQL5, sesion, dormir=dormir).decode("utf-8", "ignore")
    documentos = []
    for ident in list(dict.fromkeys(re.findall(r'href="/en/code/(\d+)"', listado)))[:max_n]:
        dormir(1.0)
        url = f"https://www.mql5.com/en/code/{ident}"
        crudo = http.descargar(url, sesion, dormir=dormir).decode("utf-8", "ignore")
        texto = texto_plano(crudo)
        documentos.append({"fuente": "mql5", "url": url, "titulo": _titulo_html(crudo) or texto[:80],
                           "fecha": datetime.now(timezone.utc).date().isoformat(), "texto": texto})
    return documentos


def materiales(carpeta):
    documentos = []
    for ruta in sorted(Path(carpeta).glob("*")):
        if ruta.suffix.lower() not in (".pdf", ".md", ".txt"):
            continue
        texto = _pdf(ruta.read_bytes()) if ruta.suffix.lower() == ".pdf" else ruta.read_text(encoding="utf-8",
                                                                                             errors="ignore")
        documentos.append({"fuente": "materiales", "url": f"materiales://{ruta.name}", "titulo": ruta.stem,
                           "fecha": datetime.fromtimestamp(ruta.stat().st_mtime, timezone.utc).date().isoformat(),
                           "texto": texto})
    return documentos


REGISTRO = {"arxiv": arxiv, "quantpedia": quantpedia, "reddit": reddit, "mql5": mql5}
