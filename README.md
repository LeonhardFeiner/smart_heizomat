# smart_heizomat

Reads sensor values from a **Heizomat RHK-AK 100** wood chip boiler by connecting to its HMI via VNC, capturing screenshots, and extracting values with OCR. Publishes results to MQTT with Home Assistant auto-discovery.

## How it works

```
Heizomat HMI (VNC) ──► screenshot ──► OCR ──► MQTT ──► Home Assistant
```

1. `heizomat-mqtt` connects to the boiler's VNC server and takes screenshots of the HMI display
2. It navigates between the main screen and the boiler/setpoint screen by simulating mouse clicks
3. Tesseract OCR extracts ~28 sensor values from fixed pixel regions
4. Values are published as a JSON payload to MQTT, with Home Assistant discovery config on first connect

## Services

| Service | Image | Description |
|---|---|---|
| `heizomat-mqtt` | `feiner/heizomat-mqtt` | VNC capture + OCR + MQTT publisher |
| `novnc` | `feiner/novnc-dotcursor` | noVNC web proxy (view the HMI in a browser), with dot cursor patch |

## Quick start

1. Copy `.env.example` to `.env` and fill in your values:

```sh
cp .env.example .env
```

2. Start the stack:

```sh
docker compose up -d
```

The noVNC web UI is available at `http://<raspberry-pi-ip>:6080`. Three pages are served:

| URL | Description |
|---|---|
| `http://<raspberry-pi-ip>:6080/vnc_lite_modified.html?password=<vnc_password>` | Lite UI with dot cursor patch (recommended) |
| `http://<raspberry-pi-ip>:6080/vnc_lite.html?password=<vnc_password>` | Lite UI (original) |
| `http://<raspberry-pi-ip>:6080/vnc.html?password=<vnc_password>` | Full noVNC UI |

## Configuration

Non-sensitive settings are hardcoded in `docker-compose.yml`. Secrets go in `.env` (never committed).

### `.env`

| Variable | Description |
|---|---|
| `MQTT_BROKER_HOST` | IP or hostname of the MQTT broker |
| `MQTT_USERNAME` | MQTT username |
| `MQTT_PASSWORD` | MQTT password |
| `VNC_ADDRESS` | IP of the Heizomat VNC server |
| `VNC_PW` | VNC password |

### `docker-compose.yml` (non-sensitive)

| Variable | Default | Description |
|---|---|---|
| `TZ` | `Europe/Berlin` | Timezone |
| `MQTT_BROKER_PORT` | `1883` | MQTT broker port |
| `MQTT_TOPIC` | `heizomat/hackschnitzel` | Topic for sensor JSON payload |
| `SENSOR_BASENAME` | `hackschnitzel` | Prefix for HA entity IDs and discovery topics |
| `PUBLISH_INTERVAL` | `600` | Seconds between readings |
| `DEBUG_OCR` | `false` | Save debug crop images to `./debug_crops/` |

## MQTT topics

| Topic | Content |
|---|---|
| `heizomat/hackschnitzel` | JSON with all sensor values, published every `PUBLISH_INTERVAL` seconds |
| `homeassistant/sensor/hackschnitzel/<sensor>/config` | Retained HA discovery config per sensor |

## Sensors

The following values are read via OCR:

**Main screen:** Kessel_Temperatur, Kessel_Solltemperatur, Betriebszustand, Betriebsart, Brennstoff, Abgas_Temperatur, Abgas_Restsauerstoff, Geblaeseleistung, Partikelabscheider_Strom, Partikelabscheider_Spannung, Primärluft, Sekundärluft, Takt, Pause, RuecklaufMischer_Temperatur, Uhrzeit

**Boiler screen:** BoilerUnten_Temperatur, BoilerMitte_Temperatur, BoilerOben_Temperatur, Heizkreis_1, Heizkreis_2, Sensor_Temperatur, Sensor_Durschnittstemperatur

**Setpoint screen:** Soll_BoilerMitte_Temperatur, Soll_BoilerOben_Temperatur, Soll_Heizkreis_1, Soll_Heizkreis_2, Soll_RuecklaufMischer_Temperatur

## Debugging OCR

Set `DEBUG_OCR=true` in `docker-compose.yml` and mount `./debug_crops`. The container will save cropped images for each sensor region so you can verify OCR input quality.

## CI

Docker images are built for `linux/amd64` and `linux/arm64` via GitHub Actions and pushed to Docker Hub on every push to `main` or a `v*` tag.
