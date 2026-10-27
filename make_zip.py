#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成发布用的 zip：只用白名单，个人隐私文件永远不会被打进去。

用法： python make_zip.py
产物： 超星作业提取.zip（与脚本同目录）

白名单 = exe + 源码 + 图标 + 打包脚本；
CookieKey / .cookiekey.* / cookie/ / device/ / debug/ / *.dat / 自检日志
一律排除，并且只要白名单里意外混进这类文件就立刻中止（不生成 zip）。
"""
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "超星作业提取"

# ---- 白名单：只有这些会被打包 ----
FILES = [
    NAME + ".exe",
    "README.md",
    "LICENSE",
    "docs/preview.png",
    "build_exe.bat",
    "make_zip.py",
    "requirements.txt",
    "app.py",
    "chaoxing_extractor.py",
    "cx_crypto.py",
    "cx_eula.py",
    "cx_guard.py",
    "cx_env.py",
    "cx_keyring.py",
    "cx_login.py",
    "cx_peer.py",
    "cx_vault.py",
]
ASSET_DIR = "assets"
ASSET_EXTS = (".png", ".ico")

# ---- 隐私闸门：命中任何一条就拒绝打包 ----
BAD_DIRS = ("cookie", "device", "keys", "debug", "__pycache__", ".workbuddy",
            "build-tk", "dist", ".build-venv", ".pkg")
BAD_WORDS = ("cookiekey", "session", "debug", "selftest")
BAD_EXTS = (".dat", ".bak", ".log", ".json", ".db", ".sqlite", ".ini")

# ---- 只用来提示「这些隐私文件已被排除」，不会打包 ----
PRIVATE_HINTS = [
    os.path.join("keys", "CookieKey"), os.path.join("keys", ".cookiekey.lock"),
    "CookieKey", ".cookiekey.lock",
    "cookie/session.dat",
    os.path.join("device", "keys.dat"), os.path.join("device", "items.dat"),
    os.path.join("device", "members.dat"),
    "selftest_log.txt", ".eula.ok", "debug",
]


def bad_reason(arc):
    """返回命中的原因，空字符串表示安全。"""
    parts = arc.replace("\\", "/").split("/")
    low = arc.lower()
    for d in BAD_DIRS:
        if d in parts:
            return "隐私目录 " + d
    base = os.path.basename(low)
    for w in BAD_WORDS:
        if w in base:
            return "疑似隐私文件（%s）" % w
    if low.endswith(BAD_EXTS):
        return "疑似数据文件 %s" % os.path.splitext(low)[1]
    return ""


def collect():
    targets = []
    for f in FILES:
        if os.path.isfile(f):
            targets.append(f)
        else:
            print("  [跳过] 缺少 %s" % f)
    if os.path.isdir(ASSET_DIR):
        for f in sorted(os.listdir(ASSET_DIR)):
            p = os.path.join(ASSET_DIR, f)
            if os.path.isfile(p) and f.lower().endswith(ASSET_EXTS):
                targets.append(p)
    return targets


def main():
    os.chdir(HERE)
    print("=" * 52)
    print("  生成发布包 %s.zip（仅白名单文件）" % NAME)
    print("=" * 52)

    if not os.path.isfile(NAME + ".exe"):
        print("[错误] 没找到 %s.exe，请先运行 build_exe.bat 打包。" % NAME)
        return 1

    targets = collect()
    blocked = [(t, bad_reason(t)) for t in targets if bad_reason(t)]
    if blocked:
        print("[错误] 白名单里混进了隐私文件，已中止（没有生成 zip）：")
        for t, why in blocked:
            print("   %s  <- %s" % (t, why))
        return 1

    out = NAME + ".zip"
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for t in targets:
            z.write(t, t.replace(os.sep, "/"))

    size = os.path.getsize(out) / 1048576.0
    print("已写入 %d 个文件：%.1f MB" % (len(targets), size))
    for t in targets:
        print("   + " + t.replace(os.sep, "/"))

    present = [p for p in PRIVATE_HINTS if os.path.exists(p)]
    if present:
        print("\n以下隐私文件已排除，不会打包：")
        for p in present:
            print("   - " + p.replace(os.sep, "/"))
    print("\n完成：%s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
