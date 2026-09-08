# Free Strategy Contract

The Free runtime creates a deterministic Strategy Contract before generating signals. It records the symbol, timeframe, indicators, entry and exit rules, long/cash position mode, signal timing, execution method, costs, benchmark, normalized description, and contract hash.

Supported indicators are EMA, SMA, and RSI only.

Supported rules are:

- `close > EMA<n>` for long and `close < EMA<n>` for cash.
- `close > SMA<n>` for long and `close < SMA<n>` for cash.
- `RSI<n> < lower_threshold` for long and `RSI<n> > upper_threshold` for cash.

The runtime rejects unsupported strategy types rather than translating them to a different rule.
