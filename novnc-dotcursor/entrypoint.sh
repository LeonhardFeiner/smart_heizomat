#!/bin/sh
set -e

if [ -n "$VNC_PASSWORD" ]; then
    esc=$(printf '%s' "$VNC_PASSWORD" | sed -e 's/[\/&]/\\&/g')
    sed -i "s/__VNC_PASSWORD__/$esc/" /opt/noVNC/vnc_lite_modified.html
fi

exec "$@"
