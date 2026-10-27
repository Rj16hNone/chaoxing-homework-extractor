#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设备记录库（受主密钥保护）
============================
记录加密保存在 device/items.dat，密钥来自 cx_keyring 的主密钥：
  - 主密钥只能通过已登记的设备解锁；
  - 未解锁时，记录既不能查看，也不能增删。

只读视图、容器混淆、完整性校验与 Cookie 会话仓库一致。
"""

import os
import sys
import json
import struct
import hashlib
import datetime

import cx_crypto
import cx_guard
import cx_env
import cx_keyring
import cx_vault

DIR_NAME = "device"
ITEMS_FILE = "items.dat"      # 当前文件名
LEGACY_FILE = "members.dat"    # 旧版文件名，仅用于读取兼容
SALT_LEN = 16


# ------------------------------------------------------------------ 路径
def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _paths(base_dir=None):
    d = base_dir or os.path.join(_app_dir(), DIR_NAME)
    return d, os.path.join(d, ITEMS_FILE)


def _read_path(base_dir=None):
    """优先读新文件名；只有它不存在时才回退到旧文件名。"""
    d, cur = _paths(base_dir)
    legacy = os.path.join(d, LEGACY_FILE)
    if not os.path.exists(cur) and os.path.exists(legacy):
        return legacy
    return cur


# ------------------------------------------------------------------ 密钥
def _derive(salt, legacy=False):
    """记录专用子密钥；CookieKey 只有 Cookie 权限，拿不到这把钥匙。"""
    key = cx_keyring.master() if legacy else cx_keyring.profile_key()
    if key is None:
        raise RuntimeError("locked")
    label = b"cx.members.kdf.v2" if legacy else b"cx.members.kdf.v3"
    material = cx_crypto.hmac_sha256(key, label + salt)
    dk = hashlib.scrypt(material, salt=salt, n=16384, r=8, p=1,
                        dklen=64, maxmem=128 * 1024 * 1024)
    return dk[:32], dk[32:]


# ------------------------------------------------------------------ 容器
def _seal(payload_bytes):
    salt = os.urandom(SALT_LEN)
    enc_key, mac_key = _derive(salt)
    nonce = os.urandom(12)
    ct = cx_crypto.aes_ctr_xor(payload_bytes, enc_key, nonce)
    tag = cx_crypto.hmac_sha256(mac_key, salt + nonce + ct)
    noise_len = os.urandom(1)[0] % 16
    inner = (
        bytes([noise_len]) + os.urandom(noise_len)
        + struct.pack(">I", len(ct)) + salt + nonce + tag + ct
    )
    return cx_guard.scramble(inner)


def _unseal(blob):
    if len(blob) < 1 + 4 + SALT_LEN + 12 + 32:
        return None
    inner = cx_guard.unscramble(blob)
    try:
        noise_len = inner[0]
        pos = 1 + noise_len
        ct_len = struct.unpack(">I", inner[pos:pos + 4])[0]
        pos += 4
        salt = inner[pos:pos + SALT_LEN]
        pos += SALT_LEN
        nonce = inner[pos:pos + 12]
        pos += 12
        tag = inner[pos:pos + 32]
        pos += 32
        ct = inner[pos:]
        if len(ct) != ct_len or ct_len <= 0:
            return None
    except Exception:
        return None
    for legacy in (False, True):
        try:
            enc_key, mac_key = _derive(salt, legacy=legacy)
        except Exception:
            continue
        if not cx_crypto.constant_time_eq(tag, cx_crypto.hmac_sha256(mac_key, salt + nonce + ct)):
            continue
        try:
            return json.loads(cx_crypto.aes_ctr_xor(ct, enc_key, nonce).decode("utf-8"))
        except Exception:
            return None
    return None


def _write(path, data):
    tmp = path + ".new"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    cx_vault.secure_file_permissions(os.path.dirname(path), path)


# ------------------------------------------------------------------ 状态
def state(base_dir=None, devices=None):
    """委托给密钥环：unregistered / locked / open。"""
    return cx_keyring.state(base_dir=base_dir, devices=devices)


def info(base_dir=None):
    st = cx_keyring.state(base_dir=base_dir, devices=[])
    if st["state"] == "unregistered":
        return None
    return {"display": st.get("display") or "已登记设备"}


# ------------------------------------------------------------------ 登记
def setup(device, base_dir=None):
    """登记管理设备；成功后初始化记录（含本机）。"""
    ok, msg = cx_keyring.register_device(device, base_dir=base_dir)
    if not ok:
        return False, msg

    existing = None
    try:
        existing = _unseal(open(_read_path(base_dir), "rb").read())
    except OSError:
        existing = None

    if not (isinstance(existing, dict) and isinstance(existing.get("members"), list)):
        members = [{
            "name": "本机",
            "type": "电脑",
            "fp": cx_env.machine_id(),
            "added_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        }]
        if not save_all(members, base_dir=base_dir):
            return False, "初始化失败"
    return True, msg


def reset(base_dir=None):
    """销毁登记与全部受保护数据。"""
    return cx_keyring.wipe(base_dir=base_dir)


# ------------------------------------------------------------------ 记录读写
def load_all(base_dir=None, device=None):
    """读取记录；未解锁或被篡改时返回 None。"""
    if not cx_keyring.ready():
        return None
    try:
        blob = open(_read_path(base_dir), "rb").read()
    except OSError:
        return []
    data = _unseal(blob)
    if not isinstance(data, dict):
        return None
    members = data.get("members")
    return members if isinstance(members, list) else []


def save_all(members, base_dir=None, device=None):
    if not cx_keyring.ready():
        return False
    dir_path, members_path = _paths(base_dir)
    os.makedirs(dir_path, exist_ok=True)
    payload = json.dumps(
        {"v": 2, "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         "members": members},
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        _write(members_path, _seal(payload))
        return True
    except Exception:
        return False


def add(name, type_, fp_raw, base_dir=None, device=None):
    """添加记录。fp_raw 可以是本机标识摘要，或设备序列号等原始文本。"""
    if not cx_keyring.ready():
        return False, "请先解锁后再操作"
    members = load_all(base_dir)
    if members is None:
        return False, "记录无法解密"
    fp = fp_raw if len(fp_raw or "") == 64 else cx_env.derive_id(fp_raw)
    if not fp:
        return False, "标识不能为空"
    if any(m.get("fp") == fp for m in members):
        return False, "该设备已在记录中"
    members.append({
        "name": (name or "未命名设备").strip(),
        "type": (type_ or "其他").strip(),
        "fp": fp,
        "added_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    ok = save_all(members, base_dir=base_dir)
    return (True, "已添加") if ok else (False, "保存失败")


def remove(index, base_dir=None, device=None):
    if not cx_keyring.ready():
        return False, "请先解锁后再操作"
    members = load_all(base_dir)
    if not members or not (0 <= index < len(members)):
        return False, "没有这条记录"
    members.pop(index)
    ok = save_all(members, base_dir=base_dir)
    return (True, "已删除") if ok else (False, "保存失败")
