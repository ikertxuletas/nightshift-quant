import argparse
import json
import sqlite3
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np

from quant import actualizar, costes as mcostes, datos, indicadores, motor, rutas, universo
from quant.barrido import _lower_priority
from quant.demo import config, diario, seguridad, seleccion
from quant.demo.broker import Order
from quant.demo.papel import PaperBroker

_STEP = {"H4": timedelta(hours=4), "D1": timedelta(days=1)}
_NIGHT = (time(1, 30), time(6, 30))


class _Skip(Exception):
    pass


def _naive(t):
    return t.astimezone(timezone.utc).replace(tzinfo=None) if t.tzinfo else t


def _event(con, now, kind, sid, text):
    con.execute("INSERT INTO demo_events(ts,kind,strategy_id,detail_es) VALUES(?,?,?,?)",
                (now.isoformat(timespec="seconds"), kind, sid, text))


def _closed_bars(bars, tf, now):
    n = len(bars["ts"])
    if n and bars["ts"][-1] > np.datetime64(now - _STEP[tf]):
        n -= 1
    return {k: v[:n] for k, v in bars.items()}


def _record_exit(con, costes_of, pos, fill, reason, ref):
    cp = costes_of(pos.instrument).comision_pct
    entry = con.execute("SELECT created, price_ref FROM demo_orders WHERE strategy_id=? AND kind='open' "
                        "AND status='filled' ORDER BY id DESC LIMIT 1", (pos.strategy_id,)).fetchone()
    friction = pos.units * (abs(pos.entry_price - entry[1]) + abs(fill.price - ref)) if entry and entry[1] else 0.0
    commissions = pos.units * pos.entry_price * cp + fill.costs
    pnl = pos.side * pos.units * (fill.price - pos.entry_price) - commissions
    con.execute("INSERT INTO demo_trades(strategy_id,side,entry_ts,exit_ts,entry,exit,units,pnl,costs,reason) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (pos.strategy_id, pos.side, entry[0] if entry else None, fill.ts, pos.entry_price, fill.price,
                 pos.units, pnl, commissions + friction, reason))


def _close(con, broker, costes_of, pos, client_id, ts, ref, reason):
    cur = con.execute("INSERT OR IGNORE INTO demo_orders(client_id,strategy_id,kind,side,units,price_ref,status,created)"
                      " VALUES(?,?,?,?,?,?,?,?)", (client_id, pos.strategy_id, "close", -pos.side, pos.units, ref,
                                                   "sent", ts))
    if not cur.rowcount:
        return False
    try:
        fill = broker.close(pos.strategy_id, client_id)
    except Exception as e:
        con.execute("DELETE FROM demo_orders WHERE client_id=?", (client_id,))
        raise _Skip(f"estrategia {pos.strategy_id} ({pos.instrument}): no se pudo cerrar ({e})")
    con.execute("UPDATE demo_orders SET status='filled', price_fill=?, created=? WHERE client_id=?",
                (fill.price, fill.ts, client_id))
    _record_exit(con, costes_of, pos, fill, reason, ref)
    return True


def _default_costes_of(raiz):
    cfg, uni = mcostes.cargar(raiz / "config" / "costes.json"), universo.cargar(raiz / "config")
    return lambda inst: mcostes.costes_de(inst, cfg, clase=universo.clase_de(inst, uni))


