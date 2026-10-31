package com.cx.helper;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.Charset;
import java.security.KeyStore;
import java.security.SecureRandom;
import java.util.LinkedHashMap;
import java.util.Map;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * 登录态的本地加密。
 *
 * 两层：Android Keystore 里一把不可导出的 KEK（AES-256-GCM，关闭了用户认证要求，
 * 打开应用不弹指纹），用它包裹一个随机 DEK；真正加密 Cookie 的是 DEK。
 * 密钥不进文件、不进内存转储之外的任何地方：把文件拷到别的手机或电脑上解不开，
 * 换机、清除数据、卸载重装后也自然失效（等同于「未登录」，静默回到登录页）。
 */
final class Store {
    private Store() {
    }

    private static final String KS = "AndroidKeyStore";
    private static final String ALIAS = "cx_k";
    private static final int TAG_BITS = 128;
    private static final String F_DEK = "d.bin";
    private static final String F_SES = "s.bin";

    // ------------------------------------------------------------------ KEK
    private static SecretKey kek(boolean create) throws Exception {
        KeyStore ks = KeyStore.getInstance(KS);
        ks.load(null);
        if (ks.containsAlias(ALIAS)) {
            return (SecretKey) ks.getKey(ALIAS, null);
        }
        if (!create) {
            return null;
        }
        KeyGenerator kg = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KS);
        kg.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setUserAuthenticationRequired(false)
                .setRandomizedEncryptionRequired(true)
                .build());
        return kg.generateKey();
    }

    private static byte[] gcm(SecretKey key, int mode, byte[] iv, byte[] data) throws Exception {
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(mode, key, new GCMParameterSpec(TAG_BITS, iv));
        return c.doFinal(data);
    }

    private static byte[] seal(SecretKey key, byte[] plain) throws Exception {
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.ENCRYPT_MODE, key);
        byte[] iv = c.getIV();
        byte[] ct = c.doFinal(plain);
        byte[] out = new byte[iv.length + ct.length];
        System.arraycopy(iv, 0, out, 0, iv.length);
        System.arraycopy(ct, 0, out, iv.length, ct.length);
        return out;
    }

    private static byte[] unseal(SecretKey key, byte[] blob) throws Exception {
        if (blob == null || blob.length < 13) {
            return null;
        }
        byte[] iv = new byte[12];
        System.arraycopy(blob, 0, iv, 0, 12);
        byte[] ct = new byte[blob.length - 12];
        System.arraycopy(blob, 12, ct, 0, ct.length);
        return gcm(key, Cipher.DECRYPT_MODE, iv, ct);
    }

    // ------------------------------------------------------------------ DEK
    private static SecretKey dek(Context ctx, boolean create) throws Exception {
        File f = new File(ctx.getFilesDir(), F_DEK);
        if (f.exists()) {
            byte[] wrapped = read(f);
            SecretKey k = kek(false);
            if (k != null) {
                byte[] raw = unseal(k, wrapped);
                if (raw != null && raw.length == 32) {
                    return new SecretKeySpec(raw, "AES");
                }
            }
            if (!create) {
                return null;
            }
            f.delete();
        }
        if (!create) {
            return null;
        }
        byte[] raw = new byte[32];
        new SecureRandom().nextBytes(raw);
        SecretKey k = kek(true);
        write(f, seal(k, raw));
        return new SecretKeySpec(raw, "AES");
    }

    // ------------------------------------------------------------------ 对外
    static boolean save(Context ctx, Map<String, String> cookies) {
        try {
            JSONObject o = new JSONObject();
            for (Map.Entry<String, String> e : cookies.entrySet()) {
                o.put(e.getKey(), e.getValue());
            }
            SecretKey d = dek(ctx, true);
            byte[] blob = seal(d, o.toString().getBytes(Charset.forName("UTF-8")));
            write(new File(ctx.getFilesDir(), F_SES), blob);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    static Map<String, String> load(Context ctx) {
        Map<String, String> out = new LinkedHashMap<>();
        try {
            File f = new File(ctx.getFilesDir(), F_SES);
            if (!f.exists()) {
                return out;
            }
            SecretKey d = dek(ctx, false);
            if (d == null) {
                return out;
            }
            byte[] plain = unseal(d, read(f));
            if (plain == null) {
                return out;
            }
            JSONObject o = new JSONObject(new String(plain, Charset.forName("UTF-8")));
            java.util.Iterator<String> it = o.keys();
            while (it.hasNext()) {
                String k = it.next();
                out.put(k, String.valueOf(o.opt(k)));
            }
        } catch (Exception e) {
            out.clear();       // 解不开就当作未登录，不解释原因
        }
        return out;
    }

    static void clear(Context ctx) {
        try {
            new File(ctx.getFilesDir(), F_SES).delete();
            new File(ctx.getFilesDir(), F_DEK).delete();
            KeyStore ks = KeyStore.getInstance(KS);
            ks.load(null);
            if (ks.containsAlias(ALIAS)) {
                ks.deleteEntry(ALIAS);
            }
        } catch (Exception ignored) {
        }
    }

    // ------------------------------------------------------------------ 文件
    private static byte[] read(File f) throws Exception {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        FileInputStream in = new FileInputStream(f);
        try {
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) {
                bos.write(buf, 0, n);
            }
        } finally {
            in.close();
        }
        return bos.toByteArray();
    }

    private static void write(File f, byte[] data) throws Exception {
        FileOutputStream out = new FileOutputStream(f);
        try {
            out.write(data);
            out.flush();
        } finally {
            out.close();
        }
    }

    static String fingerprint(String s) {
        try {
            byte[] d = java.security.MessageDigest.getInstance("SHA-256")
                    .digest(s.getBytes(Charset.forName("UTF-8")));
            return Base64.encodeToString(d, Base64.NO_WRAP).substring(0, 8);
        } catch (Exception e) {
            return "";
        }
    }
}
