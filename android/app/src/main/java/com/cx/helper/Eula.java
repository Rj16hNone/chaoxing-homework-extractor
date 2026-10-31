package com.cx.helper;

import android.content.Context;

/** 首次启动的许可与免责声明（只在第一次打开时弹一次）。 */
final class Eula {
    private Eula() {
    }

    static final int VERSION = 2;
    static final String TITLE = "软件许可与免责声明";

    private static final String PREF = "cx_prefs";
    private static final String KEY = "eula_v";

    static final String BODY =
            "超星学习通 · 未完成作业 / 考试提取（安卓版）\n"
            + "版本 1.1 · MIT License\n\n"
            + "在使用本软件之前，请完整阅读以下条款。点击「同意并继续」表示你已阅读、理解并接受全部内容；"
            + "如果不接受，请点击「退出」，软件将不会运行。\n\n"
            + "一、软件用途\n\n"
            + "本软件是一个时间管理辅助工具，用于汇总你自己账号下的课程作业与考试截止时间。"
            + "软件自身只发送读取请求：不会自动提交作业、不会代你参加考试、也不会修改学习通上的任何数据。\n\n"
            + "列表里的每一条都可以点开，在内置网页视图中打开学习通的官方页面。页面里的作答、上传附件、"
            + "提交等操作全部由你本人手动完成，与你用浏览器访问没有区别；提交前请自行核对内容与截止时间。\n\n"
            + "二、账号与服务条款\n\n"
            + "登录凭证由你本人提供，软件不保存密码。使用本软件可能与你所在学校的管理规定或学习通的"
            + "服务条款存在冲突，是否使用、如何使用由你自行判断并承担全部责任。\n\n"
            + "请勿将本软件用于自动签到、刷课、代做、批量爬取他人数据等用途。\n\n"
            + "三、数据与隐私\n\n"
            + "· 登录态只加密保存在本应用私有目录（AES-256-GCM，自带完整性校验），不上传、不同步；\n"
            + "· 加密密钥由系统密钥库保管，无法导出：文件被拷走也解不开；\n"
            + "· 换手机、清除数据或卸载重装后需重新登录一次，原登录态无法迁移；\n"
            + "· 软件没有服务器、没有账号体系、不含任何遥测或统计上报；\n"
            + "· 软件不写操作日志，不记录课程名、作业名、截止时间，也不保存原始网页内容。\n\n"
            + "四、免责\n\n"
            + "本软件按「现状」提供，不附带任何明示或暗示的担保，包括但不限于可用性、准确性、"
            + "适合作某一特定用途。\n\n"
            + "因使用或无法使用本软件所导致的任何直接或间接损失（包括但不限于错过作业或考试、"
            + "账号异常、数据丢失、设备故障），作者不承担任何责任。\n\n"
            + "五、许可\n\n"
            + "本软件以 MIT 许可证发布：你可以自由使用、修改、分发，保留版权与许可声明即可。\n\n"
            + "六、条款变更\n\n"
            + "条款可能随版本更新而变化。更新后的条款会在同一位置展示，并需要重新确认。\n\n"
            + "继续使用即视为你已阅读、理解并同意上述全部条款。";

    static boolean accepted(Context ctx) {
        return ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE).getInt(KEY, 0) >= VERSION;
    }

    static void accept(Context ctx) {
        ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE)
                .edit().putInt(KEY, VERSION).apply();
    }
}
