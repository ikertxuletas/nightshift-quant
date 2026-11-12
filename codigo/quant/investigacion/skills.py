"""Ficheros de oficio (skills) de cada agente y catalogo de indicadores en texto."""
from quant import indicadores, rutas

DESCRIPCIONES = {
    "open": "precio de apertura de la vela.",
    "high": "precio maximo de la vela.",
    "low": "precio minimo de la vela.",
    "close": "precio de cierre de la vela.",
    "volume": "volumen negociado de la vela.",
    "SMA(n)": "media simple de los ultimos n cierres, vela actual incluida.",
    "EMA(n)": "media exponencial de los cierres, vela actual incluida.",
    "RSI(n)": "fuerza relativa de Wilder sobre n velas; 0 a 100.",
    "ATR(n)": "rango verdadero medio de Wilder sobre n velas; mide volatilidad en unidades de precio.",
    "BB_SUP(n,k)": "media de n cierres mas k desviaciones tipicas.",
    "BB_INF(n,k)": "media de n cierres menos k desviaciones tipicas.",
    "MAX(n)": "maximo de los ultimos n maximos, vela actual incluida; para rupturas hay que escribir MAX(20)[1].",
    "MIN(n)": "minimo de los ultimos n minimos, vela actual incluida; misma advertencia.",
    "MOM(n)": "rentabilidad de los ultimos n cierres, en tanto por uno.",
    "ZSCORE(n)": "cuantas desviaciones tipicas se aleja el cierre de su media de n velas.",
    "VOL(n)": "desviacion tipica de los rendimientos de las ultimas n velas.",
    "HMA(n)": "media movil de Hull de n cierres; sube si HMA(n) > HMA(n)[1].",
    "RANGO_DIA(n)": "maximo menos minimo del dia de hace n dias (n=1 es ayer), en unidades de precio.",
}


def _leer(ruta):
    return ruta.read_text(encoding="utf-8") if ruta.exists() else ""


def cargar(agente, raiz=None):
    carpeta = (raiz or rutas.RAIZ / "skills") / agente
    referencias = {}
    carpeta_ref = carpeta / "ref"
    if carpeta_ref.is_dir():
        for fichero in sorted(carpeta_ref.glob("*.md")):
            referencias[fichero.stem] = _leer(fichero)
    return {"skill": _leer(carpeta / "skill.md"), "notas": _leer(carpeta / "notas.md"), "referencias": referencias}


def system(agente, referencias=None, raiz=None):
    cargado = cargar(agente, raiz)
    partes = [cargado["skill"]]
    nombres = cargado["referencias"] if referencias is None else [n for n in referencias if n in cargado["referencias"]]
    for nombre in nombres:
        partes.append(f"## Referencia: {nombre}\n{cargado['referencias'][nombre]}")
    if cargado["notas"]:
        partes.append(f"## Notas del supervisor\n{cargado['notas']}")
    return "\n\n".join(p for p in partes if p)


def catalogo_indicadores():
    lineas = []
    for nombre in indicadores.CAMPOS:
        lineas.append(f"{nombre}: {DESCRIPCIONES[nombre]}")
    for nombre, (nargs, _) in indicadores.CATALOGO.items():
        clave = f"{nombre}({'n,k' if nargs == 2 else 'n'})"
        lineas.append(f"{clave}: {DESCRIPCIONES[clave]}")
    return "\n".join(lineas) + "\n"


if __name__ == "__main__":
    import sys

    if "--indicadores" in sys.argv:
        destino = rutas.RAIZ / "skills" / "formalizador" / "ref" / "indicadores.md"
        destino.write_text(catalogo_indicadores(), encoding="utf-8")
        print(f"escrito {destino}")
