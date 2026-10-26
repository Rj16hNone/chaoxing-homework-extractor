#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底层加密原语（纯标准库实现，便于打包成单文件 exe）
=====================================================
- AES-128/192/256 分组加密（FIPS-197）
- CBC 模式（超星登录页密码加密用）
- CTR 模式（本地会话文件加密用）

所有实现均已用官方测试向量校验：
  FIPS-197 C.1/C.3、NIST SP 800-38A F.2.1/F.5.5
"""

import base64
import hmac
import hashlib

# ------------------------------------------------------------------ 常量表
_SBOX = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
]
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x1b) & 0xFF
    return a


def key_expansion(key):
    """密钥扩展，支持 16 / 24 / 32 字节（AES-128/192/256），返回 Nr+1 组轮密钥。"""
    if isinstance(key, str):
        key = key.encode("utf-8")
    if len(key) not in (16, 24, 32):
        raise ValueError("AES 密钥长度必须为 16 / 24 / 32 字节")
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[i * 4:i * 4 + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        temp = list(w[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]                 # RotWord
            temp = [_SBOX[b] for b in temp]            # SubWord
            temp[0] ^= _RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            temp = [_SBOX[b] for b in temp]
        w.append([w[i - nk][j] ^ temp[j] for j in range(4)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(nr + 1)]


def encrypt_block(block, round_keys):
    """加密单个 16 字节分组（状态按列存储：s[c][r] = state[r][c]）"""
    s = [list(block[c * 4:c * 4 + 4]) for c in range(4)]
    nr = len(round_keys) - 1

    def add_round_key(rk):
        for c in range(4):
            for r in range(4):
                s[c][r] ^= rk[c * 4 + r]

    add_round_key(round_keys[0])
    for rnd in range(1, nr + 1):
        s = [[_SBOX[s[c][r]] for r in range(4)] for c in range(4)]          # SubBytes
        s = [[s[(c + r) % 4][r] for r in range(4)] for c in range(4)]       # ShiftRows
        if rnd != nr:                                                       # MixColumns
            for c in range(4):
                a0, a1, a2, a3 = s[c]
                s[c][0] = _xtime(a0) ^ (_xtime(a1) ^ a1) ^ a2 ^ a3
                s[c][1] = a0 ^ _xtime(a1) ^ (_xtime(a2) ^ a2) ^ a3
                s[c][2] = a0 ^ a1 ^ _xtime(a2) ^ (_xtime(a3) ^ a3)
                s[c][3] = (_xtime(a0) ^ a0) ^ a1 ^ a2 ^ _xtime(a3)
        add_round_key(round_keys[rnd])
    return bytes(s[c][r] for c in range(4) for r in range(4))


# ------------------------------------------------------------------ CBC
def aes_cbc_encrypt_raw(plaintext, key, iv):
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")
    if isinstance(key, str):
        key = key.encode("utf-8")
    if isinstance(iv, str):
        iv = iv.encode("utf-8")
    pad = 16 - len(plaintext) % 16
    data = plaintext + bytes([pad]) * pad
    round_keys = key_expansion(key)
    prev = iv
    out = bytearray()
    for i in range(0, len(data), 16):
        block = bytes(a ^ b for a, b in zip(data[i:i + 16], prev))
        enc = encrypt_block(block, round_keys)
        out.extend(enc)
        prev = enc
    return bytes(out)


def aes_cbc_encrypt_hex(plaintext, key, iv):
    return aes_cbc_encrypt_raw(plaintext, key, iv).hex()


def aes_cbc_encrypt_b64(plaintext, key, iv):
    return base64.b64encode(aes_cbc_encrypt_raw(plaintext, key, iv)).decode()


# ------------------------------------------------------------------ CTR
def aes_ctr_xor(data, key, nonce, initial_counter=0):
    """AES-CTR：nonce 为 12 字节，计数器 32 位大端；加密与解密是同一操作。"""
    if isinstance(key, str):
        key = key.encode("utf-8")
    if len(nonce) != 12:
        raise ValueError("CTR nonce 必须为 12 字节")
    round_keys = key_expansion(key)
    out = bytearray()
    counter = initial_counter & 0xFFFFFFFF
    for i in range(0, len(data), 16):
        ks = encrypt_block(nonce + counter.to_bytes(4, "big"), round_keys)
        chunk = data[i:i + 16]
        out.extend(bytes(a ^ b for a, b in zip(chunk, ks)))
        counter = (counter + 1) & 0xFFFFFFFF
    return bytes(out)


# ------------------------------------------------------------------ 工具
def hmac_sha256(key, message):
    return hmac.new(key, message, hashlib.sha256).digest()


def constant_time_eq(a, b):
    return hmac.compare_digest(a, b)
