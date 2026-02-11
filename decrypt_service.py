import base64

from cryptography.fernet import Fernet


def decrypt_fek(encrypted_fek_b64, kek_b64):
    fernet_kek = Fernet(kek_b64.encode("ascii"))
    return fernet_kek.decrypt(base64.b64decode(encrypted_fek_b64))


def decrypt_existing_files(folder_path, fernet):
    if not folder_path.is_dir():
        return
    for item in folder_path.iterdir():
        if not item.is_file():
            continue
        try:
            data = item.read_bytes()
            decrypted = fernet.decrypt(data)
            item.write_bytes(decrypted)
        except Exception:
            pass
