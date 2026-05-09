import hashlib
import socket
import getpass
import base64

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes


def _derive_key() -> bytes:
    machine = socket.gethostname()
    user = getpass.getuser()
    seed = f"{machine}:{user}"
    return hashlib.sha256(seed.encode()).digest()[:16]


def encrypt_password(plaintext: str) -> str:
    key = _derive_key()
    iv = get_random_bytes(16)
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    ciphertext = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    combined = iv + ciphertext
    return base64.b64encode(combined).decode("ascii")


def decrypt_password(encoded: str) -> str:
    key = _derive_key()
    raw = base64.b64decode(encoded)
    iv = raw[:16]
    ciphertext = raw[16:]
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    return unpad(cipher.decrypt(ciphertext), AES.block_size).decode("utf-8")
