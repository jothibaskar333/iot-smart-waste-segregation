"""Tests for fill levels, alerts, servo actions, settings and persistence."""

import pytest

from models.database import Database
from services.bins import HIGH, LOW, NORMAL, fill_status
from services.classifier import SensorValidationError
from services.mqtt_service import MQTTService
from services.waste_system import WasteSystem

WET_ITEM = {"ir": True, "moisture": 90, "metal": False}
DRY_ITEM = {"ir": True, "moisture": 10, "metal": False}
METAL_ITEM = {"ir": True, "moisture": 50, "metal": True}
NO_ITEM = {"ir": False, "moisture": 2, "metal": False}


def test_fill_status_boundaries():
    assert fill_status(0, 30, 80) == LOW
    assert fill_status(29.9, 30, 80) == LOW
    assert fill_status(30, 30, 80) == NORMAL
    assert fill_status(79.9, 30, 80) == NORMAL
    assert fill_status(80, 30, 80) == HIGH


def test_sorting_increments_correct_bin(system):
    system.process_reading(WET_ITEM)
    system.process_reading(METAL_ITEM)
    bins = system.get_bins()
    assert bins["wet"]["level"] == 5.0
    assert bins["metal"]["level"] == 5.0
    assert bins["dry"]["level"] == 0.0


def test_no_item_does_not_sort_or_fill(system):
    result = system.process_reading(NO_ITEM)
    assert result["sorted"] is False
    assert result["event_id"] is None
    assert result["servo"]["action"] == "NO_ACTION"
    assert all(b["level"] == 0 for b in system.get_bins().values())
    assert system.db.get_events() == []
    assert system.db.count_no_item_readings() == 1


def test_servo_targets_category_angles(system):
    angles = system.servo.angles
    assert system.process_reading(WET_ITEM)["servo"]["target_angle"] == angles["WET"]
    assert system.process_reading(DRY_ITEM)["servo"]["target_angle"] == angles["DRY"]
    assert system.process_reading(METAL_ITEM)["servo"]["target_angle"] == angles["METAL"]


def test_high_fill_alert_generated_once(system):
    results = [system.process_reading(DRY_ITEM) for _ in range(16)]  # 16 * 5% = 80%
    alerts_raised = [a for r in results for a in r["new_alerts"]]
    assert len(alerts_raised) == 1
    assert alerts_raised[0]["bin"] == "dry"
    assert results[15]["fill_levels"]["dry"]["status"] == HIGH
    assert results[14]["new_alerts"] == []  # 75% - below threshold

    # Further items do not duplicate the active alert.
    system.process_reading(DRY_ITEM)
    active = system.db.get_alerts(active_only=True)
    assert len(active) == 1


def test_reset_clears_levels_and_resolves_alerts(system):
    for _ in range(16):
        system.process_reading(WET_ITEM)
    assert system.db.get_alerts(active_only=True)
    result = system.reset_bins()
    assert result["alerts_resolved"] == 1
    assert system.get_bins()["wet"]["level"] == 0
    assert system.db.get_alerts(active_only=True) == []
    history = system.db.get_alerts()
    assert history[0]["resolved_at"] is not None


def test_reset_single_bin_and_invalid_bin(system):
    system.process_reading(WET_ITEM)
    system.process_reading(DRY_ITEM)
    system.reset_bins("wet")
    bins = system.get_bins()
    assert bins["wet"]["level"] == 0 and bins["dry"]["level"] == 5
    with pytest.raises(SensorValidationError):
        system.reset_bins("glass")


def test_lowering_high_threshold_raises_alert(system):
    for _ in range(10):  # 50%
        system.process_reading(METAL_ITEM)
    result = system.update_settings({"fill_high_threshold": 50})
    assert [a["bin"] for a in result["new_alerts"]] == ["metal"]


def test_settings_validation(system):
    with pytest.raises(SensorValidationError):
        system.update_settings({"fill_low_threshold": 90})  # low >= high
    with pytest.raises(SensorValidationError):
        system.update_settings({"moisture_threshold": 150})
    with pytest.raises(SensorValidationError):
        system.update_settings({"unknown": 1})


def test_fill_level_capped_at_100(system):
    system.update_settings({"fill_increment": 60})
    system.process_reading(WET_ITEM)
    system.process_reading(WET_ITEM)
    assert system.get_bins()["wet"]["level"] == 100


def test_device_reported_fill_levels_override_simulation(system):
    system.process_reading({**DRY_ITEM, "fill": {"dry": 42.5, "wet": 10}}, source="mqtt")
    bins = system.get_bins()
    assert bins["dry"]["level"] == 42.5
    assert bins["wet"]["level"] == 10
    latest = system.db.get_fill_history()[-1]
    assert latest["simulated"] is False and latest["source"] == "mqtt"


def test_events_persist_across_restart(test_config):
    db = Database(test_config.DATABASE_PATH)
    first = WasteSystem(db, test_config)
    first.process_reading(WET_ITEM)
    first.process_reading(METAL_ITEM)
    first.update_settings({"moisture_threshold": 45})

    # A brand-new instance on the same file sees the same data.
    second = WasteSystem(Database(test_config.DATABASE_PATH), test_config)
    events = second.db.get_events()
    assert [e["category"] for e in events] == ["METAL", "WET"]
    assert events[1]["moisture"] == 90
    assert second.get_bins()["wet"]["level"] == 5
    assert second.settings["moisture_threshold"] == 45


def test_mqtt_payload_processed_with_same_logic(system, test_config):
    mqtt = MQTTService(system, test_config)
    result = mqtt.handle_payload(b'{"device_id": "esp32-01", "ir": true, "moisture": 72, "metal": false}')
    assert result["classification"] == "WET"
    assert result["source"] == "mqtt"
    assert system.db.get_events()[0]["device_id"] == "esp32-01"


def test_mqtt_bad_payloads_are_rejected_not_raised(system, test_config):
    mqtt = MQTTService(system, test_config)
    assert mqtt.handle_payload(b"not json") is None
    assert mqtt.handle_payload(b'{"ir": true, "moisture": 500, "metal": false}') is None
    status = mqtt.status()
    assert status["messages_received"] == 2
    assert status["messages_rejected"] == 2
    assert status["state"] == "disabled"
    assert system.db.get_events() == []
