import os
import shutil
from urllib.parse import quote
from flask import Flask, flash, request, redirect, url_for, send_file
from flask_sock import Sock
from werkzeug.utils import secure_filename
import sys
import pathlib


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
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
sock = Sock(app)


@sock.route('/websocket')
def websocket(ws):
    while True:
        try:
            data = ws.receive()
            if data is None:
                break
            ws.send(data)
        except Exception:
            break


def allowed_file(filename):
    return True


def _safe_upload_path(*parts):
    base = os.path.abspath(app.config["UPLOAD_FOLDER"])
    path = os.path.abspath(os.path.join(base, *parts))
    return path if path.startswith(base) and os.path.exists(path) else None


UPLOADS_PAGE_STYLE = """
    * { box-sizing: border-box; }
    body {
        font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
        margin: 0;
        min-height: 100vh;
        background: linear-gradient(145deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        color: #e8e8e8;
        padding: 2rem;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }
    .uploads-wrap { max-width: 640px; width: 100%; margin-top: -20rem; }
    h1 {
        font-size: 1.75rem;
        font-weight: 600;
        margin: 0 0 0.5rem 0;
        color: #fff;
    }
    .breadcrumb {
        margin-bottom: 1.5rem;
        font-size: 0.9rem;
        opacity: 0.85;
    }
    .breadcrumb a { color: #7dd3fc; text-decoration: none; }
    .breadcrumb a:hover { text-decoration: underline; }
    .card-list { list-style: none; padding: 0; margin: 0; }
    .card-list li { margin-bottom: 0.5rem; }
    .card-list a {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.85rem 1rem;
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 10px;
        color: #e8e8e8;
        text-decoration: none;
        font-size: 1rem;
        transition: background 0.2s, border-color 0.2s;
    }
    .card-list a:hover {
        background: rgba(255,255,255,0.12);
        border-color: rgba(125, 211, 252, 0.4);
    }
    .card-list a::before {
        content: '';
        width: 24px;
        height: 24px;
        flex-shrink: 0;
        background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%237dd3fc'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z'/%3E%3C/svg%3E") center/contain no-repeat;
    }
    .card-list.files a::before {
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%234ade80'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z'/%3E%3C/svg%3E");
    }
    .card-list li.file-row {
        position: relative;
        list-style: none;
    }
    .card-list li.file-row > a {
        padding-right: 3.25rem;
    }
    .delete-form {
        position: absolute;
        right: 0.5rem;
        top: 50%;
        transform: translateY(-50%);
        margin: 0;
        display: inline-flex;
    }
    .delete-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2rem;
        height: 2rem;
        padding: 0;
        border: none;
        border-radius: 8px;
        background: rgba(255,255,255,0.06);
        color: #e8e8e8;
        cursor: pointer;
        transition: background 0.2s, color 0.2s;
    }
    .delete-btn:hover { background: rgba(239, 68, 68, 0.4); color: #fca5a5; }
    .delete-btn svg { width: 1.1rem; height: 1.1rem; }
    .empty { opacity: 0.8; font-size: 1rem; }
    .modal-overlay {
        display: none;
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.6);
        align-items: center;
        justify-content: center;
        z-index: 1000;
        padding: 1rem;
    }
    .modal-overlay.is-open { display: flex; }
    .modal-card {
        background: linear-gradient(145deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 16px;
        padding: 1.5rem;
        max-width: 360px;
        width: 100%;
        box-shadow: 0 20px 50px rgba(0,0,0,0.4);
    }
    .modal-card h2 {
        margin: 0 0 1rem 0;
        font-size: 1.15rem;
        font-weight: 600;
        color: #fff;
    }
    .modal-actions {
        display: flex;
        gap: 0.75rem;
        justify-content: flex-end;
        margin-top: 1.25rem;
    }
    .modal-btn {
        padding: 0.5rem 1.25rem;
        border-radius: 10px;
        font-size: 0.95rem;
        font-weight: 600;
        cursor: pointer;
        border: 1px solid transparent;
        transition: background 0.2s, border-color 0.2s, color 0.2s;
    }
    .modal-btn-cancel {
        background: rgba(255,255,255,0.08);
        color: #e8e8e8;
        border-color: rgba(255,255,255,0.15);
    }
    .modal-btn-cancel:hover { background: rgba(255,255,255,0.14); color: #fff; }
    .modal-btn-delete {
        background: rgba(239, 68, 68, 0.25);
        color: #fca5a5;
        border-color: rgba(239, 68, 68, 0.5);
    }
    .modal-btn-delete:hover { background: rgba(239, 68, 68, 0.4); color: #fecaca; }
    .site-nav {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 1.25rem;
        padding: 0.75rem 0;
        margin-top: 1.25rem;
        margin-bottom: 1.5rem;
        border-bottom: 1px solid rgba(255,255,255,0.15);
    }
    .site-nav a {
        color: #e8e8e8;
        text-decoration: none;
        font-weight: 600;
        font-size: 1rem;
        padding: 0.4rem 0;
    }
    .site-nav a:hover { color: #7dd3fc; }
    .site-nav a.active { color: #7dd3fc; }
    .site-nav a { display: inline-flex; align-items: center; gap: 0.4rem; }
    .site-nav .nav-icon { width: 1.1rem; height: 1.1rem; flex-shrink: 0; }
    .site-nav .nav-logo { height: 2rem; width: auto; display: block; margin-right: 0.5rem; }
"""
GIPHY_LOGO_URL = "https://media2.giphy.com/media/QssGEmpkyEOhBCb7e1/giphy.gif?cid=ecf05e47a0n3gi1bfqntqmob8g9aid1oyj2wr3ds3mg700bl&rid=giphy.gif"
FAVICON_LINK = '<link rel="icon" href="' + GIPHY_LOGO_URL.replace("&", "&amp;") + '" type="image/gif">'
NAV_LOGO = '<a href="/" class="nav-logo-link"><img src="' + GIPHY_LOGO_URL + '" alt="Logo" class="nav-logo"></a>'
HOME_ICON = '<svg class="nav-icon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg>'
UPLOADS_ICON = '<svg class="nav-icon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>'
NAV_HTML = '<nav class="site-nav">' + NAV_LOGO + '<a href="/">' + HOME_ICON + 'Home</a><a href="/uploads">' + UPLOADS_ICON + 'Uploads</a></nav>'
NAV_HTML_HOME_ACTIVE = '<nav class="site-nav">' + NAV_LOGO + '<a href="/" class="active">' + HOME_ICON + 'Home</a><a href="/uploads">' + UPLOADS_ICON + 'Uploads</a></nav>'
NAV_HTML_UPLOADS_ACTIVE = '<nav class="site-nav">' + NAV_LOGO + '<a href="/">' + HOME_ICON + 'Home</a><a href="/uploads" class="active">' + UPLOADS_ICON + 'Uploads</a></nav>'


