"""Core orchestration: one place where every sensor reading is processed.

Both the dashboard simulator and the optional MQTT subscriber call
``WasteSystem.process_reading`` so they share exactly the same
classification, servo, fill-level and alert logic.
"""

from __future__ import annotations

import threading

from models.database import Database
from services import bins as bin_utils
from services.bins import BINS
from services.classifier import (
    NONE,
    SensorValidationError,
    classify,
    parse_reading,
    validate_threshold,
)
from services.servo import SimulatedServo

SETTING_KEYS = ("moisture_threshold", "fill_low_threshold", "fill_high_threshold", "fill_increment")
MAX_DEVICE_ID_LENGTH = 64


class WasteSystem:
    def __init__(self, db: Database, config):
        self.db = db
        self._lock = threading.RLock()
        self.servo = SimulatedServo(
            wet_angle=config.SERVO_ANGLE_WET,
            dry_angle=config.SERVO_ANGLE_DRY,
            metal_angle=config.SERVO_ANGLE_METAL,
            idle_angle=config.SERVO_ANGLE_IDLE,
        )

        defaults = {
            "moisture_threshold": float(config.MOISTURE_THRESHOLD),
            "fill_low_threshold": float(config.FILL_LOW_THRESHOLD),
            "fill_high_threshold": float(config.FILL_HIGH_THRESHOLD),
            "fill_increment": float(config.FILL_INCREMENT),
        }
        stored = db.get_settings()
        self.settings = {k: float(stored.get(k, v)) for k, v in defaults.items()}

        latest = db.get_latest_fill_levels()
        if latest is None:
            self.levels = {name: 0.0 for name in BINS}
            db.record_fill_levels(self.levels, source="init")
        else:
            self.levels = {name: float(latest[name]) for name in BINS}

    # ------------------------------------------------------------------ input
    def process_reading(self, raw: dict, source: str = "simulator") -> dict:
        """Validate, classify, divert, update bins, raise alerts, persist."""
        reading = parse_reading(raw)

        device_id = raw.get("device_id")
        if device_id is not None:
            if not isinstance(device_id, str) or len(device_id) > MAX_DEVICE_ID_LENGTH:
                raise SensorValidationError(
                    [f"'device_id' must be a string of at most {MAX_DEVICE_ID_LENGTH} characters"]
                )

        reported_fill = None
        if raw.get("fill") is not None:
            try:
                reported_fill = bin_utils.parse_fill_levels(raw["fill"])
            except ValueError as exc:
                raise SensorValidationError([str(exc)]) from exc

        with self._lock:
            category = classify(reading, self.settings["moisture_threshold"])
            servo = self.servo.divert(category)
            stored = self.db.record_reading_and_event(
                reading.to_dict(),
                category,
                source=source,
                device_id=device_id,
                servo=servo if category != NONE else None,
            )

            levels_changed = False
            fill_simulated = True
            if reported_fill:
                # Device-reported levels (e.g. ultrasonic) take precedence.
                for name, level in reported_fill.items():
                    self.levels[name] = bin_utils.clamp_level(level)
                levels_changed = True
                fill_simulated = False
            elif category != NONE:
                name = category.lower()
                self.levels[name] = bin_utils.clamp_level(
                    self.levels[name] + self.settings["fill_increment"]
                )
                levels_changed = True

            if levels_changed:
                self.db.record_fill_levels(self.levels, source=source, simulated=fill_simulated)
            new_alerts = self._evaluate_alerts()

        return {
            "classification": category,
            "sorted": category != NONE,
            "reading": {**reading.to_dict(), "device_id": device_id},
            "servo": servo,
            "source": source,
            "timestamp": stored["timestamp"],
            "event_id": stored["event_id"],
            "fill_levels": self.get_bins(),
            "new_alerts": new_alerts,
        }

    # ----------------------------------------------------------------- alerts
    def _evaluate_alerts(self) -> list[dict]:
        """Create an alert when a bin reaches HIGH; auto-resolve when it drops."""
        high = self.settings["fill_high_threshold"]
        created = []
        for name in BINS:
            level = self.levels[name]
            if level >= high:
                if not self.db.has_active_alert(name):
                    message = (
                        f"{name.capitalize()} bin is {level:g}% full "
                        f"(threshold {high:g}%). Empty the bin."
                    )
                    alert_id = self.db.create_alert(name, level, high, message)
                    created.append({"id": alert_id, "bin": name, "level": level, "message": message})
            elif self.db.has_active_alert(name):
                self.db.resolve_alerts(name)
        return created

    # -------------------------------------------------------------- bins/reset
    def get_bins(self) -> dict:
        low = self.settings["fill_low_threshold"]
        high = self.settings["fill_high_threshold"]
        return {
            name: {
                "level": self.levels[name],
                "status": bin_utils.fill_status(self.levels[name], low, high),
            }
            for name in BINS
        }

    def reset_bins(self, bin_name: str | None = None) -> dict:
        if bin_name is not None and bin_name not in BINS:
            raise SensorValidationError(["'bin' must be one of wet, dry, metal"])
        with self._lock:
            targets = [bin_name] if bin_name else list(BINS)
            for name in targets:
                self.levels[name] = 0.0
            self.db.record_fill_levels(self.levels, source="reset")
            resolved = 0
            for name in targets:
                resolved += self.db.resolve_alerts(name)
        return {"reset": targets, "alerts_resolved": resolved, "fill_levels": self.get_bins()}

    # --------------------------------------------------------------- settings
    def update_settings(self, values) -> dict:
        if not isinstance(values, dict) or not values:
            raise SensorValidationError(["request body must be a JSON object with settings to change"])
        unknown = [k for k in values if k not in SETTING_KEYS]
        if unknown:
            raise SensorValidationError([f"unknown setting(s): {', '.join(unknown)}"])

        new = dict(self.settings)
        for key, value in values.items():
            new[key] = validate_threshold(value, key)
        if new["fill_low_threshold"] >= new["fill_high_threshold"]:
            raise SensorValidationError(
                ["'fill_low_threshold' must be lower than 'fill_high_threshold'"]
            )
        if new["fill_increment"] <= 0:
            raise SensorValidationError(["'fill_increment' must be greater than 0"])

        with self._lock:
            self.settings = new
            self.db.save_settings(new)
            new_alerts = self._evaluate_alerts()
        return {"settings": dict(self.settings), "new_alerts": new_alerts}

    # ----------------------------------------------------------------- status
    def get_status(self) -> dict:
        counts = self.db.get_category_counts()
        return {
            "total_sorted": sum(counts.values()),
            "counts": counts,
            "no_item_readings": self.db.count_no_item_readings(),
            "fill_levels": self.get_bins(),
            "latest_reading": self.db.get_latest_reading(),
            "settings": dict(self.settings),
            "servo": self.servo.to_dict(),
            "active_alerts": len(self.db.get_alerts(active_only=True)),
        }
