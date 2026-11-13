# Quant

**A self-hosted trading-research lab in Python, run every night by AI agents.**

[![Support on PayPal](https://img.shields.io/badge/Support%20this%20project-PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/IkerGonzalezRP)

> ☕ **Quant is free and open source.** It is built and maintained in my spare time, and every night it runs on my own Claude subscription and hardware. If it saves you time or teaches you something, a small contribution keeps it going: **[paypal.me/IkerGonzalezRP](https://paypal.me/IkerGonzalezRP)** (or PayPal to ikerchup.g@gmail.com). Thank you!

Quant runs on your own computer. Every night it:

1. **Downloads prices** (Yahoo, Dukascopy, Binance) for a universe of indices, currencies, commodities, stocks and crypto.
2. **Reads public documents** (arXiv, Quantpedia, MQL5, Reddit) with AI agents that extract the trading ideas and turn them into **fichas**: exact rules the engine can run.
3. **Tests every ficha** with a backtest engine that charges real costs (commission, spread and slippage) and a **validator** with fixed criteria: maximum drawdown, out-of-sample years, parameter robustness, doubled costs, Monte Carlo and a buy-and-hold comparison.
4. **Sweeps classic strategy families** (moving-average crosses, breakouts, mean reversion, momentum...) across the whole universe and ranks them with a 0–100 score.
5. **Improves your own strategies** in a lab: an agent proposes variants every night, they are measured on the training years only, and the final exam uses years the agent never sees.
6. **Paper-trades** the strategies that pass, with fake money and real prices, and retires the ones that drift away from their backtest.
7. **Explains everything** in a local web panel made for non-programmers: what happened, why each strategy wins or loses, and what every number means (with a glossary).

> **Disclaimer.** This is a personal research and learning project. It is not financial advice, it never trades real money, and backtest results guarantee nothing about the future.

> **Language.** The code and the docs are in English. The panel, the reports and the agents' outputs are in Spanish.

## Requirements

- **Windows 10 or 11** (the nightly jobs use Task Scheduler; everything else runs on any system with Python).
- **Python 3.12 or newer** (developed on 3.14).
- **[Claude Code](https://claude.com/claude-code)** installed and logged in to your subscription: the nightly agents call it with `claude -p`. Without it the engine, the sweep, the demo and the panel still work; only the agent stages are skipped.
- About 20 GB of free disk space for prices.

## Installation

```powershell
git clone https://github.com/ikertxuletas/nightshift-quant.git Quant
cd Quant
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r codigo\requirements.txt
.venv\Scripts\python.exe -m pip install -e codigo
```

Check that everything works (it takes a minute; some tests are skipped until you have real prices):

```powershell
cd codigo
..\.venv\Scripts\python.exe -m pytest -q
```

Sign the validator criteria. Quant refuses to validate if `config/criterios.json` changes without being signed again:

```powershell
..\.venv\Scripts\python.exe -m quant.criterios --firmar
```

## First steps

From the `codigo` folder:

```powershell
# 1. Prices (the first run takes hours; afterwards it only downloads what is new)
..\.venv\Scripts\python.exe -m quant.actualizar --fuente yahoo
..\.venv\Scripts\python.exe -m quant.actualizar

# 2. Family sweep (you can cap it: --horas 2)
..\.venv\Scripts\python.exe -m quant.barrido --horas 2

# 3. Panel at http://127.0.0.1:20135
..\.venv\Scripts\python.exe -m quant.panel.servidor
```

The panel only listens on your computer and asks for a key generated at startup, in `registro/panel_clave`. Open it once with `http://127.0.0.1:20135/?key=<the key>` and the browser will remember it.

To run everything on its own every night, install the scheduled tasks from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File codigo\instalar_tareas.ps1
```

This creates: the night run at 02:00 (prices, agents, lab, demo and report), the review at 06:15, a watchdog at 07:30, the demo every hour, the sweep on Saturdays and the panel at logon. If you have several computers and want the night to run on only one, set the `QUANT_EQUIPO` environment variable to that computer's name.

## How it is organised

| Folder | What is inside |
|---|---|
| `codigo/quant/` | Backtest engine, validator, indicators, costs, data and universe |
| `codigo/quant/familias/` | Strategy families for the sweep and your own strategies (`propias.py`) |
| `codigo/quant/investigacion/` | The night: agents (reader, formaliser, critic, reporter, mentor), lab, advisor, review and diagnostics |
| `codigo/quant/demo/` | Paper demo: selection, orders, safety net and drift against the backtest |
| `codigo/quant/panel/` | Local web panel (HTML generated in Python, no framework) |
| `skills/` | The instructions of each nightly agent |
| `config/` | Universe, costs, validator criteria and demo |
| `examen/` | A fixed exam that measures whether the agents read well: hand-written correct answers and the link to each document |
| `roles/`, `CLAUDE.md` | How the Claude Code sessions that maintain the project split the work |

## Adding your own strategies

Your own strategies do not enter the sweep: the lab works on them every night. Two public examples are included:

- `ejemplo`: Larry Connors' RSI(2), adapted to the S&P 500 on 15-minute bars.
- `manual`: how a manual routine described in words gets translated (a moving-average cross in the direction of the 200 average, with stop and target measured in ATR and an exit before the session closes).

To add yours:

1. Write its family in `codigo/quant/familias/<name>.py` (copy `ejemplo.py`: the ficha describes entries, exits, management and trading hours) and register it in `familias/__init__.py`.
2. Add it to `PROPIAS` in `codigo/quant/familias/propias.py` with its instrument, timeframe and the exam cut-off date (`corte`): the lab never sees the data after it until the final exam.
3. Run the tests. That night the lab will start proposing variants and the panel will show it under Ranking › Propias.

## Contributing

Improvements and bug reports are welcome: open an *issue* or a *pull request*.

## Support the project

If Quant is useful to you, please consider supporting it. Every contribution, however small, helps pay for the nightly AI runs and the time spent improving it.

[![Donate with PayPal](https://img.shields.io/badge/Donate-PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/IkerGonzalezRP)

**PayPal:** [paypal.me/IkerGonzalezRP](https://paypal.me/IkerGonzalezRP) · ikerchup.g@gmail.com

## License

[MIT](LICENSE). Charts use [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/) (Apache 2.0) and the [Geist](https://vercel.com/font) font (OFL), both included in `codigo/quant/panel/static/`.
