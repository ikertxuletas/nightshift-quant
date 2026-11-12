"""Precomputes strategy-page figures, the Quant score and the why-it-wins analysis for every pass/doubtful result."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from quant import ranking, rutas
from quant.panel import ficha_stats, nota

_SP500 = {}


def _d1(raiz, instrumento):
    from quant import datos
    try:
        return datos.cargar(instrumento, "D1", Path(raiz) / "datos")
    except (datos.ErrorDatos, OSError, KeyError):
        return None


def analisis_de(raiz, ficha, instrumento, vecinos, hasta=None):
    from quant import costes as mcostes
    from quant import datos, universo
    from quant.investigacion import analisis
    raiz = Path(raiz)
    uni = universo.cargar(raiz / "config")
    barras = datos.cargar(instrumento, ficha["universo"]["plazo"], raiz / "datos", desde=universo.desde_de(instrumento, uni))
    costes = mcostes.costes_de(instrumento, mcostes.cargar(raiz / "config" / "costes.json"), clase=universo.clase_de(instrumento, uni))
    if hasta is not None:
        antes = barras["ts"] < __import__("numpy").datetime64(hasta)
        barras = {k: v[antes] for k, v in barras.items()}
    if str(raiz) not in _SP500:
        _SP500[str(raiz)] = _d1(raiz, "US500")
    return analisis.analizar(ficha, instrumento, barras, costes, _d1(raiz, instrumento), _SP500[str(raiz)], vecinos)


def vecinos_barrido(latest, r):
    base = json.loads(r["params_json"])
    salida = []
    for o in latest:
        if (o["family"], o["instrumento"], o["timeframe"], o["filter"]) != (r["family"], r["instrumento"], r["timeframe"], r["filter"]):
            continue
        p = json.loads(o["params_json"])
        if set(p) != set(base):
            continue
        distintos = [k for k in p if p[k] != base[k]]
        pf = ((json.loads(o["res"]).get("metricas") or {}).get("total") or {}).get("profit_factor")
        if len(distintos) == 1 and pf is not None:
            salida.append({"pf": round(pf, 2), "etiqueta": f"{distintos[0]} {p[distintos[0]]}"})
    return salida


def vecinos_lab(filas, ficha, exp_id):
    from quant.investigacion import laboratorio
    salida = []
    for o in filas:
        if o["id"] == exp_id or not o["ficha_json"]:
            continue
        try:
            otra = json.loads(o["ficha_json"])
        except ValueError:
            continue
        pf = _pf_lab(o) if o["entreno_json"] else None
        if pf is not None and laboratorio.cambios(ficha, otra) == 1:
            salida.append({"pf": round(pf, 2), "etiqueta": "; ".join(laboratorio._cambios_vistos(ficha, otra))[:80]})
    return salida


def _pf_lab(f):
    try:
        return (((json.loads(f["entreno_json"]) or {}).get("metricas") or {}).get("total") or {}).get("profit_factor")
    except (TypeError, ValueError):
        return None


def _orden_lab(con, filas):
    from quant.panel import hoy_datos
    pf = lambda f: _pf_lab(f) or 0
    mejores = {(hoy_datos.progreso_propia(con, e) or {}).get("mejor_id") for e in {f["estrategia"] for f in filas}}
    ultima = max((f["noche"] or "" for f in filas), default="")
    return sorted(filas, key=lambda f: (f["id"] not in mejores, f["veredicto"] not in ("pasa_validador", "ganadora"),
                                        f["noche"] != ultima, -pf(f)))


def precalcular_lab(con, raiz, minutos=15, hasta=None, reloj=time.monotonic):
    from quant.familias import propias
    raiz = Path(raiz)
    con.execute(ficha_stats.SCHEMA_ANALISIS)
    out = {"hechas": 0, "saltadas": 0, "pendientes": 0, "errores": []}
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_experimentos'").fetchone():
        return out
    filas = [f for f in con.execute("SELECT id, estrategia, noche, veredicto, ficha_json, entreno_json FROM lab_experimentos"
                                    " WHERE invalido IS NULL AND entreno_json IS NOT NULL").fetchall() if _pf_lab(f) is not None]
    hechos = {r[0] for r in con.execute("SELECT clave FROM panel_analisis WHERE clave LIKE 'e:%'")}
    fin = reloj() + minutos * 60 if hasta is None else min(reloj() + minutos * 60, hasta)
    por_estrategia = {}
    for f in _orden_lab(con, filas):
        if f"e:{f['id']}" in hechos:
            out["saltadas"] += 1
            continue
        if reloj() >= fin:
            out["pendientes"] += 1
            continue
        try:
            propia = propias.PROPIAS[f["estrategia"]]
            ficha = json.loads(f["ficha_json"])
            hermanas = por_estrategia.setdefault(f["estrategia"], [x for x in filas if x["estrategia"] == f["estrategia"]])
            a = analisis_de(raiz, ficha, propia.instrument, vecinos_lab(hermanas, ficha, f["id"]), hasta=propia.corte)
            ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with con:
                con.execute("INSERT OR REPLACE INTO panel_analisis VALUES (?, ?, ?)",
                            (f"e:{f['id']}", json.dumps(a, ensure_ascii=False), ahora))
            out["hechas"] += 1
        except Exception as e:
            out["errores"].append(f"#{f['id']}: {type(e).__name__}: {e}")
    return out


def _ficha(con, combo_id):
    return json.loads(con.execute("SELECT f.json FROM fichas f JOIN combinations c ON c.ficha_id = f.id"
                                  " WHERE c.id = ?", (combo_id,)).fetchone()[0])


def precalcular(con, raiz, minutos=45):
    raiz = Path(raiz)
    con.execute(ficha_stats.SCHEMA)
    con.execute(ficha_stats.SCHEMA_ANALISIS)
    hechos = {r[0] for r in con.execute("SELECT resultado_id FROM panel_stats")}
    out = {"hechas": 0, "saltadas": 0, "errores": []}
    latest = ranking.latest_results(con)
    elegidos = [r for r in latest if r["veredicto"] in ("pasa", "dudosa") and r["instrumento"] != "_cartera"]
    for r in elegidos:
        if r["resultado_id"] in hechos:
            out["saltadas"] += 1
            continue
        try:
            res, capital = ficha_stats.ejecutar(raiz, _ficha(con, r["id"]), r["instrumento"])
            stats = ficha_stats.estadisticas(res.ts, res.equity, res.operaciones, capital)
            puntos = nota.nota(json.loads(r["res"]).get("metricas") or {}, stats)
            with con:
                con.execute("INSERT OR REPLACE INTO panel_stats VALUES (?, ?, ?, ?)",
                            (r["resultado_id"], json.dumps(stats), json.dumps(puntos, ensure_ascii=False),
                             datetime.now(timezone.utc).isoformat(timespec="seconds")))
            out["hechas"] += 1
        except Exception as e:
            out["errores"].append(f"{r['instrumento']} #{r['resultado_id']}: {type(e).__name__}: {e}")
    hechos = {r[0] for r in con.execute("SELECT clave FROM panel_analisis")}
    an = {"hechas": 0, "saltadas": 0, "pendientes": 0, "errores": []}
    fin = time.monotonic() + minutos * 60
    for r in elegidos:
        clave = f"r:{r['resultado_id']}"
        if clave in hechos:
            an["saltadas"] += 1
            continue
        if time.monotonic() >= fin:
            an["pendientes"] += 1
            continue
        try:
            a = analisis_de(raiz, _ficha(con, r["id"]), r["instrumento"], vecinos_barrido(latest, r))
            with con:
                con.execute("INSERT OR REPLACE INTO panel_analisis VALUES (?, ?, ?)",
                            (clave, json.dumps(a, ensure_ascii=False), datetime.now(timezone.utc).isoformat(timespec="seconds")))
            an["hechas"] += 1
        except Exception as e:
            an["errores"].append(f"{r['instrumento']} #{r['resultado_id']}: {type(e).__name__}: {e}")
    out["analisis"] = an
    return out


def main(argv=None):
    from quant.investigacion import catalogo
    p = argparse.ArgumentParser(description="Precalcula cifras, Nota Quant y análisis para el panel")
    p.add_argument("--raiz", default=str(rutas.RAIZ))
    p.add_argument("--minutos", type=float, default=45)
    a = p.parse_args(argv)
    con = catalogo.abrir(Path(a.raiz) / "catalogo.db")
    try:
        print(json.dumps(precalcular(con, a.raiz, a.minutos), ensure_ascii=False))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
