import logging
import os
import shutil
import subprocess
import time

import cv2

from .ocr import DEBUG_DIR, DEBUG_OCR, crop_and_ocr, is_area_grey
from .sensors import sollwerte_indicator

logger = logging.getLogger(__name__)

VNC_ADDRESS = os.environ.get("VNC_ADDRESS", "")
VNC_PW = os.environ.get("VNC_PW", "")


def vnc_cmd(actions: list):
    addr = VNC_ADDRESS if ":" in VNC_ADDRESS else f"{VNC_ADDRESS}:0"
    base = ["vncdotool", "-s", addr]
    if VNC_PW:
        base.extend(["-p", VNC_PW])
    try:
        subprocess.run(base + actions, check=True, capture_output=True, timeout=15)
        return True
    except Exception as e:
        logger.error(f"VNC Error: {e}, Command: {' '.join(base + actions)}")
        return False


def capture(filename):
    if not vnc_cmd(["capture", filename]):
        logger.error(f"Failed to capture {filename}")
        return None

    img = cv2.imread(filename)
    if img is None:
        logger.error(f"Failed to read {filename} from disk")
        return None

    if DEBUG_OCR:
        shutil.copy(filename, os.path.join(DEBUG_DIR, f"_{filename}"))

    return img


def capture_hold_sollwerte(filename="setpoint.png"):
    """Moves to the Sollwerte button, presses down, captures, and releases."""
    x, y = 450, 455
    action_sequence = [
        "mousemove", str(x), str(y),
        "mousedown", "1",
        "pause", "0.5",
        "capture", filename,
        "mouseup", "1",
    ]

    if not vnc_cmd(action_sequence):
        logger.error(f"Failed to execute touch-capture for {filename}")
        return None

    img = cv2.imread(filename)
    if img is None:
        return None

    if DEBUG_OCR:
        shutil.copy(filename, os.path.join(DEBUG_DIR, f"_touch_{filename}"))

    time.sleep(0.5)
    return img


def check_sollwerte_page(img):
    check_val = crop_and_ocr(img, sollwerte_indicator)
    return check_val and "soll" in str(check_val).lower()


def toggle_page():
    if not vnc_cmd(["mousemove", "649", "455", "click", "1"]):
        logger.error("Failed to switch page via VNC")
        return False
    time.sleep(0.6)
    return True


def capture_current_page(filename):
    img = capture(filename)
    if img is None:
        return None

    if not is_area_grey(img):
        logger.info("HMI State: Red/Green detected. Skipping cycle.")
        if DEBUG_OCR:
            shutil.copy(filename, os.path.join(DEBUG_DIR, "_non_grey.png"))
        return {}

    result_dict = {}

    if check_sollwerte_page(img):
        new_name = "boiler"
        result_dict["setpoint"] = capture_hold_sollwerte()
    else:
        new_name = "main"

    result_dict[new_name] = img

    if DEBUG_OCR:
        shutil.copy(filename, os.path.join(DEBUG_DIR, f"_{new_name}.png"))

    return result_dict


def capture_hmi():
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
