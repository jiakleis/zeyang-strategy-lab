#!/usr/bin/env python3
"""Shared EMA/SMA/RSI indicator and long/cash signal core for Free and Pro."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


ENGINE_VERSION = "indicator_signal_v1"
BASIC_INDICATORS = frozenset({"EMA", "SMA", "RSI"})


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if period <= 0:
        raise ValueError("EMA period must be positive")
    alpha = 2.0 / (period + 1.0)
    previous: float | None = None
    for index, value in enumerate(values):
        previous = value if previous is None else alpha * value + (1.0 - alpha) * previous
        result[index] = previous
    return result


def sma(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    window: list[float] = []
    for index, value in enumerate(values):
        window.append(value)
        if len(window) > period:
            window.pop(0)
        if len(window) == period:
            result[index] = sum(window) / period
    return result


def rsi(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result
    gains = [max(values[index] - values[index - 1], 0.0) for index in range(1, len(values))]
    losses = [max(values[index - 1] - values[index], 0.0) for index in range(1, len(values))]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def value() -> float:
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    result[period] = value()
    for index in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[index - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index - 1]) / period
        result[index] = value()
    return result


def calculate_indicators(rows: list[dict[str, Any]], indicators: list[dict[str, Any]]) -> dict[str, list[float | None]]:
    closes = [float(row["close"]) for row in rows]
    output: dict[str, list[float | None]] = {}
    for indicator in indicators:
        kind = indicator["type"]
        identifier = indicator["id"]
        if kind == "EMA":
            output[identifier] = ema(closes, int(indicator["period"]))
        elif kind == "SMA":
            output[identifier] = sma(closes, int(indicator["period"]))
        elif kind == "RSI":
            output[identifier] = rsi(closes, int(indicator["period"]))
        else:
            raise ValueError(f"Free Core 不支持指标：{kind}")
    return output


def _operand(operand: Any, index: int, values: dict[str, list[float | None]], rows: list[dict[str, Any]]) -> float | None:
    if isinstance(operand, (int, float)):
        return float(operand)
    if operand == "close":
        return float(rows[index]["close"])
    if operand == "open":
        return _float(rows[index].get("open"))
    if isinstance(operand, str) and operand in values:
        return values[operand][index]
    return None


def _comparison(left: float | None, operator: str, right: float | None) -> bool | None:
    if left is None or right is None:
        return None
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == "==":
        return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
    raise ValueError(f"不支持比较运算符：{operator}")


def evaluate(rule: dict[str, Any], index: int, values: dict[str, list[float | None]], rows: list[dict[str, Any]]) -> bool | None:
    kind = rule.get("type", "comparison")
    if kind == "comparison":
        return _comparison(_operand(rule.get("left"), index, values, rows), rule["operator"], _operand(rule.get("right"), index, values, rows))
    raise ValueError(f"Free Core 不支持规则类型：{kind}")


def generate_signals(rows: list[dict[str, Any]], contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    values = calculate_indicators(rows, contract["indicators"])
    signals: list[dict[str, Any]] = []
    position = 0.0
    warmup = 0
    for indicator in contract["indicators"]:
        if indicator["type"] in {"SMA", "RSI"}:
            warmup = max(warmup, int(indicator.get("period", 0)))
    for index, row in enumerate(rows):
        entry = evaluate(contract["entry_rule"], index, values, rows) if index >= warmup else None
        exit_rule = evaluate(contract["exit_rule"], index, values, rows) if index >= warmup else None
        if exit_rule is True:
            position = 0.0
        elif entry is True:
            position = 1.0
        item = dict(row)
        item["signal"] = position
        item["indicators"] = {key: value[index] for key, value in values.items()}
        signals.append(item)
    return signals, {"warmup_bars": warmup, "indicator_columns": sorted(values), "rows": len(signals)}


def write_signal_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["date", "open", "high", "low", "close", "volume", "adj_close", "signal"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "date": row["date"].isoformat(),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume", ""),
                "adj_close": row.get("adj_close", ""),
                "signal": row["signal"],
            })
