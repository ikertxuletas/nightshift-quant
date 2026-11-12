"""Quant score: 8 attributes from 0 to 10 and their mean x10. Display only, it never changes a verdict."""


def _clip(x):
    return max(0.0, min(1.0, x))


def _n(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def nota(metricas, stats):
    t, d, f = metricas.get("total") or {}, metricas.get("dentro") or {}, metricas.get("fuera") or {}
    sharpe, dd, rent = t.get("sharpe") or 0.0, t.get("drawdown") or 0.0, t.get("rentabilidad") or 0.0
    ops = t.get("operaciones") or 0
    ratio = (f.get("sharpe") or 0.0) / d["sharpe"] if (d.get("sharpe") or 0) > 0 else 0.0
    caros = metricas.get("rentabilidad_costes_x2")
    costes = 10 * _clip(caros / rent) if rent > 0 and caros is not None else 0.0
    anios = (stats or {}).get("anios") or 0.0
    positivos, n_anios = (stats or {}).get("anios_positivos"), (stats or {}).get("n_anios")
    consistencia = 10 * positivos / n_anios if n_anios else 0.0
    ventaja = sharpe - (metricas.get("sharpe_comprar_mantener") or 0.0)
    atributos = [
        ("riesgo", "Rentabilidad ajustada al riesgo", 10 * _clip(sharpe / 1.5),
         f"Sharpe de {_n(sharpe)} en todo el periodo; 1,5 sería un 10."),
        ("aguante", "Aguante fuera de muestra", 10 * _clip(ratio / 1.5),
         f"Fuera de muestra rinde {_n(ratio)} veces lo que rendía dentro; 1,5 veces sería un 10."),
        ("caidas", "Control de caídas", 10 * _clip(1 - dd / 0.30),
         f"Peor caída del {_n(dd * 100, 1)} %; un 0 % sería un 10 y un 30 % un 0."),
        ("robustez", "Robustez", 10 * _clip(metricas.get("robustez") or 0.0),
         "Proporción de variantes de sus parámetros (±20 %) que también ganan."),
        ("costes", "Resistencia a costes", costes,
         "Parte de la ganancia que conserva con costes al doble."),
        ("experiencia", "Experiencia", 10 * min(anios / 10, 1) * min(ops / 100, 1),
         f"{_n(anios, 1)} años y {ops} operaciones; 10 años y 100 operaciones serían un 10."),
        ("consistencia", "Consistencia", consistencia,
         f"Gana dinero en {positivos} de {n_anios} años." if n_anios else "Sin años completos que contar."),
        ("ventaja", "Ventaja frente a comprar y mantener", 10 * _clip(ventaja / 0.5),
         f"Sharpe {_n(ventaja)} frente a tener el activo; +0,5 sería un 10."),
    ]
    lista = [{"clave": k, "nombre": nombre, "valor": round(v, 2), "por_que": por_que}
             for k, nombre, v, por_que in atributos]
    return {"nota": round(sum(a["valor"] for a in lista) / len(lista) * 10), "atributos": lista}
