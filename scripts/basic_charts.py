#!/usr/bin/env python3
"""Portable basic PNG charts shared by the Free and Pro runtimes."""

from __future__ import annotations

import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def date_only(value: str | None) -> str:
    return value[:10] if value else "—"


def font(size: int, bold: bool = False):
    windows_directory = os.environ.get("WINDIR")
    font_directory = Path(windows_directory) / "Fonts" if windows_directory else None
    candidates = [
        font_directory / "msyh.ttc" if font_directory else None,
        font_directory / ("msyhbd.ttc" if bold else "msyh.ttc") if font_directory else None,
        font_directory / "simhei.ttf" if font_directory else None,
        font_directory / "arial.ttf" if font_directory else None,
        "DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        path = Path(candidate)
        if not path.is_absolute() or path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def chart_base(title: str, subtitle: str = "") -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (1600, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((90, 50), title, fill="#163A5F", font=font(38, True))
    if subtitle:
        draw.text((92, 105), subtitle, fill="#667085", font=font(21))
    return image, draw


def chart_line(path: Path, title: str, subtitle: str, dates: list[str], series: list[tuple[str, list[float], str]], percent_axis: bool = False, zero_line: bool = False, log_scale: bool = False) -> None:
    image, draw = chart_base(title, subtitle)
    left, top, right, bottom = 110, 175, 1510, 770
    plotted_series = []
    for label, values_for_series, color in series:
        if log_scale:
            plotted_series.append((label, [math.log(max(value, 1e-9)) for value in values_for_series], color))
        else:
            plotted_series.append((label, values_for_series, color))
    values = [value for _, values_for_series, _ in plotted_series for value in values_for_series if math.isfinite(value)]
    if not values:
        return
    ymin, ymax = min(values), max(values)
    if ymin == ymax:
        ymin -= 1
        ymax += 1
    padding = (ymax - ymin) * 0.08
    ymin -= padding
    ymax += padding
    draw.rectangle((left, top, right, bottom), outline="#B9C6D3", width=2)
    for step in range(6):
        fraction = step / 5
        y = bottom - fraction * (bottom - top)
        value = ymin + fraction * (ymax - ymin)
        draw.line((left, y, right, y), fill="#E8EDF2", width=1)
        label_value = math.exp(value) if log_scale else value
        label = f"{label_value * 100:.0f}%" if percent_axis else f"{label_value:,.0f}"
        draw.text((20, y - 12), label, fill="#667085", font=font(18))
    if zero_line and ymin < 0 < ymax:
        y = bottom - (0 - ymin) / (ymax - ymin) * (bottom - top)
        draw.line((left, y, right, y), fill="#B54747", width=2)
    colors = []
    for index, (label, values_for_series, color) in enumerate(plotted_series):
        colors.append((label, color))
        points = []
        for point_index, value in enumerate(values_for_series):
            x = left + (right - left) * point_index / max(len(dates) - 1, 1)
            y = bottom - (value - ymin) / (ymax - ymin) * (bottom - top)
            points.append((x, y))
        if len(points) > 1:
            draw.line(points, fill=color, width=4)
        elif points:
            draw.ellipse((points[0][0] - 3, points[0][1] - 3, points[0][0] + 3, points[0][1] + 3), fill=color)
        if points:
            raw_value = series[index][1][-1]
            endpoint = f"{raw_value:,.0f}" if not percent_axis else f"{raw_value * 100:.2f}%"
            if log_scale and not percent_axis:
                endpoint = f"{raw_value:,.0f} ({raw_value / 100.0 - 1.0:+.0%})"
            label_width = max(112, draw.textbbox((0, 0), endpoint, font=font(16, True))[2] + 12)
            label_x = max(left, min(right - label_width, points[-1][0] - label_width - 4))
            label_y = max(top, min(bottom - 24, points[-1][1] - 28 - index * 24))
            draw.rounded_rectangle((label_x, label_y, label_x + label_width, label_y + 24), radius=5, fill="white", outline=color, width=1)
            draw.text((label_x + 6, label_y + 3), endpoint, fill=color, font=font(16, True))
    for index, (label, color) in enumerate(colors):
        x = 110 + index * 260
        draw.line((x, 825, x + 38, 825), fill=color, width=6)
        draw.text((x + 50, 811), label, fill="#243447", font=font(20))
    if dates:
        draw.text((left, 785), date_only(dates[0]), fill="#667085", font=font(18))
        end_text = date_only(dates[-1])
        end_width = draw.textbbox((0, 0), end_text, font=font(18))[2]
        draw.text((right - end_width, 785), end_text, fill="#667085", font=font(18))
    image.save(path, format="PNG", optimize=True)


def chart_bars(path: Path, title: str, subtitle: str, labels: list[str], values_a: list[float], values_b: list[float] | None = None, label_a: str = "策略", label_b: str = "买入持有", colors: tuple[str, str] = ("#163A5F", "#93A7BB")) -> None:
    image, draw = chart_base(title, subtitle)
    left, top, right, bottom = 110, 175, 1510, 770
    all_values = list(values_a) + (list(values_b) if values_b else [])
    ymin, ymax = min(0.0, min(all_values)), max(0.0, max(all_values))
    if ymin == ymax:
        ymax = 1.0
    padding = (ymax - ymin) * 0.12
    ymin -= padding
    ymax += padding
    draw.rectangle((left, top, right, bottom), outline="#B9C6D3", width=2)
    zero_y = bottom - (0 - ymin) / (ymax - ymin) * (bottom - top)
    draw.line((left, zero_y, right, zero_y), fill="#7A8794", width=2)
    for step in range(6):
        fraction = step / 5
        y = bottom - fraction * (bottom - top)
        value = ymin + fraction * (ymax - ymin)
        draw.line((left, y, right, y), fill="#E8EDF2", width=1)
        draw.text((20, y - 12), f"{value * 100:.0f}%", fill="#667085", font=font(18))
    count = len(labels)
    group_width = (right - left) / max(count, 1)
    bar_width = min(26, group_width / (3 if values_b else 2))
    for index, label in enumerate(labels):
        center = left + group_width * (index + 0.5)
        for series_index, values_for_series in enumerate([values_a] + ([values_b] if values_b is not None else [])):
            value = values_for_series[index]
            x0 = center + (series_index - (0.5 if values_b else 0)) * (bar_width + 4) - bar_width / 2
            y1 = bottom - (value - ymin) / (ymax - ymin) * (bottom - top)
            y0 = zero_y
            fill = colors[series_index]
            draw.rectangle((x0, min(y0, y1), x0 + bar_width, max(y0, y1)), fill=fill)
        if (index % max(1, count // 8) == 0 and not (count > 8 and index == count - 2)) or index == count - 1:
            text_width = draw.textbbox((0, 0), label, font=font(16))[2]
            draw.text((center - text_width / 2, bottom + 18), label, fill="#667085", font=font(16))
    legend = [(label_a, colors[0])]
    if values_b is not None:
        legend.append((label_b, colors[1]))
    for index, (label, color) in enumerate(legend):
        x = 110 + index * 260
        draw.rectangle((x, 825, x + 34, 847), fill=color)
        draw.text((x + 48, 820), label, fill="#243447", font=font(20))
    image.save(path, format="PNG", optimize=True)


def normalized_equity(curve: list[dict[str, object]]) -> list[float]:
    if not curve:
        return []
    initial = float(curve[0]["equity"])
    return [100.0 * float(point["equity"]) / initial for point in curve]
