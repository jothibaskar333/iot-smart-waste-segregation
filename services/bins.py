"""Fill-level helpers for the three bins (wet, dry, metal).

In simulation mode the level rises by a fixed increment for each item sorted
into a bin. A future ESP32/ESP8266 node can instead report a measured level
(for example derived from an ultrasonic distance sensor) in its MQTT payload.
"""

from __future__ import annotations

import math

BINS = ("wet", "dry", "metal")

LOW = "LOW"
NORMAL = "NORMAL"
HIGH = "HIGH"


def fill_status(level: float, low_threshold: float, high_threshold: float) -> str:
    """LOW below the low threshold, HIGH at/above the high threshold, else NORMAL."""
    if level >= high_threshold:
        return HIGH
    if level < low_threshold:
        return LOW
    return NORMAL


def clamp_level(level: float) -> float:
    return round(max(0.0, min(100.0, level)), 1)


def parse_fill_levels(data) -> dict[str, float]:
    """Validate an optional ``fill`` object such as {"wet": 42, "dry": 10}.

    Only the bins present are returned. Raises ValueError on bad input.
    """
    if not isinstance(data, dict):
        raise ValueError("'fill' must be an object like {\"wet\": 40, \"dry\": 20, \"metal\": 5}")
    levels: dict[str, float] = {}
    for key, value in data.items():
        if key not in BINS:
            raise ValueError(f"unknown bin '{key}' in 'fill' (expected wet, dry or metal)")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value):
            raise ValueError(f"fill level for '{key}' must be a number")
        if not 0 <= value <= 100:
            raise ValueError(f"fill level for '{key}' must be between 0 and 100")
        levels[key] = float(value)
    return levels
