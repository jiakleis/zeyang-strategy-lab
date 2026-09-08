#!/usr/bin/env python3
"""Dependency-free regression tests for the investment-backtest-history skill."""

from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_price_data.py"
BACKTEST = ROOT / "scripts" / "run_backtest.py"
EXAMPLE = ROOT / "tests" / "fixtures" / "example_signals.csv"
GOLDEN = ROOT / "tests" / "fixtures" / "backtest.json"


def invoke(script: Path, *args: str) -> tuple[int, dict]:
    completed = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{script.name} 输出不是 JSON：stdout={completed.stdout[-500:]} stderr={completed.stderr[-500:]}") from exc
    return completed.returncode, payload


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_json_approx(actual: object, expected: object, path: str = "") -> None:
    if isinstance(expected, dict):
        check(isinstance(actual, dict), f"golden 类型不一致：{path}")
        check(set(actual) == set(expected), f"golden 字段漂移：{path}")
        for key in expected:
            check_json_approx(actual[key], expected[key], f"{path}.{key}" if path else key)
    elif isinstance(expected, list):
        check(isinstance(actual, list) and len(actual) == len(expected), f"golden 列表漂移：{path}")
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            check_json_approx(actual_item, expected_item, f"{path}[{index}]")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        check(isinstance(actual, (int, float)) and not isinstance(actual, bool), f"golden 数值类型不一致：{path}")
        check(math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-12), f"golden 数值漂移：{path}")
    else:
        check(actual == expected, f"golden 值漂移：{path}")


