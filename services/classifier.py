"""Rule-based waste classifier.

This is deliberately simple, educational logic built on three sensor inputs:

* IR sensor        -> is an item present on the sorting platform?
* Moisture sensor  -> normalised moisture percentage (0-100)
* Metal sensor     -> did the inductive/metal sensor trigger?

Priority order:
    1. No item detected     -> no sorting operation (NONE)
    2. Metal detected       -> METAL
    3. Moisture > threshold -> WET
    4. Otherwise            -> DRY

It is NOT a universal waste-classification method. Real waste is often
mixed (for example a damp paper cup or a foil-lined food wrapper) and a
single moisture/metal reading cannot capture that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

WET = "WET"
DRY = "DRY"
METAL = "METAL"
NONE = "NONE"

CATEGORIES = (WET, DRY, METAL)

MOISTURE_MIN = 0.0
MOISTURE_MAX = 100.0


class SensorValidationError(ValueError):
    """Raised when a sensor reading is missing fields or out of range."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class SensorReading:
    ir_detected: bool
    moisture: float
    metal_detected: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_bool(value, field: str, errors: list[str]):
    """Accept JSON booleans or the integers 0/1 (common from microcontrollers)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    errors.append(f"'{field}' must be a boolean (true/false or 0/1), got {value!r}")
    return None


def _parse_moisture(value, errors: list[str]):
    # bool is a subclass of int in Python, so reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"'moisture' must be a number, got {value!r}")
        return None
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        errors.append("'moisture' must be a finite number")
        return None
    if not MOISTURE_MIN <= value <= MOISTURE_MAX:
        errors.append(
            f"'moisture' must be between {MOISTURE_MIN:g} and {MOISTURE_MAX:g}, got {value:g}"
        )
        return None
    return value


def parse_reading(data) -> SensorReading:
    """Validate a raw dict (from JSON / MQTT) and build a SensorReading.

    Expected keys: ``ir`` (bool), ``moisture`` (0-100), ``metal`` (bool).
    """
    if not isinstance(data, dict):
        raise SensorValidationError(["sensor reading must be a JSON object"])

    errors: list[str] = []
    for key in ("ir", "moisture", "metal"):
        if key not in data:
            errors.append(f"missing required field '{key}'")
    if errors:
        raise SensorValidationError(errors)

    ir = _parse_bool(data["ir"], "ir", errors)
    metal = _parse_bool(data["metal"], "metal", errors)
    moisture = _parse_moisture(data["moisture"], errors)
    if errors:
        raise SensorValidationError(errors)

    return SensorReading(ir_detected=ir, moisture=moisture, metal_detected=metal)


def validate_threshold(value, name: str) -> float:
    """Validate a percentage threshold (0-100)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SensorValidationError([f"'{name}' must be a number"])
    value = float(value)
    if math.isnan(value) or not 0.0 <= value <= 100.0:
        raise SensorValidationError([f"'{name}' must be between 0 and 100"])
    return value


def classify(reading: SensorReading, moisture_threshold: float) -> str:
    """Return WET, DRY, METAL, or NONE (no item -> no sorting)."""
    if not reading.ir_detected:
        return NONE
    if reading.metal_detected:
        return METAL
    if reading.moisture > moisture_threshold:
        return WET
    return DRY
