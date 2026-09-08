---
name: zeyang-strategy-lab-free
description: "Run local single-asset historical research with EMA, SMA, or RSI long/cash rules and produce basic JSON, CSV, Markdown, and chart artifacts. Use for research and education, not live trading or investment advice."
---

# Zeyang Strategy Lab Free

Use this skill only for local, single-asset daily historical research with a user-provided CSV. The standard entrypoint is `scripts/run_free_research.py`; require an explicit `--input` path and do not fetch data automatically.

## Supported strategy shape

- EMA or SMA: close above the selected average means long; close below means cash.
- RSI: below a declared lower threshold means long; above a declared upper threshold means cash.
- Long/cash only, with signal at close and execution on the following bar.

Prefer to parse the symbol, daily timeframe, local input file, rule, execution assumption, and cost assumptions from the user's request and input data. Ask the user only when a required field is genuinely missing or the strategy has a material ambiguity. The input CSV requires `date` and `close`; `open` is optional. With the default `next_open` execution, a missing `open` formally falls back to the next bar's `close` and produces a warning. Return the generated Strategy Contract, summary, core metrics, warnings, and artifact paths. State that the result is research only and not investment advice.

## Unsupported requests

Do not search for Pro files, call a Pro runtime, implement an unsupported feature, silently simplify a strategy, or fall back to another rule.

For MACD, Bollinger, cross/crossunder, shorting, leverage, minute data, multi-asset portfolios, or parameter optimization, respond exactly:

```text
Current Free edition does not support this strategy.
```

## Data and interpretation limits

Read [references/data-contract.md](references/data-contract.md) before accepting ambiguous or malformed input. For metric definitions and research limits, read [references/metrics-and-robustness.md](references/metrics-and-robustness.md). Do not claim that execution lag proves an external signal has no look-ahead bias.
