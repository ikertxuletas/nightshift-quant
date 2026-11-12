# Examen fijo de los agentes

Estos 20 casos son la vara de medir del Lector, el Formalizador y el Critico. Cada carpeta de
`casos/` tiene su `meta.json` (titulo y enlace a la fuente), el `extracto.json` correcto y, cuando la
estrategia es expresable, la `ficha.json` correcta.

**Los textos de los documentos no se incluyen**: son articulos y paginas de terceros (arXiv,
Quantpedia, MQL5, Reddit) y no se redistribuyen. Para usar un caso, abre el enlace `url` de su
`meta.json`, guarda el texto en `documento.txt` dentro de su carpeta y recortalo con
`quant.investigacion.agentes.recorte`. Los casos sin `documento.txt` se saltan.

Cinco casos traen ademas una `critica.json` con una ficha manipulada a proposito y el veredicto que
el Critico deberia dar.

Las respuestas correctas estan escritas a mano leyendo los documentos: **ninguna la ha generado un
modelo**. Por eso sirven para comparar skills, prompts y modelos entre si.

**Solo el dueño cambia estos casos.** Ni los agentes ni ningun proceso automatico tocan esta carpeta:
si el examen se ajusta para que un modelo apruebe, deja de medir nada.

Para ejecutarlo:

```
..\.venv\Scripts\python.exe -m quant.investigacion.examen --agente lector --guardar
```

Las notas de cada agente se guardan en `notas.json`.
