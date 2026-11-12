from pathlib import Path

from quant.demo import diario


def stop_file_present(raiz):
    return (Path(raiz) / "PARAR").exists()


def client_id(strategy_id, bar_ts, kind):
    return f"q9-{strategy_id}-{bar_ts}-{kind}"


def require_demo(broker):
    if not broker.is_demo():
        raise RuntimeError("cuenta no demo")


def reconcile(con, broker):
    mine = diario.open_positions(con)
    theirs = {p.strategy_id: (p.side, p.units) for p in broker.positions()}
    out = []
    for sid in sorted(mine.keys() | theirs.keys()):
        if sid not in theirs:
            out.append(f"Estrategia {sid}: el diario tiene posición abierta pero el bróker no.")
        elif sid not in mine:
            out.append(f"Estrategia {sid}: el bróker tiene posición abierta que no está en el diario.")
        elif mine[sid][0] != theirs[sid][0] or abs(mine[sid][1] - theirs[sid][1]) > 1e-9:
            out.append(f"Estrategia {sid}: lado o tamaño distintos entre diario {mine[sid]} y bróker {theirs[sid]}.")
    return out


def portfolio_warnings(con, cfg, today):
    diario.ensure_schema(con)
    out = []
    capital = con.execute("SELECT COALESCE(SUM(capital),0) FROM demo_strategies WHERE status='active'").fetchone()[0]
    pnl = con.execute("SELECT COALESCE(SUM(pnl),0) FROM demo_trades WHERE substr(exit_ts,1,10)=?", (today,)).fetchone()[0]
    if capital and -pnl / capital * 100 > cfg["daily_loss_ref_pct"]:
        out.append(f"Pérdida del día {pnl:.2f} supera la referencia del {cfg['daily_loss_ref_pct']}% del capital.")
    n = len(diario.open_positions(con))
    if n > cfg["max_positions_ref"]:
        out.append(f"{n} posiciones abiertas superan la referencia de {cfg['max_positions_ref']}.")
    return out
