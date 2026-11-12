import json

from quant import rutas, universo
from quant.familias import propias

_ORDER = {"pasa": 0, "dudosa": 1, "no_pasa": 2, "pendiente_datos": 3}


def _key(r):
    return (r["family"], r["params_json"], r["instruments_json"], r["timeframe"], r["filter"])


def latest_results(con):
    sql = """SELECT c.id, c.family, c.params_json, c.instruments_json, c.timeframe, c.filter, c.data_until,
                    r.id AS resultado_id, r.instrumento, r.veredicto, r.json AS res
             FROM combinations c JOIN resultados r ON r.ficha_id = c.ficha_id"""
    best = {}
    for r in con.execute(sql):
        if propias.es_propia(r["family"]):
            continue
        key = _key(r)
        if key not in best or r["data_until"] > best[key]["data_until"]:
            best[key] = r
    return list(best.values())


def _class(r, uni):
    if r["instrumento"] == "_cartera":
        classes = {universo.clase_de(i, uni) for i in json.loads(r["instruments_json"])}
        return "cartera:" + classes.pop() if len(classes) == 1 and None not in classes else "cartera"
    return universo.clase_de(r["instrumento"], uni)


def _group_key(r, cls):
    return (r["family"], r["params_json"], r["timeframe"], r["filter"], cls)


def _groups(latest, uni):
    classes = [_class(r, uni) for r in latest]
    groups = {}
    for r, cls in zip(latest, classes):
        g = groups.setdefault(_group_key(r, cls), [0, 0])
        g[0] += r["veredicto"] in ("pasa", "dudosa")
        g[1] += 1
    return classes, groups


def consistency(con, combo_id, uni=None):
    uni = uni or universo.cargar(rutas.CONFIG)
    latest = latest_results(con)
    classes, groups = _groups(latest, uni)
    for r, cls in zip(latest, classes):
        if r["id"] == combo_id:
            return tuple(groups[_group_key(r, cls)])
    return (0, 0)


def rows(con, market=None, family=None, verdict=None, limit=500, uni=None, latest=None):
    uni = uni or universo.cargar(rutas.CONFIG)
    latest = latest_results(con) if latest is None else latest
    classes, groups = _groups(latest, uni)
    out = []
    for r, cls in zip(latest, classes):
        if (family and r["family"] != family) or (verdict and r["veredicto"] != verdict):
            continue
        if market and cls != market and not (cls or "").endswith(":" + market):
            continue
        res = json.loads(r["res"])
        m = res.get("metricas", {})
        total = m.get("total", {})
        ok, n = groups[_group_key(r, cls)]
        out.append({
            "combo_id": r["id"], "resultado_id": r["resultado_id"], "key": _key(r), "family": r["family"], "params": json.loads(r["params_json"]),
            "instrument": r["instrumento"] if r["instrumento"] != "_cartera" else cls,
            "timeframe": r["timeframe"], "verdict": r["veredicto"],
            "sharpe_oos": m.get("fuera", {}).get("sharpe"), "drawdown": total.get("drawdown"),
            "cagr": total.get("cagr"), "trades": total.get("operaciones"),
            "return_total": total.get("rentabilidad"), "win_rate": total.get("acierto"),
            "profit_factor": total.get("profit_factor"),
            "failed": [c["criterio"] for c in res.get("criterios", []) if not c["cumple"]],
            "consistency": f"{ok}/{n}", "suspicious": ok == 1 and n >= 3 and r["veredicto"] in ("pasa", "dudosa"),
        })
    out.sort(key=lambda x: (_ORDER.get(x["verdict"], 9), -(x["sharpe_oos"] if x["sharpe_oos"] is not None else float("-inf"))))
    return out[:limit]


def family_stats(con, latest=None):
    stats = {}
    for r in (latest_results(con) if latest is None else latest):
        if r["veredicto"] not in ("pasa", "dudosa", "no_pasa"):
            continue
        s = stats.setdefault(r["family"], {"family": r["family"], "tested": 0, "pasa": 0, "dudosa": 0})
        s["tested"] += 1
        if r["veredicto"] in ("pasa", "dudosa"):
            s[r["veredicto"]] += 1
    return [{**s, "expected_by_chance": round(0.05 * s["tested"], 1)} for s in sorted(stats.values(), key=lambda s: s["family"])]
