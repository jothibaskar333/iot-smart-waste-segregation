"""Generates plausible *simulated* sensor readings for the demo buttons.

Values are random but chosen relative to the current moisture threshold so
that, for example, "simulate wet waste" produces a reading the classifier
will see as wet. None of these values come from a physical sensor.
"""

from __future__ import annotations

import random

SCENARIOS = ("wet", "dry", "metal", "none")


def generate_reading(scenario: str, moisture_threshold: float, rng: random.Random | None = None) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError(f"'type' must be one of: {', '.join(SCENARIOS)}")
    rng = rng or random.Random()

    if scenario == "wet":
        low = moisture_threshold + (100 - moisture_threshold) * 0.2
        moisture = rng.uniform(low, 100)
        reading = {"ir": True, "moisture": moisture, "metal": False}
    elif scenario == "dry":
        moisture = rng.uniform(0, moisture_threshold * 0.8)
        reading = {"ir": True, "moisture": moisture, "metal": False}
    elif scenario == "metal":
        # Any moisture - metal detection has priority over moisture.
        moisture = rng.uniform(5, 70)
        reading = {"ir": True, "moisture": moisture, "metal": True}
    else:
        # Empty platform: the moisture probe reads ambient dryness.
        moisture = rng.uniform(0, 8)
        reading = {"ir": False, "moisture": moisture, "metal": False}

    reading["moisture"] = round(reading["moisture"], 1)
    reading["device_id"] = "simulator"
    return reading
