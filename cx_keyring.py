#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
密钥环（主密钥 + 解锁槽位）
==============================
设计目标：
  - Cookie 会话与硬件成员名单都由同一把 **主密钥(MK)** 加密；
  - MK 本身不落盘明文，而是被「解锁槽位」包裹：
      槽位 A：U 盘 —— 密钥材料 = 本机指纹 + U 盘原始序列号
      槽位 B：备份钥匙文件 —— 一个可复制到任何位置的独立文件（用口令保护）
  - 没有 U 盘、也没有备份钥匙，就拿不到 MK，两份数据都无法解密。
  - 例外（写入方向）：**创建 / 更新** Cookie 文件不需要任何解锁权限 ——
      未解锁时改用「机器绑定派生密钥」(provisional_key) 加密落盘；
      下次解锁后再读取，会自动重加密为正式的 Cookie 子密钥（见 cx_vault）。
      读取方向仍然必须解锁，因此这个例外不会让人在没有钥匙时看到 Cookie。
  - CookieKey：**独立的 32 字节随机密钥**，每台电脑只能创建一次，创建不需要 U 盘。
      存在 CookieKey 时，Cookie 文件一律用它加密（优先级高于主密钥派生）。
      该文件与本机指纹绑定（v3），只在创建它的电脑上可用；可在本机任意复制换目录。

备份钥匙文件（可移植）：
  文件内只有「用口令派生密钥包裹的 MK」，不含任何本机信息，
  因此可以放在任意文件夹 / 网盘 / 另一台电脑上，只要记得口令即可解封。
