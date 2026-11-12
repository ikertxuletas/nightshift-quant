"""Own-strategies lab: nightly agent experiments on the owner's strategies, with a held-out exam that fixes winners."""
import hashlib
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from quant import ficha as mficha
from quant import metricas, motor, validacion
from quant.investigacion import local, skills

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_experimentos (
  id INTEGER PRIMARY KEY, estrategia TEXT, noche TEXT, huella TEXT, ficha_json TEXT, motivo TEXT, cambios INTEGER,
  veredicto TEXT, invalido TEXT, entreno_json TEXT, examen_json TEXT, confirmacion_json TEXT, umbral_pf REAL,
  creado TEXT, UNIQUE(estrategia, huella));
CREATE TABLE IF NOT EXISTS lab_ganadoras (
  id INTEGER PRIMARY KEY, experimento_id INTEGER UNIQUE, estrategia TEXT, fijada TEXT, estado TEXT, umbral_pf REAL,
  examen_json TEXT, confirmacion_json TEXT, ayer_json TEXT, revisada TEXT, retirada TEXT, motivo_retiro TEXT);
CREATE TABLE IF NOT EXISTS lab_asesor (
  id INTEGER PRIMARY KEY, estrategia TEXT, fecha TEXT, informe TEXT, direccion TEXT, direccion_es TEXT,
  propuestas_json TEXT, creado TEXT);
