import os
import pathlib
import shutil

from flask import redirect, request, url_for
from ui_pages import GIPHY_LOGO_URL


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
            confirm_final = (request.form.get("confirm_final_attempt") or "").strip() == "1"
            if confirm_final:
                pin_service.confirm_final_attempt(folder)
            if pin_service.verify_folder_pin(folder, pin):
                pin_service.clear_pin_failures(folder)
                pin_service.unlock_folder_with_fek(folder, pin)
                resp = redirect(next_url)
                if pin_service.folder_has_encryption(folder):
                    fek_b64 = pin_service.get_session_fek_b64(folder)
                    if fek_b64:
                        token = pin_service.unlock_store_add(folder, fek_b64)
                        pin_service.set_unlock_cookie_on_response(resp, folder, token)
                return resp
            failures = pin_service.register_failed_pin_attempt(folder)
            if failures == 9:
                return (
                    render_pin_entry_page(
                        folder,
                        next_url,
                        error="Wrong PIN. 1 attempt left before folder deletion.",
                        show_final_attempt_popup=True,
                    ),
                    401,
                )
            if failures >= 10:
                if not pin_service.is_final_attempt_confirmed(folder):
                    return (
                        render_pin_entry_page(
                            folder,
                            next_url,
                            error="Wrong PIN. Confirm the final attempt warning to continue.",
                            show_final_attempt_popup=True,
                        ),
                        401,
                    )
                try:
                    shutil.rmtree(path)
                except OSError:
                    return "Too many wrong attempts. Failed to delete folder.", 500
                if not pin_service.remove_folder_details(folder):
                    return "Folder deleted, but failed to remove PIN details.", 500
                return (
                    "<!doctype html><html><head>"
                    '<meta charset="UTF-8">'
                    '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
                    f'<link rel="icon" href="{GIPHY_LOGO_URL}" type="image/gif">'
                    "<title>Folder Deleted - File Transfer Server</title>"
                    '</head><body style="font-family:Segoe UI;'
                    'background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;'
                    'align-items:center;justify-content:center;margin:0;">'
                    '<div style="text-align:center;background:rgba(255,255,255,0.06);'
                    'border-radius:16px;padding:2.5rem 2.5rem 2rem 2.5rem;box-shadow:0 20px 50px rgba(0,0,0,0.3);">'
                    '<h2 style="margin-top:0;margin-bottom:1.1rem;">Folder deleted</h2>'
                    '<p style="margin:0 0 1.15rem 0;">Too many wrong PIN attempts. This folder has been removed.</p>'
                    '<p style="margin:0;"><a href="/uploads" style="color:#7dd3fc;text-decoration:none;font-size:1rem;">Back to Uploads</a></p>'
                    '</div></body></html>',
                    410,
                )
            left = 10 - failures
            return render_pin_entry_page(folder, next_url, error=f"Wrong PIN. {left} attempt(s) left."), 401
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
