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

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

URL = os.environ.get("URL")
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "heizomat/values")
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
PUBLISH_INTERVAL = float(os.environ.get("PUBLISH_INTERVAL", "10"))
HA_DISCOVERY_PREFIX = "homeassistant"

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
    rect: Tuple[int, int, int, int]      # (x, y, w, h)
    parser_type: str                     # "float", "int", "text"
    unit: Optional[str] = None
    device_class: Optional[str] = None
    icon: str = "mdi:counter"

# MAIN SENSORS
main_sensors = {
    "Pause": SensorConfig((173, 476, 68, 23), "float", icon="mdi:pause"),
    "Takt": SensorConfig((176, 451, 64, 18), "float", icon="mdi:timer"),
    "Hackgut_P": SensorConfig((208, 338, 41, 16), "int", "%", icon="mdi:molecule"),
    "Hackgut_S": SensorConfig((207, 309, 44, 16), "int", "%", icon="mdi:molecule"),
    "Abgas_Temperatur": SensorConfig((730, 223, 40, 19), "int", "°C", "temperature", "mdi:thermometer-lines"),
    "Abgas_Restsauerstoff": SensorConfig((726, 195, 48, 23), "float", "%", icon="mdi:molecule"),
    "Geblaeseleistung": SensorConfig((555, 195, 48, 23), "int", "%", icon="mdi:fan"),
    "Partikelabscheider_Strom": SensorConfig((734, 151, 39, 18), "float", "mA", "current", "mdi:current-dc"),
    "Partikelabscheider_Spannung": SensorConfig((654, 151, 39, 18), "float", "kV", "voltage", "mdi:current-dc"),
    "Kessel_Solltemperatur": SensorConfig((191, 151, 83, 28), "int", "°C", "temperature", "mdi:thermometer-chevron-up"),
    "Kessel_Temperatur": SensorConfig((192, 114, 81, 31), "float", "°C", "temperature", "mdi:thermometer"),
    "RuecklaufMischer_Temperatur": SensorConfig((719, 456, 54, 18), "float", "°C", "temperature", "mdi:pipe-valve"),
    "Zustandrestzeit": SensorConfig((706, 116, 76, 28), "int", icon="mdi:clock-alert"),
    "Brennstoff": SensorConfig((8, 217, 264, 21), "text", icon="mdi:fuel"),
    "Betriebszustand": SensorConfig((403, 115, 291, 29), "text", icon="mdi:power"),
    "Uhrzeit": SensorConfig((302, 74, 196, 31), "text", icon="mdi:clock"),
    "Betriebsart": SensorConfig((600, 74, 200, 33), "text", icon="mdi:cog"),
}

# BOILER SENSORS
boiler_sensors = {
    "BoilerUnten_Temperatur": SensorConfig((244, 432, 52, 19), "float", "°C", "temperature", "mdi:thermometer"),
    "BoilerMitte_Temperatur": SensorConfig((244, 357, 52, 19), "float", "°C", "temperature", "mdi:thermometer"),
    "BoilerOben_Temperatur": SensorConfig((244, 282, 52, 19), "float", "°C", "temperature", "mdi:thermometer"),
    "Sensor_Temperatur": SensorConfig((37, 152, 41, 16), "float", "°C", "temperature", "mdi:thermometer"),
    "Sensor_Durschnittstemperatur": SensorConfig((37, 177, 41, 16), "float", "°C", "temperature", "mdi:thermometer"),
    "Heizkreis_1": SensorConfig((368, 251, 54, 19), "float", "°C", "temperature", "mdi:radiator"),
    "Heizkreis_2": SensorConfig((448, 251, 54, 19), "float", "°C", "temperature", "mdi:radiator"),
}



sollwerte_rect = (405, 509, 89, 39)

# ----------------------------------------------------------------------
# PARSING FUNCTIONS
# ----------------------------------------------------------------------
def parse_text(value):
    return str(value).strip()

def parse_float(value):
    try:
        # cleaned = value.strip(" |°%mAkV")
        cleaned = (
            value.replace(",", ".")
                 .replace("O", "0")
                 .replace("I", "1")
                 .replace("İ", "1")
                 .replace("|", "")
                 .strip()
        )
        cleaned = cleaned.replace(',', '.')
        if cleaned.count('.') < 1:
            cleaned = cleaned[:-1] + '.' + cleaned[-1]
        return float(cleaned)
    except:
        return None

def parse_int(value):
    try:
        cleaned = (
            value.replace(",", ".")
                 .replace("O", "0")
                 .replace("I", "1")
                 .replace("İ", "1")
                 .replace("|", "")
                 .strip()
        )
        return float(cleaned)
    except:
        return None

