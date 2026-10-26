#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
登录状态加密仓库（唯一可读写 Cookie 的模块）
================================================
职责边界（隐私设计）：
  - 只有本模块可以「写」Cookie：登录成功后加密落盘到 cookie/session.dat；
  - 其他模块只能通过 load_session() 拿到 ReadOnlyCookies —— 只读、不可修改、
    不可序列化、不可打印（repr 自动脱敏）；
  - 除本模块外，程序不会把 Cookie 写入任何日志、剪贴板、临时文件或网络。

保护层次（自内向外）：
  1. 加密：AES-256-CTR，密钥 = scrypt(子密钥, 随机 salt)；
     子密钥两档：正式子密钥（主密钥派生 / CookieKey 携带）与机器绑定派生密钥
     （仅用于未解锁时的初次落盘，解锁后自动重加密为正式子密钥）；
  2. 完整性：HMAC-SHA256（encrypt-then-MAC），校验失败一律视为无会话；
  3. 混淆：整块置换 + 随机长度的前置噪声，文件无固定头部、无固定字段偏移，
     直接查看只是一串随机字节；换机器/换账户无法还原。

写入方向（创建 / 更新）不需要任何解锁权限；读取方向必须解锁。

重要说明（不做过度承诺）：
  密钥由本机指纹派生，因此把 session.dat 拷到别的电脑/别的系统账户上无法解密；
  但如果攻击者已经能以「同一个 Windows 账户」在你的电脑上运行任意程序，
  他理论上可以复用本模块的解密逻辑。此种情况下请依赖系统账户权限与磁盘加密。
