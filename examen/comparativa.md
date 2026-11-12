# Comparativa de modelos (Task 7, Step 3)

Examen fijo ejecutado con `python -m quant.investigacion.examen --agente <a> --modelo <m>` (sin `--guardar`) para cada candidato, una pasada. Regla de decision: gana la mejor nota; si la diferencia es <= 0,02 gana el mas rapido.

| Agente | Modelo | Nota | s/caso | Decision | Motivo |
|---|---|---|---|---|---|
| lector | qwen3.5:35b-a3b (actual) | 0,6901 | 39,4 | perdedor | nota muy inferior al candidato |
| lector | qwen3.5:27b (candidato) | 0,8186 | 121,6 | **ganador** | diferencia de nota 0,1285 > 0,02: gana la mejor nota pese a ser 3x mas lento |
| formalizador | gemma4:31b (actual) | 0,3085 | 207,2 | perdedor | misma nota que el candidato pero 9x mas lento |
| formalizador | gemma4:26b-a4b-it-qat (candidato) | 0,3098 | 22,2 | **ganador** | diferencia de nota 0,0013 <= 0,02: empate tecnico, gana el mas rapido |
| critico | qwen3.5:27b (actual) | 0,90 | 88,6 | **ganador** | diferencia de nota 0,10 > 0,02: gana la mejor nota, se mantiene el actual |
| critico | qwen3.5:35b-a3b (candidato) | 0,80 | 26,0 | perdedor | nota inferior al actual pese a ser 3,4x mas rapido |

## Cambios aplicados

- `config/agentes.json`: `lector.modelo_base` -> `qwen3.5:27b`; `formalizador.modelo_base` -> `gemma4:26b-a4b-it-qat`. `critico` sin cambios.
- Especialistas recreados via API HTTP (`especialistas.crear`, sin CLI `ollama`) para `quant-lector` y `quant-formalizador`.
- Notas reguardadas con `examen --agente <a> --guardar` sobre los especialistas ya recreados (`examen/notas.json`):
  - lector: nota 0,7942, 20 casos, 2873,3 s totales (143,7 s/caso) — pequeña variacion frente a la pasada de comparativa (0,8186) por naturaleza estocastica del LLM; sigue muy por encima del modelo anterior (0,6901).
  - formalizador: nota 0,3085, 8 casos, 174,5 s totales (21,8 s/caso) — nota estable, tiempo por caso confirmado ~9x mas rapido que el modelo anterior.
  - critico: sin cambio, se mantiene la nota de partida (0,90, 5 casos, 445 s).

## Fallos tipicos observados

**Formalizador** (nota mas baja de los tres agentes, 0,31): produce fichas con `forma: "serie_temporal"` pero incluye una seccion `transversal` (con `ranking`/`top`/`cada_barras`) en vez de `entrada`/`salida` con lado `largo`/`corto`; esto ocurre sistematicamente en estrategias de rotacion/momentum transversal entre clases de activos o sectores (Quantpedia), donde el paper describe un ranking periodico y el agente lo traduce mal al esquema de ficha. Tambien aparecen fichas sin la propiedad obligatoria `gestion`, y con `entrada`/`salida` en `null` cuando el agente no logra extraer una regla de entrada explicita del texto. Estos fallos se repiten igual con `gemma4:31b` y con `gemma4:26b-a4b-it-qat`: es un problema del prompt/skill de formalizacion frente a estrategias transversales, no del modelo base.

**Lector**: en casos de documentos MQL5 con reglas de salida poco estandar (`15-mql5-zetaburst`), extrae un `plazo` o `tipo` fuera del enum permitido y falla el reintento; en papers largos y densos (`03-arxiv-retos-prop-firms`) la nota cae por resumenes incompletos. El candidato `qwen3.5:27b` mejora notablemente la fidelidad en casos Reddit y arXiv pero sigue siendo lento (2-3x el modelo anterior) y no elimina estos fallos de enum.

**Critico**: en el unico caso de nota parcial (`15-mql5-zetaburst`, 0,5) el modelo evalua de forma mas indulgente de lo esperado una ficha con reglas de gestion de riesgo ambiguas; comun a ambos modelos probados.

## 2026-10-29: Ollama frente a Claude (Plan 8)

| Agente | Ollama | Claude | Modelo |
|---|---|---|---|
| lector (20 casos) | 0,7317 | 0,6732 | haiku |
| lector, prueba sin guardar | | 0,6992 | sonnet |
| formalizador (8) | 0,5506 | 0,6584 | sonnet |
| critico (5) | 0,7 | 0,6 | sonnet |

Notas de Ollama guardadas en `notas_ollama_2026-10-29.json`. El lector se queda en haiku: sonnet solo gana 0,026 a un coste bastante mayor. El critico baja un caso de cinco.
