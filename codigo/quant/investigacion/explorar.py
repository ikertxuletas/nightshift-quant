import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from quant import rutas
from quant.investigacion import catalogo, fuentes


def main(argv=None, sesion=None, registro=None, materiales=None):
    parser = argparse.ArgumentParser(description="Busca documentos con estrategias y los guarda en el catalogo")
    parser.add_argument("--raiz", default=str(rutas.RAIZ))
    parser.add_argument("--max-por-fuente", type=int, default=20)
    parser.add_argument("--solo", nargs="*")
    parser.add_argument("--sin-materiales", action="store_true")
    args = parser.parse_args(argv)
    raiz = Path(args.raiz)
    (raiz / "registro").mkdir(parents=True, exist_ok=True)
    registro = fuentes.REGISTRO if registro is None else registro
    if sesion is None:
        import requests
        sesion = requests.Session()
    con = catalogo.abrir(raiz / "catalogo.db")
    textos = raiz / "documentos"
    por_fuente, errores, intentadas, log = {}, 0, 0, []
    for nombre, funcion in registro.items():
        if args.solo and nombre not in args.solo:
            continue
        intentadas += 1
        try:
            documentos = funcion(sesion, max_n=args.max_por_fuente)
        except Exception as e:
            errores += 1
            log.append({"fuente": nombre, "error": f"{type(e).__name__}: {e}"})
            continue
        nuevos = sum(1 for d in documentos
                     if catalogo.anadir_documento(con, d["fuente"], d["url"], d["titulo"], d["fecha"],
                                                  d["texto"], textos))
        por_fuente[nombre] = nuevos
        log.append({"fuente": nombre, "vistos": len(documentos), "nuevos": nuevos})
    propios = materiales
    if propios is None and not args.sin_materiales:
        if (raiz / "materiales").is_dir():
            intentadas += 1
            try:
                propios = fuentes.materiales(raiz / "materiales")
            except Exception as e:
                errores += 1
                log.append({"fuente": "materiales", "error": f"{type(e).__name__}: {e}"})
                propios = []
        else:
            propios = []
    for d in propios or []:
        if catalogo.anadir_documento(con, d["fuente"], d["url"], d["titulo"], d["fecha"], d["texto"], textos):
            por_fuente["materiales"] = por_fuente.get("materiales", 0) + 1
    salida = {"fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"), "por_fuente": por_fuente,
              "nuevos": sum(por_fuente.values()), "errores": errores}
    hoy = datetime.now(timezone.utc).strftime("%Y%m%d")
    with open(raiz / "registro" / f"explorar_{hoy}.log", "a", encoding="utf-8") as fichero:
        for linea in log:
            fichero.write(json.dumps(linea, ensure_ascii=False) + "\n")
    (raiz / "registro" / "explorar_ultimo.json").write_text(json.dumps(salida, indent=1, ensure_ascii=False),
                                                           encoding="utf-8")
    print(json.dumps(salida, ensure_ascii=False))
    # Una fuente caida no hace fallar la etapa: solo si fallan todas las fuentes intentadas.
    return 1 if errores and errores >= intentadas else 0


if __name__ == "__main__":
    sys.exit(main())