def parse_value(raw_text, parser_type):
    parsers = {"float": parse_float, "int": parse_int, "text": parse_text}
    parser = parsers.get(parser_type, parse_text)
    result = parser(raw_text)
    return result #if result is not None else raw_text

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
    raw_text = pytesseract.image_to_string(preprocessed, "deu", "--psm 6").strip()
    return parse_value(raw_text, sensor_config.parser_type)

def get_associations(images):
    img1, img2 = images
    sollwerte_text_1 = crop_and_ocr(img1, SensorConfig(sollwerte_rect, "text"))
    sollwerte_text_2 = crop_and_ocr(img2, SensorConfig(sollwerte_rect, "text"))
    
    logger.debug(f"Sollwerte 1: '{sollwerte_text_1}' | 2: '{sollwerte_text_2}'")

    if isinstance(sollwerte_text_1, str) and "sollwerte" in sollwerte_text_1.lower():
        return [(boiler_sensors, ""), (main_sensors, "")]
    elif isinstance(sollwerte_text_2, str) and "sollwerte" in sollwerte_text_2.lower():
        return [(main_sensors, ""), (boiler_sensors, "")]
    return [(main_sensors, ""), ({}, "")]

def capture_heizomat_parallel(screenshot1_path, screenshot2_path):
    imgs = [Image.open(screenshot1_path), Image.open(screenshot2_path)]
    suffix_img_dict_list = get_associations(imgs)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            f"{key}{suffix}": executor.submit(crop_and_ocr, img, sensor_config)
            for img, (sensor_dict, suffix) in zip(imgs, suffix_img_dict_list)
            for key, sensor_config in sensor_dict.items()
        }
        return {key: future.result() for key, future in sorted(futures.items())}

# ----------------------------------------------------------------------
# MAIN FUNCTIONS
# ----------------------------------------------------------------------
def read_values():
    x, y = 649, 528
    
    logger.debug("📸 Capturing...")
    subprocess.run([
        'python3', 'capture_screenshot_script.py', 'double', 
        URL, str(x), str(y)
    ], check=True, capture_output=True)
    
    try:
        values = capture_heizomat_parallel('screenshot1.png', 'screenshot2.png')
        
        for path in ['screenshot1.png', 'screenshot2.png']:
            if os.path.exists(path):
                os.remove(path)
                
        logger.info(f"✅ OCR: {len(values)} values")
        return values
    except Exception as e:
        logger.error(f"❌ Capture failed: {e}")
        return {}


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
        "default_entity_id": f"sensor.heizomat_{object_id}",
        "unique_id": f"heizomat_{object_id}",
        "state_topic": state_topic(key),
        # "value_template": f"{{{{ value_json.values.{key} }}}}",
        # "availability_topic": "heizomat/values/$state",
        "payload_available": "ready",
        "payload_not_available": "lost",
        "device": {
            "identifiers": ["heizomat"],
            "name": "Heizomat",
            "manufacturer": "Heizomat",
            "model": "Biomass Boiler"
        },
        "icon": sensor_config.icon
    }

    if sensor_config.unit:
        config["unit_of_measurement"] = sensor_config.unit
    if sensor_config.device_class:
        config["device_class"] = sensor_config.device_class

    return discovery_topic, config


def send_ha_discovery():
    logger.info("🚀 HA Auto-Discovery (25+ sensors)...")
    
    # mqtt_client.publish("homeassistant/sensor/heizomat_+/config", "", qos=0, retain=False)
    # Main sensors
    for key, sensor_config in chain(main_sensors.items(), boiler_sensors.items()):
        topic, config = create_ha_discovery(key, sensor_config)
        mqtt_client.publish(topic, json.dumps(config), qos=0, retain=True)
        logger.info(f"📡 {key}: {sensor_config.unit or 'text'} ({sensor_config.icon})")
    
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

    while True:
        try:
            # read OCR values
            values = read_values()
            values["timestamp"] = time.time()

            if mqtt_connected and mqtt_client and values:
                # publish each sensor individually
                for key, val in values.items():
                    topic = f"{MQTT_TOPIC}/{key}"
                    # handle None values gracefully
                    payload = val if val is not None else ""
                    mqtt_client.publish(topic, payload, qos=1, retain=True)
                logger.info(f"📤 Published {len(values)} individual sensors → {MQTT_TOPIC}/")

            else:
                logger.warning("⏳ No MQTT connection or no values to publish")

        except KeyboardInterrupt:
            logger.info("🛑 Graceful shutdown")
            break
        except Exception as e:
            logger.error(f"❌ Loop error: {e}")

        time.sleep(PUBLISH_INTERVAL)

    mqtt_client.loop_stop()
    mqtt_client.disconnect()