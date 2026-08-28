FROM debian:bullseye-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    python3-websockify \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/novnc/noVNC.git /opt/noVNC

WORKDIR /opt/noVNC

RUN sed -e '/{ credentials: { password: password } });/a \
rfb.showDotCursor = true;' \
    -e "s/readQueryVariable('password')/readQueryVariable('password', '__VNC_PASSWORD__')/" \
    /opt/noVNC/vnc_lite.html > /opt/noVNC/vnc_lite_modified.html

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "-c", "websockify --web=. 6080 ${VNC_SERVER:-localhost}:${VNC_PORT:-5900}"]

EXPOSE 6080
