def ensure_schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS demo_strategies(
        id INTEGER PRIMARY KEY, combo_id INTEGER, ficha_json TEXT, instrument TEXT, timeframe TEXT, broker TEXT,
        label TEXT, status TEXT, capital REAL, added TEXT, retired TEXT, retire_reason_es TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS demo_orders(
        id INTEGER PRIMARY KEY, client_id TEXT UNIQUE, strategy_id INTEGER, kind TEXT, side INTEGER, units REAL,
        price_req REAL, price_fill REAL, price_ref REAL, stop REAL, target REAL, status TEXT, created TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS demo_trades(
        id INTEGER PRIMARY KEY, strategy_id INTEGER, side INTEGER, entry_ts TEXT, exit_ts TEXT, entry REAL,
        exit REAL, units REAL, pnl REAL, costs REAL, reason TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS demo_events(
        id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, strategy_id INTEGER, detail_es TEXT)""")
    con.execute("CREATE TABLE IF NOT EXISTS demo_state(key TEXT PRIMARY KEY, value TEXT)")


def active(con):
    ensure_schema(con)
    return con.execute("SELECT * FROM demo_strategies WHERE status='active' ORDER BY id").fetchall()


def active_instruments(con):
    ensure_schema(con)
    rows = con.execute("SELECT DISTINCT instrument FROM demo_strategies WHERE status='active' ORDER BY instrument")
    return [r[0] for r in rows]


def open_positions(con):
    """Journal view: strategy_id -> (side, units) when the strategy's latest filled order is an open."""
    ensure_schema(con)
    rows = con.execute("""SELECT o.strategy_id, o.side, o.units FROM demo_orders o
        WHERE o.status='filled' AND o.kind='open' AND o.id=(SELECT MAX(id) FROM demo_orders
        WHERE strategy_id=o.strategy_id AND status='filled')""")
    return {r[0]: (r[1], r[2]) for r in rows}
