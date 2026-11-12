import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from quant import actualizar, datos, motor, rutas
from quant.demo import config as demo_config, desvio, diario as demo, pasada, seleccion
from quant.investigacion import canario, catalogo, claude_cli, contratos, copia, investigar, laboratorio, mentor, \
    relator, tiempos

ETAPAS = contratos.ETAPAS
RESERVA = {"precios": 30, "investigar": 110, "canario": 10, "demo": 10, "laboratorio": 30, "relator": 15,
           "mentor": 30, "copia": 5}
CON_MODELO = {"investigar", "canario", "laboratorio", "relator", "mentor"}
MINIMO = 2
MAXIMA_NOCHE = timedelta(hours=4)
MOTIVOS_CORTE = {"tope": "tope de llamadas alcanzado", "limite": "limite de uso de la suscripcion"}
MOTIVOS_COMPROBACION = {"login": "sesion de claude caducada", "limite": MOTIVOS_CORTE["limite"],
                        "fallo": "claude no responde"}


def _leer_json(ruta):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _leer_memoria(raiz, fecha):
    ruta = Path(raiz) / "registro" / f"memoria_{fecha}.log"
    if not ruta.exists():
        return []
    lineas = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        try:
            lineas.append(json.loads(linea))
        except ValueError:
            continue
    return lineas


def _etapa_precios(ctx):
    argv = ["--raiz", str(ctx["raiz"]), "--max-minutos", str(ctx["minutos"])]
    con = catalogo.abrir(ctx["raiz"] / "catalogo.db")
    try:
        criticos = demo.active_instruments(con)
    finally:
        con.close()
    if criticos:
        argv += ["--criticos", *criticos]
    codigo = actualizar.main(argv, reloj=ctx["reloj"])
    return {"codigo": codigo, **_leer_json(ctx["raiz"] / "registro" / "actualizar_ultimo.json")}


def _etapa_investigar(ctx):
    argv = ["--raiz", str(ctx["raiz"]), "--max-minutos", str(ctx["minutos"])]
    if ctx["args"].sin_explorar:
        argv.append("--sin-explorar")
    for nombre in ("limite_lectura", "limite_fichas"):
        valor = getattr(ctx["args"], nombre)
        if valor is not None:
            argv += ["--" + nombre.replace("_", "-"), str(valor)]
    extra = {"llamar": ctx["llamar"]} if ctx["llamar"] else {}
    codigo = investigar.main(argv, ocupado=ctx["ocupado"], reloj=ctx["reloj"], **extra)
    return {"codigo": codigo, **_leer_json(ctx["raiz"] / "registro" / "investigar_ultimo.json")}


def _etapa_relator(ctx):
    extra = {"llamar": ctx["llamar"]} if ctx["llamar"] else {}
    resumen = relator.procesar_relatos(ctx["con"], hasta=ctx["hasta"], reloj=ctx["reloj"], antes=ctx["antes"], **extra)
    return {**resumen, "informe": str(relator.informe(ctx["con"], ctx["raiz"], ctx["fecha"]))}


def _etapa_mentor(ctx):
    llamar = ctx["llamar"] or claude_cli.chat
    return mentor.ciclo(ctx["con"], ctx["raiz"], desde=ctx["desde"], llamar=llamar, hasta=ctx["hasta"],
                        reloj=ctx["reloj"])


def _etapa_copia(ctx):
    return copia.copiar(ctx["raiz"])


def _etapa_canario(ctx):
    extra = {"llamar": ctx["llamar"]} if ctx["llamar"] else {}
    return canario.ejecutar(ctx["raiz"], hasta=ctx["hasta"], reloj=ctx["reloj"], **extra)


def _backtest_fractions(s, ctx):
    raiz = ctx["raiz"]
    ficha = json.loads(s["ficha_json"])
    costes = ctx.get("costes_of") or pasada._default_costes_of(raiz)
    bars = (ctx.get("bars_of") or (lambda inst, tf: datos.cargar(inst, tf, raiz / "datos")))(s["instrument"], s["timeframe"])
    antes = bars["ts"] < np.datetime64(s["added"][:10])
    bars = {k: v[antes] for k, v in bars.items()}
    if len(bars["ts"]) < 2 or not s["capital"]:
        raise datos.ErrorDatos("sin barras anteriores a su entrada en la demo")
    res = motor.backtest_serie(ficha, s["instrument"], bars, costes(s["instrument"]), s["capital"])
    return [op.pnl / s["capital"] for op in res.operaciones]


