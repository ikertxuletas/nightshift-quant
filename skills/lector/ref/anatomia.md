# Donde suelen estar las reglas

- **Paper academico**: casi nunca en la introduccion o el abstract. Busca la seccion de datos y metodologia (como se construye la señal) y la de construccion de la cartera o backtest (como se entra, se pondera y se rebalancea). Los resultados prometidos estan en la seccion de resultados empiricos, normalmente en una tabla.
- **Quantpedia**: las reglas de negociacion estan en el apartado explicito "Trading Rules" (o su traduccion, reglas de negociacion). El resto de la ficha (motivacion, referencias academicas) no aporta reglas ejecutables.
- **Hilo de Reddit**: casi siempre el primer mensaje contiene toda la estrategia; las respuestas son opiniones, variantes o preguntas, rara vez reglas adicionales fiables. Si la regla completa solo aparece repartida entre respuestas, marca el documento como incompleto.
- **Codigo MQL5**: las reglas de entrada estan en las funciones que comprueban condiciones antes de abrir una orden (tipicamente `OnTick` o funciones de señal); las de salida en las que gestionan el stop, el take profit o el cierre anticipado. El codigo es la fuente de verdad mas fiable porque no admite ambiguedad, pero hay que distinguir parametros de entrada (inputs) de logica fija.

## Como leer una tabla de resultados

Identifica primero las columnas: periodo probado, si los resultados incluyen costes de transaccion, y la metrica exacta (CAGR no es lo mismo que rentabilidad anualizada simple; Sharpe puede venir con o sin ajustar por riesgo libre). Si la tabla no dice si incluye costes, no asumas que si los incluye.

## Anomalia descrita frente a estrategia con reglas

Una anomalia describe una correlacion observada ("las acciones de baja volatilidad baten al mercado ajustado a riesgo") sin decir como entrar ni salir. Una estrategia tiene reglas ejecutables: que se compra, cuando, cuanto, y cuando se cierra. Si el documento solo describe el fenomeno, sin decir que se compra ni cuando se entra, el resultado es `no`. Si dice que se opera y cuando se entra pero falta alguna de las otras respuestas (cuanto, cuando se cierra), es `incompleta` y lo que falta va en `faltan`.
