"""Current-user Windows DPAPI vault; ciphertext is excluded from data backups."""

import ctypes
from ctypes import wintypes
import json
import os

from fastapi import HTTPException

from app.storage import now, uid


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


def target(provider, slot="primary"):
    if slot not in ("primary", "backup") or (slot == "backup" and provider != "gemini"):
        raise ValueError("invalid credential slot")
    return provider if slot == "primary" else "gemini:backup"


def _state(db, name):
    row = db.execute("SELECT detail_json FROM changes WHERE action='secret.change' AND target=? ORDER BY rowid DESC LIMIT 1", (name,)).fetchone()
    return json.loads(row[0]) if row else None


def _developer(db, actor):
    row = db.execute("SELECT active,role FROM users WHERE username=?", (actor,)).fetchone()
    if not row or not row["active"] or row["role"] != "developer":
        raise HTTPException(403, "활성 개발자 계정만 키를 관리할 수 있습니다.")


def _registration_required(store):
    return store is not None and store.path("secrets/gemini-registration-required").exists()


def state(store, provider, slot="primary"):
    with store.connect() as db:
        return _state(db, target(provider, slot))


def _credential(store, db, provider, slot):
    from app.gemini import ProviderError
    saved = _state(db, target(provider, slot)) if db is not None else None
    reason = "unregistered"
    if saved:
        reason = "removed"
        if saved["available"]:
            try:
                return protect(store.path(f"secrets/{saved['reference']}.bin").read_bytes(), decrypt=True).decode(), saved["reference"]
            except OSError:
                reason = "file_unavailable"
            except (ValueError, HTTPException):
                reason = "decrypt_failed"
    elif slot == "primary":
        if provider == "gemini" and _registration_required(store):
            reason = "restore_required"
        else:
            value = os.environ.get(PROVIDERS.get(provider, ""), "")
            if value:
                return value, "environment"
    raise ProviderError("developer_settings_required", credential_reason=reason)


def credential(store, provider, slot="primary"):
    if store:
        # Serialize the metadata/ciphertext read with rotation across API and worker processes.
        with store.connect(write=True) as db:
            return _credential(store, db, provider, slot)
    return _credential(None, None, provider, slot)


def credential_for_reference(store, reference):
    from app.gemini import ProviderError
    with store.connect(write=True) as db:
        for slot in ("primary", "backup"):
            try:
                value, current = _credential(store, db, "gemini", slot)
            except ProviderError:
                continue
            if current == reference:
                return value, current
    raise ProviderError("developer_settings_required")


def available(store, provider):
    saved = state(store, provider)
    if saved:
        return saved["available"] and store.path(f"secrets/{saved['reference']}.bin").is_file()
    return bool(os.environ.get(PROVIDERS.get(provider, ""), "")) and not (provider == "gemini" and _registration_required(store))


def _slot_state(store, db, slot):
    from app.gemini import ProviderError
    name = target("gemini", slot)
    saved = _state(db, name)
    reference = saved["reference"] if saved else ("environment" if slot == "primary" and os.environ.get("GEMINI_API_KEY") and not _registration_required(store) else None)
    source = "vault" if saved else "environment" if reference else "none"
    reason = None
    try:
        _credential(store, db, "gemini", slot)
    except ProviderError as exc:
        reason = exc.credential_reason
    row = db.execute("SELECT detail_json,happened_at FROM changes WHERE action='secret.test' AND target=? "
                     "AND json_extract(detail_json,'$.reference')=? ORDER BY rowid DESC LIMIT 1", (name, reference)).fetchone()
    test = json.loads(row[0]) if row else None
    if test:
        test.setdefault("slot", slot)
        test.setdefault("tested_at", row["happened_at"])
    return {"slot": slot, "reference": reference, "source": source, "available": reason is None,
            "unavailable_reason": reason, "last_test": test}


def slot_states(store):
    with store.connect(write=True) as db:
        return [_slot_state(store, db, slot) for slot in ("primary", "backup")]


def change(store, provider, value, actor, *, slot="primary", expected_reference=None, check_reference=False):
    from app.gemini import ProviderError
    target(provider, slot)
    slots = ("primary", "backup") if provider == "gemini" and value is None and not check_reference else (slot,)
    result = None
    with store.connect(write=True) as db:
        _developer(db, actor)
        if check_reference and _slot_state(store, db, slot)["reference"] != expected_reference:
            raise HTTPException(409, "키 상태가 변경되었습니다. 새 상태를 확인하고 다시 입력하세요.")
        if provider == "gemini" and value is not None:
            try:
                other, _ = _credential(store, db, provider, "backup" if slot == "primary" else "primary")
            except ProviderError:
                other = None
            if value == other:
                raise HTTPException(409, "주키와 예비키에는 서로 다른 키를 등록하세요.")
        reference = uid()
        if value is not None:
            encrypted = protect(value.encode())
            path = store.path(f"secrets/{reference}.bin")
            path.parent.mkdir(exist_ok=True)
            with path.open("xb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
        for selected in slots:
            selected_ref = reference if selected == slot else uid()
            store.audit(db, actor, target(provider, selected), "secret.change", {"reference": selected_ref, "available": value is not None})
        if check_reference:
            result = _slot_state(store, db, slot)
        # Commit the revocation before removing bytes. A failed unlink cannot reactivate a key.
        db.commit()
        # Keep the write fence until retired-file cleanup completes.
        db.execute("BEGIN IMMEDIATE")
        active = {json.loads(r[0])["reference"] for r in db.execute(
            "SELECT detail_json FROM changes WHERE rowid IN (SELECT MAX(rowid) FROM changes WHERE action='secret.change' GROUP BY target)")}
        for path in store.path("secrets").glob("*.bin") if store.path("secrets").exists() else []:
            if path.stem not in active:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass  # Revoked metadata remains authoritative; a later key change retries cleanup.
    return result or {"provider": provider, "reference": reference, "available": value is not None}


def connection_test(store, provider, actor, slot="primary"):
    from app.gemini import BASE, ProviderError, request
    reference, status = "unavailable", "developer_settings_required"
    try:
        with store.connect(write=True) as db:
            _developer(db, actor)
            saved = _state(db, target(provider, slot))
            if saved:
                reference = saved["reference"]
            key, reference = _credential(store, db, provider, slot)
        url = {"gemini": BASE + "/v1beta/models?pageSize=1", "openai": "https://api.openai.com/v1/models",
               "anthropic": "https://api.anthropic.com/v1/models?limit=1"}[provider]
        request("GET", url, key, provider=provider)
        status = "connected"
    except ProviderError as exc:
        status = exc.code
    result = {"provider": provider, "slot": slot, "reference": reference, "status": status, "tested_at": now()}
    with store.connect(write=True) as db:
        store.audit(db, actor, target(provider, slot), "secret.test", result)
    return result
