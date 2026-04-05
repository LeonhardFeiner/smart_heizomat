#!/usr/bin/env python3
"""
Heizomat MQTT Monitor v4.0 - DATACLASS Edition
Single source of truth for all sensors + HA Auto-Discovery
"""

from itertools import chain
import subprocess
from PIL import Image
import cv2
import numpy as np
import pytesseract
import os
import logging
import json
import time
import concurrent.futures
import paho.mqtt.client as mqtt
import re
from dataclasses import dataclass
from typing import Tuple, Optional
import datetime
import sys

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

URL = os.environ.get("URL")
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "heizomat/values")
SENSOR_BASENAME = os.environ.get("SENSOR_BASENAME", "heizomat")
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
PUBLISH_INTERVAL = float(os.environ.get("PUBLISH_INTERVAL", "10"))
HA_DISCOVERY_PREFIX = "homeassistant"
CAPTURE_TIMEOUT = int(os.environ.get("CAPTURE_TIMEOUT", "30"))
OCR_TIMEOUT = float(os.environ.get("OCR_TIMEOUT", "20"))
WATCHDOG_MAX_FAILURES = int(os.environ.get("WATCHDOG_MAX_FAILURES", "5"))
WATCHDOG_MIN_VALID_FRAC = float(os.environ.get("WATCHDOG_MIN_VALID_FRAC", "0.6"))

if not URL:
    raise ValueError("URL environment variable required")

logger.info(f"🚀 Heizomat MQTT v4.0 - Dataclass Edition")
logger.info(f"📍 URL={URL}")
logger.info(f"📍 MQTT={MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")


# ----------------------------------------------------------------------
# SINGLE DATACLASS - ALL SENSOR INFO
# ----------------------------------------------------------------------
@dataclass
class SensorConfig:
    name: str
    rect: Tuple[int, int, int, int]  # (x, y, w, h)
    parser_type: str  # "float", "int", "text"
    page_segmentation_mode: int = 7
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str = "mdi:counter"
    min_value: float | int | None = None
    max_value: float | int | None = None


# MAIN SENSORS
main_sensors = [
    SensorConfig(
        name="Pause",
        rect=(173, 476, 68, 23),
        parser_type="float",
        unit="s",
        device_class="duration",
        state_class="measurement",
        icon="mdi:pause",
    ),
    SensorConfig(
        name="Takt",
        rect=(176, 451, 64, 20),
        parser_type="float",
        unit="s",
        device_class="duration",
        state_class="measurement",
        icon="mdi:timer",
        min_value=1,
        max_value=30,
    ),
    SensorConfig(
        name="Hackgut_P",
        rect=(208, 338, 41, 17),
        parser_type="int",
        unit="%",
        device_class=None,
        state_class="measurement",
        icon="mdi:molecule",
        min_value=0,
        max_value=100,
    ),
    SensorConfig(
        name="Hackgut_S",
        rect=(207, 309, 44, 17),
        parser_type="int",
        unit="%",
        device_class=None,
        state_class="measurement",
        icon="mdi:molecule",
        min_value=0,
        max_value=100,
    ),
    SensorConfig(
        name="Abgas_Temperatur",
        rect=(730, 223, 40, 19),
        parser_type="int",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer-lines",
        min_value=30,
        max_value=300,
    ),
    SensorConfig(
        name="Abgas_Restsauerstoff",
        rect=(726, 195, 48, 23),
        parser_type="float",
        unit="%",
        device_class=None,
        state_class="measurement",
        icon="mdi:molecule",
        min_value=2,
        max_value=21,
    ),
    SensorConfig(
        name="Geblaeseleistung",
        rect=(555, 195, 48, 23),
        parser_type="int",
        unit="%",
        device_class=None,
        state_class="measurement",
        icon="mdi:fan",
        min_value=0,
        max_value=100,
    ),
    SensorConfig(
        name="Partikelabscheider_Strom",
        rect=(734, 151, 39, 18),
        parser_type="float",
        unit="mA",
        device_class="current",
        state_class="measurement",
        icon="mdi:current-dc",
        min_value=0,
        max_value=0.2,
    ),
    SensorConfig(
        name="Partikelabscheider_Spannung",
        rect=(654, 151, 39, 18),
        parser_type="float",
        unit="kV",
        device_class="voltage",
        state_class="measurement",
        icon="mdi:current-dc",
        min_value=0,
        max_value=30,
    ),
    SensorConfig(
        name="Kessel_Solltemperatur",
        rect=(191, 151, 83, 28),
        parser_type="int",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer-chevron-up",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        name="Kessel_Solltemperatur",
        rect=(191, 151, 83, 28),
        parser_type="int",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer-chevron-up",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        name="Kessel_Temperatur",
        rect=(192, 114, 81, 31),
        parser_type="float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        name="RuecklaufMischer_Temperatur",
        rect=(719, 456, 54, 19),
        parser_type="float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:pipe-valve",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        name="Brennstoff",
        rect=(8, 217, 264, 21),
        parser_type="text",
        unit=None,
        device_class=None,
        state_class=None,
        icon="mdi:fuel",
    ),
    SensorConfig(
        name="Betriebszustand",
        rect=(403, 115, 291, 29),
        parser_type="text",
        unit=None,
        device_class=None,
        state_class=None,
        icon="mdi:power",
    ),
    SensorConfig(
        name="Uhrzeit",
        rect=(302, 74, 196, 31),
        parser_type="datetime",
        page_segmentation_mode=7,
        unit=None,
        device_class=None,
        state_class=None,
        icon="mdi:clock",
    ),
    SensorConfig(
        name="Betriebsart",
        rect=(600, 74, 200, 33),
        parser_type="text",
        unit=None,
        device_class=None,
        state_class=None,
        icon="mdi:cog",
    ),
]

