package com.cx.helper;

import android.util.Base64;

/**
 * 字符串还原：源码里只有 Base64 + 异或的密文，运行时才拼出明文，
 * 这样在 dex 里 grep 不到域名与接口路径。
 */
final class Str {
    private Str() {
    }

    static String d(String enc, int seed) {
        try {
            byte[] b = Base64.decode(enc, Base64.NO_WRAP);
            for (int i = 0; i < b.length; i++) {
                b[i] ^= (byte) ((seed + i * 31) & 0xFF);
            }
            return new String(b, "UTF-8");
        } catch (Exception e) {
            return "";
        }
    }
}