def run_pass(con, raiz, broker, now, cfg, bars_of=None, costes_of=None, update=None):
    local = now.astimezone() if now.tzinfo else now
    raiz, now = Path(raiz), _naive(now)
    diario.ensure_schema(con)
    bars_of = bars_of or (lambda inst, tf: datos.cargar(inst, tf, raiz / "datos"))
    costes_of = costes_of or _default_costes_of(raiz)
    update = update or (lambda insts: actualizar.main(["--raiz", str(raiz), "--solo", *insts]))
    out = {"opened": 0, "closed": 0, "skipped": [], "warnings": []}
    insts = diario.active_instruments(con)
    # the night's price stage writes the same parquet files
    if insts and not _NIGHT[0] <= local.time() <= _NIGHT[1]:
        try:
            update(insts)
        except Exception as e:
            out["warnings"].append(f"No se pudieron actualizar los precios: {e}")

    seguridad.require_demo(broker)
    before = {p.strategy_id: p for p in broker.positions()}
    for fill in broker.advance(now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)):
        sid = int(fill.client_id.split("-")[1])
        pos = before[sid]
        cur = con.execute("INSERT OR IGNORE INTO demo_orders(client_id,strategy_id,kind,side,units,price_fill,price_ref,"
                          "status,created) VALUES(?,?,?,?,?,?,?,?,?)",
                          (fill.client_id, sid, "close", -pos.side, pos.units, fill.price, fill.price, "filled", fill.ts))
        if cur.rowcount:
            _record_exit(con, costes_of, pos, fill, fill.client_id.split("-")[2], fill.price)
            out["closed"] += 1

    active = {s["id"]: s for s in diario.active(con)}
    for pos in broker.positions():
        if pos.strategy_id in active:
            continue
        ts = now.isoformat(timespec="seconds")
        opened_cid = con.execute("SELECT client_id FROM demo_orders WHERE strategy_id=? AND kind='open' AND "
                                 "status='filled' ORDER BY id DESC LIMIT 1", (pos.strategy_id,)).fetchone()
        cid = f"{opened_cid[0]}-retired" if opened_cid else f"q9-{pos.strategy_id}-orphan-retired"
        try:
            ref = float(bars_of(pos.instrument, "D1")["close"][-1])
        except Exception:
            ref = pos.entry_price
        try:
            out["closed"] += _close(con, broker, costes_of, pos, cid, ts, ref, "retirada")
        except _Skip as e:
            out["skipped"].append(str(e))

    blocked = None
    diffs = seguridad.reconcile(con, broker)
    if diffs:
        blocked = "descuadre diario/bróker"
        _event(con, now, "mismatch", None, " | ".join(diffs))
    if seguridad.stop_file_present(raiz):
        blocked = "archivo PARAR"
        _event(con, now, "stop_file", None, "Archivo PARAR presente: no se abre nada, solo se cierra.")

    held = {p.strategy_id: p for p in broker.positions()}
    for s in active.values():
        label = f"estrategia {s['id']} ({s['instrument']})"
        try:
            bars = _closed_bars(bars_of(s["instrument"], s["timeframe"]), s["timeframe"], now)
            costes = costes_of(s["instrument"])
        except (datos.ErrorDatos, mcostes.ErrorCostes, KeyError, OSError) as e:
            out["skipped"].append(f"{label}: sin datos o costes ({e})")
            continue
        if len(bars["ts"]) < 2:
            out["skipped"].append(f"{label}: sin velas cerradas")
            continue
        bar_ts = np.datetime_as_string(bars["ts"][-1], unit="s")
        state_key = f"last_bar:{s['id']}"
        last = con.execute("SELECT value FROM demo_state WHERE key=?", (state_key,)).fetchone()
        if last and last[0] >= bar_ts:
            continue
        decided = lambda: con.execute("INSERT OR REPLACE INTO demo_state VALUES(?, ?)", (state_key, bar_ts))
        try:
            ficha = json.loads(s["ficha_json"])
            res = motor.backtest_serie(ficha, s["instrument"], bars, costes, s["capital"])
            pend = res.pending
            target = pend["enter"] or (0 if pend["exit"] else (res.open_position["side"] if res.open_position else 0))
            gestion = seleccion.effective_ficha(ficha, s["label"], cfg)["gestion"]
        except Exception as e:
            out["skipped"].append(f"{label}: ficha o datos no válidos ({type(e).__name__}: {e})")
            continue
        ref = float(bars["close"][-1])
        pos = held.get(s["id"])
        if pos and pos.side != target:
            try:
                out["closed"] += _close(con, broker, costes_of, pos, seguridad.client_id(s["id"], bar_ts, "close"),
                                        bar_ts, ref, "senal")
            except _Skip as e:
                out["skipped"].append(str(e))
                continue
            pos = None
        if not target or pos:
            decided()
            continue
        if blocked:
            out["skipped"].append(f"{label}: apertura bloqueada ({blocked})")
            continue
        try:
            if not gestion.get("tamano") and not (gestion.get("stop") or gestion.get("trailing")):
                gestion = {**gestion, "tamano": {"tipo": "unidades", "valor": float(s["capital"]) / ref}}
            atr = indicadores.calcular(f"ATR({motor.PERIODO_ATR})", bars, {})[-1]
            opened, _ = motor._abrir(target, ref, len(bars["ts"]) - 1, atr, gestion, costes, float(s["capital"]))
        except Exception as e:
            out["skipped"].append(f"{label}: no se pudo dimensionar ({type(e).__name__}: {e})")
            continue
        if opened is None:
            out["skipped"].append(f"{label}: tamaño no calculable")
            continue
        cid = seguridad.client_id(s["id"], bar_ts, "open")
        units = abs(opened["q"])
        ins = con.execute("INSERT OR IGNORE INTO demo_orders(client_id,strategy_id,kind,side,units,price_req,price_ref,"
                          "stop,target,status,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (cid, s["id"], "open", target, units, ref, ref, opened["stop"], opened["objetivo"], "sent",
                           bar_ts))
        if not ins.rowcount:
            decided()
            continue
        try:
            fill = broker.send(Order(cid, s["id"], s["instrument"], target, units, opened["stop"], opened["objetivo"]))
        except Exception as e:
            con.execute("DELETE FROM demo_orders WHERE client_id=?", (cid,))
            out["skipped"].append(f"{label}: no se pudo enviar la orden ({e})")
            continue
        con.execute("UPDATE demo_orders SET status='filled', price_fill=?, created=? WHERE client_id=?",
                    (fill.price, fill.ts, cid))
        _event(con, now, "enter", s["id"],
               f"Abre {'largo' if target > 0 else 'corto'} en {s['instrument']}: {units:.4g} unidades a {fill.price:.4f}.")
        decided()
        out["opened"] += 1

    for w in seguridad.portfolio_warnings(con, cfg, now.date().isoformat()):
        out["warnings"].append(w)
        _event(con, now, "warn", None, w)
    con.commit()
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Pasada de la demo en papel")
    p.add_argument("--raiz", default=str(rutas.RAIZ))
    raiz = Path(p.parse_args(argv).raiz)
    _lower_priority()
    con = sqlite3.connect(raiz / "catalogo.db", timeout=30)
    con.row_factory = sqlite3.Row
    costes_of = _default_costes_of(raiz)
    broker = PaperBroker(con, costes_of, lambda inst: datos.cargar(inst, "H1", raiz / "datos"))
    ruta_cfg = raiz / "config" / "demo.json"
    cfg = config.cargar(ruta_cfg if ruta_cfg.exists() else Path(__file__).parents[3] / "config" / "demo.json")
    print(json.dumps(run_pass(con, raiz, broker, datetime.now(timezone.utc), cfg, costes_of=costes_of),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
