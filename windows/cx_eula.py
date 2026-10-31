#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
首次启动的许可与免责声明
==========================
只在第一次打开软件时弹出一次；用户点「同意并继续」后写一个标记文件，
之后不再打扰。标记文件里只有版本号和时间，不含任何个人信息。

标记优先写在程序目录（绿色软件习惯）；目录不可写时退到用户本地目录，
这样放在 Program Files 之类的只读位置也不会每次都弹。
"""

import os
import sys
import json
import datetime

EULA_VERSION = 3
FILE_NAME = ".eula.ok"          # 程序目录里的标记
FALLBACK_DIR = "ChaoxingHelper"  # %LOCALAPPDATA% 下的兜底目录

TITLE = "软件许可与免责声明"

BODY = """超星学习通 · 未完成作业 / 考试提取
版本 1.0 · MIT License

在使用本软件之前，请完整阅读以下条款。点击「同意并继续」表示你已阅读、理解并接受全部内容；如果不接受，请点击「退出」，软件将不会运行。

一、软件用途

本软件是一个「只读」的时间管理辅助工具，用于汇总你自己账号下的课程作业与考试截止时间。软件只发送读取请求，不提交作业、不参加考试、不修改学习通上的任何数据。

二、账号与服务条款

登录凭证由你本人提供，软件不保存密码。使用本软件可能与你所在学校的管理规定或学习通的服务条款存在冲突，是否使用、如何使用由你自行判断并承担全部责任。

请勿将本软件用于自动签到、刷课、代做、批量爬取他人数据等用途。

三、用途限定

本软件仅供编程学习与技术交流（例如了解网页结构、练习 Python / Java 开发），不作为日常使用的工具，也不代表作者对学习通及其所属平台的任何立场或建议。

请在下载、获取或编译后 24 小时内删除本软件及其全部副本（包括源码、安装包与可执行文件）。如果你需要长期管理自己的作业与考试时间，请直接使用学习通官方客户端或学校提供的渠道。

继续保留或使用本软件，即视为你已自行评估相关风险，并同意自行承担由此产生的全部后果。

四、数据与隐私

· 登录态只加密保存在本机（AES-256-CTR + HMAC-SHA256 完整性校验），不上传、不同步；
· 软件没有服务器、没有账号体系、不含任何遥测或统计上报；
· 软件不写操作日志，不记录课程名、作业名、截止时间，也不保存原始网页内容；
· 加密密钥与这台电脑绑定：换电脑或重装系统后需重新登录一次，原登录态无法迁移。

五、免责

本软件按「现状」提供，不附带任何明示或暗示的担保，包括但不限于可用性、准确性、适合作某一特定用途。

因使用或无法使用本软件所导致的任何直接或间接损失（包括但不限于错过作业或考试、账号异常、数据丢失、设备故障），作者不承担任何责任。

六、许可

本软件以 MIT 许可证发布：你可以自由使用、修改、分发，保留版权与许可声明即可。完整条款见随软件附带的 LICENSE 文件。

七、条款变更

条款可能随版本更新而变化。更新后的条款会在同一位置展示，并需要重新确认。

继续使用即视为你已阅读、理解并同意上述全部条款。"""


def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _primary_path():
    return os.path.join(_app_dir(), FILE_NAME)


def _fallback_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, FALLBACK_DIR, FILE_NAME)


def _read_version(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return int(data.get("v", 0) or 0)
    except Exception:
        return 0


def accepted():
    """当前版本是否已被同意过。"""
    for p in (_primary_path(), _fallback_path()):
        if _read_version(p) >= EULA_VERSION:
            return True
    return False


def accept():
    """记录「已同意」；返回 True 表示写成功了。"""
    payload = {
        "v": EULA_VERSION,
        "at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    for p in (_primary_path(), _fallback_path()):
        try:
            d = os.path.dirname(p)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            return True
        except OSError:
            continue
    return False
