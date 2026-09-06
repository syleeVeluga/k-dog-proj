"""Current-user Windows DPAPI vault; ciphertext is excluded from data backups."""

import ctypes
from ctypes import wintypes
import json
import os

from fastapi import HTTPException

from app.storage import uid


PROVIDERS = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def protect(data: bytes, *, decrypt=False) -> bytes:
    if os.name != "nt":
        raise HTTPException(409, "이 로컬 키 저장소는 Windows 서비스 계정의 DPAPI가 필요합니다.")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    # UI forbidden; never CRYPTPROTECT_LOCAL_MACHINE.
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise HTTPException(409, "서비스 계정의 키 보호/복호화를 확인하세요.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def state(store, provider):
    with store.connect() as db:
        row = db.execute("SELECT detail_json FROM changes WHERE action='secret.change' AND target=? ORDER BY rowid DESC LIMIT 1", (provider,)).fetchone()
    return json.loads(row[0]) if row else None


def credential(store, provider):
    from app.gemini import ProviderError
    if store:
        # Serialize the metadata/ciphertext read with rotation across API and worker processes.
        with store.connect(write=True) as db:
            row = db.execute("SELECT detail_json FROM changes WHERE action='secret.change' AND target=? ORDER BY rowid DESC LIMIT 1", (provider,)).fetchone()
            if row:
                saved = json.loads(row[0])
                if not saved["available"]:
                    raise ProviderError("developer_settings_required")
                try:
                    return protect(store.path(f"secrets/{saved['reference']}.bin").read_bytes(), decrypt=True).decode(), saved["reference"]
                except (OSError, ValueError, HTTPException):
                    raise ProviderError("developer_settings_required") from None
    value = os.environ.get(PROVIDERS.get(provider, ""), "")
    if not value:
        raise ProviderError("developer_settings_required")
    return value, "environment"


def available(store, provider):
    saved = state(store, provider)
    if saved:
        return saved["available"] and store.path(f"secrets/{saved['reference']}.bin").is_file()
    return bool(os.environ.get(PROVIDERS.get(provider, ""), ""))


def change(store, provider, value, actor):
    reference = uid()
    with store.connect(write=True) as db:
        if value is not None:
            encrypted = protect(value.encode())
            path = store.path(f"secrets/{reference}.bin")
            path.parent.mkdir(exist_ok=True)
            with path.open("xb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
        store.audit(db, actor, provider, "secret.change", {"reference": reference, "available": value is not None})
        # Commit the revocation before removing bytes. A failed unlink cannot reactivate a key.
        db.commit()
        # Keep the write fence until retired-file cleanup completes.
        db.execute("BEGIN IMMEDIATE")
        active = {json.loads(r[0])["reference"] for r in db.execute(
            "SELECT detail_json FROM changes WHERE rowid IN (SELECT MAX(rowid) FROM changes WHERE action='secret.change' GROUP BY target)")}
        for path in store.path("secrets").glob("*.bin") if store.path("secrets").exists() else []:
            if path.stem not in active:
                path.unlink(missing_ok=True)
    return {"provider": provider, "reference": reference, "available": value is not None}


def connection_test(store, provider, actor):
    from app.gemini import BASE, ProviderError, request
    reference, status = "unavailable", "developer_settings_required"
    try:
        key, reference = credential(store, provider)
        url = {"gemini": BASE + "/v1beta/models?pageSize=1", "openai": "https://api.openai.com/v1/models",
               "anthropic": "https://api.anthropic.com/v1/models?limit=1"}[provider]
        request("GET", url, key, provider=provider)
        status = "connected"
    except ProviderError as exc:
        status = exc.code
    result = {"provider": provider, "reference": reference, "status": status}
    with store.connect(write=True) as db:
        store.audit(db, actor, provider, "secret.test", result)
    return result