def _uploads_html(title, breadcrumb_html, items, list_class="card-list", nav_html=None):
    if nav_html is None:
        nav_html = NAV_HTML_UPLOADS_ACTIVE
    if items:
        bin_svg = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>'
        list_items = []
        for item in items:
            li_class = ' class="file-row"' if item.get("delete_url") else ""
            link = f'<a href="{item["url"]}">{item["label"]}</a>'
            if item.get("delete_url"):
                msg = item.get("delete_message", "Delete?")
                link += f'<form method="post" action="{item["delete_url"]}" class="delete-form js-delete-form" data-confirm-message="{msg}"><button type="button" class="delete-btn js-delete-trigger" aria-label="Delete">{bin_svg}</button></form>'
            list_items.append(f'<li{li_class}>{link}</li>')
        body = f'<ul class="{list_class}">{"".join(list_items)}</ul>'
    else:
        body = '<p class="empty">No items here yet.</p>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    {FAVICON_LINK}
    <title>{title}</title>
    <style>{UPLOADS_PAGE_STYLE}</style>
</head>
<body>
    <div class="uploads-wrap">
        {nav_html}
        <nav class="breadcrumb">{breadcrumb_html}</nav>
        <h1>{title}</h1>
        {body}
    </div>
    <div id="delete-modal" class="modal-overlay" aria-hidden="true">
        <div class="modal-card">
            <h2 class="js-modal-title">Delete this file?</h2>
            <div class="modal-actions">
                <button type="button" class="modal-btn modal-btn-cancel js-modal-cancel">Cancel</button>
                <button type="button" class="modal-btn modal-btn-delete js-modal-delete">Delete</button>
            </div>
        </div>
    </div>
    <script>
    (function(){{
        var modal = document.getElementById("delete-modal");
        var cancelBtn = document.querySelector(".js-modal-cancel");
        var deleteBtn = document.querySelector(".js-modal-delete");
        var pendingForm = null;
        document.querySelectorAll(".js-delete-trigger").forEach(function(btn){{
            btn.addEventListener("click", function(){{
                pendingForm = this.closest("form");
                if (pendingForm && modal) {{
                    var titleEl = modal.querySelector(".js-modal-title");
                    if (titleEl) titleEl.textContent = pendingForm.getAttribute("data-confirm-message") || "Delete?";
                    modal.classList.add("is-open");
                    modal.setAttribute("aria-hidden", "false");
                }}
            }});
        }});
        function closeModal(){{
            modal.classList.remove("is-open");
            modal.setAttribute("aria-hidden", "true");
            pendingForm = null;
        }}
        if (cancelBtn) cancelBtn.addEventListener("click", closeModal);
        if (deleteBtn) deleteBtn.addEventListener("click", function(){{
            if (pendingForm) {{ pendingForm.submit(); }}
            closeModal();
        }});
        if (modal) modal.addEventListener("click", function(e){{
            if (e.target === modal) closeModal();
        }});
    }})();
    </script>
