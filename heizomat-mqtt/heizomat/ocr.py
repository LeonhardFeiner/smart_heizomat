import logging
import os

import cv2
import numpy as np
import pytesseract

from .sensors import SensorConfig, parse_value, tessedit_char_whitelist

logger = logging.getLogger(__name__)

DEBUG_OCR = os.environ.get("DEBUG_OCR", "false").lower() == "true"
DEBUG_DIR = "/app/debug_crops"


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
    return parse_value(raw_text, sensor_config)


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
