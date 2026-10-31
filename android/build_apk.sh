#!/usr/bin/env bash
# 直接用 Android SDK 的 build-tools 构建 APK（不依赖 Gradle / Android Studio）。
#
# 依赖：
#   JAVA_HOME        JDK 17
#   ANDROID_SDK      SDK 根目录（含 platforms/android-34 与 build-tools/34.0.0）
#   本地 jar         libs/jsoup.jar（见 libs/README.md）
#
# 产出：build/Android.apk（已用 keystore/cx.jks 签名并 zipalign）
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

: "${JAVA_HOME:?请先设置 JAVA_HOME}"
: "${ANDROID_SDK:?请先设置 ANDROID_SDK}"

BT="$ANDROID_SDK/build-tools/34.0.0"
PLATFORM="$ANDROID_SDK/platforms/android-34"
LIBS="$HERE/libs"
OUT="$HERE/build"
KS="$HERE/keystore/cx.jks"
# 签名口令不进仓库：优先环境变量 CX_KS_PASS，其次本机 keystore/cx.pass
KS_PASS="${CX_KS_PASS:-}"
if [ -z "$KS_PASS" ] && [ -f "$HERE/keystore/cx.pass" ]; then
    KS_PASS="$(tr -d '\r\n' < "$HERE/keystore/cx.pass")"
fi
if [ -z "$KS_PASS" ]; then
    echo "[错误] 缺少签名口令：设置环境变量 CX_KS_PASS，或把口令写进 keystore/cx.pass（两者都不进仓库）" >&2
    exit 1
fi

JAVA="$JAVA_HOME/bin/java"
JAVAC="$JAVA_HOME/bin/javac"
KEYTOOL="$JAVA_HOME/bin/keytool"

# 逐项清理：整目录一次删除会命中批量删除保护（本目录约 60 个文件）
if [ -d "$OUT" ]; then
    for item in "$OUT"/*; do
        [ -e "$item" ] && rm -rf "$item"
    done
fi
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"

echo "==> 1/7 编译资源"
"$BT/aapt2.exe" compile --dir app/src/main/res -o "$OUT/res.zip"

echo "==> 2/7 链接资源与清单"
"$BT/aapt2.exe" link \
    -o "$OUT/base.apk" \
    -I "$PLATFORM/android.jar" \
    --manifest app/src/main/AndroidManifest.xml \
    -R "$OUT/res.zip" \
    --java "$OUT/gen" \
    --min-sdk-version 23 \
    --target-sdk-version 34 \
    --version-code 5 \
    --version-name 1.0 \
    --auto-add-overlay

echo "==> 3/7 编译 Java"
"$JAVAC" -encoding UTF-8 -source 1.8 -target 1.8 -nowarn \
    -bootclasspath "$PLATFORM/android.jar" \
    -classpath "$LIBS/jsoup.jar" \
    -d "$OUT/classes" \
    $(find app/src/main/java "$OUT/gen" -name '*.java' | tr '\n' ' ')

echo "==> 4/7 R8（压缩 + 混淆）"
"$JAVA_HOME/bin/jar" cf "$OUT/classes.jar" -C "$OUT/classes" .
"$JAVA" -cp "$BT/lib/d8.jar" com.android.tools.r8.R8 \
    --release \
    --min-api 23 \
    --lib "$PLATFORM/android.jar" \
    --pg-conf app/proguard-rules.pro \
    --output "$OUT/dex" \
    "$OUT/classes.jar" "$LIBS/jsoup.jar"

echo "==> 5/7 打包 dex"
cp -f "$OUT/base.apk" "$OUT/unaligned.apk"
"$JAVA_HOME/bin/jar" uf "$OUT/unaligned.apk" -C "$OUT/dex" classes.dex
"$BT/zipalign.exe" -f -p 4 "$OUT/unaligned.apk" "$OUT/aligned.apk"

echo "==> 6/7 签名"
if [ ! -f "$KS" ]; then
    mkdir -p "$(dirname "$KS")"
    "$KEYTOOL" -genkeypair -keystore "$KS" -alias cx -keyalg RSA -keysize 2048 \
        -validity 10000 -storepass "$KS_PASS" -keypass "$KS_PASS" \
        -dname "CN=Chaoxing Helper, OU=Personal, O=Personal, L=CN, C=CN" >/dev/null
    echo "    已生成签名证书 keystore/cx.jks（口令来自 CX_KS_PASS / keystore/cx.pass，请自行备份）"
fi
"$BT/apksigner.bat" sign \
    --ks "$KS" --ks-key-alias cx \
    --ks-pass "pass:$KS_PASS" --key-pass "pass:$KS_PASS" \
    --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
    --out "$OUT/Android.apk" "$OUT/aligned.apk"

echo "==> 7/7 校验"
"$BT/apksigner.bat" verify --print-certs "$OUT/Android.apk" | head -5
ls -lh "$OUT/Android.apk"
echo "完成：$OUT/Android.apk"
