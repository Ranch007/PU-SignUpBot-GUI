import hashlib
import socket
import getpass
import base64
import ctypes
from ctypes import wintypes
import os

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


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows 用户范围 DPAPI；不使用 LOCAL_MACHINE 标志。"""
    if os.name != "nt":
        raise OSError("DPAPI 仅支持 Windows")
    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    operation = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    operation.restype = wintypes.BOOL
    operation.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    source = ctypes.create_string_buffer(data, len(data))
    source_blob = _DataBlob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    result = _DataBlob()
    if not operation(ctypes.byref(source_blob), None, None, None, None, 0x1,
                     ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def protect_secret(plaintext: str) -> str:
    """新格式优先使用 Windows 用户范围 DPAPI；其他系统兼容旧本机加密。"""
    if os.name == "nt":
        encrypted = _dpapi(plaintext.encode("utf-8"), protect=True)
        return "dpapi:v1:" + base64.b64encode(encrypted).decode("ascii")
    return "enc:v1:" + encrypt_password(plaintext)


def unprotect_secret(stored: str) -> str:
    if stored.startswith("dpapi:v1:"):
        raw = base64.b64decode(stored[len("dpapi:v1:"):], validate=True)
        return _dpapi(raw, protect=False).decode("utf-8")
    if stored.startswith("enc:v1:"):
        return decrypt_password(stored[len("enc:v1:"):])
    raise ValueError("未知凭据格式")
