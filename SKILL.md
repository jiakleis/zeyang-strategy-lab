---
name: zeyang-strategy-lab-free
description: "用于本地单标的历史数据研究与策略验证，支持 EMA、SMA 或 RSI 的做多/空仓规则，并生成基础 JSON、CSV、Markdown 与图表文件。仅用于历史研究与教育，不用于实盘交易或投资建议。 Run local single-asset historical research with EMA, SMA, or RSI long/cash rules and produce basic JSON, CSV, Markdown, and chart artifacts. Use for research and education, not live trading or investment advice."
---

# 泽洋策略实验室 Free / Zeyang Strategy Lab Free

## 中文简介

这是一个用于本地、单标的、日线历史数据研究与策略验证的免费 Skill。用户必须提供 CSV 文件；标准入口是 `scripts/run_free_research.py`，必须明确指定 `--input` 路径，不自动获取数据。

仅用于历史数据研究与策略验证，不构成投资建议。Free 版不执行实盘交易、不提供实时信号、不荐股，也不保证收益。

## English Overview

Use this skill only for local, single-asset daily historical research with a user-provided CSV. The standard entrypoint is `scripts/run_free_research.py`; require an explicit `--input` path and do not fetch data automatically.

This skill is for historical research and strategy validation only, not investment advice. The Free edition does not execute live trades, provide real-time signals, recommend securities, or guarantee returns.

## 支持的策略形态 / Supported strategy shape

- EMA 或 SMA：收盘价高于所选均线时做多，低于所选均线时空仓。
- RSI：低于声明的下限时做多，高于声明的上限时空仓。
- 仅支持做多/空仓，收盘产生信号，下一根 K 线执行。

- EMA or SMA: close above the selected average means long; close below means cash.
- RSI: below a declared lower threshold means long; above a declared upper threshold means cash.
- Long/cash only, with signal at close and execution on the following bar.

优先从用户请求和输入数据中解析标的、日线周期、本地输入文件、规则、执行假设和成本假设。只有在必要字段确实缺失或策略存在重大歧义时才询问用户。输入 CSV 必须包含 `date` 和 `close`，`open` 可选。使用默认的 `next_open` 执行方式时，如果缺少 `open`，将正式回退到下一根 K 线的 `close`，并产生警告。返回生成的 Strategy Contract、摘要、核心指标、警告和文件路径。明确说明结果仅用于研究，不构成投资建议。

Prefer to parse the symbol, daily timeframe, local input file, rule, execution assumption, and cost assumptions from the user's request and input data. Ask the user only when a required field is genuinely missing or the strategy has a material ambiguity. The input CSV requires `date` and `close`; `open` is optional. With the default `next_open` execution, a missing `open` formally falls back to the next bar's `close` and produces a warning. Return the generated Strategy Contract, summary, core metrics, warnings, and artifact paths. State that the result is research only and not investment advice.

## 不支持的请求 / Unsupported requests

不要搜索 Pro 文件、调用 Pro 运行时、实现不支持的功能、默默简化策略，或回退到其他规则。

Do not search for Pro files, call a Pro runtime, implement an unsupported feature, silently simplify a strategy, or fall back to another rule.

对于 MACD、布林带、cross/crossunder、做空、杠杆、分钟数据、多资产组合或参数优化请求，必须仅回复以下英文原文：

For MACD, Bollinger, cross/crossunder, shorting, leverage, minute data, multi-asset portfolios, or parameter optimization, respond exactly:

```text
Current Free edition does not support this strategy.
```

## 数据与解读限制 / Data and interpretation limits

在接受有歧义或格式错误的输入前，先阅读 [references/data-contract.md](references/data-contract.md)。关于指标定义和研究限制，阅读 [references/metrics-and-robustness.md](references/metrics-and-robustness.md)。不要声称执行延迟证明外部信号不存在前视偏差。

Read [references/data-contract.md](references/data-contract.md) before accepting ambiguous or malformed input. For metric definitions and research limits, read [references/metrics-and-robustness.md](references/metrics-and-robustness.md). Do not claim that execution lag proves an external signal has no look-ahead bias.
