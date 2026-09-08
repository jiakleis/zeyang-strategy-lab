#!/usr/bin/env python3
"""Validate historical OHLCV and optional target-signal CSV data."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


NULLS = {"", "na", "n/a", "null", "none", "nan"}
ALIASES = {
    "date": {"date", "datetime", "timestamp", "time"},
    "symbol": {"symbol", "ticker", "code"},
    "open": {"open", "open_price"},
    "high": {"high", "high_price"},
    "low": {"low", "low_price"},
    "close": {"close", "close_price", "last"},
    "adj_close": {"adj_close", "adjusted_close", "adjustedclose"},
    "volume": {"volume", "vol", "turnover_volume"},
    "signal": {"signal", "position", "target_position", "target"},
}


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
    number = float(text)
    if not math.isfinite(number):
        raise ValueError("not finite")
    return number


def find_columns(headers: list[str]) -> dict[str, str]:
    normalized = {normalize(header): header for header in headers if header is not None}
    result: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                result[canonical] = normalized[alias]
                break
    return result


def add_issue(items: list[dict[str, Any]], level: str, code: str, message: str, line: int | None = None) -> None:
    item: dict[str, Any] = {"level": level, "code": code, "message": message}
    if line is not None:
        item["line"] = line
    items.append(item)


def validate(path: Path, naive_timezone: str = "UTC", extreme_move: float = 0.5) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    naive_zone = get_zone(naive_timezone)
    naive_count = 0

    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        return {"status": "fail", "errors": [{"code": "file_open", "message": str(exc)}], "warnings": []}

    with handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        columns = find_columns(headers)
        if "date" not in columns:
            add_issue(errors, "error", "missing_date", "需要 date/datetime/timestamp 字段")
        if "close" not in columns:
            add_issue(errors, "error", "missing_close", "需要 close 字段")
        if errors:
            return {"status": "fail", "columns": columns, "errors": errors, "warnings": warnings}

        previous_by_symbol: dict[str, datetime] = {}
        seen: set[tuple[str, datetime]] = set()
        for line_number, raw in enumerate(reader, start=2):
            symbol = (raw.get(columns.get("symbol", ""), "") or "").strip() or "__single__"
            try:
                timestamp, was_naive = parse_datetime(raw.get(columns["date"], "") or "", naive_zone)
                if was_naive:
                    naive_count += 1
            except (TypeError, ValueError) as exc:
                add_issue(errors, "error", "invalid_date", f"无法解析日期：{exc}", line_number)
                continue

            key = (symbol, timestamp)
            if key in seen:
                add_issue(errors, "error", "duplicate_key", f"重复的 symbol/date：{symbol} / {timestamp.isoformat()}", line_number)
                continue
            seen.add(key)
            if symbol in previous_by_symbol and timestamp <= previous_by_symbol[symbol]:
                add_issue(errors, "error", "not_sorted", "数据未按 symbol/date 升序排列", line_number)

            values: dict[str, float | None] = {}
            for field, column in columns.items():
                if field in {"date", "symbol"}:
                    continue
                try:
                    values[field] = parse_number(raw.get(column, "") or "")
                except (TypeError, ValueError) as exc:
                    add_issue(errors, "error", f"invalid_{field}", f"{field} 不是有效数值：{exc}", line_number)
                    values[field] = None

            close = values.get("close")
            if close is None or close <= 0:
                add_issue(errors, "error", "non_positive_close", "close 必须大于 0", line_number)
            for field in ("open", "high", "low"):
                value = values.get(field)
                if value is not None and value <= 0:
                    add_issue(errors, "error", f"non_positive_{field}", f"{field} 必须大于 0", line_number)
            volume = values.get("volume")
            if volume is not None and volume < 0:
                add_issue(errors, "error", "negative_volume", "volume 不得为负", line_number)

            signal = values.get("signal")
            if "signal" in columns:
                if signal is None:
                    add_issue(errors, "error", "invalid_signal", "signal 必须是数值且不得为空", line_number)
                elif signal < 0:
                    add_issue(errors, "error", "negative_signal_unsupported", "V1 仅支持 long/cash；signal 不得为负，不支持做空", line_number)
                elif signal > 1:
                    add_issue(errors, "error", "signal_out_of_range", "signal 必须在 [0, 1] 内", line_number)

            open_price = values.get("open")
            high = values.get("high")
            low = values.get("low")
            if all(value is not None for value in (open_price, high, low, close)):
                assert open_price is not None and high is not None and low is not None and close is not None
                if high < max(open_price, low, close) or low > min(open_price, high, close):
                    add_issue(errors, "error", "ohlc_inconsistent", "OHLC 不满足 high/low 包络关系", line_number)

            rows.append({"line": line_number, "symbol": symbol, "timestamp": timestamp, "values": values})
            previous_by_symbol[symbol] = timestamp

    if not rows:
        add_issue(errors, "error", "empty_data", "文件没有可用数据行")

    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_symbol[row["symbol"]].append(row)

    move_records: list[tuple[str, datetime, datetime, float]] = []
    for symbol, symbol_rows in by_symbol.items():
        timestamps = [row["timestamp"] for row in symbol_rows]
        deltas = [(b - a).total_seconds() / 86400 for a, b in zip(timestamps, timestamps[1:])]
        positive = [delta for delta in deltas if delta > 0]
        if len(positive) >= 3:
            typical = statistics.median(positive)
            for delta, before, after in zip(deltas, timestamps, timestamps[1:]):
                if delta > max(5.0, typical * 3.0):
                    add_issue(warnings, "warning", "date_gap", f"{symbol} 存在较大日期缺口：{before.isoformat()} 到 {after.isoformat()}")
                    break

        previous_close: float | None = None
        previous_date: datetime | None = None
        for row in symbol_rows:
            close = row["values"].get("close")
            if previous_close is not None and close is not None and previous_close > 0:
                move_records.append((symbol, previous_date or row["timestamp"], row["timestamp"], close / previous_close - 1.0))
            if close is not None:
                previous_close = close
                previous_date = row["timestamp"]

    absolute_moves = [abs(item[3]) for item in move_records if abs(item[3]) > 0]
    robust_baseline = statistics.median(absolute_moves) if absolute_moves else 0.0
    # Keep the absolute floor useful when a single bad jump contaminates the
    # median; the robust multiplier is only a secondary signal.
    move_threshold = max(extreme_move, min(1.0, robust_baseline * 8.0))
    extreme_count = 0
    for symbol, before, after, move in move_records:
        if abs(move) > move_threshold:
            add_issue(warnings, "warning", "extreme_move", f"{symbol} {before.date()} 到 {after.date()} 价格变动 {move:+.2%}，请复核复权/拼接/企业行为")
            extreme_count += 1
            if extreme_count >= 20:
                add_issue(warnings, "warning", "extreme_move_truncated", "异常跳变超过 20 条，仅展示前 20 条")
                break

    if naive_count:
        add_issue(warnings, "warning", "naive_timestamp_normalized", f"{naive_count} 个无时区时间已按 {naive_timezone} 解释并统一为 UTC")
    if "open" not in columns:
        add_issue(warnings, "warning", "missing_open", "缺少 open；回测执行将退化为下一根 close")
    if "volume" not in columns:
        add_issue(warnings, "warning", "missing_volume", "缺少 volume；无法做流动性或容量校验")
    if len(rows) < 30:
        add_issue(warnings, "warning", "short_sample", f"样本仅 {len(rows)} 行，统计量不稳定")

    timestamps = [row["timestamp"] for row in rows]
    result = {
        "status": "fail" if errors else ("warn" if warnings else "pass"),
        "file": str(path),
        "columns": columns,
        "rows": len(rows),
        "symbols": sorted(by_symbol),
        "date_range": {
            "start": min(timestamps).isoformat() if timestamps else None,
            "end": max(timestamps).isoformat() if timestamps else None,
        },
        "assumptions": {
            "naive_timezone": naive_timezone,
            "normalized_timezone": "UTC",
            "extreme_move_threshold": extreme_move,
            "signal_checked": "signal" in columns,
        },
        "errors": errors,
        "warnings": warnings,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--output", type=Path, help="写入 JSON 报告")
    parser.add_argument("--force", action="store_true", help="允许覆盖已有 --output 文件")
    parser.add_argument("--naive-timezone", default="UTC", help="无时区时间的解释时区，默认 UTC")
    parser.add_argument("--extreme-move", type=float, default=0.5, help="单期价格变动警告阈值，默认 50%%")
    args = parser.parse_args()
    try:
        if args.output and args.output.exists() and not args.force:
            raise ValueError("输出文件已存在；如需覆盖请显式使用 --force")
        if args.extreme_move <= 0:
            raise ValueError("--extreme-move 必须大于 0")
        report = validate(args.csv_path, args.naive_timezone, args.extreme_move)
    except (OSError, ValueError) as exc:
        report = {"status": "fail", "file": str(args.csv_path), "errors": [{"code": "runtime", "message": str(exc)}], "warnings": []}
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        try:
            args.output.write_text(payload + "\n", encoding="utf-8")
        except OSError as exc:
            report["status"] = "fail"
            report["errors"].append({"code": "output_write", "message": str(exc)})
            payload = json.dumps(report, ensure_ascii=False, indent=2)
            print(payload)
            return 2
    print(payload)
    return 2 if report["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
