"""Flask entry point for the IoT-Based Smart Waste Segregation and Monitoring System.

Run with:  python app.py
"""

from __future__ import annotations

import atexit
import logging

from flask import Flask, jsonify, render_template, request

from config import Config
from models.database import Database
from services.classifier import SensorValidationError
from services.mqtt_service import MQTTService
from services.simulator import SCENARIOS, generate_reading
from services.waste_system import WasteSystem

MAX_LIMIT = 500


def _error(message: str, status: int = 400, details: list[str] | None = None):
    body = {"error": message}
    if details:
        body["details"] = details
    return jsonify(body), status


def _parse_limit(default: int):
    raw = request.args.get("limit")
    if raw is None:
        return default, None
    try:
        value = int(raw)
    except ValueError:
        return None, _error("'limit' must be an integer")
    if not 1 <= value <= MAX_LIMIT:
        return None, _error(f"'limit' must be between 1 and {MAX_LIMIT}")
    return value, None


def _json_body():
    """Return the parsed JSON body, or None if it is missing/invalid."""
    return request.get_json(silent=True)


def create_app(config_object=Config, start_mqtt: bool = True) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.json.sort_keys = False

    db = Database(config_object.DATABASE_PATH)
    system = WasteSystem(db, config_object)
    mqtt = MQTTService(system, config_object)
    app.extensions["waste_system"] = system
    app.extensions["mqtt_service"] = mqtt

    if start_mqtt and mqtt.enabled:
        mqtt.start()
        atexit.register(mqtt.stop)

    # ------------------------------------------------------------- pages
    @app.get("/")
    def index():
        return render_template("index.html")

    # --------------------------------------------------------------- API
    @app.get("/api/status")
    def api_status():
        status = system.get_status()
        status["mode"] = "SIMULATION"
        status["hardware"] = {
            "servo": "simulated",
            "sensors": "simulated unless received via MQTT",
            "physical_hardware_tested": False,
        }
        status["mqtt"] = mqtt.status()
        return jsonify(status)

    @app.get("/api/events")
    def api_events():
        limit, err = _parse_limit(20)
        if err:
            return err
        return jsonify({"events": db.get_events(limit)})

    @app.get("/api/fill-levels")
    def api_fill_levels():
        limit, err = _parse_limit(50)
        if err:
            return err
        return jsonify(
            {
                "current": system.get_bins(),
                "thresholds": {
                    "low": system.settings["fill_low_threshold"],
                    "high": system.settings["fill_high_threshold"],
                },
                "history": db.get_fill_history(limit),
            }
        )

    @app.get("/api/alerts")
    def api_alerts():
        limit, err = _parse_limit(50)
        if err:
            return err
        active_only = request.args.get("active", "").lower() in {"1", "true", "yes"}
        return jsonify(
            {
                "active": db.get_alerts(active_only=True, limit=limit),
                "history": [] if active_only else db.get_alerts(limit=limit),
            }
        )

    @app.post("/api/simulate")
    def api_simulate():
        body = _json_body()
        if not isinstance(body, dict):
            return _error("request body must be JSON, e.g. {\"type\": \"wet\"}")

        if "reading" in body:
            # Custom simulated reading typed into the dashboard.
            raw = body["reading"]
            if isinstance(raw, dict):
                raw = {**raw, "device_id": raw.get("device_id", "simulator")}
        elif "type" in body:
            scenario = str(body["type"]).lower()
            if scenario not in SCENARIOS:
                return _error(f"'type' must be one of: {', '.join(SCENARIOS)}")
            raw = generate_reading(scenario, system.settings["moisture_threshold"])
        else:
            return _error("provide either 'type' (wet/dry/metal/none) or a 'reading' object")

        try:
            result = system.process_reading(raw, source="simulator")
        except SensorValidationError as exc:
            return _error("invalid sensor reading", details=exc.errors)
        return jsonify(result), 201 if result["sorted"] else 200

    @app.post("/api/reset")
    def api_reset():
        body = _json_body() or {}
        if not isinstance(body, dict):
            return _error("request body must be a JSON object")
        try:
            return jsonify(system.reset_bins(body.get("bin")))
        except SensorValidationError as exc:
            return _error("invalid reset request", details=exc.errors)

    @app.get("/api/settings")
    def api_get_settings():
        return jsonify({"settings": system.settings})

    @app.route("/api/settings", methods=["PUT", "POST"])
    def api_update_settings():
        try:
            return jsonify(system.update_settings(_json_body()))
        except SensorValidationError as exc:
            return _error("invalid settings", details=exc.errors)

    # ------------------------------------------------------------ errors
    @app.errorhandler(404)
    def not_found(exc):
        if request.path.startswith("/api/"):
            return _error("endpoint not found", 404)
        return exc

    @app.errorhandler(405)
    def method_not_allowed(exc):
        if request.path.startswith("/api/"):
            return _error("method not allowed for this endpoint", 405)
        return exc

    @app.errorhandler(500)
    def server_error(exc):
        app.logger.exception("Unhandled error")
        return _error("internal server error", 500)

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    application = create_app()
    # The reloader is disabled so the MQTT client is not started twice.
    application.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, use_reloader=False)
