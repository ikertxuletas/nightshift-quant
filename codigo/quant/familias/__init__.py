import copy
import hashlib
import itertools
import json
from dataclasses import dataclass, field
from typing import Callable, Iterator

STOP_ATR = (2, 3)
ALL_CLASSES = ("indice", "forex", "materia", "accion", "cripto")


@dataclass(frozen=True)
class Family:
    name: str
    explanation_es: str
    params: dict
    markets: tuple
    timeframes: tuple
    form: str
    generate: Callable
    coherent: Callable = field(default=lambda p: True)


@dataclass(frozen=True)
class Combo:
    family: str
    params: dict
    instruments: tuple
    timeframe: str
    filter: str
    origin: str


def stop(params):
    return {"tipo": "atr", "valor": params["stop_atr"]}


def _groups(family, uni):
    # a market entry is a universe class or a single instrument name
    by_market = [tuple(n for n, i in uni["instrumentos"].items() if i["clase"] == m or n == m)
                 for m in family.markets]
    by_market = [g for g in by_market if g]
    return by_market if family.form == "transversal" else [(i,) for g in by_market for i in g]


def combos(family, uni, origin="barrido") -> Iterator[Combo]:
    names = list(family.params)
    grids = [dict(zip(names, v)) for v in itertools.product(*family.params.values())]
    grids = [p for p in grids if family.coherent(p)]
    for params, group, tf in itertools.product(grids, _groups(family, uni), family.timeframes):
        yield Combo(family.name, params, tuple(group), tf, "sin_filtro", origin)


def to_ficha(combo):
    fam = FAMILIES[combo.family]
    key = json.dumps([combo.family, combo.params, combo.instruments, combo.timeframe, combo.filter], sort_keys=True)
    ficha = copy.deepcopy(fam.generate(combo.params, list(combo.instruments), combo.timeframe, combo.filter))
    return {"id": f"{combo.family}-{hashlib.sha1(key.encode()).hexdigest()[:8]}",
            "titulo": f"{combo.family} {combo.params} {','.join(combo.instruments)} {combo.timeframe}",
            "fuente": {"url": f"familia://{fam.name}", "cita": fam.explanation_es},
            **ficha, "estado": "borrador"}


def serie(tipo, instruments, timeframe, entry, exit_, gestion):
    ficha = {"tipo": tipo, "forma": "serie_temporal",
             "universo": {"instrumentos": instruments, "plazo": timeframe},
             "entrada": {"largo": entry}, "gestion": gestion}
    if exit_:
        ficha["salida"] = {"largo": exit_}
    return ficha


from quant.familias import (bollinger_reversion, control_comprar_mantener, cruce_medias, ejemplo,  # noqa: E402
                            manual, momentum_rotacion, recuperacion_media, rsi_reversion,
                            ruptura_donchian, ruptura_maximo_20, tendencia_cripto, zscore_reversion)

FAMILIES = {f.name: f for f in (m.FAMILY for m in (
    cruce_medias, ruptura_donchian, momentum_rotacion, rsi_reversion, bollinger_reversion,
    recuperacion_media, ruptura_maximo_20, zscore_reversion, tendencia_cripto, control_comprar_mantener, ejemplo,
    manual))}
