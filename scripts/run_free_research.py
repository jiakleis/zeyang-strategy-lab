#!/usr/bin/env python3
"""Free runtime: natural-language EMA/SMA/RSI strategy to local research artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import indicator_signal_core
import run_backtest
import strategy_contract_core
import validate_price_data
from basic_charts import chart_line, normalized_equity


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "runs"


def _emit(payload: dict[str, Any], code: int) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


def _failure(stage: str, reason: str, hint: str, progress: list[str]) -> dict[str, Any]:
    return {
        "status": "fail",
        "failed_at": stage,
        "reason": reason,
        "next_action": hint,
        "progress": progress,
    }


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_trades(path: Path, trades: list[dict[str, Any]]) -> None:
    fields = sorted({key for trade in trades for key in trade})
    if not fields:
        fields = ["date", "side", "price", "quantity", "notional", "commission", "slippage", "liquidation"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)


def _write_summary(path: Path, contract: dict[str, Any], backtest: dict[str, Any]) -> None:
    metrics = backtest["metrics"]
    benchmark = backtest["benchmark"]["metrics"]
    costs = backtest["costs"]

    def pct(value: float | None) -> str:
        return "—" if value is None else f"{float(value) * 100:.2f}%"

    text = f"""# {contract['strategy_display_name']}

## 回测摘要

{contract['normalized_summary']}

## 核心结果

- 策略总收益：{pct(metrics.get('total_return'))}
- 买入持有总收益：{pct(benchmark.get('total_return'))}
- CAGR：{pct(metrics.get('cagr'))}
- 最大回撤：{pct(metrics.get('max_drawdown'))}
- 仓位变化次数：{metrics.get('trades', 0)}
- 总交易成本：{costs.get('total_cost', 0.0):,.2f}

## 研究边界

