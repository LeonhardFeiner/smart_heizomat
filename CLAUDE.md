# CLAUDE.md

## Project overview

Reads sensor values from a Heizomat RHK-AK 100 wood chip boiler via VNC screenshot + Tesseract OCR, then publishes them to MQTT with Home Assistant auto-discovery. Runs on a Raspberry Pi 5 (ARM64).

## Structure

```
heizomat-mqtt/      Python service: VNC capture → OCR → MQTT publisher
novnc-dotcursor/    noVNC web proxy with dot cursor patch, for viewing the HMI in a browser
docker-compose.yml  Orchestration (uses .env for secrets)
```

## Target platform

Raspberry Pi 5 — **linux/arm64 only**. Do not add `linux/arm/v7` back; QEMU emulation of arm/v7 on GitHub Actions runners is too slow and causes apt-get timeouts and pip compilation hangs.

## Docker images

| Folder | Image | Platforms |
|---|---|---|
| `heizomat-mqtt/` | `feiner/heizomat-mqtt` | `linux/amd64`, `linux/arm64` |
| `novnc-dotcursor/` | `feiner/novnc-dotcursor` | `linux/amd64`, `linux/arm64` |

CI builds and pushes to Docker Hub on every push to `main` or a `v*` tag via `.github/workflows/docker-publish.yml`.

## Configuration

Secrets live in `.env` (gitignored). Non-sensitive config is hardcoded in `docker-compose.yml`. See `.env.example` for required variables.

## Known pitfalls

- Use `opencv-python-headless` not `opencv-python` — the latter links against OpenGL (`libgl1`) which fails to install on headless ARM builds.
- The `novnc-dotcursor` Dockerfile uses `--no-install-recommends`, so `ca-certificates` must be listed explicitly or `git clone` over HTTPS will fail with a certificate error.
- `python3-websockify` from apt pulls in `python3-numpy` as a dependency — this is acceptable (pre-built .deb, no compilation) and intentional to avoid pip-compiled numpy under QEMU.
- `novnc` uses `network_mode: host` (needs direct LAN access to reach the boiler's VNC server). `heizomat-mqtt` runs on the shared `mqtt_net` bridge network (external, created by the `mosquitto` stack) and reaches the broker via `MQTT_BROKER_HOST=mosquitto` — same pattern as `smart_orange`'s `eb7000-mqtt-bridge`.
