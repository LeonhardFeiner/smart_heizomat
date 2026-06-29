FROM debian:bullseye-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    python3-websockify \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/novnc/noVNC.git /opt/noVNC

WORKDIR /opt/noVNC

RUN sed '/{ credentials: { password: password } });/a \
rfb.showDotCursor = true;' /opt/noVNC/vnc_lite.html > /opt/noVNC/vnc_lite_modified.html

CMD ["sh", "-c", "websockify --web=. 6080 ${VNC_SERVER:-localhost}:${VNC_PORT:-5900}"]

EXPOSE 6080
