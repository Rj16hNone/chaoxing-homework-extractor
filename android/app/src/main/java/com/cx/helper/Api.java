package com.cx.helper;

import android.net.Uri;

import org.json.JSONArray;
import org.json.JSONObject;
import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.jsoup.select.Elements;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 学习通接口客户端（只读）：登录、课程列表、课程详情、作业、考试。
 * 课程与作业都按「新老多入口并集」取，单条入口失败不影响其它。
 */
final class Api {

    interface P {
        void step(String msg);
    }

    static final class Err extends Exception {
        Err(String m) {
            super(m);
        }
    }

    private static final int PAGE_SIZE = 20;
    private static final int MAX_PAGES = 10;

    private final LinkedHashMap<String, String> ck = new LinkedHashMap<>();
    String fid = "";
    String uid = "";
    String cpi = "";
    final List<String> warn = new ArrayList<>();

    Api(Map<String, String> seed) {
        if (seed != null) {
            for (Map.Entry<String, String> e : seed.entrySet()) {
                if (e.getKey() != null && !e.getKey().isEmpty()) {
                    ck.put(e.getKey(), e.getValue() == null ? "" : e.getValue());
                }
            }
        }
        fid = nz(ck.get("fid"));
        uid = ck.containsKey("uid") ? nz(ck.get("uid")) : nz(ck.get("_uid"));
    }

    Map<String, String> cookies() {
        return new LinkedHashMap<>(ck);
    }

    // ------------------------------------------------------------------ HTTP
    private String cookieHeader() {
        synchronized (ck) {
            if (ck.isEmpty()) {
                return "";
            }
            StringBuilder sb = new StringBuilder();
            for (Map.Entry<String, String> e : ck.entrySet()) {
                if (sb.length() > 0) {
                    sb.append("; ");
                }
                sb.append(e.getKey()).append('=').append(e.getValue());
            }
            return sb.toString();
        }
    }

    private void absorb(Map<String, List<String>> headers) {
        if (headers == null) {
            return;
        }
        synchronized (ck) {
            for (Map.Entry<String, List<String>> e : headers.entrySet()) {
                String k = e.getKey();
                if (k == null || !k.equalsIgnoreCase("Set-Cookie") || e.getValue() == null) {
                    continue;
                }
                for (String raw : e.getValue()) {
                    if (raw == null) {
                        continue;
                    }
                    int sc = raw.indexOf(';');
                    String pair = sc >= 0 ? raw.substring(0, sc) : raw;
                    int eq = pair.indexOf('=');
                    if (eq <= 0) {
                        continue;
                    }
                    String name = pair.substring(0, eq).trim();
                    String val = pair.substring(eq + 1).trim();
                    if (!name.isEmpty() && !name.equalsIgnoreCase("deleted")) {
                        ck.put(name, val);
                    }
                }
            }
        }
        if (!ck.containsKey("_uid") && ck.containsKey("uid")) {
            ck.put("_uid", ck.get("uid"));
        }
    }

    private String open(String url, String referer, Map<String, String> params,
                        byte[] post, String ctype) throws Err {
        String target = url;
        if (params != null && !params.isEmpty()) {
            StringBuilder q = new StringBuilder();
            for (Map.Entry<String, String> e : params.entrySet()) {
                if (q.length() > 0) {
                    q.append('&');
                }
                q.append(enc(e.getKey())).append('=').append(enc(nz(e.getValue())));
            }
            target += (target.contains("?") ? "&" : "?") + q;
        }

        for (int hop = 0; hop < 6; hop++) {
            HttpURLConnection c = null;
            try {
                c = (HttpURLConnection) new URL(target).openConnection();
                c.setInstanceFollowRedirects(false);
                c.setConnectTimeout(20000);
                c.setReadTimeout(25000);
                c.setRequestProperty("User-Agent", C.UA);
                c.setRequestProperty("Accept-Language", "zh-CN,zh;q=0.9");
                c.setRequestProperty("Accept", "text/html,application/json,application/xhtml+xml,*/*");
                String ckh = cookieHeader();
                if (!ckh.isEmpty()) {
                    c.setRequestProperty("Cookie", ckh);
                }
                if (referer != null && !referer.isEmpty()) {
                    c.setRequestProperty("Referer", referer);
                }
                if (post != null) {
                    c.setRequestMethod("POST");
                    c.setDoOutput(true);
                    c.setRequestProperty("Content-Type", ctype);
                    c.setFixedLengthStreamingMode(post.length);
                    OutputStream os = c.getOutputStream();
                    os.write(post);
                    os.flush();
                    os.close();
                } else {
                    c.setRequestMethod("GET");
                }

                int code = c.getResponseCode();
                absorb(c.getHeaderFields());

                if (code >= 300 && code < 400) {
                    String loc = c.getHeaderField("Location");
                    if (loc == null || loc.isEmpty()) {
                        return "";
                    }
                    target = new URL(new URL(target), loc).toString();
                    post = null;
                    c.disconnect();
                    continue;
                }
                InputStream is = code >= 400 ? c.getErrorStream() : c.getInputStream();
                byte[] raw = is == null ? new byte[0] : readAll(is);
                return decode(raw, c.getContentType());
            } catch (IOException e) {
                throw new Err("网络请求失败：" + e.getMessage());
            } finally {
                if (c != null) {
                    c.disconnect();
                }
            }
        }
        throw new Err("重定向次数过多，请检查网络环境");
    }

