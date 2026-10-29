# -*- coding: utf-8 -*-
"""密钥派生：cookie/session.dat 的加密密钥。

设计（2026-10-29 定稿）：
    软件没有任何解锁门。登录态文件用「本机绑定密钥」加解密 ——
    同一台电脑 + 同一个系统账户可以重新推导出来，换机或换账户就推不出来，
    所以文件即使被拷走也是废数据。

    历史版本留下的接口（master / cookie_key / profile_key 等）保留为空实现，
    只为让旧版加密文件仍能按顺序尝试解密，读到后会重写成当前格式。
"""

import cx_crypto
import cx_guard

_PROVISIONAL_LABEL = b"cx.subkey.cookie.machine.v1"


# ------------------------------------------------------------------ 主密钥（已停用）
def master():
    """旧版主密钥：本版本不使用，恒为 None（兼容旧调用点）。"""
    return None


def mk_cookie_key():
    """旧版「主密钥派生 Cookie 子密钥」：已停用。"""
    return None


def cookie_key():
    """旧版 CookieKey 带来的独立密钥：已停用。"""
    return None


def profile_key():
    """旧版设备记录子密钥：已停用。"""
    return None


def set_master(mk, src=""):
    """兼容旧调用点：现在不保存任何主密钥。"""
    return None


def lock():
    """兼容旧调用点：内存里本来就没有常驻密钥。"""
    return None


# ------------------------------------------------------------------ 本机绑定密钥
def provisional_key():
    """本机绑定派生密钥：Cookie 文件唯一的加解密密钥来源。

    计算机名 + 系统账户 + MachineGuid + 系统盘卷序列号 → HMAC-SHA256。
    单向派生，无法反推，也不落盘。
    """
    return cx_crypto.hmac_sha256(cx_guard.machine_secret(), _PROVISIONAL_LABEL)


def vault_key(tier="machine"):
    """按档位取密钥：machine（当前）/ mk、cookie（旧文件兼容，恒 None）。"""
    if tier == "machine":
        return provisional_key()
    if tier == "mk":
        return mk_cookie_key()
    return cookie_key()


def write_tier():
    """写入档位：固定 machine。"""
    return "machine"


def cookie_writable():
    """能否写入加密 Cookie 文件：永远可以。"""
    return True


def cookie_readable():
    """能否读取已保存的 Cookie：永远可以（换机/换账户由密码学层挡住）。"""
    return True


def ready():
    """兼容旧调用点：始终就绪。"""
    return True


def access_level():
    """兼容旧调用点：不再有分级，恒为 full。"""
    return "full"