# BOILER SENSORS
boiler_sensors = [
    SensorConfig(
        name="BoilerUnten_Temperatur",
        rect=(244, 432, 52, 19),
        parser_type="float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        name="BoilerMitte_Temperatur",
        rect=(244, 357, 52, 20),
        parser_type="float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        name="BoilerOben_Temperatur",
        rect=(244, 282, 52, 20),
        parser_type="float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        name="Sensor_Temperatur",
        rect=(37, 152, 41, 16),
        parser_type="float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer",
        min_value=-30,
        max_value=50,
    ),
    SensorConfig(
        name="Sensor_Durschnittstemperatur",
        rect=(37, 177, 41, 16),
        parser_type="float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer",
        min_value=-30,
        max_value=50,
    ),
    SensorConfig(
        name="Heizkreis_1",
        rect=(368, 251, 54, 19),
        parser_type="float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:radiator",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        name="Heizkreis_2",
        rect=(448, 251, 54, 19),
        parser_type="float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:radiator",
        min_value=10,
        max_value=99,
    ),
]


sollwerte = SensorConfig("sollwerte", (405, 509, 89, 39), "text")

last_values = {}

# compute expected sensor counts for watchdog quality checks
try:
    total_sensors = len(list(chain(main_sensors, boiler_sensors)))
except Exception:
    total_sensors = 0

WATCHDOG_MIN_VALID = max(1, int(total_sensors * WATCHDOG_MIN_VALID_FRAC))


# ----------------------------------------------------------------------
# PARSING FUNCTIONS
# ----------------------------------------------------------------------
def parse_text(value, name=""):
    return str(value).strip()


def parse_float(value, name=""):
    try:
        # cleaned = value.strip(" |°%mAkV")
        cleaned = value.replace(",", ".").strip()
        if cleaned.count(".") < 1:
            logger.warning(
                f"Float with no decimal point: '{cleaned}' for sensor '{name}'"
            )
            # cleaned = cleaned[:-1] + "." + cleaned[-1]
        return float(cleaned)
    except Exception as e:
        logger.warning(f"Float parse error: '{value}' -> {e} for sensor '{name}'")
        return None


def parse_int(value, name=""):
    try:
        cleaned = value.replace(",", ".").strip()
        return int(cleaned)
    except Exception as e:
        logger.warning(f"Int parse error: '{value}' -> {e} for sensor '{name}'")
        return None


