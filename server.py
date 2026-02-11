import os
import sys

from flask import Flask, request
from flask_sock import Sock

from pin_routes import register_pin_routes
from pin_service import PinService
from ui_pages import (
    render_folder_not_found_page,
    render_home_page,
    render_pin_entry_page,
    render_uploads_page,
)
from upload_routes import register_upload_routes


# Windows: prevent Werkzeug from using socket.fromfd (not supported on Windows).
# Otherwise a leftover WERKZEUG_RUN_MAIN / WERKZEUG_SERVER_FD can trigger WinError 10038.
if sys.platform == "win32":
    os.environ.pop("WERKZEUG_RUN_MAIN", None)
    os.environ.pop("WERKZEUG_SERVER_FD", None)


def get_or_create_folder(folder_path):
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    return folder_path


def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.remote_addr or "unknown"


UPLOAD_FOLDER = get_or_create_folder("uploads")
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-in-production")
sock = Sock(app)

pin_service = PinService(app.config["UPLOAD_FOLDER"], app.secret_key)


def _safe_upload_path(*parts):
    base = os.path.abspath(app.config["UPLOAD_FOLDER"])
    path = os.path.abspath(os.path.join(base, *parts))
    return path if path.startswith(base) and os.path.exists(path) else None


register_pin_routes(
    app=app,
    pin_service=pin_service,
    safe_upload_path=_safe_upload_path,
    get_client_ip=get_client_ip,
    render_pin_entry_page=render_pin_entry_page,
)

register_upload_routes(
    app=app,
    pin_service=pin_service,
    safe_upload_path=_safe_upload_path,
    get_client_ip=get_client_ip,
    render_uploads_page=render_uploads_page,
    render_folder_not_found_page=render_folder_not_found_page,
    render_home_page=render_home_page,
)


@sock.route("/websocket")
def websocket(ws):
    while True:
        try:
            data = ws.receive()
            if data is None:
                break
            ws.send(data)
        except Exception:
            break


DEFAULT_PORT = 8069

# On Windows, socket.fromfd() is not supported; disable reloader to avoid fd-based server.
_RUN_OPTS = {"use_reloader": False} if sys.platform == "win32" else {}

if __name__ == "__main__":
    if len(sys.argv) == 1:
        app.run(host="0.0.0.0", port=DEFAULT_PORT, **_RUN_OPTS)
    elif sys.argv[-1] == "80":
        app.run(host="0.0.0.0", port=80, **_RUN_OPTS)
    elif sys.argv[-1] == "help":
        print("\nExamples:\n\tDev: python server.py\n\tDeploy: python server.py 80\n\tDeploy custom port: python server.py <9598>\n\n")
    else:
        try:
            port = int(sys.argv[-1])
            app.run(host="0.0.0.0", port=port, **_RUN_OPTS)
        except (ValueError, OSError):
            print("Cannot open port", sys.argv[-1])
            print("Running on localhost:" + str(DEFAULT_PORT))
            app.run(port=DEFAULT_PORT, **_RUN_OPTS)
