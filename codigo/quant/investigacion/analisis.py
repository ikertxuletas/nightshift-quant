"""Why a strategy wins or loses: six figure groups and the hour x weekday edge map from one backtest."""
import math
from collections import Counter
from copy import deepcopy

import numpy as np
import pandas as pd

from quant import motor
from quant.investigacion import mapa

_DIAS = "LMXJVSD"


def _pf(rs):
    g, p = sum(x for x in rs if x > 0), -sum(x for x in rs if x < 0)
    return round(g / p, 2) if p else None


def _prob_suerte(R):
    R = np.asarray(R, float)
    if len(R) < 2 or R.std(ddof=1) == 0:
        return None
    t = R.mean() / (R.std(ddof=1) / math.sqrt(len(R)))
    return round(0.5 * math.erfc(t / math.sqrt(2)), 3)


def _celda(ts64):
    t = pd.Timestamp(ts64).tz_localize("UTC").tz_convert("Europe/Madrid")
    return _DIAS[t.weekday()], f"{t.hour:02d}h"


def _diario(dia):
    return pd.DataFrame({k: dia[k] for k in ("open", "high", "low", "close")},
                        index=pd.DatetimeIndex(dia["ts"]).normalize())


def analizar(ficha, instrumento, barras, costes, dia, dia_sp500, vecinos=()):
    f = deepcopy(ficha)
    f["gestion"]["tamano"] = {"tipo": "unidades", "valor": 1}
    f["gestion"].pop("perdida_diaria_max", None)
    con_c = [o for o in motor.backtest_serie(f, instrumento, barras, costes, 5000).operaciones if o.motivo != "fin"]
    riesgo = np.array(mapa._riesgos(f, barras, con_c), float)
    validas = [k for k, (o, r) in enumerate(zip(con_c, riesgo)) if np.isfinite(r) and r > 0 and o.unidades > 0]
    con_c, riesgo = [con_c[k] for k in validas], riesgo[validas]
    if len(con_c) < 2:
        return None
    sin_c = [o for o in motor.backtest_serie(f, instrumento, barras, costes.escalar(0), 5000).operaciones
             if o.motivo != "fin" and o.unidades > 0]
    # the engine may cap units below 1 when the price exceeds the cash; results are per one unit, as in mapa
    R = np.array([o.pnl / o.unidades for o in con_c]) / riesgo
    n = len(R)

    celdas = {}
    for r, o in zip(R, con_c):
        celdas.setdefault(_celda(barras["ts"][o.i_entrada]), []).append(r)
    rejilla = [{"dia": d, "hora": h, "ops": len(rs), "pf": _pf(rs)} for (d, h), rs in sorted(celdas.items())]

    bruto = sum(o.pnl / o.unidades for o in sin_c)
    costes_tot = sum(o.costes / o.unidades for o in con_c)
    g1 = {"r_medio": round(float(R.mean()), 3), "costes_sobre_bruto": round(costes_tot / bruto, 3) if bruto > 0 else None,
          "bruto_por_op_pts": round(bruto / len(sin_c), 2) if sin_c else None, "coste_por_op_pts": round(costes_tot / n, 2)}

    rg = riesgo
    mae, mfe = [], []
    for o, r in zip(con_c, rg):
        lo, hi = barras["low"][o.i_entrada:o.i_salida + 1].min(), barras["high"][o.i_entrada:o.i_salida + 1].max()
        if o.lado > 0:
            mae.append((o.precio_entrada - lo) / r), mfe.append((hi - o.precio_entrada) / r)
        else:
            mae.append((hi - o.precio_entrada) / r), mfe.append((o.precio_entrada - lo) / r)
    mae, mfe = np.array(mae), np.array(mfe)
    gan = R > 0
    med = lambda x, d=2: round(float(np.median(x)), d) if len(x) else None
    g2 = {"mae_ganadoras_mediana": med(mae[gan]), "mae_perdedoras_mediana": med(mae[~gan]), "mfe_mediana": med(mfe),
          "r_mediana": med(R), "dejado_mediana": med(mfe - R),
          "salidas": {k: round(v / n, 3) for k, v in Counter(o.motivo for o in con_c).most_common()},
          "pts": {"mae_ganadoras": med((mae * rg)[gan], 1), "mae_perdedoras": med((mae * rg)[~gan], 1), "mfe": med(mfe * rg, 1),
                  "resultado": med(R * rg, 1), "dejado": med((mfe - R) * rg, 1), "stop": med(rg, 1)}}

    racha = peor = 0
    for r in R:
        racha = racha + 1 if r < 0 else 0
        peor = max(peor, racha)
    ts_sal = pd.DatetimeIndex(barras["ts"][[o.i_salida for o in con_c]])
    ts_ent = pd.DatetimeIndex(barras["ts"][[o.i_entrada for o in con_c]])
    pico_t, pico_v, bajo_agua = ts_sal[0], -np.inf, pd.Timedelta(0)
    for t, v in zip(ts_sal, np.cumsum(R)):
        if v > pico_v:
            pico_v, pico_t = v, t
        bajo_agua = max(bajo_agua, t - pico_t)
    semanas = max((ts_ent[-1] - ts_ent[0]).days / 7, 1 / 7)
    dias_mercado = len(np.unique(pd.DatetimeIndex(barras["ts"]).normalize()))
    g3 = {"peor_racha": int(peor), "dias_sin_maximo": int(bajo_agua.days), "ops_semana": round(n / semanas, 2),
          "dias_con_op": round(len(np.unique(ts_ent.normalize())) / dias_mercado, 3)}

    sd = R.std(ddof=1)
    g4 = {"prob_suerte": _prob_suerte(R), "t": round(float(R.mean() / (sd / math.sqrt(n))), 2) if sd else None, "n": n,
          "vecinos": sorted(vecinos, key=lambda v: -v["pf"])[:8]}

    g5 = None
    if dia is not None:
        d = _diario(dia)
        rango = d["high"] - d["low"]
        tendencia = (d["close"] - d["open"]).abs() / rango.replace(0, np.nan) >= 0.5
        volatil = rango > rango.rolling(20).median()
        clases = {"tendencia": [], "lateral": [], "volatil": [], "tranquilo": []}
        for r, t in zip(R, ts_ent.normalize()):
            if t in d.index:
                clases["tendencia" if tendencia.at[t] else "lateral"].append(r)
                clases["volatil" if volatil.at[t] else "tranquilo"].append(r)
        g5 = {k: {"ops": len(v), "pf": _pf(v)} for k, v in clases.items()}

    g6 = None
    if dia_sp500 is not None:
        diario = pd.Series(R, index=ts_sal.normalize()).groupby(level=0).sum()
        ret = _diario(dia_sp500)["close"].pct_change().reindex(diario.index).dropna()
        if len(ret) >= 20 and ret.std() > 0 and diario.loc[ret.index].std() > 0:
            g6 = {"corr_sp500": round(float(np.corrcoef(diario.loc[ret.index], ret)[0, 1]), 2), "dias": len(ret)}

    return {"n": n, "g1": g1, "g2": g2, "g3": g3, "g4": g4, "g5": g5, "g6": g6, "rejilla": rejilla}
