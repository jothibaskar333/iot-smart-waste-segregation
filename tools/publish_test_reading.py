"""Publish a test sensor reading to the MQTT broker.

This stands in for an ESP32/ESP8266 node so you can test MQTT mode without
hardware. It uses the same environment variables as the dashboard.

Examples (PowerShell):
    python tools/publish_test_reading.py --type wet
    python tools/publish_test_reading.py --ir 1 --moisture 35 --metal 1
    python tools/publish_test_reading.py --type dry --fill-dry 55
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import paho.mqtt.client as mqtt

PRESETS = {
    "wet": {"ir": True, "moisture": 78.0, "metal": False},
    "dry": {"ir": True, "moisture": 18.0, "metal": False},
    "metal": {"ir": True, "moisture": 30.0, "metal": True},
    "none": {"ir": False, "moisture": 3.0, "metal": False},
}


def build_payload(args) -> dict:
    payload = {"device_id": args.device_id, **PRESETS[args.type]}
    if args.ir is not None:
        payload["ir"] = bool(args.ir)
    if args.moisture is not None:
        payload["moisture"] = args.moisture
    if args.metal is not None:
        payload["metal"] = bool(args.metal)
    fill = {
        name: value
        for name, value in (("wet", args.fill_wet), ("dry", args.fill_dry), ("metal", args.fill_metal))
        if value is not None
    }
    if fill:
        payload["fill"] = fill
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--type", choices=PRESETS, default="wet", help="preset reading (default: wet)")
    parser.add_argument("--ir", type=int, choices=(0, 1), help="override IR value")
    parser.add_argument("--moisture", type=float, help="override moisture percent (0-100)")
    parser.add_argument("--metal", type=int, choices=(0, 1), help="override metal value")
    parser.add_argument("--fill-wet", type=float, help="optional reported wet-bin level")
    parser.add_argument("--fill-dry", type=float, help="optional reported dry-bin level")
    parser.add_argument("--fill-metal", type=float, help="optional reported metal-bin level")
    parser.add_argument("--device-id", default="test-publisher")
    parser.add_argument("--host", default=os.environ.get("MQTT_BROKER_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MQTT_BROKER_PORT", "1883")))
    parser.add_argument("--topic", default=os.environ.get("MQTT_TOPIC", "smartwaste/sensors"))
    args = parser.parse_args()

    payload = json.dumps(build_payload(args))
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id="")
    if os.environ.get("MQTT_USERNAME"):
        client.username_pw_set(os.environ["MQTT_USERNAME"], os.environ.get("MQTT_PASSWORD"))

    try:
        client.connect(args.host, args.port, keepalive=30)
    except OSError as exc:
        print(f"Could not connect to MQTT broker at {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1

    client.loop_start()
    info = client.publish(args.topic, payload, qos=1)
    info.wait_for_publish(timeout=5)
    client.loop_stop()
    client.disconnect()

    if not info.is_published():
        print("Publish did not complete within 5 seconds.", file=sys.stderr)
        return 1
    print(f"Published to {args.topic} on {args.host}:{args.port}: {payload}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
