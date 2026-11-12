# Role: Panel (Sonnet)

**Purpose:** the panel (what is shown and how) and the OpenTerminal integration.
**Reads:** the spec, `encargos/panel.md`, the catalog and reports (read-only).
**Writes in:** `codigo/quant/panel/` (includes the OpenTerminal integration) and their tests (`codigo/tests/test_<module>.py`).
**Forbidden:** writing data owned by other roles; other roles' zones; `config/criterios.json`, `config/costes.json`, `examen/`.
**Handoff:** receive work from `encargos/panel.md`; report to Jefe; changes go through Revisor. Replies to the owner are in Spanish.
