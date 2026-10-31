#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
内部保护层
============
两个职责：
  1. 传输密钥的碎片化装配 —— 密钥不以明文常量、也不以连续字符串的形式存在于
     源码或可执行文件中，运行时按片段还原；对外只暴露语义化的封装函数。
  2. 本地数据混淆 —— 对落盘的会话文件做整块置换（位置相关流），
     配合上层加密，使文件既无可识别头，也无固定字段偏移。

说明：混淆不等于加密，它的目标是让「随手打开/搜索/比对」难以得到有效信息；
真正的机密性由 cx_vault 的加密与完整性校验保证。
"""

import os
import sys
import hmac
import hashlib
import getpass
import platform

import cx_crypto

# ------------------------------------------------------------------ 密钥碎片
# 每项：(片段字节, 掩码)；还原时按段反序并逐字节异或，段间再加一个位置偏移。
_FRAGMENTS = (
    (b"\xef\xe8\xb5\xf2", 0x9A),
    (b"\x59\x72\x51\x31", 0x3D),
    (b"\xa2\xf3\xc1\xde", 0xC1),
    (b"\x00\x16\x12\x0c", 0x27),
)


def _assemble():
    out = bytearray()
    for i, (chunk, mask) in enumerate(_FRAGMENTS):
        shift = ((i + 1) * 0x1D) & 0xFF
        out.extend(bytes(b ^ mask ^ shift for b in chunk[::-1]))
    return bytes(out)


def secure_field(text):
    """对登录字段做传输层封装（算法与密钥同网页端一致，仅不暴露细节）。"""
    k = _assemble()
    return cx_crypto.aes_cbc_encrypt_b64(text, k, k)


# ------------------------------------------------------------------ 本机指纹
def machine_secret():
    """本机指纹：计算机名 + 系统账户 + MachineGuid + 系统盘卷序列号。"""
    parts = [platform.node() or "", getpass.getuser() or ""]
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
                guid, _ = winreg.QueryValueEx(k, "MachineGuid")
                parts.append(str(guid))
        except Exception:
            pass
        try:
            import ctypes
            serial = ctypes.c_ulong(0)
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                "C:\\", None, 0, ctypes.byref(serial), None, None, None, 0
            )
            if ok:
                parts.append(str(serial.value))
        except Exception:
            pass
    else:
        try:
            with open("/etc/machine-id") as f:
                parts.append(f.read().strip())
        except Exception:
            pass
    return "\x1f".join(parts).encode("utf-8")


# ------------------------------------------------------------------ 数据混淆
_BLOCK = 32


def _stream():
    return hashlib.sha256(machine_secret() + b"\x8f\xc2\x11\x4b\x07\xe6\x39\xd4").digest()


def scramble(data):
    """整块置换：按 32 字节分块，用本机相关流异或，块序号参与计算。

    该变换是自反的（再调用一次即还原）。
    """
    key = _stream()
    out = bytearray(len(data))
    for off in range(0, len(data), _BLOCK):
        ks = hmac.new(key, off.to_bytes(8, "big"), hashlib.sha256).digest()
        n = min(_BLOCK, len(data) - off)
        for j in range(n):
            out[off + j] = data[off + j] ^ ks[j]
    return bytes(out)


def unscramble(data):
    return scramble(data)
