# RDP Computer Use MCP Server - Docker image
# Includes all system dependencies for the Xvfb + xfreerdp3 + xdotool + scrot stack

FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    xvfb \
    freerdp3-x11 \
    xdotool \
    scrot \
    imagemagick \
    boundary \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server.py /app/server.py

ENTRYPOINT ["python3", "/app/server.py"]
