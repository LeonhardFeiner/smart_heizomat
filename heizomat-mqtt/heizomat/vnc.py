import logging
import os
import shutil
import subprocess
import threading
import time

import cv2

from .ocr import DEBUG_DIR, DEBUG_OCR, crop_and_ocr, is_area_grey, is_dialog_open, is_screen_blanked
from .sensors import main_sensors, sollwerte_indicator, uhrzeit_sensor

logger = logging.getLogger(__name__)

VNC_ADDRESS = os.environ.get("VNC_ADDRESS", "")
VNC_PW = os.environ.get("VNC_PASSWORD", "")

SETTLE_RETRIES = 2
SETTLE_SLEEP = 0.4

# Close ("X") button of the "Meldungen" warnings popup, on the main page only.
DIALOG_CLOSE_BUTTON = (721, 75)

# The HMI blanks to a near-black screensaver after a few idle minutes, and the
# poll interval (600s) is far longer than that timeout, so almost every cycle
# used to land on a blank screen and get skipped. On a wake tap we aim for the
# empty gap in the top status bar (between the "Kunde" label and the clock, no
# control underneath) -- a Siemens Comfort panel consumes the first touch purely
# to dismiss the screensaver and does not forward it, but targeting dead space
# keeps it a no-op even if some firmware revision does forward it.
WAKE_TAP = (230, 14)
WAKE_SETTLE = 5.0

# Red off button, bottom-left of the main page. It only exists while the boiler
# is running or in "Wartung mit RGG"; once pressed in RGG the HMI drops to plain
# "Wartung" (confirmed live 2026-10-02). The green start button next to it needs a
# 3 s hold, so a stray click here can never start the boiler.
OFF_BUTTON = (50, 455)
OFF_SETTLE = 3.0
RGG_STATE = "Wartung mit RGG"
OFF_STATE = "Wartung"

# Serialises every VNC session: the poll cycle flips between pages, so an
# off-button click landing mid-cycle could hit the wrong page layout.
HMI_LOCK = threading.Lock()

_sensors_by_name = {s.name: s for s in main_sensors}


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


def capture_settled(filename, img):
    """Retry the capture if the clock is unreadable, which usually means the
    HMI's top info bar was still mid-redraw when the screenshot was taken."""
    for attempt in range(SETTLE_RETRIES + 1):
        if crop_and_ocr(img, uhrzeit_sensor):
            return img
        if attempt == SETTLE_RETRIES:
            logger.warning("Uhrzeit still unreadable after retries; using capture as-is")
            return img
        logger.warning("Uhrzeit unreadable, HMI may be mid-redraw; retrying capture")
        time.sleep(SETTLE_SLEEP)
        img = capture(filename)
        if img is None:
            return None
    return img


def check_sollwerte_page(img):
    check_val = crop_and_ocr(img, sollwerte_indicator)
    return check_val and "soll" in str(check_val).lower()


def wake_screen():
    """Dismiss the HMI's idle screensaver with a tap on dead screen space, then
    wait for the page to redraw. Returns False if the VNC command itself failed."""
    x, y = WAKE_TAP
    if not vnc_cmd(["mousemove", str(x), str(y), "click", "1"]):
        logger.error("Failed to send wake tap to HMI")
        return False
    time.sleep(WAKE_SETTLE)
    return True


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

    if is_screen_blanked(img):
        logger.info("HMI screen blank (idle screensaver); sending wake tap")
        if not wake_screen():
            return {}
        img = capture(filename)
        if img is None:
            return None
        if is_screen_blanked(img):
            logger.warning("HMI screen still blank after wake tap; skipping cycle")
            if DEBUG_OCR:
                shutil.copy(filename, os.path.join(DEBUG_DIR, "_blanked.png"))
            return {}

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

        # A "Meldungen" (warnings) popup can be sitting open over the main
        # page, covering most sensor fields with a plain white dialog body
        # and producing a burst of blank/garbage reads across every sensor
        # underneath it. is_dialog_open() only applies to this page layout
        # (the boiler/setpoint page's artwork differs), so it's checked here.
        if is_dialog_open(img):
            logger.warning("Meldungen dialog appears open on HMI; attempting to dismiss")
            x, y = DIALOG_CLOSE_BUTTON
            if not vnc_cmd(["mousemove", str(x), str(y), "click", "1"]):
                logger.error("Failed to click dialog close button")
                return None
            time.sleep(0.5)
            img = capture(filename)
            if img is None:
                return None
            if is_dialog_open(img):
                logger.warning("Dialog still open after dismiss attempt; skipping cycle")
                if DEBUG_OCR:
                    shutil.copy(filename, os.path.join(DEBUG_DIR, "_dialog_blocked.png"))
                return {}

        img = capture_settled(filename, img)
        if img is None:
            return None

    result_dict[new_name] = img

    if DEBUG_OCR:
        shutil.copy(filename, os.path.join(DEBUG_DIR, f"_{new_name}.png"))

    return result_dict


def _read_modes(img):
    return {n: crop_and_ocr(img, _sensors_by_name[n]) for n in ("Betriebsart", "Betriebszustand")}


def switch_off_from_rgg():
    """Presses the HMI off button to finish the warm-weather shutdown
    (Wartung mit RGG -> Wartung). Re-reads the state from a fresh screenshot
    right before clicking, since the command can arrive minutes after the
    decision was made (and OCR is only polled every 10 min). Returns (ok, message)."""
    with HMI_LOCK:
        pages = capture_current_page("off_check.png")
        if not pages or "main" not in pages:
            return False, "HMI nicht auf der Hauptseite lesbar (Bildschirm/Dialog), nichts geklickt"

        modes = _read_modes(pages["main"])
        if RGG_STATE not in modes.values():
            return False, f"Zustand ist nicht '{RGG_STATE}' ({modes}), nichts geklickt"

        x, y = OFF_BUTTON
        if not vnc_cmd(["mousemove", str(x), str(y), "click", "1"]):
            return False, "VNC-Klick auf Aus-Taste fehlgeschlagen"
        time.sleep(OFF_SETTLE)

        img = capture("off_verify.png")
        if img is None:
            return False, "Aus-Taste geklickt, Kontrollbild fehlgeschlagen"
        after = _read_modes(img)
        if after["Betriebsart"] == OFF_STATE:
            return True, f"'{RGG_STATE}' -> '{OFF_STATE}'"
        return False, f"Aus-Taste geklickt, aber Zustand nicht bestätigt ({after})"


def capture_hmi():
    with HMI_LOCK:
        return _capture_hmi_locked()


def _capture_hmi_locked():
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
