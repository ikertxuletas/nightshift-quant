## Como leer las tres referencias del resultado

El resultado trae hasta tres comparaciones distintas; no son intercambiables:

**El estandar**: es el que decide si la ficha pasa, es dudosa o no pasa. Son los umbrales fijos del examen (drawdown maximo, Sharpe fuera de muestra minimo, etc.) que se aplican igual a todas las estrategias. Es la unica referencia que determina el veredicto.

**"Prometido por la fuente" (`vs_fuente`)**: compara el resultado obtenido en la prueba con las cifras que decia el documento original de donde salio la estrategia. Un valor negativo significa que a la estrategia le fue peor en la prueba que lo que prometia el documento; un valor positivo, que le fue mejor. Esta referencia no decide el veredicto, solo informa de si el documento era optimista.

**"Normal para su tipo" (`vs_tipo`)**: situa la estrategia frente a otras de la misma familia (por ejemplo, otras estrategias de reversion) probadas en el sistema, para saber si sus numeros son tipicos o llamativos dentro de ese grupo. Tampoco decide el veredicto.

Por eso una estrategia puede pasar el estandar y, a la vez, quedar lejos de lo que prometia la fuente: el estandar es un listón fijo y objetivo, mientras que la fuente puede haber exagerado sus propios resultados (por ejemplo, sin descontar costes, o eligiendo el mejor periodo posible). Pasar el estandar dice que la estrategia cumple el minimo exigido en esta prueba; no dice que cumpla lo que prometia el papel de origen.
