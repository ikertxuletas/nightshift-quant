import json
import sys
from pathlib import Path

from quant import rutas

CLASES = {"indice", "forex", "materia", "accion", "cripto"}
FUENTES = {"dukascopy", "yahoo", "binance"}
URL_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
URL_DAX = "https://en.wikipedia.org/wiki/DAX"
_AGENTE = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}


class ErrorUniverso(ValueError):
    pass


def _validar(nombre, info):
    if info.get("clase") not in CLASES or info.get("fuente") not in FUENTES:
        raise ErrorUniverso(f"{nombre}: clase o fuente no válida")
    if not info.get("simbolo") or not info.get("desde"):
        raise ErrorUniverso(f"{nombre}: falta simbolo o desde")
    if info["fuente"] == "dukascopy" and not info.get("divisor", 0) > 0:
        raise ErrorUniverso(f"{nombre}: dukascopy necesita divisor > 0")


def cargar(config=rutas.CONFIG):
    ruta = Path(config) / "universo.json"
    if not ruta.exists():
        return {"instrumentos": {}}
    instrumentos = dict(json.loads(ruta.read_text(encoding="utf-8"))["instrumentos"])
    acciones = Path(config) / "universo_acciones.json"
    if acciones.exists():
        for t in json.loads(acciones.read_text(encoding="utf-8")):
            instrumentos.setdefault(t, {"clase": "accion", "fuente": "yahoo", "simbolo": t, "desde": "1990-01-01"})
    for nombre, info in instrumentos.items():
        _validar(nombre, info)
    return {"instrumentos": instrumentos}


def clase_de(instrumento, uni):
    info = uni["instrumentos"].get(instrumento)
    return info["clase"] if info else None


def desde_de(instrumento, uni):
    info = uni["instrumentos"].get(instrumento)
    return info.get("desde") if info else None


def tickers_indices(leer_html):
    sp500 = leer_html(URL_SP500, storage_options=_AGENTE)[0]["Symbol"].astype(str).str.replace(".", "-")
    dax = next(t for t in leer_html(URL_DAX, storage_options=_AGENTE) if "Ticker" in t.columns and len(t) == 40)
    return sorted(set(sp500) | set(dax["Ticker"].astype(str)))


def refrescar_acciones(config=rutas.CONFIG, leer_html=None):
    if leer_html is None:
        import pandas as pd
        leer_html = pd.read_html
    tickers = tickers_indices(leer_html)
    if len(tickers) < 400:
        raise ErrorUniverso(f"solo se obtuvieron {len(tickers)} tickers, menos del minimo de 400")
    ruta = Path(config) / "universo_acciones.json"
    if ruta.exists():
        previos = json.loads(ruta.read_text(encoding="utf-8"))
        if len(tickers) < len(previos) * 0.8:
            raise ErrorUniverso(
                f"solo se obtuvieron {len(tickers)} tickers, menos del 80% de los {len(previos)} anteriores")
    ruta.write_text(json.dumps(tickers, indent=1), encoding="utf-8")
    return len(tickers)


if __name__ == "__main__":
    if "--refrescar-acciones" in sys.argv:
        print(f"{refrescar_acciones()} tickers")
    else:
        print(json.dumps(cargar(), indent=2, ensure_ascii=False))
