#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
超星学习通 —— 账号密码登录（无需手动复制 Cookie）
==================================================
登录流程（经真实登录页 JS 实测，2026-10）：
  1. GET  https://passport2.chaoxing.com/login?fid=&refer=http%3A%2F%2Fi.chaoxing.com
     取得会话 Cookie（JSESSIONID / route）。
  2. 账号与密码字段经内部保护层封装后提交（算法与密钥由 cx_guard 管理，
     不在本模块中以明文形式出现）。
  3. POST https://passport2.chaoxing.com/fanyalogin
        fid, uname=AES(账号), password=AES(密码), refer, t=true,
        forbidotherlogin=0, validate="", doubleFactorLogin=0,
        independentId=0, independentNameId=0
  4. 返回 JSON：{"status": true, "msg": "登录成功"} 即成功，会话里带上登录 Cookie。

本模块只依赖标准库 + requests，加密细节由 cx_guard / cx_crypto 提供。
"""

import re
import json

import requests

import cx_guard

LOGIN_PAGE = "https://passport2.chaoxing.com/login?fid=&refer=http%3A%2F%2Fi.chaoxing.com"
LOGIN_API = "https://passport2.chaoxing.com/fanyalogin"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class LoginError(Exception):
    """登录失败（消息可直接展示给用户）"""


def chaoxing_login(username, password, fid="-1", timeout=20, session=None):
    """超星学习通账号密码登录。

    参数：
      username: 手机号 / 学习通账号 / 邮箱
      password: 密码
      fid:      学校/机构 ID，不知道就留 "-1"（手机号登录一般可用）

    返回：
      (cookies_dict, msg)   cookies_dict 可直接传给 ChaoxingClient
    异常：
      LoginError 携带给用户看的中文原因
    """
    username = (username or "").strip()
    password = (password or "").strip()
    if not username or not password:
        raise LoginError("请填写账号和密码。")

    s = session or requests.Session()
    s.headers.update({
        "User-Agent": DEFAULT_UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://passport2.chaoxing.com/login?fid=&refer=http%3A%2F%2Fi.chaoxing.com",
        "X-Requested-With": "XMLHttpRequest",
    })

    try:
        page = s.get(LOGIN_PAGE, timeout=timeout)
        page.encoding = "utf-8"
    except requests.RequestException as e:
        raise LoginError(f"无法打开超星登录页，请检查网络：{e}")

    if not page.text:
        raise LoginError("超星登录页返回为空，请稍后重试。")

    payload = {
        "fid": str(fid or "-1"),
        "uname": cx_guard.secure_field(username),
        "password": cx_guard.secure_field(password),
        "refer": "http%3A%2F%2Fi.chaoxing.com",
        "t": "true",
        "forbidotherlogin": "0",
        "validate": "",
        "doubleFactorLogin": "0",
        "independentId": "0",
        "independentNameId": "0",
    }

    try:
        r = s.post(LOGIN_API, data=payload, timeout=timeout)
    except requests.RequestException as e:
        raise LoginError(f"登录请求失败，请检查网络：{e}")

    try:
        data = r.json()
    except Exception:
        # 有些情况返回 HTML（如被风控拦截）
        if "验证码" in r.text or "captcha" in r.text.lower():
            raise LoginError("登录需要图形验证码，请改用「Cookie 方式」导入登录态。")
        raise LoginError("登录接口返回异常，请稍后重试（可能被风控拦截）。")

    if not data.get("status"):
        msg = str(data.get("msg") or data.get("msg2") or "").strip() or "登录失败"
        if "验证码" in msg or "captcha" in msg.lower():
            raise LoginError("登录需要图形验证码，请改用「Cookie 方式」导入登录态。")
        if "冻结" in msg or "错误" in msg:
            raise LoginError(f"登录失败：{msg}")
        raise LoginError(f"登录失败：{msg}")

    cookies = requests.utils.dict_from_cookiejar(s.cookies)

    # 部分部署在跳转后才下发 _uid/_d 等 Cookie，登录成功后补访问一次首页
    if not cookies.get("_uid") or not cookies.get("fid"):
        for url in ("https://i.chaoxing.com/base", "https://i.chaoxing.com"):
            try:
                s.get(url, timeout=timeout, allow_redirects=True)
            except requests.RequestException:
                continue
            cookies = requests.utils.dict_from_cookiejar(s.cookies)
            if cookies.get("_uid") and cookies.get("fid"):
                break

    # 登录成功的判据：必须有 uid 且有 fid（学习通业务接口依赖它们）
    if not cookies.get("_uid") and not cookies.get("uid"):
        raise LoginError("登录返回成功，但没有拿到登录 Cookie，请改用「Cookie 方式」。")
    if not cookies.get("fid"):
        raise LoginError("登录成功但缺少 fid（学校信息），请填写学校 ID 后重试，或改用「Cookie 方式」。")

    return cookies, str(data.get("msg") or "登录成功")


def cookies_to_header(cookies):
    """把 dict 形式的 Cookie 拼成请求头字符串（便于测试/展示）"""
    return "; ".join(f"{k}={v}" for k, v in cookies.items())
