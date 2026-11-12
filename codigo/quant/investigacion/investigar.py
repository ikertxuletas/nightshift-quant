"""Proceso completo de investigacion: explorar, leer, formalizar, criticar y validar."""
import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from quant import calidad, costes, criterios, datos, ficha as mficha, rutas, universo, validacion
from quant.investigacion import agentes, catalogo, claude_cli, explorar, memoria
from quant.investigacion.memoria import QUNS_RUNNING_D3D_FULL_SCREEN, _estado_notificacion

ESPERA_SEGUNDOS = 60
MAX_ESPERAS = 10
RUTA_CARGA = Path(os.environ.get("QUANT_CARGA", Path.home() / ".quant" / "carga.py"))
INACTIVIDAD_MINUTOS_DEFECTO = 15.0


_CARGA = None


def _cargar_carga():
    """carga.py se importa una sola vez; devuelve (modulo, aviso)."""
    global _CARGA
    if _CARGA is not None:
        return _CARGA
    if not RUTA_CARGA.exists():
        _CARGA = (None, f"no existe {RUTA_CARGA}, el PC se considera libre")
        return _CARGA
    try:
        spec = importlib.util.spec_from_file_location("carga", RUTA_CARGA)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        _CARGA = (modulo, "")
    except Exception as e:
        _CARGA = (None, f"no se pudo cargar {RUTA_CARGA}: {type(e).__name__}: {e}")
    return _CARGA


def _inactividad_minutos_config(config):
    """cargar_config no valida tipos; un valor no numerico no debe dejar pasar la noche por accidente."""
    try:
        return float(config.get("inactividad_minutos", INACTIVIDAD_MINUTOS_DEFECTO))
    except (TypeError, ValueError):
        return INACTIVIDAD_MINUTOS_DEFECTO


def _ocupado_defecto(raiz=None):
    """Solo frena por juego o pantalla completa: la GPU cargada suele ser el propio Ollama.
    Un juego en pantalla completa exclusiva D3D (mando, sin teclado/raton) siempre cuenta como
    ocupado. El resto de pantalla completa (una ventana, un video) solo cuenta como ocupado si
    hay alguien delante (poco inactivo): una ventana olvidada con nadie usando el teclado o el
    raton no debe parar la noche."""
    modulo = _cargar_carga()[0]
    if modulo is None:
        return ""
    try:
        if _estado_notificacion() == QUNS_RUNNING_D3D_FULL_SCREEN:
            return "juego o pantalla completa"
        if not modulo._pantalla_completa():
            return ""
        config = memoria.cargar_config(raiz or rutas.RAIZ)
        if memoria.inactivo_minutos() < _inactividad_minutos_config(config):
            return "juego o pantalla completa"
        return ""
    except Exception:
        return ""


def _fuentes_con_error(raiz):
    ruta = raiz / "registro" / "explorar_ultimo.json"
    if not ruta.exists():
        return 0
    try:
        return int(json.loads(ruta.read_text(encoding="utf-8")).get("errores", 0))
    except (OSError, ValueError, TypeError):
        return 0


def _esperar_libre(ocupado, dormir):
    motivo = ocupado()
    intentos = 0
    while motivo and intentos < MAX_ESPERAS:
        dormir(ESPERA_SEGUNDOS)
        intentos += 1
        motivo = ocupado()
    return motivo


def _construir_antes(ocupado, dormir, estado):
    def antes():
        motivo = _esperar_libre(ocupado, dormir)
        if motivo:
            estado["motivo"] = motivo
        return motivo
    return antes


def validar_ficha(ficha, raiz):
    """Valida una ficha ya correcta contra los datos de la raiz, sin catalogo: instrumento -> detalle."""
    raiz = Path(raiz)
    crit = criterios.cargar(raiz / "config")
    config_costes = costes.cargar(raiz / "config" / "costes.json")
    uni = universo.cargar(raiz / "config")
    barras, costes_map, resultado = {}, {}, {}
    for instrumento in ficha["universo"]["instrumentos"]:
        try:
            costes_map[instrumento] = costes.costes_de(instrumento, config_costes,
                                                       clase=universo.clase_de(instrumento, uni))
            motivo_calidad = calidad.bloqueo(instrumento, raiz / "datos")
            if motivo_calidad:
                raise datos.ErrorDatos(f"calidad: {motivo_calidad}")
            barras[instrumento] = datos.cargar(instrumento, ficha["universo"]["plazo"], raiz / "datos",
                                               desde=universo.desde_de(instrumento, uni))
        except (datos.ErrorDatos, costes.ErrorCostes) as e:
            costes_map.pop(instrumento, None)
            resultado[instrumento] = {"veredicto": "pendiente_datos", "motivo": str(e)}

    if ficha["forma"] == "transversal" and resultado:
        return {"_cartera": {"veredicto": "pendiente_datos",
                             "motivo": "; ".join(r["motivo"] for r in resultado.values())}}
    if barras:
        resultado.update(validacion.validar(ficha, barras, costes_map, crit))
    return resultado


