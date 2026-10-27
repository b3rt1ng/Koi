from __future__ import annotations

import hashlib
import hmac
import os
import struct
import time

_NEGOTIATE_UNICODE = 0x00000001
_REQUEST_TARGET = 0x00000004
_NEGOTIATE_NTLM = 0x00000200
_NEGOTIATE_ALWAYS_SIGN = 0x00008000
_NEGOTIATE_EXTENDED_SESSIONSECURITY = 0x00080000
_NEGOTIATE_TARGET_INFO = 0x00800000

_FLAGS = (
    _NEGOTIATE_UNICODE
    | _REQUEST_TARGET
    | _NEGOTIATE_NTLM
    | _NEGOTIATE_ALWAYS_SIGN
    | _NEGOTIATE_EXTENDED_SESSIONSECURITY
    | _NEGOTIATE_TARGET_INFO
)

_EPOCH_DELTA = 116_444_736_000_000_000


def _filetime() -> bytes:
    return struct.pack('<Q', int(time.time() * 10_000_000) + _EPOCH_DELTA)


def _sec_buf(length: int, offset: int) -> bytes:
    return struct.pack('<HHI', length, length, offset)


def nt_hash(password: str) -> bytes:
    return hashlib.new('md4', password.encode('utf-16-le')).digest()


def _response_key(nt_h: bytes, user: str, domain: str) -> bytes:
    return hmac.new(nt_h, (user.upper() + domain).encode('utf-16-le'), 'md5').digest()


def negotiate() -> bytes:
    return (
        b'NTLMSSP\x00'
        + struct.pack('<I', 1)
        + struct.pack('<I', _FLAGS)
        + _sec_buf(0, 0)
        + _sec_buf(0, 0)
    )


def _parse_challenge(data: bytes) -> tuple[bytes, int, bytes]:
    if data[:8] != b'NTLMSSP\x00' or struct.unpack_from('<I', data, 8)[0] != 2:
        raise ValueError('invalid NTLM Type 2 message')

    challenge = data[24:32]
    flags = struct.unpack_from('<I', data, 20)[0]

    target_info = b''
    if len(data) >= 48:
        info_len, _, info_off = struct.unpack_from('<HHI', data, 40)
        target_info = data[info_off:info_off + info_len]

    return challenge, flags, target_info


def authenticate(type2: bytes, user: str, nt_h: bytes, domain: str = '') -> bytes:
    server_challenge, _, target_info = _parse_challenge(type2)
    resp_key = _response_key(nt_h, user, domain)

    client_challenge = os.urandom(8)
    blob = (
        b'\x01\x01\x00\x00\x00\x00\x00\x00'
        + _filetime()
        + client_challenge
        + b'\x00\x00\x00\x00'
        + target_info
        + b'\x00\x00\x00\x00'
    )

    nt_proof = hmac.new(resp_key, server_challenge + blob, 'md5').digest()
    nt_response = nt_proof + blob
    lm_response = hmac.new(resp_key, server_challenge + client_challenge, 'md5').digest() + client_challenge

    domain_b = domain.encode('utf-16-le')
    user_b = user.encode('utf-16-le')
    ws_b = b''
    sk_b = b''

    base = 64
    off = base
    payload = [domain_b, user_b, ws_b, lm_response, nt_response, sk_b]
    offsets = []
    for part in payload:
        offsets.append(off)
        off += len(part)

    header = b'NTLMSSP\x00' + struct.pack('<I', 3)
    header += _sec_buf(len(lm_response), offsets[3])
    header += _sec_buf(len(nt_response), offsets[4])
    header += _sec_buf(len(domain_b), offsets[0])
    header += _sec_buf(len(user_b), offsets[1])
    header += _sec_buf(len(ws_b), offsets[2])
    header += _sec_buf(len(sk_b), offsets[5])
    header += struct.pack('<I', _FLAGS)

    return header + b''.join(payload)