"""

import os
import sys
import json
import time
import struct
import shutil
import datetime
from collections.abc import Mapping

import cx_crypto
import cx_guard
import cx_keyring

DIR_NAME = "cookie"
FILE_NAME = "session.dat"
SALT_LEN = 16
NONCE_LEN = 12
TAG_LEN = 32
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1


class CookieAccessError(PermissionError):
    """对只读 Cookie 的非法写操作"""


# ================================================================ 只读视图
class ReadOnlyCookies(Mapping):
    """只读 Cookie 视图。

    - 支持 dict(cookies) / cookies["k"] / 迭代（供 HTTP 客户端组包使用）
    - 禁止改、删、清空、序列化、拷贝；打印自动脱敏
    """

    __slots__ = ("_data", "_created")

    def __init__(self, data):
        object.__setattr__(self, "_data", {str(k): str(v) for k, v in dict(data).items()})
        object.__setattr__(self, "_created", time.time())

    # ---- 读取（唯一允许的操作）
    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def get(self, key, default=None):
        return self._data.get(key, default)

    # ---- 脱敏输出
    def __repr__(self):
        return f"<ReadOnlyCookies 已加载 {len(self._data)} 项（内容已脱敏，禁止导出）>"

    __str__ = __repr__

    # ---- 一切写操作直接拒绝
    def _deny(self, *args, **kwargs):
        raise CookieAccessError("Cookie 为只读对象，禁止修改 / 删除 / 清空")

    __setitem__ = _deny
    __delitem__ = _deny
    update = _deny
    clear = _deny
    pop = _deny
    popitem = _deny
    setdefault = _deny

    # ---- 禁止序列化 / 拷贝（防止被落盘或转手）
    def __reduce__(self):
        raise CookieAccessError("Cookie 为只读对象，禁止序列化 / 拷贝")

    def __copy__(self):
        raise CookieAccessError("Cookie 为只读对象，禁止拷贝")

    def __deepcopy__(self, memo):
        raise CookieAccessError("Cookie 为只读对象，禁止拷贝")


# ================================================================ 路径与密钥
def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _paths(base_dir=None):
    d = base_dir or os.path.join(_app_dir(), DIR_NAME)
    return d, os.path.join(d, FILE_NAME)


def _derive_keys(salt, legacy=False, tier="cookie"):
    """会话密钥。

    tier=cookie   —— 正式 Cookie 子密钥（主密钥派生 / CookieKey 携带），未解锁时不可用；
    tier=machine  —— 机器绑定派生密钥，用于「未解锁也能创建」的初次落盘；
    legacy=True   —— 旧版 v2 格式，直接用主密钥派生（仅兼容读取）。
    """
    key = cx_keyring.master() if legacy else cx_keyring.vault_key(tier)
    if key is None:
        raise RuntimeError("locked")
    label = b"cx.vault.kdf.v2" if legacy else b"cx.vault.kdf.v3"
    material = cx_crypto.hmac_sha256(key, label + salt)
    dk = __import__("hashlib").scrypt(
        material, salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        dklen=64, maxmem=128 * 1024 * 1024,
    )
    return dk[:32], dk[32:]


# ================================================================ 写盘加固
def _harden_permissions(dir_path, file_path):
    """把文件权限收紧到「仅当前用户」。失败则回滚，绝不让用户失去读取能力。"""
    if os.name != "nt":
        try:
            os.chmod(dir_path, 0o700)
            os.chmod(file_path, 0o600)
        except OSError:
            pass
        return
    user = os.environ.get("USERNAME") or __import__("getpass").getuser()
    domain = os.environ.get("USERDOMAIN")
    account = f"{domain}\\{user}" if domain else user
    try:
        import subprocess
        subprocess.run(
            ["icacls", dir_path, "/grant:r", f"{account}:(OI)(CI)F", "/inheritance:r"],
            capture_output=True, timeout=15,
        )
        subprocess.run(
            ["icacls", file_path, "/grant:r", f"{account}:F", "/inheritance:r"],
            capture_output=True, timeout=15,
        )
    except Exception:
        return
    try:
        with open(file_path, "rb") as f:
            f.read(1)
    except OSError:
        for p in (file_path, dir_path):
            try:
                subprocess.run(["icacls", p, "/reset"], capture_output=True, timeout=15)
            except Exception:
                pass


def _atomic_write(path, data):
    tmp = path + ".new"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def secure_file_permissions(dir_path, file_path):
    """对外暴露的权限加固（供其他受保护模块复用）。"""
    _harden_permissions(dir_path, file_path)


# ================================================================ 对外 API
def save_session(cookies, extra=None, base_dir=None):
    """加密保存登录状态。返回 bool（失败不抛异常，避免影响主流程）。

    创建 / 更新不需要任何解锁权限：程序目录里有 CookieKey 就用它加密，
    完整解锁时用主密钥派生的正式子密钥，两者都没有才退回机器绑定密钥；
    等下次解锁读取时会透明重加密为正式密钥。
    """
    try:
        dir_path, file_path = _paths(base_dir)
        os.makedirs(dir_path, exist_ok=True)

        payload = {
            "version": 2,
            "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cookies": {str(k): str(v) for k, v in dict(cookies).items()},
        }
        if extra:
            payload.update({k: v for k, v in extra.items() if k != "cookies"})
        plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        salt = os.urandom(SALT_LEN)
        nonce = os.urandom(NONCE_LEN)
        enc_key, mac_key = _derive_keys(salt, tier=cx_keyring.write_tier())
        ciphertext = cx_crypto.aes_ctr_xor(plaintext, enc_key, nonce)
        tag = cx_crypto.hmac_sha256(mac_key, salt + nonce + ciphertext)

        # 随机长度噪声 + 长度字段，使文件长度与字段偏移都不固定
        noise_len = os.urandom(1)[0] % 16
        inner = (
            bytes([noise_len])
            + os.urandom(noise_len)
            + struct.pack(">I", len(ciphertext))
            + salt + nonce + tag + ciphertext
        )
        _atomic_write(file_path, cx_guard.scramble(inner))
        _harden_permissions(dir_path, file_path)
        return True
    except Exception:
        return False


def load_session(base_dir=None):
    """读取并解密登录状态，返回 ReadOnlyCookies；无文件/被篡改/未解锁均返回 None。

    读取属于「使用」方向，必须已解锁（管理 U 盘 / 备份钥匙 / CookieKey）。
    若文件是未解锁时用机器绑定密钥创建的，解锁读到后会自动重加密为正式密钥。
    """
    # 入口处自检一次 CookieKey：程序目录里只要有它就直接可用，不依赖调用方顺序。
    # 已经载入的密钥（可能来自别的路径）不去动它，避免把调用方的选择覆盖掉。
    if cx_keyring.access_level() == "none":
        try:
            cx_keyring.auto_cookie_key()
        except Exception:
            pass
    if not cx_keyring.cookie_readable():
        return None
    _, file_path = _paths(base_dir)
    try:
        with open(file_path, "rb") as f:
            blob = f.read()
    except OSError:
        return None

    min_len = 1 + 4 + SALT_LEN + NONCE_LEN + TAG_LEN
    if len(blob) < min_len:
        return None

    inner = cx_guard.unscramble(blob)
    try:
        noise_len = inner[0]
        pos = 1 + noise_len
        if pos + 4 > len(inner):
            return None
        ct_len = struct.unpack(">I", inner[pos:pos + 4])[0]
        pos += 4
        if len(inner) < pos + SALT_LEN + NONCE_LEN + TAG_LEN:
            return None
        salt = inner[pos:pos + SALT_LEN]
        pos += SALT_LEN
        nonce = inner[pos:pos + NONCE_LEN]
        pos += NONCE_LEN
        tag = inner[pos:pos + TAG_LEN]
        pos += TAG_LEN
        ciphertext = inner[pos:]
        if len(ciphertext) != ct_len or ct_len <= 0:
            return None
    except Exception:
        return None

    data = None
    used_legacy = False
    used_tier = ""
    # 依次尝试：CookieKey → 主密钥派生（旧档）→ 机器绑定 → 旧版 v2
    candidates = []
    if cx_keyring.cookie_key() is not None:
        candidates.append((False, "cookie"))
    if cx_keyring.master() is not None:
        candidates.append((False, "mk"))
    candidates.append((False, "machine"))
    candidates.append((True, "cookie"))
    for legacy, tier in candidates:
        try:
            enc_key, mac_key = _derive_keys(salt, legacy=legacy, tier=tier)
        except Exception:
            continue
        if not cx_crypto.constant_time_eq(tag, cx_crypto.hmac_sha256(mac_key, salt + nonce + ciphertext)):
            continue
        try:
            plaintext = cx_crypto.aes_ctr_xor(ciphertext, enc_key, nonce)
            data = json.loads(plaintext.decode("utf-8"))
            used_legacy, used_tier = legacy, tier
        except Exception:
            data = None
        break

    if not isinstance(data, dict):
        return None
    cookies = data.get("cookies") or {}
    if not isinstance(cookies, dict) or not cookies:
        return None
    # 旧格式 / 机器绑定 / 主密钥派生：能读到就透明升级为 CookieKey 加密
    if (used_legacy or used_tier in ("machine", "mk")) and cx_keyring.cookie_key() is not None:
        try:
            extra = {k: v for k, v in data.items() if k not in ("cookies", "version")}
            save_session(cookies, extra=extra, base_dir=base_dir)
        except Exception:
            pass
    return ReadOnlyCookies(cookies)


def session_info(base_dir=None):
    """只返回非敏感的会话元信息，不暴露任何 Cookie 内容。"""
    _, file_path = _paths(base_dir)
    if not os.path.exists(file_path):
        return None
    cookies = load_session(base_dir)
    if cookies is None:
        return None
    return {"count": len(cookies), "size": os.path.getsize(file_path)}


def has_session(base_dir=None):
    return load_session(base_dir) is not None


def session_file_exists(base_dir=None):
    """只判断文件是否存在（不解密、不读取内容）。"""
    return os.path.exists(_paths(base_dir)[1])


def clear_session(base_dir=None):
    """删除本地登录状态（仅在用户明确「退出登录」时调用）。"""
    dir_path, file_path = _paths(base_dir)
    ok = False
    for p in (file_path, file_path + ".new"):
        try:
            os.remove(p)
            ok = True
        except OSError:
            pass
    try:
        if os.path.isdir(dir_path) and not os.listdir(dir_path):
            shutil.rmtree(dir_path, ignore_errors=True)
    except OSError:
        pass
    return ok