</body>
</html>"""


@app.route("/uploads", methods=["GET"])
@app.route("/uploads/<path:subpath>", methods=["GET", "POST"])
def list_or_download_uploads(subpath=None):
    if not subpath:
        # List folders: date_IP
        base = app.config["UPLOAD_FOLDER"]
        if not os.path.isdir(base):
            return _uploads_html(
                "Uploads",
                '<a href="/">Home</a> / Uploads',
                [],
            )
        folders = [
            d for d in os.listdir(base)
            if os.path.isdir(os.path.join(base, d))
        ]
        folders.sort(reverse=True)
        client_ip = get_client_ip().strip()
        items = []
        for f in folders:
            item = {"url": f"/uploads/{quote(f)}", "label": f}
            if client_ip == f or client_ip in ("127.0.0.1", "::1"):
                item["delete_url"] = f"/uploads/{quote(f)}/delete-folder"
                item["delete_message"] = "Delete this folder and all its files?"
            items.append(item)
        return _uploads_html(
            "Uploads",
            '<a href="/">Home</a> / Uploads',
            items,
        )
    parts = subpath.strip("/").split("/")
    folder = parts[0]
    path = _safe_upload_path(folder)
    if path is None:
        return "Not found", 404
    # POST .../delete-folder: only folder owner can delete their folder
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
        return redirect(url_for("list_or_download_uploads"))
    # POST .../delete: only folder owner can delete a file
    if request.method == "POST" and len(parts) >= 2 and parts[-1] == "delete":
        client_ip = get_client_ip().strip()
        if client_ip != folder and client_ip not in ("127.0.0.1", "::1"):
            return "Forbidden: you can only delete your own files.", 403
        filename = "/".join(parts[1:-1])  # in case filename contains /
        file_path = _safe_upload_path(folder, filename)
        if file_path is None or not os.path.isfile(file_path):
            return "Not found", 404
        try:
            os.remove(file_path)
        except OSError:
            return "Could not delete file.", 500
        return redirect(url_for("list_or_download_uploads", subpath=folder))
    if len(parts) == 1:
        # List files in folder; only folder owner (IP matches folder name) can delete
        if not os.path.isdir(path):
            return "Not found", 404
        client_ip = get_client_ip().strip()
        can_delete = (client_ip == folder or client_ip in ("127.0.0.1", "::1"))
        files = [
            f for f in os.listdir(path)
            if os.path.isfile(os.path.join(path, f))
        ]
        files.sort()
        items = []
        for f in files:
            item = {"url": f"/uploads/{folder}/{quote(f)}", "label": f}
            if can_delete:
                item["delete_url"] = f"/uploads/{folder}/{quote(f)}/delete"
                item["delete_message"] = "Delete this file?"
            items.append(item)
        breadcrumb = f'<a href="/">Home</a> / <a href="/uploads">Uploads</a> / {folder}'
        return _uploads_html(
            folder,
            breadcrumb,
            items,
            list_class="card-list files",
        )
    # Download file: /uploads/folder/filename
    file_path = _safe_upload_path(*parts)
    if file_path is None or not os.path.isfile(file_path):
        return "Not found", 404
    return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))


@app.route('/', methods=['GET', 'POST'])
def upload_file():
    uploader_ip = str(get_client_ip())
    upload_dir = pathlib.Path(app.config['UPLOAD_FOLDER'], uploader_ip)

    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        files = request.files.getlist("file")
        if not len(files):
            flash('No selected file')
            return redirect(request.url)
        if files:
            upload_dir.mkdir(parents=True, exist_ok=True)
            for file in files:
                filename = secure_filename(file.filename)
                file.save(upload_dir / filename)
            return redirect(url_for('upload_file', name=filename))
    return '''
    <!doctype html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="icon" href="https://media2.giphy.com/media/QssGEmpkyEOhBCb7e1/giphy.gif?cid=ecf05e47a0n3gi1bfqntqmob8g9aid1oyj2wr3ds3mg700bl&amp;rid=giphy.gif" type="image/gif">
    <title>Upload new File</title>
    <style>
    * { box-sizing: border-box; }
    body {
        font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
        margin: 0;
        min-height: 100vh;
        background: linear-gradient(145deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        color: #e8e8e8;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 1rem;
        overflow-x: hidden;
    }
    .home-wrap {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        margin-top: -21rem;
        max-width: 100%;
        width: 100%;
    }
    .site-nav {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        align-items: center;
        gap: 1rem;
        padding: 0.75rem clamp(1rem, 4vw, 2rem);
        margin-top: 1.25rem;
        margin-bottom: 0;
        border-bottom: 1px solid rgba(255,255,255,0.15);
        width: 100%;
        max-width: 640px;
    }
    .site-nav a {
        color: #e8e8e8;
        text-decoration: none;
        font-weight: 600;
        font-size: clamp(0.875rem, 2.5vw, 1rem);
    }
    .site-nav a:hover { color: #7dd3fc; }
    .site-nav a.active { color: #7dd3fc; }
    .site-nav a { display: inline-flex; align-items: center; gap: 0.4rem; }
    .site-nav .nav-icon { width: 1.1rem; height: 1.1rem; flex-shrink: 0; }
    .site-nav .nav-logo-link { margin-right: 0.25rem; }
    .site-nav .nav-logo { height: 2rem; width: auto; display: block; max-height: 2rem; }
    input[type="file"] { display: none; }
    input[type="submit"] { display: none; }
    .custom-file-upload {
        border: 1px solid rgba(255,255,255,0.12);
        background: rgba(255,255,255,0.05);
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.75rem;
        padding: 1.25rem 2rem;
        cursor: pointer;
        min-width: 180px;
        border-radius: 16px;
        margin: 8px;
        font-size: clamp(1rem, 2.5vw, 1.25rem);
        font-weight: 600;
        color: #e8e8e8;
        transition: background 0.2s, border-color 0.2s, color 0.2s, box-shadow 0.2s, transform 0.2s;
        box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        border-left: 4px solid transparent;
    }
    .custom-file-upload:hover {
        background: rgba(255,255,255,0.1);
        border-color: rgba(125, 211, 252, 0.35);
        border-left-color: #7dd3fc;
        color: #7dd3fc;
        box-shadow: 0 8px 28px rgba(0,0,0,0.25);
        transform: translateY(-2px);
    }
    .custom-file-upload .btn-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }
    .custom-file-upload .btn-icon svg { width: 1.35rem; height: 1.35rem; }
    .upload:hover { background: rgba(125, 211, 252, 0.12); border-left-color: #7dd3fc; color: #7dd3fc; }
    #body {
        visibility: hidden;
        min-height: 100vh;
        min-height: 100dvh;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        gap: clamp(1rem, 4vw, 2rem);
        position: fixed;
        inset: 0;
        background: linear-gradient(145deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 1rem;
        box-sizing: border-box;
    }
    .progress-wrap {
        width: 100%;
        max-width: min(90vw, 360px);
        margin: 0 auto;
        padding: 0 0.25rem;
    }
    .progress-wrap .label {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 0.5rem;
        font-size: clamp(0.875rem, 2.5vw, 0.95rem);
        color: #e8e8e8;
    }
    .progress-track {
        height: clamp(8px, 2.5vw, 12px);
        background: rgba(255,255,255,0.12);
        border-radius: 999px;
        overflow: hidden;
    }
    .progress-bar {
        height: 100%;
        width: 0%;
        background: linear-gradient(90deg, #7dd3fc, #38bdf8);
        border-radius: 999px;
        transition: width 0.15s ease-out;
    }
    .main {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        align-items: center;
        margin-top: 2rem;
        gap: 0.5rem;
        width: 100%;
        max-width: 100%;
    }
    ul { position: absolute; color: #e8e8e8; font-size: clamp(0.75rem, 2vw, 1rem); }
    .spinner {
        --t: 2500ms;
        --animation: rotate var(--t) linear infinite;
        --animation2: scale var(--t) linear infinite alternate;
        position: relative;
        width: clamp(6rem, 20vw, 10rem);
        height: clamp(6rem, 20vw, 10rem);
        display: flex;
        justify-content: center;
        align-items: center;
        animation: var(--animation), var(--animation2);
    }
    .spinner::before, .spinner::after { content: ''; position: absolute; }
    .spinner::before {
        inset: 0;
        border: 3px solid #7dd3fc;
        border-radius: 50%;
        mask-image: conic-gradient(transparent 10%, black);
        animation: borderScale var(--t) linear infinite alternate;
    }
    .spinner::after {
        --r: 45deg;
        --scale: 2;
        width: 20%;
        height: 20%;
        background:
            radial-gradient(circle at 30% 35%, #e8e8e8 3px, transparent 0),
            radial-gradient(circle at 70% 35%, #e8e8e8 3px, transparent 0),
            radial-gradient(circle at top center, #e8e8e8 6px, transparent 0),
            #7dd3fc;
        background-position: 0 0, 0 0, 0 1.25rem;
        top: 0;
        translate: 0 -50%;
        rotate: 45deg;
        animation: var(--animation) reverse, var(--animation2);
        border-radius: 20%;
    }
    @keyframes rotate { to { rotate: calc(360deg + var(--r, 0deg)); } }
    @keyframes scale { to { scale: var(--scale, 0.5); } }
    @keyframes borderScale { to { border: 6px solid #7dd3fc; } }
    @media screen and (min-width: 1000px) {
        .custom-file-upload {
            min-width: 220px;
            padding: 1.5rem 2.25rem;
            font-size: 1.2rem;
        }
    }
    @media screen and (max-width: 600px) {
        .home-wrap { margin-top: -4rem; }
        .site-nav { gap: 0.75rem; padding: 0.5rem 1rem; }
        .site-nav .nav-logo { height: 1.5rem; }
        .custom-file-upload {
            min-width: 140px;
            padding: 1rem 1.5rem;
            font-size: clamp(0.9rem, 3.5vw, 1.1rem);
        }
        .main { margin-top: 1.5rem; }
        #body .spinner { width: clamp(5rem, 22vw, 8rem); height: clamp(5rem, 22vw, 8rem); }
        .progress-wrap { max-width: 94vw; }
    }
    @media screen and (max-width: 380px) {
        body { padding: 0.5rem; }
        .custom-file-upload {
            min-width: 120px;
            padding: 0.85rem 1.25rem;
            margin: 6px;
            font-size: clamp(0.8rem, 3vw, 1rem);
        }
        .main { flex-direction: column; }
        #body { padding: 0.75rem; }
        #body .spinner { width: 4.5rem; height: 4.5rem; }
        .progress-wrap .label { font-size: 0.8125rem; }
    }
    @media screen and (max-width: 1000px) {
        .spinner::after {
            --r: 45deg;
            --scale: 2;
            width: 20%;
            height: 20%;
            background: radial-gradient(circle at 30% 50%, #e8e8e8 8px, transparent 0), radial-gradient(circle at 70% 50%, #e8e8e8 8px, transparent 0), radial-gradient(circle at 50% -3%, #e8e8e8 28px, transparent 0), #7dd3fc;
            background-position: 0 0, 0 0, 0 1.25rem;
            top: 0;
            translate: 0 -50%;
            rotate: 45deg;
            animation: var(--animation) reverse, var(--animation2);
            border-radius: 20%;
        }
        .spinner {
            --t: 2500ms;
            width: 40rem;
            height: 40rem;
            display: flex;
            justify-content: center;
            align-items: center;
            animation: var(--animation), var(--animation2);
        }
        .spinner::before {
            inset: 0;
            border: 3px solid #7dd3fc;
            border-radius: 50%;
            mask-image: conic-gradient(transparent 10%, black);
            animation: borderScale var(--t) linear infinite alternate;
        }
    }
    </style>
    </head>
    <body>
    <div class="home-wrap">
    <nav class="site-nav"><a href="/" class="nav-logo-link"><img src="https://media2.giphy.com/media/QssGEmpkyEOhBCb7e1/giphy.gif?cid=ecf05e47a0n3gi1bfqntqmob8g9aid1oyj2wr3ds3mg700bl&amp;rid=giphy.gif" alt="Logo" class="nav-logo"></a><a href="/" class="active"><svg class="nav-icon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg>Home</a><a href="/uploads"><svg class="nav-icon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>Uploads</a></nav>
    <div class="main">
    <form method=post enctype=multipart/form-data>
        <input id="k-upload" onchange="enablethis(this)" class="files" type="file" name="file" multiple>
        <label for="k-upload" class="custom-file-upload">
            <span class="btn-icon" aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg></span>Select Files
        </label>


        <input onclick="transit()" id="file-upload" class="submiter" disabled type=submit value="Upload">
        <label for="file-upload" class="custom-file-upload upload">
            <span class="btn-icon" aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg></span>Upload
        </label>
    </form>
    <div>
    <ul id="is">
    </ul>
    </div>

    </div>
    </div>
    <div id="body">
        <div class="progress-wrap">
            <div class="label"><span id="progress-label">Uploading…</span><span id="progress-pct">0%</span></div>
            <div class="progress-track"><div class="progress-bar" id="progress-bar"></div></div>
        </div>
        <div class="spinner"></div>
    </div>
    <script>
    function transit(){
        document.getElementById("body").style.visibility = "visible";
        document.getElementById("progress-bar").style.width = "0%";
        document.getElementById("progress-pct").textContent = "0%";
        document.getElementById("progress-label").textContent = "Uploading…";
    }
    function enablethis(e){
        var uploadBtn = document.getElementsByClassName("upload")[0];
        uploadBtn.style.background = "rgba(125, 211, 252, 0.2)";
        uploadBtn.style.borderLeftColor = "#7dd3fc";
        document.getElementsByClassName("submiter")[0].removeAttribute("disabled");
        let ul = document.getElementById("is");
        const li = text => {
            var l = document.createElement('li');
            l.innerText = text;
            return l;
        };
        [...e.files].forEach( el => {
            ul.appendChild(li(el.name));
        });
    }
    (function(){
        var form = document.querySelector('form[method=post][enctype*=multipart]');
        if (!form) return;
        form.addEventListener('submit', function(ev){
            ev.preventDefault();
            transit();
            var fd = new FormData(form);
            var xhr = new XMLHttpRequest();
            var bar = document.getElementById("progress-bar");
            var pct = document.getElementById("progress-pct");
            var label = document.getElementById("progress-label");
            xhr.upload.addEventListener('progress', function(e){
                if (e.lengthComputable) {
                    var percent = Math.round((e.loaded / e.total) * 100);
                    bar.style.width = percent + "%";
                    pct.textContent = percent + "%";
                } else {
                    pct.textContent = "...";
                }
            });
            xhr.addEventListener('load', function(){
                if (xhr.status >= 200 && xhr.status < 300) {
                    label.textContent = "Done!";
                    bar.style.width = "100%";
                    pct.textContent = "100%";
                    setTimeout(function(){ window.location.href = "/"; }, 600);
                } else {
                    label.textContent = "Upload failed";
                    setTimeout(function(){ document.getElementById("body").style.visibility = "hidden"; }, 2000);
                }
            });
            xhr.addEventListener('error', function(){
                label.textContent = "Upload failed";
                setTimeout(function(){ document.getElementById("body").style.visibility = "hidden"; }, 2000);
            });
            xhr.open('POST', form.action || '/');
            xhr.send(fd);
        });
    })();
    </script>
    </body>
    </html>
    '''


DEFAULT_PORT = 8069

if __name__ == "__main__":
    if len(sys.argv) == 1:
        app.run(host="0.0.0.0", port=DEFAULT_PORT)
    elif sys.argv[-1] == "80":
        app.run(host="0.0.0.0", port=80)
    elif sys.argv[-1] == "help":
        print("\nExamples:\n\tDev: python server.py\n\tDeploy: python server.py 80\n\tDeploy custom port: python server.py <9598>\n\n")
    else:
        try:
            port = int(sys.argv[-1])
            app.run(host="0.0.0.0", port=port)
        except (ValueError, OSError):
            print("Cannot open port", sys.argv[-1])
            print("Running on localhost:" + str(DEFAULT_PORT))
            app.run(port=DEFAULT_PORT)
