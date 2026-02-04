import os
import shutil
import json
import base64
from io import BytesIO
from urllib.parse import quote
import sys
import pathlib

# Windows: prevent Werkzeug from using socket.fromfd (not supported on Windows).
# Otherwise a leftover WERKZEUG_RUN_MAIN / WERKZEUG_SERVER_FD can trigger WinError 10038.
if sys.platform == "win32":
    os.environ.pop("WERKZEUG_RUN_MAIN", None)
    os.environ.pop("WERKZEUG_SERVER_FD", None)

from flask import Flask, flash, request, redirect, url_for, send_file, session, Response
from flask_sock import Sock
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


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

# --- Folder PIN protection + per-folder encryption (FEK protected by PIN/KEK) ---
PBKDF2_ITERATIONS = 100_000
SALT_LENGTH = 16


def _pins_path():
    base = os.path.abspath(app.config["UPLOAD_FOLDER"])
    return os.path.join(base, ".folder_pins.json")


def _load_pins():
    path = _pins_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_pins(pins):
    path = _pins_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pins, f)
        return True
    except OSError:
        return False


def _get_pin_record(folder_name):
    pins = _load_pins()
    return pins.get(folder_name)


def folder_has_pin(folder_name):
    rec = _get_pin_record(folder_name)
    if rec is None:
        return False
    if isinstance(rec, str):
        return bool(rec)
    return bool(rec.get("hash"))


def folder_has_encryption(folder_name):
    rec = _get_pin_record(folder_name)
    return isinstance(rec, dict) and rec.get("encrypted_fek")


def _derive_kek(pin_clean, salt_b64):
    salt = base64.b64decode(salt_b64)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    key_bytes = kdf.derive(pin_clean.encode("utf-8"))
    return base64.urlsafe_b64encode(key_bytes).decode("ascii")


def _decrypt_fek(encrypted_fek_b64, kek_b64):
    fernet_kek = Fernet(kek_b64.encode("ascii"))
    return fernet_kek.decrypt(base64.b64decode(encrypted_fek_b64))


def _encrypt_fek(fek_bytes, kek_b64):
    fernet_kek = Fernet(kek_b64.encode("ascii"))
    return base64.b64encode(fernet_kek.encrypt(fek_bytes)).decode("ascii")


def _session_folder_keys():
    return session.get("folder_keys") or {}


def _set_session_fek(folder_name, fek_b64):
    keys = dict(_session_folder_keys())
    keys[folder_name] = fek_b64
    session["folder_keys"] = keys


def _clear_session_fek(folder_name):
    keys = dict(_session_folder_keys())
    keys.pop(folder_name, None)
    session["folder_keys"] = keys


def get_fek_for_folder(folder_name):
    fek_b64 = _session_folder_keys().get(folder_name)
    if not fek_b64:
        return None
    try:
        return Fernet(fek_b64.encode("ascii"))
    except Exception:
        return None


def _folder_path(folder_name):
    return pathlib.Path(app.config["UPLOAD_FOLDER"], folder_name)


def _encrypt_existing_files(folder_name, fernet):
    folder_path = _folder_path(folder_name)
    if not folder_path.is_dir():
        return
    for name in os.listdir(folder_path):
        fpath = folder_path / name
        if not fpath.is_file():
            continue
        try:
            data = fpath.read_bytes()
            encrypted = fernet.encrypt(data)
            fpath.write_bytes(encrypted)
        except Exception:
            pass


def _decrypt_existing_files(folder_name, fernet):
    folder_path = _folder_path(folder_name)
    if not folder_path.is_dir():
        return
    for name in os.listdir(folder_path):
        fpath = folder_path / name
        if not fpath.is_file():
            continue
        try:
            data = fpath.read_bytes()
            decrypted = fernet.decrypt(data)
            fpath.write_bytes(decrypted)
        except Exception:
            pass


def _get_fernet_from_current_pin(folder_name, current_pin):
    rec = _get_pin_record(folder_name)
    if not isinstance(rec, dict) or not rec.get("encrypted_fek"):
        return None
    pin_clean = (current_pin or "").strip()
    if not pin_clean:
        return None
    if not check_password_hash(rec["hash"], pin_clean):
        return None
    kek_b64 = _derive_kek(pin_clean, rec["salt"])
    try:
        fek_bytes = _decrypt_fek(rec["encrypted_fek"], kek_b64)
        fek_b64 = base64.urlsafe_b64encode(fek_bytes).decode("ascii") if isinstance(fek_bytes, bytes) else fek_bytes.decode("ascii")
        return Fernet(fek_b64.encode("ascii"))
    except Exception:
        return None


