import random

import pytest

from services.classifier import (
    DRY,
    METAL,
    NONE,
    WET,
    SensorReading,
    SensorValidationError,
    classify,
    parse_reading,
)
from services.simulator import generate_reading

THRESHOLD = 60.0


def reading(ir=True, moisture=10.0, metal=False):
    return SensorReading(ir_detected=ir, moisture=moisture, metal_detected=metal)


def test_no_item_detected_means_no_sorting():
    assert classify(reading(ir=False, moisture=95, metal=True), THRESHOLD) == NONE


def test_metal_takes_priority_over_moisture():
    assert classify(reading(moisture=95, metal=True), THRESHOLD) == METAL
    assert classify(reading(moisture=5, metal=True), THRESHOLD) == METAL


def test_wet_above_threshold():
    assert classify(reading(moisture=60.1), THRESHOLD) == WET


def test_dry_below_threshold():
    assert classify(reading(moisture=20), THRESHOLD) == DRY


def test_moisture_equal_to_threshold_is_dry():
    # The rule is "moisture exceeds the threshold" -> strictly greater.
    assert classify(reading(moisture=60.0), THRESHOLD) == DRY


def test_threshold_is_configurable():
    r = reading(moisture=40)
    assert classify(r, 60) == DRY
    assert classify(r, 30) == WET


def test_parse_valid_reading_accepts_0_1_booleans():
    r = parse_reading({"ir": 1, "moisture": 42, "metal": 0})
    assert r == SensorReading(ir_detected=True, moisture=42.0, metal_detected=False)


@pytest.mark.parametrize(
    "payload, fragment",
    [
        ({"ir": True, "moisture": 50}, "missing required field 'metal'"),
        ({"ir": True, "moisture": -1, "metal": False}, "between 0 and 100"),
        ({"ir": True, "moisture": 100.5, "metal": False}, "between 0 and 100"),
        ({"ir": True, "moisture": "wet", "metal": False}, "must be a number"),
        ({"ir": True, "moisture": True, "metal": False}, "must be a number"),
        ({"ir": True, "moisture": float("nan"), "metal": False}, "finite"),
        ({"ir": "yes", "moisture": 50, "metal": False}, "'ir' must be a boolean"),
        ({"ir": True, "moisture": 50, "metal": 2}, "'metal' must be a boolean"),
    ],
)
def test_invalid_sensor_values_rejected(payload, fragment):
    with pytest.raises(SensorValidationError) as exc:
        parse_reading(payload)
    assert fragment in str(exc.value)


def test_non_object_reading_rejected():
    with pytest.raises(SensorValidationError):
        parse_reading(["ir", "moisture"])


@pytest.mark.parametrize(
    "scenario, expected", [("wet", WET), ("dry", DRY), ("metal", METAL), ("none", NONE)]
)
def test_simulator_scenarios_classify_as_requested(scenario, expected):
    rng = random.Random(1234)
    for threshold in (10, 60, 90):
        for _ in range(50):
            raw = generate_reading(scenario, threshold, rng)
            assert classify(parse_reading(raw), threshold) == expected
