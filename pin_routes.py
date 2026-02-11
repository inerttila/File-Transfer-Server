import os
import pathlib

from flask import redirect, request, url_for


def register_pin_routes(app, pin_service, safe_upload_path, get_client_ip, render_pin_entry_page):
    @app.route("/uploads/<folder>/pin", methods=["GET", "POST"])
    def pin_entry(folder):
        path = safe_upload_path(folder)
        if path is None or not os.path.isdir(path):
            return "Not found", 404
        if not pin_service.folder_has_pin(folder):
            return redirect(url_for("list_or_download_uploads", subpath=folder))
        if request.method == "POST":
            pin = (request.form.get("pin") or "").strip()
            next_url = request.form.get("next") or url_for("list_or_download_uploads", subpath=folder)
            if pin_service.verify_folder_pin(folder, pin):
                pin_service.unlock_folder_with_fek(folder, pin)
                resp = redirect(next_url)
                if pin_service.folder_has_encryption(folder):
                    fek_b64 = pin_service.get_session_fek_b64(folder)
                    if fek_b64:
                        token = pin_service.unlock_store_add(folder, fek_b64)
                        pin_service.set_unlock_cookie_on_response(resp, folder, token)
                return resp
            return render_pin_entry_page(folder, next_url, error="Wrong PIN. Try again."), 401
        next_url = request.args.get("next") or url_for("list_or_download_uploads", subpath=folder)
        return render_pin_entry_page(folder, next_url)

    @app.route("/uploads/<folder>/set-pin", methods=["POST"])
    def set_pin(folder):
        client_ip = get_client_ip().strip()
        if client_ip != folder and client_ip not in ("127.0.0.1", "::1"):
            return {"ok": False, "error": "You can only set a PIN for your own folder."}, 403
        folder_path = pathlib.Path(app.config["UPLOAD_FOLDER"], folder)
        folder_path.mkdir(parents=True, exist_ok=True)
        path = safe_upload_path(folder)
        if path is None or not os.path.isdir(path):
            return {"ok": False, "error": "Folder not found."}, 404

        data = request.get_json(force=True, silent=True) or {}
        pin = (data.get("pin") or "").strip() if isinstance(data.get("pin"), str) else ""
        raw_current = data.get("current_pin") if not data.get("remove") else (data.get("current_pin") or data.get("pin"))
        if raw_current is not None and not isinstance(raw_current, str):
            raw_current = str(raw_current)
        current_pin = (raw_current or "").strip() or None
        remove = data.get("remove") is True
        if remove:
            pin = ""
        ok, err = pin_service.set_folder_pin(folder, pin, current_pin=current_pin)
        if err:
            return {"ok": False, "error": err}, 400
        return {"ok": True, "has_pin": bool(pin)}

    @app.route("/uploads/<folder>/pin-status", methods=["GET"])
    def pin_status(folder):
        client_ip = get_client_ip().strip()
        if client_ip != folder and client_ip not in ("127.0.0.1", "::1"):
            return {"has_pin": False}, 403
        return {"has_pin": pin_service.folder_has_pin(folder)}
