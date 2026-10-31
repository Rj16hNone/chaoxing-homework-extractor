package com.cx.helper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.ParsePosition;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** 解析工具：时间、剩余时长、已完成判定、Cookie 归一化。 */
final class Parse {
    private Parse() {
    }

    private static final String[] DONE_KW = {
            "已完成", "已交", "已提交", "已结束", "已批阅", "已交卷", "已做", "合格", "待批阅",
    };

    private static final String[] FMT = {
            "yyyy-M-d H:m:s",
            "yyyy-M-d H:m",
            "yyyy/M/d H:m:s",
            "yyyy/M/d H:m",
            "yyyy.M.d H:m",
            "yyyy-M-d",
            "yyyy/M/d",
    };
    private static final String[] FMT_NOYEAR = {
            "M-d H:m",
            "M/d H:m",
            "M月d日 H:m",
            "M月d日H:m",
            "M-d",
            "M/d",
            "M月d日",
    };

    static boolean isDone(String s) {
        if (s == null || s.isEmpty()) {
            return false;
        }
        for (String k : DONE_KW) {
            if (s.contains(k)) {
                return true;
            }
        }
        return false;
    }

    /** 解析时间文本；不带年份的按与参考时间最接近的那一年推断。 */
    static Date dt(String text, Date ref) {
        if (text == null) {
            return null;
        }
        String s = text.trim();
        if (s.isEmpty()) {
            return null;
        }
        Date r = ref == null ? new Date() : ref;
        Date d = tryFmt(s, FMT);
        if (d != null) {
            return d;
        }
        Date raw = tryFmt(s, FMT_NOYEAR);
        if (raw == null) {
            return null;
        }
        Calendar rc = Calendar.getInstance();
        rc.setTime(r);
        int year = rc.get(Calendar.YEAR);
        Date best = null;
        for (int y = year - 1; y <= year + 1; y++) {
            Calendar c = Calendar.getInstance();
            c.setTime(raw);
            c.set(Calendar.YEAR, y);
            Date cand = c.getTime();
            if (best == null
                    || Math.abs(cand.getTime() - r.getTime()) < Math.abs(best.getTime() - r.getTime())) {
                best = cand;
            }
        }
        return best;
    }

    private static Date tryFmt(String s, String[] fmts) {
        for (String f : fmts) {
            SimpleDateFormat sdf = new SimpleDateFormat(f, Locale.CHINA);
            sdf.setLenient(false);
            ParsePosition pp = new ParsePosition(0);
            Date d = sdf.parse(s, pp);
            if (d != null && pp.getIndex() == s.length()) {
                return d;
            }
        }
        return null;
    }

    /** 「剩余515小时48分钟 / 剩2天3小时 / 剩余30分钟」→ 毫秒；解析不出返回 -1。 */
    static long remainingMs(String text) {
        if (text == null || text.isEmpty()) {
            return -1;
        }
        long d = grab(text, "(\\d+)\\s*天");
        long h = grab(text, "(\\d+)\\s*(?:个)?\\s*小时");
        long m = grab(text, "(\\d+)\\s*分钟");
        if (d == 0 && h == 0 && m == 0) {
            return -1;
        }
        return ((d * 24 + h) * 60 + m) * 60000L;
    }

    private static long grab(String text, String re) {
        Matcher m = Pattern.compile(re).matcher(text);
        return m.find() ? Long.parseLong(m.group(1)) : 0;
    }

    static String hm(Date d) {
        return d == null ? "" : new SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.CHINA).format(d);
    }

    static String iso(Date d) {
        return d == null ? "" : new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.CHINA).format(d);
    }

    static Date fromIso(String s) {
        if (s == null || s.isEmpty()) {
            return null;
        }
        try {
            SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.CHINA);
            f.setLenient(false);
            ParsePosition pp = new ParsePosition(0);
            Date d = f.parse(s, pp);
            return (d != null && pp.getIndex() == s.length()) ? d : null;
        } catch (Exception e) {
            return null;
        }
    }

    /** Cookie 归一化：JSON 数组 / JSON 对象 / 截断 JSON / name=value;… 都认。 */
    static Map<String, String> cookies(String raw) {
        Map<String, String> out = new LinkedHashMap<>();
        if (raw == null) {
            return out;
        }
        String s = raw.trim();
        if (s.startsWith("\uFEFF")) {
            s = s.substring(1).trim();
        }
        if (s.isEmpty()) {
            return out;
        }

        try {
            JSONArray arr = new JSONArray(s);
            for (int i = 0; i < arr.length(); i++) {
                JSONObject o = arr.optJSONObject(i);
                if (o == null) {
                    continue;
                }
                String n = o.optString("name", o.optString("key", ""));
                String v = o.optString("value", "");
                if (!n.isEmpty()) {
                    out.put(n, v);
                }
            }
            if (!out.isEmpty()) {
                return out;
            }
        } catch (Exception ignored) {
        }

        try {
            JSONObject o = new JSONObject(s);
            java.util.Iterator<String> it = o.keys();
            while (it.hasNext()) {
                String k = it.next();
                out.put(k, String.valueOf(o.opt(k)));
            }
            if (!out.isEmpty()) {
                return out;
            }
        } catch (Exception ignored) {
        }

        // 截断的 JSON：把还能配对上的 name / value 抠出来
        if (s.contains("\"name\"") && s.contains("\"value\"")) {
            Matcher nm = Pattern.compile("\"name\"\\s*:\\s*\"([^\"]*)\"").matcher(s);
            Matcher vm = Pattern.compile("\"value\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"").matcher(s);
            java.util.List<int[]> vpos = new java.util.ArrayList<>();
            java.util.List<String> vval = new java.util.ArrayList<>();
            while (vm.find()) {
                vpos.add(new int[]{vm.start(), vm.end()});
                vval.add(vm.group(1));
            }
            int vi = 0;
            while (nm.find()) {
                while (vi < vpos.size() && vpos.get(vi)[0] < nm.end()) {
                    vi++;
                }
                if (vi < vpos.size() && vpos.get(vi)[0] - nm.end() < 500) {
                    out.put(nm.group(1), vval.get(vi).replace("\\\"", "\"").replace("\\\\", "\\"));
                    vi++;
                }
            }
            if (!out.isEmpty()) {
                return out;
            }
        }

        if (s.toLowerCase(Locale.ROOT).startsWith("cookie:")) {
            s = s.substring(7).trim();
        }
        for (String part : s.split(";")) {
            String p = part.trim();
            int eq = p.indexOf('=');
            if (eq <= 0) {
                continue;
            }
            out.put(p.substring(0, eq).trim(), p.substring(eq + 1).trim());
        }
        return out;
    }
}
