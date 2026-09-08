#!/usr/bin/env python3
"""Run an auditable one-asset target-position backtest on a CSV."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


NULLS = {"", "na", "n/a", "null", "none", "nan"}
FREQUENCY_PERIODS = {"daily": 252, "weekly": 52, "monthly": 12}
MIN_RISK_OBSERVATIONS = 10


def normalize(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def get_zone(name: str):
    if name.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"无法识别时区：{name}") from exc


def parse_datetime(value: str, naive_zone) -> tuple[datetime, bool]:
    text = value.strip()
    if not text:
        raise ValueError("empty date")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    was_naive = parsed.tzinfo is None
    if was_naive:
        parsed = parsed.replace(tzinfo=naive_zone)
    return parsed.astimezone(timezone.utc), was_naive


def parse_number(value: str) -> float | None:
    text = value.strip().lower().replace(",", "")
    if text in NULLS:
        return None
    result = float(text)
    if not math.isfinite(result):
        raise ValueError("not finite")
    return result


def find_column(headers: list[str], *names: str) -> str | None:
    normalized = {normalize(header): header for header in headers}
    for name in names:
        if name in normalized:
            return normalized[name]
    return None


def parse_rows(path: Path, naive_timezone: str, require_signal: bool = True) -> tuple[list[dict[str, Any]], list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    naive_zone = get_zone(naive_timezone)
    naive_count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        date_col = find_column(headers, "date", "datetime", "timestamp", "time")
        close_col = find_column(headers, "close", "close_price", "last")
        open_col = find_column(headers, "open", "open_price")
        high_col = find_column(headers, "high", "high_price")
        low_col = find_column(headers, "low", "low_price")
        volume_col = find_column(headers, "volume", "vol", "turnover_volume")
        adj_close_col = find_column(headers, "adj_close", "adjusted_close", "adjustedclose")
        signal_col = find_column(headers, "signal", "position", "target_position", "target")
        symbol_col = find_column(headers, "symbol", "ticker", "code")
        if not date_col or not close_col or (require_signal and not signal_col):
            required = [("date", date_col), ("close", close_col)]
            if require_signal:
                required.append(("signal", signal_col))
            missing = [name for name, col in required if not col]
            return [], [f"缺少字段：{', '.join(missing)}"], warnings, {
                "has_open": bool(open_col),
                "symbol_column": symbol_col,
                "symbols": [],
                "selected_symbol": None,
            }

        previous: datetime | None = None
        seen: set[datetime] = set()
        symbols_seen: set[str] = set()
        for line, raw in enumerate(reader, start=2):
            raw_symbol = raw.get(symbol_col, "") if symbol_col else ""
            symbol = (raw_symbol or "").strip() or "__single__"
            symbols_seen.add(symbol)
            try:
                timestamp, was_naive = parse_datetime(raw.get(date_col, "") or "", naive_zone)
                close = parse_number(raw.get(close_col, "") or "")
                signal = parse_number(raw.get(signal_col, "") or "")
                open_price = parse_number(raw.get(open_col, "") or "") if open_col else None
                high_price = parse_number(raw.get(high_col, "") or "") if high_col else None
                low_price = parse_number(raw.get(low_col, "") or "") if low_col else None
                volume = parse_number(raw.get(volume_col, "") or "") if volume_col else None
                adj_close = parse_number(raw.get(adj_close_col, "") or "") if adj_close_col else None
            except (TypeError, ValueError) as exc:
                errors.append(f"第 {line} 行解析失败：{exc}")
                continue
            if was_naive:
                naive_count += 1
            if close is None or close <= 0:
                errors.append(f"第 {line} 行 close 必须大于 0")
                continue
            if require_signal and (signal is None or signal < 0 or signal > 1):
                errors.append(f"第 {line} 行 signal 必须在 [0, 1] 内；V1 仅支持 long/cash，不支持做空")
                continue
            if open_price is not None and open_price <= 0:
                errors.append(f"第 {line} 行 open 必须大于 0")
                continue
            if timestamp in seen:
                errors.append(f"第 {line} 行日期重复：{timestamp.isoformat()}")
                continue
            if previous is not None and timestamp <= previous:
                errors.append(f"第 {line} 行日期未严格升序")
            previous = timestamp
            seen.add(timestamp)
            rows.append({"line": line, "date": timestamp, "close": close, "open": open_price, "high": high_price, "low": low_price, "volume": volume, "adj_close": adj_close, "signal": signal})

    visible_symbols = sorted(symbol for symbol in symbols_seen if symbol != "__single__")
    if len(symbols_seen) > 1:
        labels = ", ".join(sorted(symbols_seen))
        errors.append(f"当前仅支持单标的回测；发现多个 symbol：{labels}。请拆分文件后分别运行")
    selected_symbol = visible_symbols[0] if len(symbols_seen) == 1 and visible_symbols else None

    if not rows:
        errors.append("文件没有可用数据行")
    if not open_col:
        warnings.append("缺少 open：执行价格退化为下一根 close；结果更适合探索而非交易估算")
    if naive_count:
        warnings.append(f"{naive_count} 个无时区时间已按 {naive_timezone} 解释并统一为 UTC")
    return rows, errors, warnings, {
        "has_open": bool(open_col),
        "naive_timestamp_count": naive_count,
        "symbol_column": symbol_col,
        "symbols": visible_symbols,
        "selected_symbol": selected_symbol,
    }


def filter_rows(rows: list[dict[str, Any]], start: datetime | None, end: datetime | None) -> list[dict[str, Any]]:
    selected = [row for row in rows if (start is None or row["date"] >= start) and (end is None or row["date"] <= end)]
    if len(selected) < 2:
        raise ValueError("日期筛选后至少需要两根 K 线")
    return selected


def infer_frequency(rows: list[dict[str, Any]]) -> tuple[str, float | None]:
    deltas = [(b["date"] - a["date"]).total_seconds() / 86400 for a, b in zip(rows, rows[1:])]
    positive = [delta for delta in deltas if delta > 0]
    if not positive:
        return "irregular", None
    median_days = statistics.median(positive)
    if median_days < 0.1:
        return "irregular", median_days
    if median_days <= 2:
        return "daily", median_days
    if median_days <= 10:
        return "weekly", median_days
    if median_days <= 45:
        return "monthly", median_days
    return "irregular", median_days


def resolve_frequency(rows: list[dict[str, Any]], requested: str) -> tuple[str, str, int | None, list[str], float | None]:
    inferred, median_days = infer_frequency(rows)
    warnings: list[str] = []
    if requested == "auto":
        selected = inferred
        if median_days is not None and median_days < 0.1:
            warnings.append("检测到日内/高频数据；当前引擎不提供日内年化周期，已将频率降级为 irregular")
    else:
        if median_days is not None and median_days < 0.1:
            selected = "irregular"
            warnings.append("检测到日内/高频数据；当前引擎不提供日内年化周期，已将频率降级为 irregular")
        else:
            selected = requested
        if inferred != "irregular" and inferred != requested:
            warnings.append(f"指定频率 {requested} 与日期间隔推断 {inferred} 不一致，请复核年化口径")
    periods = FREQUENCY_PERIODS.get(selected)
    if periods is None:
        warnings.append("无法可靠推断频率，年化波动率、Sharpe 和 Sortino 将置空")
    return selected, inferred, periods, warnings, median_days


def sample_std(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def safe_ratio(numerator: float | None, denominator: float) -> float | None:
    return numerator / denominator if numerator is not None and denominator else None


def calculate_metrics(curve: list[dict[str, Any]], initial_cash: float, total_turnover: float, trades: int, periods_per_year: int | None, annual_risk_free_rate: float) -> dict[str, Any]:
    equity = [float(point["equity"]) for point in curve]
    returns = [float(point["return"]) for point in curve[1:]]
    start = datetime.fromisoformat(curve[0]["date"])
    end = datetime.fromisoformat(curve[-1]["date"])
    days = max((end - start).total_seconds() / 86400, 0.0)
    years = days / 365.25 if days else 0.0
    final_equity = equity[-1]
    total_return = final_equity / initial_cash - 1.0
    cagr_extrapolated = (final_equity / initial_cash) ** (1.0 / years) - 1.0 if years > 0 and final_equity > 0 else None
    cagr_is_extrapolated = years < 1.0
    cagr = None if cagr_is_extrapolated else cagr_extrapolated

    periodic_rf = 0.0
    if periods_per_year is not None:
        if annual_risk_free_rate <= -1:
            raise ValueError("risk-free-rate 必须大于 -1")
        periodic_rf = (1.0 + annual_risk_free_rate) ** (1.0 / periods_per_year) - 1.0
    excess_returns = [value - periodic_rf for value in returns]
    risk_metrics_suppressed = len(returns) < MIN_RISK_OBSERVATIONS
    std_return = sample_std(returns)
    volatility = std_return * math.sqrt(periods_per_year) if periods_per_year and len(returns) > 1 and not risk_metrics_suppressed else None
    sharpe = statistics.mean(excess_returns) / std_return * math.sqrt(periods_per_year) if periods_per_year and std_return and not risk_metrics_suppressed else None
    downside = [min(value, 0.0) for value in excess_returns]
    downside_dev = math.sqrt(sum(value * value for value in downside) / len(downside)) if downside else 0.0
    sortino = statistics.mean(excess_returns) / downside_dev * math.sqrt(periods_per_year) if periods_per_year and downside_dev and not risk_metrics_suppressed else None

    peak = initial_cash
    max_drawdown = 0.0
    drawdown_start = start
    drawdown_end = start
    current_peak_date = start
    for point in curve:
        point_date = datetime.fromisoformat(point["date"])
        value = float(point["equity"])
        if value > peak:
            peak = value
            current_peak_date = point_date
        drawdown = value / peak - 1.0 if peak else 0.0
        if drawdown < max_drawdown:
            max_drawdown = drawdown
            drawdown_start = current_peak_date
            drawdown_end = point_date

    nonzero = [value for value in returns if abs(value) > 1e-15]
    exposure = statistics.mean(abs(float(point["position"])) for point in curve) if curve else 0.0
    win_rate = len([value for value in nonzero if value > 0]) / len(nonzero) if nonzero else None
    return {
        "total_return": total_return,
        "cagr": cagr,
        "cagr_extrapolated": cagr_extrapolated,
        "cagr_is_extrapolated": cagr_is_extrapolated,
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "risk_metrics_is_suppressed": risk_metrics_suppressed,
        "max_drawdown": max_drawdown,
        "max_drawdown_start": drawdown_start.isoformat(),
        "max_drawdown_end": drawdown_end.isoformat(),
        "calmar": safe_ratio(cagr, abs(max_drawdown)),
        "exposure": exposure,
        "win_rate_nonzero_periods": win_rate,
        "trades": trades,
        "turnover_position_change": total_turnover,
        "observations": len(curve),
        "calendar_days": days,
        "sample_years": years,
    }


def simulate(rows: list[dict[str, Any]], targets: list[float], initial_cash: float, commission_bps: float, slippage_bps: float, liquidate: bool, execution_price: str) -> tuple[list[dict[str, Any]], float, int, list[str], dict[str, float], list[dict[str, Any]]]:
    if len(rows) < 2:
        raise ValueError("至少需要两根 K 线")
    if len(targets) != len(rows):
        raise ValueError("targets 长度必须与 rows 一致")
    if initial_cash <= 0:
        raise ValueError("initial_cash 必须大于 0")
    if commission_bps < 0 or slippage_bps < 0:
        raise ValueError("成本不能为负")

    warnings: list[str] = []
    commission_rate = commission_bps / 10000.0
    slippage_rate = slippage_bps / 10000.0
    equity = initial_cash
    held = 0.0
    total_turnover = 0.0
    trades = 0
    commission_total = 0.0
    slippage_total = 0.0
    trades_ledger: list[dict[str, Any]] = []
    fallback_used = False
    curve: list[dict[str, Any]] = [{"date": rows[0]["date"].isoformat(), "equity": equity, "position": held, "return": 0.0}]

    for index in range(1, len(rows)):
        row = rows[index]
        previous_close = rows[index - 1]["close"]
        if execution_price == "next_open" and row["open"] is not None:
            fill_price = row["open"]
        else:
            fill_price = row["close"]
            if execution_price == "next_open" and not fallback_used:
                warnings.append("缺少 open：next_open 已退化为 next_close")
                fallback_used = True

        equity_before_trade = equity * (1.0 + held * (fill_price / previous_close - 1.0))
        target = float(targets[index - 1])
        if target < 0 or target > 1:
            raise ValueError("V1 仅支持 [0, 1] 的 long/cash signal，不支持负仓位或杠杆")
        delta = target - held
        turnover = abs(delta)
        commission_cost = equity_before_trade * turnover * commission_rate
        slippage_cost = equity_before_trade * turnover * slippage_rate
        trade_cost = commission_cost + slippage_cost
        equity_after_trade = equity_before_trade - trade_cost
        if equity_after_trade <= 0:
            raise ValueError(f"第 {row['line']} 行后资金非正，可能是成本参数错误")
        equity = equity_after_trade * (1.0 + target * (row["close"] / fill_price - 1.0))
        if abs(delta) > 1e-12:
            trades += 1
            commission_total += commission_cost
            slippage_total += slippage_cost
            trades_ledger.append({
                "date": row["date"].isoformat(),
                "side": "buy" if delta > 0 else "sell",
                "from_position": held,
                "to_position": target,
                "position_change": delta,
                "turnover": turnover,
                "fill_price": fill_price,
                "equity_before_trade": equity_before_trade,
                "commission": commission_cost,
                "slippage": slippage_cost,
                "total_cost": trade_cost,
                "liquidation": False,
            })
        total_turnover += turnover
        held = target
        curve.append({"date": row["date"].isoformat(), "equity": equity, "position": held, "return": 0.0})

    liquidation_cost = 0.0
    if liquidate and abs(held) > 1e-12:
        liquidation_turnover = abs(held)
        liquidation_commission = equity * liquidation_turnover * commission_rate
        liquidation_slippage = equity * liquidation_turnover * slippage_rate
        liquidation_cost = liquidation_commission + liquidation_slippage
        liquidation_equity_before = equity
        equity -= liquidation_cost
        if equity <= 0:
            raise ValueError("期末平仓后资金非正，可能是成本参数错误")
        trades += 1
        total_turnover += liquidation_turnover
        commission_total += liquidation_commission
        slippage_total += liquidation_slippage
        trades_ledger.append({
            "date": rows[-1]["date"].isoformat(),
            "side": "sell",
            "from_position": held,
            "to_position": 0.0,
            "position_change": -held,
            "turnover": liquidation_turnover,
            "fill_price": rows[-1]["close"],
            "equity_before_trade": liquidation_equity_before,
            "commission": liquidation_commission,
            "slippage": liquidation_slippage,
            "total_cost": liquidation_cost,
            "liquidation": True,
        })
        curve[-1]["equity"] = equity
        curve[-1]["position"] = 0.0
    for index in range(1, len(curve)):
        curve[index]["return"] = curve[index]["equity"] / curve[index - 1]["equity"] - 1.0
    if liquidation_cost:
        warnings.append(f"末日平仓成本已计入：{liquidation_cost:.6f}")
    return curve, total_turnover, trades, warnings, {
        "commission": commission_total,
        "slippage": slippage_total,
        "total": commission_total + slippage_total,
    }, trades_ledger


def add_drawdown_series(curve: list[dict[str, Any]], initial_cash: float) -> list[dict[str, Any]]:
    peak = initial_cash
    series: list[dict[str, Any]] = []
    for point in curve:
        equity = float(point["equity"])
        peak = max(peak, equity)
        drawdown = equity / peak - 1.0 if peak else 0.0
        point["drawdown"] = drawdown
        series.append({"date": point["date"], "drawdown": drawdown})
    return series


def sign_agreement(pairs: list[tuple[float, float]]) -> float | None:
    useful = [(signal, change) for signal, change in pairs if abs(signal) > 1e-12 and abs(change) > 1e-15]
    if not useful:
        return None
    return sum(1 for signal, change in useful if signal * change > 0) / len(useful)


def diagnose_signal(rows: list[dict[str, Any]]) -> dict[str, Any]:
    same_pairs: list[tuple[float, float]] = []
    next_pairs: list[tuple[float, float]] = []
    for index in range(1, len(rows)):
        same_pairs.append((rows[index]["signal"], rows[index]["close"] / rows[index - 1]["close"] - 1.0))
    for index in range(len(rows) - 1):
        next_pairs.append((rows[index]["signal"], rows[index + 1]["close"] / rows[index]["close"] - 1.0))
    same = sign_agreement(same_pairs)
    following = sign_agreement(next_pairs)
    suspected = bool(following is not None and same is not None and following >= 0.75 and following - same >= 0.20)
    return {
        "method": "sign_agreement_heuristic",
        "same_period_sign_agreement": same,
        "next_period_sign_agreement": following,
        "suspected": suspected,
        "note": "这是人工复核提示，不是信号来源的形式化证明。",
    }


def unique(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def run(rows: list[dict[str, Any]], initial_cash: float, commission_bps: float, slippage_bps: float, liquidate: bool, execution_price: str, requested_frequency: str, annual_risk_free_rate: float, signal_source: str, signal_rule: str | None) -> dict[str, Any]:
    selected_frequency, inferred_frequency, periods, frequency_warnings, median_days = resolve_frequency(rows, requested_frequency)
    if commission_bps == 0 and slippage_bps == 0:
        frequency_warnings.append("手续费和滑点均为 0；结果可能过于乐观")
    if periods is not None and len(rows) < periods:
        frequency_warnings.append(f"样本少于一个 {selected_frequency} 年化周期（{periods} 个观测），统计量有限")

    strategy_targets = [row["signal"] for row in rows]
    if any(target < 0 or target > 1 for target in strategy_targets):
        raise ValueError("V1 仅支持 [0, 1] 的 long/cash signal，不支持做空")
    curve, turnover, trades, simulation_warnings, cost_breakdown, trades_ledger = simulate(rows, strategy_targets, initial_cash, commission_bps, slippage_bps, liquidate, execution_price)
    drawdown_series = add_drawdown_series(curve, initial_cash)
    metrics = calculate_metrics(curve, initial_cash, turnover, trades, periods, annual_risk_free_rate)
    if metrics["cagr_is_extrapolated"]:
        frequency_warnings.append("样本不足一年：cagr 已置空，cagr_extrapolated 仅作描述，不能用于排名")

    benchmark_targets = [1.0] * len(rows)
    benchmark_curve, benchmark_turnover, benchmark_trades, benchmark_warnings, benchmark_cost_breakdown, benchmark_trades_ledger = simulate(rows, benchmark_targets, initial_cash, commission_bps, slippage_bps, liquidate, execution_price)
    benchmark_drawdown_series = add_drawdown_series(benchmark_curve, initial_cash)
    benchmark_metrics = calculate_metrics(benchmark_curve, initial_cash, benchmark_turnover, benchmark_trades, periods, annual_risk_free_rate)

    gross_curve, gross_turnover, gross_trades, _, _, _ = simulate(rows, strategy_targets, initial_cash, 0.0, 0.0, liquidate, execution_price)
    add_drawdown_series(gross_curve, initial_cash)
    gross_metrics = calculate_metrics(gross_curve, initial_cash, gross_turnover, gross_trades, periods, annual_risk_free_rate)
    relative = {
        "total_return_difference": metrics["total_return"] - benchmark_metrics["total_return"],
        "cagr_difference": metrics["cagr"] - benchmark_metrics["cagr"] if metrics["cagr"] is not None and benchmark_metrics["cagr"] is not None else None,
        "max_drawdown_difference": metrics["max_drawdown"] - benchmark_metrics["max_drawdown"],
    }

    lookahead = diagnose_signal(rows)
    diagnostics: dict[str, Any] = {
        "signal_provenance": {
            "source": signal_source,
            "rule": signal_rule,
            "verified": False,
            "confidence": "low" if not signal_rule else "documented_but_unverified",
            "note": "引擎只能保证 signal[t] 在 t+1 执行，不能证明外部 signal 的生成过程没有使用未来数据。",
        },
        "lookahead": lookahead,
        "performance_review": {
            "required": bool((metrics["sharpe"] is not None and abs(metrics["sharpe"]) > 3) or (metrics["cagr_extrapolated"] is not None and abs(metrics["cagr_extrapolated"]) > 1) or (metrics["win_rate_nonzero_periods"] is not None and metrics["win_rate_nonzero_periods"] > 0.8)),
            "threshold_note": "极端表现只触发人工复核，不构成前视证明。",
        },
    }
    warnings = list(frequency_warnings) + simulation_warnings + [f"[benchmark] {warning}" for warning in benchmark_warnings]
    if metrics["risk_metrics_is_suppressed"]:
        warnings.append(f"样本少于 {MIN_RISK_OBSERVATIONS} 个收益观测：年化波动率、Sharpe 和 Sortino 已置空")
    if not signal_rule:
        warnings.append("外部 signal 未提供生成规则；前视风险无法由引擎验证")
    if lookahead["suspected"]:
        warnings.append("signal 与下一期收益的方向一致率异常高，请复核是否使用了未来数据")
    if diagnostics["performance_review"]["required"]:
        warnings.append("绩效极端或胜率异常，请复核信号时序、复权口径和成本")

    return {
        "schema_version": "3.0",
        "status": "warn" if warnings else "pass",
        "file": None,
        "assumptions": {
            "execution_lag_bars": 1,
            "execution_price": execution_price,
            "signal_range": [0, 1],
            "position_mode": "long_cash",
            "commission_bps": commission_bps,
            "slippage_bps": slippage_bps,
            "initial_cash": initial_cash,
            "liquidate_at_end": liquidate,
            "risk_free_rate_annual": annual_risk_free_rate,
            "frequency": selected_frequency,
            "inferred_frequency": inferred_frequency,
            "median_interval_days": median_days,
            "annualization_periods": periods,
        },
        "metrics": metrics,
        "gross": {"metrics": gross_metrics},
        "costs": {
            "commission_cost": cost_breakdown["commission"],
            "slippage_cost": cost_breakdown["slippage"],
            "total_cost": cost_breakdown["total"],
            "gross_result": gross_metrics["total_return"],
            "net_result": metrics["total_return"],
        },
        "benchmark": {"name": "buy_and_hold", "metrics": benchmark_metrics, "curve": benchmark_curve, "drawdown": benchmark_drawdown_series, "trades": benchmark_trades_ledger, "costs": benchmark_cost_breakdown},
        "relative": relative,
        "diagnostics": diagnostics,
        "warnings": unique(warnings),
        "errors": [],
        "curve": curve,
        "drawdown": drawdown_series,
        "trades": trades_ledger,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="包含 date、close、signal 的 CSV")
    parser.add_argument("--output", type=Path, help="写入完整 JSON 结果")
    parser.add_argument("--force", action="store_true", help="允许覆盖已有 --output 文件")
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--commission-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--no-liquidate", action="store_true", help="不在最后一根 K 线平仓")
    parser.add_argument("--execution-price", choices=("next_open", "next_close"), default="next_open")
    parser.add_argument("--frequency", choices=("auto", "daily", "weekly", "monthly"), default="auto")
    parser.add_argument("--risk-free-rate", type=float, default=0.0, help="年化无风险利率，例如 0.03")
    parser.add_argument("--start-date", help="包含该日期，ISO-8601")
    parser.add_argument("--end-date", help="包含该日期，ISO-8601")
    parser.add_argument("--naive-timezone", default="UTC", help="无时区时间的解释时区，默认 UTC")
    parser.add_argument("--signal-source", default="external_csv_unverified")
    parser.add_argument("--signal-rule", help="信号生成规则摘要；仅记录，不构成自动验证")
    args = parser.parse_args()

    try:
        if args.output and args.output.exists() and not args.force:
            raise ValueError("输出文件已存在；如需覆盖请显式使用 --force")
        if args.risk_free_rate <= -1:
            raise ValueError("--risk-free-rate 必须大于 -1")
        naive_zone = get_zone(args.naive_timezone)
        rows, errors, parse_warnings, metadata = parse_rows(args.csv_path, args.naive_timezone)
        if errors:
            report = {"status": "fail", "file": str(args.csv_path), "errors": errors, "warnings": parse_warnings, "metadata": metadata}
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2
        start = parse_datetime(args.start_date, naive_zone)[0] if args.start_date else None
        end = parse_datetime(args.end_date, naive_zone)[0] if args.end_date else None
        if start and end and start > end:
            raise ValueError("start-date 不能晚于 end-date")
        rows = filter_rows(rows, start, end)
        report = run(rows, args.initial_cash, args.commission_bps, args.slippage_bps, not args.no_liquidate, args.execution_price, args.frequency, args.risk_free_rate, args.signal_source, args.signal_rule)
        report["file"] = str(args.csv_path)
        report["warnings"] = unique(parse_warnings + report["warnings"])
        report["status"] = "warn" if report["warnings"] else "pass"
        report["metadata"] = {**metadata, "selected_rows": len(rows), "start_date": rows[0]["date"].isoformat(), "end_date": rows[-1]["date"].isoformat()}
    except Exception as exc:
        report = {"status": "fail", "file": str(args.csv_path), "errors": [{"type": type(exc).__name__, "message": str(exc)}], "warnings": []}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        try:
            args.output.write_text(payload + "\n", encoding="utf-8")
        except OSError as exc:
            report["status"] = "fail"
            report["errors"].append({"type": "output_write", "message": str(exc)})
            payload = json.dumps(report, ensure_ascii=False, indent=2)
            print(payload)
            return 2
    print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
