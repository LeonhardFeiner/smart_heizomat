import datetime
import difflib
import logging
import os
from dataclasses import dataclass
from typing import Tuple

logger = logging.getLogger(__name__)


@dataclass
class SensorConfig:
    name: str
    rect: Tuple[int, int, int, int]  # (x, y, w, h)
    parser_type: str  # "float", "int", "text", "datetime", "enum"
    page_segmentation_mode: int = 7
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str = "mdi:counter"
    min_value: float | int | None = None
    max_value: float | int | None = None
    enum_options: Tuple[str, ...] | None = None  # parser_type == "enum" only


tessedit_char_whitelist = {
    "float": "0123456789,",
    "int": "0123456789",
    "str": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzÄäÖöÜüß0123456789 ,.-",
    "datetime": "0123456789.: ",
}

last_values: dict = {}

# ----------------------------------------------------------------------
# ENUM MATCHING
# ----------------------------------------------------------------------
# Betriebsart/Betriebszustand states are fixed by the boiler's firmware
# (confirmed via ~12 days of OCR history + the Heizomat TouchControl dealer
# page), so they're hardcoded here. Brennstoff (fuel type) is an
# installation setting instead — configurable via env var, defaulting to
# what this deployment actually burns.
ENUM_MATCH_THRESHOLD = 0.6
ENUM_FALLBACK = "Unbekannt"

BETRIEBSART_OPTIONS = (
    "Wartung",
    "Wartung mit RGG",
    "Dauerbetrieb",
    "Zündbetrieb",
    "Boilerbetrieb",
    "Gebläsenachlauf",
)
BETRIEBSZUSTAND_OPTIONS = (
    "Wartung",
    "Wartung mit RGG",
    "Vorglühen",
    "Zündvorgang",
    "Glutbettbildung",
    "Lastbetrieb",
    "Dauerbetrieb",
    "Zündbetrieb",
    "Boilerbetrieb",
    "Gebläsenachlauf",
)
BRENNSTOFF_OPTIONS = tuple(
    v.strip()
    for v in os.environ.get("BRENNSTOFF_OPTIONS", "Hackschnitzel").split(",")
    if v.strip()
)


def match_enum(raw_text, options, threshold=ENUM_MATCH_THRESHOLD, fallback=ENUM_FALLBACK):
    """Fuzzy-matches raw OCR text against known enum options (edit-distance
    ratio, tolerant of OCR noise). Returns (value, is_exact) — is_exact is
    False whenever the raw text wasn't a clean 1:1 match, whether or not a
    fuzzy match was accepted, so the caller can flag it for review."""
    text = (raw_text or "").strip().lower()
    if not text or not options:
        return fallback, False

    best_option, best_score = None, 0.0
    for option in options:
        score = difflib.SequenceMatcher(None, text, option.lower()).ratio()
        if score > best_score:
            best_option, best_score = option, score

    if best_score >= threshold:
        return best_option, best_score >= 1.0
    return fallback, False


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
        min_value=0,
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
        min_value=0,
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
        "enum",
        unit=None,
        device_class="enum",
        state_class=None,
        icon="mdi:fuel",
        enum_options=BRENNSTOFF_OPTIONS,
    ),
    SensorConfig(
        "Betriebszustand",
        (403, 42, 291, 31),
        "enum",
        unit=None,
        device_class="enum",
        state_class=None,
        icon="mdi:power",
        enum_options=BETRIEBSZUSTAND_OPTIONS,
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
        "enum",
        unit=None,
        device_class="enum",
        state_class=None,
        icon="mdi:cog",
        enum_options=BETRIEBSART_OPTIONS,
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

# Settle-check sensor: the clock is the most sensitive field to a mid-redraw
# capture, so it's used to detect and retry a capture taken while the HMI's
# top info bar was still repainting.
uhrzeit_sensor = next(s for s in main_sensors if s.name == "Uhrzeit")


# ----------------------------------------------------------------------
# PARSING FUNCTIONS
# ----------------------------------------------------------------------
def parse_text(value, name=""):
    return str(value).strip()


def parse_float(value, name=""):
    try:
        cleaned = value.replace(",", ".").strip()
        return float(cleaned)
    except Exception:
        logger.warning(f"Float parse error: '{value}' for sensor '{name}'")
        return None


def parse_int(value, name=""):
    try:
        cleaned = value.replace(",", ".").strip()
        return int(float(cleaned))  # handle case where HMI might show .0
    except Exception:
        logger.warning(f"Int parse error: '{value}' for sensor '{name}'")
        return None


def parse_datetime(value, name=""):
    try:
        cleaned = value.strip().replace(" ", "")
        if len(cleaned) == 18:
            cleaned = cleaned[:10] + " " + cleaned[10:]
        dt = datetime.datetime.strptime(cleaned, "%d.%m.%Y %H:%M:%S")
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        logger.warning(f"Uhrzeit parse failed for: '{value}'")
        return None


def parse_value(raw_text, config):
    parsers = {
        "float": parse_float,
        "int": parse_int,
        "text": parse_text,
        "datetime": parse_datetime,
    }

    if not raw_text or raw_text.strip() == "":
        logger.warning(f"Sensor '{config.name}': OCR returned empty text: '{raw_text}'")
        return None

    parser = parsers.get(config.parser_type, parse_text)
    result = parser(raw_text, name=config.name)

    if result is None:
        logger.warning(f"Sensor '{config.name}': Parser failed to convert '{raw_text}'")
        return None

    if config.min_value is not None and result < config.min_value:
        logger.warning(
            f"Sensor '{config.name}': Value {result} below min {config.min_value} (Raw: '{raw_text}')"
        )
        return None

    if config.max_value is not None and result > config.max_value:
        logger.warning(
            f"Sensor '{config.name}': Value {result} above max {config.max_value} (Raw: '{raw_text}')"
        )
        return None

    last_values[config.name] = result
    return result
