# Quant

A personal trading-research system (Python). Agents research and validate strategies overnight, a demo bot trades them on paper, and a panel shows the results. Nothing here trades real money. Overview: `README.md`.

**Language:** replies to the owner are in Spanish. Everything else (code, comments, roles, prompts) is in English.

**Each terminal reads `roles/<its role>.md` first** and acts only as that role. This team builds and maintains Quant with the owner; it is not the nightly agents (`skills/`), which are part of the product.

## Team and write zones

Each path is written by one role only; the others read it. A shared file is arbitrated by Jefe.

| Role | Model | Writes in | Ask about |
|---|---|---|---|
| **Jefe** | Opus | `docs/`, `CLAUDE.md`, `roles/`, `encargos/` | Default entry point: decides or routes to the right role; writes plans and hands out assignments |
| **Motor** | Sonnet | `codigo/quant/*.py` (top-level modules; not barrido.py or ranking.py), `codigo/quant/esquema_ficha.json`, `codigo/quant/fuentes/`, `codigo/quant/investigacion/`, `codigo/instalar_tareas.ps1` | Backtests that do not add up, new indicators, engine extensions. Only with a Jefe assignment and the owner's OK |
| **Estrategias** | Sonnet | `codigo/quant/familias/`, `codigo/quant/barrido.py`, `codigo/quant/ranking.py`, `skills/` | Families, own strategies (the examples `ejemplo` and `manual`), papers that did not fit, the sweep |
| **Demo** | Sonnet | `codigo/quant/demo/`, `config/demo.json` | Adapters, orders, safety net, drift |
| **Panel** | Sonnet | `codigo/quant/panel/` | What is shown and how |
| **Operaciones** | Haiku | `informes/operaciones/` | "What happened last night?", "why is it red?". Reads diagnostics, reports and logs; passes fixes to Jefe |
| **Revisor** | Opus | Nothing | Reviews every change from Motor, Estrategias, Demo and Panel before it reaches the owner |

If unsure who to ask, ask Jefe.

A more specific zone wins over the Motor glob `codigo/quant/*.py`.

Each role writes the tests for modules in its zone as `codigo/tests/test_<module>.py`. This table is canonical; role files mirror it exactly.

Assignments between roles go in `encargos/<role>.md`.

## Only the owner decides

No role changes these:

- `config/criterios.json`, `config/costes.json` and `examen/`.
- Which own strategies get translated, and in what order.
- Opening demo accounts, storing keys, real money.
- New families, new filters, and changes to the engine, validator, ficha schema or adapters (Jefe assignment plus the owner's OK).

## Key paths

- Catalog: `catalogo.db` (repo root, SQLite)
- Logs and reports: `registro/`, `informes/`

## Tests

From `codigo/`: `PYTHONPATH=. ../.venv/Scripts/python.exe -m pytest -q` (add a test file path to focus).
