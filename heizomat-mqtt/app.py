#!/usr/bin/env python3
"""
Heizomat MQTT Monitor v5.0 - VNC DIRECT Edition
Direct coordinate mapping for raw VNC (800x480)
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
from dataclasses import dataclass
from typing import Tuple
import datetime
import sys

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

VNC_ADDRESS = os.environ.get("VNC_ADDRESS")
VNC_PW = os.environ.get("VNC_PW", "")
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "heizomat/values")
SENSOR_BASENAME = os.environ.get("SENSOR_BASENAME", "heizomat")
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
PUBLISH_INTERVAL = float(os.environ.get("PUBLISH_INTERVAL", "10"))

HA_DISCOVERY_PREFIX = "homeassistant"
OCR_TIMEOUT = float(os.environ.get("OCR_TIMEOUT", "20"))
WATCHDOG_MAX_FAILURES = int(os.environ.get("WATCHDOG_MAX_FAILURES", "5"))
DEBUG_OCR = os.environ.get("DEBUG_OCR", "false").lower() == "true"
DEBUG_DIR = "/app/debug_crops"


if not VNC_ADDRESS:
    raise ValueError("VNC_ADDRESS environment variable required")

logger.info(f"🚀 Heizomat MQTT v5.0 - VNC DIRECT Edition")
logger.info(f"📍 MQTT={MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")
logger.info(f"📍 VNC={VNC_ADDRESS}")


@dataclass
class SensorConfig:
    name: str
    rect: Tuple[int, int, int, int]  # (x, y, w, h)
    parser_type: str  # "float", "int", "text", "datetime"
    page_segmentation_mode: int = 7
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str = "mdi:counter"
    min_value: float | int | None = None
    max_value: float | int | None = None


# ----------------------------------------------------------------------
# SENSOR DEFINITIONS (Y-Coordinates reduced by 73)
# ----------------------------------------------------------------------
main_sensors = [
    SensorConfig(
        "Pause",
        (173, 403, 68, 23),
        "float",
        unit="s",
        device_class="duration",
        state_class="measurement",
        icon="mdi:pause",
    ),
    SensorConfig(
        "Takt",
        (176, 378, 64, 21),
        "float",
        unit="s",
        device_class="duration",
        state_class="measurement",
        icon="mdi:timer",
        min_value=1,
        max_value=30,
    ),
    SensorConfig(
        "Hackgut_P",
        (208, 265, 41, 19),
        "int",
        unit="%",
        device_class=None,
        state_class="measurement",
        icon="mdi:molecule",
        min_value=0,
        max_value=100,
    ),
    SensorConfig(
        "Hackgut_S",
        (207, 235, 44, 19),
        "int",
        unit="%",
        device_class=None,
        state_class="measurement",
        icon="mdi:molecule",
        min_value=0,
        max_value=100,
    ),
    SensorConfig(
        "Abgas_Temperatur",
        (730, 150, 40, 19),
        "int",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer-lines",
        min_value=30,
        max_value=300,
    ),
    SensorConfig(
        "Abgas_Restsauerstoff",
        (726, 122, 48, 23),
        "float",
        unit="%",
        device_class=None,
        state_class="measurement",
        icon="mdi:molecule",
        min_value=2,
        max_value=21,
    ),
    SensorConfig(
        "Geblaeseleistung",
        (555, 122, 48, 23),
        "int",
        unit="%",
        device_class=None,
        state_class="measurement",
        icon="mdi:fan",
        min_value=0,
        max_value=100,
    ),
    SensorConfig(
        "Partikelabscheider_Strom",
        (734, 78, 39, 18),
        "float",
        unit="mA",
        device_class="current",
        state_class="measurement",
        icon="mdi:current-dc",
        min_value=0,
        max_value=0.2,
    ),
    SensorConfig(
        "Partikelabscheider_Spannung",
        (654, 78, 39, 18),
        "float",
        unit="kV",
        device_class="voltage",
        state_class="measurement",
        icon="mdi:current-dc",
        min_value=0,
        max_value=30,
    ),
    SensorConfig(
        "Kessel_Solltemperatur",
        (191, 78, 83, 28),
        "int",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer-chevron-up",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        "Kessel_Temperatur",
        (192, 41, 81, 31),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        "RuecklaufMischer_Temperatur",
        (719, 383, 54, 21),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:pipe-valve",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        "Brennstoff",
        (8, 144, 264, 21),
        "text",
        unit=None,
        device_class=None,
        state_class=None,
        icon="mdi:fuel",
    ),
    SensorConfig(
        "Betriebszustand",
        (403, 42, 291, 31),
        "text",
        unit=None,
        device_class=None,
        state_class=None,
        icon="mdi:power",
    ),
    SensorConfig(
        "Uhrzeit",
        (302, 1, 196, 31),
        "datetime",
        unit=None,
        device_class=None,
        state_class=None,
        icon="mdi:clock",
    ),
    SensorConfig(
        "Betriebsart",
        (600, 1, 200, 33),
        "text",
        unit=None,
        device_class=None,
        state_class=None,
        icon="mdi:cog",
    ),
]

boiler_sensors = [
    SensorConfig(
        "BoilerUnten_Temperatur",
        (244, 359, 52, 20),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        "BoilerMitte_Temperatur",
        (244, 284, 52, 20),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        "BoilerOben_Temperatur",
        (244, 209, 52, 20),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        "Sensor_Temperatur",
        (37, 79, 41, 17),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer",
        min_value=-30,
        max_value=50,
    ),
    SensorConfig(
        "Sensor_Durschnittstemperatur",
        (37, 104, 41, 17),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer",
        min_value=-30,
        max_value=50,
    ),
    SensorConfig(
        "Heizkreis_1",
        (368, 178, 54, 20),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:radiator",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        "Heizkreis_2",
        (448, 178, 54, 20),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:radiator",
        min_value=10,
        max_value=99,
    ),
]

# Detection sensor: Check if "Sollwerte" text exists at this spot
sollwerte_indicator = SensorConfig("sollwerte", (405, 436, 89, 39), "text")

# Global state
last_values = {}
mqtt_connected = False
tessedit_char_whitelist = {
    "float": "0123456789,",
    "int": "0123456789",
    "str": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzÄäÖöÜüß0123456789 ,.-",
    "datetime": "0123456789.: ",
}


# ----------------------------------------------------------------------
# PARSING FUNCTIONS
# ----------------------------------------------------------------------
def parse_text(value, name=""):
    return str(value).strip()


def parse_float(value, name=""):
    try:
        cleaned = value.replace(",", ".").strip()
        return float(cleaned)
    except Exception as e:
        logger.warning(f"Float parse error: '{value}' for sensor '{name}'")
        return None


def parse_int(value, name=""):
    try:
        cleaned = value.replace(",", ".").strip()
        return int(float(cleaned))  # handle case where HMI might show .0
    except Exception as e:
        logger.warning(f"Int parse error: '{value}' for sensor '{name}'")
        return None


def parse_datetime(value, name=""):
    try:
        cleaned = value.strip().replace(" ", "")  # Remove all spaces first
        # Expected format now: DD.MM.YYYYHH:MM:SS (18 chars)
        if len(cleaned) == 18:
            # Re-insert the space where it belongs
            cleaned = cleaned[:10] + " " + cleaned[10:]

        dt = datetime.datetime.strptime(cleaned, "%d.%m.%Y %H:%M:%S")
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        logger.warning(f"⏰ Uhrzeit parse failed for: '{value}'")
        return None


def parse_value(raw_text, config):
    parsers = {
        "float": parse_float,
        "int": parse_int,
        "text": parse_text,
        "datetime": parse_datetime,
    }

    if not raw_text or raw_text.strip() == "":
        logger.warning(f"⚠️ Sensor '{config.name}': OCR returned empty text")
        return None

    parser = parsers.get(config.parser_type, parse_text)
    result = parser(raw_text, name=config.name)

    if result is None:
        logger.warning(
            f"⚠️ Sensor '{config.name}': Parser failed to convert '{raw_text}'"
        )
        return None

    # Bounds checking
    if config.min_value is not None and result < config.min_value:
        logger.warning(
            f"📉 Sensor '{config.name}': Value {result} below min {config.min_value} (Raw: '{raw_text}')"
        )
        return None

    if config.max_value is not None and result > config.max_value:
        logger.warning(
            f"📈 Sensor '{config.name}': Value {result} above max {config.max_value} (Raw: '{raw_text}')"
        )
        return None

    last_values[config.name] = result
    return result


# ----------------------------------------------------------------------
# OCR ENGINE
# ----------------------------------------------------------------------
def preprocess_image_for_ocr(pil_img, rect, sensor_name="unknown"):
    x, y, w, h = rect
    cropped = pil_img.crop((x, y, x + w, y + h))

    # Save the raw crop if debug is on
    if DEBUG_OCR:
        debug_path = os.path.join(DEBUG_DIR, f"{sensor_name}.png")
        cropped.save(debug_path)

    # Process for OCR
    img = np.array(cropped.convert("L"))
    _, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # If debug is on, save the "processed" (black/white) version too
    if DEBUG_OCR:
        processed_path = os.path.join(DEBUG_DIR, f"{sensor_name}_processed.png")
        cv2.imwrite(processed_path, img)

    if img.mean() < 127:
        img = cv2.bitwise_not(img)
    return Image.fromarray(img)


def crop_and_ocr(image, sensor_config: SensorConfig):
    preprocessed = preprocess_image_for_ocr(
        image, sensor_config.rect, sensor_config.name
    )
    whitelist = tessedit_char_whitelist.get(sensor_config.parser_type)
    tess_config = f"--psm {sensor_config.page_segmentation_mode} --oem 3"
    if whitelist:
        tess_config += f" -c tessedit_char_whitelist={whitelist}"

    raw_text = pytesseract.image_to_string(
        preprocessed, "deu", config=tess_config
    ).strip()
    return parse_value(raw_text, sensor_config)


def is_area_grey(img_path, rect):
    """Checks if the area (x, y, w, h) in the image is Grey."""
    x, y, w, h = rect

    # Load image and crop
    img = cv2.imread(img_path)
    if img is None:
        return False

    crop = img[y : y + h, x : x + w]

    # Convert to HSV (Hue, Saturation, Value)
    hsv_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    # Calculate average Saturation and Value
    avg_saturation = np.mean(hsv_crop[:, :, 1])
    avg_value = np.mean(hsv_crop[:, :, 2])

    if DEBUG_OCR:
        # Save the color-check crop so you can see what it's looking at
        cv2.imwrite(os.path.join(DEBUG_DIR, "COLOR_CHECK_AREA.png"), crop)
        logger.info(
            f"🎨 Color Check: Avg Saturation={avg_saturation:.2f}, Avg Value={avg_value:.2f}"
        )

    # GREY logic: In HSV, grey has very low saturation.
    # Usually, saturation < 50 (out of 255) is grey/white/black.
    if avg_saturation < 50:
        return True
    return False


# ----------------------------------------------------------------------
# VNC CAPTURE
# ----------------------------------------------------------------------
def vnc_cmd(actions: list):
    # Ensure display :0 is there
    addr = VNC_ADDRESS if ":" in VNC_ADDRESS else f"{VNC_ADDRESS}:0"
    base = ["vncdotool", "-s", addr]
    if VNC_PW:
        base.extend(["-p", VNC_PW])

    # Final command sent to OS: vncdotool -s IP:0 -p PW mousemove 649 455 click 1
    try:
        subprocess.run(base + actions, check=True, capture_output=True, timeout=15)
        return True
    except Exception as e:
        logger.error(f"VNC Error: {e}")
        return False


def capture_hmi():
    # 1. Capture first screen
    if not vnc_cmd(["capture", "screenshot1.png"]):
        return False

    # 2. PERFORM THE COLOR CHECK
    # Area: x=580, y=0, w=20, h=35
    if not is_area_grey("screenshot1.png", (580, 0, 20, 35)):
        logger.info("⏸️ HMI State: Red/Green detected. Skipping this cycle (No error).")
        return None  # Soft "failure" - do not increment watchdog

    # 3. Move to coordinates and THEN click button 1
    # Format: mousemove X Y click 1
    if not vnc_cmd(["mousemove", "649", "455", "click", "1"]):
        return False

    # time.sleep(1.5)  # Wait for page flip

    # 4. Capture second screen
    if not vnc_cmd(["capture", "screenshot2.png"]):
        return False

    if DEBUG_OCR:
        import shutil

        # Save them with fixed names so they are easy to find in the volume
        shutil.copy("screenshot1.png", os.path.join(DEBUG_DIR, "_screenshot1.png"))
        shutil.copy("screenshot2.png", os.path.join(DEBUG_DIR, "_screenshot2.png"))

    vnc_cmd(["mousemove", "649", "455", "click", "1"])
    return True


# ----------------------------------------------------------------------
# MQTT & DISCOVERY
# ----------------------------------------------------------------------
def on_connect(client, userdata, flags, reason_code, properties=None):
    global mqtt_connected
    # 'rc' is now called 'reason_code' in the new API
    if reason_code == 0:
        logger.info("✅ MQTT Connected")
        mqtt_connected = True
        send_ha_discovery(client)
    else:
        logger.error(f"❌ MQTT Connection failed: {reason_code}")


def send_ha_discovery(client):
    logger.info("📡 Sending HA Discovery...")
    for sensor in chain(main_sensors, boiler_sensors):
        obj_id = sensor.name.lower()
        topic = f"{HA_DISCOVERY_PREFIX}/sensor/heizomat/{obj_id}/config"
        config = {
            "name": f"Heizomat {sensor.name}",
            "unique_id": f"heizomat_{obj_id}",
            "state_topic": MQTT_TOPIC,
            "value_template": f"{{{{ value_json.{sensor.name} }}}}",
            "device": {
                "identifiers": ["heizomat"],
                "name": "Heizomat Boiler",
                "manufacturer": "Heizomat",
            },
            "icon": sensor.icon,
        }
        if sensor.unit:
            config["unit_of_measurement"] = sensor.unit
        if sensor.device_class:
            config["device_class"] = sensor.device_class
        if sensor.state_class:
            config["state_class"] = sensor.state_class

        client.publish(topic, json.dumps(config), retain=True)


# ----------------------------------------------------------------------
# MAIN LOOP
# ----------------------------------------------------------------------
if __name__ == "__main__":
    mqtt_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id="heizomat_vnc_monitor"
    )
    mqtt_client.on_connect = on_connect
    if MQTT_USERNAME:
        mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    try:
        mqtt_client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        logger.error(f"Could not connect to MQTT: {e}")

    consecutive_failures = 0

    while True:
        status = capture_hmi()
        if status is None:
            logger.info(
                "⏸️ Skipping data extraction due to HMI state (Red/Green detected)."
            )
            # Soft failure (color check failed) - do not increment watchdog
            continue
        elif status:
            try:
                img1 = Image.open("screenshot1.png")
                img2 = Image.open("screenshot2.png")

                # Detect which image is which
                check_text = crop_and_ocr(img1, sollwerte_indicator)
                if check_text and "soll" in str(check_text).lower():
                    mapping = [(boiler_sensors, img1), (main_sensors, img2)]
                else:
                    mapping = [(main_sensors, img1), (boiler_sensors, img2)]

                final_data = {}

                # Use a dictionary to track which sensor goes with which future
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                    future_to_sensor = {}
                    for sensors, img in mapping:
                        for s in sensors:
                            # Submit the OCR task
                            future = executor.submit(crop_and_ocr, img, s)
                            future_to_sensor[future] = s.name

                    for future in concurrent.futures.as_completed(future_to_sensor):
                        sensor_name = future_to_sensor[future]
                        try:
                            val = future.result()
                            if val is not None:
                                final_data[sensor_name] = val
                        except Exception as exc:
                            logger.error(
                                f"❌ Sensor '{sensor_name}' generated an exception: {exc}"
                            )

                # Summary Logging
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
                    mqtt_client.publish(MQTT_TOPIC, json.dumps(final_data), qos=1)
                    logger.info(f"📤 Published {len(final_data)} sensors")
                    consecutive_failures = 0
                else:
                    logger.warning("Empty data set after OCR")
                    consecutive_failures += 1

            except Exception as e:
                logger.error(f"Processing error: {e}")
                consecutive_failures += 1
            finally:
                for p in ["screenshot1.png", "screenshot2.png"]:
                    if os.path.exists(p):
                        os.remove(p)
        else:
            consecutive_failures += 1

        if consecutive_failures >= WATCHDOG_MAX_FAILURES:
            logger.error("🚨 Watchdog failure limit reached. Restarting...")
            sys.exit(1)

        time.sleep(PUBLISH_INTERVAL)
