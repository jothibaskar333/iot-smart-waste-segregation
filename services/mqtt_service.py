"""Optional MQTT subscriber (Paho MQTT 2.x).

Disabled by default. When MQTT_ENABLED=true the dashboard subscribes to
MQTT_TOPIC and feeds each JSON payload through the same
``WasteSystem.process_reading`` used by the simulator.

The app keeps working if the broker is missing or drops: Paho's network
thread retries in the background and the state is shown on the dashboard.
"""

from __future__ import annotations

import json
import logging
import threading

from models.database import utc_now
from services.classifier import SensorValidationError

log = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 2048


class MQTTService:
    def __init__(self, system, config):
        self.system = system
        self.enabled = bool(config.MQTT_ENABLED)
        self.host = config.MQTT_BROKER_HOST
        self.port = config.MQTT_BROKER_PORT
        self.topic = config.MQTT_TOPIC
        self.username = config.MQTT_USERNAME
        self.password = config.MQTT_PASSWORD
        self.client_id = config.MQTT_CLIENT_ID
        self.keepalive = config.MQTT_KEEPALIVE

        self._lock = threading.Lock()
        self.state = "disabled" if not self.enabled else "not_started"
        self.last_error: str | None = None
        self.last_message_at: str | None = None
        self.messages_received = 0
        self.messages_rejected = 0
        self._client = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if not self.enabled or self._client is not None:
            return
        import paho.mqtt.client as mqtt

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
        )
        if self.username:
            client.username_pw_set(self.username, self.password)
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_connect_fail = self._on_connect_fail
        client.on_message = self._on_message

        self._set_state("connecting")
        try:
            # connect_async + loop_start never blocks start-up; Paho keeps
            # retrying in its background thread if the broker is unreachable.
            client.connect_async(self.host, self.port, keepalive=self.keepalive)
            client.loop_start()
        except Exception as exc:  # e.g. invalid host string
            self._set_state("error", f"Could not start MQTT client: {exc}")
            log.warning("MQTT start failed: %s", exc)
            return
        self._client = client

    def stop(self) -> None:
        if self._client is not None:
            self._client.disconnect()
            self._client.loop_stop()
            self._client = None
            self._set_state("disconnected")

    # ------------------------------------------------------------ callbacks
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            self._set_state("error", f"Broker refused connection: {reason_code}")
            return
        client.subscribe(self.topic, qos=1)
        self._set_state("connected")
        log.info("MQTT connected to %s:%s, subscribed to %s", self.host, self.port, self.topic)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        if self.state == "disabled":
            return
        self._set_state("disconnected", f"Disconnected from broker: {reason_code}")
        log.warning("MQTT disconnected (%s); Paho will retry", reason_code)

    def _on_connect_fail(self, client, userdata):
        self._set_state(
            "disconnected", f"Cannot reach broker at {self.host}:{self.port}; retrying"
        )
        log.warning("MQTT broker %s:%s unreachable; Paho will retry", self.host, self.port)

    def _on_message(self, client, userdata, message):
        self.handle_payload(message.payload)

    # -------------------------------------------------------------- payload
    def handle_payload(self, payload: bytes) -> dict | None:
        """Decode a JSON payload and process it. Bad payloads are counted, not raised."""
        with self._lock:
            self.messages_received += 1
            self.last_message_at = utc_now()
        try:
            if len(payload) > MAX_PAYLOAD_BYTES:
                raise SensorValidationError([f"payload larger than {MAX_PAYLOAD_BYTES} bytes"])
            try:
                data = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SensorValidationError([f"payload is not valid JSON: {exc}"]) from exc
            return self.system.process_reading(data, source="mqtt")
        except SensorValidationError as exc:
            with self._lock:
                self.messages_rejected += 1
                self.last_error = f"Rejected MQTT payload: {exc}"
            log.warning("Rejected MQTT payload: %s", exc)
            return None

    # --------------------------------------------------------------- status
    def _set_state(self, state: str, error: str | None = None) -> None:
        with self._lock:
            self.state = state
            if error:
                self.last_error = error

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self.enabled,
                "state": self.state,
                "connected": self.state == "connected",
                "broker": f"{self.host}:{self.port}" if self.enabled else None,
                "topic": self.topic if self.enabled else None,
                "last_error": self.last_error,
                "last_message_at": self.last_message_at,
                "messages_received": self.messages_received,
                "messages_rejected": self.messages_rejected,
            }