"""
MAX_BYTES_MAPA = 20_000
_SECCIONES = ("universo", "entrada", "salida", "gestion", "horario")


def ensure_schema(con):
    con.executescript(_SCHEMA)
    # Invalid rows carry no fingerprint, so a corrected ficha with the same logic is not taken for a repeat.
    con.execute("UPDATE lab_experimentos SET huella = NULL WHERE veredicto = 'invalido' AND huella IS NOT NULL")
    con.commit()


def _canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def huella(ficha):
    return hashlib.sha256(_canon({k: ficha.get(k) for k in _SECCIONES}).encode()).hexdigest()


def _atomos(cond):
    if not cond:
        return []
    if "y" in cond or "o" in cond:
        return [a for c in cond.get("y", cond.get("o")) for a in _atomos(c)]
    if "no" in cond:
        return ["no:" + _canon(cond["no"])]
    return [_canon(cond)]


def _conectores(cond):
    """Shape of the y/o/no tree without its atomic conditions: an AND→OR rewrite changes it."""
    if not cond:
        return None
    for op in ("y", "o"):
        if op in cond:
            return {op: sorted(_canon(_conectores(c)) for c in cond[op] if any(k in c for k in ("y", "o", "no")))}
    if "no" in cond:
        return {"no": _conectores(cond["no"]) if any(k in cond["no"] for k in ("y", "o", "no")) else None}
    return None


def _hojas(x, ruta=()):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _hojas(v, ruta + (k,))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _hojas(v, ruta + (i,))
    else:
        yield ruta, x


def cambios(base, ficha):
    """Edit count vs the base: a tweaked, added or removed condition is 1; each differing gestion leaf is 1;
    horario sesiones, dias, zona and cierre are 1 each when they differ."""
    n = 0
    for seccion in ("entrada", "salida"):
        for lado in ("largo", "corto"):
            ca, cb = (base.get(seccion) or {}).get(lado), (ficha.get(seccion) or {}).get(lado)
            a, b = Counter(_atomos(ca)), Counter(_atomos(cb))
            n += max(sum((a - b).values()), sum((b - a).values()))
            n += bool(ca and cb and _canon(_conectores(ca)) != _canon(_conectores(cb)))
    ga, gb = dict(_hojas(base.get("gestion") or {})), dict(_hojas(ficha.get("gestion") or {}))
    n += sum(ga.get(k) != gb.get(k) for k in set(ga) | set(gb))
    ha, hb = base.get("horario") or {}, ficha.get("horario") or {}
    n += sum(ha.get(k) != hb.get(k) for k in ("sesiones", "dias", "zona", "cierre"))
    return n


def umbral_pf(cambios, examenes_previos):
    # Every exam taken is another lottery ticket: +0.1 at 20 exams, +0.2 at 60, +0.3 at 140, ...
    return min(1.0 + 0.05 * cambios, 1.3) + 0.1 * math.log2(1 + examenes_previos / 20)


def comprobar(base, ficha):
    if not isinstance(ficha, dict):
        return ["la ficha no es un objeto"]
    errores = list(mficha.errores(ficha))
    if errores:
        return errores
    if ficha["universo"]["instrumentos"] != base["universo"]["instrumentos"]:
        errores.append("no se puede cambiar el instrumento")
    if ficha["universo"]["plazo"] != base["universo"]["plazo"]:
        errores.append("no se puede cambiar el plazo")
    for campo in ("tipo", "forma"):
        if ficha.get(campo) != base.get(campo):
            errores.append(f"no se puede cambiar el {campo}")
    # Shrinking the position would shrink the drawdown and switch off the drawdown gates.
    if (ficha.get("gestion") or {}).get("tamano") != (base.get("gestion") or {}).get("tamano"):
        errores.append("no se puede cambiar el tamaño de la posición")
    return errores


def recortar(barras, hasta):
    antes = barras["ts"] < np.datetime64(hasta)
    return {k: v[antes] for k, v in barras.items()}


def metricas_desde(ficha, instrumento, barras, costes, capital, desde):
    """Backtest on every bar (indicators warm up), metrics only for the stretch from `desde` on."""
    inicio = int(np.searchsorted(barras["ts"], np.datetime64(desde)))
    if inicio >= len(barras["ts"]):
        return None
    res = motor.backtest_serie(ficha, instrumento, barras, costes, capital)
    return metricas.resumen(res.equity[inicio:], res.ts[inicio:],
                            [o for o in res.operaciones if o.i_entrada >= inicio])


def evaluar(ficha, barras, costes, crit, corte, confirmacion):
    inst = ficha["universo"]["instrumentos"][0]
    entreno = validacion.validar(ficha, {inst: recortar(barras[inst], corte)}, costes, crit)[inst]
    examen = conf = None
    if entreno.get("veredicto") == "pasa":
        examen = metricas_desde(ficha, inst, barras[inst], costes[inst], crit["capital"], corte)
        conf = metricas_desde(ficha, inst, barras[inst], costes[inst], crit["capital"], confirmacion)
    return {"entreno": entreno, "examen": examen, "confirmacion": conf}


def _num(x):
    return f"{x:.2f}".replace(".", ",")


def pasa_examen(examen, umbral, drawdown_max):
    if examen is None:
        return False, "sin datos en el examen"
    if not examen["operaciones"]:
        return False, "sin operaciones en el examen"
    if examen["operaciones"] < 30:
        return False, f"solo {examen['operaciones']} operaciones en el examen (mínimo 30)"
    if examen["rentabilidad"] <= 0:
        return False, f"rentabilidad {_num(examen['rentabilidad'] * 100)} % en el examen"
    if examen["drawdown"] > drawdown_max:
        return False, f"caída del {_num(examen['drawdown'] * 100)} % en el examen (máximo {_num(drawdown_max * 100)} %)"
    if examen["profit_factor"] < umbral:
        return False, f"profit factor {_num(examen['profit_factor'])} por debajo de {_num(umbral)}"
    return True, ""


_CONTEXTO_METRICAS = ("sharpe", "drawdown", "rentabilidad", "operaciones", "acierto", "profit_factor")


def _resumen_entreno(entreno_json):
    if not entreno_json:
        return {}
    r = json.loads(entreno_json)
    m = r.get("metricas") or {}
    return {"metricas": {t: {k: m[t][k] for k in _CONTEXTO_METRICAS if k in m.get(t, {})}
                         for t in ("total", "dentro", "fuera") if t in m},
            "criterios_fallados": [c["criterio"] for c in r.get("criterios") or [] if not c.get("cumple", True)]}


def _cambios_vistos(base, ficha):
    """Each edit vs the base as a short line, the same edits `cambios` counts."""
    out = []
    for seccion in ("entrada", "salida"):
        for lado in ("largo", "corto"):
            a = Counter(_atomos((base.get(seccion) or {}).get(lado)))
            b = Counter(_atomos((ficha.get(seccion) or {}).get(lado)))
            out += [f"{seccion}.{lado} +{x}" for x in b - a] + [f"{seccion}.{lado} -{x}" for x in a - b]
    ga, gb = dict(_hojas(base.get("gestion") or {})), dict(_hojas(ficha.get("gestion") or {}))
    out += [f"gestion.{'.'.join(map(str, k))}={gb.get(k)}" for k in set(ga) | set(gb) if ga.get(k) != gb.get(k)]
    ha, hb = base.get("horario") or {}, ficha.get("horario") or {}
    out += [f"horario.{k}={_canon(hb.get(k))}" for k in ("sesiones", "dias", "zona", "cierre") if ha.get(k) != hb.get(k)]
    return out


def _explorado(con, propia, base):
    """The detailed history is only the latest experiments; without the rest the agent re-proposes old ones."""
    fichas = [json.loads(f[0]) for f in con.execute("SELECT ficha_json FROM lab_experimentos WHERE estrategia = ?",
                                                    (propia.name,))]
    vistos = Counter(c for f in fichas for c in set(_cambios_vistos(base, f)))
    return (f"## Already explored (all {len(fichas)} experiments: each change vs the base and how many used it)\n"
            + ("\n".join(f"{n}x {c}" for c, n in vistos.most_common()) or "(none yet)") + "\n")


def direccion_vigente(con, estrategia):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_asesor'").fetchone():
        return None
    fila = con.execute("SELECT direccion FROM lab_asesor WHERE estrategia = ? ORDER BY fecha DESC, id DESC LIMIT 1",
                       (estrategia,)).fetchone()
    return fila[0] if fila else None


def mejores(con, estrategia, n=3):
    """Fichas of the best experiments by training profit factor; the unchanged base and invalid ones excluded."""
    filas = con.execute("SELECT ficha_json, entreno_json FROM lab_experimentos WHERE estrategia = ? AND"
                        " veredicto != 'invalido' AND entreno_json IS NOT NULL AND cambios != 0", (estrategia,)).fetchall()
    con_pf = [(((json.loads(f[1]).get("metricas") or {}).get("total") or {}).get("profit_factor"), f[0]) for f in filas]
    con_pf = [(pf, fj) for pf, fj in con_pf if isinstance(pf, (int, float)) and math.isfinite(pf)]
    return [json.loads(fj) for _, fj in sorted(con_pf, key=lambda x: -x[0])[:n]]


def mapa_de(con, propia, barras, costes_of):
    from quant.familias import propias as mpropias
    from quant.investigacion import mapa as mmapa
    b, c = barras(propia.instrument, propia.timeframe), costes_of(propia.instrument)
    sujetos = [("base", mpropias.ficha_base(propia.name))] + [
        (f"best variant {k}", f) for k, f in enumerate(mejores(con, propia.name), 1)]
    mapas = [(n, mmapa.mapa(f, propia.instrument, b, c, propia.corte)) for n, f in sujetos]
    for sin in ((), ("anio",)):
        for k in range(len(mapas), 0, -1):
            texto = "\n".join(mmapa.texto(n, m, sin) for n, m in mapas[:k])
            if len(texto.encode("utf-8")) <= MAX_BYTES_MAPA:
                return texto
    return texto


def contexto(con, propia, base, limite=40, mapa_texto=""):
    """What the agent may see: training-side results only. Exam metrics and winners never leave the database."""
    filas = con.execute("SELECT ficha_json, motivo, cambios, veredicto, invalido, entreno_json FROM lab_experimentos"
                        " WHERE estrategia = ? ORDER BY id DESC LIMIT ?", (propia.name, limite)).fetchall()
    historial = [{"ficha": json.loads(f["ficha_json"]), "motivo": f["motivo"], "cambios": f["cambios"],
                  "veredicto": "pasa_validador" if f["veredicto"] == "ganadora" else f["veredicto"],
                  **({"invalido": f["invalido"]} if f["invalido"] else {}), **_resumen_entreno(f["entreno_json"])}
                 for f in reversed(filas)]
    return (f"## Strategy\n{propia.name} (origin: {propia.origen})\n\n"
            f"## Base ficha\n{_canon(base)}\n\n"
            f"## Indicator catalog\n{skills.catalogo_indicadores()}\n"
            f"## History (oldest first, {len(historial)} experiments)\n"
            + ("\n".join(_canon(h) for h in historial) or "(none yet)") + "\n\n"
            + _explorado(con, propia, base)
            + (f"\n## Edge map (training data only)\n{mapa_texto}\n" if mapa_texto else "")
            + (f"\n## Direction from the weekly advisor (follow it)\n{d}\n"
               if (d := direccion_vigente(con, propia.name)) else ""))


def proponer(llamar, propia, contexto, n):
    prompt = f"{contexto}\nPropose up to {n} new experiments for {propia.name}."
    try:
        datos = local.json_de(llamar("sonnet", skills.system("laboratorio"), prompt, formato="json"))
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    lista = datos.get("experimentos") if isinstance(datos, dict) else None
    if not isinstance(lista, list):
        return [], "respuesta sin la lista 'experimentos'"
    validos = [{"motivo": x["motivo"], "ficha": x["ficha"]} for x in lista
               if isinstance(x, dict) and isinstance(x.get("motivo"), str) and isinstance(x.get("ficha"), dict)]
    descartados = len(lista) - len(validos)
    return validos[:n], (f"{descartados} experimentos mal formados descartados" if descartados else None)


def simular_ayer(ficha, instrumento, barras, costes, capital, antes=None):
    """Trades the ficha opened on the last full day before `antes` (YYYY-MM-DD); the last day with bars if None."""
    dias = barras["ts"].astype("datetime64[D]")
    if antes is not None:
        dias_previos = dias[dias < np.datetime64(antes)]
        ultimo = dias_previos[-1] if len(dias_previos) else None
    else:
        ultimo = dias[-1] if len(dias) else None
    if ultimo is None:
        return {"fecha": None, "operaciones": []}
    res = motor.backtest_serie(ficha, instrumento, barras, costes, capital)
    ops = [{"lado": o.lado, "entrada": str(barras["ts"][o.i_entrada])[:19], "salida": str(barras["ts"][o.i_salida])[:19],
            "precio_entrada": round(o.precio_entrada, 4), "precio_salida": round(o.precio_salida, 4),
            "pnl": round(o.pnl, 2), "motivo": o.motivo}
           for o in res.operaciones if dias[o.i_entrada] == ultimo]
    return {"fecha": str(ultimo), "operaciones": ops}


def _cargadores(raiz, bars_of, costes_of):
    from quant import costes as mcostes
    from quant import datos, universo
    uni = universo.cargar(raiz / "config") if (bars_of is None or costes_of is None) else None
    if bars_of is None:
        bars_of = lambda inst, tf: datos.cargar(inst, tf, raiz / "datos", desde=universo.desde_de(inst, uni))
    if costes_of is None:
        config = mcostes.cargar(raiz / "config" / "costes.json")
        costes_of = lambda inst: mcostes.costes_de(inst, config, clase=universo.clase_de(inst, uni))
    cache = {}

    def barras(inst, tf):
        if (inst, tf) not in cache:
            cache[(inst, tf)] = bars_of(inst, tf)
        return cache[(inst, tf)]
    return barras, costes_of


def _guardar_experimento(con, propia, noche, ahora, h, ficha, motivo, n_cambios, veredicto, invalido=None,
                         evaluado=None, umbral=None, commit=True):
    evaluado = evaluado or {}
    cur = con.execute(
        "INSERT INTO lab_experimentos (estrategia, noche, huella, ficha_json, motivo, cambios, veredicto, invalido,"
        " entreno_json, examen_json, confirmacion_json, umbral_pf, creado) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (propia.name, noche, h, _canon(ficha), motivo, n_cambios, veredicto, invalido,
         *(json.dumps(evaluado[k], ensure_ascii=False) if evaluado.get(k) is not None else None
           for k in ("entreno", "examen", "confirmacion")), umbral, ahora))
    if commit:
        con.commit()
    return cur.lastrowid


def _reexaminar(con, crit, barras, costes_of, ahora, noche, hasta, reloj, out):
    from quant.familias import propias as mpropias
    filas = con.execute("SELECT g.*, e.ficha_json FROM lab_ganadoras g JOIN lab_experimentos e"
                        " ON e.id = g.experimento_id WHERE g.estado = 'vigente'").fetchall()
    for n, g in enumerate(filas):
        if hasta is not None and reloj() > hasta:
            out["sin_tiempo"] += len(filas) - n
            out["errores"].append(f"sin tiempo para reexaminar {len(filas) - n} ganadoras")
            return
        try:
            propia = mpropias.PROPIAS[g["estrategia"]]
            ficha = json.loads(g["ficha_json"])
            b, c = barras(propia.instrument, propia.timeframe), costes_of(propia.instrument)
            examen = metricas_desde(ficha, propia.instrument, b, c, crit["capital"], propia.corte)
            conf = metricas_desde(ficha, propia.instrument, b, c, crit["capital"], propia.confirmacion)
            ok, motivo = pasa_examen(examen, g["umbral_pf"], crit["drawdown_max"])
            with con:
                con.execute("UPDATE lab_ganadoras SET examen_json=?, confirmacion_json=?, revisada=? WHERE id=?",
                            (json.dumps(examen), json.dumps(conf), ahora, g["id"]))
                if not ok:
                    con.execute("UPDATE lab_ganadoras SET estado='retirada', retirada=?, motivo_retiro=? WHERE id=?",
                                (ahora, motivo, g["id"]))
            out["reexaminadas"] += 1
            out["retiradas"] += not ok
        except Exception as e:
            out["errores"].append(f"ganadora {g['id']}: {type(e).__name__}: {e}")
            continue
        try:
            ayer = simular_ayer(ficha, propia.instrument, b, c, crit["capital"], noche)
            with con:
                con.execute("UPDATE lab_ganadoras SET ayer_json=? WHERE id=?", (json.dumps(ayer), g["id"]))
            out["simuladas"] += 1
        except Exception as e:
            out["errores"].append(f"simulación de la ganadora {g['id']}: {type(e).__name__}: {e}")


# The agent call alone can take up to 10 min (claude_cli timeout), plus 3 min to test at least one experiment.
MARGEN_AGENTE = 180 + 600
TANDAS_VACIAS_MAX = 3
# Each batch is a long Sonnet call: keep the count low so the weekly subscription limit lasts.
TANDAS_MAX = 15


def ejecutar(con, raiz, llamar, hasta=None, reloj=time.monotonic, max_experimentos=10, bars_of=None,
             costes_of=None, ahora=None, crit=None, reexaminar=True):
    """Nightly lab stage: re-exam and simulate winners first, then the agent's experiments while time lasts."""
    from quant import criterios as mcriterios
    from quant.familias import propias as mpropias
    ensure_schema(con)
    crit = crit or mcriterios.cargar(Path(raiz) / "config")
    barras, costes_of = _cargadores(Path(raiz) if raiz else None, bars_of, costes_of)
    ahora = (ahora or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    noche = ahora[:10]
    out = {"reexaminadas": 0, "retiradas": 0, "simuladas": 0, "propuestos": 0, "invalidos": 0, "repetidos": 0,
           "probados": 0, "ganadoras": 0, "sin_tiempo": 0, "errores": []}
    if reexaminar:
        _reexaminar(con, crit, barras, costes_of, ahora, noche, hasta, reloj, out)
    cupo = max(1, max_experimentos // max(1, len(mpropias.PROPIAS)))
    for propia in mpropias.PROPIAS.values():
        if hasta is not None and reloj() > hasta - MARGEN_AGENTE:
            out["sin_tiempo"] += cupo
            break
        base = mpropias.ficha_base(propia.name)
        try:
            mapa_texto = mapa_de(con, propia, barras, costes_of)
        except Exception as e:
            out["errores"].append(f"{propia.name}: mapa: {type(e).__name__}: {e}")
            mapa_texto = ""
        lista, error = proponer(llamar, propia, contexto(con, propia, base, mapa_texto=mapa_texto), cupo)
        if error:
            out["errores"].append(f"{propia.name}: {error}")
        out["propuestos"] += len(lista)
        if not con.execute("SELECT 1 FROM lab_experimentos WHERE estrategia = ? AND huella = ?",
                           (propia.name, huella(base))).fetchone():
            lista = [{"motivo": "Ficha base sin cambios: el punto de partida para comparar", "ficha": base}] + lista
        examenes = con.execute("SELECT COUNT(*) FROM lab_experimentos WHERE estrategia = ? AND examen_json IS NOT NULL",
                               (propia.name,)).fetchone()[0]
        for k, p in enumerate(lista):
            ficha = p["ficha"]
            try:
                motivos = comprobar(base, ficha)
                if motivos:
                    _guardar_experimento(con, propia, noche, ahora, None, ficha, p["motivo"], None, "invalido",
                                         invalido="; ".join(motivos))
                    out["invalidos"] += 1
                    continue
                h = huella(ficha)
                if con.execute("SELECT 1 FROM lab_experimentos WHERE estrategia = ? AND huella = ?",
                               (propia.name, h)).fetchone():
                    out["repetidos"] += 1
                    continue
                if hasta is not None and reloj() > hasta - 180:
                    out["sin_tiempo"] += len(lista) - k
                    break
                n_cambios = cambios(base, ficha)
                inst = propia.instrument
                evaluado = evaluar(ficha, {inst: barras(inst, propia.timeframe)}, {inst: costes_of(inst)}, crit,
                                   propia.corte, propia.confirmacion)
                out["probados"] += 1
                if evaluado["entreno"].get("veredicto") != "pasa":
                    _guardar_experimento(con, propia, noche, ahora, h, ficha, p["motivo"], n_cambios, "no_pasa",
                                         evaluado=evaluado)
                    continue
                umbral = umbral_pf(n_cambios, examenes)
                examenes += 1
                ok, _ = pasa_examen(evaluado["examen"], umbral, crit["drawdown_max"])
                with con:
                    eid = _guardar_experimento(con, propia, noche, ahora, h, ficha, p["motivo"], n_cambios,
                                               "ganadora" if ok else "pasa_validador", evaluado=evaluado,
                                               umbral=umbral, commit=False)
                    if ok:
                        con.execute("INSERT INTO lab_ganadoras (experimento_id, estrategia, fijada, estado, umbral_pf,"
                                    " examen_json, confirmacion_json, revisada) VALUES (?,?,?,'vigente',?,?,?,?)",
                                    (eid, propia.name, ahora, umbral, json.dumps(evaluado["examen"]),
                                     json.dumps(evaluado["confirmacion"]), ahora))
                out["ganadoras"] += ok
            except Exception as e:
                out["errores"].append(f"{propia.name}: {type(e).__name__}: {e}")
        if out["sin_tiempo"]:
            break
    out["errores_contenido"] = len(out["errores"])
    return out


def tandas(con, raiz, llamar, hasta, reloj=time.monotonic, **kw):
    """Last nightly stage: batch after batch until `hasta`; one failing batch does not stop the rest."""
    from quant.investigacion import claude_cli
    total = {"tandas": 0, "fallidas": 0, "errores": []}
    vacias = 0
    while reloj() <= hasta - MARGEN_AGENTE:
        try:
            out = ejecutar(con, raiz, llamar, hasta=hasta, reloj=reloj, reexaminar=total["tandas"] == 0, **kw)
        except claude_cli.CorteClaude as e:
            total["corte"] = e.motivo
            break
        except Exception as e:
            out = {"errores": [f"tanda {total['tandas'] + 1}: {type(e).__name__}: {e}"]}
            total["fallidas"] += 1
        total["tandas"] += 1
        for clave, valor in out.items():
            if clave == "errores":
                total["errores"] += valor
            elif clave != "errores_contenido" and isinstance(valor, int):
                total[clave] = total.get(clave, 0) + valor
        vacias = 0 if out.get("probados") else vacias + 1
        if vacias >= TANDAS_VACIAS_MAX:
            total["parado"] = f"{TANDAS_VACIAS_MAX} tandas seguidas sin probar nada"
            break
        if out.get("sin_tiempo"):
            break
        if total["tandas"] >= TANDAS_MAX:
            total["parado"] = f"tope de {TANDAS_MAX} tandas por noche"
            break
    total["errores_contenido"] = len(total["errores"])
    return total


def main(argv=None):
    import argparse
    from quant import rutas
    from quant.investigacion import catalogo, claude_cli
    p = argparse.ArgumentParser(description="Laboratorio de estrategias propias")
    p.add_argument("--max", type=int, default=10)
    p.add_argument("--raiz", default=str(rutas.RAIZ))
    a = p.parse_args(argv)
    raiz = Path(a.raiz)
    con = catalogo.abrir(raiz / "catalogo.db")
    try:
        out = ejecutar(con, raiz, claude_cli.chat, max_experimentos=a.max)
    finally:
        con.close()
    (raiz / "registro" / "laboratorio_ultimo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                               encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
