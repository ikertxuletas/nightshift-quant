# Design · Panel Quant

## Brief
For whom: the owner, alone, not a designer or developer; they check how their trading-research system is doing.
Goal: inform/operate. In a few seconds know, in this order: (1) is everything fine, (2) how much the demo is winning or losing, with its curve, (3) how their own strategies are doing, (4) what happened last night. Detail one step further down, never on the first screen.
Tone: calm, minimal, explained. Enough data to know what we are looking at, never overwhelming. Must not look AI-made.
Platform: local web app (server-rendered HTML from `codigo/quant/panel/`), desktop browser, dark.
User decisions (2026-11-12):
- References: Revolut (clean balance-first screen, rows with the amount on the right) and TradingView (charts: area curve, price scale on the right, crosshair).
- Dark theme on desktop.
- Every figure carries a short plain-language line underneath, always visible, plus a "?" that opens a deeper, detailed explanation of what it is and how to read it.
- New style for every page except Mercado (OpenTerminal keeps its own). Hoy is reorganised first; the other pages follow one by one after the owner sees Hoy.
Note: the skill's apps module is pending; core rules (aesthetics.md, quality.md) applied.
Revision (2026-11-12, after the first mock-up "too simple, looks AI-made"):
- Personality: precise, minimalist, serious, professional, explanatory, modern, technical.
- Density depends on the screen: few large things (Revolut) where it is a summary, many small things (TradingView) where it is detail.
- Colours: soft, dark, easy on the eyes, with an identity of their own.
- Explicitly requested (overrides the banned list, aesthetics §1): a living background with slow motion, like Revolut's, so the app feels alive. Must respect prefers-reduced-motion and use transform/opacity only.
- Classic trading-app elements so the eye knows where to go: real charts that take a large part of the screen when they are the subject and explain themselves.
- Asset logos yes (BTC, ETH, SP500...), drawn originally; nothing taken from other apps, no other apps' logos.
- Shape: designer's choice. Next step: a board of original options per decision (palette, living background, header, chart, rows, edge map, type, shape) for the owner to pick.
Board picks (2026-11-12):
1. Palette A "Noche azul", with more tones: layered blue-slate surfaces and a faint marble-vein texture on surfaces.
2. Living background B: real market price lines, very faint, sliding slowly behind the header.
3. Header B "mesa de trading": ticker strip + compact figures on a lined surface, plus period buttons Día / Semana / Mes / Todo.
4. All three charts (curve with band, candles with trades, candles with volume), with a switcher to change between them.
5. Rows A: asset logo, name, 30-day sparkline, amount on the right.
6. Edge map A: hour x weekday colour grid (cells with <20 trades hidden).
7. Type: Geist.
8. Shape B: one surface divided by thin lines.
Revision 2 (2026-11-12):
- No marble texture on surfaces. "Marble" meant the colour range: dark palettes inspired by real dark marbles. Candidates on a live switcher in the mock-ups: Negro Marquina (default), Verde Guatemala, Gris piedra, Emperador, Sodalita azul, Noche azul (previous). All pass contrast (lowest text pair 5.73:1).
- The owner wants to see every tab, not only Hoy: mock-ups of Hoy, Demo, Propias, Ranking, Sistema, Glosario (Mercado untouched) with real data.
- Palette chosen (2026-11-12): Negro Marquina (fondo #131518, capa #16191D, superficie #1B1E23, superficie-alta #22262C, linea #2D3138, linea-clara #3D434C, tinta #E9EBEE 13.99:1, tinta-suave #A3A8B2 7.0:1, acento #D5DBE6 12.02:1; sube #3CC796 7.8:1, baja #F2727A 5.94:1, aviso #E9B453; contrasts on superficie). Mock-ups approved as the direction; next: strategy page + Propias with the six figure groups, then spec and plan.
- Ranking (2026-11-12): no "why the others fail" block (not individual information). Full-width table, larger figures; the score is a coloured pill by band: 75+ muy alta, 70-74 alta, 65-69 media, <65 baja, none = grey; legend above the table. Shows every tested strategy (pass, doubtful and not passing) and each row opens its own strategy page.
- Keep the previous Darwinex-style structure with the new design elements (owner, 2026-11-12). Ranking = cards, not a table: score in a coloured circle by band, name + timeframe + verdict, family and parameters, 8 figures in two rows (annual, period, max drawdown, profit factor / total return, hit rate, out-of-sample Sharpe, trades) and the 8-attribute mini bars. Strategy page order, as before: header (family, rules, parameter chips) / key figures (8) + semicircle score gauge / how it was tested (sentence, 70-30 split bar, chips) / account growth (curve, with a switch to trades on candles) + backtest trade stats + share eaten by costs / return by year / return by month with Total column (last 3 years / all) / gauge breakdown in 3 columns / criteria as sentences with a check or cross and the value.
- Propias merged into Ranking (2026-11-12): no Propias tab (tabs: Hoy, Demo, Ranking, Sistema, Glosario, Mercado). Ranking has a selector Barrido / Propias; Propias view: strategy selector (ejemplo / manual), summary (best variant, tested, pass validator, exam or demo), funnel + night-by-night evolution, the advisor's direction, filters, and experiments as Ranking-style cards (circle = profit factor by band 1.3+ / 1.0 / 0.9 / <0.9, 8 figures, 9 criteria squares). Experiment page uses the same Darwinex structure (header with reason and folded technical changes, key figures + profit-factor gauge with the 1.0 mark, how it was tested, criteria as sentences).
- Own strategies use the same analysis as the sweep ones, with three differences (owner, 2026-11-12): (1) always labelled "solo entrenamiento, hasta 2023", since the later years are the exam and the lab must not see them; (2) the exam appears only once a variant passes the validator, then "Entrenamiento, examen y confirmación" side by side; (3) each experiment page opens with the comparison against the original and the best variant ("frente a tu original: +0,28 por euro perdido, 2 % menos de caída"). Also compute the Quant score, the 8-attribute mini bars and the return by year and month for own variants on their training years, so their cards look like the sweep cards.
- Sistema merged into Hoy (2026-11-12): no Sistema tab (tabs: Hoy, Demo, Ranking, Glosario, Mercado). After Hoy's panel, a "Sistema" block: freshness (last night, demo prices, test run, backup), last night stage by stage with durations, scheduled tasks with last and next run. "Anoche" links to it.
- Order on every strategy or experiment page: the Darwinex analysis first, then "Lo nuevo: por qué gana o pierde" with only the parts not already shown: trades on candles (experiments), the edge map (hour x weekday; minimum 20 trades per cell, 5 when the strategy has under 1,000 trades, flagged as orientative) and the six figure groups. The separate "share eaten by costs" bar is dropped because group 1 answers it.
- Strategy page keeps the previous Darwinex-style analysis, restyled: key figures, score gauge with the eight attributes and their reasons, return by year (bars) and by month (heat grid, last 10 years / all), criteria in words (value vs threshold, cumple / no cumple), how it was tested (in-sample vs out-of-sample, costs x2, neighbours, Monte Carlo), plus rules in words, trades on candles and the share eaten by costs.
- Propias: working strategy selector (ejemplo / manual); every section follows the selected strategy; full experiment history with filters (search, result, night, minimum profit factor, minimum trades, sort) and a page per experiment (figures, changes in words with the technical list folded, why the lab tried it, how it was tested, criteria in words).
- Filters everywhere, above all in Ranking: search, verdict, market (crypto / indices / stocks), family, timeframe, minimum score, sort by score / profit factor / annual return, "Quitar filtros", and a live count ("36 de 300 estrategias"). Demo: filter by label (controles / aprobadas / en prueba). Glosario: search. Propias (later): filter the experiment history.

## Direction
Design Read: a private trading desk for one non-expert: dark and quiet, one big number you can trust at a glance, every figure said in plain words.
Mode: Operate · Dials: variance 3 / motion 2 / density 5 (Operate's 7 lowered to 5 because the brief asks not to be overwhelmed).
Palette (dark; neutrals carry the blue-slate hue):
- fondo = #0F1522 (page background)
- superficie = #172033 (cards)
- linea = #2A3650 (dividers only; decorative, 1.35:1)
- tinta = #E9EEF6 (15.66:1 on fondo, 13.96:1 on superficie)
- tinta_suave = #9AA7BC (7.5:1 / 6.68:1)
- acento = #7AAEFF (links, focus, active tab; 8.1:1 / 7.22:1)
- sube = #3CC796 (gains; 8.52:1 / 7.59:1)
- baja = #F2727A (losses; 6.49:1 / 5.78:1)
- aviso = #E9B453 (warnings; 9.66:1 / 8.61:1)
Typography: Geist for everything (display 34/600, headings 17/600, body 15/400, small 13/400), tabular figures for every number; no monospace labels.
Spacing: 4, 8, 12, 16, 24, 32, 48.
Radii: 14 cards, 8 controls, 999 pills and the "?" button.
Signature element: the demo result as one large Revolut-style figure with its TradingView-style area curve right under it. Everything else stays quiet.
Hoy skeleton: status line (full width) · demo figure + curve (wide) with open positions as Revolut rows (narrow) · own strategies, each as one row with a scale marking 1.0 (the break-even line) · last night as a short list of stages.
Why it is not the generic answer: GitHub-style greys, coloured pills and a KPI row of six equal tiles are replaced by one figure and lists read top to bottom; green/red are reserved for money and the 1.0 line; no traffic-light dots as decoration.

## Content decisions (owner, 2026-11-12)
Global
- Plain words on Hoy ("gana 1,03 € por cada euro que pierde"); technical terms on detail pages; every figure: short line always visible + "?" with a deep explanation and a link to its Glosario entry.
- Tabs, in order: Hoy, Demo (new), Propias, Ranking, Sistema, Glosario, Mercado (Mercado keeps its own look).
- Hoy auto-reloads every 2 minutes and shows the time of the last update.

Hoy, top to bottom
1. Status, three levels: "Todo en orden" (night finished, demo checked prices in the last 26 h) / "Hay algo que mirar" (a new warning, a stage with warnings, or the lab with no experiments) / "Algo falló" (a stage did not finish, demo >26 h without checking, or the panel cannot read data). Warnings repeated unchanged for several days collapse into one quiet line ("3 avisos conocidos"); only new ones stand out.
2. Demo: large figure = closed + open at last price; under it, the closed part alone; one line comparing own strategies vs buy-and-hold controls. Daily curve (rebuilt from 3 Nov from stored trades and daily prices) with the backtest's expected band shaded behind it; period buttons (1 semana / 1 mes / Todo, default Todo; a button appears only when it has enough days). Open positions beside it as Revolut rows.
3. Own strategies: best variant with >=200 trades, bar with the 1.0 mark, a small line of how that best result evolved night by night, and its phase (entrenamiento / validador / examen / demo).
4. Last night: a short summary written by the panel from the data (fixed sentences, exact), links to Sistema and to the Relator's report.
5. What happens next ("Esta noche a la 01:00 ...; el domingo, informe del asesor").

Per page
- Demo: the 7 strategies as rows (what they are, result so far, trades, hit rate, result vs backtest expectation, open position); when a strategy gets retired, in words; costs paid; worst drawdown so far vs the backtest's worst; list of closed trades.
- Propias (next page to redo after Hoy): lab funnel (propuestas > probadas > pasan validador > examen > demo); best variant described in words as changes vs the base; edge map drawn as a colour grid (hour, weekday, side); best variant's curve and its trades on a candlestick chart (TradingView style, entry/exit markers); the advisor's direction in one sentence and whether the lab follows it.
- Ranking: each family in one sentence; why the best ones fail (most frequent failing criterion); the last sweep (moved here from Hoy).
- Strategy page: rules in words; trades on a candlestick chart with markers; share of gross profit eaten by costs.
- Sistema: freshness of each data source (last prices, last backup, last night, last test run); next run of each scheduled task.
- Glosario: linked from every "?"; adds the new terms (mapa de ventajas, asesor, fase).

Strategy figures to add (all six groups; most come from the backtest trades that already exist)
1. Is each trade worth it: average gain per unit risked (R); share of gross profit eaten by costs; cost per trade vs average gain per trade, in index points.
2. Are stop and target well placed: how far a trade goes against before it ends (MAE); how far it went in favour before closing (MFE, profit left on the table); how trades end (% target / stop / opposite signal / session close).
3. Could the owner stand trading it: longest losing streak; longest time without a new equity high; trades per week and share of days with a trade.
4. Real or luck: probability the result is luck (from the R per trade and the number of trades); parameter stability (neighbouring values give similar results = plateau, reliable; only one exact value works = peak, likely chance), using the neighbours the lab already tests; training vs exam side by side once there is an exam.
5. When it works: trend days vs range days, high vs low volatility; by hour, weekday and side (the edge map).
6. Does it add anything: correlation with buy-and-hold SP500 and with the other own strategies.

## Technical
Stack: server-rendered HTML from Python (`codigo/quant/panel/`), no framework; CSP `default-src 'self'; style-src 'self'` (no inline `style=`, no `<style>`). Lightweight Charts 4.2.0 (local, `attributionLogo: false`, credit in the chart help). Geist variable woff2 self-hosted in `static/fonts/` (OFL).
Structure (plan 13): `static/panel.css` (tokens on `:root`, then new pieces, then the old class names restyled until plans 14-16), `piezas.py` (header + ticker + sliding lines, `ayuda`, `cifra`, `selector`, `spark`, `barra_uno`, `graficos`), `static/graficos.js` (charts from a JSON spec; `[data-g]`/`[data-vista]` view switch, `[data-p]` periods), `hoy_datos.py` (demo curve, band, open positions, status, night summary, next runs, own-strategy progress), `paginas.hoy` + `_sistema_bloque`.
Charts: UTC times, formatted in Madrid time by the browser (DST-safe). Caches: demo curve per catalog stamp and hour, manual candles per hour, ticker per day.

Plan 14: `investigacion/analisis.py` (six groups + edge map from one backtest, pure), table `panel_analisis (clave 'r:<resultado_id>' | 'e:<experimento_id>', json, creado)` filled by `panel/precalcular.py` for pass/doubtful results (45-minute budget; first run: 357 in a few minutes, 0 errors); other strategies get it on demand, cached in memory. `panel/ficha_html.py` holds the Ranking card and strategy-page pieces (score circle and gauge, mini bars, year bars, month heat, gauge breakdown, criteria, edge map, six groups). Colour intensity uses classes by band (`h-*`, `m-*`), never inline styles.

Plan 15: Propias is a view of Ranking (`/propias?estrategia=`; the tab is gone). Experiments are computed on training years only (`ficha_stats.ejecutar(..., hasta=corte)`, `precalcular.analisis_de(..., hasta=)`); `panel_analisis` `e:<id>` is filled by `precalcular.precalcular_lab`, called after the lab stage each night (15 min, never past the night's deadline). Experiment pages compute what is missing on demand (4-7 s first view). The exam block only shows for variants that pass the validator.

Plan 16: Demo tab (`paginas.demo`, `/demo`): reuses `_demo_hoy` (curve, summary, open positions) so its totals match Hoy; rows come from `demo_strategies` (active and retired), the label filter is a link selector (`?etiqueta=`) that also filters the closed trades; "Frente al backtest" uses `_frente_backtest` with the same rule and the same backtest sample as the nightly drift check (`noche._backtest_fractions`: bars before the strategy joined the demo; compared once it reaches `drift_min_trades` or `drift_min_weeks`); controls are not judged; the retirement text is built from `config/demo.json`. Glossary: one `GLOSARIO` list (group, term, definition, "En Quant" example) in six groups, articles with `id=<slug>` so every "?" link lands on its term (a test walks the links of Hoy, Demo, Ranking, a strategy, Propias and an experiment); the `:target` term gets an outline. Pages without `combinations` (fresh catalog) render empty instead of failing.

## Audit
Date: 2026-11-12 (plan 13, real panel, playwright at 1366×900 and 375×800).
- Horizontal scroll: none on Hoy, Ranking, Propias, Glosario, Mercado at both widths.
- Text contrast (computed, every text node against its effective background): no pair below 4.5:1.
- Focus: visible 2 px outline on tabs and "?" buttons; popovers open with click and close with Escape.
- Reduced motion: header lines stop (`animation-name: none`).
- Console: no errors after disabling the TradingView logo (it injected a `<style>` blocked by CSP).
- Fixed during the audit: curve collapsed to one instant (second-resolution timestamps in the Madrid shift), stray header "?" button, stretched rounded SVG bars.
- vs mock-up (non-data differences): expected-band lines added to the curve; Sistema block uses the new tables; old pages (Ranking, Propias, Glosario) keep their old layout on the new tokens until plans 14-16.
Accessory removed: the stage bars' rounded ends.

Plan 14 (2026-11-12, real panel, 1366×900 and 375×800): Ranking (first page, filtered second page, empty result), the ETHUSDT H4 strategy page and a non-passing one.
- Horizontal scroll: none. Console: no errors.
- Contrast: strong heat and map cells failed (2.5–4.0); fixed by lowering the alpha of level 4 heat and level 3 map cells and using dark text on the strongest map cells. All pages now ≥ 4.5:1.
- Fixed during the audit: key figures inherited the old verdict pill style; whole numbers showed as "122,00"; the raw technical title line was removed.
- vs mock-up: the candle chart draws trades without the family's own indicators; the edge map of D1/H4 strategies has few cells (entries fall on bar opens), as expected.

Plan 15 (2026-11-12, real panel, 1366×900 and 375×800): Propias for both strategies (filtered second page, empty result), experiments #1117 and #570.
- Horizontal scroll: none. Contrast: no pair below 4.5:1. Console: no errors.
- Fixed during the audit: "12 cambios" next to "Ver los 16 cambios técnicos" (a replacement is one change but two lines); the summary now reads "Ver el detalle de los cambios".
- vs mock-up: "En la demo" in the path shows "–" (no catalog link yet); the "closest to winning" block was dropped in favour of the best variant and the cards.

Plan 16, final audit (2026-11-12, real panel, playwright at 320, 375, 768, 1366 and 1920 px): Hoy, Demo (all and one label), Ranking, a strategy page, Propias, experiment #570, Glosario, Mercado.
- Horizontal scroll: none at any width. Contrast: no pair below 4.5:1. Console: no errors.
- Focus: visible on tabs, selectors, filters and "?"; popovers open on click and close with Escape. Reduced motion: header lines stop. Glossary search filters terms and hides empty groups.
- Empty catalog: every tab answers 200 and missing strategies/experiments 404 (test); Demo and Ranking used to fail without the `combinations` table.
- Fixed during the audit: Demo table logos sat above their names (missing `td .con-logo` rule); the glossary grid painted the empty last cell grey.
- Unused CSS removed: 49 rules for classes no page emits any more (old cards, KPI rows, hero blocks, verdict pills, old glossary).
Accessory removed: the group label on every glossary term (the group heading already says it).
