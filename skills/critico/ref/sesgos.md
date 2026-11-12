# Lista de comprobacion de sesgos

- **Fuga de futuro (look-ahead)**: usar en la decision de una vela datos que en ese momento todavia no existian (por ejemplo el cierre del dia, antes de que el dia haya cerrado).
- **Confundir el cierre de la vela actual con el de la siguiente**: una señal calculada con el cierre de hoy solo puede ejecutarse a partir de la apertura de mañana, nunca en el mismo instante del cierre.
- **Stop confundido con trailing**: un stop fijo no se mueve con el precio; un trailing si. Si el extracto dice "stop" a secas, no asumas que es dinamico.
- **Unidades mezcladas**: comprobar si una distancia esta en porcentaje, en puntos de precio o en multiplos de ATR; un "2%" no es lo mismo que "2 ATR".
- **Universo de supervivientes**: si el universo probado son los instrumentos que existen hoy, el resultado esta sesgado al alza porque excluye los que quebraron o fueron excluidos del indice.
- **Costes ausentes**: comprobar si el extracto dice explicitamente que los resultados incluyen comisiones y deslizamiento; si no lo dice, no se puede asumir que si.
- **Reglas ambiguas**: frases como "cuando el mercado esta fuerte" o "en tendencia clara" no son una regla ejecutable; si la ficha las tradujo a un indicador concreto sin que el extracto de esa cifra, es un supuesto no declarado.
- **Señales sin regla de salida**: si el extracto solo describe cuando entrar y la ficha inventa una salida no mencionada, eso es una regla añadida que hay que devolver o rechazar.
