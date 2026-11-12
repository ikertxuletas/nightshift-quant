import json
from datetime import date, timedelta

from quant import familias, ranking, rutas, universo
from quant.demo import diario

CONTROL = "control_comprar_mantener"
_TIER = {"pasa": 0, "dudosa": 1, "no_pasa": 2}
_LABEL = {"pasa": "aprobada", "dudosa": "dudosa", "no_pasa": "en_prueba"}
_LABEL_TIER = {"aprobada": 0, "dudosa": 1, "en_prueba": 2}
_MINUTE_SOURCES = ("dukascopy", "binance")
_KEY_SQL = "SELECT family, params_json, instruments_json, timeframe, filter FROM combinations WHERE id=?"


def _ficha(con, combo_id):
    row = con.execute("SELECT f.json FROM combinations c JOIN fichas f ON f.id=c.ficha_id WHERE c.id=?",
                      (combo_id,)).fetchone()
    return json.loads(row[0]) if row else None


def _key(con, combo_id):
    row = con.execute(_KEY_SQL, (combo_id,)).fetchone()
    return tuple(row) if row else None


def effective_ficha(ficha, label, cfg):
    if label == "control":
        return ficha
    g = dict(ficha.get("gestion") or {})
    if not g.get("stop") and not g.get("trailing"):
        g["stop"] = {"tipo": "atr", "valor": cfg["stop_atr"][0]}
    g.setdefault("tamano", {"tipo": "riesgo", "valor": cfg["risk_pct"]})
    return {**ficha, "gestion": g}


def _score(r):
    if r["verdict"] == "no_pasa":
        return len(r["failed"])
    return -(r["sharpe_oos"] if r["sharpe_oos"] is not None else float("-inf"))


def _control_entries(con, rows, old_controls):
    fam = familias.FAMILIES[CONTROL]
    out = []
    for inst in fam.markets:
        row = next((r for r in rows if r["family"] == CONTROL and r["instrument"] == inst), None)
        ficha = _ficha(con, row["combo_id"]) if row else None
        if ficha is None:
            ficha = familias.to_ficha(familias.Combo(CONTROL, {}, (inst,), "D1", "sin_filtro", "control"))
        old = old_controls.get(inst)
        out.append({"combo_id": row["combo_id"] if row else None, "family": CONTROL, "instrument": inst,
                    "timeframe": "D1", "label": "control", "ficha": ficha, "existing_id": old["id"] if old else None})
    return out


