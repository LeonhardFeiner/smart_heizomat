#!/usr/bin/env python3
"""
Heizomat MQTT Monitor - VNC DIRECT Edition
Direct coordinate mapping for raw VNC (800x480)
"""

import concurrent.futures
import datetime
import json
import logging
import os
import sys
import time
from itertools import chain

import paho.mqtt.client as mqtt

from heizomat.sensors import boiler_sensors, main_sensors, sensor_dict, setpoint_sensors
from heizomat.vnc import capture_hmi
from heizomat.ocr import crop_and_ocr

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

VNC_ADDRESS = os.environ.get("VNC_ADDRESS")
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "heizomat/values")
SENSOR_BASENAME = os.environ.get("SENSOR_BASENAME", "heizomat")
MQTT_USERNAME = os.environ.get("MQTT_USERNAME") or None
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD") or None
PUBLISH_INTERVAL = float(os.environ.get("PUBLISH_INTERVAL", "10"))

HA_DISCOVERY_PREFIX = "homeassistant"
WATCHDOG_MAX_FAILURES = int(os.environ.get("WATCHDOG_MAX_FAILURES", "5"))

AVAILABILITY_TOPIC = f"{SENSOR_BASENAME}/status"
PAYLOAD_AVAILABLE = "ready"
PAYLOAD_NOT_AVAILABLE = "lost"

if not VNC_ADDRESS:
    raise ValueError("VNC_ADDRESS environment variable required")

logger.info(f"Heizomat MQTT - VNC DIRECT Edition")
logger.info(f"MQTT={MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")
logger.info(f"VNC={VNC_ADDRESS}")

mqtt_connected = False
_discovery_sent = False


# ----------------------------------------------------------------------
# MQTT & DISCOVERY
# ----------------------------------------------------------------------
def _slugify(name: str) -> str:
    result = name.lower()
    for src, dst in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        result = result.replace(src, dst)
    return result


def on_connect(client, userdata, flags, reason_code, properties=None):
    global mqtt_connected, _discovery_sent
    if reason_code == 0:
        logger.info("MQTT Connected")
        mqtt_connected = True
        if not _discovery_sent:
            send_ha_discovery(client)
            _discovery_sent = True
        client.publish(AVAILABILITY_TOPIC, PAYLOAD_AVAILABLE, qos=1, retain=True)
    else:
        logger.error(f"MQTT Connection failed: {reason_code}")


def send_ha_discovery(client):
    prefix = SENSOR_BASENAME
    logger.info(f"Sending HA Discovery using prefix: {prefix}...")

    for sensor in chain.from_iterable(sensor_dict.values()):
        obj_id = _slugify(sensor.name)
        topic = f"{HA_DISCOVERY_PREFIX}/sensor/{prefix}/{obj_id}/config"

        config = {
            "name": sensor.name,
            "default_entity_id": f"sensor.{prefix}_{obj_id}",
            "unique_id": f"{prefix}_{obj_id}",
            "state_topic": MQTT_TOPIC,
            "value_template": f"{{{{ value_json.{sensor.name} }}}}",
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": PAYLOAD_AVAILABLE,
            "payload_not_available": PAYLOAD_NOT_AVAILABLE,
            "device": {
                "identifiers": [prefix],
                "name": prefix,
                "manufacturer": "Heizomat",
                "model": "RHK-AK 100",
            },
            "icon": sensor.icon,
        }
        if sensor.unit:
            config["unit_of_measurement"] = sensor.unit
        if sensor.device_class:
            config["device_class"] = sensor.device_class
        if sensor.state_class:
            config["state_class"] = sensor.state_class

        client.publish(topic, json.dumps(config), qos=1, retain=True)


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    mqtt_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id="heizomat_vnc_monitor"
    )
    mqtt_client.on_connect = on_connect
    if MQTT_USERNAME:
        mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    mqtt_client.will_set(AVAILABILITY_TOPIC, PAYLOAD_NOT_AVAILABLE, qos=1, retain=True)

    try:
        mqtt_client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        logger.error(f"Could not connect to MQTT: {e}")

    consecutive_failures = 0

    try:
        while True:
            cycle_start = time.time()
            screens = capture_hmi()

            if screens:
                try:
                    final_data = {}

                    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                        future_to_sensor = {}
                        for name, img in screens.items():
                            sensors = sensor_dict[name]
                            for s in sensors:
                                future = executor.submit(crop_and_ocr, img, s)
                                future_to_sensor[future] = s.name

                        for future in concurrent.futures.as_completed(future_to_sensor):
                            sensor_name = future_to_sensor[future]
                            try:
                                val = future.result()
                                if val is not None:
                                    final_data[sensor_name] = val
                            except Exception as exc:
                                logger.error(f"Sensor '{sensor_name}' exception: {exc}")

                    total_expected = len(main_sensors) + len(boiler_sensors)
                    success_count = len(final_data)

                    if success_count < total_expected:
                        missing = [
                            s.name
                            for s in chain(main_sensors, boiler_sensors)
                            if s.name not in final_data
                        ]
                        logger.warning(
                            f"Missing {total_expected - success_count} sensors: {', '.join(missing)}"
                        )

                    if final_data:
                        final_data["timestamp"] = datetime.datetime.now().isoformat()
                        mqtt_client.publish(MQTT_TOPIC, json.dumps(final_data), qos=1, retain=True)
                        logger.info(f"Published {len(final_data)} sensors")
                        consecutive_failures = 0
                    else:
                        logger.warning("Empty data set after OCR")
                        consecutive_failures += 1

                except Exception as e:
                    logger.error(f"Processing error: {e}")
                    consecutive_failures += 1
            elif screens is None:
                consecutive_failures += 1

            if consecutive_failures >= WATCHDOG_MAX_FAILURES:
                logger.error("Watchdog failure limit reached. Restarting...")
                sys.exit(1)

            elapsed = time.time() - cycle_start
            if elapsed > PUBLISH_INTERVAL:
                logger.warning(
                    f"Cycle took longer ({elapsed:.1f}s) than interval ({PUBLISH_INTERVAL}s)!"
                )

            now = time.time()
            next_target = (now // PUBLISH_INTERVAL + 1) * PUBLISH_INTERVAL
            time.sleep(next_target - now)

    finally:
        # A clean disconnect() below suppresses the broker-side LWT, so publish
        # the "lost" availability ourselves for graceful shutdowns (e.g. the
        # watchdog restart above). Ungraceful deaths still fall back to the LWT.
        try:
            mqtt_client.publish(
                AVAILABILITY_TOPIC, PAYLOAD_NOT_AVAILABLE, qos=1, retain=True
            ).wait_for_publish(timeout=2)
        except Exception:
            pass
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()
