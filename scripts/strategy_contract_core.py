#!/usr/bin/env python3
"""Shared deterministic Strategy Contract core for Free and Pro runtimes."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Callable, Collection


SCHEMA_VERSION = "1.0"
BASIC_SUPPORTED_INDICATORS = frozenset({"EMA", "SMA", "RSI"})
RESERVED_SYMBOL_WORDS = {
    "EMA", "SMA", "RSI", "MACD", "BOLLINGER", "BUY", "SELL", "AND", "OR", "CLOSE", "OPEN",
}


class ContractError(ValueError):
    """A user-facing contract validation error."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def contract_hash(contract: dict[str, Any]) -> str:
    payload = deepcopy(contract)
    payload.pop("contract_hash", None)
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _indicator_id(kind: str, period: int | None = None) -> str:
    return f"{kind.lower()}{period or 14}"


def _indicator(kind: str, period: int | None = None) -> dict[str, Any]:
    normalized_kind = kind.upper()
    if normalized_kind not in BASIC_SUPPORTED_INDICATORS:
        raise ContractError(f"Free Core 暂不支持指标：{normalized_kind}")
    return {
        "id": _indicator_id(normalized_kind, period),
        "type": normalized_kind,
        "input": "close",
        "period": period or 14,
    }


def _symbol_from_text(text: str) -> str | None:
    for token in re.findall(r"\b[A-Za-z][A-Za-z0-9._-]{0,9}\b", text):
        upper = token.upper()
        if upper not in RESERVED_SYMBOL_WORDS and not re.fullmatch(r"(?:EMA|SMA|RSI)\d+", upper):
            return upper
    return None


def _timeframe(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("分钟", "min", "intraday", "小时", "hour")):
        raise ContractError("当前 V1 不支持分钟线、小时线或日内高频数据")
    if any(word in lowered for word in ("周线", "weekly", "1w")):
        return "1w"
    if any(word in lowered for word in ("月线", "monthly", "1m")):
        return "1mo"
    return "1d"


def _period(kind: str, text: str, default: int) -> int:
    match = re.search(rf"(?:{kind}|{kind.lower()}|{kind.title()})\s*(\d+)", text, flags=re.I)
    return int(match.group(1)) if match else default


def _rule(left: str, operator: str, right: Any) -> dict[str, Any]:
    return {"type": "comparison", "left": left, "operator": operator, "right": right, "equality_behavior": "hold"}


def _timeframe_label(value: str) -> str:
    return {"1d": "日线", "1w": "周线", "1mo": "月线"}.get(value, value)


def _summary(contract: dict[str, Any]) -> str:
    entry = contract["entry_rule"]
    exit_rule = contract["exit_rule"]
    return f"{contract['symbol']} {contract['timeframe']}：{entry['left']} {entry['operator']} {entry['right']} 持仓，{exit_rule['left']} {exit_rule['operator']} {exit_rule['right']} 空仓；只做多/空仓，收盘生成信号，下一交易日开盘执行。"


def display_fields(contract: dict[str, Any]) -> dict[str, str]:
    """Derive Free-safe report-facing names without changing execution data."""
    indicators = contract.get("indicators", [])
    labels = [f"{item.get('type', '').upper()}{item.get('period', '')}" for item in indicators]
    timeframe_label = _timeframe_label(contract.get("timeframe", "1d"))
    if len(labels) == 1 and labels[0].startswith("RSI"):
        short_name = f"{labels[0]} 阈值策略"
        display_name = f"{contract['symbol']} {labels[0]} {timeframe_label}阈值策略"
    elif len(labels) == 1:
        short_name = f"{labels[0]} 长仓/空仓策略"
        display_name = f"{contract['symbol']} {labels[0]} {timeframe_label}策略"
    else:
        short_name = f"{' / '.join(labels)} 策略"
        display_name = f"{contract['symbol']} {' / '.join(labels)} {timeframe_label}策略"
    return {
        "strategy_display_name": display_name,
        "strategy_short_name": short_name,
        "strategy_description": contract.get("original_text", contract.get("strategy_text", "")),
        "indicator_summary": " / ".join(labels),
    }