def parse_datetime(value, name=""):
    try:
        cleaned = value.strip()
        dt = datetime.datetime.strptime(cleaned, "%d.%m.%Y %H:%M:%S")
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as e:
        logger.warning(f"Datetime parse error: '{value}' -> {e} for sensor '{name}'")
        return None


tessedit_char_whitelist = {
    "float": "0123456789,",
    "int": "0123456789",
    "str": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzÄäÖöÜüß0123456789 ,.-",
    # "datetime": "0123456789:. ",
}


def parse_value(raw_text, config):
    parser_type = config.parser_type
    parsers = {
        "float": parse_float,
        "int": parse_int,
        "text": parse_text,
        "datetime": parse_datetime,
    }
    parser = parsers.get(parser_type, parse_text)

    result = parser(raw_text, name=config.name)

    if result is None:
        logger.warning(
            f"Could not parse value for parser '{parser_type}': '{raw_text}'"
            f" for sensor '{config.name}'"
        )

    if result is not None and config.min_value is not None:
        if result < config.min_value:
            logger.warning(
                f"Value {result} for parser '{parser_type}' and raw text '{raw_text}'"
                f" below min {config.min_value} for sensor '{config.name}'"
            )
            if config.min_value < 0:
                result = None
            elif last_values.get(config.name) is not None:
                while result * 1.75 < last_values[config.name]:
                    result *= 10
                if not result * 0.75 < last_values[config.name]:
                    result = None
                logger.warning(f"Corrected value {result} for sensor '{config.name}'")
            else:
                result = None

    if result is not None and config.max_value is not None:
        if result > config.max_value:
            logger.warning(
                f"Value {result} for parser '{parser_type}' and raw text '{raw_text}'"
                f" above max {config.max_value} for sensor '{config.name}'"
            )
            if last_values.get(config.name) is not None:
                while result * 0.75 > last_values[config.name]:
                    result /= 10
                if not result * 1.25 > last_values[config.name]:
                    result = None
                logger.warning(f"Corrected value {result} for sensor '{config.name}'")
            else:
                result = None

    if result is not None:
        last_values[config.name] = result

    return result  # if result is not None else raw_text


# ----------------------------------------------------------------------
# OCR Functions
# ----------------------------------------------------------------------
def preprocess_image_for_ocr(pil_img, rect):
    x, y, w, h = rect
    cropped = pil_img.crop((x, y, x + w, y + h))
    img = np.array(cropped.convert("L"))
    _, img = cv2.threshold(img, 127, 255, cv2.THRESH_OTSU)
    if img.mean() < 127:
        img = cv2.bitwise_not(img)
    return Image.fromarray(img)


def crop_and_ocr(image, sensor_config: SensorConfig):
    preprocessed = preprocess_image_for_ocr(image, sensor_config.rect)

    whitelist = tessedit_char_whitelist.get(sensor_config.parser_type)
    config = f"--psm {sensor_config.page_segmentation_mode} --oem 3"
    if whitelist:
        config += f" -c tessedit_char_whitelist={whitelist}"

    raw_text = pytesseract.image_to_string(
        preprocessed, "deu", config=config  # Pass it here!
    ).strip()
    return parse_value(raw_text, sensor_config)


def get_associations(images):
    img1, img2 = images
    sollwerte_text_1 = crop_and_ocr(img1, sollwerte)
    sollwerte_text_2 = crop_and_ocr(img2, sollwerte)

    logger.debug(f"Sollwerte 1: '{sollwerte_text_1}' | 2: '{sollwerte_text_2}'")

    if isinstance(sollwerte_text_1, str) and "sollwerte" in sollwerte_text_1.lower():
        return [(boiler_sensors, ""), (main_sensors, "")]
    elif isinstance(sollwerte_text_2, str) and "sollwerte" in sollwerte_text_2.lower():
        return [(main_sensors, ""), (boiler_sensors, "")]
    return [(main_sensors, ""), ({}, "")]