Signal 由本次 Strategy Contract 经确定性 EMA/SMA/RSI 指标与比较规则生成，并在下一根 K 线执行。本摘要仅用于研究，不构成投资建议。
"""
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", required=True, help="自然语言策略描述")
    parser.add_argument("--input", type=Path, required=True, help="用户提供的本地 OHLCV CSV")
    parser.add_argument("--symbol", help="可选，覆盖策略文本中的标的")
    parser.add_argument("--timeframe", choices=("1d", "1w", "1mo"))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--execution", choices=("next_open", "next_close"), default="next_open")
    parser.add_argument("--commission-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--naive-timezone", default="UTC")
    args = parser.parse_args()

    progress: list[str] = []
    understood = strategy_contract_core.understand(
        args.strategy,
        args.symbol,
        args.timeframe,
        args.commission_bps,
        args.slippage_bps,
        args.execution,
    )
    if understood["status"] == "clarification":
        return _emit({"status": "clarification_required", "questions": understood["questions"], "progress": progress}, 3)
    if understood["status"] != "pass":
        return _emit(_failure("strategy_understanding", understood["errors"][0], "请提供 EMA、SMA 或 RSI 的明确 long/cash 比较规则。", progress), 2)
    contract = understood["contract"]
    progress.append("✓ 策略理解完成")

    input_path = args.input.resolve()
    if not input_path.exists():
        return _emit(_failure("data_loading", f"找不到 CSV 文件：{input_path}", "请提供有效的 --input CSV 路径。", progress), 2)
    validation = validate_price_data.validate(input_path, args.naive_timezone)
    if validation.get("status") == "fail":
        first = validation.get("errors", [{}])[0].get("message", "数据校验失败")
        return _emit(_failure("data_validation", first, "请修正数据字段、日期、价格或多标的问题后重试。", progress), 2)
    progress.append("✓ 数据校验完成")

    rows, parse_errors, parse_warnings, _ = run_backtest.parse_rows(input_path, args.naive_timezone, require_signal=False)
    if parse_errors:
        return _emit(_failure("data_loading", parse_errors[0], "请检查 CSV 的 date、close、open 和 symbol 字段。", progress), 2)
    try:
        naive_zone = run_backtest.get_zone(args.naive_timezone)
        start = run_backtest.parse_datetime(args.start_date, naive_zone)[0] if args.start_date else None
        end = run_backtest.parse_datetime(args.end_date, naive_zone)[0] if args.end_date else None
        if start and end and start > end:
            raise ValueError("start date 不能晚于 end date")
        rows = run_backtest.filter_rows(rows, start, end)
        signal_rows, signal_meta = indicator_signal_core.generate_signals(rows, contract)
    except (TypeError, ValueError, KeyError) as exc:
        return _emit(_failure("indicator_signal", str(exc), "请检查指标周期、规则和日期区间。", progress), 2)
    if len(signal_rows) <= signal_meta["warmup_bars"]:
        return _emit(_failure("indicator_signal", f"数据不足以完成 warm-up：需要超过 {signal_meta['warmup_bars']} 根 K 线。", "请扩大数据区间或提供更长历史数据。", progress), 2)
    progress.append("✓ 指标与信号生成完成")

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = "free-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    run_dir = output_root / run_id
    try:
        run_dir.mkdir(exist_ok=False)
        charts_dir = run_dir / "charts"
        charts_dir.mkdir()
        indicator_signal_core.write_signal_csv(run_dir / "signals.csv", signal_rows)
        _json_write(run_dir / "validation.json", validation)
        _json_write(run_dir / "strategy-contract.json", contract)

        frequency = {"1d": "daily", "1w": "weekly", "1mo": "monthly"}[contract["timeframe"]]
        backtest = run_backtest.run(
            signal_rows,
            float(contract["initial_cash"]),
            float(contract["commission_bps"]),
            float(contract["slippage_bps"]),
            True,
            contract["execution"],
            frequency,
            0.0,
            "internal_deterministic",
            contract["normalized_summary"],
        )
        backtest["warnings"] = run_backtest.unique(parse_warnings + backtest.get("warnings", []))
        backtest["status"] = "warn" if backtest["warnings"] else "pass"
        _json_write(run_dir / "backtest.json", backtest)
        _write_trades(run_dir / "trades.csv", backtest["trades"])
        _write_summary(run_dir / "Summary.md", contract, backtest)

        dates = [point["date"] for point in backtest["curve"]]
        chart_line(
            charts_dir / "equity-vs-benchmark.png",
            "策略与买入持有净值曲线",
            "净值基准 100 · 默认成本",
            dates,
            [
                ("策略", normalized_equity(backtest["curve"]), "#163A5F"),
                ("买入持有", normalized_equity(backtest["benchmark"]["curve"]), "#93A7BB"),
            ],
            log_scale=True,
        )
        chart_line(
            charts_dir / "drawdown.png",
            "策略回撤",
            "默认成本 · 回撤从历史峰值计算",
            dates,
            [("回撤", [float(point["drawdown"]) for point in backtest["drawdown"]], "#B54747")],
            percent_axis=True,
            zero_line=True,
        )
    except Exception as exc:
        return _emit(_failure("free_artifacts", f"{type(exc).__name__}: {exc}", "请检查输出目录权限和基础图表依赖。", progress), 2)

    progress.extend(["✓ 回测完成", "✓ 基础图表完成", "✓ Free 研究产物完成"])
    total_return = backtest["metrics"].get("total_return")
    trade_count = int(backtest["metrics"].get("trades", 0))
    max_drawdown = backtest["metrics"].get("max_drawdown")
    benchmark_total_return = backtest["benchmark"]["metrics"].get("total_return")

    def _pct(value: Any) -> str:
        return "—" if value is None else f"{float(value) * 100:.2f}%"

    user_summary = (
        f"总收益率：{_pct(total_return)}；"
        f"交易次数：{trade_count} 次；"
        f"最大回撤：{_pct(max_drawdown)}；"
        f"买入持有收益：{_pct(benchmark_total_return)}。"
    )
    return _emit({
        "status": "pass",
        "message": "Free 回测完成。",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "strategy_contract": str(run_dir / "strategy-contract.json"),
        "contract_hash": contract["contract_hash"],
        "user_summary": user_summary,
        "key_metrics": {
            "strategy_total_return": total_return,
            "trade_count": trade_count,
            "max_drawdown": max_drawdown,
            "benchmark_total_return": benchmark_total_return,
        },
        "backtest": str(run_dir / "backtest.json"),
        "summary": str(run_dir / "Summary.md"),
        "charts": [str(path) for path in sorted(charts_dir.glob("*.png"))],
        "warnings": backtest.get("warnings", []),
        "progress": progress,
    }, 0)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "fail", "failed_at": "workflow", "reason": f"{type(exc).__name__}: {exc}", "next_action": "请检查输入文件和运行环境。"}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
