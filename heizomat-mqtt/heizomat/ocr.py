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


def preprocess_image_for_ocr(cv_img, rect, sensor_name="unknown"):
    x, y, w, h = rect
    cropped = cv_img[y : y + h, x : x + w]

    if DEBUG_OCR:
        cv2.imwrite(os.path.join(DEBUG_DIR, f"{sensor_name}.png"), cropped)

    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    if np.mean(thresh) < 127:
        thresh = cv2.bitwise_not(thresh)

    upscaled = cv2.resize(thresh, (w * 3, h * 3), interpolation=cv2.INTER_LINEAR)
    bordered = cv2.copyMakeBorder(upscaled, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=255)

    if DEBUG_OCR:
        cv2.imwrite(os.path.join(DEBUG_DIR, f"{sensor_name}_processed.png"), bordered)

    return bordered


def ocr(img, page_segmentation_mode, whitelist=None, *, oem=3, lang="deu"):
    tess_config = f"--psm {page_segmentation_mode} --oem {oem}"
    if whitelist:
        tess_config += f" -c tessedit_char_whitelist={whitelist}"
    return pytesseract.image_to_string(img, lang=lang, config=tess_config).strip()


def crop_and_ocr(cv_img, sensor_config: SensorConfig):
    processed_img = preprocess_image_for_ocr(cv_img, sensor_config.rect, sensor_config.name)
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
