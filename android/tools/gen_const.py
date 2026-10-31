#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成安卓端的常量表（C.java）：所有 URL / UA 以异或+Base64 形式存放，源码与
dex 里都不出现明文。改地址只需改这里再跑一次。"""

import base64
import os

ITEMS = [
    # (Java 常量名, 明文)
    ("PASS_PAGE", "https://passport2.chaoxing.com/login?fid=&refer=http%3A%2F%2Fi.chaoxing.com"),
    ("PASS_API", "https://passport2.chaoxing.com/fanyalogin"),
    ("COURSE_JSON", "https://mooc1-api.chaoxing.com/mycourse/backclazzdata"),
    ("COURSE_LIST", "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"),
    ("COURSE_LIST_FB", "https://mooc1-1.chaoxing.com/visit/courselistdata"),
    ("DETAIL_A", "https://mooc1.chaoxing.com/visit/stucoursemiddle"),
    ("DETAIL_B", "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/stucoursemiddle"),
    ("DETAIL_C", "https://mooc1-1.chaoxing.com/visit/stucoursemiddle"),
    ("DETAIL_D", "https://mooc1.chaoxing.com/mycourse/stucoursemiddle"),
    ("DETAIL_NEW", "https://mooc1.chaoxing.com/mooc-ans/mycourse/stu"),
    ("WORK_NEW", "https://mooc1.chaoxing.com/mooc-ans/mooc2/work/list"),
    ("WORK_M2", "https://mooc1.chaoxing.com/mooc2/work/list"),
    ("WORK_M1", "https://mooc1.chaoxing.com/work/list"),
    ("EXAM_NEW", "https://mooc1.chaoxing.com/mooc-ans/exam/test/examlist"),
    ("EXAM_MID", "https://mooc1.chaoxing.com/exam-ans/exam/test/examcode/examlist"),
    ("EXAM_OLD", "https://mooc1.chaoxing.com/exam/test/examlist"),
    ("HOME_BASE", "https://i.chaoxing.com/base"),
    ("HOME_I", "https://i.chaoxing.com"),
    ("VISIT_OLD", "https://mooc1.chaoxing.com/visit/interaction"),
    ("VISIT_M2", "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"),
    ("REF_M2", "https://mooc2-ans.chaoxing.com/"),
    ("REF_I", "https://i.chaoxing.com/"),
    ("REF_M1", "https://mooc1.chaoxing.com/"),
    ("UA", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    ("MOOC1_HOST", "https://mooc1.chaoxing.com"),
    ("REFER_ENC", "http%3A%2F%2Fi.chaoxing.com"),
    ("MOOC_ANS", "mooc-ans"),
]


def enc(text, seed):
    raw = bytearray(text.encode("utf-8"))
    for i in range(len(raw)):
        raw[i] ^= (seed + i * 31) & 0xFF
    return base64.b64encode(bytes(raw)).decode()


def main():
    lines = [
        "package com.cx.helper;",
        "",
        "/** 常量表（由 tools/gen_const.py 生成，勿手改）。 */",
        "final class C {",
        "    private C() {",
        "    }",
        "",
    ]
    for i, (name, val) in enumerate(ITEMS):
        seed = (0x31 + i * 19) & 0x7F
        lines.append('    static final String %s = Str.d("%s", %d);' % (name, enc(val, seed), seed))
    lines += ["}", ""]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "app", "src", "main", "java", "com", "cx", "helper", "C.java")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print("written", out, len(ITEMS), "constants")


if __name__ == "__main__":
    main()
