import base64
import json
import os
import pathlib
import secrets
import time

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from flask import request, session
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from decrypt_service import decrypt_existing_files, decrypt_fek
from encrypt_service import encrypt_existing_files, encrypt_fek


class PinService:
    PBKDF2_ITERATIONS = 100_000
    SALT_LENGTH = 16
    FT_UNLOCKS_COOKIE = "FT_UNLOCKS"
    FT_UNLOCKS_MAX_AGE_DAYS = 7
    FT_UNLOCKS_MAX_AGE_SEC = FT_UNLOCKS_MAX_AGE_DAYS * 24 * 3600

    def __init__(self, upload_folder, secret_key):
        self.upload_folder = upload_folder
        self.secret_key = secret_key
        self._unlock_store = {}  # token -> {"folder": str, "fek": str, "expires": float}
        self._pin_attempts = {}  # folder -> {"count": int, "final_confirmed": bool}

    def _unlock_serializer(self):
        return URLSafeTimedSerializer(self.secret_key, salt="ft-unlocks")

    def _unlock_store_cleanup(self):
        now = time.time()
        expired = [t for t, v in self._unlock_store.items() if v["expires"] <= now]
        for token in expired:
            self._unlock_store.pop(token, None)

    def unlock_store_add(self, folder_name, fek_b64):
        self._unlock_store_cleanup()
        token = secrets.token_urlsafe(32)
        self._unlock_store[token] = {
            "folder": folder_name,
            "fek": fek_b64,
            "expires": time.time() + self.FT_UNLOCKS_MAX_AGE_SEC,
        }
        return token

    def _unlock_store_get(self, token):
        self._unlock_store_cleanup()
        entry = self._unlock_store.get(token)
        if not entry or entry["expires"] <= time.time():
            return None, None
        return entry["folder"], entry["fek"]

    def _unlock_store_revoke_folder(self, folder_name):
        to_remove = [t for t, v in self._unlock_store.items() if v["folder"] == folder_name]
        for token in to_remove:
            self._unlock_store.pop(token, None)

    def _get_unlock_cookie_data(self):
        raw = request.cookies.get(self.FT_UNLOCKS_COOKIE)
        if not raw:
            return {}
        try:
            payload = self._unlock_serializer().loads(raw, max_age=self.FT_UNLOCKS_MAX_AGE_SEC)
            return payload.get("folders") or {}
        except (BadSignature, Exception):
            return {}

    def _get_fek_from_unlock_cookie(self, folder_name):
        cookies = self._get_unlock_cookie_data()
        token = cookies.get(folder_name)
        if not token:
            return None
        _, fek_b64 = self._unlock_store_get(token)
        if not fek_b64:
            return None
        try:
            return Fernet(fek_b64.encode("ascii"))
        except Exception:
            return None

    def set_unlock_cookie_on_response(self, response, folder_name, token):
        current = self._get_unlock_cookie_data()
        current[folder_name] = token
        payload = self._unlock_serializer().dumps({"folders": current})
        response.set_cookie(
            self.FT_UNLOCKS_COOKIE,
            payload,
            max_age=self.FT_UNLOCKS_MAX_AGE_SEC,
            path="/",
            samesite="Lax",
            httponly=True,
        )

    def _pins_path(self):
        base = pathlib.Path(self.upload_folder).resolve()
        return base / ".folder_pins.json"

    def _load_pins(self):
        path = self._pins_path()
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_pins(self, pins):
        path = self._pins_path()
        try:
            path.write_text(json.dumps(pins), encoding="utf-8")
            return True
        except OSError:
            return False

    def _get_pin_record(self, folder_name):
        pins = self._load_pins()
        return pins.get(folder_name)

    def folder_has_pin(self, folder_name):
        rec = self._get_pin_record(folder_name)
        if rec is None:
            return False
        if isinstance(rec, str):
            return bool(rec)
        return bool(rec.get("hash"))

    def folder_has_encryption(self, folder_name):
        rec = self._get_pin_record(folder_name)
        return isinstance(rec, dict) and rec.get("encrypted_fek")

    def remove_folder_details(self, folder_name):
        """Remove PIN/encryption metadata and unlock state for a folder."""
        pins = self._load_pins()
        had_record = folder_name in pins
        if had_record:
            pins.pop(folder_name, None)
            if not self._save_pins(pins):
                return False
        self._clear_session_fek(folder_name)
        self._unlock_store_revoke_folder(folder_name)
        self.clear_pin_failures(folder_name)
        return True

    def register_failed_pin_attempt(self, folder_name):
        state = self._pin_attempts.get(folder_name) or {"count": 0, "final_confirmed": False}
        state["count"] += 1
        self._pin_attempts[folder_name] = state
        return state["count"]

    def get_failed_pin_attempts(self, folder_name):
        state = self._pin_attempts.get(folder_name) or {"count": 0, "final_confirmed": False}
        return int(state["count"])

    def confirm_final_attempt(self, folder_name):
        state = self._pin_attempts.get(folder_name) or {"count": 0, "final_confirmed": False}
        state["final_confirmed"] = True
        self._pin_attempts[folder_name] = state

    def is_final_attempt_confirmed(self, folder_name):
        state = self._pin_attempts.get(folder_name) or {"count": 0, "final_confirmed": False}
        return bool(state["final_confirmed"])

    def clear_pin_failures(self, folder_name):
        self._pin_attempts.pop(folder_name, None)

    def _derive_kek(self, pin_clean, salt_b64):
        salt = base64.b64decode(salt_b64)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self.PBKDF2_ITERATIONS,
        )
        key_bytes = kdf.derive(pin_clean.encode("utf-8"))
        return base64.urlsafe_b64encode(key_bytes).decode("ascii")

    def _session_folder_keys(self):
        return session.get("folder_keys") or {}

    def _set_session_fek(self, folder_name, fek_b64):
        keys = dict(self._session_folder_keys())
        keys[folder_name] = fek_b64
        session["folder_keys"] = keys

    def _clear_session_fek(self, folder_name):
        keys = dict(self._session_folder_keys())
        keys.pop(folder_name, None)
        session["folder_keys"] = keys

    def get_session_fek_b64(self, folder_name):
        return self._session_folder_keys().get(folder_name)

    def get_fek_for_folder(self, folder_name):
        fek_b64 = self._session_folder_keys().get(folder_name)
        if fek_b64:
            try:
                return Fernet(fek_b64.encode("ascii"))
            except Exception:
                pass
        return self._get_fek_from_unlock_cookie(folder_name)

    def _folder_path(self, folder_name):
        return pathlib.Path(self.upload_folder, folder_name)

    def _get_fernet_from_current_pin(self, folder_name, current_pin):
        rec = self._get_pin_record(folder_name)
        if not isinstance(rec, dict) or not rec.get("encrypted_fek"):
            return None
        pin_clean = (current_pin or "").strip()
        if not pin_clean:
            return None
        if not check_password_hash(rec["hash"], pin_clean):
            return None
        kek_b64 = self._derive_kek(pin_clean, rec["salt"])
        try:
            fek_bytes = decrypt_fek(rec["encrypted_fek"], kek_b64)
            # decrypt_fek returns the original Fernet key bytes (already urlsafe-base64 text bytes).
            fek_b64 = fek_bytes.decode("ascii") if isinstance(fek_bytes, bytes) else str(fek_bytes)
            return Fernet(fek_b64.encode("ascii"))
        except Exception:
            return None

    def set_folder_pin(self, folder_name, pin, current_pin=None):
        pins = self._load_pins()
        if not pin or not pin.strip():
            rec = pins.get(folder_name)
            if rec is not None:
                if not current_pin or not (current_pin or "").strip():
                    return (False, "Please enter your current PIN to remove protection.")
                if not self.verify_folder_pin(folder_name, current_pin):
                    return (False, "Wrong PIN.")
            if isinstance(rec, dict) and rec.get("encrypted_fek"):
                fernet = self.get_fek_for_folder(folder_name)
                if not fernet:
                    fernet = self._get_fernet_from_current_pin(folder_name, current_pin)
                if not fernet:
                    return (False, "Wrong PIN.")
                # Decrypt all files before removing folder protection.
                decrypt_existing_files(self._folder_path(folder_name), fernet)
            pins.pop(folder_name, None)
            self._clear_session_fek(folder_name)
            self._unlock_store_revoke_folder(folder_name)
            if not self._save_pins(pins):
                return (False, "Failed to update PIN file. Please try again.")
            return (True, None)

        pin_clean = pin.strip()
        if len(pin_clean) < 4:
            return (False, "PIN must be at least 4 characters")

        rec = pins.get(folder_name)
        if rec is not None:
            if not current_pin or not (current_pin or "").strip():
                return (False, "Please enter your current PIN to change it.")
            if not self.verify_folder_pin(folder_name, current_pin):
                return (False, "Wrong current PIN.")

        if isinstance(rec, dict) and rec.get("encrypted_fek"):
            fernet_old = self.get_fek_for_folder(folder_name)
            if not fernet_old and current_pin:
                fernet_old = self._get_fernet_from_current_pin(folder_name, current_pin)
            if not fernet_old:
                return (
                    False,
                    "Wrong current PIN or open the folder and enter current PIN first, then you can change PIN.",
                )
            decrypt_existing_files(self._folder_path(folder_name), fernet_old)

        salt = os.urandom(self.SALT_LENGTH)
        salt_b64 = base64.b64encode(salt).decode("ascii")
        kek_b64 = self._derive_kek(pin_clean, salt_b64)
        fek = Fernet.generate_key()
        encrypted_fek_b64 = encrypt_fek(fek, kek_b64)
        pin_hash = generate_password_hash(pin_clean, method="pbkdf2:sha256")
        pins[folder_name] = {
            "hash": pin_hash,
            "salt": salt_b64,
            "encrypted_fek": encrypted_fek_b64,
        }
        if not self._save_pins(pins):
            return (False, "Failed to save PIN")

        self._unlock_store_revoke_folder(folder_name)
        fernet = Fernet(fek)
        encrypt_existing_files(self._folder_path(folder_name), fernet)
        self._set_session_fek(folder_name, fek.decode("ascii"))
        self._unlock_folder(folder_name)
        return (True, None)

    def verify_folder_pin(self, folder_name, pin):
        rec = self._get_pin_record(folder_name)
        if not rec:
            return False
        if isinstance(rec, str):
            return check_password_hash(rec, pin)
        if not check_password_hash(rec["hash"], pin):
            return False
        return True

    def unlock_folder_with_fek(self, folder_name, pin):
        rec = self._get_pin_record(folder_name)
        if not isinstance(rec, dict) or not rec.get("encrypted_fek"):
            # Legacy PIN-only folder (no encrypted FEK): session unlock flag is enough.
            self._unlock_folder(folder_name)
            return
        pin_clean = pin.strip()
        kek_b64 = self._derive_kek(pin_clean, rec["salt"])
        try:
            fek_bytes = decrypt_fek(rec["encrypted_fek"], kek_b64)
            # Keep FEK exactly as originally generated/stored.
            fek_b64 = fek_bytes.decode("ascii") if isinstance(fek_bytes, bytes) else str(fek_bytes)
            self._set_session_fek(folder_name, fek_b64)
            self._unlock_folder(folder_name)
        except Exception:
            pass

    def _unlocked_folders(self):
        return set(session.get("unlocked_folders") or [])

    def _unlock_folder(self, folder_name):
        folders = list(self._unlocked_folders())
        if folder_name not in folders:
            folders.append(folder_name)
        session["unlocked_folders"] = folders

    def is_folder_unlocked(self, folder_name):
        # Encrypted folders are unlocked only when we have a valid FEK
        # (session or unlock cookie). This prevents downloading ciphertext.
        if self.folder_has_encryption(folder_name):
            return self.get_fek_for_folder(folder_name) is not None
        return folder_name in self._unlocked_folders()
