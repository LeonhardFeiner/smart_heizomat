#!/usr/bin/env python3
"""
Heizomat MQTT Monitor v5.0 - VNC DIRECT Edition
Direct coordinate mapping for raw VNC (800x480)
"""

from itertools import chain
import subprocess
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
import shutil

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
        "Primärluft",
        (207, 264, 44, 20),
        "int",
        unit="%",
        device_class=None,
        state_class="measurement",
        icon="mdi:molecule",
        min_value=0,
        max_value=100,
    ),
    SensorConfig(
        "Sekundärluft",
        (207, 234, 44, 20),
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

setpoint_sensors = [
    SensorConfig(
        "Soll_BoilerMitte_Temperatur",
        (244, 284, 52, 20),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer-chevron-up",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        "Soll_BoilerOben_Temperatur",
        (244, 209, 52, 20),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer-chevron-up",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        "Soll_Heizkreis_1",
        (368, 205, 54, 20),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:radiator",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        "Soll_Heizkreis_2",
        (448, 205, 54, 20),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:radiator",
        min_value=10,
        max_value=99,
    ),
    SensorConfig(
        "Soll_RuecklaufMischer_Temperatur",
        (12, 337, 54, 21),
        "float",
        unit="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:pipe-valve",
        min_value=10,
        max_value=99,
    ),
]


sensor_dict = {
    "main": main_sensors,
    "boiler": boiler_sensors,
    "setpoint": setpoint_sensors,
}

# Detection sensor: Check if "Sollwerte" text exists at this spot
sollwerte_indicator = SensorConfig("_sollwerte", (405, 436, 89, 39), "text")

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
        logger.warning(
            f"⚠️ Sensor '{config.name}': OCR returned empty text: '{raw_text}'"
        )
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
def preprocess_image_for_ocr(cv_img, rect, sensor_name="unknown"):
    x, y, w, h = rect

    # OpenCV Cropping: [y1:y2, x1:x2]
    cropped = cv_img[y : y + h, x : x + w]

    if DEBUG_OCR:
        cv2.imwrite(os.path.join(DEBUG_DIR, f"{sensor_name}.png"), cropped)

    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)

    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    if np.mean(thresh) < 127:
        thresh = cv2.bitwise_not(thresh)

    upscaled = cv2.resize(thresh, (w * 3, h * 3), interpolation=cv2.INTER_LINEAR)
    boardered = cv2.copyMakeBorder(upscaled, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=255)

    if DEBUG_OCR:
        cv2.imwrite(os.path.join(DEBUG_DIR, f"{sensor_name}_processed.png"), boardered)

    return boardered


def ocr(img, page_segmentation_mode, whitelist=None, *, oem=3, lang="deu"):
    tess_config = f"--psm {page_segmentation_mode} --oem {oem}"
    if whitelist:
        tess_config += f" -c tessedit_char_whitelist={whitelist}"

    return pytesseract.image_to_string(img, lang=lang, config=tess_config).strip()


def crop_and_ocr(cv_img, sensor_config: SensorConfig):
    processed_img = preprocess_image_for_ocr(
        cv_img, sensor_config.rect, sensor_config.name
    )

    raw_text = ocr(
        processed_img,
        sensor_config.page_segmentation_mode,
        whitelist=tessedit_char_whitelist.get(sensor_config.parser_type),
    )
    return parse_value(raw_text, sensor_config)


def is_area_grey(img, rect=(580, 0, 20, 35)):
    """Checks if the area (x, y, w, h) in the image is Grey."""
    x, y, w, h = rect

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
        cv2.imwrite(os.path.join(DEBUG_DIR, "_color_check.png"), crop)
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
        logger.error(f"VNC Error: {e}, Command: {' '.join(base + actions)}")
        return False


def capture(filename):
    """Performs a simple screen capture and returns the CV2 image object."""
    if not vnc_cmd(["capture", filename]):
        logger.error(f"❌ Failed to capture {filename}")
        return None

    img = cv2.imread(filename)
    if img is None:
        logger.error(f"❌ Failed to read {filename} from disk")
        return None

    if DEBUG_OCR:
        shutil.copy(filename, os.path.join(DEBUG_DIR, f"_{filename}"))

    return img


