import numpy as np

from quant import datos, rutas
from quant.demo.broker import Fill, Position
from quant.motor import _salida_intrabarra


class PaperBroker:
    name = "papel"

    def __init__(self, con, costes_of, bars_loader=None):
        self.con, self.costes_of = con, costes_of
        self.bars_loader = bars_loader or (lambda inst: datos.cargar(inst, "H1", rutas.DATOS))
        self.con.execute("""CREATE TABLE IF NOT EXISTS demo_paper_positions(
            strategy_id INTEGER PRIMARY KEY, instrument TEXT, side INTEGER, units REAL, entry_price REAL,
            stop REAL, target REAL, last_checked TEXT)""")

    def is_demo(self):
        return True

    def positions(self):
        rows = self.con.execute("SELECT strategy_id,instrument,side,units,entry_price,stop,target "
                                "FROM demo_paper_positions ORDER BY strategy_id")
        return [Position(*r) for r in rows]

    def _last(self, instrument):
        b = self.bars_loader(instrument)
        return float(b["close"][-1]), str(b["ts"][-1])

    def send(self, order):
        cst = self.costes_of(order.instrument)
        close, ts = self._last(order.instrument)
        price = close * (1 + order.side * cst.spread_pct / 2)
        self.con.execute("INSERT OR REPLACE INTO demo_paper_positions VALUES(?,?,?,?,?,?,?,?)",
                         (order.strategy_id, order.instrument, order.side, float(order.units), price,
                          order.stop, order.target, ts))
        return Fill(order.client_id, price, ts, float(order.units) * price * cst.comision_pct)

    def close(self, strategy_id, client_id):
        p = next(p for p in self.positions() if p.strategy_id == strategy_id)
        cst = self.costes_of(p.instrument)
        close, ts = self._last(p.instrument)
        price = close * (1 - p.side * cst.spread_pct / 2)
        self.con.execute("DELETE FROM demo_paper_positions WHERE strategy_id=?", (strategy_id,))
        return Fill(client_id, price, ts, p.units * price * cst.comision_pct)

    def advance(self, now):
        """Closes positions hit by stop/target on bars after last_checked.
        Fill.client_id is paper-<strategy_id>-<stop|objetivo>-<ts>."""
        fills = []
        for p in self.positions():
            try:
                b = self.bars_loader(p.instrument)
            except (datos.ErrorDatos, KeyError, OSError):
                continue
            last = self.con.execute("SELECT last_checked FROM demo_paper_positions WHERE strategy_id=?",
                                    (p.strategy_id,)).fetchone()[0]
            mask = b["ts"] > np.datetime64(last)
            if now is not None:
                mask &= b["ts"] <= np.datetime64(now)
            pos = {"q": p.side * p.units, "stop": p.stop, "objetivo": p.target}
            hit = None
            for i in np.flatnonzero(mask):
                price, reason = _salida_intrabarra(pos, b["open"][i], b["high"][i], b["low"][i])
                if price is not None:
                    hit = (float(price), reason, str(b["ts"][i]))
                    break
            if hit:
                price, reason, ts = hit
                self.con.execute("DELETE FROM demo_paper_positions WHERE strategy_id=?", (p.strategy_id,))
                fills.append(Fill(f"paper-{p.strategy_id}-{reason}-{ts}", price, ts,
                                  p.units * price * self.costes_of(p.instrument).comision_pct))
            elif mask.any():
                self.con.execute("UPDATE demo_paper_positions SET last_checked=? WHERE strategy_id=?",
                                 (str(b["ts"][mask][-1]), p.strategy_id))
        return fills
