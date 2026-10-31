# 安卓版（Android）

超星学习通未完成作业 / 考试提取 —— 安卓原生实现。功能与桌面版一致：登录 → 汇总课程里的作业与考试 → 按「未完成 / 超时未交 / 已完成」三块列出，点一行用浏览器打开对应页面。**只读取，不提交、不删除、不作答。**

## 与桌面版的差别

| | 桌面版（Windows） | 安卓版 |
|---|---|---|
| 语言 / 运行时 | Python 3 + tkinter | Java + 系统框架（无 AndroidX、无 Kotlin 依赖） |
| 体积 | 安装包 29.7 MB | APK 约 125 KB |
| 硬件门 | 无（本机绑定加密） | **无**，装好即用，无任何解锁界面 |
| 登录态加密 | AES-256-CTR + HMAC-SHA256，密钥由本机指纹派生 | **Android Keystore 双层**：不可导出的 KEK 包裹随机 DEK，DEK 再加密登录态 |
| 混淆 | PyInstaller 打包 | R8 全量重命名 + 压平包名 + 字符串异或编码 |

## 安全设计

**1. 只有本 App 自己能解密**

- `AndroidKeyStore` 里生成一把 AES-256-GCM 的 **KEK**，`setUserAuthenticationRequired(false)`（打开应用不弹指纹）、`setRandomizedEncryptionRequired(true)`，私钥不可导出、只在 App 进程内可用；
- KEK 包裹一个随机 **DEK** 存到 `filesDir/d.bin`，登录态用 DEK 加密存 `filesDir/s.bin`（GCM 自带完整性校验）；
- 把 `s.bin` 拷到别的手机/电脑 = 一堆解不开的字节；换机、清除数据、卸载重装后 KEK 没了，自然回到「未登录」，**静默回登录页，不解释原因**；
- `android:allowBackup="false"` + `fullBackupContent="false"`，不进云备份、不进 adb backup；
- 只申请 `INTERNET` 一个权限，不碰存储、无障碍、设备信息。

**2. 混淆**

- `minifyEnabled`（R8 `--release`）+ `-repackageclasses ''` + `-allowaccessmodification`：除入口 `MainActivity` 外，194 个类全部改名并压平到默认包（`a`、`b2`、`c0`…）；
- 域名/接口路径不写成明面常量：`tools/gen_const.py` 把 27 条 URL 与 UA 异或后 Base64 存进 `C.java`，运行时才还原；dex 里 `grep chaoxing` 为空；
- 登录字段用 AES-128-CBC 封装（密钥由 4 段碎片在运行时拼出，源码里没有连续密钥），与网页端算法一致；
- 不保留 `BuildConfig.DEBUG` 分支，不打日志。

## 构建

不依赖 Gradle / Android Studio，直接用 SDK 的 build-tools 打：

```bash
# JDK 17 + Android SDK（platforms/android-34、build-tools/34.0.0）
export JAVA_HOME=/path/to/jdk17
export ANDROID_SDK=/path/to/android-sdk
bash build_apk.sh
# 产出 build/超星作业提取.apk（已 zipalign + v1/v2/v3 签名）
```

脚本做的事：`aapt2 compile` → `aapt2 link` → `javac` → `R8` → `jar uf` 塞 dex → `zipalign` → `apksigner`。

- 签名证书 `keystore/cx.jks` 已随仓库提供（别名 `cx`，口令 `cxhelper`），这样后续版本能覆盖安装、不被系统要求先卸载。**如果你想自己掌控签名**：删掉该文件再跑一次脚本，会重新生成一张；但换了证书就等于换了应用身份，旧版必须先卸载。打算发布给别人用时，请务必换成自己的证书并把它从仓库里移除。
- `libs/jsoup.jar` 是唯一第三方依赖（HTML 解析，445 KB）；HTTP 部分用系统的 `HttpURLConnection`，不引入 OkHttp/okio，APK 才能压到 125 KB。

## 目录

```
android/
├── app/
│   ├── src/main/
│   │   ├── AndroidManifest.xml
│   │   ├── java/com/cx/helper/
│   │   │   ├── MainActivity.java   界面、三块筛选、导出 CSV
│   │   │   ├── Api.java            登录 / 课程 / 作业 / 考试（多入口并集）
│   │   │   ├── Parse.java          时间、剩余时长、Cookie 归一化
│   │   │   ├── Tasks.java          数据模型与三块归属
│   │   │   ├── Store.java          Keystore 双层加密
│   │   │   ├── Guard.java          登录字段 AES 封装
│   │   │   ├── Str.java / C.java   字符串还原与编码常量表
│   │   │   └── Eula.java           首次运行声明
│   │   └── res/                    主题、颜色、图标
│   └── proguard-rules.pro
├── libs/jsoup.jar
├── tools/gen_const.py              生成 C.java（改接口地址后重跑）
├── keystore/cx.jks                 签名证书（请保留）
└── build_apk.sh
```

## 已知限制

- 图形验证码账号仍需在电脑上用「Cookie 导入」：安卓端同样支持粘贴 Cookie（JSON 数组 / JSON 对象 / `name=value;` 都认）。
- 未做指纹解锁与后台定时刷新（按「不做任何门」的要求，打开即用）。
- 未接 NDK：加密与签名校验都在 Java 层，R8 混淆已生效；如需把签名校验下沉到 native，需要再加 NDK 工具链。
- 本环境无安卓设备/模拟器，未做真机跑通验证；静态检查为：`aapt2 dump badging` 正常、`apksigner verify` 通过、dex 类名已混淆、无明文域名。
