import base64

from cryptography.fernet import Fernet


def encrypt_fek(fek_bytes, kek_b64):
    fernet_kek = Fernet(kek_b64.encode("ascii"))
    return base64.b64encode(fernet_kek.encrypt(fek_bytes)).decode("ascii")


def encrypt_existing_files(folder_path, fernet):
    if not folder_path.is_dir():
        return
    for item in folder_path.iterdir():
        if not item.is_file():
            continue
        try:
            data = item.read_bytes()
            encrypted = fernet.encrypt(data)
            item.write_bytes(encrypted)
        except Exception:
            pass
