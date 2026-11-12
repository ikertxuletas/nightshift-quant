Causas tipicas de error y a que skill apuntan:

- Extracto con `tipo` fuera del enum permitido -> Lector, `skill.md`.
- `mercado` vacio en una lectura marcada como operable -> Lector, `skill.md`.
- Ficha con `forma` equivocada o que rellena una seccion que no le toca -> Formalizador, `ref/patrones.md` (si existe) o `skill.md`.
- Indicador fuera del catalogo permitido -> Formalizador, `ref/indicadores.md`.
- Cifras de `prometido` inventadas o sin cita -> Lector (si extrae mal) o Critico (si no lo detecta).
- Critico que devuelve o rechaza sin un motivo concreto y verificable -> Critico, `skill.md`.
- Rechazos repetidos por instrumentos o mercados inventados que no estan en el extracto -> Formalizador, `skill.md`.
- Errores de red, timeouts o `ErrorModelo` -> no son un problema de skills: `agente: null`.