def set_folder_pin(folder_name, pin, current_pin=None):
    pins = _load_pins()
    if not pin or not pin.strip():
        rec = pins.get(folder_name)
        if rec is not None:
            if not current_pin or not (current_pin or "").strip():
                return (False, "Please enter your current PIN to remove protection.")
            if not verify_folder_pin(folder_name, current_pin):
                return (False, "Wrong PIN.")
        if isinstance(rec, dict) and rec.get("encrypted_fek"):
            fernet = get_fek_for_folder(folder_name)
            if not fernet:
                fernet = _get_fernet_from_current_pin(folder_name, current_pin)
            if not fernet:
                return (False, "Wrong PIN.")
            _decrypt_existing_files(folder_name, fernet)
        pins.pop(folder_name, None)
        _clear_session_fek(folder_name)
        return (_save_pins(pins), None)
    pin_clean = pin.strip()
    if len(pin_clean) < 4:
        return (False, "PIN must be at least 4 characters")
    rec = pins.get(folder_name)
    # When changing PIN, always verify the current PIN (legacy or new format)
    if rec is not None:
        if not current_pin or not (current_pin or "").strip():
            return (False, "Please enter your current PIN to change it.")
        if not verify_folder_pin(folder_name, current_pin):
            return (False, "Wrong current PIN.")
    if isinstance(rec, dict) and rec.get("encrypted_fek"):
        fernet_old = get_fek_for_folder(folder_name)
        if not fernet_old and current_pin:
            fernet_old = _get_fernet_from_current_pin(folder_name, current_pin)
        if not fernet_old:
            return (False, "Wrong current PIN or open the folder and enter current PIN first, then you can change PIN.")
        _decrypt_existing_files(folder_name, fernet_old)
    salt = os.urandom(SALT_LENGTH)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    kek_b64 = _derive_kek(pin_clean, salt_b64)
    fek = Fernet.generate_key()
    encrypted_fek_b64 = _encrypt_fek(fek, kek_b64)
    pin_hash = generate_password_hash(pin_clean, method="pbkdf2:sha256")
    pins[folder_name] = {
        "hash": pin_hash,
        "salt": salt_b64,
        "encrypted_fek": encrypted_fek_b64,
    }
    if not _save_pins(pins):
        return (False, "Failed to save PIN")
    fernet = Fernet(fek)
    _encrypt_existing_files(folder_name, fernet)
    _set_session_fek(folder_name, fek.decode("ascii"))
    _unlock_folder(folder_name)
    return (True, None)


def verify_folder_pin(folder_name, pin):
    rec = _get_pin_record(folder_name)
    if not rec:
        return False
    if isinstance(rec, str):
        return check_password_hash(rec, pin)
    if not check_password_hash(rec["hash"], pin):
        return False
    return True


def _unlock_folder_with_fek(folder_name, pin):
    _unlock_folder(folder_name)
    rec = _get_pin_record(folder_name)
    if not isinstance(rec, dict) or not rec.get("encrypted_fek"):
        return
    pin_clean = pin.strip()
    kek_b64 = _derive_kek(pin_clean, rec["salt"])
    try:
        fek_bytes = _decrypt_fek(rec["encrypted_fek"], kek_b64)
        fek_b64 = base64.urlsafe_b64encode(fek_bytes).decode("ascii") if isinstance(fek_bytes, bytes) else fek_bytes.decode("ascii")
        _set_session_fek(folder_name, fek_b64)
    except Exception:
        pass


def _unlocked_folders():
    return set(session.get("unlocked_folders") or [])


def _unlock_folder(folder_name):
    folders = list(_unlocked_folders())
    if folder_name not in folders:
        folders.append(folder_name)
    session["unlocked_folders"] = folders


