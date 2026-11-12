"""Figures for a strategy page computed from a backtest: tested period, yearly and monthly returns, exposure."""
import numpy as np
import pandas as pd

SCHEMA = ("CREATE TABLE IF NOT EXISTS panel_stats (resultado_id INTEGER PRIMARY KEY, stats_json TEXT, nota_json TEXT,"
          " creado TEXT)")
SCHEMA_ANALISIS = "CREATE TABLE IF NOT EXISTS panel_analisis (clave TEXT PRIMARY KEY, json TEXT, creado TEXT)"


def ejecutar(raiz, ficha, instrument, hasta=None):
    """Backtest of a ficha on one instrument with the real data, costs and capital: (Resultado, capital)."""
    from quant import costes as mcostes
    from quant import criterios as mcriterios
    from quant import datos, motor, universo
    crit = mcriterios.cargar(raiz / "config")
    cfg = mcostes.cargar(raiz / "config" / "costes.json")
    uni = universo.cargar(raiz / "config")
    barras = datos.cargar(instrument, ficha["universo"]["plazo"], raiz / "datos", desde=universo.desde_de(instrument, uni))
    costes = mcostes.costes_de(instrument, cfg, clase=universo.clase_de(instrument, uni))
    if hasta is not None:
        antes = barras["ts"] < np.datetime64(hasta)
        barras = {k: v[antes] for k, v in barras.items()}
    return motor.backtest_serie(ficha, instrument, barras, costes, crit["capital"]), crit["capital"]


def estadisticas(ts, equity, operaciones, capital):
    idx = pd.to_datetime(np.asarray(ts))
    eq = pd.Series(np.asarray(equity, float), index=idx)
    anios = (idx[-1] - idx[0]).days / 365.25
    total = float(eq.iloc[-1] / capital - 1)
    cagr = float((1 + total) ** (1 / anios) - 1) if anios > 0 and total > -1 else None

    def rentabilidades(regla):
        cierres = eq.resample(regla).last()
        previos = cierres.shift(1)
        previos.iloc[0] = capital
        return cierres / previos - 1

    mensual = rentabilidades("ME")
    anual = rentabilidades("YE")
    meses = {}
    for fecha, v in mensual.items():
        meses.setdefault(str(fecha.year), [None] * 12)[fecha.month - 1] = round(float(v), 6)
    mejor, peor = mensual.idxmax(), mensual.idxmin()
    n = len(idx)
    dias = [(idx[o.i_salida] - idx[o.i_entrada]).total_seconds() / 86400 for o in operaciones]
    return {
        "desde": str(idx[0].date()), "hasta": str(idx[-1].date()), "anios": round(anios, 2),
        "total": round(total, 6), "cagr": None if cagr is None else round(cagr, 6),
        "drawdown": round(float(-(eq / eq.cummax() - 1).min()), 6),
        "meses": meses, "anual": {str(f.year): round(float(v), 6) for f, v in anual.items()},
        "mejor_mes": {"valor": round(float(mensual[mejor]), 6), "mes": mejor.strftime("%Y-%m")},
        "peor_mes": {"valor": round(float(mensual[peor]), 6), "mes": peor.strftime("%Y-%m")},
        "anios_positivos": int((anual > 0).sum()), "n_anios": int(len(anual)),
        "tiempo_mercado": sum(o.i_salida - o.i_entrada for o in operaciones) / n if n else 0.0,
        "duracion_media_dias": round(float(np.mean(dias)), 2) if dias else None,
    }
