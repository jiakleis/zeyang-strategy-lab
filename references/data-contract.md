# Free Data Contract

## Required fields

| Field | Required | Rule |
|---|---:|---|
| `date` | Yes | ISO-8601 compatible date/time; one unique, ascending series |
| `close` | Yes | Numeric and greater than zero |
| `open` | No | Numeric and greater than zero when provided; preferred for next-bar execution |
| `high` / `low` | No | When supplied with OHLC, must be internally consistent |
| `volume` | No | Must not be negative |
| `symbol` | Recommended | At most one non-empty symbol in an input file |
| `adj_close` | No | Record whether adjustments are used for signal or valuation |

Free generates its own long/cash `signal` column. Do not provide multiple symbols in one file, negative signals, short positions, or minute data.

## Local-data responsibility

You provide the local CSV and are responsible for its source, adjustment basis, currency, timezone, gaps, and corporate-action treatment. Free does not download data and does not make data provenance claims on your behalf.

## Timing

Indicators at time `t` may use only information available at or before `t`. The generated target position is executed on the next bar. A next-bar execution rule does not prove that an externally prepared signal avoided look-ahead bias.