def _validar_fichas_nuevas(con, raiz, hasta, reloj):
    """Una ficha que no pasa el esquema es un fallo de contenido: el modelo la aprobo pero no vale."""
    validadas, errores = 0, 0
    for fila in catalogo.fichas(con, "aprobada"):
        if hasta is not None and reloj() >= hasta:
            break
        if con.execute("SELECT 1 FROM resultados WHERE ficha_id = ?", (fila["id"],)).fetchone():
            continue
        f = json.loads(fila["json"])
        lista_errores = mficha.errores(f)
        if lista_errores:
            catalogo.guardar_resultado(con, fila["id"], "", "ficha_invalida",
                                       {"veredicto": "ficha_invalida", "errores": lista_errores})
            errores += 1
            continue

        resultado = validar_ficha(f, raiz)
        for instrumento, detalle in resultado.items():
            catalogo.guardar_resultado(con, fila["id"], instrumento, detalle["veredicto"], detalle)
        catalogo.marcar(con, fila["doc_id"], "validado")
        validadas += 1
    return {"validadas": validadas, "errores": errores, "errores_contenido": errores}


def main(argv=None, sesion=None, llamar=None, reloj=time.monotonic, ocupado=None):
    parser = argparse.ArgumentParser(description="Proceso completo de investigacion")
    parser.add_argument("--raiz", default=str(rutas.RAIZ))
    parser.add_argument("--max-minutos", type=int, default=180)
    parser.add_argument("--sin-explorar", action="store_true")
    parser.add_argument("--limite-lectura", type=int, default=None)
    parser.add_argument("--limite-fichas", type=int, default=None)
    args = parser.parse_args(argv)
    raiz = Path(args.raiz)
    (raiz / "registro").mkdir(parents=True, exist_ok=True)
    ocupado_defecto = ocupado is None or ocupado is _ocupado_defecto
    ocupado = ocupado or (lambda: _ocupado_defecto(raiz))
    llamar = llamar or claude_cli.chat
    hasta = reloj() + args.max_minutos * 60

    log = []
    resumen = {"explorar": None, "fuentes_con_error": 0, "lectura": None, "fichas": None, "validadas": 0,
               "errores": 0, "errores_contenido": 0, "errores_infra": 0, "omitido": ""}
    corte = None
    if ocupado_defecto:
        aviso = _cargar_carga()[1]
        if aviso:
            log.append({"etapa": "ocupado", "aviso": aviso})

    try:
        con = catalogo.abrir(raiz / "catalogo.db")

        if not args.sin_explorar:
            codigo = explorar.main(["--raiz", str(raiz)], sesion=sesion)
            resumen["explorar"] = codigo
            resumen["fuentes_con_error"] = _fuentes_con_error(raiz)
            log.append({"etapa": "explorar", "codigo": codigo,
                        "fuentes_con_error": resumen["fuentes_con_error"]})
            if codigo:
                # explorar solo devuelve distinto de 0 si fallaron todas las fuentes: es infra, no contenido.
                resumen["errores"] += 1
                resumen["errores_infra"] += 1

        estado = {}
        antes = _construir_antes(ocupado, time.sleep, estado)

        r_lectura = agentes.procesar_lectura(con, raiz / "documentos", limite=args.limite_lectura, llamar=llamar,
                                             reloj=reloj, hasta=hasta, antes=antes)
        resumen["lectura"] = r_lectura
        log.append({"etapa": "lectura", **r_lectura})
        resumen["errores"] += r_lectura.get("errores", 0)
        resumen["errores_contenido"] += r_lectura.get("errores_contenido", 0)
        resumen["errores_infra"] += r_lectura.get("errores_infra", 0)

        r_fichas = agentes.procesar_fichas(con, limite=args.limite_fichas, llamar=llamar,
                                           hasta=hasta, reloj=reloj, antes=antes)
        resumen["fichas"] = r_fichas
        log.append({"etapa": "fichas", **r_fichas})
        resumen["errores"] += r_fichas.get("errores", 0)
        resumen["errores_contenido"] += r_fichas.get("errores_contenido", 0)
        resumen["errores_infra"] += r_fichas.get("errores_infra", 0)

        if estado.get("motivo"):
            resumen["omitido"] = "pc ocupado"
            log.append({"etapa": "ocupado", "motivo": estado["motivo"]})

        r_val = _validar_fichas_nuevas(con, raiz, hasta, reloj)
        log.append({"etapa": "validacion", **r_val})
        resumen["errores"] += r_val.get("errores", 0)
        resumen["errores_contenido"] += r_val.get("errores_contenido", 0)
        resumen["validadas"] = r_val.get("validadas", 0)
    except claude_cli.CorteClaude as e:
        corte = e
        resumen["corte"] = e.motivo
        log.append({"etapa": "corte", "motivo": e.motivo})
    except Exception as e:
        detalle = f"{type(e).__name__}: {e}"
        resumen["errores"] += 1
        resumen["errores_infra"] += 1
        resumen["fallo"] = detalle
        log.append({"etapa": "proceso", "error": detalle})

    hoy = datetime.now(timezone.utc).strftime("%Y%m%d")
    with open(raiz / "registro" / f"investigar_{hoy}.log", "a", encoding="utf-8") as fichero:
        for linea in log:
            fichero.write(json.dumps(linea, ensure_ascii=False) + "\n")
    (raiz / "registro" / "investigar_ultimo.json").write_text(
        json.dumps(resumen, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False))
    if corte is not None:
        raise corte
    # Los errores de contenido (el modelo dio algo invalido) son ruido normal de investigacion:
    # solo un fallo de infraestructura (Ollama caido, disco, todas las fuentes caidas...) tira la etapa.
    return 1 if resumen["errores_infra"] else 0


if __name__ == "__main__":
    sys.exit(main())
