from flask import Flask, request, send_file, jsonify
import subprocess
from PIL import Image
import cv2
import numpy as np
import pytesseract
import os
import logging

import concurrent.futures



default_url = os.environ.get("URL")
app = Flask(__name__)
app.logger.setLevel(logging.INFO)


# Define rectangles (x, y, width, height)

main = {
    "Pause": (173, 476, 68, 23),
    "Takt": (176, 451, 64, 18),
    "Hackgut_P": (208, 338, 41, 16),
    "Hackgut_S": (207, 309, 44, 16),
    "Abgas_Temperatur": (730, 223, 40, 19),
    "Abgas_Restsauerstoff": (726, 195, 48, 23),
    "Gebläseleistung": (555, 195, 48, 23),
    "Partikelabscheider_Strom": (734, 151, 39, 18),
    "Partikelabscheider_Spannung": (654, 151, 39, 18),
    "Kessel_Solltemperatur": (191, 151, 83, 28),
    "Kessel_Temperatur": (192, 114, 81, 31),
    "RücklaufMischer_Temperatur": (719, 456, 54, 18),
    "Zustandrestzeit": (706, 116, 76, 28),
    "Brennstoff": (8, 217, 264, 21),
    "Betriebszustand": (403, 115, 291, 29),
    "Uhrzeit": (302, 74, 196, 31),
    "Betriebsart": (600, 74, 200, 33),
    # "Kessel_Temperatur2": (717, 276, 56, 19),
    # "Party": (305, 509, 89, 39),
    # "sollwerte": (405, 509, 89, 39),
}

boiler = {
    "BoilerUnten_Temperatur": (244, 432, 52, 19),
    "BoilerMitte_Temperatur": (244, 357, 52, 19),
    "BoilerOben_Temperatur": (244, 282, 52, 19),
    "Sensor_Temperatur": (37, 152, 41, 16),
    "Sensor_Durschnittstemperatur": (37, 177, 41, 16),
    "Rohr_oben": (23, 211, 54, 19),
    "Heizkreis_1": (368, 251, 54, 19),
    "Heizkreis_2": (448, 251, 54, 19),
    # "Zustandrestzeit": (706, 116, 76, 28),
    # "Betriebszustand": (403, 115, 291, 29),
    # "RücklaufMischer_Temperatur": (13, 436, 54, 19),
    # "Kessel_Temperatur": (192, 114, 81, 31),
    # "Uhrzeit": (302, 74, 196, 31),
    # "Betriebsart": (600, 74, 200, 33),
    # "Party": (305, 509, 89, 39),
    # "Sollwerte": (405, 509, 89, 39),
}

sollwerte_rect = (405, 509, 89, 39)


def get_associations(images) -> list[tuple[str, dict]]:

    img1, img2 = images

    # Check if "sollwerte" is detected on screenshot 1 or 2 by OCR
    sollwerte_text_1 = crop_and_ocr(img1, sollwerte_rect)
    sollwerte_text_2 = crop_and_ocr(img2, sollwerte_rect)

    app.logger.info(f"Sollwerte text 1: {sollwerte_text_1}")
    app.logger.info(f"Sollwerte text 2: {sollwerte_text_2}")


    first_suffix = ""
    second_suffix = ""

    # Determine which dict to use first screenshot and second
    # If "sollwerte" present in screenshot1 using boiler dict there, else main dict
    if "sollwerte" in sollwerte_text_1.lower():
        first_img_dict = boiler
        second_img_dict = main
        # first_suffix = "_boiler"
        # second_suffix = "_haupt"
    elif "sollwerte" in sollwerte_text_2.lower():
        first_img_dict = main
        second_img_dict = boiler
        # first_suffix = "_haupt"
        # second_suffix = "_boiler"
    else:
        # Default fallback if "sollwerte" not detected - assign boiler to screenshot1
        first_img_dict = main
        second_img_dict = main
        # first_suffix = "_haupt"
        second_suffix = "2"

    return [(first_img_dict, first_suffix), (second_img_dict, second_suffix)]


def preprocess_image_for_ocr(pil_img, rect: tuple):
    x, y, w, h = rect
    cropped = pil_img.crop((x, y, x + w, y + h))

    # Convert PIL Image to numpy array
    img = np.array(cropped.convert("L"))  # grayscale

    # Apply thresholding
    _, img = cv2.threshold(img, 127, 255, cv2.THRESH_OTSU)

    if img.mean() < 127:
        img = cv2.bitwise_not(img)

    # Convert back to PIL Image
    return Image.fromarray(img)


def crop_and_ocr(image: Image.Image, rect: tuple) -> str:
    preprocessed = preprocess_image_for_ocr(image, rect)
    text = pytesseract.image_to_string(preprocessed, "deu", "--psm 6").strip()

    result = text
    try:
        number_str = text.replace(",", ".").lower().replace("ö", "0").replace("o", "0")
        result = float(number_str)
        result = int(number_str) if result.is_integer() else result
    except:
        pass
    return result


def capture_heizomat(*screenshot_pathes: list[str]) -> dict:
    imgs = [Image.open(path) for path in screenshot_pathes]
    suffix_img_dict_list = get_associations(imgs)

    result = {
        f"{k}{suffix}" : crop_and_ocr(img1, rect)
        for img1, (img_dict, suffix) in zip(imgs, suffix_img_dict_list)
        for k, rect in img_dict.items()
    }

    return dict(sorted(result.items()))


def capture_heizomat_parallel(*screenshot_pathes: list[str]) -> dict:
    imgs = [Image.open(path) for path in screenshot_pathes]
    suffix_img_dict_list = get_associations(imgs)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            f"{key}{suffix}": executor.submit(crop_and_ocr, img, rect)
            for img, (img_dict, suffix) in zip(imgs, suffix_img_dict_list)
            for key, rect in img_dict.items()
        }

        # Collect results as they complete
        result = {
            key: future.result()
            for key, future
            in sorted(futures.items())
        }

    return result



@app.route('/capture')
def capture():
    app.logger.info('Capture request received')
    url = request.args.get('url', default=default_url)
    if not url:
        return 'Missing url parameter', 400
    screenshot_path = 'screenshot.png'
    subprocess.run(['python3', 'capture_screenshot_script.py', 'single', url, screenshot_path], check=True)
    return send_file(screenshot_path, mimetype='image/png')

@app.route('/capture-and-ocr')
def capture_and_ocr():
    app.logger.info('Capture and OCR request received')
    url = request.args.get('url', default=default_url)
    if not url:
        return 'Missing url parameter', 400
    screenshot_path = 'screenshot.png'
    subprocess.run(['python3', 'capture_screenshot_script.py', 'single', url, screenshot_path], check=True)
    ocr_text = pytesseract.image_to_string(Image.open(screenshot_path))
    os.remove(screenshot_path)
    return jsonify({'text': ocr_text})

@app.route('/capture-heizomat')
def capture_heizomat_route():
    app.logger.info('Capture Heizomat request received')
    url = request.args.get('url', default=default_url)

    if not url:
        return 'Missing url parameter', 400

    x = request.args.get('x', default=649, type=int)
    y = request.args.get('y', default=528, type=int)

    # Run double screenshot subprocess (creates screenshot1.png and screenshot2.png)
    subprocess.run(['python3', 'capture_screenshot_script.py', 'double', url, str(x), str(y)], check=True)

    app.logger.info('Start OCR processing')

    # Run your OCR extraction logic on these two screenshots
    ocr_results = capture_heizomat_parallel('screenshot1.png', 'screenshot2.png')

    # Return as JSON response
    return jsonify(ocr_results)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
