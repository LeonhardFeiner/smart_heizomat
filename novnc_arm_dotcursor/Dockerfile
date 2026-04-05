FROM arm32v7/debian:bullseye-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    bash \
    libffi-dev \
    build-essential \
    && pip3 install websockify

RUN git clone https://github.com/novnc/noVNC.git /opt/noVNC

WORKDIR /opt/noVNC


RUN sed '/{ credentials: { password: password } });/a \
rfb.showDotCursor = true;' /opt/noVNC/vnc_lite.html > /opt/noVNC/vnc_lite_modified.html

CMD ["sh", "-c", "websockify --web=. 6080 ${VNC_SERVER:-localhost}:${VNC_PORT:-5900}"]

EXPOSE 6080