"""

import os
import sys
import json
import base64
import hashlib
import datetime

import cx_crypto
import cx_guard
import cx_hwid

DIR_NAME = "device"
STORE_FILE = "keys.dat"
BACKUP_MAGIC = b"CXBK1\x00"
BACKUP_VER_PASS = 1      # 有口令
BACKUP_VER_NOPASS = 2    # 无口令：文件本身即钥匙
COOKIE_KEY_NAME = "CookieKey"
COOKIE_KEY_MAGIC = b"CXCK1\x00"
COOKIE_KEY_VER_STANDALONE = 2     # v2：独立随机密钥（旧版，未绑机器）
COOKIE_KEY_VER_MACHINE = 3        # v3：绑本机指纹，复制到别的电脑无法解封
COOKIE_KEY_MARK = ".cookiekey.lock"   # 记录「本机已创建过」，保证只能创建一次
CK_DIRS_FILE = ".cookiekey.dirs"      # 额外自动检测目录
MASTER_LEN = 32
SALT_LEN = 16
PBKDF2_ROUNDS = 200000

_mk = None            # 内存中的主密钥（完整权限）
_mk_source = ""       # usb / backup
_ck = None            # 内存中的 Cookie 子密钥（受限权限）
_ck_source = ""       # cookiekey

# 周期复核：连续 N 次确认「钥匙不在」才收回权限，避免硬件枚举抖动导致误锁
WATCH_STRIKES = 2
WATCH_INTERVAL = 10   # 秒
_miss_usb = 0
_miss_ck = 0


# ------------------------------------------------------------------ 路径
def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _paths(base_dir=None):
    d = base_dir or os.path.join(_app_dir(), DIR_NAME)
    return d, os.path.join(d, STORE_FILE)


# ------------------------------------------------------------------ 加解封
def _derive(material, salt):
    dk = hashlib.scrypt(material, salt=salt, n=16384, r=8, p=1,
                        dklen=64, maxmem=128 * 1024 * 1024)
    return dk[:32], dk[32:]


def _wrap(mk, material):
    salt = os.urandom(SALT_LEN)
    enc, mac = _derive(material, salt)
    nonce = os.urandom(12)
    ct = cx_crypto.aes_ctr_xor(mk, enc, nonce)
    tag = cx_crypto.hmac_sha256(mac, salt + nonce + ct)
    return {
        "salt": salt.hex(), "nonce": nonce.hex(),
        "ct": ct.hex(), "tag": tag.hex(),
    }


def _unwrap(slot, material):
    try:
        salt = bytes.fromhex(slot["salt"])
        nonce = bytes.fromhex(slot["nonce"])
        ct = bytes.fromhex(slot["ct"])
        tag = bytes.fromhex(slot["tag"])
        enc, mac = _derive(material, salt)
        if not cx_crypto.constant_time_eq(tag, cx_crypto.hmac_sha256(mac, salt + nonce + ct)):
            return None
        mk = cx_crypto.aes_ctr_xor(ct, enc, nonce)
        return mk if len(mk) == MASTER_LEN else None
    except Exception:
        return None


def _usb_material(hw_id):
    return cx_crypto.hmac_sha256(cx_guard.machine_secret(), b"cx.keyring.usb.v1" + hw_id.encode("utf-8"))


# ------------------------------------------------------------------ 存储
def _read_store(base_dir=None):
    _, path = _paths(base_dir)
    try:
        blob = open(path, "rb").read()
    except OSError:
        return None
    try:
        data = json.loads(cx_guard.unscramble(blob).decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_store(data, base_dir=None):
    dir_path, path = _paths(base_dir)
    os.makedirs(dir_path, exist_ok=True)
    tmp = path + ".new"
    with open(tmp, "wb") as f:
        f.write(cx_guard.scramble(json.dumps(data, ensure_ascii=True).encode("utf-8")))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        import cx_vault
        cx_vault.secure_file_permissions(dir_path, path)
    except Exception:
        pass


# ------------------------------------------------------------------ 状态
def master():
    """当前内存中的主密钥（完整权限；未解锁则为 None）。"""
    return _mk


def unlocked():
    return _mk is not None


def source():
    return _mk_source


def access_level():
    """full=U盘/备份钥匙；cookie=仅有 CookieKey（受限）；none=未解锁。"""
    if _mk is not None:
        return "full"
    if _ck is not None:
        return "cookie"
    return "none"


def _subkey(label):
    if _mk is None:
        raise RuntimeError("locked")
    return cx_crypto.hmac_sha256(_mk, b"cx.subkey." + label)


def cookie_key():
    """Cookie 会话子密钥：完整解锁时由主密钥派生；仅有 CookieKey 时直接返回文件里的密钥。"""
    if _ck is not None:
        return _ck
    if _mk is not None:
        return _subkey(b"cookie.v1")
    return None


def members_key():
    """硬件成员子密钥：只能由主密钥派生（CookieKey 拿不到）。"""
    return _subkey(b"members.v1") if _mk is not None else None


def mk_cookie_key():
    """主密钥派生的 Cookie 子密钥（旧档位，仅用于兼容读取历史文件）。"""
    return _subkey(b"cookie.v1") if _mk is not None else None


# ------------------------------------------------------------------ 机器绑定密钥
_PROVISIONAL_LABEL = b"cx.subkey.cookie.machine.v1"


def provisional_key():
    """机器绑定派生密钥：不需要 U 盘、也不需要 CookieKey 即可得到。

    唯一用途是「还没解锁时也能把登录状态加密落盘」。它是单向派生、不可反推主密钥，
    但同一台电脑、同一个系统账户下可以被重新推导出来，强度明显低于主密钥派生，
    因此只用于写入；读取仍要求解锁。
    """
    return cx_crypto.hmac_sha256(cx_guard.machine_secret(), _PROVISIONAL_LABEL)


def vault_key(tier="cookie"):
    """Cookie 文件用的密钥。

    cookie  —— CookieKey 携带的独立密钥（优先，仅限本机）；
    mk      —— 主密钥派生的旧档位（仅兼容读取）；
    machine —— 机器绑定派生密钥（没钥匙时也能落盘）。
    """
    if tier == "machine":
        return provisional_key()
    if tier == "mk":
        return mk_cookie_key()
    return cookie_key()


def write_tier():
    """写入档位：cookie（正式子密钥）/ machine（机器绑定）。

    没有完整权限时先现场探一次程序目录里的 CookieKey —— 只要它在，
    就用它加密落盘，这样这份密文日后靠 CookieKey 就能解开；
    只有连 CookieKey 都没有时才退回机器绑定密钥。
    """
    if cookie_key() is None:
        auto_cookie_key()
    return "cookie" if cookie_key() is not None else "machine"


def cookie_writable():
    """创建 / 更新加密 Cookie 文件：任何状态都允许，无需 U 盘，也无需 CookieKey。"""
    return True


def cookie_readable():
    """读取已保存的 Cookie 是否允许：需要解锁（管理 U 盘 / 备份钥匙 / CookieKey）。"""
    return access_level() != "none"


def lock():
    """清除内存中的所有密钥（锁定）。"""
    global _mk, _mk_source, _ck, _ck_source, _miss_usb, _miss_ck
    _mk = None
    _mk_source = ""
    _ck = None
    _ck_source = ""
    _miss_usb = 0
    _miss_ck = 0


def set_master(mk, src):
    global _mk, _mk_source, _ck, _ck_source
    _mk = mk
    _mk_source = src
    _ck = None
    _ck_source = ""
    # 程序目录 / 检测目录里若有 CookieKey，仍然优先用它加密：
    # 这样即使插着 U 盘解锁，写出的 Cookie 文件也能被 CookieKey 读回
    #（CookieKey 与本机绑定，本机任意目录复制后仍可用）。
    p = find_cookie_key()
    if p:
        load_cookie_key(p)


def registered_display(base_dir=None):
    st = _read_store(base_dir)
    if not st:
        return ""
    return "管理 U 盘"      # 不显示具体型号/盘符


def state(base_dir=None, devices=None):
    """返回 {'state': unregistered|locked|open, 'device':..., 'display':...}"""
    st = _read_store(base_dir)
    if not st:
        return {"state": "unregistered", "device": None, "display": ""}

    usb = st.get("usb") or {}
    devs = cx_hwid.list_usb_devices() if devices is None else devices
    match = next((d for d in devs if d.get("fp") == usb.get("fp")), None)

    if match and _mk is None:
        try_unlock_usb([match], base_dir=base_dir)
    if _mk is not None:
        return {"state": "open", "device": match, "display": "管理 U 盘",
                "source": _mk_source}
    return {"state": "locked", "device": match, "display": "管理 U 盘"}


# ------------------------------------------------------------------ 注册 / 解锁
def register_usb(device, base_dir=None):
    """把 U 盘登记为解锁槽位。若已有主密钥则沿用，否则新建（旧名单会被重置）。"""
    if not device or not device.get("hw_id"):
        return False, "没有可注册的 U 盘"

    st = _read_store(base_dir)
    mk = _mk
    if mk is None and st:
        # 已注册过其它 U 盘：只有当前能解锁（旧盘在场）时才沿用它
        old = (st.get("usb") or {}).get("fp")
        if old == device.get("fp"):
            slot = (st.get("usb") or {}).get("slot") or {}
            mk = _unwrap(slot, _usb_material(device["hw_id"]))

    fresh = mk is None
    if fresh:
        mk = os.urandom(MASTER_LEN)

    slot = _wrap(mk, _usb_material(device["hw_id"]))
    data = {
        "v": 2,
        "usb": {
            "fp": device["fp"],
            "display": "管理 U 盘",     # 不记录/显示具体型号与盘符
            "slot": slot,
        },
        "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_store(data, base_dir)
    set_master(mk, "usb")
    return True, ("已注册" if not fresh else "已注册（新建主密钥）")


def try_unlock_usb(devices=None, base_dir=None):
    """尝试用当前 U 盘解封主密钥。"""
    st = _read_store(base_dir)
    if not st:
        return False
    usb = st.get("usb") or {}
    devs = cx_hwid.list_usb_devices() if devices is None else devices
    for d in devs:
        if d.get("fp") != usb.get("fp"):
            continue
        mk = _unwrap(usb.get("slot") or {}, _usb_material(d["hw_id"]))
        if mk:
            set_master(mk, "usb")
            return True
    return False


# ------------------------------------------------------------------ CookieKey
# 定位：**独立的 Cookie 钥匙**，不再从主密钥派生。
#   · 每台电脑必须且只能创建一次（建完写标记文件，之后拒绝再建）；
#   · v3 起与**本机指纹**绑定：文件只在这台电脑上能解，复制到别的电脑等于废文件；
#     同一台电脑上可以随意复制/换目录（自动检测目录就是为这个准备的）；
#   · 创建不需要 U 盘，也不需要任何解锁权限。
def cookie_key_path(base_dir=None):
    return os.path.join(_app_dir() if base_dir is None else base_dir, COOKIE_KEY_NAME)


def cookie_key_mark_path():
    return os.path.join(_app_dir(), COOKIE_KEY_MARK)


def _ck_kdf(salt):
    """旧版（v1/v2）包裹密钥：与机器无关，所以复制出去也能解。"""
    return (hashlib.sha256(b"cx.ck.1" + salt).digest()
            + hashlib.sha256(b"cx.ck.2" + salt).digest())


def _ck_kdf_machine(salt):
    """v3 包裹密钥：掺入本机指纹，换台电脑就解不出密钥。"""
    mat = cx_guard.machine_secret()
    return (cx_crypto.hmac_sha256(mat, b"cx.ck.m1" + salt)
            + cx_crypto.hmac_sha256(mat, b"cx.ck.m2" + salt))


def _ck_blob(ck, salt, nonce, version):
    dk = _ck_kdf_machine(salt) if version >= COOKIE_KEY_VER_MACHINE else _ck_kdf(salt)
    enc, mac = dk[:32], dk[32:]
    ct = cx_crypto.aes_ctr_xor(ck, enc, nonce)
    tag = cx_crypto.hmac_sha256(mac, salt + nonce + ct)
    return COOKIE_KEY_MAGIC + bytes([version]) + salt + nonce + tag + ct


def _ck_meta(path=None):
    """读出 (密钥, 版本号)；文件缺失 / 损坏 / 来自别的电脑都返回 (None, 0)。"""
    path = path or cookie_key_path()
    try:
        with open(path, "rb") as f:
            blob = f.read()
    except OSError:
        return None, 0
    if not blob.startswith(COOKIE_KEY_MAGIC):
        return None, 0
    pos = len(COOKIE_KEY_MAGIC)
    if len(blob) < pos + 1 + SALT_LEN + 12 + 32 + 32:
        return None, 0
    version = blob[pos]
    pos += 1
    salt = blob[pos:pos + SALT_LEN]
    pos += SALT_LEN
    nonce = blob[pos:pos + 12]
    pos += 12
    tag = blob[pos:pos + 32]
    pos += 32
    ct = blob[pos:]
    dk = _ck_kdf_machine(salt) if version >= COOKIE_KEY_VER_MACHINE else _ck_kdf(salt)
    enc, mac = dk[:32], dk[32:]
    if not cx_crypto.constant_time_eq(tag, cx_crypto.hmac_sha256(mac, salt + nonce + ct)):
        return None, version        # 版本号保留：便于区分「坏了」还是「别的电脑的」
    ck = cx_crypto.aes_ctr_xor(ct, enc, nonce)
    return (ck if len(ck) == 32 else None), version


def _ck_fp(ck):
    return cx_crypto.hmac_sha256(ck, b"cx.ck.fp")[:8].hex()


def upgrade_cookie_key_binding(path=None):
    """把旧版（v1/v2，未绑机器）的 CookieKey 原地重包为 v3（绑本机）。

    密钥本身不变，所以已加密的 Cookie 文件照旧能解；
    只是从此复制到别的电脑就解不开了。返回 True 表示做了升级。
    """
    path = path or find_cookie_key() or cookie_key_path()
    ck, ver = _ck_meta(path)
    if ck is None or ver >= COOKIE_KEY_VER_MACHINE:
        return False
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(12)
    blob = _ck_blob(ck, salt, nonce, COOKIE_KEY_VER_MACHINE)
    try:
        tmp = path + ".new"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def has_cookie_key(path=None):
    return os.path.exists(path or cookie_key_path())


def _first_present_ck():
    """优先返回本机可用的 CookieKey；都不行时返回第一个真实存在的文件。"""
    usable = find_cookie_key()
    if usable:
        return usable
    for p in scan_candidates():
        if os.path.exists(p):
            return p
    return cookie_key_path()


def cookie_key_state(path=None):
    """CookieKey 的创建状态。

    返回 {'exists','present','foreign','corrupt','legacy','version',
          'created_at','fp','locked','path'}
      exists  —— 能解出可用密钥（本机可用）
      present —— 文件在（可能属于别的电脑，也可能损坏）
      foreign —— 文件是绑定格式但解不开：基本等于「别的电脑创建的」
      locked  —— 本机已经创建过（有标记），即便文件暂时不在了也不允许再建
    """
    path = path or _first_present_ck()
    mark = None
    try:
        with open(cookie_key_mark_path(), "r", encoding="utf-8") as f:
            mark = json.load(f)
    except Exception:
        mark = None
    info = cookie_key_info(path)
    ck = _read_cookie_key(path) if info["present"] else None
    if mark is None and ck is not None:
        # 老版本装过 CookieKey：补一个标记，避免之后重复创建
        mark = {"created_at": "", "fp": _ck_fp(ck)}
        try:
            with open(cookie_key_mark_path(), "w", encoding="utf-8") as f:
                json.dump(mark, f)
        except OSError:
            pass
    return {
        "exists": ck is not None,
        "present": info["present"],
        "foreign": info["foreign"],
        "corrupt": info["corrupt"],
        "legacy": info["legacy"],
        "version": info["version"],
        "created_at": (mark or {}).get("created_at", ""),
        "fp": (mark or {}).get("fp", "") or (_ck_fp(ck) if ck else ""),
        "locked": bool(mark),
        "path": path,
    }


def create_cookie_key(path=None):
    """创建 CookieKey：独立的 32 字节随机密钥，每台电脑只能创建一次。

    落盘格式为 v3：用「本机指纹」包裹密钥，因此该文件只在创建它的这台电脑上可用。
    """
    path = path or cookie_key_path()
    if has_cookie_key(path):
        info = cookie_key_info(path)
        if info["foreign"]:
            return False, ("程序目录里的 CookieKey 是在另一台电脑上创建的，本机无法使用。\n"
                           "（Key 与本机硬件绑定，复制过来的文件只能留在原电脑用）")
        if info["usable"]:
            return False, "本机已有 CookieKey（每台电脑只能创建一次）。"
        return False, "程序目录里的 CookieKey 文件已损坏，请删除后重新创建。"
    if os.path.exists(cookie_key_mark_path()):
        return False, ("本机已经创建过 CookieKey，不能重复生成。\n"
                       "请把之前备份/复制的 CookieKey 放回程序目录即可继续使用。")
    ck = os.urandom(32)
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(12)
    blob = _ck_blob(ck, salt, nonce, COOKIE_KEY_VER_MACHINE)
    try:
        with open(path, "wb") as f:
            f.write(blob)
    except OSError as e:
        return False, "写入失败：%s" % e
    try:
        with open(cookie_key_mark_path(), "w", encoding="utf-8") as f:
            json.dump({
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "fp": _ck_fp(ck),
                "ver": COOKIE_KEY_VER_MACHINE,
            }, f)
    except OSError:
        pass
    return True, path


# ------------------------------------------------------------- 额外自动检测目录
def ck_dirs_path():
    return os.path.join(_app_dir(), CK_DIRS_FILE)


def extra_scan_dirs():
    try:
        with open(ck_dirs_path(), "r", encoding="utf-8") as f:
            dirs = json.load(f)
        return [d for d in dirs if isinstance(d, str) and d]
    except Exception:
        return []


def set_extra_scan_dirs(dirs):
    uniq = []
    for d in dirs:
        d = os.path.abspath(d)
        if d not in uniq:
            uniq.append(d)
    try:
        with open(ck_dirs_path(), "w", encoding="utf-8") as f:
            json.dump(uniq, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return uniq


def add_scan_dir(d):
    return set_extra_scan_dirs(extra_scan_dirs() + [d])


def remove_scan_dir(d):
    target = os.path.abspath(d)
    return set_extra_scan_dirs([x for x in extra_scan_dirs() if os.path.abspath(x) != target])


def scan_candidates():
    """按优先级列出会去查找 CookieKey 的位置。"""
    out = [cookie_key_path()]
    for d in extra_scan_dirs():
        p = os.path.join(d, COOKIE_KEY_NAME)
        if p not in out:
            out.append(p)
    return out


def find_cookie_key():
    """在程序目录 + 额外检测目录里找第一个可用的 CookieKey，返回路径。"""
    for p in scan_candidates():
        if _read_cookie_key(p) is not None:
            return p
    return None


def _read_cookie_key(path=None):
    """从文件解出 Cookie 子密钥。

    文件缺失 / 被替换 / 损坏 / **来自别的电脑** 一律返回 None。
    """
    ck, _ver = _ck_meta(path)
    return ck


def cookie_key_info(path=None):
    """CookieKey 文件的细粒度状态，供界面显示用。

    version: 0=不可读, 2=旧版(未绑机器), 3=绑本机
    foreign: 文件在，但解不开，且格式是本机绑定的 —— 基本等于「别的电脑创建的」
    corrupt: 文件在，解不开，格式是旧版 —— 基本等于「文件损坏」
    """
    path = path or find_cookie_key() or cookie_key_path()
    ck, ver = _ck_meta(path)
    present = os.path.exists(path)
    usable = ck is not None
    return {
        "path": path,
        "present": present,
        "usable": usable,
        "version": ver,
        "foreign": bool(present and not usable and ver >= COOKIE_KEY_VER_MACHINE),
        "corrupt": bool(present and not usable and 0 < ver < COOKIE_KEY_VER_MACHINE),
        "legacy": bool(usable and ver < COOKIE_KEY_VER_MACHINE),
    }


def load_cookie_key(path=None):
    """载入 CookieKey：只授予 Cookie 读写权限，不触碰成员与主密钥。

    path 省略时按「程序目录 → 额外检测目录」顺序自动查找。
    若读到的是旧版（未绑机器）的钥匙，会顺手原地升级为绑定本机的格式。
    """
    global _ck, _ck_source
    if path is None:
        path = find_cookie_key()
        if path is None:
            return False
    ck, ver = _ck_meta(path)
    if ck is None:
        return False
    _ck = ck
    _ck_source = "cookiekey"
    if ver < COOKIE_KEY_VER_MACHINE:
        # 老钥匙：密钥本身不变（已加密的 Cookie 照旧能解），
        # 只是从此复制到别的电脑就解不开了。
        upgrade_cookie_key_binding(path)
    return True


def auto_cookie_key(path=None):
    """没有完整权限时，现场探测一次 CookieKey。

    「已保存的登录状态」只依赖 CookieKey：只要探到就可以直接使用，
    不需要插 U 盘、也不需要备份钥匙。会扫描程序目录与所有额外检测目录。
    """
    if access_level() != "none":
        return access_level() == "cookie"
    return load_cookie_key(path)


def refresh_cookie_key(path=None):
    """定期/入口处调用：CookieKey 出现就自动载入，消失就自动降级。

    返回 True 表示当前可读 Cookie（含完整权限）。
    """
    if _mk is not None:
        return True
    if _ck is not None:
        if _cookie_key_intact(path):
            return True
        lock()                      # 文件被移走 / 换掉：立即失效
    return auto_cookie_key(path)


# ------------------------------------------------------------------ 备份钥匙
def _backup_kdf(passphrase, salt):
    """备份钥匙的包裹密钥：有口令用 PBKDF2，无口令用固定派生（文件即钥匙）。"""
    if passphrase:
        return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, PBKDF2_ROUNDS, 64)
    return (hashlib.sha256(b"cx.bak.nopass.1" + salt).digest()
            + hashlib.sha256(b"cx.bak.nopass.2" + salt).digest())


def create_backup(path, passphrase, base_dir=None):
    """生成可移植的备份钥匙文件（需先解锁）。passphrase 为空表示不设口令。"""
    if _mk is None:
        return False, "请先插入管理 U 盘解锁"
    salt = os.urandom(SALT_LEN)
    enc, mac = (lambda dk: (dk[:32], dk[32:]))(_backup_kdf(passphrase or "", salt))
    nonce = os.urandom(12)
    ct = cx_crypto.aes_ctr_xor(_mk, enc, nonce)
    tag = cx_crypto.hmac_sha256(mac, salt + nonce + ct)
    ver = BACKUP_VER_PASS if passphrase else BACKUP_VER_NOPASS
    blob = BACKUP_MAGIC + bytes([ver]) + salt + nonce + tag + ct
    try:
        with open(path, "wb") as f:
            f.write(blob)
    except OSError as e:
        return False, "写入失败：%s" % e
    return True, "备份钥匙已生成"


def unlock_with_backup(path, passphrase, base_dir=None):
    """用备份钥匙文件解封主密钥（可在任意路径使用）。"""
    try:
        blob = open(path, "rb").read()
    except OSError as e:
        return False, "无法读取文件：%s" % e
    if not blob.startswith(BACKUP_MAGIC):
        return False, "这不是本程序的备份钥匙文件"
    ver = blob[len(BACKUP_MAGIC)]
    if ver not in (BACKUP_VER_PASS, BACKUP_VER_NOPASS):
        return False, "备份文件版本不支持"
    pos = len(BACKUP_MAGIC) + 1
    if len(blob) < pos + SALT_LEN + 12 + 32 + MASTER_LEN:
        return False, "文件不完整"
    salt = blob[pos:pos + SALT_LEN]; pos += SALT_LEN
    nonce = blob[pos:pos + 12]; pos += 12
    tag = blob[pos:pos + 32]; pos += 32
    ct = blob[pos:]
    dk = _backup_kdf((passphrase or "") if ver == BACKUP_VER_PASS else "", salt)
    enc, mac = dk[:32], dk[32:]
    if not cx_crypto.constant_time_eq(tag, cx_crypto.hmac_sha256(mac, salt + nonce + ct)):
        return False, "口令错误或文件已损坏"
    mk = cx_crypto.aes_ctr_xor(ct, enc, nonce)
    if len(mk) != MASTER_LEN:
        return False, "密钥格式不正确"
    set_master(mk, "backup")
    return True, "已用备份钥匙解锁"


# ------------------------------------------------------------------ 周期复核
def _registered_fp(base_dir=None):
    st = _read_store(base_dir) or {}
    return (st.get("usb") or {}).get("fp")


def _cookie_key_intact(path=None):
    """内存里的 CookieKey 是否仍然有效（文件还在，且能解出同一把子密钥）。"""
    if _ck is None:
        return True
    if path is None:
        path = find_cookie_key() or cookie_key_path()
    ck = _read_cookie_key(path)
    return ck is not None and cx_crypto.constant_time_eq(ck, _ck)


def revalidate(devices=None, base_dir=None, ck_path=None):
    """复核当前钥匙是否还在；不在就立即收回权限（lock）。

    规则：
      · U 盘解锁 —— 注册的 U 盘不在场则锁定（连续 WATCH_STRIKES 次确认才算，
        避免一次枚举抖动误锁；枚举失败的那一轮直接跳过判断）；
      · CookieKey 解锁 —— 文件被移走 / 更换 / 损坏则锁定；
      · 备份钥匙解锁 —— 钥匙是可复制的独立文件，不因硬件变化失效，不做检查；
      · 本来就没有钥匙 —— 只探测 CookieKey（很便宜）：探到就升到受限权限，
        因为「已保存的登录状态」只需要 CookieKey 即可使用。

    返回 {'before': 复核前级别, 'level': 复核后级别, 'changed': 是否变化, 'reason': 原因}
    """
    global _miss_usb, _miss_ck
    before = access_level()
    reason = ""

    if _mk is not None and _mk_source == "usb":
        fp = _registered_fp(base_dir)
        if devices is not None:
            fps = [d.get("fp") for d in devices]
        else:
            fps = cx_hwid.list_usb_fps()
        if fps is None:                 # 枚举失败：本轮不判断，不计入缺失次数
            _miss_usb = 0
            reason = "usb_unknown"
        elif not fp:
            _miss_usb += 1                  # 连注册记录都没了
        elif fp in fps:
            _miss_usb = 0
        else:
            _miss_usb += 1

        if _miss_usb >= WATCH_STRIKES:
            _miss_usb = 0
            lock()
            reason = "usb_removed"
            # 本机还留着 CookieKey 的话，退回「只能读 Cookie」的受限权限
            if load_cookie_key(ck_path):
                reason = "usb_removed_fallback"

    elif _ck is not None:
        if _cookie_key_intact(ck_path):
            _miss_ck = 0
        else:
            _miss_ck += 1
            if _miss_ck >= WATCH_STRIKES:
                _miss_ck = 0
                lock()
                reason = "cookiekey_missing"

    else:
        # 当前没有任何钥匙：只做一次廉价的 CookieKey 探测（不枚举硬件）。
        # 探到就升到受限权限 —— 已保存的登录状态只依赖 CookieKey。
        if auto_cookie_key(ck_path):
            reason = "cookiekey_found"

    after = access_level()
    return {"before": before, "level": after,
            "changed": before != after, "reason": reason}


def wipe(base_dir=None):
    """销毁注册与所有受保护数据。"""
    dir_path, store = _paths(base_dir)
    ok = False
    for p in (store, store + ".new", os.path.join(dir_path, "members.dat"),
              os.path.join(dir_path, "members.dat.new"),
              os.path.join(dir_path, "key.dat"),    # key.dat 为旧版遗留文件
              cookie_key_path()):                   # 子密钥一并销毁
        try:
            os.remove(p)
            ok = True
        except OSError:
            pass
    try:
        if os.path.isdir(dir_path) and not os.listdir(dir_path):
            os.rmdir(dir_path)
    except OSError:
        pass
    lock()
    return ok
