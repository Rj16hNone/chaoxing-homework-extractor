#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
超星学习通 —— 未完成作业 / 考试 提取器（核心逻辑）
=================================================
仅依赖 requests + beautifulsoup4。

以下接口均经过真实账号实测验证（2026-10）：
  1) 课程列表（需要 Cookie 里的 fid）:
       GET https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata
           ?courseType=1&courseFid=<fid>
       解析 div.course 卡片：span.course-name=课程名，隐藏域 courseId/clazzId，
       卡片链接里还带 cpi。
  2) 课程详情（拿 workEnc 等）:
       GET https://mooc1.chaoxing.com/visit/stucoursemiddle
           ?courseid=<courseId>&clazzid=<clazzId>&ismooc2=1&v=2
       隐藏域取 cpi / workEnc / enc / openc。
  3) 作业列表:
       GET https://mooc1.chaoxing.com/mooc2/work/list
           ?courseId&classId&cpi&ut=s&openc&enc=<workEnc>&t=<毫秒时间戳>
           &stuenc=<enc>&isdisplaytable=2&status=0
       解析 .bottomList ul li：p.overHidden2=名称，p.status=状态(未交/已完成)，
       div.time=「剩余X小时Y分钟」，li 的 data 属性=作业链接。
  4) 作业详情（精确起止时间）:
       打开作业链接，正则提取「作答时间:<em>开始</em>至<em>截止</em>」。
  5) 考试列表（按用户返回全部考试，无需逐课程请求; 每页 12 条）:
       GET https://mooc1.chaoxing.com/exam-ans/exam/test/examcode/examlist
           ?cpi=<cpi>&status=-1&start=<偏移>
       解析 tr.dataTr：编号/考试名称/考试时间/时长/考试状态/作答状态/分数/方式/操作。

