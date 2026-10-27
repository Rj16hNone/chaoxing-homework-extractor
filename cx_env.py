#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设备与环境标识
==============
提供两类底层信息：
  1. 枚举当前连接的外部存储设备（按固件序列号识别，与盘内文件、盘符无关）；
  2. 生成本机 / 手工录入设备的稳定标识（统一为 SHA-256 摘要）。

设备标识来源优先级：设备序列号（SerialNumber）> 设备实例路径（PNPDeviceID）。
两者都来自设备固件/枚举信息，复制盘内文件不会改变标识。
"""

import json
import hashlib
import subprocess

# 枚举外部接口的物理磁盘，并顺带取盘符（仅用于展示）
_PS_SCAN = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_DiskDrive | Where-Object { $_.InterfaceType -eq 'USB' } | ForEach-Object {
  $d = $_
  $letters = @()
  foreach ($p in (Get-CimAssociatedInstance -InputObject $d -ResultClassName Win32_DiskPartition)) {
    foreach ($l in (Get-CimAssociatedInstance -InputObject $p -ResultClassName Win32_LogicalDisk)) {
      $letters += $l.DeviceID
    }
  }
  [pscustomobject]@{
    Model   = $d.Model
    Serial  = "$($d.SerialNumber)".Trim()
    PNP     = $d.PNPDeviceID
    SizeGB  = [math]::Round($d.Size / 1GB, 1)
    Letters = ($letters -join ',')
  }
} | ConvertTo-Json -Depth 3
"""


LAST_ERROR = ""   # 最近一次枚举失败的原因（供界面提示）

def _run_ps(script, timeout=20):
    global LAST_ERROR
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
            capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if p.returncode != 0:
            LAST_ERROR = "PowerShell 退出码 %s" % p.returncode
        else:
            LAST_ERROR = ""
        return p.stdout.decode("utf-8", errors="ignore").strip()
    except Exception as e:
        LAST_ERROR = str(e)
        return ""


def _digest(hw_id):
    return hashlib.sha256(hw_id.encode("utf-8")).hexdigest()


def scan_devices():
    """返回当前连接的 USB 存储设备列表（按设备与环境标识）。"""
    raw = _run_ps(_PS_SCAN)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]

    devices = []
    for d in data:
        model = (d.get("Model") or "").strip()
        serial = (d.get("Serial") or "").strip()
        pnp = (d.get("PNP") or "").strip()
        if not (serial or pnp):
            continue
        # 设备身份：优先固件序列号；没有序列号时退回设备实例路径
        hw_id = "USB|%s|%s" % (model or "unknown", serial or pnp)
        devices.append({
            "model": model or "未知设备",
            "serial": serial,
            "pnp": pnp,
            "size_gb": d.get("SizeGB"),
            "letters": (d.get("Letters") or "").strip(),
            "hw_id": hw_id,
            "fp": _digest(hw_id),
        })
    return devices


# 周期性复核用的轻量查询：只取设备身份，不做分区 / 盘符关联（快得多）
_PS_IDS = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_DiskDrive | Where-Object { $_.InterfaceType -eq 'USB' } | ForEach-Object {
  [pscustomobject]@{
    Model  = $_.Model
    Serial = "$($_.SerialNumber)".Trim()
    PNP    = $_.PNPDeviceID
  }
} | ConvertTo-Json -Depth 2
"""


def scan_ids():
    """当前连接设备的标识列表（轻量版，供周期性复核使用）。

    返回 list  —— 查询成功（可能为空，表示确实没有设备）；
    返回 None  —— 查询失败，结果不可信（调用方本轮应放弃判断，
                  避免把一次偶发的枚举失败误当成「设备已移除」）。
    """
    raw = _run_ps(_PS_IDS, timeout=15)
    if not raw:
        return None if LAST_ERROR else []
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, dict):
        data = [data]
    fps = []
    for d in data:
        model = (d.get("Model") or "").strip()
        serial = (d.get("Serial") or "").strip()
        pnp = (d.get("PNP") or "").strip()
        if not (serial or pnp):
            continue
        fps.append(_digest("USB|%s|%s" % (model or "unknown", serial or pnp)))
    return fps


def machine_id():
    """本机稳定标识（计算机名 + 账户 + MachineGuid + 卷序列号 的摘要）。"""
    try:
        import cx_guard
        return _digest("PC|" + cx_guard.machine_secret().hex())
    except Exception:
        return ""


def derive_id(raw):
    """把手工录入的标识（设备序列号 / ID 等）归一化为摘要。"""
    text = (raw or "").strip().lower()
    if not text:
        return ""
    return _digest("EXT|" + text)


def mask_id(fp, head=10):
    if not fp:
        return "—"
    return fp[:head] + "…" + fp[-4:] if len(fp) > head + 4 else fp
