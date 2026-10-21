"""AES-GCM ciphertext protected by a per-user key in the macOS login Keychain.

Use Security.framework directly: neither keys nor provider credentials enter argv.
The Keychain item is never replaced when access fails or ciphertext is damaged.
"""

import ctypes as c
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException


HEADER = b"KDOG-MAC-1"
AAD = b"K-DOG macOS vault v1"


def keychain_key(*, create=False, service="K-DOG API vault"):
    cf = c.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    sec = c.CDLL("/System/Library/Frameworks/Security.framework/Security")
    ref = c.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ref, c.c_char_p, c.c_uint32]
    cf.CFStringCreateWithCString.restype = ref
    cf.CFDataCreate.argtypes = [ref, ref, c.c_long]
    cf.CFDataCreate.restype = ref
    cf.CFDataGetLength.argtypes = [ref]
    cf.CFDataGetLength.restype = c.c_long
    cf.CFDataGetBytePtr.argtypes = [ref]
    cf.CFDataGetBytePtr.restype = ref
    cf.CFDictionaryCreate.argtypes = [ref, c.POINTER(ref), c.POINTER(ref), c.c_long, ref, ref]
    cf.CFDictionaryCreate.restype = ref
    cf.CFRelease.argtypes = [ref]
    cf.CFRelease.restype = None
    sec.SecItemCopyMatching.argtypes = [ref, c.POINTER(ref)]
    sec.SecItemCopyMatching.restype = c.c_int32
    sec.SecItemAdd.argtypes = [ref, c.POINTER(ref)]
    sec.SecItemAdd.restype = c.c_int32
    owned = []

    def constant(name):
        return ref.in_dll(sec, name).value

    def string(value):
        result = cf.CFStringCreateWithCString(None, value.encode("utf-8"), 0x08000100)
        owned.append(result)
        return result

    def dictionary(pairs):
        keys, values = zip(*pairs)
        result = cf.CFDictionaryCreate(None, (ref * len(keys))(*keys),
                                      (ref * len(values))(*values), len(keys), None, None)
        owned.append(result)
        return result

    try:
        base = [(constant("kSecClass"), constant("kSecClassGenericPassword")),
                (constant("kSecAttrService"), string(service)),
                (constant("kSecAttrAccount"), string("aes256-v1"))]
        query = dictionary([*base, (constant("kSecReturnData"), ref.in_dll(cf, "kCFBooleanTrue").value),
                            (constant("kSecMatchLimit"), constant("kSecMatchLimitOne"))])

        def read():
            result = ref()
            status = sec.SecItemCopyMatching(query, c.byref(result))
            if status == 0:
                try:
                    value = c.string_at(cf.CFDataGetBytePtr(result), cf.CFDataGetLength(result))
                    if len(value) != 32:
                        raise ValueError("invalid vault key")
                    return status, value
                finally:
                    cf.CFRelease(result)
            return status, None

        status, value = read()
        if status == -25300 and create:  # errSecItemNotFound
            value = AESGCM.generate_key(bit_length=256)
            buffer = c.create_string_buffer(value)
            data = cf.CFDataCreate(None, buffer, len(value))
            owned.append(data)
            status = sec.SecItemAdd(dictionary([*base, (constant("kSecValueData"), data)]), None)
            if status == -25299:  # Another process created the item; use its key.
                status, value = read()
        if status != 0:
            raise ValueError(f"Keychain status {status}")
        return value
    finally:
        for item in reversed(owned):
            if item:
                cf.CFRelease(item)


def protect(data: bytes, *, decrypt=False) -> bytes:
    try:
        if decrypt and (not data.startswith(HEADER) or len(data) < len(HEADER) + 12 + 16):
            raise ValueError("invalid ciphertext")
        key = keychain_key(create=not decrypt)
        if decrypt:
            offset = len(HEADER)
            return AESGCM(key).decrypt(data[offset:offset + 12], data[offset + 12:], AAD)
        nonce = os.urandom(12)
        return HEADER + nonce + AESGCM(key).encrypt(nonce, data, AAD)
    except (OSError, ValueError, InvalidTag):
        raise HTTPException(409, "macOS 로그인 키체인 접근과 이 Mac의 실행 계정을 확인하세요.") from None