安全边界：本工具只发 GET 请求读取数据，绝不提交 / 删除 / 作答任何作业或考试。
"""

import re
import json
import time
import datetime
import urllib.parse
from collections.abc import Mapping

import requests
from bs4 import BeautifulSoup

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 状态文本中，出现以下关键词视为「已完成 / 已交」，不计入未完成
DONE_KEYWORDS = (
    "已完成", "已交", "已提交", "已结束", "已批阅", "已交卷", "已做", "合格", "待批阅",
)

COURSE_LIST_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
COURSE_LIST_FALLBACK = "https://mooc1-1.chaoxing.com/visit/courselistdata"
COURSE_DETAIL_URL = "https://mooc1.chaoxing.com/visit/stucoursemiddle"
WORK_LIST_URL = "https://mooc1.chaoxing.com/mooc2/work/list"          # mooc2 模板（较老）
WORK_LIST_OLD_URL = "https://mooc1.chaoxing.com/work/list"            # mooc1 模板（最老）
EXAM_LIST_URL = "https://mooc1.chaoxing.com/exam-ans/exam/test/examcode/examlist"
EXAM_LIST_OLD_URL = "https://mooc1.chaoxing.com/exam/test/examlist"   # mooc1 模板（最老）

# ---- 新版（Vue / mooc-ans）接口：课程列表走 JSON，作业/考试走 mooc-ans 路径
COURSE_JSON_URL = "https://mooc1-api.chaoxing.com/mycourse/backclazzdata"
COURSE_DETAIL_NEW_URL = "https://mooc1.chaoxing.com/mooc-ans/mycourse/stu"
WORK_LIST_NEW_URL = "https://mooc1.chaoxing.com/mooc-ans/mooc2/work/list"
EXAM_LIST_NEW_URL = "https://mooc1.chaoxing.com/mooc-ans/exam/test/examlist"
WORK_PAGE_SIZE = 20          # 新版作业列表每页条数（用于翻页判断）
WORK_MAX_PAGES = 10          # 最多翻 10 页，防止死循环

# 课程详情页入口（新老模板各留几个，能取到 enc 就停）
COURSE_DETAIL_OLD_ENTRIES = (
    "https://mooc1.chaoxing.com/visit/stucoursemiddle",
    "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/stucoursemiddle",
    "https://mooc1-1.chaoxing.com/visit/stucoursemiddle",
    "https://mooc1.chaoxing.com/mycourse/stucoursemiddle",
)

# 「我的课程」其他入口：有的课程（机构课、协会课、旁听/归档课）不会出现在
# backclazzdata 的默认分组里，只能从个人主页或老版邀请页的 HTML 里抠出来
COURSE_HOME_PAGES = (
    ("i-base", "https://i.chaoxing.com/base"),
    ("visit-old", "https://mooc1.chaoxing.com/visit/interaction"),
    ("visit-mooc2", "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"),
)
# courseType：0/空=全部，1=我学的课，2=我教的课，3=归档/其他
COURSE_TYPES = ("", "1", "2", "3")

# 作业列表三代入口：new（mooc-ans，分页）/ mooc2 / mooc1（最老）都试，结果合并
WORK_ROUTES = (
    ("new", WORK_LIST_NEW_URL, True),
    ("mooc2", WORK_LIST_URL, False),
    ("mooc1", WORK_LIST_OLD_URL, False),
)
# 考试列表三代入口
EXAM_ROUTES = (EXAM_LIST_NEW_URL, EXAM_LIST_URL, EXAM_LIST_OLD_URL)

# 考试表头 -> 内部字段名
EXAM_HEADER_MAP = {
    "考试名称": "name",
    "考试时间": "time",
    "考试状态": "exam_status",
    "作答状态": "answer_status",
    "分数": "score",
    "操作": "ops",
}

_DT_FORMATS = [
    ("%Y-%m-%d %H:%M:%S", False),
    ("%Y-%m-%d %H:%M", False),
    ("%Y/%m/%d %H:%M:%S", False),
    ("%Y/%m/%d %H:%M", False),
    ("%Y.%m.%d %H:%M", False),
    ("%Y-%m-%d", False),
    ("%Y/%m/%d", False),
    ("%m-%d %H:%M", True),
    ("%m/%d %H:%M", True),
    ("%m月%d日 %H:%M", True),
    ("%m月%d日%H:%M", True),
    ("%m-%d", True),
    ("%m/%d", True),
    ("%m月%d日", True),
]


class ChaoxingError(Exception):
    """提取过程中的业务错误（会直接展示给用户）"""


# ---------------------------------------------------------------- Cookie 解析
def _unescape(s):
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s.replace('\\"', '"').replace("\\\\", "\\")


def _pairs_from_partial_json(raw):
    """从截断 / 不完整的 JSON 文本里尽力提取 name/value 对。

    场景：用户粘贴插件导出的 Cookie JSON 时只粘到一半（只剩尾部片段），
    此时整段不是合法 JSON，但里面完整的 {name,value} 对象仍然可以救出来。
    """
    cookies = {}
    names = list(re.finditer(r'"name"\s*:\s*"([^"]*)"', raw))
    values = list(re.finditer(r'"value"\s*:\s*"((?:[^"\\]|\\.)*)"', raw))
    vi = 0
    for nm in names:
        while vi < len(values) and values[vi].start() < nm.end():
            vi += 1
        if vi < len(values) and values[vi].start() - nm.end() < 500:
            cookies[nm.group(1)] = _unescape(values[vi].group(1))
            vi += 1
    return cookies


def normalize_cookies(raw):
    """把用户粘贴/导入的 Cookie 转成 (dict, domains)。

    支持四种形态：
      - 浏览器插件导出的 JSON 数组：  [{name,value,domain,...}, ...]   ← EditThisCookie / Cookie-Editor 等
      - JSON 对象：                    {"a":"1","b":"2"}
      - 不完整/被截断的 JSON 文本：    尽量用正则抢救出完整的 name/value 对
      - 纯 Cookie 字符串：             a=1; b=2; c=3   （可带 "Cookie:" 前缀）
    返回值第二项 domains 用于域名诊断（判断是不是学习通 Cookie）。
    """
    domains = set()
    if raw is None:
        return {}, domains
    if isinstance(raw, Mapping):  # 登录模块的字典 / 加密仓库的只读视图
        return {str(k): str(v) for k, v in raw.items()}, domains
    raw = raw.strip().lstrip("﻿").strip()
    if not raw:
        return {}, domains

    # 1) 完整 JSON
    try:
        obj = json.loads(raw)
    except Exception:
        obj = None

    if isinstance(obj, list):
        cookies = {}
        for item in obj:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("key")
            value = item.get("value")
            if name is None or value is None:
                continue
            cookies[str(name)] = str(value)
            d = item.get("domain")
            if d:
                domains.add(str(d).lstrip("."))
        if cookies:
            return cookies, domains

    if isinstance(obj, dict):
        return {str(k): str(v) for k, v in obj.items()}, domains

    # 2) 截断的 JSON（正则抢救）
    if '"name"' in raw and '"value"' in raw:
        cookies = _pairs_from_partial_json(raw)
        if cookies:
            return cookies, domains

    # 3) 纯字符串形态
    if raw.lower().startswith("cookie:"):
        raw = raw[len("cookie:"):].strip()
    cookies = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        cookies[k.strip()] = v.strip()
    return cookies, domains


# ---------------------------------------------------------------- 工具函数
def _is_done(status_text):
    if not status_text:
        return False
    return any(kw in status_text for kw in DONE_KEYWORDS)


def _parse_dt(text, ref=None):
    """把时间文本解析成 datetime；不带年份时按与 ref 的接近程度推断年份。"""
    if not text:
        return None
    text = str(text).strip()
    ref = ref or datetime.datetime.now()
    for fmt, need_year in _DT_FORMATS:
        try:
            dt = datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
        if need_year:
            best = None
            for y in (ref.year - 1, ref.year, ref.year + 1):
                cand = dt.replace(year=y)
                if best is None or abs((cand - ref).total_seconds()) < abs((best - ref).total_seconds()):
                    best = cand
            return best
        return dt
    return None


def _parse_remaining(text):
    """解析「剩余515小时48分钟 / 剩2天3小时 / 剩余30分钟」为 timedelta。"""
    if not text:
        return None
    days = re.search(r"(\d+)\s*天", text)
    hours = re.search(r"(\d+)\s*(?:个)?\s*小时", text)
    minutes = re.search(r"(\d+)\s*分钟", text)
    d = int(days.group(1)) if days else 0
    h = int(hours.group(1)) if hours else 0
    m = int(minutes.group(1)) if minutes else 0
    if d or h or m:
        return datetime.timedelta(days=d, hours=h, minutes=m)
    return None


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S") if dt else ""


def _from_iso(text):
    """把 deadline_iso / start_iso 还原成 datetime；空或格式不对返回 None。"""
    if not text:
        return None
    try:
        return datetime.datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


# ---------------------------------------------------------------- 三块分类
# 作业列表按「未完成 / 超时未交 / 已完成」分三块；顺序即表格里的显示顺序（紧急的在前）。
STATE_OPEN = "open"
STATE_OVERDUE = "overdue"
STATE_DONE = "done"
STATE_ORDER = (STATE_OPEN, STATE_OVERDUE, STATE_DONE)
STATE_LABEL = {STATE_OPEN: "未完成", STATE_OVERDUE: "超时未交", STATE_DONE: "已完成"}


def task_state(t, now=None):
    """把一个任务归到三块之一。

    done    已完成（作业已交 / 考试已交卷）
    overdue 未完成，且截止时间已经过去
    open    未完成，还没到期；拿不到时间的也归这里（宁可当作待办）
    """
    now = now or datetime.datetime.now()
    if t.get("done"):
        return STATE_DONE
    end = _from_iso(t.get("deadline_iso"))
    if end is not None:
        return STATE_OVERDUE if end < now else STATE_OPEN
    # 没有明确截止时间时，考试状态写着「已结束」而没作答，同样算超时
    st = "%s %s" % (t.get("exam_status") or "", t.get("status") or "")
    if "已结束" in st:
        return STATE_OVERDUE
    return STATE_OPEN


class ChaoxingClient:
    def __init__(self, cookies, timeout=20):
        self.cookies, self.domains = normalize_cookies(cookies)
        if not self.cookies:
            raise ChaoxingError(
                "未提供任何 Cookie，请先在浏览器登录学习通后复制 Cookie"
                "（或用「选择 Cookie 文件」导入插件导出的 JSON）。"
            )
        self.timeout = timeout
        self.fid = self.cookies.get("fid") or ""
        self.cpi = ""  # 用户级 ID，课程列表/详情页里可拿到
        self._uid = self.cookies.get("uid") or self.cookies.get("_uid") or ""
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_UA,
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        self._safe_set_cookies()

    def _safe_set_cookies(self):
        """把 Cookie 逐个写入会话，跳过非法项，避免整段崩溃（如非法请求头）。"""
        for k, v in self.cookies.items():
            try:
                self.session.cookies.set(k, v)
            except Exception:
                continue

    # ---------------------------------------------------------------- 诊断
    def diagnose(self):
        """返回警告列表（域名不对 / Cookie 不完整 / 缺 fid 等）。"""
        warns = []
        if self.domains:
            markers = ("chaoxing", "xuetang", "icourse", "edu.cn", "fanya", "cx")
            if not any(any(m in d for m in markers) for d in self.domains):
                sample = ", ".join(sorted(self.domains)[:6])
                warns.append(
                    "这些 Cookie 的域名都不是学习通/超星（检测到：" + sample +
                    "）。请在学习通网页登录后，重新导出【该网站】的 Cookie。"
                )
        if not self.fid:
            warns.append(
                "Cookie 里没有找到 fid 字段（学习通登录态的关键）。"
                "如果只粘贴了一部分，请用「选择 Cookie 文件」导入完整 JSON。"
            )
        elif len(self.cookies) < 5:
            warns.append(
                "只解析到 %d 个 Cookie，可能粘贴不完整，建议用「选择 Cookie 文件」导入完整 JSON。"
                % len(self.cookies)
            )
        return warns

    # ---------------------------------------------------------------- 网络层
    def _get(self, url, params=None, referer=None, retries=2):
        headers = {}
        if referer:
            headers["Referer"] = referer
        last_err = None
        for i in range(retries + 1):
            try:
                r = self.session.get(
                    url, params=params, headers=headers,
                    timeout=self.timeout, allow_redirects=True,
                )
                r.encoding = "utf-8"
                if r.status_code == 200:
                    return r
                if r.status_code in (429, 500, 502, 503):
                    last_err = f"HTTP {r.status_code}"
                    time.sleep(1 + i)
                    continue
                raise ChaoxingError(f"HTTP {r.status_code} 访问 {url}")
            except requests.RequestException as e:
                last_err = str(e)
                if i < retries:
                    time.sleep(1 + i)
                    continue
                raise ChaoxingError(f"请求失败 {url}：{e}")
        raise ChaoxingError(f"重试后仍失败 {url}：{last_err}")

    # ---------------------------------------------------------------- 登录校验
    def check_login(self):
        if not self.fid:
            return False, (
                "Cookie 中缺少 fid（学习通登录态关键字段）。请重新登录学习通，"
                "完整复制 Cookie，或用「选择 Cookie 文件」导入插件导出的 JSON。"
            )
        # 新版优先：JSON 接口能返回课程就说明登录态可用（不依赖页面模板）
        try:
            if self._courses_from_api():
                return True, "Cookie 有效。"
        except ChaoxingError:
            pass
        try:
            r = self._get(
                COURSE_LIST_URL,
                params={"courseType": "1", "courseFid": self.fid},
                referer="https://mooc2-ans.chaoxing.com/",
            )
        except ChaoxingError as e:
            return False, f"无法访问学习通课程页：{e}"
        low = (r.url or "").lower()
        if "passport" in low or "login" in low:
            return False, "请求被重定向到登录页，Cookie 可能已过期，请重新登录学习通再复制。"
        html = r.text or ""
        if "请登录" in html or "立即登录" in html or "passport.chaoxing" in html:
            return False, "页面提示需要登录，Cookie 可能已过期，请重新登录学习通再复制。"
        return True, "Cookie 有效。"

    # ---------------------------------------------------------------- 课程列表
    def _courses_from_api(self, course_type=""):
        """新版接口：一次拿回全部课程（含 courseId / classId / cpi）。

        新版学习通前端是 Vue 单页应用，课程卡片由 JS 渲染，HTML 里没有课程链接，
        所以优先走这个 JSON 接口；旧模板也兼容（同一个接口一直可用）。

        course_type："" 全部 / "1" 我学的课 / "2" 我教的课 / "3" 归档。
        不同分组返回的课程不一样，必须都跑一遍再合并。
        """
        params = {"view": "json", "rss": "1"}
        if course_type:
            params["courseType"] = course_type
        r = self._get(COURSE_JSON_URL, params=params,
                      referer="https://i.mooc.chaoxing.com/")
        try:
            data = json.loads(r.text)
        except Exception:
            return []
        if not isinstance(data, dict) or data.get("result") != 1:
            return []
        courses = []
        for ch in data.get("channelList") or []:
            content = ch.get("content") or {}
            course = content.get("course") or {}
            entries = course.get("data") or []
            if not isinstance(entries, list):
                continue
            clazz_id = str(content.get("id") or "")
            cpi = str(content.get("cpi") or "")
            for c in entries:
                if not isinstance(c, dict):
                    continue
                cid = str(c.get("id") or "")
                if not cid or not clazz_id:
                    continue
                # 已退课/已归档的课照样保留：它们可能还有历史作业，
                # 是否显示交给 task_state 判断，别在这里直接丢掉
                retired = str(ch.get("isretire") or content.get("isretire") or "0") == "1"
                if cpi and not self.cpi:
                    self.cpi = cpi
                courses.append({
                    "name": c.get("name") or cid,
                    "courseId": cid,
                    "classId": clazz_id,
                    "clazzid": clazz_id,
                    "cpi": cpi,
                    "teacher": c.get("teacherfactor") or "",
                    "retired": retired,
                    "url": "",
                })
        return courses

    def _parse_courses(self, html):
        soup = BeautifulSoup(html, "html.parser")
        cards = []
        for sel in ("div.course", "div.course-item", "li.course-item"):
            cards = soup.select(sel)
            if cards:
                break
        if not cards:
            # 兜底：任何指向课程详情页的链接，取其最近容器
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "stucoursemiddle" in href or ("courseid=" in href and "clazzid=" in href):
                    cards.append(a.find_parent(["li", "div"]) or a)

        courses = []
        seen = set()
        for card in cards:
            name = ""
            nm = card.select_one("span.course-name") or card.select_one(".course-name")
            if nm:
                name = nm.get("title") or nm.get_text(strip=True)
            if not name:
                a0 = card.find("a", href=True)
                if a0:
                    name = a0.get_text(strip=True)
            if not name and card.name == "a":
                name = card.get_text(strip=True)

            a = None
            for cand in card.find_all("a", href=True):
                if "stucoursemiddle" in cand["href"]:
                    a = cand
                    break
            if a is None:
                a = card.find("a", href=True)
            if a is None and card.name == "a":
                a = card          # 兜底时卡片本身就是 <a>，find 找不到自己
            href = a["href"] if a else ""

            q = {}
            if href:
                try:
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    q = {k: v[0] for k, v in qs.items()}
                except Exception:
                    q = {}

            hid = {}
            for inp in card.find_all("input"):
                n = inp.get("name") or inp.get("id")
                if n:
                    hid[n] = inp.get("value", "")

            course_id = hid.get("courseId") or q.get("courseid") or ""
            clazz_id = hid.get("clazzId") or hid.get("classId") or q.get("clazzid") or ""
            cpi = hid.get("cpi") or q.get("cpi") or ""
            if not course_id or not clazz_id:
                continue
            key = (course_id, clazz_id)
            if key in seen:
                continue
            seen.add(key)
            if cpi and not self.cpi:
                self.cpi = cpi
            courses.append({
                "name": name or (course_id + "/" + clazz_id),
                "courseId": course_id,
                "classId": clazz_id,
                "clazzid": clazz_id,
                "cpi": cpi,
                "url": href,
            })
        return courses

    def get_courses(self):
        """课程列表：把能找到的入口**全部跑一遍**，结果合并去重。

        学习通的课程散在好几处：backclazzdata 的 JSON（还按 courseType 分组）、
        老版 courselistdata 的 HTML、个人主页 / 老版邀请页的 HTML。机构课、协会课、
        旁听或归档课经常只在其中某一处出现，所以这里不做「拿到就停」。
        """
        courses = []
        seen = set()
        self.course_sources = []          # [(来源, 新增条数)]，供 --diag-courses 用

        def add(label, lst):
            n = 0
            for c in lst:
                key = (c.get("courseId"), c.get("classId"))
                if not (key[0] and key[1]) or key in seen:
                    continue
                seen.add(key)
                courses.append(c)
                n += 1
            if n:
                self.course_sources.append((label, n))
            return n

        # 1) JSON 接口：按分组逐个取（全部 / 我学的 / 我教的 / 归档）
        for ct in COURSE_TYPES:
            label = "api" + (":courseType=" + ct if ct else ":all")
            try:
                add(label, self._courses_from_api(ct))
            except ChaoxingError:
                continue

        # 2) 老版 HTML 课程列表（常能补上 API 漏掉的课）
        html_attempts = [(COURSE_LIST_FALLBACK, None)]
        if self.fid:
            html_attempts.insert(0, (COURSE_LIST_URL, {"courseType": "1", "courseFid": self.fid}))
        html_attempts.insert(1 if self.fid else 0, (COURSE_LIST_URL, None))
        for url, params in html_attempts:
            label = "html:" + url.split("//")[-1].split("/")[0]
            try:
                r = self._get(url, params=params, referer="https://mooc2-ans.chaoxing.com/")
            except ChaoxingError:
                continue
            add(label, self._parse_courses(r.text))

        # 3) 个人主页 / 邀请页：机构课、协会课往往只在这里露面
        for label, url in COURSE_HOME_PAGES:
            try:
                r = self._get(url, referer="https://i.chaoxing.com/")
            except ChaoxingError:
                continue
            add(label, self._parse_courses(r.text))
        return courses

    # ---------------------------------------------------------------- 课程详情
    @staticmethod
    def _enc_fields(html):
        """从课程页里抠出 enc / workEnc / cpi 等参数。

        旧模板放在隐藏域里；新版 Vue 页面没有隐藏域，但要是有内联的
        `enc=xxxxxxxx` 或 `workEnc: "..."` 也一并接住。
        """
        soup = BeautifulSoup(html or "", "html.parser")
        hid = {}
        for inp in soup.find_all("input"):
            n = inp.get("name") or inp.get("id")
            if n:
                hid[n] = inp.get("value", "")
        out = {
            "cpi": hid.get("cpi") or "",
            "workEnc": hid.get("workEnc") or "",
            "enc": hid.get("enc") or hid.get("oldenc") or "",
            "openc": hid.get("openc") or "",
            "examEnc": hid.get("examEnc") or "",
            "token": hid.get("token") or "",
        }
        if not out["workEnc"]:
            m = (re.search(r'id="workEnc"[^>]*value="([0-9a-fA-F]{16,})"', html or "")
                 or re.search(r'workEnc\s*[:=]\s*["\']([0-9a-fA-F]{16,})["\']', html or ""))
            if m:
                out["workEnc"] = m.group(1)
        if not out["enc"]:
            m = re.search(r"enc=([0-9a-fA-F]{32})", html or "")
            if m:
                out["enc"] = m.group(1)
        if not out["openc"]:
            m = re.search(r'id="openc"[^>]*value="([0-9a-fA-F]+)"', html or "")
            if m:
                out["openc"] = m.group(1)
        return out

    def get_course_detail(self, course):
        """课程详情页：新老入口依次尝试，取到 enc / workEnc 就停。

        返回时会给 course 打上 style：
            "old" —— 从旧模板页面取到了 enc（作业/考试走旧路径最稳）
            "new" —— 只有新页面能打开、没有 enc（走不带 enc 的新路径）
        两种情况都会继续去抓作业，不会因为「没有 enc」就跳过课程。
        """
        cid, cid2 = course["courseId"], course["classId"]
        cpi = course.get("cpi") or ""
        old = []
        for base in COURSE_DETAIL_OLD_ENTRIES:
            if base == "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/stucoursemiddle":
                old.append("%s?courseid=%s&clazzid=%s&cpi=%s&v=2" % (base, cid, cid2, cpi))
            else:
                old.append("%s?courseid=%s&clazzid=%s&ismooc2=1&v=2" % (base, cid, cid2))
        new = ["%s?courseid=%s&clazzid=%s&cpi=%s&ut=s" % (COURSE_DETAIL_NEW_URL, cid, cid2, cpi)]

        got_any = False
        for style, url in ([("old", u) for u in old] + [("new", u) for u in new]):
            try:
                r = self._get(url, referer="https://mooc2-ans.chaoxing.com/")
            except ChaoxingError:
                continue
            got_any = True
            fields = self._enc_fields(r.text)
            for k in ("cpi", "workEnc", "enc", "openc", "examEnc", "token"):
                if fields.get(k) and not course.get(k):
                    course[k] = fields[k]
            if course.get("cpi") and not self.cpi:
                self.cpi = course["cpi"]
            if course.get("workEnc") or course.get("enc"):
                course["style"] = style
                return course
        if got_any:
            # 所有入口都能打开，但都没有 enc —— 新版课程页（Vue）就是这个特征，
            # 作业列表仍然可能用「不带 enc」的新路径取到，交给 fetch_works 再试。
            course["style"] = "new"
            course["new_style"] = True
        return course

    # ---------------------------------------------------------------- 作业
    def _base_work_params(self, course):
        return {
            "courseId": course["courseId"],
            "classId": course["classId"],
            "cpi": course.get("cpi") or "",
            "ut": "s",
            "openc": course.get("openc") or "",
            "enc": course.get("workEnc") or "",
            "stuenc": course.get("enc") or "",
            "token": course.get("token") or "",
            "isdisplaytable": "2",
            "status": "0",  # 0=全部，1=未完成，2=已完成
        }

    def _fetch_works_one(self, course, route, max_pages):
        """单条入口抓作业：new 走 mooc-ans（pageNum 分页），mooc2 / mooc1 走老路径。"""
        referer = course.get("url") or "https://mooc1.chaoxing.com/"
        url = dict(((r[0], r[1]) for r in WORK_ROUTES)).get(route, WORK_LIST_URL)
        paginate = route == "new"
        if route == "bare":
            # 极简参数兜底：个别老模板只认 courseId / classId
            base = {"courseId": course["courseId"], "classId": course["classId"],
                    "status": "0"}
        else:
            base = self._base_work_params(course)
        items = []
        seen = set()

        for page in range(1, (max_pages if paginate else 1) + 1):
            params = dict(base)
            params["t"] = int(time.time() * 1000)
            if paginate:
                params["pageNum"] = str(page)
            try:
                r = self._get(url, params=params, referer=referer)
            except ChaoxingError:
                break
            added = 0
            for w in self._parse_works(r.text):
                key = w.get("link") or (w["name"], w.get("remain") or "")
                if key in seen:
                    continue
                seen.add(key)
                items.append(w)
                added += 1
            if added == 0:
                break
            if paginate:
                time.sleep(0.15)     # 翻页之间稍微喘一下
        return items

    def fetch_works(self, course):
        """作业列表：三代入口**都跑**，结果合并去重。

        new（mooc-ans）/ mooc2 / mooc1 的列表结构一致，解析器共用；
        哪条返回数据就用哪条，多条都有就取并集。
        先按课程风格走首选入口；首选拿到数据后，其余入口只跑第 1 页补漏。
        """
        order = ["mooc2", "mooc1", "new"] if course.get("style") == "old" else ["new", "mooc2", "mooc1"]
        items, seen = [], set()

        for route in order:
            max_pages = WORK_MAX_PAGES if not items else 1
            try:
                got = self._fetch_works_one(course, route, max_pages)
            except ChaoxingError:
                got = []
            for w in got:
                key = w.get("link") or (w["name"], w.get("remain") or "")
                if key in seen:
                    continue
                seen.add(key)
                items.append(w)

        if not items:
            # 三代入口都空：用最省参数的请求再兜一次（部分老模板只认 courseId/classId）
            try:
                for w in self._fetch_works_one(course, "bare", 1):
                    key = w.get("link") or (w["name"], w.get("remain") or "")
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(w)
            except ChaoxingError:
                pass
        return items

    def _parse_works(self, html):
        """解析作业列表：新旧模板共用一套选择器（结构一致，只是外层 class 不同）。"""
        soup = BeautifulSoup(html, "html.parser")
        groups = (
            soup.select(".bottomList li"),
            soup.select(".bottomList ul li"),
            soup.select("ul.ulDiv li"),
            soup.select(".workList li"),
            soup.select(".workList ul li"),
        )
        lis = next((g for g in groups if g), [])
        if not lis:
            lis = [li for li in soup.select("li")
                   if li.select_one("p.overHidden2") or li.select_one(".overHidden2")]
        items = []
        for li in lis:
            name_tag = li.select_one("p.overHidden2") or li.select_one(".overHidden2")
            if name_tag:
                name = name_tag.get_text(strip=True)
            else:                       # 老模板偶尔没有 overHidden2，取第一个链接文字
                a0 = li.find("a", href=True)
                name = a0.get_text(strip=True) if a0 else ""
            if not name:
                continue
            status_tag = li.select_one("p.status") or li.select_one(".status")
            status = status_tag.get_text(strip=True) if status_tag else ""
            if not status:
                aria = li.get("aria-label") or ""
                if ";" in aria:
                    status = aria.split(";")[-1].strip()
            time_tag = li.select_one("div.time") or li.select_one(".time")
            remain = time_tag.get_text(" ", strip=True) if time_tag else ""
            link = li.get("data") or ""
            if not link:
                a = li.find("a", href=True)
                if a:
                    link = a["href"]
            if link.startswith("//"):
                link = "https:" + link
            elif link.startswith("/"):
                link = "https://mooc1.chaoxing.com" + link
            items.append({
                "name": name,
                "status": status,
                "remain": remain,
                "link": link,
                "done": _is_done(status),
            })
        return items

    def _fetch_task_times(self, url, ref=None):
        """打开作业详情页，提取「作答时间:<em>开始</em>至<em>截止</em>」。

        新版详情页（/mooc-ans/mooc2/work/task）的 <em> 可能只有开始时间、
        截止时间为空，所以这里允许空值，再从纯文本里兜一次。
        """
        r = self._get(url, referer=ref or (
            "https://mooc1.chaoxing.com/mooc-ans/" if "mooc-ans" in url else WORK_LIST_URL))
        html = r.text or ""
        m = re.search(
            r"作答时间\s*[：:]\s*<em>\s*([^<]*?)\s*</em>\s*至\s*<em>\s*([^<]*?)\s*</em>",
            html,
        )
        if not m:
            m = re.search(
                r"<em>\s*([\d./\-]+\s+[\d:]+)\s*</em>\s*至\s*<em>\s*([\d./\-]+\s+[\d:]*)\s*</em>",
                html,
            )
        if m:
            start_raw, end_raw = (m.group(1) or "").strip(), (m.group(2) or "").strip()
        else:
            # 兜底：从可见文本里找「作答时间: xx 至 yy」
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            m2 = re.search(
                r"作答时间\s*[：:]\s*([\d./\-]+\s+[\d:]+)\s*至\s*([\d./\-]+\s+[\d:]+)?",
                text,
            )
            if not m2:
                return None, None
            start_raw = (m2.group(1) or "").strip()
            end_raw = (m2.group(2) or "").strip()
        return _parse_dt(start_raw, ref) if start_raw else None, (
            _parse_dt(end_raw, ref) if end_raw else None
        )

    def _work_to_task(self, w, cname):
        now = datetime.datetime.now()
        remain_delta = _parse_remaining(w.get("remain") or "")
        ref = now + remain_delta if remain_delta else now

        start_dt = end_dt = None
        if w.get("link") and not w["done"]:
            try:
                start_dt, end_dt = self._fetch_task_times(w["link"], ref)
            except ChaoxingError:
                start_dt, end_dt = None, None

        approx = False
        if end_dt is None and remain_delta is not None:
            end_dt = now + remain_delta
            approx = True

        if end_dt is not None:
            display = end_dt.strftime("%Y-%m-%d %H:%M")
            if approx:
                display = "约 " + display + "（" + (w.get("remain") or "") + "）"
        else:
            display = w.get("remain") or "未注明"

        return {
            "type": "作业",
            "course": cname,
            "name": w["name"],
            "status": w["status"] or ("已完成" if w["done"] else "未交"),
            "deadline": display,
            "deadline_iso": _iso(end_dt),
            "start_iso": _iso(start_dt),
            "approx": approx,
            "remain": w.get("remain") or "",
            "link": w.get("link") or "",
            "done": w["done"],
        }

    # ---------------------------------------------------------------- 考试
    def fetch_exams(self):
        """按用户拉取全部考试（cpi 维度）：新、旧两条入口**都跑**并合并，自动翻页。

        每页 12 条；两个入口返回的表格结构相同，解析器共用。
        """
        if not self.cpi:
            return []
        items = []
        seen = set()
        start = 0
        for _ in range(8):
            page_all = []
            for url in EXAM_ROUTES:
                try:
                    r = self._get(
                        url,
                        params={"cpi": self.cpi, "status": "-1", "start": str(start)},
                        referer="https://mooc1.chaoxing.com/",
                    )
                except ChaoxingError:
                    continue
                page_all.extend(self._parse_exams(r.text))
            added = 0
            for it in page_all:
                key = (it["name"], it["deadline"])
                if key in seen:
                    continue
                seen.add(key)
                items.append(it)
                added += 1
            # 两条入口都没新数据，或者本页不足 12 条，就说明到底了
            if added == 0 or len(page_all) < 12:
                break
            start += 12
        return items

    def _exam_col_map(self, table):
        m = {}
        if not table:
            return m
        first_tr = table.find("tr")
        if not first_tr:
            return m
        for i, th in enumerate(first_tr.find_all("th")):
            key = EXAM_HEADER_MAP.get(th.get_text(strip=True))
            if key:
                m[key] = i
        return m

    def _parse_exams(self, html):
        soup = BeautifulSoup(html, "html.parser")
        items = []
        for tr in soup.select("tr.dataTr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            table = tr.find_parent("table")
            cmap = self._exam_col_map(table)
            cols = [td.get_text(" ", strip=True) for td in tds]

            def col(key, default_idx):
                i = cmap.get(key, default_idx)
                return cols[i] if 0 <= i < len(cols) else ""

            name = col("name", 1)
            if not name:
                continue
            timerange = col("time", 2)
            exam_status = col("exam_status", 4)
            answer_status = col("answer_status", 5)
            score = col("score", 6)

            # 操作列里的链接（onclick="go('...')"）
            link = ""
            ops_i = cmap.get("ops", len(tds) - 1)
            if 0 <= ops_i < len(tds):
                a = tds[ops_i].find("a", onclick=True) or tds[ops_i].find("a", href=True)
                if a:
                    m = re.search(r"go\(\s*'([^']+)'", a.get("onclick", ""))
                    if m:
                        link = "https://mooc1.chaoxing.com" + m.group(1)
                    elif (a.get("href") or "").startswith("http"):
                        link = a["href"]

            parts = re.split(r"\s*至\s*", timerange) if timerange else []
            start_dt = _parse_dt(parts[0]) if parts else None
            end_dt = _parse_dt(parts[1]) if len(parts) > 1 else None
            # 同一天就压缩成「日期 时间–时间」，避免表格里被截断
            if start_dt and end_dt and start_dt.date() == end_dt.date():
                shown_deadline = "%s–%s" % (
                    start_dt.strftime("%Y-%m-%d %H:%M"), end_dt.strftime("%H:%M"))
            elif start_dt and end_dt:
                shown_deadline = "%s 至 %s" % (
                    start_dt.strftime("%Y-%m-%d %H:%M"), end_dt.strftime("%Y-%m-%d %H:%M"))
            else:
                shown_deadline = timerange or "未注明"

            items.append({
                "type": "考试",
                "course": "",
                "name": name,
                "status": answer_status or exam_status or "",
                "exam_status": exam_status,
                "score": score,
                "deadline": shown_deadline,
                "deadline_iso": _iso(end_dt or start_dt),
                "start_iso": _iso(start_dt),
                "approx": False,
                "remain": "",
                "link": link,
                "done": _is_done(answer_status),
            })
        return items

    # ---------------------------------------------------------------- 聚合
    def extract_all(self, only_incomplete=True):
        result = {
            "ok": True,
            "uid": self._uid,
            "fid": self.fid,
            "cookie_count": len(self.cookies),
            "courses_count": 0,
            "tasks": [],
            "errors": [],
            "hint": "",
        }
        courses = self.get_courses()
        result["courses_count"] = len(courses)
        if not courses:
            result["hint"] = (
                "没有读到任何课程。请先在浏览器里确认学习通能正常打开课程列表，"
                "然后点「重新提取」再试一次。"
            )

        for c in courses:
            cname = c.get("name") or "未知课程"
            try:
                self.get_course_detail(c)
            except ChaoxingError as e:
                result["errors"].append(f"「{cname}」课程详情获取失败：{e}")
                continue
            if not (c.get("courseId") and c.get("classId")):
                result["errors"].append(f"「{cname}」缺少 courseId/classId，已跳过")
                continue
            try:
                works = self.fetch_works(c)
            except ChaoxingError as e:
                result["errors"].append(f"「{cname}」作业获取失败：{e}")
                works = []
            for w in works:
                if only_incomplete and w["done"]:
                    continue
                result["tasks"].append(self._work_to_task(w, cname))
            time.sleep(0.1)  # 温和一点，避免请求过密

        # 考试（用户级接口，一次拿全）
        try:
            for e in self.fetch_exams():
                if only_incomplete and e["done"]:
                    continue
                result["tasks"].append(e)
        except ChaoxingError as e:
            result["errors"].append(f"考试列表获取失败：{e}")

        # 打上「三块」归属并按块排序：未完成（最紧急）→ 超时未交 → 已完成
        now = datetime.datetime.now()
        counts = {k: 0 for k in STATE_ORDER}
        for t in result["tasks"]:
            t["state"] = task_state(t, now)
            counts[t["state"]] = counts.get(t["state"], 0) + 1
        result["counts"] = counts

        def sort_key(t):
            iso = t.get("deadline_iso") or ""
            st = t.get("state") or STATE_OPEN
            rank = STATE_ORDER.index(st) if st in STATE_ORDER else len(STATE_ORDER)
            return (rank, 0, iso) if iso else (rank, 1, "")

        result["tasks"].sort(key=sort_key)
        return result


# ---------------------------------------------------------------- CLI 入口
def main():
    import argparse
    import csv

    ap = argparse.ArgumentParser(description="超星学习通 未完成作业/考试 提取器")
    ap.add_argument("--cookies", help="浏览器复制的 Cookie 字符串")
    ap.add_argument("--cookies-file", help="存放 Cookie 的文件路径（支持 JSON）")
    ap.add_argument("--output", help="导出 CSV 路径（默认 stdout）")
    ap.add_argument("--all", action="store_true", help="包含已完成的任务")
    ap.add_argument("--diag-courses", action="store_true",
                    help="只列出各入口抓到的课程（排查「某门课不显示」时用）")
    args = ap.parse_args()

    cookies = args.cookies
    if not cookies and args.cookies_file:
        with open(args.cookies_file, "r", encoding="utf-8-sig") as f:
            cookies = f.read()

    client = ChaoxingClient(cookies)
    for w in client.diagnose():
        print("警告：", w)
    ok, msg = client.check_login()
    print("登录校验：", msg)
    if not ok:
        return
    if args.diag_courses:
        courses = client.get_courses()
        print("课程来源：")
        for label, n in getattr(client, "course_sources", []):
            print("  %-26s +%d" % (label, n))
        print("共 %d 门：" % len(courses))
        for c in courses:
            print("  - %s%s  courseId=%s classId=%s%s" % (
                c.get("name") or "(无名)",
                "  [归档]" if c.get("retired") else "",
                c.get("courseId"), c.get("classId"),
                "  cpi=" + c["cpi"] if c.get("cpi") else ""))
        return
    data = client.extract_all(only_incomplete=not args.all)
    if args.output:
        with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["分类", "类型", "课程", "名称", "状态", "截止时间", "链接"])
            for t in data["tasks"]:
                w.writerow([STATE_LABEL.get(t.get("state"), ""), t["type"], t["course"],
                            t["name"], t["status"], t["deadline"], t["link"]])
        print(f"已导出 {len(data['tasks'])} 条到 {args.output}")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    if data["errors"]:
        print("\n部分错误：")
        for e in data["errors"]:
            print(" -", e)


if __name__ == "__main__":
    main()