def capture_heizomat_parallel(screenshot1_path, screenshot2_path):
    imgs = [Image.open(screenshot1_path), Image.open(screenshot2_path)]
    suffix_img_dict_list = get_associations(imgs)

    # Limit workers so we don't spawn too many OCR threads on the Pi
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
    try:
        futures = {
            f"{sensor_config.name}{suffix}": executor.submit(
                crop_and_ocr, img, sensor_config
            )
            for img, (sensor_list, suffix) in zip(imgs, suffix_img_dict_list)
            for sensor_config in sensor_list
        }

        results = {}
        for key, future in sorted(futures.items()):
            try:
                # Protect against OCR hangs on a single sensor blocking the whole loop
                results[key] = future.result(timeout=OCR_TIMEOUT)
            except concurrent.futures.TimeoutError:
                logger.error(
                    f"⏱️ OCR timeout after {OCR_TIMEOUT}s for sensor '{key}'"
                )
                results[key] = None
            except Exception as e:
                logger.error(f"❌ OCR error for sensor '{key}': {e}")
                results[key] = None

        # If everything timed out or failed, signal an overall failure
        if all(v is None for v in results.values()):
            logger.error(
                "🚨 All OCR tasks failed or timed out in this cycle — returning empty values"
            )
            return {}

        return results
    finally:
        # Do not block waiting for stuck OCR threads; let them die in the background
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=False)


# ----------------------------------------------------------------------
# MAIN FUNCTIONS
# ----------------------------------------------------------------------
def read_values():
    x, y = 649, 528

    logger.debug("📸 Capturing...")
    # ensure stale chromium children are not lingering
    try:
        subprocess.run(["pkill", "-f", "chromium"], check=False)
    except Exception:
        logger.debug("Could not pkill chromium (maybe not installed)")

    try:
        res = subprocess.run(
            ["python3", "capture_screenshot_script.py", "double", str(URL), str(x), str(y)],
            check=True,
            capture_output=True,
            text=True,
            timeout=CAPTURE_TIMEOUT,
        )
        if res.stdout:
            logger.debug(f"capture stdout: {res.stdout}")
        if res.stderr:
            logger.warning(f"capture stderr: {res.stderr}")
    except subprocess.TimeoutExpired as e:
        logger.error(f"❌ Capture timed out after {CAPTURE_TIMEOUT}s: {e}")
        try:
            subprocess.run(["pkill", "-f", "chromium"], check=False)
        except Exception:
            pass
        reap_zombies()
        return {}
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Capture subprocess failed: {e}; stdout={e.stdout}; stderr={e.stderr}")
        try:
            subprocess.run(["pkill", "-f", "chromium"], check=False)
        except Exception:
            pass
        reap_zombies()
        return {}
    except Exception as e:
        logger.exception(f"❌ Unexpected capture error: {e}")
        try:
            subprocess.run(["pkill", "-f", "chromium"], check=False)
        except Exception:
            pass
        reap_zombies()
        return {}

    try:
        values = capture_heizomat_parallel("screenshot1.png", "screenshot2.png")

        for path in ["screenshot1.png", "screenshot2.png"]:
            if os.path.exists(path):
                os.remove(path)
        # reap any finished child processes to avoid defunct chromium entries
        reap_zombies()

        logger.info(f"✅ OCR: {len(values)} values")
        return values
    except Exception as e:
        logger.error(f"❌ Capture failed: {e}")
        return {}


def reap_zombies():
    """Try to reap any zombie child processes."""
    try:
        while True:
            pid, status = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
            logger.info(f"♻️ Reaped child process {pid}")
    except ChildProcessError:
        # no child processes
        return
    except OSError as e:
        logger.debug(f"reap_zombies OSError: {e}")
        return


def state_topic(key: str) -> str:
    return f"{MQTT_TOPIC}/{key}"


