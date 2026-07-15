import os
import pathlib
import shutil
import mimetypes
from io import BytesIO
from urllib.parse import quote

from flask import flash, redirect, request, send_file, url_for

from inert_transfer.upload_handler import (
    build_directory_listing_items,
    build_uploads_breadcrumb,
    is_archive_filename,
    process_upload_batch,
    read_stored_file_bytes,
    remove_bundle_artifacts,
)


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

        if request.method == "POST" and parts[-1] == "delete-folder":
            client_ip = get_client_ip().strip()
            if client_ip != folder and client_ip not in ("127.0.0.1", "::1"):
                return "Forbidden: you can only delete your own folder.", 403
            if len(parts) == 2:
                if not os.path.isdir(path):
                    return "Not found", 404
                try:
                    shutil.rmtree(path)
                except OSError:
                    return "Could not delete folder.", 500
                if not pin_service.remove_folder_details(folder):
                    return "Folder deleted, but failed to remove PIN details.", 500
                return redirect(url_for("list_or_download_uploads"))
            sub_rel = "/".join(parts[1:-1])
            sub_path = safe_upload_path(folder, sub_rel)
            if sub_path is None or not os.path.isdir(sub_path):
                return "Not found", 404
            try:
                shutil.rmtree(sub_path)
                bundle_zip = os.path.join(os.path.dirname(sub_path), os.path.basename(sub_path) + ".zip")
                if os.path.isfile(bundle_zip):
                    os.remove(bundle_zip)
            except OSError:
                return "Could not delete folder.", 500
            parent_parts = parts[1:-2]
            if parent_parts:
                return redirect(
                    url_for("list_or_download_uploads", subpath=f"{folder}/{'/'.join(parent_parts)}")
                )
            return redirect(url_for("list_or_download_uploads", subpath=folder))

        if len(parts) >= 3 and parts[-1] == "download":
            file_rel = "/".join(parts[1:-1])
            file_path = safe_upload_path(folder, file_rel)
            if file_path is None or not os.path.isfile(file_path):
                return "Not found", 404
            if pin_service.folder_has_pin(folder) and not pin_service.is_folder_unlocked(folder):
                return redirect(url_for("pin_entry", folder=folder, next=request.url))
            download_name = os.path.basename(file_path)
            is_archive = is_archive_filename(download_name)
            mimetype = (
                "application/octet-stream"
                if is_archive
                else (mimetypes.guess_type(download_name)[0] or "application/octet-stream")
            )
            fernet = None
            if pin_service.folder_has_encryption(folder):
                fernet = pin_service.get_fek_for_folder(folder)
                if not fernet:
                    return "Enter PIN to download encrypted uploads.", 403
                try:
                    payload = read_stored_file_bytes(pathlib.Path(file_path), fernet)
                except Exception:
                    return "Decryption failed", 500
                return send_file(
                    BytesIO(payload),
                    mimetype=mimetype,
                    as_attachment=True,
                    download_name=download_name,
                    conditional=False,
                    etag=False,
                )
            return send_file(
                file_path,
                mimetype=mimetype,
                as_attachment=True,
                download_name=download_name,
                conditional=False,
                etag=False,
            )

        if request.method == "POST" and len(parts) >= 2 and parts[-1] == "delete":
            client_ip = get_client_ip().strip()
            if client_ip != folder and client_ip not in ("127.0.0.1", "::1"):
                return "Forbidden: you can only delete your own files.", 403
            filename = "/".join(parts[1:-1])
            file_path = safe_upload_path(folder, filename)
            if file_path is None or not os.path.isfile(file_path):
                return "Not found", 404
            try:
                filename_base = os.path.basename(filename)
                if is_archive_filename(filename_base):
                    remove_bundle_artifacts(pathlib.Path(app.config["UPLOAD_FOLDER"], folder), filename_base)
                else:
                    os.remove(file_path)
            except OSError:
                return "Could not delete file.", 500
            return redirect(url_for("list_or_download_uploads", subpath=folder))

        def _render_directory_listing(disk_path, rel_inside, page_title):
            if pin_service.folder_has_pin(folder) and not pin_service.is_folder_unlocked(folder):
                next_url = url_for("list_or_download_uploads", subpath="/".join(parts))
                return redirect(url_for("pin_entry", folder=folder, next=next_url))
            client_ip = get_client_ip().strip()
            can_delete = client_ip == folder or client_ip in ("127.0.0.1", "::1")
            sort = request.args.get("sort", "-mtime")
            if sort not in {"name", "-name", "size", "-size", "mtime", "-mtime"}:
                sort = "-mtime"
            items = build_directory_listing_items(
                pathlib.Path(disk_path),
                folder,
                rel_inside,
                can_delete,
            )
            reverse = sort.startswith("-")
            key = sort[1:] if reverse else sort

            def _sort_key(entry):
                if key == "name":
                    return (0 if entry.get("is_bundle") else 1, (entry["label"] or "").lower())
                return (0 if entry.get("is_bundle") else 1, entry.get(key, 0))

            items.sort(key=_sort_key, reverse=reverse)
            rel_parts = rel_inside.split("/") if rel_inside else []
            breadcrumb = build_uploads_breadcrumb(folder, rel_parts)
            return render_uploads_page(
                page_title,
                breadcrumb,
                items,
                list_class="files-table",
                current_sort=sort,
            )

        if len(parts) == 1:
            if not os.path.isdir(path):
                return render_folder_not_found_page(), 404
            return _render_directory_listing(path, "", folder)

        inner_path = safe_upload_path(*parts)
        if inner_path is not None and os.path.isdir(inner_path):
            sidecar_zip = os.path.join(os.path.dirname(inner_path), os.path.basename(inner_path) + ".zip")
            if os.path.isfile(sidecar_zip):
                return redirect(
                    url_for(
                        "list_or_download_uploads",
                        subpath=f"{folder}/{quote(os.path.basename(sidecar_zip))}",
                    )
                )
            return "Not found", 404

        if pin_service.folder_has_pin(folder) and not pin_service.is_folder_unlocked(folder):
            return redirect(url_for("pin_entry", folder=folder, next=request.url))

        file_path = safe_upload_path(*parts)
        if file_path is None or not os.path.isfile(file_path):
            return "Not found", 404

        download_name = os.path.basename(file_path)
        if is_archive_filename(download_name):
            return redirect(
                url_for(
                    "list_or_download_uploads",
                    subpath=f"{folder}/{'/'.join(parts[1:])}/download",
                )
            )

        preview_mode = request.args.get("preview") == "1"
        guessed_mimetype = mimetypes.guess_type(download_name)[0] or "application/octet-stream"
        fernet = None
        if pin_service.folder_has_encryption(folder):
            fernet = pin_service.get_fek_for_folder(folder)
            if not fernet:
                return "Enter PIN to download encrypted uploads.", 403
            try:
                payload = read_stored_file_bytes(pathlib.Path(file_path), fernet)
            except Exception:
                return "Decryption failed", 500
            return send_file(
                BytesIO(payload),
                as_attachment=not preview_mode,
                download_name=download_name,
                mimetype=guessed_mimetype,
                conditional=False,
                etag=False,
            )
        return send_file(
            file_path,
            as_attachment=not preview_mode,
            download_name=download_name,
            mimetype=guessed_mimetype,
            conditional=False,
            etag=False,
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
                items = []
                last_name = None
                for file in files:
                    if not file or not file.filename:
                        continue
                    last_name = file.filename
                    items.append((file.filename, file.read()))
                if not items:
                    flash("No selected file")
                    return redirect(request.url)
                process_upload_batch(upload_dir, items, fernet)
                redirect_name = last_name.split("/")[-1].split("\\")[-1] if last_name else ""
                return redirect(url_for("upload_file", name=redirect_name))
        return render_home_page(uploader_ip)
