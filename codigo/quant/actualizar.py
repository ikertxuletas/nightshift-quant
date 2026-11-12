import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from quant import calidad, rutas, universo


def _fuentes_reales():
    from quant.fuentes import binance, dukascopy, yahoo
    return {
        "dukascopy": lambda inst, info, ctx: dukascopy.actualizar(inst, info, ctx["hasta"], ctx["datos"], ctx["sesion"],
                                                                   max_dias=ctx["max_dias"], limite=ctx.get("limite")),
        "binance": lambda inst, info, ctx: binance.actualizar(inst, info, ctx["hasta"], ctx["datos"], ctx["sesion"],
                                                               limite=ctx.get("limite")),
        "yahoo": lambda inst, info, ctx: yahoo.actualizar(inst, info, ctx["datos"]),
    }


def _argumentos(argv):
    p = argparse.ArgumentParser(description="Actualiza los precios del universo y el informe de calidad")
    p.add_argument("--raiz", default=str(rutas.RAIZ))
    p.add_argument("--solo", nargs="*")
    p.add_argument("--fuente", choices=sorted(universo.FUENTES))
    p.add_argument("--hasta")
    p.add_argument("--max-dias", type=int)
    p.add_argument("--max-minutos", type=float)
    p.add_argument("--refrescar-acciones", action="store_true")
    p.add_argument("--criticos", nargs="*", default=[])
    return p.parse_args(argv)


def main(argv=None, fuentes=None, sesion=None, hoy=None, reloj=time.monotonic):
    args = _argumentos(argv)
    raiz = Path(args.raiz)
    hoy = hoy or datetime.now(timezone.utc).date()
    try:
        hasta = date.fromisoformat(args.hasta) if args.hasta else hoy - timedelta(days=1)
        registro = raiz / "registro"
        registro.mkdir(parents=True, exist_ok=True)
    except (ValueError, OSError) as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    refresco_error = None
    if args.refrescar_acciones:
        try:
            universo.refrescar_acciones(raiz / "config")
        except Exception as e:
            refresco_error = f"{type(e).__name__}: {e}"

    try:
        uni = universo.cargar(raiz / "config")
    except Exception as e:
        salida = {
            "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hasta": hasta.isoformat(),
            "instrumentos": [],
            "errores": 1,
            "bloqueados": [],
            "fallo_general": f"{type(e).__name__}: {e}",
        }
        (registro / "actualizar_ultimo.json").write_text(
            json.dumps(salida, indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({k: salida[k] for k in ("hasta", "errores", "bloqueados")}, ensure_ascii=False))
        return 2

    fuentes = fuentes or _fuentes_reales()
    if sesion is None:
        import requests
        sesion = requests.Session()
    inicio = reloj()
    limite = inicio + args.max_minutos * 60 if args.max_minutos is not None else None
    contexto = {"hasta": hasta, "datos": raiz / "datos", "sesion": sesion, "max_dias": args.max_dias, "limite": limite}
    resumenes = []
    try:
        log = open(registro / f"actualizar_{hasta:%Y%m%d}.log", "a", encoding="utf-8")
    except OSError as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    with log:
        for instrumento, info in uni["instrumentos"].items():
            if (args.solo and instrumento not in args.solo) or (args.fuente and info["fuente"] != args.fuente):
                continue
            if args.max_minutos is not None and reloj() - inicio > args.max_minutos * 60:
                resumen = {"instrumento": instrumento, "error": None, "omitido": "tiempo agotado"}
            else:
                try:
                    resumen = fuentes[info["fuente"]](instrumento, info, contexto)
                except Exception as e:
                    resumen = {"instrumento": instrumento, "error": f"{type(e).__name__}: {e}"}
            log.write(json.dumps(resumen, ensure_ascii=False) + "\n")
            resumenes.append(resumen)
    procesados = [r["instrumento"] for r in resumenes if not r.get("omitido")]

    error_calidad = None
    bloqueados = []
    try:
        calidad.revisar_todo(uni, raiz / "datos", solo=procesados)
        bloqueados = [i for i in procesados if calidad.bloqueo(i, raiz / "datos")]
    except Exception as e:
        error_calidad = f"{type(e).__name__}: {e}"
        bloqueados = []

    salida = {
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hasta": hasta.isoformat(),
        "instrumentos": resumenes,
        "errores": sum(1 for r in resumenes if r.get("error")),
        "bloqueados": bloqueados,
    }
    fallos = [r["instrumento"] for r in resumenes if r.get("error")]
    salida["criticos_con_error"] = [i for i in fallos if i in args.criticos]
    if refresco_error:
        salida["refresco_acciones"] = refresco_error
        salida["errores"] += 1
    if error_calidad:
        salida["error_calidad"] = error_calidad
        salida["errores"] += 1
    (registro / "actualizar_ultimo.json").write_text(json.dumps(salida, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: salida[k] for k in ("hasta", "errores", "bloqueados")}, ensure_ascii=False))
    muchos = len(fallos) / max(1, len(procesados)) > 0.05
    return 1 if muchos or salida["criticos_con_error"] or error_calidad else 0


if __name__ == "__main__":
    sys.exit(main())