def _etapa_demo(ctx):
    con, raiz = ctx["con"], ctx["raiz"]
    local = ctx.get("ahora") or datetime.now()
    ahora = local.astimezone(timezone.utc).replace(tzinfo=None)
    cfg = demo_config.cargar_de(raiz)
    stamp = ahora.isoformat(timespec="seconds")
    try:
        costes_of = ctx.get("costes_of") or pasada._default_costes_of(raiz)
        error_costes = None
    except Exception as e:
        costes_of, error_costes = None, e
    evaluated = retired = 0
    skipped = []
    for s in demo.active(con):
        try:
            if error_costes:
                raise error_costes
            fractions = _backtest_fractions(s, {**ctx, "costes_of": costes_of})
            costes = costes_of(s["instrument"])
        except Exception as e:
            skipped.append(f"estrategia {s['id']} ({s['instrument']}): {type(e).__name__}: {e}")
            continue
        evaluated += 1
        out = desvio.evaluate(con, s["id"], cfg, ahora, fractions, costes)
        if out["decision"] == "retire" and s["label"] != "control":
            with con:
                con.execute("UPDATE demo_strategies SET status='retired', retired=?, retire_reason_es=? WHERE id=?",
                            (stamp, out["reason_es"], s["id"]))
                con.execute("INSERT INTO demo_events(ts,kind,strategy_id,detail_es) VALUES(?,?,?,?)",
                            (stamp, "retire", s["id"], out["reason_es"]))
            retired += 1
    rotated = local.weekday() == 0
    if rotated:
        seleccion.apply(con, seleccion.select(con, cfg), ahora, cfg)
    out = {"evaluated": evaluated, "retired": retired, "rotated": rotated, "skipped": skipped}
    if skipped and not evaluated:
        out["aviso"] = "Ninguna estrategia de la demo se pudo evaluar esta noche: faltan datos o costes."
    return out


def _etapa_laboratorio(ctx):
    from quant.panel import precalcular
    out = laboratorio.tandas(ctx["con"], ctx["raiz"], ctx["llamar"] or claude_cli.chat, hasta=ctx["hasta"],
                             reloj=ctx["reloj"])
    try:
        panel = precalcular.precalcular_lab(ctx["con"], ctx["raiz"], 15, ctx["hasta"], reloj=ctx["reloj"])
    except Exception as e:
        panel = {"error": f"{type(e).__name__}: {e}"}
    return {**out, "panel": panel} if isinstance(out, dict) else out


ETAPAS_REALES = {"precios": _etapa_precios, "investigar": _etapa_investigar, "canario": _etapa_canario,
                 "demo": _etapa_demo, "laboratorio": _etapa_laboratorio, "relator": _etapa_relator,
                 "mentor": _etapa_mentor, "copia": _etapa_copia}


def _fin(ahora, texto):
    hora, minuto = (int(x) for x in texto.split(":"))
    fin = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    return fin if fin > ahora else fin + timedelta(days=1)


def _reserva_posterior(nombre):
    siguientes = ETAPAS[ETAPAS.index(nombre) + 1:]
    return sum(RESERVA[s] for s in siguientes)


