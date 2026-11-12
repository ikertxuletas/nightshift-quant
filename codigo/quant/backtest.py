import argparse
import json
import sys
from pathlib import Path

from quant import calidad
from quant import costes as mcostes
from quant import criterios as mcriterios
from quant import datos, ficha as mficha, rutas, universo, validacion


def probar(ficha, raiz, crit, config_costes, uni):
    barras, costes, resultado = {}, {}, {}
    for instrumento in ficha["universo"]["instrumentos"]:
        try:
            costes[instrumento] = mcostes.costes_de(instrumento, config_costes, clase=universo.clase_de(instrumento, uni))
            motivo_calidad = calidad.bloqueo(instrumento, raiz / "datos")
            if motivo_calidad:
                raise datos.ErrorDatos(f"calidad: {motivo_calidad}")
            barras[instrumento] = datos.cargar(instrumento, ficha["universo"]["plazo"], raiz / "datos",
                                               desde=universo.desde_de(instrumento, uni))
        except (datos.ErrorDatos, mcostes.ErrorCostes) as e:
            costes.pop(instrumento, None)
            resultado[instrumento] = {"veredicto": "pendiente_datos", "motivo": str(e)}
    if ficha["forma"] == "transversal" and resultado:
        resultado = {"_cartera": {"veredicto": "pendiente_datos",
                                  "motivo": "; ".join(r["motivo"] for r in resultado.values())}}
    elif barras:
        resultado.update(validacion.validar(ficha, barras, costes, crit))
    return resultado


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backtest y validación de una ficha")
    parser.add_argument("ficha")
    parser.add_argument("--raiz", default=str(rutas.RAIZ))
    args = parser.parse_args(argv)
    raiz = Path(args.raiz)
    try:
        crit = mcriterios.cargar(raiz / "config")
    except mcriterios.ErrorCriterios as e:
        print(f"PARADA: {e}", file=sys.stderr)
        return 3
    try:
        f = mficha.cargar(args.ficha)
    except mficha.ErrorFicha as e:
        print("\n".join(e.errores), file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError) as e:
        print(f"ficha ilegible: {e}", file=sys.stderr)
        return 2
    try:
        config_costes = mcostes.cargar(raiz / "config" / "costes.json")
    except (OSError, json.JSONDecodeError) as e:
        print(f"PARADA: costes ilegibles: {e}", file=sys.stderr)
        return 3
    try:
        uni = universo.cargar(raiz / "config")
    except (universo.ErrorUniverso, OSError, json.JSONDecodeError) as e:
        print(f"PARADA: universo ilegible: {e}", file=sys.stderr)
        return 3
    print(json.dumps(probar(f, raiz, crit, config_costes, uni), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
