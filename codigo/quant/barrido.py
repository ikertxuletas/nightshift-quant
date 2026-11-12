import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from quant import costes as mcostes
from quant import criterios as mcriterios
from quant import familias, rutas, universo
from quant.backtest import probar
from quant.familias import propias
from quant.demo import diario
from quant.investigacion.catalogo import _ahora, abrir
from quant.investigacion.memoria import QUNS_RUNNING_D3D_FULL_SCREEN, _estado_notificacion

_SCHEMA = """CREATE TABLE IF NOT EXISTS combinations(
    id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, family TEXT, params_json TEXT, instruments_json TEXT,
    timeframe TEXT, filter TEXT, origin TEXT, ficha_id INTEGER, data_until TEXT, created TEXT)"""


def ensure_schema(con):
    con.execute(_SCHEMA)
    con.commit()


def _key(combo):
    return json.dumps([combo.family, combo.params, list(combo.instruments), combo.timeframe, combo.filter],
                      sort_keys=True)


def fingerprint(combo, data_until):
    return hashlib.sha256((_key(combo) + data_until).encode()).hexdigest()


def _row_combo(row, origin=None):
    return familias.Combo(row["family"], json.loads(row["params_json"]), tuple(json.loads(row["instruments_json"])),
                          row["timeframe"], row["filter"], origin or row["origin"])


def _neighbors(con, tested):
    rows = con.execute("""SELECT c.*, r.json AS res FROM combinations c JOIN resultados r ON r.ficha_id = c.ficha_id
                          WHERE r.veredicto = 'dudosa'""").fetchall()
    scored = sorted(rows, key=lambda r: -json.loads(r["res"])["metricas"]["fuera"]["sharpe"])
    best = list(dict.fromkeys(r["id"] for r in scored))[:10]
    by_id = {r["id"]: r for r in scored}
    for rid in best:
        base = _row_combo(by_id[rid], "vecina")
        fam = familias.FAMILIES.get(base.family)
        if fam is None or propias.es_propia(fam.name):
            continue
        for name, values in fam.params.items():
            values = list(values)
            if name not in base.params or base.params[name] not in values:
                continue
            i = values.index(base.params[name])
            for j in (i - 1, i + 1):
                if 0 <= j < len(values):
                    cand = familias.Combo(base.family, {**base.params, name: values[j]}, base.instruments,
                                          base.timeframe, base.filter, "vecina")
                    if fam.coherent(cand.params) and _key(cand) not in tested:
                        yield cand


def queue(con, uni, data_until, demo_combo_ids):
    ensure_schema(con)
    fps = {r[0] for r in con.execute("SELECT fingerprint FROM combinations")}
    tested = {_key(_row_combo(r)) for r in con.execute("SELECT * FROM combinations")}
    counts = dict(con.execute("SELECT family, COUNT(*) FROM combinations GROUP BY family").fetchall())
    out, queued = [], set()

    def add(combo, by_fingerprint=False):
        k = _key(combo)
        if k in queued or (fingerprint(combo, data_until) in fps if by_fingerprint else k in tested):
            return
        queued.add(k)
        out.append(combo)

    for cid in demo_combo_ids:
        row = con.execute("SELECT * FROM combinations WHERE id = ? AND data_until < ?", (cid, data_until)).fetchone()
        if row:
            add(_row_combo(row), by_fingerprint=True)
    for fam in sorted(familias.FAMILIES.values(), key=lambda f: counts.get(f.name, 0)):
        if propias.es_propia(fam.name):
            continue
        for combo in familias.combos(fam, uni):
            add(combo)
    for combo in _neighbors(con, tested):
        add(combo)
    return out


def _store(con, combo, ficha, results, data_until):
    now = _ahora()
    with con:
        fid = con.execute("INSERT INTO fichas (doc_id, json, estado, motivo, creado) VALUES (NULL, ?, 'generada', NULL, ?)",
                          (json.dumps(ficha, ensure_ascii=False), now)).lastrowid
        for instrument, res in results.items():
            con.execute("INSERT INTO resultados (ficha_id, instrumento, veredicto, json, creado) VALUES (?, ?, ?, ?, ?)",
                        (fid, instrument, res["veredicto"], json.dumps(res, ensure_ascii=False), now))
        con.execute("""INSERT INTO combinations (fingerprint, family, params_json, instruments_json, timeframe, filter,
                       origin, ficha_id, data_until, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (fingerprint(combo, data_until), combo.family, json.dumps(combo.params, sort_keys=True),
                     json.dumps(list(combo.instruments)), combo.timeframe, combo.filter, combo.origin, fid,
                     data_until, now))


def _lower_priority():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)


def _load(raiz):
    return (mcriterios.cargar(raiz / "config"), mcostes.cargar(raiz / "config" / "costes.json"),
            universo.cargar(raiz / "config"))


def run(con, raiz, max_hours, max_combos, clock=time.monotonic, sleep=time.sleep,
        notification=_estado_notificacion, family=None, probar=probar):
    _lower_priority()
    raiz = Path(raiz)
    registro = raiz / "registro"
    data_until = json.loads((registro / "actualizar_ultimo.json").read_text(encoding="utf-8"))["hasta"]
    crit, costes, uni = _load(raiz)
    ensure_schema(con)
    diario.ensure_schema(con)
    demo_ids = [r[0] for r in con.execute("SELECT combo_id FROM demo_strategies WHERE status='active'")]
    pending = [c for c in queue(con, uni, data_until, demo_ids) if family in (None, c.family)]
    out = {"tested": 0, "pasa": 0, "dudosa": 0, "no_pasa": 0, "pendiente_datos": 0, "errores": 0, "paused_s": 0.0}
    start, stopped, budget = clock(), "interrumpida", max_hours * 3600
    try:
        for combo in pending:
            if max_combos is not None and out["tested"] >= max_combos:
                stopped = "max"
                break
            while notification() == QUNS_RUNNING_D3D_FULL_SCREEN and clock() - start < budget:
                sleep(60)
                out["paused_s"] += 60
            if clock() - start >= budget:
                stopped = "tope"
                break
            try:
                ficha = familias.to_ficha(combo)
                results = probar(ficha, raiz, crit, costes, uni)
                _store(con, combo, ficha, results, data_until)
            except Exception:
                out["errores"] += 1
                continue
            out["tested"] += 1
            for res in results.values():
                out[res["veredicto"]] = out.get(res["veredicto"], 0) + 1
        else:
            stopped = "vacia"
    finally:
        out["stopped"] = stopped
        registro.mkdir(parents=True, exist_ok=True)
        (registro / "barrido_ultimo.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Barrido de familias de estrategias")
    p.add_argument("--horas", type=float, default=30)
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--familia", default=None)
    p.add_argument("--raiz", default=str(rutas.RAIZ))
    a = p.parse_args(argv)
    raiz = Path(a.raiz)
    con = abrir(raiz / "catalogo.db")
    print(json.dumps(run(con, raiz, a.horas, a.max, family=a.familia)))
    try:
        from quant.panel import precalcular
        print(json.dumps(precalcular.precalcular(con, raiz), ensure_ascii=False))
    except Exception as e:
        print(f"precalculo del panel fallido: {type(e).__name__}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
