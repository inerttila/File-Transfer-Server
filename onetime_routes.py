import json
import mimetypes
import os
import pathlib
import shutil
import re
import secrets
import threading
from io import BytesIO

from flask import jsonify, request, send_file, url_for
from werkzeug.utils import secure_filename

_REGISTRY_LOCK = threading.Lock()
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _onetime_files_dir(app):
    return app.config["ONETIME_FILES_FOLDER"]


def _legacy_onetime_files_dir(upload_root):
    return os.path.join(upload_root, "onetime")


def _legacy_registry_path(upload_root):
    return os.path.join(_legacy_onetime_files_dir(upload_root), ".registry.json")


def _migrate_legacy_onetime_files_if_needed(app):
    """Move uploads/onetime/ to sibling onetime/ if present."""
    new = _onetime_files_dir(app)
    if os.path.isdir(new):
        return
    old = _legacy_onetime_files_dir(app.config["UPLOAD_FOLDER"])
    if not os.path.isdir(old):
        return
    try:
        shutil.move(old, new)
    except OSError:
        pass


def _registry_path(app):
    return app.config["ONETIME_REGISTRY_PATH"]


def _migrate_legacy_registry_if_needed(app):
    path = _registry_path(app)
    if os.path.isfile(path):
        return
    legacy = _legacy_registry_path(app.config["UPLOAD_FOLDER"])
    if not os.path.isfile(legacy):
        return
    try:
        shutil.move(legacy, path)
    except OSError:
        pass


def _ensure_onetime_files_dir(app):
    _migrate_legacy_onetime_files_if_needed(app)
    path = _onetime_files_dir(app)
    os.makedirs(path, exist_ok=True)
    return path


def _load_registry(app):
    _migrate_legacy_registry_if_needed(app)
    path = _registry_path(app)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_registry(app, registry):
    path = _registry_path(app)
    if not registry:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=0, sort_keys=True)
    os.replace(tmp, path)


def register_onetime_routes(app, render_onetime_share_page, render_onetime_invalid_page):
    """One-time download links: upload once, first GET consumes file and deletes it."""

    @app.route("/one-time-link", methods=["GET"])
    def onetime_share_page():
        return render_onetime_share_page()

    @app.route("/api/one-time-link", methods=["POST"])
    def api_one_time_share():
        if "file" not in request.files:
            return jsonify({"error": "No file part"}), 400
        file = request.files["file"]
        if not file or not file.filename:
            return jsonify({"error": "No selected file"}), 400
        original_name = file.filename
        safe_name = secure_filename(original_name)
        if not safe_name:
            return jsonify({"error": "Invalid file name"}), 400

        token = secrets.token_urlsafe(24)

        _ensure_onetime_files_dir(app)
        stored_name = f"{token}_{safe_name}"
        ot_dir = _onetime_files_dir(app)
        disk_path = os.path.join(ot_dir, stored_name)
        base = os.path.abspath(ot_dir)
        abs_path = os.path.abspath(disk_path)
        if not abs_path.startswith(base + os.sep) and abs_path != base:
            return jsonify({"error": "Invalid path"}), 400

        try:
            file.save(abs_path)
        except OSError:
            return jsonify({"error": "Could not save file"}), 500

        entry = {
            "stored_name": stored_name,
            "original_name": os.path.basename(original_name) or safe_name,
        }
        with _REGISTRY_LOCK:
            registry = _load_registry(app)
            registry[token] = entry
            _save_registry(app, registry)

        download_url = url_for("onetime_download", token=token, _external=True)
        return jsonify(
            {
                "download_url": download_url,
                "original_name": entry["original_name"],
            }
        )

    @app.route("/o/<token>", methods=["GET"])
    def onetime_download(token):
        if not token or not _TOKEN_RE.match(token):
            return render_onetime_invalid_page(), 404

        _migrate_legacy_onetime_files_if_needed(app)
        ot_dir = _onetime_files_dir(app)
        onetime_base = os.path.abspath(ot_dir)

        with _REGISTRY_LOCK:
            registry = _load_registry(app)
            if token not in registry:
                return render_onetime_invalid_page(), 404
            info = registry[token]
            stored_name = info.get("stored_name")
            original_name = info.get("original_name") or "download"
            if not stored_name or not isinstance(stored_name, str):
                registry.pop(token, None)
                _save_registry(app, registry)
                return render_onetime_invalid_page(), 404

            disk_path = os.path.join(ot_dir, stored_name)
            abs_path = os.path.abspath(disk_path)
            if not abs_path.startswith(onetime_base + os.sep):
                registry.pop(token, None)
                _save_registry(app, registry)
                return render_onetime_invalid_page(), 404

            if not os.path.isfile(abs_path):
                registry.pop(token, None)
                _save_registry(app, registry)
                return render_onetime_invalid_page(), 404

            p = pathlib.Path(abs_path)
            try:
                raw = p.read_bytes()
            except OSError:
                return render_onetime_invalid_page(), 404

            del registry[token]
            _save_registry(app, registry)
            try:
                p.unlink()
            except OSError:
                pass

        guessed = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
        return send_file(
            BytesIO(raw),
            as_attachment=True,
            download_name=original_name,
            mimetype=guessed,
        )
