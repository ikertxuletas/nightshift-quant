# Quant

*English: Quant is a personal, self-hosted trading-research lab written in Python. Every night a team of AI agents (Claude Code) reads public papers, turns the trading ideas into machine-readable rules, backtests and validates them with strict criteria; the survivors trade on paper in a demo, and a local web panel explains everything in plain language. It never trades real money. The project, its UI and its agents' outputs are in Spanish; the code is in English.*

Quant es un laboratorio de investigación de trading que corre en tu propio ordenador. Cada noche:

1. **Descarga precios** (Yahoo, Dukascopy, Binance) de un universo de índices, divisas, materias primas, acciones y criptomonedas.
2. **Lee documentos públicos** (arXiv, Quantpedia, MQL5, Reddit) con agentes de IA que extraen las ideas de trading y las convierten en **fichas**: reglas exactas que el motor puede ejecutar.
3. **Prueba cada ficha** con un motor de backtest con costes reales (comisión, diferencial y deslizamiento) y un **validador** con criterios fijos: caída máxima, años fuera de muestra, robustez de parámetros, costes dobles, Montecarlo y comparación con comprar y mantener.
4. **Barre familias de estrategias** clásicas (cruces de medias, rupturas, reversión a la media, momento...) en todo el universo y las ordena con una nota de 0 a 100.
5. **Mejora tus propias estrategias** en un laboratorio: un agente propone variantes cada noche, se miden solo con los años de entrenamiento y el examen final usa años que el agente nunca ve.
6. **Opera en papel** las estrategias que aprueban, con dinero ficticio y precios reales, y retira las que se desvían de su backtest.
7. **Lo explica todo** en un panel web local, pensado para quien no es programador: qué ha pasado, por qué gana o pierde cada estrategia y qué significa cada cifra (con glosario).

> **Aviso.** Esto es un proyecto personal de investigación y aprendizaje. No es consejo financiero, no opera dinero real y los resultados de un backtest no garantizan nada en el futuro.

## Qué hace falta

- **Windows 10 u 11** (las tareas nocturnas usan el Programador de tareas; el resto funciona en cualquier sistema con Python).
- **Python 3.12 o superior** (desarrollado con 3.14).
- **[Claude Code](https://claude.com/claude-code)** instalado y con sesión iniciada en tu suscripción: los agentes nocturnos lo llaman con `claude -p`. Sin él, el motor, el barrido, la demo y el panel funcionan igual; solo se omiten las etapas con agentes.
- Unos 20 GB libres para los precios.

## Instalación

```powershell
git clone https://github.com/ikertxuletas/quant-abierto.git Quant
cd Quant
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r codigo\requirements.txt
.venv\Scripts\python.exe -m pip install -e codigo
```

Comprueba que todo está bien (tarda un minuto; algunas pruebas se saltan hasta que tengas precios reales):

```powershell
cd codigo
..\.venv\Scripts\python.exe -m pytest -q
```

Firma los criterios del validador. Quant se niega a validar si `config/criterios.json` cambia sin volver a firmarlo:

```powershell
..\.venv\Scripts\python.exe -m quant.criterios --firmar
```

## Primeros pasos

Desde la carpeta `codigo`:

```powershell
# 1. Precios (la primera vez tarda horas; después solo baja lo nuevo)
..\.venv\Scripts\python.exe -m quant.actualizar --fuente yahoo
..\.venv\Scripts\python.exe -m quant.actualizar

# 2. Barrido de familias (puedes limitarlo: --horas 2)
..\.venv\Scripts\python.exe -m quant.barrido --horas 2

# 3. Panel en http://127.0.0.1:20135
..\.venv\Scripts\python.exe -m quant.panel.servidor
```

El panel solo escucha en tu ordenador y pide una clave que se genera al arrancar, en `registro/panel_clave`. Ábrelo una vez con `http://127.0.0.1:20135/?key=<la clave>` y el navegador la recordará.

Para que todo corra solo cada noche, instala las tareas programadas desde PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File codigo\instalar_tareas.ps1
```

Crea estas tareas: la noche a las 02:00 (precios, agentes, laboratorio, demo e informe), la revisión a las 06:15, un vigilante a las 07:30, la demo cada hora, el barrido los sábados y el panel al iniciar sesión. Si tienes varios equipos y quieres que la noche corra solo en uno, define la variable de entorno `QUANT_EQUIPO` con el nombre de ese equipo.

## Cómo está organizado

| Carpeta | Qué hay |
|---|---|
| `codigo/quant/` | Motor de backtest, validador, indicadores, costes, datos y universo |
| `codigo/quant/familias/` | Familias de estrategias del barrido y las estrategias propias (`propias.py`) |
| `codigo/quant/investigacion/` | La noche: agentes (lector, formalizador, crítico, relator, mentor), laboratorio, asesor, revisión y diagnóstico |
| `codigo/quant/demo/` | Demo en papel: selección, órdenes, red de seguridad y desvío frente al backtest |
| `codigo/quant/panel/` | Panel web local (HTML generado en Python, sin framework) |
| `skills/` | Las instrucciones de cada agente nocturno |
| `config/` | Universo, costes, criterios del validador y demo |
| `examen/` | Examen fijo para medir si los agentes leen bien: respuestas correctas escritas a mano y el enlace a cada documento |
| `roles/`, `CLAUDE.md` | Cómo se reparten el trabajo las sesiones de Claude Code que mantienen el proyecto |

## Añadir tus propias estrategias

Las estrategias propias no entran en el barrido: las trabaja el laboratorio cada noche. Vienen dos ejemplos públicos:

- `ejemplo`: el RSI(2) de Larry Connors, adaptado al SP500 en velas de 15 minutos.
- `manual`: cómo se traduce una operativa manual descrita con palabras (cruce de medias a favor de la media de 200, con stop y objetivo medidos en ATR y cierre antes del final de la sesión).

Para añadir la tuya:

1. Escribe su familia en `codigo/quant/familias/<nombre>.py` (copia `ejemplo.py`: la ficha describe entradas, salidas, gestión y horario) y regístrala en `familias/__init__.py`.
2. Añádela a `PROPIAS` en `codigo/quant/familias/propias.py` con su instrumento, plazo y la fecha de corte del examen (`corte`): el laboratorio nunca verá los datos posteriores hasta el examen final.
3. Pasa las pruebas. Esa noche el laboratorio empezará a proponer variantes y el panel la mostrará en Ranking › Propias.

## Contribuir

Las mejoras y los avisos de fallos son bienvenidos: abre un *issue* o un *pull request*.

Si el proyecto te resulta útil y quieres apoyarlo, puedes hacer una aportación por **PayPal** a **ikerchup.g@gmail.com**. Gracias.

## Licencia

[MIT](LICENSE). Los gráficos usan [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/) (Apache 2.0) y la letra [Geist](https://vercel.com/font) (OFL), incluidas en `codigo/quant/panel/static/`.
