import os
import pathlib
import shutil
import mimetypes
from io import BytesIO
from urllib.parse import quote

from werkzeug.utils import secure_filename

from flask import flash, redirect, request, send_file, url_for


def register_upload_routes(
    app,
    pin_service,
    safe_upload_path,
    get_client_ip,
    render_uploads_page,
    render_folder_not_found_page,
    render_home_page,
):
    @app.route("/api/uploader-folder", methods=["GET"])
    def api_uploader_folder():
        return {"folder": get_client_ip().strip()}

    @app.route("/api/uploader-has-folder", methods=["GET"])
    def api_uploader_has_folder():
        folder = get_client_ip().strip()
        path = pathlib.Path(app.config["UPLOAD_FOLDER"], folder)
        return {"has_folder": path.is_dir()}

    @app.route("/uploads", methods=["GET"])
    @app.route("/uploads/<path:subpath>", methods=["GET", "POST"])
    def list_or_download_uploads(subpath=None):
        if not subpath:
            base = app.config["UPLOAD_FOLDER"]
            if not os.path.isdir(base):
                return render_uploads_page("Uploads", '<a href="/">Home</a> / Uploads', [])
            folders = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
            folders.sort(reverse=True)
            client_ip = get_client_ip().strip()
            items = []
            for folder_name in folders:
                item = {"url": f"/uploads/{quote(folder_name)}", "label": folder_name}
                if client_ip == folder_name or client_ip in ("127.0.0.1", "::1"):
                    item["delete_url"] = f"/uploads/{quote(folder_name)}/delete-folder"
                    item["delete_message"] = "Delete this folder and all its files?"
                    item["pin_menu"] = True
                    item["folder_name"] = folder_name
                    item["has_pin"] = pin_service.folder_has_pin(folder_name)
                items.append(item)
            return render_uploads_page("Uploads", '<a href="/">Home</a> / Uploads', items)

        parts = subpath.strip("/").split("/")
        folder = parts[0]
        path = safe_upload_path(folder)
        if path is None:
            return render_folder_not_found_page(), 404

        if request.method == "POST" and len(parts) == 2 and parts[-1] == "delete-folder":
            client_ip = get_client_ip().strip()
            if client_ip != folder and client_ip not in ("127.0.0.1", "::1"):
                return "Forbidden: you can only delete your own folder.", 403
            if not os.path.isdir(path):
                return "Not found", 404
            try:
                shutil.rmtree(path)
            except OSError:
                return "Could not delete folder.", 500
            if not pin_service.remove_folder_details(folder):
                return "Folder deleted, but failed to remove PIN details.", 500
            return redirect(url_for("list_or_download_uploads"))

        if request.method == "POST" and len(parts) >= 2 and parts[-1] == "delete":
            client_ip = get_client_ip().strip()
            if client_ip != folder and client_ip not in ("127.0.0.1", "::1"):
                return "Forbidden: you can only delete your own files.", 403
            filename = "/".join(parts[1:-1])
            file_path = safe_upload_path(folder, filename)
            if file_path is None or not os.path.isfile(file_path):
                return "Not found", 404
            try:
                os.remove(file_path)
            except OSError:
                return "Could not delete file.", 500
            return redirect(url_for("list_or_download_uploads", subpath=folder))

        if len(parts) == 1:
            if not os.path.isdir(path):
                return render_folder_not_found_page(), 404
            if pin_service.folder_has_pin(folder) and not pin_service.is_folder_unlocked(folder):
                next_url = url_for("list_or_download_uploads", subpath=folder)
                return redirect(url_for("pin_entry", folder=folder, next=next_url))
            client_ip = get_client_ip().strip()
            can_delete = client_ip == folder or client_ip in ("127.0.0.1", "::1")
            files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
            files.sort()
            items = []
            for file_name in files:
                item = {"url": f"/uploads/{folder}/{quote(file_name)}", "label": file_name}
                if can_delete:
                    item["delete_url"] = f"/uploads/{folder}/{quote(file_name)}/delete"
                    item["delete_message"] = "Delete this file?"
                items.append(item)
            breadcrumb = f'<a href="/">Home</a> / <a href="/uploads">Uploads</a> / {folder}'
            return render_uploads_page(folder, breadcrumb, items, list_class="card-list files")

        if pin_service.folder_has_pin(folder) and not pin_service.is_folder_unlocked(folder):
            return redirect(url_for("pin_entry", folder=folder, next=request.url))

        file_path = safe_upload_path(*parts)
        if file_path is None or not os.path.isfile(file_path):
            return "Not found", 404

        preview_mode = request.args.get("preview") == "1"
        guessed_mimetype = mimetypes.guess_type(os.path.basename(file_path))[0] or "application/octet-stream"

        if pin_service.folder_has_encryption(folder):
            fernet = pin_service.get_fek_for_folder(folder)
            if fernet:
                try:
                    ciphertext = pathlib.Path(file_path).read_bytes()
                    plaintext = fernet.decrypt(ciphertext)
                    return send_file(
                        BytesIO(plaintext),
                        as_attachment=not preview_mode,
                        download_name=os.path.basename(file_path),
                        mimetype=guessed_mimetype,
                    )
                except Exception:
                    return "Decryption failed", 500
        return send_file(
            file_path,
            as_attachment=not preview_mode,
            download_name=os.path.basename(file_path),
            mimetype=guessed_mimetype,
        )

    @app.route("/", methods=["GET", "POST"])
    def upload_file():
        uploader_ip = str(get_client_ip())
        upload_dir = pathlib.Path(app.config["UPLOAD_FOLDER"], uploader_ip)

        if request.method == "POST":
            if "file" not in request.files:
                flash("No file part")
                return redirect(request.url)
            files = request.files.getlist("file")
            if not len(files):
                flash("No selected file")
                return redirect(request.url)
            if files:
                upload_dir.mkdir(parents=True, exist_ok=True)
                folder_name = uploader_ip
                if pin_service.folder_has_encryption(folder_name) and not pin_service.get_fek_for_folder(folder_name):
                    flash("Open your folder and enter PIN first to upload encrypted files.")
                    return redirect(request.url)
                fernet = pin_service.get_fek_for_folder(folder_name) if pin_service.folder_has_encryption(folder_name) else None
                for file in files:
                    filename = secure_filename(file.filename)
                    content = file.read()
                    out_path = upload_dir / filename
                    if fernet:
                        out_path.write_bytes(fernet.encrypt(content))
                    else:
                        out_path.write_bytes(content)
                return redirect(url_for("upload_file", name=filename))
        return render_home_page(uploader_ip)
