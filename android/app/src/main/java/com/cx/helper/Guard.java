package com.cx.helper;

import android.util.Base64;

import java.nio.charset.Charset;

import javax.crypto.Cipher;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * 登录字段的传输层封装。
 *
 * 密钥由若干碎片在运行时拼出来（每片先反序、再逐字节异或一个掩码和一个位置偏移），
 * 源码与二进制里都不出现连续的 16 字节密钥，也不出现可直接用于解密的常量。
 * 算法与网页端一致：AES-128-CBC，IV 与密钥相同，PKCS#5 填充，Base64 输出。
 */
final class Guard {
    private Guard() {
    }

    /** 每行：4 个密文字节 + 1 个掩码 */
    private static final int[][] F = {
            {0xEF, 0xE8, 0xB5, 0xF2, 0x9A},
            {0x59, 0x72, 0x51, 0x31, 0x3D},
            {0xA2, 0xF3, 0xC1, 0xDE, 0xC1},
            {0x00, 0x16, 0x12, 0x0C, 0x27},
    };

    private static byte[] key() {
        byte[] out = new byte[F.length * 4];
        int p = 0;
        for (int i = 0; i < F.length; i++) {
            int[] row = F[i];
            int mask = row[4];
            int shift = ((i + 1) * 0x1D) & 0xFF;
            for (int j = 0; j < 4; j++) {
                out[p++] = (byte) (row[3 - j] ^ mask ^ shift);
            }
        }
        return out;
    }

    static String field(String text) throws Exception {
        if (text == null) {
            text = "";
        }
        byte[] k = key();
        Cipher c = Cipher.getInstance("AES/CBC/PKCS5Padding");
        c.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(k, "AES"), new IvParameterSpec(k));
        byte[] enc = c.doFinal(text.getBytes(Charset.forName("UTF-8")));
        return Base64.encodeToString(enc, Base64.NO_WRAP);
    }
}