def is_folder_unlocked(folder_name):
    return folder_name in _unlocked_folders()


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
        padding-right: 5rem;
    }
    .row-actions {
        position: absolute;
        right: 0.5rem;
        top: 50%;
        transform: translateY(-50%);
        margin: 0;
        display: flex;
        gap: 0.25rem;
        align-items: center;
    }
    .delete-form {
        margin: 0;
        display: inline-flex;
    }
    .card-list li.file-row > .delete-form {
        position: absolute;
        right: 0.5rem;
        top: 50%;
        transform: translateY(-50%);
    }
    .pin-menu-btn {
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
        font-size: 1.25rem;
        line-height: 1;
        transition: background 0.2s, color 0.2s;
    }
    .pin-menu-btn:hover { background: rgba(125, 211, 252, 0.25); color: #7dd3fc; }
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
    .lock-icon { font-size: 0.9em; opacity: 0.9; margin-right: 0.25rem; }
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
    .modal-actions-top {
        margin-top: 0;
        margin-bottom: 0.75rem;
        justify-content: flex-start;
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
    .modal-btn-primary { background: #7dd3fc; color: #1a1a2e; }
    .modal-btn-primary:hover { background: #38bdf8; color: #0f172a; }
    .pin-modal-input {
        width: 100%;
        padding: 0.6rem 0.75rem;
        border: 1px solid rgba(255,255,255,0.2);
        border-radius: 10px;
        background: rgba(0,0,0,0.2);
        color: #e8e8e8;
        font-size: 1rem;
        margin-bottom: 1rem;
    }
    .pin-modal-input:focus { outline: none; border-color: #7dd3fc; }
    .pin-modal-error { color: #fca5a5; font-size: 0.9rem; margin-bottom: 0.5rem; }
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
            li_class = ' class="file-row"' if (item.get("delete_url") or item.get("pin_menu")) else ""
            label_html = ("<span class=\"lock-icon\" title=\"Protected\" aria-hidden=\"true\">&#128274;</span> " if item.get("has_pin") else "") + item["label"]
            link = f'<a href="{item["url"]}">{label_html}</a>'
            if item.get("pin_menu"):
                folder_esc = (item.get("folder_name") or "").replace("&", "&amp;").replace('"', "&quot;")
                has_pin = "true" if item.get("has_pin") else "false"
                link += f'<span class="row-actions"><button type="button" class="pin-menu-btn js-pin-menu" data-folder="{folder_esc}" data-has-pin="{has_pin}" aria-label="Folder options">&#8230;</button>'
            if item.get("delete_url"):
                msg = item.get("delete_message", "Delete?")
                link += f'<form method="post" action="{item["delete_url"]}" class="delete-form js-delete-form" data-confirm-message="{msg}"><button type="button" class="delete-btn js-delete-trigger" aria-label="Delete">{bin_svg}</button></form>'
            if item.get("pin_menu"):
                link += "</span>"
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
    <div id="pin-modal" class="modal-overlay" aria-hidden="true">
        <div class="modal-card">
            <h2 class="js-pin-title">Set a PIN to protect your folder</h2>
            <div class="modal-actions modal-actions-top" id="pin-remove-wrap" style="display: none;">
                <button type="button" class="modal-btn modal-btn-delete js-pin-remove">Remove PIN</button>
            </div>
            <p class="js-pin-desc">Protect this folder so only people with the PIN can open it. PIN must be at least 4 characters.</p>
            <p id="pin-modal-error" class="pin-modal-error" style="display: none;"></p>
            <input type="password" id="pin-modal-input" class="pin-modal-input" placeholder="Enter PIN" minlength="4" autocomplete="off">
            <input type="password" id="pin-modal-new" class="pin-modal-input" placeholder="New PIN" minlength="4" autocomplete="off" style="display: none;">
            <div class="modal-actions">
                <button type="button" class="modal-btn modal-btn-cancel js-pin-cancel">Cancel</button>
                <button type="button" class="modal-btn modal-btn-primary js-pin-set">Set PIN</button>
            </div>
        </div>
    </div>
    <div id="pin-remove-modal" class="modal-overlay" aria-hidden="true" style="z-index: 1001;">
        <div class="modal-card">
            <h2>Remove PIN</h2>
            <p>Enter your current PIN to remove protection from this folder.</p>
            <p id="pin-remove-error" class="pin-modal-error" style="display: none;"></p>
            <input type="password" id="pin-remove-input" class="pin-modal-input" placeholder="Current PIN" minlength="4" autocomplete="off">
            <div class="modal-actions">
                <button type="button" class="modal-btn modal-btn-cancel js-pin-remove-cancel">Cancel</button>
                <button type="button" class="modal-btn modal-btn-delete js-pin-remove-confirm">Remove PIN</button>
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
    (function(){{
        var pinModal = document.getElementById("pin-modal");
        var pinTitle = pinModal && pinModal.querySelector(".js-pin-title");
        var pinDesc = pinModal && pinModal.querySelector(".js-pin-desc");
        var pinInput = document.getElementById("pin-modal-input");
        var pinModalNew = document.getElementById("pin-modal-new");
        var pinError = document.getElementById("pin-modal-error");
        var pinSetBtn = document.querySelector(".js-pin-set");
        var pinRemoveBtn = document.querySelector(".js-pin-remove");
        var pinRemoveWrap = document.getElementById("pin-remove-wrap");
        var pinCancelBtn = document.querySelector(".js-pin-cancel");
        var currentPinFolder = null;
        var currentPinFolderHasPin = false;
        function closePinModal(){{
            if (pinModal) {{ pinModal.classList.remove("is-open"); pinModal.setAttribute("aria-hidden", "true"); }}
            currentPinFolder = null;
            currentPinFolderHasPin = false;
            if (pinInput) pinInput.value = "";
            if (pinModalNew) {{ pinModalNew.value = ""; }}
            if (pinError) {{ pinError.style.display = "none"; pinError.textContent = ""; }}
        }}
        function showPinModal(folder, hasPin){{
            currentPinFolder = folder;
            currentPinFolderHasPin = (hasPin === "true");
            if (pinTitle) pinTitle.textContent = currentPinFolderHasPin ? "Change or remove PIN" : "Set a PIN to protect your folder";
            if (pinDesc) pinDesc.textContent = currentPinFolderHasPin ? "To remove protection, enter your current PIN below and click Remove PIN above. To change PIN, enter current and new PIN below and click Change PIN." : "Protect this folder so only people with the PIN can open it. PIN must be at least 4 characters.";
            if (pinRemoveWrap) pinRemoveWrap.style.display = currentPinFolderHasPin ? "flex" : "none";
            if (pinSetBtn) pinSetBtn.textContent = currentPinFolderHasPin ? "Change PIN" : "Set PIN";
            if (pinInput) {{ pinInput.placeholder = currentPinFolderHasPin ? "Current PIN" : "Enter PIN"; pinInput.value = ""; pinInput.focus(); }}
            if (pinModalNew) {{ pinModalNew.style.display = "block"; pinModalNew.value = ""; pinModalNew.placeholder = currentPinFolderHasPin ? "New PIN" : "Confirm PIN"; }}
            if (pinModal) {{ pinModal.classList.add("is-open"); pinModal.setAttribute("aria-hidden", "false"); }}
            if (pinError) {{ pinError.style.display = "none"; pinError.textContent = ""; }}
        }}
        document.querySelectorAll(".js-pin-menu").forEach(function(btn){{
            btn.addEventListener("click", function(e){{
                e.preventDefault();
                var folder = this.getAttribute("data-folder");
                var hasPin = this.getAttribute("data-has-pin") || "false";
                if (folder) showPinModal(folder, hasPin);
            }});
        }});
        if (pinCancelBtn) pinCancelBtn.addEventListener("click", closePinModal);
        if (pinModal) pinModal.addEventListener("click", function(e){{ if (e.target === pinModal) closePinModal(); }});
        if (pinSetBtn) pinSetBtn.addEventListener("click", function(){{
            if (!currentPinFolder || !pinInput) return;
            var payload;
            if (currentPinFolderHasPin) {{
                var currentPin = pinInput.value;
                var newPin = pinModalNew ? pinModalNew.value : "";
                if (newPin.length < 4) {{ if (pinError) {{ pinError.textContent = "New PIN must be at least 4 characters"; pinError.style.display = "block"; }} return; }}
                payload = {{ pin: newPin, current_pin: currentPin }};
            }} else {{
                var pin = pinInput.value;
                var confirmPin = pinModalNew ? pinModalNew.value : "";
                if (pin.length < 4) {{ if (pinError) {{ pinError.textContent = "PIN must be at least 4 characters"; pinError.style.display = "block"; }} return; }}
                if (pin !== confirmPin) {{ if (pinError) {{ pinError.textContent = "PIN and Confirm PIN do not match"; pinError.style.display = "block"; }} return; }}
                payload = {{ pin: pin }};
            }}
            var xhr = new XMLHttpRequest();
            xhr.open("POST", "/uploads/" + encodeURIComponent(currentPinFolder) + "/set-pin");
            xhr.setRequestHeader("Content-Type", "application/json");
            xhr.onload = function(){{
                if (xhr.status >= 200 && xhr.status < 300) {{ closePinModal(); window.location.reload(); }}
                else {{
                    var r = null;
                    try {{ r = JSON.parse(xhr.responseText); }} catch(z) {{}}
                    if (pinError) {{ pinError.textContent = (r && r.error) || "Failed to set PIN"; pinError.style.display = "block"; }}
                }}
            }};
            xhr.onerror = function(){{
                if (pinError) {{ pinError.textContent = "Network error"; pinError.style.display = "block"; }}
            }};
            xhr.send(JSON.stringify(payload));
        }});
        var pinRemoveModal = document.getElementById("pin-remove-modal");
        var pinRemoveInput = document.getElementById("pin-remove-input");
        var pinRemoveError = document.getElementById("pin-remove-error");
        var pinRemoveCancelBtn = document.querySelector(".js-pin-remove-cancel");
        var pinRemoveConfirmBtn = document.querySelector(".js-pin-remove-confirm");
        function openRemovePinModal(){{
            if (!currentPinFolder) return;
            if (pinRemoveInput) {{ pinRemoveInput.value = ""; pinRemoveInput.focus(); }}
            if (pinRemoveError) {{ pinRemoveError.style.display = "none"; pinRemoveError.textContent = ""; }}
            if (pinRemoveModal) {{ pinRemoveModal.classList.add("is-open"); pinRemoveModal.setAttribute("aria-hidden", "false"); }}
        }}
        function closeRemovePinModal(){{
            if (pinRemoveModal) {{ pinRemoveModal.classList.remove("is-open"); pinRemoveModal.setAttribute("aria-hidden", "true"); }}
            if (pinRemoveInput) pinRemoveInput.value = "";
            if (pinRemoveError) {{ pinRemoveError.style.display = "none"; pinRemoveError.textContent = ""; }}
        }}
        if (pinRemoveBtn) pinRemoveBtn.addEventListener("click", function(){{
            openRemovePinModal();
        }});
        if (pinRemoveCancelBtn) pinRemoveCancelBtn.addEventListener("click", closeRemovePinModal);
        if (pinRemoveModal) pinRemoveModal.addEventListener("click", function(e){{ if (e.target === pinRemoveModal) closeRemovePinModal(); }});
        if (pinRemoveConfirmBtn) pinRemoveConfirmBtn.addEventListener("click", function(){{
            if (!currentPinFolder || !pinRemoveInput) return;
            var currentPin = pinRemoveInput.value;
            if (!currentPin || currentPin.length < 4) {{
                if (pinRemoveError) {{ pinRemoveError.textContent = "Please enter your current PIN"; pinRemoveError.style.display = "block"; }}
                return;
            }}
            var xhr = new XMLHttpRequest();
            xhr.open("POST", "/uploads/" + encodeURIComponent(currentPinFolder) + "/set-pin");
            xhr.setRequestHeader("Content-Type", "application/json");
            xhr.onload = function(){{
                if (xhr.status >= 200 && xhr.status < 300) {{ closeRemovePinModal(); closePinModal(); window.location.reload(); }}
                else {{
                    var r = null;
                    try {{ r = JSON.parse(xhr.responseText); }} catch(z) {{}}
                    if (pinRemoveError) {{ pinRemoveError.textContent = (r && r.error) || "Failed to remove PIN"; pinRemoveError.style.display = "block"; }}
                }}
            }};
            xhr.send(JSON.stringify({{ remove: true, current_pin: currentPin }}));
        }});
    }})();
    </script>
</body>
</html>"""


def _folder_not_found_html(folder_name):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    {FAVICON_LINK}
    <title>Folder not found</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            margin: 0;
            min-height: 100vh;
            background: linear-gradient(145deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            color: #e8e8e8;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 1rem;
        }}
        .not-found-wrap {{
            max-width: 360px;
            width: 100%;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 16px;
            padding: 1.5rem;
            box-shadow: 0 20px 50px rgba(0,0,0,0.3);
            text-align: center;
        }}
        .not-found-wrap h1 {{ margin: 0 0 0.75rem 0; font-size: 1.25rem; color: #fff; }}
        .not-found-wrap p {{ margin: 0 0 1.25rem 0; opacity: 0.9; font-size: 0.95rem; }}
        .not-found-wrap a {{
            display: inline-block;
            padding: 0.65rem 1.5rem;
            border-radius: 10px;
            background: #7dd3fc;
            color: #1a1a2e;
            font-weight: 600;
            font-size: 1rem;
            text-decoration: none;
            transition: background 0.2s;
        }}
        .not-found-wrap a:hover {{ background: #38bdf8; }}
    </style>
</head>
<body>
    <div class="not-found-wrap">
        <h1>Folder not found</h1>
        <p>The folder does not exist. It may have been deleted.</p>
        <a href="/uploads">Go back</a>
    </div>
</body>
</html>"""


def _pin_entry_html(folder_name, next_url, error=None, form_action=None):
    if form_action is None:
        form_action = url_for("pin_entry", folder=folder_name)
    err = f'<p class="pin-error">{error}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    {FAVICON_LINK}
    <title>Enter PIN – {quote(folder_name)}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            margin: 0;
            min-height: 100vh;
            background: linear-gradient(145deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            color: #e8e8e8;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 1rem;
        }}
        .pin-wrap {{
            max-width: 320px;
            width: 100%;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 16px;
            padding: 1.5rem;
            box-shadow: 0 20px 50px rgba(0,0,0,0.3);
        }}
        .pin-wrap h1 {{ margin: 0 0 1rem 0; font-size: 1.15rem; color: #fff; }}
        .pin-wrap p {{ margin: 0 0 1rem 0; opacity: 0.9; font-size: 0.95rem; }}
        .pin-error {{ color: #fca5a5; margin-bottom: 0.75rem !important; }}
        .pin-wrap input[type="password"] {{
            width: 100%;
            padding: 0.75rem 1rem;
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 10px;
            background: rgba(0,0,0,0.2);
            color: #e8e8e8;
            font-size: 1rem;
            margin-bottom: 1rem;
        }}
        .pin-wrap input:focus {{ outline: none; border-color: #7dd3fc; }}
        .pin-wrap button {{
            width: 100%;
            padding: 0.75rem;
            border-radius: 10px;
            border: none;
            background: #7dd3fc;
            color: #1a1a2e;
            font-weight: 600;
            font-size: 1rem;
            cursor: pointer;
        }}
        .pin-wrap button:hover {{ background: #38bdf8; }}
        .pin-wrap a {{ color: #7dd3fc; text-decoration: none; font-size: 0.9rem; }}
        .pin-wrap a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="pin-wrap">
        <h1>This folder is protected</h1>
        <p>Enter the PIN to open folder &quot;{quote(folder_name)}&quot;.</p>
        {err}
        <form method="post" action="{form_action}">
            <input type="hidden" name="next" value="{quote(next_url or ("/uploads/" + quote(folder_name)))}">
            <input type="password" name="pin" placeholder="PIN" autofocus minlength="4" required>
            <button type="submit">Unlock</button>
        </form>
        <p style="margin-top: 1rem;"><a href="/uploads">← Back to Uploads</a></p>
    </div>
</body>
</html>"""


@app.route("/uploads/<folder>/pin", methods=["GET", "POST"])
def pin_entry(folder):
    path = _safe_upload_path(folder)
    if path is None or not os.path.isdir(path):
        return "Not found", 404
    if not folder_has_pin(folder):
        return redirect(url_for("list_or_download_uploads", subpath=folder))
    if request.method == "POST":
        pin = (request.form.get("pin") or "").strip()
        next_url = request.form.get("next") or url_for("list_or_download_uploads", subpath=folder)
        if verify_folder_pin(folder, pin):
            _unlock_folder_with_fek(folder, pin)
            return redirect(next_url)
        return _pin_entry_html(folder, next_url, error="Wrong PIN. Try again."), 401
    next_url = request.args.get("next") or url_for("list_or_download_uploads", subpath=folder)
    return _pin_entry_html(folder, next_url)


@app.route("/uploads/<folder>/set-pin", methods=["POST"])
def set_pin(folder):
    client_ip = get_client_ip().strip()
    if client_ip != folder and client_ip not in ("127.0.0.1", "::1"):
        return {"ok": False, "error": "You can only set a PIN for your own folder."}, 403
    folder_path = pathlib.Path(app.config["UPLOAD_FOLDER"], folder)
    folder_path.mkdir(parents=True, exist_ok=True)
    path = _safe_upload_path(folder)
    if path is None or not os.path.isdir(path):
        return {"ok": False, "error": "Folder not found."}, 404
    data = request.get_json(force=True, silent=True) or {}
    pin = (data.get("pin") or "").strip() if isinstance(data.get("pin"), str) else ""
    # Accept current_pin as str or number (e.g. from JSON); normalize to stripped str or None
    raw_current = data.get("current_pin") if not data.get("remove") else (data.get("current_pin") or data.get("pin"))
    if raw_current is not None and not isinstance(raw_current, str):
        raw_current = str(raw_current)
    current_pin = (raw_current or "").strip() or None
    remove = data.get("remove") is True
    if remove:
        pin = ""
    ok, err = set_folder_pin(folder, pin, current_pin=current_pin)
    if err:
        return {"ok": False, "error": err}, 400
    return {"ok": True, "has_pin": bool(pin)}


@app.route("/uploads/<folder>/pin-status", methods=["GET"])
def pin_status(folder):
    client_ip = get_client_ip().strip()
    if client_ip != folder and client_ip not in ("127.0.0.1", "::1"):
        return {"has_pin": False}, 403
    return {"has_pin": folder_has_pin(folder)}


@app.route("/api/uploader-folder", methods=["GET"])
def api_uploader_folder():
    """Return the current client's folder name (IP) for use on home page."""
    return {"folder": get_client_ip().strip()}


@app.route("/api/uploader-has-folder", methods=["GET"])
def api_uploader_has_folder():
    """Return whether the current client already has a folder (fresh user = false)."""
    folder = get_client_ip().strip()
    path = pathlib.Path(app.config["UPLOAD_FOLDER"], folder)
    return {"has_folder": path.is_dir()}


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
                item["pin_menu"] = True
                item["folder_name"] = f
                item["has_pin"] = folder_has_pin(f)
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
        return _folder_not_found_html(folder), 404
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
            return _folder_not_found_html(folder), 404
        if folder_has_pin(folder) and not is_folder_unlocked(folder):
            next_url = url_for("list_or_download_uploads", subpath=folder)
            return redirect(url_for("pin_entry", folder=folder, next=next_url))
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
    if folder_has_pin(folder) and not is_folder_unlocked(folder):
        return redirect(url_for("pin_entry", folder=folder, next=request.url))
    file_path = _safe_upload_path(*parts)
    if file_path is None or not os.path.isfile(file_path):
        return "Not found", 404
    if folder_has_encryption(folder):
        fernet = get_fek_for_folder(folder)
        if fernet:
            try:
                ciphertext = pathlib.Path(file_path).read_bytes()
                plaintext = fernet.decrypt(ciphertext)
                return send_file(
                    BytesIO(plaintext),
                    as_attachment=True,
                    download_name=os.path.basename(file_path),
                    mimetype="application/octet-stream",
                )
            except Exception:
                return "Decryption failed", 500
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
            folder_name = uploader_ip
            if folder_has_encryption(folder_name) and not get_fek_for_folder(folder_name):
                flash("Open your folder and enter PIN first to upload encrypted files.")
                return redirect(request.url)
            fernet = get_fek_for_folder(folder_name) if folder_has_encryption(folder_name) else None
            for file in files:
                filename = secure_filename(file.filename)
                content = file.read()
                out_path = upload_dir / filename
                if fernet:
                    out_path.write_bytes(fernet.encrypt(content))
                else:
                    out_path.write_bytes(content)
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
    .home-info {
        max-width: 520px;
        width: 100%;
        margin-bottom: 1.5rem;
        padding: 0.9rem 1.1rem;
        background: rgba(125, 211, 252, 0.08);
        border: 1px solid rgba(125, 211, 252, 0.25);
        border-radius: 12px;
        color: #e8e8e8;
        font-size: clamp(0.85rem, 2.2vw, 0.95rem);
        line-height: 1.45;
        text-align: center;
    }
    .home-info strong { color: #7dd3fc; }
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
    .home-encrypt-modal, .home-pin-modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6); align-items: center; justify-content: center; z-index: 1000; padding: 1rem; }
    .home-encrypt-modal.is-open, .home-pin-modal.is-open { display: flex; }
    .home-encrypt-card, .home-pin-card { background: linear-gradient(145deg, #1a1a2e 0%, #16213e 100%); border: 1px solid rgba(255,255,255,0.12); border-radius: 16px; padding: 1.5rem; max-width: 360px; width: 100%; box-shadow: 0 20px 50px rgba(0,0,0,0.4); }
    .home-encrypt-card h2, .home-pin-card h2 { margin: 0 0 0.75rem 0; font-size: 1.1rem; color: #fff; }
    .home-encrypt-card p, .home-pin-card p { margin: 0 0 1rem 0; font-size: 0.95rem; opacity: 0.9; }
    .home-modal-actions { display: flex; gap: 0.75rem; justify-content: flex-end; flex-wrap: wrap; margin-top: 1rem; }
    .home-modal-btn { padding: 0.5rem 1.25rem; border-radius: 10px; font-size: 0.95rem; font-weight: 600; cursor: pointer; border: 1px solid transparent; }
    .home-modal-btn-secondary { background: rgba(255,255,255,0.08); color: #e8e8e8; }
    .home-modal-btn-primary { background: #7dd3fc; color: #1a1a2e; }
    .home-pin-card input[type="password"] { width: 100%; padding: 0.6rem 0.75rem; border: 1px solid rgba(255,255,255,0.2); border-radius: 10px; background: rgba(0,0,0,0.2); color: #e8e8e8; font-size: 1rem; margin-bottom: 0.5rem; }
    .home-pin-card .home-pin-error { color: #fca5a5; font-size: 0.85rem; margin-bottom: 0.5rem; }
    </style>
    </head>
    <body>
    <script>window.UPLOADER_FOLDER = UPLOADER_FOLDER_PLACEHOLDER;</script>
    <div class="home-wrap">
    <nav class="site-nav"><a href="/" class="nav-logo-link"><img src="https://media2.giphy.com/media/QssGEmpkyEOhBCb7e1/giphy.gif?cid=ecf05e47a0n3gi1bfqntqmob8g9aid1oyj2wr3ds3mg700bl&amp;rid=giphy.gif" alt="Logo" class="nav-logo"></a><a href="/" class="active"><svg class="nav-icon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg>Home</a><a href="/uploads"><svg class="nav-icon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>Uploads</a></nav>
    <p class="home-info"><strong>PIN-protected uploads are encrypted.</strong> Files in folders with a PIN are encrypted with cryptography; even an admin cannot access them. Don&rsquo;t lose your PIN.</p>
    <div class="main">
    <form method=post enctype=multipart/form-data>
        <input id="k-upload" onchange="enablethis(this)" class="files" type="file" name="file" multiple>
        <label for="k-upload" class="custom-file-upload">
            <span class="btn-icon" aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg></span>Select Files
        </label>


        <input id="file-upload" class="submiter" disabled type=submit value="Upload">
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
        <div class="loading-gif-wrap">
            <div class="label"><span id="progress-label">Uploading…</span><span id="progress-pct">0%</span></div>
        </div>
        <div class="spinner"></div>
    </div>
    <div id="home-encrypt-modal" class="home-encrypt-modal" aria-hidden="true">
        <div class="home-encrypt-card">
            <h2>Do you want your folder encrypted?</h2>
            <p>Your files will be encrypted with a PIN. Only you (or anyone with the PIN) can open the folder. Don&rsquo;t lose your PIN.</p>
            <div class="home-modal-actions">
                <button type="button" class="home-modal-btn home-modal-btn-secondary" id="home-encrypt-no">No</button>
                <button type="button" class="home-modal-btn home-modal-btn-primary" id="home-encrypt-yes">Yes</button>
            </div>
        </div>
    </div>
    <div id="home-pin-modal" class="home-pin-modal" aria-hidden="true">
        <div class="home-pin-card">
            <h2>Enter your PIN for the folder</h2>
            <p>Choose a PIN (at least 4 characters). Your uploads will be encrypted.</p>
            <p id="home-pin-error" class="home-pin-error" style="display: none;"></p>
            <input type="password" id="home-pin-input" placeholder="PIN" minlength="4" autocomplete="off">
            <input type="password" id="home-pin-confirm" placeholder="Confirm PIN" minlength="4" autocomplete="off">
            <div class="home-modal-actions">
                <button type="button" class="home-modal-btn home-modal-btn-secondary" id="home-pin-cancel">Cancel</button>
                <button type="button" class="home-modal-btn home-modal-btn-primary" id="home-pin-set">Set PIN &amp; Upload</button>
            </div>
        </div>
    </div>
    <script>
    function transit(){
        var body = document.getElementById("body");
        if (body) body.style.visibility = "visible";
        var bar = document.getElementById("progress-bar");
        if (bar) bar.style.width = "0%";
        var pct = document.getElementById("progress-pct");
        if (pct) pct.textContent = "0%";
        var label = document.getElementById("progress-label");
        if (label) label.textContent = "Uploading…";
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
        var encryptModal = document.getElementById("home-encrypt-modal");
        var pinModal = document.getElementById("home-pin-modal");
        var pinInput = document.getElementById("home-pin-input");
        var pinConfirm = document.getElementById("home-pin-confirm");
        var pinError = document.getElementById("home-pin-error");
        function doUpload(){
            transit();
            var fd = new FormData(form);
            var xhr = new XMLHttpRequest();
            var bar = document.getElementById("progress-bar");
            var pct = document.getElementById("progress-pct");
            var label = document.getElementById("progress-label");
            xhr.upload.addEventListener('progress', function(e){
                if (e.lengthComputable && pct) {
                    var percent = Math.round((e.loaded / e.total) * 100);
                    if (bar) bar.style.width = percent + "%";
                    pct.textContent = percent + "%";
                } else if (pct) { pct.textContent = "..."; }
            });
            xhr.addEventListener('load', function(){
                if (xhr.status >= 200 && xhr.status < 300) {
                    if (label) label.textContent = "Done!";
                    if (bar) bar.style.width = "100%";
                    if (pct) pct.textContent = "100%";
                    setTimeout(function(){ window.location.href = "/"; }, 600);
                } else {
                    if (label) label.textContent = "Upload failed";
                    setTimeout(function(){ var b = document.getElementById("body"); if (b) b.style.visibility = "hidden"; }, 2000);
                }
            });
            xhr.addEventListener('error', function(){
                if (label) label.textContent = "Upload failed";
                setTimeout(function(){ var b = document.getElementById("body"); if (b) b.style.visibility = "hidden"; }, 2000);
            });
            xhr.open('POST', form.action || '/');
            xhr.send(fd);
        }
        function showEncryptModal(){ if (encryptModal) { encryptModal.classList.add("is-open"); encryptModal.setAttribute("aria-hidden", "false"); } }
        function hideEncryptModal(){ if (encryptModal) { encryptModal.classList.remove("is-open"); encryptModal.setAttribute("aria-hidden", "true"); } }
        function showPinModal(){ if (pinModal) { pinModal.classList.add("is-open"); pinModal.setAttribute("aria-hidden", "false"); if (pinInput) pinInput.value = ""; if (pinConfirm) pinConfirm.value = ""; if (pinError) { pinError.style.display = "none"; pinError.textContent = ""; } if (pinInput) pinInput.focus(); } }
        function hidePinModal(){ if (pinModal) { pinModal.classList.remove("is-open"); pinModal.setAttribute("aria-hidden", "true"); } }
        document.getElementById("home-encrypt-no").addEventListener("click", function(){ hideEncryptModal(); doUpload(); });
        document.getElementById("home-encrypt-yes").addEventListener("click", function(){ hideEncryptModal(); showPinModal(); });
        document.getElementById("home-pin-cancel").addEventListener("click", function(){ hidePinModal(); doUpload(); });
        document.getElementById("home-pin-set").addEventListener("click", function(){
            var pin = pinInput ? pinInput.value : "";
            var conf = pinConfirm ? pinConfirm.value : "";
            if (pin.length < 4) { if (pinError) { pinError.textContent = "PIN must be at least 4 characters"; pinError.style.display = "block"; } return; }
            if (pin !== conf) { if (pinError) { pinError.textContent = "PIN and Confirm PIN do not match"; pinError.style.display = "block"; } return; }
            var folder = window.UPLOADER_FOLDER;
            if (!folder) { doUpload(); return; }
            var xhr = new XMLHttpRequest();
            xhr.open("POST", "/uploads/" + encodeURIComponent(folder) + "/set-pin");
            xhr.setRequestHeader("Content-Type", "application/json");
            xhr.onload = function(){
                if (xhr.status >= 200 && xhr.status < 300) { hidePinModal(); doUpload(); }
                else { var r = null; try { r = JSON.parse(xhr.responseText); } catch(z) {} if (pinError) { pinError.textContent = (r && r.error) || "Failed to set PIN"; pinError.style.display = "block"; } }
            };
            xhr.onerror = function(){ if (pinError) { pinError.textContent = "Network error"; pinError.style.display = "block"; } };
            xhr.send(JSON.stringify({ pin: pin }));
        });
        function getFolderThen(fn){
            var folder = window.UPLOADER_FOLDER;
            if (folder) { fn(folder); return; }
            var xhr = new XMLHttpRequest();
            xhr.open("GET", "/api/uploader-folder");
            xhr.onload = function(){
                if (xhr.status >= 200 && xhr.status < 300) {
                    try { var r = JSON.parse(xhr.responseText); folder = r && r.folder; } catch(z) {}
                    if (folder) window.UPLOADER_FOLDER = folder;
                }
                fn(window.UPLOADER_FOLDER || null);
            };
            xhr.onerror = function(){ fn(null); };
            xhr.send();
        }
        function startUploadFlow(){
            var hasFolderXhr = new XMLHttpRequest();
            hasFolderXhr.open("GET", "/api/uploader-has-folder");
            hasFolderXhr.onload = function(){
                var hasFolder = true;
                try { var r = JSON.parse(hasFolderXhr.responseText); hasFolder = r && r.has_folder; } catch(z) {}
                if (hasFolder) { doUpload(); return; }
                getFolderThen(function(folder){
                    if (!folder) { doUpload(); return; }
                    showEncryptModal();
                });
            };
            hasFolderXhr.onerror = function(){ doUpload(); };
            hasFolderXhr.send();
        }
        var uploadBtn = document.getElementById("file-upload");
        var uploadLabel = form.querySelector('label[for="file-upload"]');
        function interceptUpload(ev){
            ev.preventDefault();
            ev.stopPropagation();
            if (!form.checkValidity || form.checkValidity()) startUploadFlow();
        }
        if (uploadBtn) uploadBtn.addEventListener("click", interceptUpload, true);
        if (uploadLabel) uploadLabel.addEventListener("click", interceptUpload, true);
        form.addEventListener("submit", function(ev){ ev.preventDefault(); ev.stopPropagation(); });
    })();
    </script>
    </body>
    </html>
    '''.replace("UPLOADER_FOLDER_PLACEHOLDER", json.dumps(uploader_ip))


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
