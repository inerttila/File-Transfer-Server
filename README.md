# File Transfer Server

Flask app for uploading and downloading files over the web.

## Setup

```bash
pip install -r requirements.txt
python server.py
```

Runs at **http://0.0.0.0:8069** (port 8069, all interfaces). Use `python server.py 80` for port 80 or `python server.py <port>` for a custom port.

## How it works

- **Home (`/`)** — Upload: choose files, then click Upload. Progress bar shows while uploading.
- **Uploads (`/uploads`)** — List folders (one per client IP). Open a folder to list files; click a file to download.
- Files are stored under `uploads/<client_ip>/`. Client IP is taken from the request (or from `X-Forwarded-For` / `X-Real-IP` when behind a proxy).
- **WebSocket** — Echo endpoint at `/websocket`.

## Requirements

- Python 3.x
- See [requirements.txt](requirements.txt)
