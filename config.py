"""Application configuration.

All values can be overridden with environment variables so that no
credentials or machine-specific settings ever need to be committed.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


class Config:
    """Default configuration, read once at start-up."""

    # --- Flask -------------------------------------------------------------
    HOST = os.environ.get("APP_HOST", "127.0.0.1")
    PORT = _env_int("APP_PORT", 5000)
    DEBUG = _env_bool("APP_DEBUG", False)

    # --- Storage -----------------------------------------------------------
    DATABASE_PATH = os.environ.get(
        "DATABASE_PATH", str(BASE_DIR / "instance" / "waste_system.db")
    )

    # --- Classification defaults (editable later from the dashboard) -------
    # Moisture is expressed as a normalised percentage (0-100).
    MOISTURE_THRESHOLD = _env_float("MOISTURE_THRESHOLD", 60.0)

    # --- Fill-level defaults (editable later from the dashboard) -----------
    FILL_LOW_THRESHOLD = _env_float("FILL_LOW_THRESHOLD", 30.0)
    FILL_HIGH_THRESHOLD = _env_float("FILL_HIGH_THRESHOLD", 80.0)
    # How much a simulated bin fills up per sorted item (percent).
    FILL_INCREMENT = _env_float("FILL_INCREMENT", 5.0)

    # --- Simulated servo diverter angles (degrees) -------------------------
    SERVO_ANGLE_WET = _env_int("SERVO_ANGLE_WET", 45)
    SERVO_ANGLE_DRY = _env_int("SERVO_ANGLE_DRY", 90)
    SERVO_ANGLE_METAL = _env_int("SERVO_ANGLE_METAL", 135)
    SERVO_ANGLE_IDLE = _env_int("SERVO_ANGLE_IDLE", 0)

    # --- Optional MQTT input ------------------------------------------------
    MQTT_ENABLED = _env_bool("MQTT_ENABLED", False)
    MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
    MQTT_BROKER_PORT = _env_int("MQTT_BROKER_PORT", 1883)
    MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "smartwaste/sensors")
    MQTT_USERNAME = os.environ.get("MQTT_USERNAME") or None
    MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD") or None
    MQTT_CLIENT_ID = os.environ.get("MQTT_CLIENT_ID", "smart-waste-dashboard")
    MQTT_KEEPALIVE = _env_int("MQTT_KEEPALIVE", 60)
