# Seguimiento de tendencia con la media de 200 sesiones en el S&P 500

Estrategia de seguimiento de tendencia sobre un único instrumento, el ETF SPY (acciones de Estados Unidos), con velas diarias.

Reglas:
- Entrada en largo: se compra SPY al cierre cuando el precio de cierre está por encima de su media móvil simple de 200 sesiones (SMA 200).
- Salida: se vende toda la posición al cierre cuando el precio de cierre cae por debajo de la media móvil simple de 200 sesiones.
- No se opera en corto. No hay stop, objetivo ni trailing: la única salida es el cruce por debajo de la media.
- Una sola posición, sin apalancamiento, con todo el capital asignado a SPY cuando se está dentro y en liquidez cuando se está fuera.

Resultados que cita la fuente para el periodo 1994-2023: rentabilidad anual compuesta del 8,1 %, caída máxima del -23,4 % y ratio de Sharpe de 0,62.

Este documento es el canario de Quant: no es una recomendación ni una estrategia candidata. Sirve para comprobar cada noche que la cadena lector → formalizador → crítico → validación sigue funcionando.