def main() -> int:
    passed = 0
    code, validation = invoke(VALIDATOR, str(EXAMPLE))
    check(code == 0 and validation["status"] == "warn", "示例数据应为 warn 而不是 fail")
    check(validation["assumptions"]["signal_checked"] is True, "校验器没有检查 signal")
    passed += 1

    code, result = invoke(BACKTEST, str(EXAMPLE), "--signal-rule", "example rule")
    check(code == 0, "示例回测失败")
    check(result["assumptions"]["execution_lag_bars"] == 1, "执行滞后不为 1")
    check(result["assumptions"]["frequency"] == "daily", "日频自动推断失败")
    check(result["benchmark"]["name"] == "buy_and_hold", "缺少买入持有基准")
    check(result["metrics"]["cagr"] is None and result["metrics"]["cagr_is_extrapolated"] is True, "短样本 CAGR 防护失败")
    check(result["metrics"]["risk_metrics_is_suppressed"] is True, "极小样本风险指标没有被抑制")
    check(result["metrics"]["sharpe"] is None and result["metrics"]["sortino"] is None, "极小样本仍输出风险比率")
    passed += 1

    code, golden_result = invoke(BACKTEST, str(EXAMPLE))
    check(code == 0, "golden 基准回测失败")
    check(golden_result["schema_version"] == "3.0", "回测 schema 未升级到完整输出版本")
    check(golden_result["assumptions"]["position_mode"] == "long_cash", "V1 仓位模式没有固定为 long/cash")
    check(len(golden_result["benchmark"]["curve"]) == len(golden_result["curve"]), "基准曲线没有与策略曲线对齐")
    check(len(golden_result["drawdown"]) == len(golden_result["curve"]), "策略 drawdown 序列长度错误")
    check(len(golden_result["trades"]) == golden_result["metrics"]["trades"], "交易 ledger 与交易次数不一致")
    check(math.isclose(golden_result["costs"]["total_cost"], golden_result["costs"]["commission_cost"] + golden_result["costs"]["slippage_cost"], rel_tol=1e-12, abs_tol=1e-12), "成本分解不一致")
    passed += 1

    code, sliced = invoke(
        BACKTEST,
        str(EXAMPLE),
        "--signal-rule",
        "example rule",
        "--execution-price",
        "next_close",
        "--risk-free-rate",
        "0.03",
        "--start-date",
        "2024-01-03",
        "--end-date",
        "2024-01-09",
    )
    check(code == 0, "执行价/日期区间/无风险利率参数失败")
    check(sliced["assumptions"]["execution_price"] == "next_close", "next_close 未记录")
    check(sliced["assumptions"]["risk_free_rate_annual"] == 0.03, "无风险利率未记录")
    check(sliced["metadata"]["selected_rows"] == 5, "日期区间筛选错误")
    passed += 1

    with tempfile.TemporaryDirectory(prefix="investment-backtest-tests-") as temp:
        temp_dir = Path(temp)
        invalid_signal = temp_dir / "invalid_signal.csv"
        write_rows(invalid_signal, [{"date": "2024-01-01", "open": 10, "high": 10, "low": 10, "close": 10, "signal": 2}])
        code, invalid_report = invoke(VALIDATOR, str(invalid_signal))
        check(code == 2 and any(item["code"] == "signal_out_of_range" for item in invalid_report["errors"]), "signal 越界没有被阻断")
        passed += 1

        negative_signal = temp_dir / "negative_signal.csv"
        write_rows(negative_signal, [
            {"date": "2024-01-01", "open": 10, "high": 10, "low": 10, "close": 10, "signal": 0},
            {"date": "2024-01-02", "open": 10, "high": 10, "low": 10, "close": 10, "signal": -1},
        ])
        code, negative_report = invoke(BACKTEST, str(negative_signal), "--signal-rule", "test")
        check(code == 2 and any("long/cash" in item for item in negative_report["errors"]), "负 signal 没有按 V1 long/cash 边界阻断")
        passed += 1

        golden_case = temp_dir / "golden-case.csv"
        write_rows(golden_case, [
            {"date": "2024-01-01", "open": 100, "high": 100, "low": 100, "close": 100, "signal": 0},
            {"date": "2024-01-02", "open": 100, "high": 100, "low": 100, "close": 100, "signal": 1},
            {"date": "2024-01-03", "open": 100, "high": 110, "low": 100, "close": 110, "signal": 1},
            {"date": "2024-01-04", "open": 110, "high": 110, "low": 110, "close": 110, "signal": 0},
            {"date": "2024-01-05", "open": 110, "high": 110, "low": 110, "close": 110, "signal": 1},
            {"date": "2024-01-08", "open": 100, "high": 100, "low": 100, "close": 100, "signal": 1},
        ])
        code, golden_case_result = invoke(BACKTEST, str(golden_case), "--signal-rule", "golden")
        check(code == 0, "人工 golden case 回测失败")
        check(golden_case_result["metrics"]["trades"] == 4, "golden case 交易次数没有包含期末平仓")
        check(math.isclose(golden_case_result["metrics"]["turnover_position_change"], 4.0, rel_tol=1e-12, abs_tol=1e-12), "golden case turnover 错误")
        check(math.isclose(golden_case_result["costs"]["commission_cost"], 214.670219945, rel_tol=1e-12, abs_tol=1e-9), "golden case commission 错误")
        check(math.isclose(golden_case_result["costs"]["slippage_cost"], 214.670219945, rel_tol=1e-12, abs_tol=1e-9), "golden case slippage 错误")
        check(math.isclose(golden_case_result["curve"][-1]["equity"], 109560.65956011, rel_tol=1e-12, abs_tol=1e-7), "golden case final equity 错误")
        check(golden_case_result["trades"][-1]["liquidation"] is True, "golden case 没有记录期末平仓")
        passed += 1

        mixed_timezone = temp_dir / "mixed_timezone.csv"
        write_rows(mixed_timezone, [
            {"date": "2024-01-01", "open": 10, "high": 10, "low": 10, "close": 10, "signal": 1},
            {"date": "2024-01-02T00:00:00+00:00", "open": 10, "high": 11, "low": 10, "close": 11, "signal": 1},
            {"date": "2024-01-03", "open": 11, "high": 12, "low": 11, "close": 12, "signal": 0},
        ])
        code, mixed_validation = invoke(VALIDATOR, str(mixed_timezone))
        check(code == 0 and any(item["code"] == "naive_timestamp_normalized" for item in mixed_validation["warnings"]), "混合时区未被稳定处理")
        code, mixed_result = invoke(BACKTEST, str(mixed_timezone), "--signal-rule", "test")
        check(code == 0 and mixed_result["status"] == "warn", "混合时区回测发生崩溃或未产生警告")
        passed += 1

        monthly = temp_dir / "monthly.csv"
        monthly_rows = []
        for index in range(13):
            month = index + 1
            year = 2024 + (month - 1) // 12
            month_in_year = (month - 1) % 12 + 1
            value = 100 + index
            monthly_rows.append({"date": f"{year:04d}-{month_in_year:02d}-01", "open": value, "high": value + 1, "low": value - 1, "close": value, "signal": 1})
        write_rows(monthly, monthly_rows)
        code, monthly_result = invoke(BACKTEST, str(monthly), "--signal-rule", "test")
        check(code == 0 and monthly_result["assumptions"]["frequency"] == "monthly", "月频自动推断失败")
        check(monthly_result["assumptions"]["annualization_periods"] == 12, "月频年化系数错误")
        check(monthly_result["metrics"]["risk_metrics_is_suppressed"] is False, "月频充分样本被错误抑制")
        check(any(item.startswith("[benchmark] ") for item in monthly_result["warnings"]), "基准警告没有来源前缀")
        passed += 1

        intraday = temp_dir / "intraday.csv"
        intraday_rows = []
        for index in range(4):
            hour = 9 + index
            value = 100 + index
            intraday_rows.append({"date": f"2024-01-02T{hour:02d}:30:00", "open": value, "high": value + 1, "low": value - 1, "close": value, "signal": 1})
        write_rows(intraday, intraday_rows)
        code, intraday_result = invoke(BACKTEST, str(intraday), "--signal-rule", "test")
        check(code == 0 and intraday_result["assumptions"]["frequency"] == "irregular", "日内数据没有降级为 irregular")
        check(intraday_result["assumptions"]["annualization_periods"] is None, "日内数据仍使用日频年化周期")
        check(any("日内/高频" in item for item in intraday_result["warnings"]), "日内数据没有产生边界警告")
        passed += 1

        jump = temp_dir / "jump.csv"
        write_rows(jump, [
            {"date": "2024-01-01", "open": 100, "high": 100, "low": 100, "close": 100, "signal": 0},
            {"date": "2024-01-02", "open": 100, "high": 100, "low": 100, "close": 100, "signal": 0},
            {"date": "2024-01-03", "open": 600, "high": 600, "low": 600, "close": 600, "signal": 0},
            {"date": "2024-01-04", "open": 601, "high": 601, "low": 601, "close": 601, "signal": 0},
        ])
        code, jump_report = invoke(VALIDATOR, str(jump))
        check(code == 0 and any(item["code"] == "extreme_move" for item in jump_report["warnings"]), "异常跳变没有被提示")
        passed += 1

        existing_output = temp_dir / "existing.json"
        existing_output.write_text("{}", encoding="utf-8")
        code, overwrite_report = invoke(BACKTEST, str(EXAMPLE), "--output", str(existing_output))
        check(code == 2 and overwrite_report["status"] == "fail", "输出文件覆盖保护失败")
        validator_existing = temp_dir / "validator-existing.json"
        validator_existing.write_text("{}", encoding="utf-8")
        code, validator_overwrite = invoke(VALIDATOR, str(EXAMPLE), "--output", str(validator_existing))
        check(code == 2 and validator_overwrite["status"] == "fail", "校验器输出覆盖保护失败")
        code, validator_forced = invoke(VALIDATOR, str(EXAMPLE), "--output", str(validator_existing), "--force")
        check(code == 0 and validator_forced["status"] == "warn", "校验器 --force 覆盖失败")
        passed += 1

        multisymbol = temp_dir / "multisymbol.csv"
        write_rows(multisymbol, [
            {"date": "2024-01-01", "open": 10, "high": 10, "low": 10, "close": 10, "signal": 1, "symbol": "AAA"},
            {"date": "2024-01-02", "open": 10, "high": 11, "low": 10, "close": 11, "signal": 1, "symbol": "AAA"},
            {"date": "2024-02-01", "open": 20, "high": 20, "low": 20, "close": 20, "signal": 1, "symbol": "BBB"},
            {"date": "2024-02-02", "open": 20, "high": 21, "low": 20, "close": 21, "signal": 1, "symbol": "BBB"},
        ])
        code, multisymbol_report = invoke(BACKTEST, str(multisymbol), "--signal-rule", "test")
        check(code == 2 and multisymbol_report["status"] == "fail", "多标的输入没有被阻断")
        check(any("多个 symbol" in item for item in multisymbol_report["errors"]), "多标的错误没有明确说明")
        check(multisymbol_report["metadata"]["symbols"] == ["AAA", "BBB"], "多标的元数据没有保留")
        passed += 1

        missing_output_dir = temp_dir / "missing-output-dir"
        validator_output = missing_output_dir / "validation.json"
        code, validator_output_report = invoke(VALIDATOR, str(EXAMPLE), "--output", str(validator_output))
        check(code == 2 and validator_output_report["status"] == "fail", "校验器输出失败没有结构化返回")
        check(any(item["code"] == "output_write" for item in validator_output_report["errors"]), "校验器没有报告输出写入错误")

        backtest_output = missing_output_dir / "backtest.json"
        code, backtest_output_report = invoke(BACKTEST, str(EXAMPLE), "--signal-rule", "test", "--output", str(backtest_output))
        check(code == 2 and backtest_output_report["status"] == "fail", "回测器输出失败没有结构化返回")
        check(any(item["type"] == "output_write" for item in backtest_output_report["errors"]), "回测器没有报告输出写入错误")
        passed += 2

    print(json.dumps({"status": "pass", "tests": passed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
