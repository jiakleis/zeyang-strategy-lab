#!/usr/bin/env python3
"""Self-contained smoke tests intended to run from an isolated Free Candidate."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "scripts" / "run_free_research.py"
CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(message)


def write_synthetic_prices(path: Path) -> None:
    fields = ["date", "open", "high", "low", "close", "volume", "symbol"]
    start = date(2024, 1, 1)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        previous = 100.0
        for index in range(90):
            close = 100.0 + index * 0.12 + ((index % 13) - 6) * 1.65
            writer.writerow({
                "date": (start + timedelta(days=index)).isoformat(),
                "open": previous,
                "high": max(previous, close) + 0.75,
                "low": min(previous, close) - 0.75,
                "close": close,
                "volume": 1000000 + index,
                "symbol": "TEST",
            })
            previous = close


def invoke(strategy: str, input_path: Path, output_root: Path, cwd: Path, *extra: str) -> tuple[int, dict]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    completed = subprocess.run(
        [sys.executable, str(ENTRYPOINT), "--strategy", strategy, "--input", str(input_path), "--output-root", str(output_root), *extra],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Free 入口输出不是 JSON：stdout={completed.stdout[-500:]} stderr={completed.stderr[-500:]}") from exc
    return completed.returncode, payload


def assert_standard_artifacts(result: dict) -> dict:
    run_dir = Path(result["run_dir"])
    expected = {"strategy-contract.json", "signals.csv", "validation.json", "backtest.json", "trades.csv", "Summary.md"}
    check(expected.issubset({path.name for path in run_dir.iterdir()}), "缺少 Free 标准产物")
    backtest = json.loads((run_dir / "backtest.json").read_text(encoding="utf-8"))
    check(backtest["curve"] and backtest["drawdown"] and backtest["benchmark"]["curve"], "缺少权益、回撤或买入持有结果")
    check(len(result["charts"]) == 2 and all(Path(path).is_file() and Path(path).stat().st_size > 0 for path in result["charts"]), "基础净值图或回撤图缺失")
    check(not list(run_dir.rglob("*.docx")) and not (run_dir / "analysis.json").exists(), "Free 输出混入 Pro 报告或分析产物")
    return backtest


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="zeyang-free-isolated-") as temp:
        temp_dir = Path(temp)
        input_path = temp_dir / "synthetic_ohlcv.csv"
        isolated_cwd = temp_dir / "different-cwd"
        isolated_cwd.mkdir()
        write_synthetic_prices(input_path)

        cases = {
            "FREE_EMA20_SMOKE": "回测 TEST 日线 EMA20，收盘价高于 EMA20 持仓，低于 EMA20 空仓。",
            "FREE_SMA20_SMOKE": "回测 TEST 日线 SMA20，收盘价高于 SMA20 持仓，低于 SMA20 空仓。",
            "FREE_RSI14_SMOKE": "回测 TEST 日线 RSI14 低于 30 买入，高于 70 卖出。",
        }
        for flag, strategy in cases.items():
            code, result = invoke(strategy, input_path, temp_dir / "runs", isolated_cwd)
            check(code == 0 and result["status"] == "pass", f"{flag} 失败：{result}")
            assert_standard_artifacts(result)

        strategy = cases["FREE_EMA20_SMOKE"]
        code, zero_cost = invoke(strategy, input_path, temp_dir / "zero-cost", isolated_cwd, "--commission-bps", "0", "--slippage-bps", "0")
        check(code == 0 and zero_cost["status"] == "pass", "零成本 Free 回测失败")
        code, charged = invoke(strategy, input_path, temp_dir / "charged", isolated_cwd, "--commission-bps", "25", "--slippage-bps", "25")
        check(code == 0 and charged["status"] == "pass", "带成本 Free 回测失败")
        zero_backtest = assert_standard_artifacts(zero_cost)
        charged_backtest = assert_standard_artifacts(charged)
        check(zero_backtest["costs"]["total_cost"] == 0.0, "零成本情景仍记录了交易成本")
        check(charged_backtest["costs"]["commission_cost"] > 0 and charged_backtest["costs"]["slippage_cost"] > 0, "手续费或滑点没有进入回测")
        check(charged_backtest["curve"][-1]["equity"] != zero_backtest["curve"][-1]["equity"], "交易成本没有改变最终净值")

        unsupported = (
            "回测 TEST 日线 MACD(12,26,9)，DIF 大于 0 轴时持仓，DIF 小于 0 轴时空仓。",
            "回测 TEST 日线 Bollinger Bands，跌破下轨买入，突破上轨卖出。",
            "回测 TEST 日线 EMA5 上穿 EMA20 买入，下穿卖出。",
            "回测 TEST 日线 EMA20，跌破 EMA20 做空。",
            "回测 TEST 日线 EMA20，使用两倍杠杆。",
            "回测 TEST 15分钟 EMA20，收盘价高于 EMA20 持仓，低于 EMA20 空仓。",
        )
        for strategy in unsupported:
            code, result = invoke(strategy, input_path, temp_dir / "unsupported", isolated_cwd)
            check(code == 2 and result.get("status") == "fail" and result.get("failed_at") == "strategy_understanding", f"未友好阻断不支持策略：{strategy}")
            check(result.get("reason") and "Traceback" not in result["reason"], "不支持策略没有返回友好原因")

    flags = {
        "FREE_EMA20_SMOKE": "PASS",
        "FREE_SMA20_SMOKE": "PASS",
        "FREE_RSI14_SMOKE": "PASS",
        "FREE_COST_SMOKE": "PASS",
        "UNSUPPORTED_STRATEGY_GATE": "PASS",
    }
    print(json.dumps({"status": "pass", "tests": CHECKS, "flags": flags}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