def validate_contract(
    contract: dict[str, Any],
    *,
    supported_indicators: Collection[str] = BASIC_SUPPORTED_INDICATORS,
    period_optional_types: Collection[str] = (),
    allowed_rule_types: Collection[str] = ("comparison",),
) -> dict[str, Any]:
    required = ("schema_version", "symbol", "timeframe", "strategy_text", "indicators", "entry_rule", "exit_rule", "position", "signal_at", "execution", "commission_bps", "slippage_bps", "benchmark")
    missing = [key for key in required if key not in contract]
    if missing:
        raise ContractError(f"Strategy Contract 缺少字段：{', '.join(missing)}")
    if contract["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"不支持的 Strategy Contract 版本：{contract['schema_version']}")
    if contract["position"] != "long_cash":
        raise ContractError("当前 V1 只支持 long/cash，不支持做空或杠杆")
    if contract["timeframe"] not in {"1d", "1w", "1mo"}:
        raise ContractError("当前 V1 只支持日线、周线或月线")
    if contract["execution"] not in {"next_open", "next_close"}:
        raise ContractError("execution 必须是 next_open 或 next_close")
    if contract["signal_at"] != "close":
        raise ContractError("当前 V1 要求 signal_at=close")
    if float(contract["commission_bps"]) < 0 or float(contract["slippage_bps"]) < 0:
        raise ContractError("手续费和滑点不能为负")
    if not contract["indicators"]:
        raise ContractError("至少需要一个指标")
    for indicator in contract["indicators"]:
        if indicator.get("type") not in supported_indicators:
            raise ContractError(f"暂不支持指标：{indicator.get('type')}")
        if indicator.get("type") not in period_optional_types and int(indicator.get("period", 0)) <= 0:
            raise ContractError("指标周期必须为正整数")
    for rule_name in ("entry_rule", "exit_rule"):
        if contract[rule_name].get("type", "comparison") not in allowed_rule_types:
            raise ContractError(f"当前 Contract Core 不支持规则类型：{contract[rule_name].get('type')}")
    return contract


def finalize_contract(
    contract: dict[str, Any],
    *,
    supported_indicators: Collection[str] = BASIC_SUPPORTED_INDICATORS,
    period_optional_types: Collection[str] = (),
    allowed_rule_types: Collection[str] = ("comparison",),
    summary_builder: Callable[[dict[str, Any]], str] | None = None,
    display_builder: Callable[[dict[str, Any]], dict[str, str]] | None = None,
) -> dict[str, Any]:
    finalized = validate_contract(
        deepcopy(contract),
        supported_indicators=supported_indicators,
        period_optional_types=period_optional_types,
        allowed_rule_types=allowed_rule_types,
    )
    finalized.setdefault("normalized_summary", (summary_builder or _summary)(finalized))
    finalized.setdefault("original_text", finalized.get("strategy_text", ""))
    finalized.update((display_builder or display_fields)(finalized))
    finalized["contract_hash"] = contract_hash(finalized)
    return finalized


def understand(text: str, symbol: str | None = None, timeframe: str | None = None, commission_bps: float = 5.0, slippage_bps: float = 5.0, execution: str = "next_open") -> dict[str, Any]:
    """Parse the Free baseline: EMA/SMA price comparisons and RSI thresholds."""
    text = (text or "").strip()
    if not text:
        return {"status": "error", "errors": ["请提供 strategy description"]}
    lowered = text.lower()
    if any(word in lowered for word in ("做空", "short", "杠杆", "leverage", "融资")):
        return {"status": "error", "errors": ["当前 V1 只支持 long/cash，不支持做空或杠杆；本次未生成回测。"]}
    if any(token in lowered for token in ("macd", "bollinger", "布林")) or re.search(r"(?:上穿|下穿|crossover|crossunder|crosses?\s+above)", lowered):
        return {"status": "error", "errors": ["Free Core 只支持 EMA、SMA、RSI 的基础比较规则；MACD、Bollinger 和均线交叉保留在 Pro。"]}
    if "突破" in text and not any(token in lowered for token in (">", "<", "高于", "低于", "大于", "小于")):
        return {"status": "clarification", "questions": ["“突破 EMA20”是指收盘价 > EMA20 后持续持仓，还是仅在上穿当日买入？"]}
    try:
        selected_symbol = (symbol or _symbol_from_text(text) or "").upper()
        if not selected_symbol:
            return {"status": "clarification", "questions": ["请补充回测标的，例如 SPY。"]}
        selected_timeframe = timeframe or _timeframe(text)
        if selected_timeframe not in {"1d", "1w", "1mo"}:
            raise ContractError("当前 V1 只支持日线、周线或月线")

        indicators: list[dict[str, Any]] = []
        for kind, default in (("EMA", 20), ("SMA", 20), ("RSI", 14)):
            if re.search(rf"\b{kind}\s*\d*", text, flags=re.I):
                indicators.append(_indicator(kind, _period(kind, text, default)))

        if indicators and indicators[0]["type"] == "RSI":
            indicator = indicators[0]["id"]
            low = re.search(r"(?:低于|小于|below|<)\s*(\d+(?:\.\d+)?)", text, flags=re.I)
            high = re.search(r"(?:高于|大于|above|>)\s*(\d+(?:\.\d+)?)", text, flags=re.I)
            if not low or not high:
                return {"status": "clarification", "questions": ["RSI 策略需要明确买入阈值和卖出阈值，例如 RSI14 低于 30 买入，高于 70 卖出。"]}
            entry_rule = _rule(indicator, "<", float(low.group(1)))
            exit_rule = _rule(indicator, ">", float(high.group(1)))
        else:
            indicator = indicators[0] if indicators else None
            if indicator is None:
                return {"status": "clarification", "questions": ["请明确一个支持的指标：EMA、SMA 或 RSI。"]}
            left = indicator["id"]
            entry = re.search(r"(?:收盘价|收盘|股价|close)[^\n,，;；]*?(?:高于|大于|站上|above|>)\s*(?:EMA|SMA)?\s*\d*", text, flags=re.I)
            exit_match = re.search(r"(?:低于|小于|跌破|below|<)\s*(?:EMA|SMA)?\s*\d*", text, flags=re.I)
            if not entry or not exit_match:
                return {"status": "clarification", "questions": ["请明确买入和卖出规则，例如收盘价高于 EMA20 持仓，低于 EMA20 空仓。"]}
            entry_rule = _rule("close", ">", left)
            exit_rule = _rule("close", "<", left)

        contract = {
            "schema_version": SCHEMA_VERSION,
            "symbol": selected_symbol,
            "timeframe": selected_timeframe,
            "strategy_text": text,
            "original_text": text,
            "indicators": indicators,
            "entry_rule": entry_rule,
            "exit_rule": exit_rule,
            "position": "long_cash",
            "signal_at": "close",
            "execution": execution,
            "commission_bps": float(commission_bps),
            "slippage_bps": float(slippage_bps),
            "initial_cash": 100000.0,
            "benchmark": "buy_and_hold",
            "equality_behavior": "hold",
            "defaults_applied": ["timeframe=daily" if timeframe is None else None, "execution=next_open" if execution == "next_open" else None, "position=long_cash", "benchmark=buy_and_hold"],
        }
        contract["defaults_applied"] = [item for item in contract["defaults_applied"] if item]
        return {"status": "pass", "contract": finalize_contract(contract)}
    except ContractError as exc:
        return {"status": "error", "errors": [str(exc)]}


def load_contract(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return finalize_contract(json.load(handle))
