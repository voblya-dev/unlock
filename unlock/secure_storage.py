"""Small Windows DPAPI wrapper used for credentials stored by Unlock."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class SecureStorageError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _crypt(data: bytes, *, protect: bool) -> bytes:
    """Encrypt/decrypt data for the current Windows user with DPAPI."""
    if sys.platform != "win32":
        raise SecureStorageError("Credential storage requires Windows DPAPI")
    if not data:
        return b""

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    source = ctypes.create_string_buffer(data)
    source_blob = _DataBlob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    result_blob = _DataBlob()

    if protect:
        crypt32.CryptProtectData.argtypes = (
            ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
        )
        ok = crypt32.CryptProtectData(
            ctypes.byref(source_blob), "Unlock configuration", None, None, None, 0,
            ctypes.byref(result_blob),
        )
    else:
        crypt32.CryptUnprotectData.argtypes = (
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
        )
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source_blob), None, None, None, None, 0, ctypes.byref(result_blob)
        )

    if not ok:
        raise SecureStorageError(f"Windows DPAPI failed ({ctypes.get_last_error()})")
    try:
        return ctypes.string_at(result_blob.pbData, result_blob.cbData)
    finally:
        kernel32.LocalFree(result_blob.pbData)


def protect(data: bytes) -> bytes:
    return _crypt(data, protect=True)


def unprotect(data: bytes) -> bytes:
    return _crypt(data, protect=False)