    private String get(String url, Map<String, String> params, String referer) throws Err {
        return open(url, referer, params, null, null);
    }

    private String post(String url, LinkedHashMap<String, String> form, String referer) throws Err {
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<String, String> e : form.entrySet()) {
            if (sb.length() > 0) {
                sb.append('&');
            }
            sb.append(enc(e.getKey())).append('=').append(enc(nz(e.getValue())));
        }
        try {
            return open(url, referer, null, sb.toString().getBytes("UTF-8"),
                    "application/x-www-form-urlencoded");
        } catch (IOException e) {
            throw new Err("请求参数编码失败");
        }
    }

    private static String enc(String s) {
        try {
            return URLEncoder.encode(nz(s), "UTF-8");
        } catch (Exception e) {
            return "";
        }
    }

    private static byte[] readAll(InputStream is) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = is.read(buf)) > 0) {
            bos.write(buf, 0, n);
        }
        is.close();
        return bos.toByteArray();
    }

    private static String decode(byte[] raw, String contentType) {
        String ct = contentType == null ? "" : contentType.toLowerCase(Locale.ROOT);
        boolean gbk = ct.contains("gbk") || ct.contains("gb2312") || ct.contains("gb18030");
        String s;
        try {
            s = new String(raw, gbk ? "GBK" : "UTF-8");
        } catch (Exception e) {
            s = new String(raw);
        }
        if (!gbk) {
            String head = s.length() > 1500 ? s.substring(0, 1500) : s;
            if (head.contains("charset=gb2312") || head.contains("charset=gbk")
                    || head.contains("charset=\"gb2312\"")) {
                try {
                    s = new String(raw, "GBK");
                } catch (Exception ignored) {
                }
            }
        }
        return s;
    }

    // ------------------------------------------------------------------ 登录
    void login(String user, String pwd, String schoolId) throws Err {
        String u = nz(user).trim();
        String p = nz(pwd).trim();
        if (u.isEmpty() || p.isEmpty()) {
            throw new Err("请填写账号和密码。");
        }
        get(C.PASS_PAGE, null, C.PASS_PAGE);       // 先拿一次会话 Cookie

        String eu;
        String ep;
        try {
            eu = Guard.field(u);
            ep = Guard.field(p);
        } catch (Exception e) {
            throw new Err("登录参数处理失败，请重试");
        }

        LinkedHashMap<String, String> form = new LinkedHashMap<>();
        form.put("fid", schoolId == null || schoolId.trim().isEmpty() ? "-1" : schoolId.trim());
        form.put("uname", eu);
        form.put("password", ep);
        form.put("refer", C.REFER_ENC);
        form.put("t", "true");
        form.put("forbidotherlogin", "0");
        form.put("validate", "");
        form.put("doubleFactorLogin", "0");
        form.put("independentId", "0");
        form.put("independentNameId", "0");

        String txt = post(C.PASS_API, form, C.PASS_PAGE);
        boolean ok = false;
        String msg = "";
        try {
            JSONObject o = new JSONObject(txt);
            ok = o.optBoolean("status", false);
            msg = o.optString("msg", o.optString("msg2", ""));
        } catch (Exception e) {
            if (txt.contains("验证码") || txt.toLowerCase(Locale.ROOT).contains("captcha")) {
                throw new Err("登录需要图形验证码，请改用「粘贴 Cookie 导入」。");
            }
            throw new Err("登录接口返回异常，请稍后重试（可能被风控拦截）。");
        }
        if (!ok) {
            if (msg.contains("验证码") || msg.toLowerCase(Locale.ROOT).contains("captcha")) {
                throw new Err("登录需要图形验证码，请改用「粘贴 Cookie 导入」。");
            }
            throw new Err("登录失败：" + (msg.isEmpty() ? "账号或密码不正确" : msg));
        }

        // 有的部署要跳一次首页才下发 _uid / fid
        if (nz(ck.get("_uid")).isEmpty() || nz(ck.get("fid")).isEmpty()) {
            for (String u2 : new String[]{C.HOME_BASE, C.HOME_I}) {
                try {
                    get(u2, null, C.HOME_I);
                } catch (Err ignored) {
                }
                if (!nz(ck.get("_uid")).isEmpty() && !nz(ck.get("fid")).isEmpty()) {
                    break;
                }
            }
        }

        if (nz(ck.get("_uid")).isEmpty() && nz(ck.get("uid")).isEmpty()) {
            throw new Err("登录返回成功，但没有拿到登录 Cookie，请改用「粘贴 Cookie 导入」。");
        }
        fid = nz(ck.get("fid"));
        uid = nz(ck.get("uid")).isEmpty() ? nz(ck.get("_uid")) : nz(ck.get("uid"));
        if (fid.isEmpty()) {
            throw new Err("登录成功但缺少学校信息，请填写学校 ID 后重试，或改用「粘贴 Cookie 导入」。");
        }
    }

    // ------------------------------------------------------------------ 课程
    List<Tasks.Course> courses() {
        List<Tasks.Course> out = new ArrayList<>();
        Set<String> seen = new HashSet<>();

        String[] types = {"", "1", "2", "3"};
        for (String ct : types) {
            LinkedHashMap<String, String> p = new LinkedHashMap<>();
            p.put("view", "json");
            p.put("rss", "1");
            if (!ct.isEmpty()) {
                p.put("courseType", ct);
            }
            try {
                merge(out, seen, parseCourseJson(get(C.COURSE_JSON, p, C.REF_I)));
            } catch (Err e) {
                // 单个分组失败不影响其它
            }
        }

        List<Object[]> htmls = new ArrayList<>();
        if (!fid.isEmpty()) {
            LinkedHashMap<String, String> p1 = new LinkedHashMap<>();
            p1.put("courseType", "1");
            p1.put("courseFid", fid);
            htmls.add(new Object[]{C.COURSE_LIST, p1});
        }
        htmls.add(new Object[]{C.COURSE_LIST, null});
        htmls.add(new Object[]{C.COURSE_LIST_FB, null});
        for (Object[] h : htmls) {
            @SuppressWarnings("unchecked")
            Map<String, String> ps = (Map<String, String>) h[1];
            try {
                merge(out, seen, parseCourseHtml(get((String) h[0], ps, C.REF_M2)));
            } catch (Err ignored) {
            }
        }

        String[][] homes = {
                {C.HOME_BASE, C.REF_I},
                {C.VISIT_OLD, C.REF_I},
                {C.VISIT_M2, C.REF_I},
        };
        for (String[] hm : homes) {
            try {
                merge(out, seen, parseCourseHtml(get(hm[0], null, hm[1])));
            } catch (Err ignored) {
            }
        }
        return out;
    }

    private void merge(List<Tasks.Course> out, Set<String> seen, List<Tasks.Course> add) {
        for (Tasks.Course c : add) {
            if (c.courseId.isEmpty() || c.classId.isEmpty()) {
                continue;
            }
            String key = c.courseId + "/" + c.classId;
            if (!seen.add(key)) {
                continue;
            }
            if (!c.cpi.isEmpty() && cpi.isEmpty()) {
                cpi = c.cpi;
            }
            out.add(c);
        }
    }

    private List<Tasks.Course> parseCourseJson(String txt) {
        List<Tasks.Course> out = new ArrayList<>();
        JSONObject o;
        try {
            o = new JSONObject(txt);
        } catch (Exception e) {
            return out;
        }
        if (o.optInt("result", 0) != 1) {
            return out;
        }
        JSONArray chs = o.optJSONArray("channelList");
        if (chs == null) {
            return out;
        }
        for (int i = 0; i < chs.length(); i++) {
            JSONObject ch = chs.optJSONObject(i);
            if (ch == null) {
                continue;
            }
            JSONObject content = ch.optJSONObject("content");
            if (content == null) {
                continue;
            }
            JSONObject course = content.optJSONObject("course");
            if (course == null) {
                continue;
            }
            JSONArray data = course.optJSONArray("data");
            if (data == null) {
                continue;
            }
            String clazzId = content.optString("id", "");
            String cpiV = content.optString("cpi", "");
            boolean retired = "1".equals(ch.optString("isretire", content.optString("isretire", "0")));
            for (int j = 0; j < data.length(); j++) {
                JSONObject c = data.optJSONObject(j);
                if (c == null) {
                    continue;
                }
                String cid = c.optString("id", "");
                if (cid.isEmpty() || clazzId.isEmpty()) {
                    continue;
                }
                Tasks.Course co = new Tasks.Course();
                co.name = c.optString("name", cid);
                co.courseId = cid;
                co.classId = clazzId;
                co.cpi = cpiV;
                co.retired = retired;
                out.add(co);
            }
        }
        return out;
    }

    private List<Tasks.Course> parseCourseHtml(String html) {
        List<Tasks.Course> out = new ArrayList<>();
        if (html == null || html.isEmpty()) {
            return out;
        }
        Document doc = Jsoup.parse(html);
        Elements cards = new Elements();
        for (String sel : new String[]{"div.course", "div.course-item", "li.course-item"}) {
            cards = doc.select(sel);
            if (!cards.isEmpty()) {
                break;
            }
        }
        if (cards.isEmpty()) {
            for (Element a : doc.select("a[href]")) {
                String href = a.attr("href");
                if (href.contains("stucoursemiddle")
                        || (href.contains("courseid=") && href.contains("clazzid="))) {
                    Element p = a.parent();
                    while (p != null && !"li".equals(p.tagName()) && !"div".equals(p.tagName())) {
                        p = p.parent();
                    }
                    cards.add(p == null ? a : p);
                }
            }
        }

        Set<String> seen = new HashSet<>();
        for (Element card : cards) {
            String name = "";
            Element nm = card.selectFirst("span.course-name");
            if (nm == null) {
                nm = card.selectFirst(".course-name");
            }
            if (nm != null) {
                name = nm.attr("title");
                if (name.isEmpty()) {
                    name = nm.text().trim();
                }
            }
            if (name.isEmpty()) {
                Element a0 = card.selectFirst("a[href]");
                if (a0 != null) {
                    name = a0.text().trim();
                }
            }
            if (name.isEmpty() && "a".equals(card.tagName())) {
                name = card.text().trim();
            }

            Element a = null;
            for (Element cand : card.select("a[href]")) {
                if (cand.attr("href").contains("stucoursemiddle")) {
                    a = cand;
                    break;
                }
            }
            if (a == null) {
                a = card.selectFirst("a[href]");
            }
            if (a == null && "a".equals(card.tagName())) {
                a = card;
            }
            String href = a == null ? "" : a.attr("href");

            String courseId = "";
            String clazzId = "";
            String cpiV = "";
            if (!href.isEmpty()) {
                try {
                    Uri uri = Uri.parse(href);
                    courseId = nz(uri.getQueryParameter("courseid"));
                    clazzId = nz(uri.getQueryParameter("clazzid"));
                    cpiV = nz(uri.getQueryParameter("cpi"));
                } catch (Exception ignored) {
                }
            }
            for (Element inp : card.select("input")) {
                String n = inp.attr("name");
                if (n.isEmpty()) {
                    n = inp.attr("id");
                }
                if (n.isEmpty()) {
                    continue;
                }
                String v = inp.attr("value");
                if ("courseId".equals(n) && courseId.isEmpty()) {
                    courseId = v;
                } else if (("clazzId".equals(n) || "classId".equals(n)) && clazzId.isEmpty()) {
                    clazzId = v;
                } else if ("cpi".equals(n) && cpiV.isEmpty()) {
                    cpiV = v;
                }
            }
            if (courseId.isEmpty() || clazzId.isEmpty()) {
                continue;
            }
            if (!seen.add(courseId + "/" + clazzId)) {
                continue;
            }
            Tasks.Course c = new Tasks.Course();
            c.name = name.isEmpty() ? (courseId + "/" + clazzId) : name;
            c.courseId = courseId;
            c.classId = clazzId;
            c.cpi = cpiV;
            c.url = href;
            out.add(c);
        }
        return out;
    }

    // ------------------------------------------------------------------ 课程详情
    void detail(Tasks.Course c) {
        String cpiV = nz(c.cpi);
        List<Object[]> urls = new ArrayList<>();
        urls.add(new Object[]{"old", C.DETAIL_A + "?courseid=" + c.courseId + "&clazzid=" + c.classId + "&ismooc2=1&v=2"});
        urls.add(new Object[]{"old", C.DETAIL_B + "?courseid=" + c.courseId + "&clazzid=" + c.classId + "&cpi=" + cpiV + "&v=2"});
        urls.add(new Object[]{"old", C.DETAIL_C + "?courseid=" + c.courseId + "&clazzid=" + c.classId + "&ismooc2=1&v=2"});
        urls.add(new Object[]{"old", C.DETAIL_D + "?courseid=" + c.courseId + "&clazzid=" + c.classId + "&ismooc2=1&v=2"});
        urls.add(new Object[]{"new", C.DETAIL_NEW + "?courseid=" + c.courseId + "&clazzid=" + c.classId + "&cpi=" + cpiV + "&ut=s"});

        boolean any = false;
        for (Object[] u : urls) {
            String html;
            try {
                html = get((String) u[1], null, C.REF_M2);
            } catch (Err e) {
                continue;
            }
            any = true;
            Map<String, String> f = encFields(html);
            if (c.cpi.isEmpty() && !nz(f.get("cpi")).isEmpty()) {
                c.cpi = f.get("cpi");
            }
            if (c.workEnc.isEmpty() && !nz(f.get("workEnc")).isEmpty()) {
                c.workEnc = f.get("workEnc");
            }
            if (c.enc.isEmpty() && !nz(f.get("enc")).isEmpty()) {
                c.enc = f.get("enc");
            }
            if (c.openc.isEmpty() && !nz(f.get("openc")).isEmpty()) {
                c.openc = f.get("openc");
            }
            if (c.examEnc.isEmpty() && !nz(f.get("examEnc")).isEmpty()) {
                c.examEnc = f.get("examEnc");
            }
            if (c.token.isEmpty() && !nz(f.get("token")).isEmpty()) {
                c.token = f.get("token");
            }
            if (!c.cpi.isEmpty() && cpi.isEmpty()) {
                cpi = c.cpi;
            }
            if (!c.workEnc.isEmpty() || !c.enc.isEmpty()) {
                c.style = (String) u[0];
                return;
            }
        }
        if (any) {
            // 能打开但没 enc：新版课程页的特征，作业仍走不带 enc 的新路径
            c.style = "new";
        }
    }

    private static Map<String, String> encFields(String html) {
        Map<String, String> out = new HashMap<>();
        if (html == null) {
            return out;
        }
        Document doc = Jsoup.parse(html);
        Map<String, String> hid = new HashMap<>();
        for (Element inp : doc.select("input")) {
            String n = inp.attr("name");
            if (n.isEmpty()) {
                n = inp.attr("id");
            }
            if (!n.isEmpty()) {
                hid.put(n, inp.attr("value"));
            }
        }
        out.put("cpi", nz(hid.get("cpi")));
        out.put("workEnc", nz(hid.get("workEnc")));
        String e1 = hid.get("enc");
        if (e1 == null || e1.isEmpty()) {
            e1 = hid.get("oldenc");
        }
        out.put("enc", nz(e1));
        out.put("openc", nz(hid.get("openc")));
        out.put("examEnc", nz(hid.get("examEnc")));
        out.put("token", nz(hid.get("token")));

        if (out.get("workEnc").isEmpty()) {
            Matcher m = Pattern.compile("workEnc\\s*[:=]\\s*[\"']([0-9a-fA-F]{16,})[\"']").matcher(html);
            if (m.find()) {
                out.put("workEnc", m.group(1));
            }
        }
        if (out.get("enc").isEmpty()) {
            Matcher m = Pattern.compile("enc=([0-9a-fA-F]{32})").matcher(html);
            if (m.find()) {
                out.put("enc", m.group(1));
            }
        }
        if (out.get("openc").isEmpty()) {
            Matcher m = Pattern.compile("id=\"openc\"[^>]*value=\"([0-9a-fA-F]+)\"").matcher(html);
            if (m.find()) {
                out.put("openc", m.group(1));
            }
        }
        return out;
    }

    // ------------------------------------------------------------------ 作业
    private LinkedHashMap<String, String> workParams(Tasks.Course c) {
        LinkedHashMap<String, String> p = new LinkedHashMap<>();
        p.put("courseId", c.courseId);
        p.put("classId", c.classId);
        p.put("cpi", nz(c.cpi));
        p.put("ut", "s");
        p.put("openc", nz(c.openc));
        p.put("enc", nz(c.workEnc));
        p.put("stuenc", nz(c.enc));
        p.put("token", nz(c.token));
        p.put("isdisplaytable", "2");
        p.put("status", "0");
        return p;
    }

    private List<Tasks.Item> worksOne(Tasks.Course c, String route, int maxPages) {
        String url;
        boolean paged;
        if ("new".equals(route)) {
            url = C.WORK_NEW;
            paged = true;
        } else if ("mooc1".equals(route)) {
            url = C.WORK_M1;
            paged = false;
        } else if ("bare".equals(route)) {
            url = C.WORK_M2;
            paged = false;
        } else {
            url = C.WORK_M2;
            paged = false;
        }

        LinkedHashMap<String, String> base;
        if ("bare".equals(route)) {
            base = new LinkedHashMap<>();
            base.put("courseId", c.courseId);
            base.put("classId", c.classId);
            base.put("status", "0");
        } else {
            base = workParams(c);
        }

        String referer = c.url == null || c.url.isEmpty() ? C.REF_M1 : c.url;
        List<Tasks.Item> items = new ArrayList<>();
        Set<String> seen = new HashSet<>();

        for (int page = 1; page <= (paged ? maxPages : 1); page++) {
            LinkedHashMap<String, String> p = new LinkedHashMap<>(base);
            p.put("t", String.valueOf(System.currentTimeMillis()));
            if (paged) {
                p.put("pageNum", String.valueOf(page));
            }
            String html;
            try {
                html = get(url, p, referer);
            } catch (Err e) {
                break;
            }
            int added = 0;
            for (Tasks.Item w : parseWorks(html)) {
                String key = w.link.isEmpty() ? (w.name + "|" + w.remain) : w.link;
                if (!seen.add(key)) {
                    continue;
                }
                items.add(w);
                added++;
            }
            if (added == 0) {
                break;
            }
            if (paged) {
                sleep(150);
            }
        }
        return items;
    }

    List<Tasks.Item> works(Tasks.Course c) {
        String[] order = "old".equals(c.style)
                ? new String[]{"mooc2", "mooc1", "new"}
                : new String[]{"new", "mooc2", "mooc1"};
        List<Tasks.Item> items = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (String route : order) {
            int maxPages = items.isEmpty() ? MAX_PAGES : 1;
            for (Tasks.Item w : worksOne(c, route, maxPages)) {
                String key = w.link.isEmpty() ? (w.name + "|" + w.remain) : w.link;
                if (!seen.add(key)) {
                    continue;
                }
                items.add(w);
            }
        }
        if (items.isEmpty()) {
            for (Tasks.Item w : worksOne(c, "bare", 1)) {
                String key = w.link.isEmpty() ? (w.name + "|" + w.remain) : w.link;
                if (!seen.add(key)) {
                    continue;
                }
                items.add(w);
            }
        }
        return items;
    }

    private List<Tasks.Item> parseWorks(String html) {
        List<Tasks.Item> items = new ArrayList<>();
        if (html == null || html.isEmpty()) {
            return items;
        }
        Document doc = Jsoup.parse(html);
        Elements lis = new Elements();
        String[] sels = {
                ".bottomList li", ".bottomList ul li", "ul.ulDiv li",
                ".workList li", ".workList ul li",
        };
        for (String sel : sels) {
            lis = doc.select(sel);
            if (!lis.isEmpty()) {
                break;
            }
        }
        if (lis.isEmpty()) {
            for (Element li : doc.select("li")) {
                if (li.selectFirst("p.overHidden2") != null || li.selectFirst(".overHidden2") != null) {
                    lis.add(li);
                }
            }
        }

        for (Element li : lis) {
            Element nameTag = li.selectFirst("p.overHidden2");
            if (nameTag == null) {
                nameTag = li.selectFirst(".overHidden2");
            }
            String name;
            if (nameTag != null) {
                name = nameTag.text().trim();
            } else {
                Element a0 = li.selectFirst("a[href]");
                name = a0 == null ? "" : a0.text().trim();
            }
            if (name.isEmpty()) {
                continue;
            }
            Element statusTag = li.selectFirst("p.status");
            if (statusTag == null) {
                statusTag = li.selectFirst(".status");
            }
            String status = statusTag == null ? "" : statusTag.text().trim();
            if (status.isEmpty()) {
                String aria = li.attr("aria-label");
                if (aria.contains(";")) {
                    String[] parts = aria.split(";");
                    status = parts[parts.length - 1].trim();
                }
            }
            Element timeTag = li.selectFirst("div.time");
            if (timeTag == null) {
                timeTag = li.selectFirst(".time");
            }
            String remain = timeTag == null ? "" : timeTag.text().trim();

            String link = li.attr("data");
            if (link.isEmpty()) {
                Element a = li.selectFirst("a[href]");
                if (a != null) {
                    link = a.attr("href");
                }
            }
            if (link.startsWith("//")) {
                link = "https:" + link;
            } else if (link.startsWith("/")) {
                link = C.MOOC1_HOST + link;
            }

            Tasks.Item w = new Tasks.Item();
            w.name = name;
            w.status = status;
            w.remain = remain;
            w.link = link;
            w.done = Parse.isDone(status);
            items.add(w);
        }
        return items;
    }

    private String[] taskTimes(String url, Date ref) {
        String html;
        try {
            html = get(url, null, url.contains(C.MOOC_ANS) ? (C.REF_M1 + C.MOOC_ANS + "/") : C.WORK_M2);
        } catch (Err e) {
            return new String[]{"", ""};
        }
        Matcher m = Pattern.compile(
                "作答时间\\s*[：:]\\s*<em>\\s*([^<]*?)\\s*</em>\\s*至\\s*<em>\\s*([^<]*?)\\s*</em>")
                .matcher(html);
        if (!m.find()) {
            m = Pattern.compile(
                    "<em>\\s*([\\d./\\-]+\\s+[\\d:]+)\\s*</em>\\s*至\\s*<em>\\s*([\\d./\\-]+\\s+[\\d:]*)")
                    .matcher(html);
            if (!m.find()) {
                String text = Jsoup.parse(html).text();
                Matcher m2 = Pattern.compile(
                        "作答时间\\s*[：:]\\s*([\\d./\\-]+\\s+[\\d:]+)\\s*至\\s*([\\d./\\-]+\\s+[\\d:]+)?")
                        .matcher(text);
                if (!m2.find()) {
                    return new String[]{"", ""};
                }
                return new String[]{m2.group(1), m2.group(2) == null ? "" : m2.group(2)};
            }
        }
        return new String[]{m.group(1).trim(), m.group(2).trim()};
    }

    private Tasks.T toTask(Tasks.Item w, String cname) {
        long now = System.currentTimeMillis();
        long rem = Parse.remainingMs(w.remain);
        Date ref = new Date(rem >= 0 ? now + rem : now);

        Date start = null;
        Date end = null;
        if (!w.link.isEmpty() && !w.done) {
            String[] ti = taskTimes(w.link, ref);
            start = Parse.dt(ti[0], ref);
            end = Parse.dt(ti[1], ref);
        }
        boolean approx = false;
        if (end == null && rem >= 0) {
            end = new Date(now + rem);
            approx = true;
        }
        String display;
        if (end != null) {
            display = Parse.hm(end);
            if (approx) {
                display = "约 " + display + "（" + w.remain + "）";
            }
        } else {
            display = w.remain.isEmpty() ? "未注明" : w.remain;
        }

        Tasks.T t = new Tasks.T();
        t.type = "作业";
        t.course = cname;
        t.name = w.name;
        t.status = w.status.isEmpty() ? (w.done ? "已完成" : "未交") : w.status;
        t.deadline = display;
        t.deadlineIso = Parse.iso(end);
        t.startIso = Parse.iso(start);
        t.approx = approx;
        t.remain = w.remain;
        t.link = w.link;
        t.done = w.done;
        return t;
    }

    // ------------------------------------------------------------------ 考试
    List<Tasks.T> exams() {
        List<Tasks.T> items = new ArrayList<>();
        if (cpi.isEmpty()) {
            return items;
        }
        String[] routes = {C.EXAM_NEW, C.EXAM_MID, C.EXAM_OLD};
        Set<String> seen = new HashSet<>();
        int start = 0;
        for (int round = 0; round < 8; round++) {
            List<Tasks.T> pageAll = new ArrayList<>();
            for (String url : routes) {
                LinkedHashMap<String, String> p = new LinkedHashMap<>();
                p.put("cpi", cpi);
                p.put("status", "-1");
                p.put("start", String.valueOf(start));
                try {
                    pageAll.addAll(parseExams(get(url, p, C.REF_M1)));
                } catch (Err ignored) {
                }
            }
            int added = 0;
            for (Tasks.T it : pageAll) {
                if (!seen.add(it.name + "|" + it.deadline)) {
                    continue;
                }
                items.add(it);
                added++;
            }
            if (added == 0 || pageAll.size() < 12) {
                break;
            }
            start += 12;
        }
        return items;
    }

    private List<Tasks.T> parseExams(String html) {
        List<Tasks.T> items = new ArrayList<>();
        if (html == null || html.isEmpty()) {
            return items;
        }
        Document doc = Jsoup.parse(html);
        for (Element tr : doc.select("tr.dataTr")) {
            Elements tds = tr.select("td");
            if (tds.size() < 5) {
                continue;
            }
            Element table = tr.parents().select("table").first();
            Map<String, Integer> cmap = new HashMap<>();
            if (table != null) {
                Element firstTr = table.selectFirst("tr");
                if (firstTr != null) {
                    Elements ths = firstTr.select("th");
                    for (int i = 0; i < ths.size(); i++) {
                        String h = ths.get(i).text().trim();
                        if (!h.isEmpty()) {
                            cmap.put(h, i);
                        }
                    }
                }
            }
            List<String> cols = new ArrayList<>();
            for (Element td : tds) {
                cols.add(td.text().trim());
            }

            String name = col(cols, cmap, "考试名称", 1);
            if (name.isEmpty()) {
                continue;
            }
            String timerange = col(cols, cmap, "考试时间", 2);
            String examStatus = col(cols, cmap, "考试状态", 4);
            String answerStatus = col(cols, cmap, "作答状态", 5);
            String score = col(cols, cmap, "分数", 6);

            String link = "";
            int opsI = cmap.containsKey("操作") ? cmap.get("操作") : tds.size() - 1;
            if (opsI >= 0 && opsI < tds.size()) {
                Element cell = tds.get(opsI);
                Element a = cell.selectFirst("a[onclick]");
                if (a == null) {
                    a = cell.selectFirst("a[href]");
                }
                if (a != null) {
                    Matcher m = Pattern.compile("go\\(\\s*'([^']+)'").matcher(a.attr("onclick"));
                    if (m.find()) {
                        link = C.MOOC1_HOST + m.group(1);
                    } else if (a.attr("href").startsWith("http")) {
                        link = a.attr("href");
                    }
                }
            }

            String[] parts = timerange.isEmpty() ? new String[0] : timerange.split("\\s*至\\s*");
            Date startDt = parts.length > 0 ? Parse.dt(parts[0], null) : null;
            Date endDt = parts.length > 1 ? Parse.dt(parts[1], null) : null;
            String shown;
            if (startDt != null && endDt != null
                    && sameDay(startDt, endDt)) {
                shown = Parse.hm(startDt) + "–"
                        + new java.text.SimpleDateFormat("HH:mm", Locale.CHINA).format(endDt);
            } else if (startDt != null && endDt != null) {
                shown = Parse.hm(startDt) + " 至 " + Parse.hm(endDt);
            } else {
                shown = timerange.isEmpty() ? "未注明" : timerange;
            }

            Tasks.T t = new Tasks.T();
            t.type = "考试";
            t.course = "";
            t.name = name;
            t.status = answerStatus.isEmpty() ? examStatus : answerStatus;
            t.examStatus = examStatus;
            t.score = score;
            t.deadline = shown;
            t.deadlineIso = Parse.iso(endDt != null ? endDt : startDt);
            t.startIso = Parse.iso(startDt);
            t.link = link;
            t.done = Parse.isDone(answerStatus);
            items.add(t);
        }
        return items;
    }

    private static String col(List<String> cols, Map<String, Integer> cmap, String key, int def) {
        int i = cmap.containsKey(key) ? cmap.get(key) : def;
        return (i >= 0 && i < cols.size()) ? cols.get(i) : "";
    }

    private static boolean sameDay(Date a, Date b) {
        java.util.Calendar ca = java.util.Calendar.getInstance();
        ca.setTime(a);
        java.util.Calendar cb = java.util.Calendar.getInstance();
        cb.setTime(b);
        return ca.get(java.util.Calendar.YEAR) == cb.get(java.util.Calendar.YEAR)
                && ca.get(java.util.Calendar.DAY_OF_YEAR) == cb.get(java.util.Calendar.DAY_OF_YEAR);
    }

    // ------------------------------------------------------------------ 聚合
    Tasks.Res extractAll(boolean onlyIncomplete, P progress) {
        Tasks.Res res = new Tasks.Res();
        List<Tasks.Course> cs = courses();
        res.courses = cs.size();
        if (cs.isEmpty()) {
            res.hint = "没有读到任何课程。请先确认学习通能正常打开课程列表，再点「重新提取」。";
        }

        for (Tasks.Course c : cs) {
            String cname = c.name == null || c.name.isEmpty() ? "未知课程" : c.name;
            if (progress != null) {
                progress.step("正在读取：" + cname);
            }
            detail(c);
            if (c.courseId.isEmpty() || c.classId.isEmpty()) {
                res.errors.add("「" + cname + "」缺少课程标识，已跳过");
                continue;
            }
            List<Tasks.Item> ws = works(c);
            for (Tasks.Item w : ws) {
                if (onlyIncomplete && w.done) {
                    continue;
                }
                res.tasks.add(toTask(w, cname));
            }
            sleep(120);
        }

        if (progress != null) {
            progress.step("正在读取考试列表…");
        }
        for (Tasks.T e : exams()) {
            if (onlyIncomplete && e.done) {
                continue;
            }
            res.tasks.add(e);
        }

        long now = System.currentTimeMillis();
        for (Tasks.T t : res.tasks) {
            t.state = Tasks.state(t, now);
            res.counts[Tasks.rank(t.state)]++;
        }
        Collections.sort(res.tasks, new Comparator<Tasks.T>() {
            @Override
            public int compare(Tasks.T a, Tasks.T b) {
                int ra = Tasks.rank(a.state);
                int rb = Tasks.rank(b.state);
                if (ra != rb) {
                    return ra - rb;
                }
                boolean ea = a.deadlineIso.isEmpty();
                boolean eb = b.deadlineIso.isEmpty();
                if (ea != eb) {
                    return ea ? 1 : -1;
                }
                return a.deadlineIso.compareTo(b.deadlineIso);
            }
        });
        return res;
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }

    private static String nz(String s) {
        return s == null ? "" : s;
    }
}