def capture_hold_sollwerte(filename="setpoint.png"):
    """Moves to the Sollwerte button, presses down, captures, and releases."""
    # Coordinates for the 'Sollwerte' / Page Flip button
    x, y = 450, 455

    # Sequence: Move -> Press -> Wait 100ms -> Screenshot -> Release
    action_sequence = [
        "mousemove",
        str(x),
        str(y),
        "mousedown",
        "1",
        "pause",
        "0.5",
        "capture",
        filename,
        "mouseup",
        "1",
    ]

    if not vnc_cmd(action_sequence):
        logger.error(f"❌ Failed to execute touch-capture for {filename}")
        return None

    img = cv2.imread(filename)
    if img is None:
        return None

    if DEBUG_OCR:
        shutil.copy(filename, os.path.join(DEBUG_DIR, f"_touch_{filename}"))

    # Give the HMI a moment to actually switch the page internally after mouseup
    time.sleep(0.5)

    return img


def check_sollwerte_page(img):
    # 3. Identify if img1 is Boiler or Main page
    check_val = crop_and_ocr(img, sollwerte_indicator)
    return check_val and "soll" in str(check_val).lower()


def toggle_page():
    """Toggles between the main and boiler pages by clicking the 'Sollwerte' button."""
    if not vnc_cmd(["mousemove", "649", "455", "click", "1"]):
        logger.error("❌ Failed to switch page via VNC")
        return False
    time.sleep(0.6)  # Wait for HMI UI transition
    return True


def capture_current_page(filename):
    img = capture(filename)
    result_dict = {}
    if img is None:
        return None

    if not is_area_grey(img):
        logger.info("⏸️ HMI State: Red/Green detected. Skipping cycle.")
        if DEBUG_OCR:
            shutil.copy(
                filename,
                os.path.join(DEBUG_DIR, "_non_grey.png"),
            )
        return {}

    if check_sollwerte_page(img):
        new_name = "boiler"
        result_dict["setpoint"] = capture_hold_sollwerte()
    else:
        new_name = "main"

    result_dict[new_name] = img

    if DEBUG_OCR:
        shutil.copy(
            filename,
            os.path.join(DEBUG_DIR, f"_{new_name}.png"),
        )

    return result_dict


def capture_hmi():
    result_dict = {}

    result_dict = capture_current_page("screenshot1.png")
    if result_dict is None:
        return None
    toggle_page()
    result = capture_current_page("screenshot2.png")
    if result is None:
        return None
    result_dict.update(result)
    toggle_page()

    return result_dict


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
    prefix = SENSOR_BASENAME

    logger.info(f"📡 Sending HA Discovery using prefix: {prefix}...")

    for sensor in chain.from_iterable(sensor_dict.values()):
        obj_id = sensor.name.lower()

        topic = f"{HA_DISCOVERY_PREFIX}/sensor/{prefix}/{obj_id}/config"

        config = {
            "name": f"{sensor.name}",
            "default_entity_id": f"sensor.{prefix}_{obj_id}",
            "unique_id": f"{prefix}_{obj_id}",
            "state_topic": MQTT_TOPIC,
            "value_template": f"{{{{ value_json.{sensor.name} }}}}",
            "payload_available": "ready",
            "payload_not_available": "lost",
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
        if sensor.icon:
            config["icon"] = sensor.icon

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
        cycle_start = time.time()

        screens = capture_hmi()  # Returns dict or None

        if screens:
            try:
                final_data = {}

                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                    future_to_sensor = {}
                    for name, img in screens.items():
                        sensors = sensor_dict[name]
                        for s in sensors:
                            # img is now the numpy array from our dict
                            future = executor.submit(crop_and_ocr, img, s)
                            future_to_sensor[future] = s.name

                    for future in concurrent.futures.as_completed(future_to_sensor):
                        sensor_name = future_to_sensor[future]
                        try:
                            val = future.result()
                            if val is not None:
                                final_data[sensor_name] = val
                        except Exception as exc:
                            logger.error(f"❌ Sensor '{sensor_name}' exception: {exc}")

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
        elif screens is None:  # Explicit failure, not a skip
            consecutive_failures += 1

        if consecutive_failures >= WATCHDOG_MAX_FAILURES:
            logger.error("🚨 Watchdog failure limit reached. Restarting...")
            sys.exit(1)

        # --- SYNC TIMING LOGIC ---
        elapsed = time.time() - cycle_start
        sleep_time = max(0, PUBLISH_INTERVAL - elapsed)

        if sleep_time == 0:
            logger.warning(
                f"⏰ Cycle took longer ({elapsed:.1f}s) than interval ({PUBLISH_INTERVAL}s)!"
            )

        time.sleep(sleep_time)
