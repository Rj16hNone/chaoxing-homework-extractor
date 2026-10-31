# R8 / ProGuard 规则
# 目标：除入口 Activity 外，类名、包名、方法名全部重命名并压平到一个包；
# 字符串常量在源码层已完成异或编码，dex 里没有明面的域名与接口路径。

# 清单里写死了这两个类名，必须保留原名（其余一律改名）
-keep class com.cx.helper.MainActivity { *; }
-keep class com.cx.helper.WebAct { *; }

-allowaccessmodification
-repackageclasses ''
-overloadaggressively
-dontusemixedcaseclassnames

# 去掉调试信息与注解，减小体积也少暴露结构
-renamesourcefileattribute S

# jsoup 只做 DOM 解析，不需要反射兜底
-dontwarn org.jsoup.**
-dontwarn javax.annotation.**
-dontwarn org.w3c.dom.**
-dontwarn java.awt.**