def _escribir_parte(raiz, parte):
    parte.pop("contrato", None)
    fuera = contratos.validar_parte(parte)
    if fuera:
        parte["contrato"] = fuera
    carpeta = raiz / "informes"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"parte_{parte['fecha']}.json"
    temporal = destino.with_suffix(".json.tmp")
    temporal.write_text(json.dumps(parte, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(temporal, destino)


def main(argv=None, ahora=None, reloj=time.monotonic, dormir=time.sleep, llamar=None, ocupado=None, etapas=None):
    parser = argparse.ArgumentParser(description="Noche de Quant: precios, investigacion, relator, mentor y copia")
    parser.add_argument("--raiz", default=str(rutas.RAIZ))
    parser.add_argument("--fin", default="06:00")
    parser.add_argument("--sin-precios", action="store_true")
    parser.add_argument("--sin-explorar", action="store_true")
    parser.add_argument("--limite-lectura", type=int, default=None)
    parser.add_argument("--limite-fichas", type=int, default=None)
    parser.add_argument("--forzar", action="store_true")
    parser.add_argument("--fecha")
    args = parser.parse_args(argv)
    equipo, elegido = os.environ.get("COMPUTERNAME", ""), os.environ.get("QUANT_EQUIPO")
    if elegido and equipo != elegido and not args.forzar:
        print(json.dumps({"omitido": f"equipo {equipo} no es {elegido}"}))
        return 2
    ahora = ahora or datetime.now()
    # astimezone sobre un datetime naive lo interpreta como hora local del sistema y lo pasa a UTC.
    desde = ahora.astimezone(timezone.utc).isoformat(timespec="seconds")
    raiz = Path(args.raiz)
    fecha = args.fecha or tiempos.fecha_local(ahora)
    inicio = reloj()
    # The task trigger does not follow daylight saving: the night starts at 01:00 in winter, and the review
    # (start + 4h15) and the task's 4h30 limit come an hour earlier too. Never run past start + 4h.
    fin_previsto = min(_fin(ahora, args.fin), ahora + MAXIMA_NOCHE)
    segundos_totales = (fin_previsto - ahora).total_seconds()
    etapas = etapas or ETAPAS_REALES
    ocupado = ocupado or investigar._ocupado_defecto
    estado = {}
    antes = investigar._construir_antes(ocupado, dormir, estado)
    con = catalogo.abrir(raiz / "catalogo.db")
    restauradas = []
    try:
        restauradas = mentor.restaurar_huerfanas(con, raiz / "skills")
    except Exception:
        pass
    parte = {"fecha": fecha, "inicio": ahora.isoformat(timespec="seconds"), "desde": desde,
             "fin_previsto": fin_previsto.isoformat(timespec="seconds"),
             "fin_real": None, "equipo": equipo, "etapas": {}, "catalogo": {}, "corte": False, "errores": 0}
    if restauradas:
        parte["restauradas"] = restauradas
    (raiz / "registro").mkdir(parents=True, exist_ok=True)
    log = open(raiz / "registro" / f"noche_{fecha}.log", "a", encoding="utf-8")
    claude_cli.reiniciar(_leer_json(raiz / "config" / "agentes.json").get("_tope_llamadas_noche"))
    parte["claude"] = claude_cli.comprobar()
    sin_modelo = None if parte["claude"].get("sesion") else MOTIVOS_COMPROBACION.get(
        parte["claude"].get("causa"), "sesion de claude caducada")
    if sin_modelo:
        parte["errores"] += 1
    try:
        for nombre in ETAPAS:
            estado.pop("motivo", None)
            transcurrido = reloj() - inicio
            restante = segundos_totales - transcurrido
            disponible = min(RESERVA[nombre] * 60, restante - _reserva_posterior(nombre) * 60)
            if nombre == "copia":
                disponible = max(min(RESERVA[nombre] * 60, restante), MINIMO * 60)
            if nombre == "laboratorio":
                # Last stage: it gets whatever is left of the night, not just its reserve.
                disponible = restante
            minutos = int(disponible // 60)
            marca = reloj()
            if nombre == "precios" and args.sin_precios:
                resultado = {"omitido": "sin precios"}
            elif nombre in CON_MODELO and sin_modelo:
                resultado = {"omitido": sin_modelo}
            elif minutos < MINIMO:
                resultado = {"omitido": "sin tiempo"}
                parte["corte"] = True
            else:
                hasta_absoluto = marca + minutos * 60
                try:
                    ctx = {"raiz": raiz, "fecha": fecha, "hasta": hasta_absoluto, "minutos": minutos,
                           "llamar": llamar, "ocupado": ocupado, "antes": antes, "args": args,
                           "con": con, "reloj": reloj, "desde": desde}
                    resultado = etapas[nombre](ctx)
                except claude_cli.CorteClaude as e:
                    sin_modelo = MOTIVOS_CORTE.get(e.motivo, f"corte de claude: {e.motivo}")
                    resultado = {"omitido": sin_modelo}
                except BaseException as e:
                    if isinstance(e, KeyboardInterrupt):
                        raise
                    resultado = {"error": f"{type(e).__name__}: {e}"}
            if contratos.hay_fallo(resultado):
                parte["errores"] += 1
            entrada = {"inicio": round(marca - inicio), "segundos": round(reloj() - marca), "resultado": resultado}
            if estado.get("motivo"):
                entrada["ocupado"] = estado["motivo"]
            parte["etapas"][nombre] = entrada
            parte["catalogo"] = catalogo.resumen(con)
            log.write(json.dumps({"etapa": nombre, **entrada}, ensure_ascii=False) + "\n")
            log.flush()
            _escribir_parte(raiz, parte)
        parte["fin_real"] = (ahora + timedelta(seconds=reloj() - inicio)).isoformat(timespec="seconds")
        parte["memoria"] = _leer_memoria(raiz, fecha)
        parte["claude"]["llamadas"] = claude_cli.llamadas()
        if contratos.validar_parte(parte):
            parte["errores"] += 1
        _escribir_parte(raiz, parte)
        try:
            contratos.guardar_real(raiz, "parte", parte)
        except Exception:
            pass
    finally:
        log.close()
        con.close()
    print(json.dumps({"fecha": fecha, "errores": parte["errores"], "corte": parte["corte"]}, ensure_ascii=False))
    return 1 if parte["errores"] else 0


if __name__ == "__main__":
    sys.exit(main())