def select(con, cfg, uni=None):
    diario.ensure_schema(con)
    uni = uni or universo.cargar(rutas.CONFIG)
    rows = ranking.rows(con, limit=100000, uni=uni)
    act = diario.active(con)
    chosen = _control_entries(con, rows, {r["instrument"]: r for r in act if r["label"] == "control"})
    fam_count, inst_count, taken = {}, {}, set()

    def take(entry):
        fam_count[entry["family"]] = fam_count.get(entry["family"], 0) + 1
        inst_count[entry["instrument"]] = inst_count.get(entry["instrument"], 0) + 1
        taken.add((entry["key"], entry["instrument"]))
        chosen.append(entry)

    def fits(r):
        return (fam_count.get(r["family"], 0) < cfg["max_per_family"]
                and inst_count.get(r["instrument"], 0) < cfg["max_per_instrument"]
                and (r["key"], r["instrument"]) not in taken)

    now = {(r["key"], r["instrument"]): r for r in rows}
    keys = {s["id"]: _key(con, s["combo_id"]) for s in act if s["label"] != "control"}
    taken.update((keys[s["id"]], s["instrument"]) for s in act if s["label"] != "control")
    for s in act:
        if s["label"] == "control":
            continue
        cur = now.get((keys[s["id"]], s["instrument"]))
        if cur is None or cur["verdict"] not in _TIER or _TIER[cur["verdict"]] <= _LABEL_TIER[s["label"]]:
            ficha = json.loads(s["ficha_json"])
            label = _LABEL[cur["verdict"]] if cur and cur["verdict"] in _TIER else s["label"]
            take({"combo_id": s["combo_id"], "key": keys[s["id"]], "family": cur["family"] if cur else ficha["id"].rsplit("-", 1)[0],
                  "instrument": s["instrument"], "timeframe": s["timeframe"], "label": label,
                  "ficha": ficha, "existing_id": s["id"]})

    barred = set()
    for old in con.execute("SELECT combo_id, instrument, retired FROM demo_strategies "
                           "WHERE status='retired' AND combo_id IS NOT NULL AND label!='control'"):
        key = _key(con, old["combo_id"])
        until = con.execute("SELECT MAX(data_until) FROM combinations WHERE family=? AND params_json=? AND "
                            "instruments_json=? AND timeframe=? AND filter=?", key).fetchone() if key else None
        limit = date.fromisoformat(old["retired"][:10]) + timedelta(days=90)
        if not until or not until[0] or date.fromisoformat(until[0][:10]) < limit:
            barred.add((key, old["instrument"]))
    cands = [r for r in rows if r["family"] != CONTROL and r["verdict"] in _TIER
             and uni["instrumentos"].get(r["instrument"], {}).get("fuente") in _MINUTE_SOURCES
             and (r["key"], r["instrument"]) not in barred]
    cands.sort(key=lambda r: (r["suspicious"], _TIER[r["verdict"]], _score(r)))
    n_new = cfg["n_demo"] - sum(c["label"] != "control" for c in chosen)
    for r in cands:
        if n_new <= 0:
            break
        if not fits(r):
            continue
        ficha = _ficha(con, r["combo_id"])
        if not ficha or ficha.get("forma") != "serie_temporal":
            continue
        label = _LABEL[r["verdict"]]
        take({"combo_id": r["combo_id"], "key": r["key"], "family": r["family"], "instrument": r["instrument"],
              "timeframe": r["timeframe"], "label": label, "ficha": effective_ficha(ficha, label, cfg),
              "existing_id": None})
        n_new -= 1
    return chosen


def apply(con, chosen, now, cfg):
    diario.ensure_schema(con)
    keep = {c["existing_id"] for c in chosen if c["existing_id"]}
    stamp = now.isoformat(timespec="seconds")
    with con:
        for s in diario.active(con):
            if s["id"] not in keep:
                con.execute("UPDATE demo_strategies SET status='retired', retired=?, retire_reason_es=? WHERE id=?",
                            (stamp, "Su última prueba empeoró el veredicto y ya no cumple para seguir en la demo.", s["id"]))
                con.execute("INSERT INTO demo_events(ts,kind,strategy_id,detail_es) VALUES(?,?,?,?)",
                            (stamp, "retire", s["id"], "Retirada: su última prueba empeoró el veredicto."))
        for c in chosen:
            if c["existing_id"]:
                if c["label"] != "control":
                    con.execute("UPDATE demo_strategies SET label=? WHERE id=?", (c["label"], c["existing_id"]))
                continue
            sid = con.execute(
                "INSERT INTO demo_strategies(combo_id,ficha_json,instrument,timeframe,broker,label,status,capital,added)"
                " VALUES(?,?,?,?,?,?,'active',0,?)",
                (c["combo_id"], json.dumps(c["ficha"], ensure_ascii=False), c["instrument"], c["timeframe"],
                 "papel", c["label"], stamp)).lastrowid
            con.execute("INSERT INTO demo_events(ts,kind,strategy_id,detail_es) VALUES(?,?,?,?)",
                        (stamp, "enter", sid, f"Entra en la demo ({c['label']}): {c['family']} en {c['instrument']}."))
        n = con.execute("SELECT COUNT(*) FROM demo_strategies WHERE status='active'").fetchone()[0]
        if n:
            con.execute("UPDATE demo_strategies SET capital=? WHERE status='active'", (cfg["capital"] / n,))
