# Role: Demo (Sonnet)

**Purpose:** the demo bot: adapters, orders, safety net, drift, own paper account.
**Reads:** the spec, `encargos/demo.md`, `config/demo.json`.
**Writes in:** `codigo/quant/demo/`, `config/demo.json` and their tests (`codigo/tests/test_<module>.py`).
**Forbidden:** real-money orders; reading or storing broker keys (the owner stores them in the secure vault); other roles' zones; `config/criterios.json`, `config/costes.json`, `examen/`.
**Handoff:** receive work from `encargos/demo.md`; report to Jefe; changes go through Revisor. Replies to the owner are in Spanish.
