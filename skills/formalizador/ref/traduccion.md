# Equivalencias de Pine Script y MQL5 a la ficha

| Codigo | Ficha |
|---|---|
| `ta.crossover(a, b)` | `{"cruza_arriba": [a, b]}` |
| `ta.crossunder(a, b)` | `{"cruza_abajo": [a, b]}` |
| `ta.sma(close, n)` | `SMA(n)` |
| `ta.ema(close, n)` | `EMA(n)` |
| `ta.rsi(close, n)` | `RSI(n)` |
| `ta.atr(n)` | `ATR(n)` |
| `iMA(..., n, ..., MODE_SMA, PRICE_CLOSE)` | `SMA(n)` |
| `iMA(..., n, ..., MODE_EMA, PRICE_CLOSE)` | `EMA(n)` |
| `iRSI(..., n, ...)` | `RSI(n)` |
| `iATR(..., n)` | `ATR(n)` |
| `strategy.exit(..., stop=x)` | `gestion.stop` |
| `strategy.exit(..., limit=x)` | `gestion.objetivo` |
| `strategy.exit(..., trail_points=x)` | `gestion.trailing` |
| `OrderSend(..., sl=x, ...)` | `gestion.stop` |
| `OrderSend(..., tp=x, ...)` | `gestion.objetivo` |
| take profit as a fraction of the previous day's range | `gestion.objetivo` `{"tipo": "rango_dia", "valor": f}` |
| flat at session end, no overnight | `horario.cierre` (HH:MM in `horario.zona`) |

## Lo que no es expresable

- `request.security(...)` que trae datos de otra temporalidad o de otro instrumento dentro de la misma condicion: la ficha no admite mezclar temporalidades ni fuentes cruzadas en una condicion simple, asi que no es expresable.
- `barstate.isrealtime`, o cualquier logica que decida con el precio de la vela que todavia no ha cerrado (por ejemplo usar `high`/`low` de la vela en curso para una señal que luego se re-evalua): eso es repintado. La ficha solo trabaja con velas cerradas, asi que esta logica hace la ficha **no expresable**, no una aproximacion.
- Recuerda que `MAX(n)` y `MIN(n)` incluyen la vela actual: si el documento describe una ruptura del maximo previo (sin contar la vela de la señal), la traduccion correcta es `MAX(n)[1]`, no `MAX(n)`.