# ----------------------------------------------------------------------
# HA Auto-Discovery
# ----------------------------------------------------------------------
def create_ha_discovery(key: str, sensor_config: SensorConfig):
    object_id = key.lower()
    discovery_topic = f"{HA_DISCOVERY_PREFIX}/sensor/heizomat/{object_id}/config"

    config = {
        "name": key,
        "default_entity_id": f"sensor.{SENSOR_BASENAME}_{object_id}",
        "unique_id": f"{SENSOR_BASENAME}_{object_id}",
        "state_topic": MQTT_TOPIC,
        "value_template": f"{{{{ value_json.get('{key}', '') }}}}",
        "payload_available": "ready",
        "payload_not_available": "lost",
        "device": {
            "identifiers": ["heizomat"],
            "name": "Heizomat",
            "manufacturer": "Heizomat",
            "model": "Biomass Boiler",
        },
    }

    if sensor_config.unit:
        config["unit_of_measurement"] = sensor_config.unit
    if sensor_config.device_class:
        config["device_class"] = sensor_config.device_class
    if sensor_config.state_class:
        config["state_class"] = sensor_config.state_class
    if sensor_config.icon:
        config["icon"] = sensor_config.icon

    return discovery_topic, config


def send_ha_discovery():
    logger.info("🚀 HA Auto-Discovery (25+ sensors)...")

    # mqtt_client.publish("homeassistant/sensor/heizomat_+/config", "", qos=0, retain=False)
    # Main sensors
    for sensor_config in chain(main_sensors, boiler_sensors):
        topic, config = create_ha_discovery(sensor_config.name, sensor_config)
        mqtt_client.publish(topic, json.dumps(config), qos=0, retain=True)
        logger.info(
            f"📡 {sensor_config.name}: {sensor_config.unit or 'text'} ({sensor_config.icon})"
        )

    logger.info("✅ HA Discovery COMPLETE!")


# ----------------------------------------------------------------------
# MQTT Setup
# ----------------------------------------------------------------------
mqtt_connected = False


def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        logger.info(f"✅ MQTT Connected {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")
        mqtt_connected = True
        send_ha_discovery()
    else:
        logger.error(f"❌ MQTT failed rc={rc}")


mqtt_client = mqtt.Client(client_id="heizomat-publisher")
mqtt_client.on_connect = on_connect

if MQTT_USERNAME:
    logger.info(f"🔐 MQTT auth: {MQTT_USERNAME}")
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

mqtt_client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
mqtt_client.loop_start()
logger.info("✅ MQTT ready")

# ----------------------------------------------------------------------
# MAIN LOOP
# ----------------------------------------------------------------------
if __name__ == "__main__":
    time.sleep(3)
    logger.info(f"⏰ Main loop ({PUBLISH_INTERVAL}s)")
    # Simple watchdog: exit process after N consecutive empty captures so Docker can restart it
    consecutive_failures = 0

    while True:
        try:
            # read OCR values
            values = read_values()
            values["timestamp"] = time.time()
            if mqtt_connected and mqtt_client and values:
                # publish each sensor individually
                payload = json.dumps(values)
                mqtt_client.publish(MQTT_TOPIC, payload, qos=1, retain=False)
                logger.info(
                    f"📤 Published {len(values)} individual sensors → {MQTT_TOPIC}/"
                )
                # reset watchdog on success
                consecutive_failures = 0

            else:
                logger.warning("⏳ No MQTT connection or no values to publish")
                # consider this a failure if no values were returned
                if not values:
                    consecutive_failures += 1
                    logger.warning(f"⚠️ Consecutive empty captures: {consecutive_failures}/{WATCHDOG_MAX_FAILURES}")
                else:
                    # if MQTT disconnected but we have values, don't increment watchdog
                    consecutive_failures = 0

            if consecutive_failures >= WATCHDOG_MAX_FAILURES:
                logger.error(
                    f"🚨 Watchdog triggered: {consecutive_failures} consecutive failures — exiting to allow container restart"
                )
                # ensure MQTT loop stops cleanly before exit
                try:
                    mqtt_client.loop_stop()
                    mqtt_client.disconnect()
                except Exception:
                    pass
                sys.exit(1)

        except KeyboardInterrupt:
            logger.info("🛑 Graceful shutdown")
            break
        except Exception as e:
            logger.error(f"❌ Loop error: {e}")

        time.sleep(PUBLISH_INTERVAL)

    mqtt_client.loop_stop()
    mqtt_client.disconnect()
