# Glosario ingles / español / aleman

| Ingles | Español | Aleman |
|---|---|---|
| moving average | media movil | gleitender Durchschnitt |
| breakout | ruptura | Ausbruch |
| drawdown | caida maxima | Rueckgang |
| stop loss | stop de perdidas | Verlustbegrenzung |
| take profit | objetivo de beneficio | Gewinnmitnahme |
| trailing stop | stop dinamico | nachlaufender Stop |
| backtest | prueba historica | historischer Test |
| overfitting | sobreajuste | Ueberanpassung |
| mean reversion | reversion a la media | Mittelwertumkehr |
| momentum | momento / momentum | Momentum |
| survivorship bias | sesgo de supervivencia | Survivorship-Bias |
| slippage | deslizamiento | Slippage |

## Funciones que delatan entradas y salidas

**Pine Script**: `strategy.entry(...)` marca una entrada; `strategy.exit(...)` y `strategy.close(...)` marcan salidas; `ta.crossover` / `ta.crossunder` suelen ser la condicion de entrada de un cruce.

**MQL5**: `OrderSend` / `trade.Buy` / `trade.Sell` marcan entradas; `trade.PositionClose` / el uso de `sl` y `tp` en la orden marcan salidas; `iMA`, `iRSI`, `iATR` etc. calculan los indicadores que alimentan la señal.
