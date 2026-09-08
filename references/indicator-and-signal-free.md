# Free Indicators and Signals

The Free runtime calculates EMA, SMA, and RSI from the input close series using deterministic local code. It evaluates the Strategy Contract on each eligible bar and emits a long/cash target signal in the range `[0, 1]`.

EMA can start from the first observation. SMA and RSI wait for their configured warm-up period. The signal is created at close and passed to the backtest engine for execution on the following bar. The generated CSV retains the input OHLCV fields where available and the target `signal`.

The Free runtime does not implement advanced indicators or crossing rules.
