# Zeyang Strategy Lab Free

Zeyang Strategy Lab Free is a local tool for historical strategy research and teaching validation. It uses your local CSV data; it does not fetch market data automatically and it does not place orders.

## Current scope

- Single asset, long/cash historical research.
- Daily bars.
- EMA, SMA, and RSI.
- Close-versus-EMA/SMA rules and RSI threshold rules.
- Basic commission and slippage assumptions.
- Buy-and-hold comparison.
- Total return, CAGR where applicable, maximum drawdown, exposure, trade count, and basic equity/drawdown charts.

Free does not support MACD, Bollinger Bands, crossover/crossunder rules, shorting, leverage, minute data, multi-asset portfolios, parameter optimization, or professional Word research reports.

## Install

Use Python 3.10 or later. The basic PNG charts require Pillow:

```text
python -m pip install Pillow
```

## Input CSV

Provide a local daily CSV. `date` and `close` are required. `open` is optional: the default `next_open` execution uses the next bar's `open` when available; when it is absent, the runtime formally falls back to the next bar's `close` and records a warning. `high`, `low`, `volume`, and one `symbol` are recommended. If `symbol` is supplied, the file must contain one asset only. Dates must be ISO-8601 compatible. See [references/data-contract.md](references/data-contract.md).

## EMA20 example

```text
python scripts/run_free_research.py --strategy "回测 TEST 日线 EMA20，收盘价高于 EMA20 持仓，低于 EMA20 空仓。" --input ./my_prices.csv
```

## RSI14 example

```text
python scripts/run_free_research.py --strategy "回测 TEST 日线 RSI14 低于 30 买入，高于 70 卖出。" --input ./my_prices.csv
```

## Output

Each run creates a local `runs/free-<run-id>/` directory containing the Strategy Contract, generated signals, validation result, backtest JSON, trade ledger, Markdown summary, and two basic charts. These files are local research artifacts and should not be committed by default.

## Research-only notice

Historical results do not predict future performance. Confirm data provenance, adjustment basis, transaction assumptions, and strategy timing before interpreting any result. This tool is for research and education only, not investment advice.

## License

Zeyang Strategy Lab Free is licensed under AGPL-3.0-only. See [LICENSE](LICENSE).

The commercial Pro edition is separately licensed and is not included in this repository.

## Contributions

For the initial public beta, issues and feedback are welcome.
Code contributions are not currently being accepted.
