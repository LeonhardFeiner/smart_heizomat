import datetime
import hashlib
import logging
import os
import re

import cv2
import numpy as np
import pytesseract

from .sensors import SensorConfig, match_enum, parse_value, tessedit_char_whitelist

logger = logging.getLogger(__name__)

DEBUG_OCR = os.environ.get("DEBUG_OCR", "false").lower() == "true"
DEBUG_DIR = "/app/debug_crops"
ANOMALY_DIR = os.path.join(DEBUG_DIR, "anomalies")
os.makedirs(ANOMALY_DIR, exist_ok=True)

# Raw (pre-match) OCR text per sensor name, for enum sensors — published
# alongside the curated value as a debug side-channel (see app.py), without
# an HA discovery config of its own.
last_raw_text: dict = {}


def _capture_anomaly(full_img, crop_img, sensor_name, raw_text):
    """Saves the full page + crop for an OCR read that failed to parse, once
    per distinct (sensor, raw text) pair — repeat misreads of the same bad
    text don't pile up more copies, so this stays cheap to review later."""
    key_hash = hashlib.sha1(f"{sensor_name}|{raw_text}".encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^A-Za-z0-9]+", "_", raw_text.strip()).strip("_")[:40] or "empty"
    base = os.path.join(ANOMALY_DIR, f"{sensor_name}__{slug}_{key_hash}")
    marker = f"{base}.txt"

    if os.path.exists(marker):
        return

    cv2.imwrite(f"{base}_full.png", full_img)
    cv2.imwrite(f"{base}_crop.png", crop_img)
    with open(marker, "w") as f:
        f.write(
            f"sensor: {sensor_name}\n"
            f"raw_text: {raw_text!r}\n"
            f"first_seen: {datetime.datetime.now().isoformat()}\n"
        )


def preprocess_image_for_ocr(cv_img, rect, sensor_name="unknown", parser_type=None):
    x, y, w, h = rect
    cropped = cv_img[y : y + h, x : x + w]

    if DEBUG_OCR:
        cv2.imwrite(os.path.join(DEBUG_DIR, f"{sensor_name}.png"), cropped)

    if parser_type == "datetime":
        # The clock is small enough that binarizing at native size then
        # LINEAR-upscaling the resulting blocky mask corrupts digits (observed:
        # "57" -> "537", a phantom stroke inserted between two adjacent glyphs).
        # Upscaling the grayscale image with CUBIC *before* thresholding keeps
        # the antialiased edges intact for OTSU to binarize cleanly.
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        upscaled = cv2.resize(gray, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
        _, thresh = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(thresh) < 127:
            thresh = cv2.bitwise_not(thresh)
    elif parser_type in ("float", "int"):
        # The VNC capture carries single/few-pixel chromatic fringing (visible
        # red/green ghosting on character edges) that corrupts grayscale
        # conversion and OTSU thresholding, dropping small marks like the
        # decimal comma or hallucinating extra digits. A median blur cleans
        # this up -- but applying it to the *native-size* crop first erodes
        # thin-stroke fonts (a 1px-wide digit stroke looks like salt-and-
        # pepper noise to a 3x3 median kernel and gets wiped out entirely --
        # this dropped the leading "2" of "21,5" down to "1,5" in production).
        # Thresholding and upscaling first, then denoising the now-3x-wider
        # strokes, removes the fringe artifacts without erasing real digits.
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(thresh) < 127:
            thresh = cv2.bitwise_not(thresh)
        thresh = cv2.resize(thresh, (w * 3, h * 3), interpolation=cv2.INTER_LINEAR)
        thresh = cv2.medianBlur(thresh, 3)
    else:
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(thresh) < 127:
            thresh = cv2.bitwise_not(thresh)
        thresh = cv2.resize(thresh, (w * 3, h * 3), interpolation=cv2.INTER_LINEAR)

    bordered = cv2.copyMakeBorder(thresh, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=255)

    if DEBUG_OCR:
        cv2.imwrite(os.path.join(DEBUG_DIR, f"{sensor_name}_processed.png"), bordered)

    return bordered


def ocr(img, page_segmentation_mode, whitelist=None, *, oem=3, lang="deu"):
    tess_config = f"--psm {page_segmentation_mode} --oem {oem}"
    if whitelist:
        tess_config += f" -c tessedit_char_whitelist={whitelist}"
    return pytesseract.image_to_string(img, lang=lang, config=tess_config).strip()


def crop_and_ocr(cv_img, sensor_config: SensorConfig):
    processed_img = preprocess_image_for_ocr(
        cv_img, sensor_config.rect, sensor_config.name, sensor_config.parser_type
    )
    raw_text = ocr(
        processed_img,
        sensor_config.page_segmentation_mode,
        whitelist=tessedit_char_whitelist.get(sensor_config.parser_type),
    )

    if sensor_config.parser_type == "enum":
        last_raw_text[sensor_config.name] = raw_text
        result, exact = match_enum(raw_text, sensor_config.enum_options)
        anomaly = not exact
    else:
        result = parse_value(raw_text, sensor_config)
        anomaly = result is None

    if anomaly:
        x, y, w, h = sensor_config.rect
        crop = cv_img[y : y + h, x : x + w]
        _capture_anomaly(cv_img, crop, sensor_config.name, raw_text)

    return result


def is_dialog_open(img, rect=(380, 200, 60, 60)):
    """Checks the boiler firebox graphic on the "main" page -- a fixed patch
    of the display that is always richly colored (red/orange fire artwork) in
    every normal state. A "Meldungen" (warnings) popup renders as a plain
    white dialog body on top of the page and covers this exact area, so a
    near-white/desaturated reading here means the popup is open and every
    sensor crop underneath it would read blank. Only meaningful on the "main"
    page layout (the "boiler"/"setpoint" page has different artwork here)."""
    x, y, w, h = rect

    if img is None:
        return False

    crop = img[y : y + h, x : x + w]
    hsv_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    avg_saturation = np.mean(hsv_crop[:, :, 1])
    avg_value = np.mean(hsv_crop[:, :, 2])

    if DEBUG_OCR:
        cv2.imwrite(os.path.join(DEBUG_DIR, "_dialog_check.png"), crop)
        logger.info(
            f"Dialog Check: Avg Saturation={avg_saturation:.2f}, Avg Value={avg_value:.2f}"
        )

    return avg_saturation < 10 and avg_value > 240


def is_screen_blanked(img, threshold=15):
    """Checks whole-frame brightness. The HMI's touchscreen falls back to a
    near-black idle screensaver after inactivity, which would otherwise slip
    past is_dialog_open() (black has near-zero saturation too, but so does a
    lit page's grey chrome) and produce a page-wide burst of blank reads."""
    if img is None:
        return False
    return float(np.mean(img)) < threshold


def is_area_grey(img, rect=(580, 0, 20, 35)):
    """Checks if the area (x, y, w, h) in the image is grey."""
    x, y, w, h = rect

    if img is None:
        return False

    crop = img[y : y + h, x : x + w]
    hsv_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    avg_saturation = np.mean(hsv_crop[:, :, 1])
    avg_value = np.mean(hsv_crop[:, :, 2])

    if DEBUG_OCR:
        cv2.imwrite(os.path.join(DEBUG_DIR, "_color_check.png"), crop)
        logger.info(
            f"Color Check: Avg Saturation={avg_saturation:.2f}, Avg Value={avg_value:.2f}"
        )

    return avg_saturation < 50
