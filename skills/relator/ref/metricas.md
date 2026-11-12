## Como explicar cada metrica en llano

**Drawdown (caida maxima)**: cuanto llego a bajar la cuenta desde su pico anterior antes de recuperarse. Ejemplo: un drawdown de 0.18 se dice "la cuenta llego a bajar un 18 % desde su maximo antes de volver a subir".

**Sharpe**: cuanta rentabilidad da la estrategia por cada unidad de riesgo que asume; mas alto es mejor, y por debajo de cero significa que ni compensa el riesgo tomado. Se mira siempre el Sharpe fuera de muestra (el del tramo de datos que el sistema no uso para ajustar nada), porque el de dentro de muestra esta inflado por diseño. Ejemplo: Sharpe fuera de muestra de 0.6 se dice "por cada unidad de riesgo, la estrategia gano 0,6 unidades de rentabilidad en el tramo que no se uso para ajustarla".

**CAGR (rentabilidad anual compuesta)**: a que ritmo medio creceria el capital cada año si el patron del periodo probado se repitiera. Ejemplo: CAGR de 0.07 se dice "de mantenerse el mismo comportamiento, el capital creceria en torno a un 7 % al año".

**Rentabilidad con costes x2**: la rentabilidad total del periodo probado, pero pagando el doble de comisiones y deslizamiento de lo habitual, para ver si sobrevive a un escenario de costes mas duro. Ejemplo: 0.5 se dice "incluso duplicando los costes de operar, el periodo probado cerro con un 50 % de rentabilidad acumulada".

**Numero de operaciones**: cuantas veces entro y salio la estrategia durante la prueba. Con pocas operaciones (por ejemplo menos de 30) el resultado no es fiable, porque un puñado de operaciones con suerte puede parecer una buena estrategia sin serlo.

**Acierto**: de cada 100 operaciones, cuantas terminaron en ganancia. Un acierto bajo no es necesariamente malo si las ganancias son mucho mayores que las perdidas; hay que mirarlo junto al profit factor.

**Profit factor**: cuanto se gano en las operaciones ganadoras por cada unidad perdida en las perdedoras. Ejemplo: profit factor de 1.4 se dice "por cada euro perdido en las operaciones malas, la estrategia gano 1,4 euros en las buenas".

**Monte Carlo (permutacion) y p95**: se barajan al azar los datos muchas veces y se repite la prueba en cada barajado, para ver si el resultado real destaca sobre lo que saldria por puro azar. El p95 es el valor que solo el 5 % de esos barajados al azar logro superar; si el resultado real queda por encima del p95, es dificil que sea casualidad.

**Robustez ±20 %**: se repite la prueba moviendo los parametros de la estrategia un 20 % hacia arriba y hacia abajo, para ver si sigue funcionando o si solo valia con los numeros exactos originales. Si el resultado se desmorona con pequeños cambios, la estrategia esta sobreajustada a esos numeros concretos.
