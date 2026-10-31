package com.cx.helper;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ContentValues;
import android.content.DialogInterface;
import android.content.Intent;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.text.InputType;
import android.text.method.ScrollingMovementMethod;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.Charset;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** 主界面：登录 → 提取 → 按三块列出 → 点一行打开页面。 */
public class MainActivity extends Activity {

    private static final int BG = 0xFFF3F5F9;
    private static final int CARD = 0xFFFFFFFF;
    private static final int INK = 0xFF1B2430;
    private static final int SUB = 0xFF7A8698;
    private static final int ACCENT = 0xFF2C6BED;
    private static final int C_OPEN = 0xFFF0912A;
    private static final int C_OVER = 0xFFD9363E;
    private static final int C_DONE = 0xFF2FA860;

    /** 打开内置网页视图的请求码。 */
    private static final int REQ_WEB = 0x42;

    private final ExecutorService exec = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    private final List<Tasks.T> all = new ArrayList<>();
    private final boolean[] on = {true, true, true};
    private Map<String, String> saved = new LinkedHashMap<>();

    private EditText edUser;
    private EditText edPwd;
    private Button btnMain;
    private TextView tvStatus;
    private TextView tvStats;
    private TextView tvExport;
    private LinearLayout filterRow;
    private LinearLayout listBox;
    private boolean busy;
    private boolean autoRan;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        buildUi();
        if (!Eula.accepted(this)) {
            askEula();
        } else {
            boot();
        }
    }

    // ------------------------------------------------------------------ 首次声明
    private void askEula() {
        final AlertDialog dlg = new AlertDialog.Builder(this)
                .setTitle(Eula.TITLE)
                .setMessage(Eula.BODY)
                .setCancelable(false)
                .setPositiveButton("同意并继续", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        Eula.accept(MainActivity.this);
                        boot();
                    }
                })
                .setNegativeButton("退出", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        finish();
                    }
                })
                .create();
        dlg.show();
    }

    private void boot() {
        saved = Store.load(this);
        if (saved.isEmpty()) {
            setStatus("还没有登录。填账号密码，或粘贴 Cookie 导入。", SUB);
        } else {
            setStatus("本机已保存登录状态。", SUB);
            autoExtract();
        }
        syncButton();
    }

    private void autoExtract() {
        if (autoRan) {
            return;
        }
        autoRan = true;
        runExtract(null);
    }

    // ------------------------------------------------------------------ 界面
    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(BG);
        scroll.setFillViewport(true);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(20), dp(16), dp(24));
        scroll.addView(root);

        TextView title = tv("Deadline", 22, INK, true);
        root.addView(title);

        TextView sub = tv("只读取 · 不会提交 / 删除 / 作答任何作业或考试", 12, SUB, false);
        LinearLayout.LayoutParams slp = wrap();
        slp.topMargin = dp(4);
        root.addView(sub, slp);

        // ---- 登录卡
        LinearLayout card = card();
        LinearLayout.LayoutParams clp = wrap();
        clp.topMargin = dp(16);
        root.addView(card, clp);

        card.addView(tv("账号密码登录", 14, INK, true));

        edUser = new EditText(this);
        edUser.setHint("手机号 / 学习通账号");
        edUser.setSingleLine(true);
        edUser.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        edUser.setInputType(InputType.TYPE_CLASS_TEXT);
        edUser.setBackground(round(0xFFF1F3F7, dp(10)));
        edUser.setPadding(dp(12), dp(10), dp(12), dp(10));
        LinearLayout.LayoutParams elp = wrap();
        elp.topMargin = dp(10);
        card.addView(edUser, elp);

        edPwd = new EditText(this);
        edPwd.setHint("密码");
        edPwd.setSingleLine(true);
        edPwd.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        edPwd.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        edPwd.setBackground(round(0xFFF1F3F7, dp(10)));
        edPwd.setPadding(dp(12), dp(10), dp(12), dp(10));
        LinearLayout.LayoutParams plp = wrap();
        plp.topMargin = dp(8);
        card.addView(edPwd, plp);

        TextView tip = tv("密码只用于本次登录，不保存、不上传", 11, SUB, false);
        LinearLayout.LayoutParams tlp = wrap();
        tlp.topMargin = dp(8);
        card.addView(tip, tlp);

        btnMain = new Button(this);
        btnMain.setText("登录并提取");
        btnMain.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        btnMain.setTextColor(0xFFFFFFFF);
        btnMain.setTypeface(Typeface.DEFAULT_BOLD);
        btnMain.setBackground(round(ACCENT, dp(12)));
        btnMain.setPadding(0, dp(11), 0, dp(11));
        LinearLayout.LayoutParams blp = wrap();
        blp.topMargin = dp(14);
        card.addView(btnMain, blp);
        btnMain.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                submit();
            }
        });

        TextView tCookie = tv("粘贴 Cookie 导入", 13, ACCENT, true);
        tCookie.setGravity(Gravity.CENTER);
        tCookie.setPadding(0, dp(12), 0, dp(4));
        card.addView(tCookie);
        tCookie.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                askCookie();
            }
        });

        TextView tOut = tv("退出登录并清除", 13, SUB, false);
        tOut.setGravity(Gravity.CENTER);
        tOut.setPadding(0, dp(6), 0, dp(2));
        card.addView(tOut);
        tOut.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                confirmLogout();
            }
        });

        tvStatus = tv("", 12, SUB, false);
        tvStatus.setPadding(dp(4), dp(14), dp(4), 0);
        root.addView(tvStatus);

        // ---- 统计 + 导出
        LinearLayout statRow = new LinearLayout(this);
        statRow.setOrientation(LinearLayout.HORIZONTAL);
        statRow.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams srp = wrap();
        srp.topMargin = dp(16);
        root.addView(statRow, srp);

        tvStats = tv("", 13, INK, true);
        statRow.addView(tvStats, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        tvExport = tv("导出 CSV", 12, ACCENT, true);
        tvExport.setPadding(dp(10), dp(4), dp(4), dp(4));
        tvExport.setVisibility(View.GONE);
        statRow.addView(tvExport);
        tvExport.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                exportCsv();
            }
        });

        // ---- 三块筛选
        filterRow = new LinearLayout(this);
        filterRow.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams flp = wrap();
        flp.topMargin = dp(10);
        root.addView(filterRow, flp);

        // ---- 任务列表
        listBox = new LinearLayout(this);
        listBox.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams llp = wrap();
        llp.topMargin = dp(12);
        root.addView(listBox, llp);

        TextView foot = tv("点一行可在浏览器打开对应的作业 / 考试页面（仅查看）", 11, 0xFFAEB8C6, false);
        foot.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams ftp = wrap();
        ftp.topMargin = dp(18);
        root.addView(foot, ftp);

        setContentView(scroll);
        render();
    }

    private void syncButton() {
        boolean hasSaved = !saved.isEmpty();
        btnMain.setText(hasSaved ? "用已保存状态提取" : "登录并提取");
        updateChips();
    }

    // ------------------------------------------------------------------ 动作
    private void submit() {
        if (busy) {
            return;
        }
        String u = edUser.getText().toString().trim();
        String p = edPwd.getText().toString().trim();
        if (!u.isEmpty() && !p.isEmpty()) {
            runExtract(new String[]{u, p});
            return;
        }
        if (!saved.isEmpty()) {
            runExtract(null);
            return;
        }
        setStatus("请填写账号和密码，或点「粘贴 Cookie 导入」。", C_OVER);
    }

    private void askCookie() {
        final EditText input = new EditText(this);
        input.setHint("粘贴浏览器导出的 Cookie（JSON 数组、JSON 对象或 name=value;…）");
        input.setMinLines(5);
        input.setGravity(Gravity.TOP | Gravity.START);
        input.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);

        new AlertDialog.Builder(this)
                .setTitle("导入 Cookie")
                .setView(input)
                .setNegativeButton("取消", null)
                .setPositiveButton("导入并提取", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        Map<String, String> ck = Parse.cookies(input.getText().toString());
                        if (ck.isEmpty()) {
                            toast("没有解析到任何 Cookie");
                            return;
                        }
                        runExtractWithCookies(ck);
                    }
                })
                .show();
    }

    private void confirmLogout() {
        new AlertDialog.Builder(this)
                .setTitle("退出登录")
                .setMessage("将删除本机保存的加密登录状态，下次需要重新登录。")
                .setNegativeButton("取消", null)
                .setPositiveButton("确定", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        Store.clear(MainActivity.this);
                        saved = new LinkedHashMap<>();
                        all.clear();
                        listBox.removeAllViews();
                        tvStats.setText("");
                        tvExport.setVisibility(View.GONE);
                        setStatus("已清除本机登录状态。", SUB);
                        syncButton();
                    }
                })
                .show();
    }

    // ------------------------------------------------------------------ 提取
    private void runExtractWithCookies(final Map<String, String> ck) {
        if (busy) {
            return;
        }
        setBusy(true);
        setStatus("正在读取课程列表…", SUB);
        exec.execute(new Runnable() {
            @Override
            public void run() {
                try {
                    Api api = new Api(ck);
                    if (Store.save(MainActivity.this, api.cookies())) {
                        saved = api.cookies();
                    }
                    finishExtract(api);
                } catch (Exception e) {
                    fail(e);
                }
            }
        });
    }

    private void runExtract(final String[] account) {
        if (busy) {
            return;
        }
        setBusy(true);
        setStatus(account == null ? "正在用已保存的登录状态读取…" : "正在登录…", SUB);

        exec.execute(new Runnable() {
            @Override
            public void run() {
                try {
                    Api api;
                    if (account == null) {
                        api = new Api(saved);
                    } else {
                        api = new Api(null);
                        api.login(account[0], account[1], "");
                        if (Store.save(MainActivity.this, api.cookies())) {
                            saved = api.cookies();
                        }
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                edPwd.setText("");
                            }
                        });
                    }
                    finishExtract(api);
                } catch (Exception e) {
                    fail(e);
                }
            }
        });
    }

    private void finishExtract(Api api) {
        Tasks.Res res = api.extractAll(true, new Api.P() {
            @Override
            public void step(final String msg) {
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        setStatus(msg, SUB);
                    }
                });
            }
        });
        final Tasks.Res r = res;
        ui.post(new Runnable() {
            @Override
            public void run() {
                all.clear();
                all.addAll(r.tasks);
                on[0] = true;
                on[1] = true;
                on[2] = true;
                render();
                setBusy(false);
                syncButton();

                StringBuilder sb = new StringBuilder();
                sb.append("扫描 ").append(r.courses).append(" 门课程 · 未完成 ")
                        .append(r.count(Tasks.OPEN)).append(" · 超时未交 ")
                        .append(r.count(Tasks.OVERDUE)).append(" · 已完成 ")
                        .append(r.count(Tasks.DONE));
                tvStats.setText(sb.toString());
                tvExport.setVisibility(all.isEmpty() ? View.GONE : View.VISIBLE);

                if (!r.errors.isEmpty()) {
                    setStatus("完成，但有 " + r.errors.size() + " 处读取失败：" + r.errors.get(0), C_OVER);
                } else if (all.isEmpty()) {
                    setStatus(r.hint.isEmpty() ? "没有未完成的作业或考试。" : r.hint, SUB);
                } else {
                    setStatus("完成。", SUB);
                }
            }
        });
    }

    private void fail(Exception e) {
        final String msg = e instanceof Api.Err ? e.getMessage()
                : ("出错：" + (e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage()));
        ui.post(new Runnable() {
            @Override
            public void run() {
                setBusy(false);
                syncButton();
                setStatus(msg, C_OVER);
            }
        });
    }

    private void setBusy(boolean b) {
        busy = b;
        btnMain.setEnabled(!b);
        btnMain.setAlpha(b ? 0.55f : 1f);
    }

    // ------------------------------------------------------------------ 列表
    private void render() {
        List<Tasks.T> shown = new ArrayList<>();
        for (Tasks.T t : all) {
            if (on[Tasks.rank(t.state)]) {
                shown.add(t);
            }
        }
        listBox.removeAllViews();
        if (shown.isEmpty()) {
            TextView empty = tv(all.isEmpty() ? "登录后这里按「未完成 / 超时未交 / 已完成」列出作业与考试"
                    : "当前筛选下没有条目", 12, SUB, false);
            empty.setGravity(Gravity.CENTER);
            empty.setPadding(0, dp(28), 0, dp(28));
            listBox.addView(empty);
        } else {
            for (Tasks.T t : shown) {
                listBox.addView(row(t));
            }
        }
        updateChips();
        tvExport.setVisibility(all.isEmpty() ? View.GONE : View.VISIBLE);
    }

    private View row(final Tasks.T t) {
        LinearLayout outer = new LinearLayout(this);
        outer.setOrientation(LinearLayout.HORIZONTAL);
        outer.setBackground(round(CARD, dp(14)));
        outer.setPadding(dp(12), dp(12), dp(12), dp(12));
        LinearLayout.LayoutParams olp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        olp.bottomMargin = dp(10);
        outer.setLayoutParams(olp);

        View bar = new View(this);
        LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(dp(4), dp(38));
        blp.rightMargin = dp(12);
        bar.setLayoutParams(blp);
        bar.setBackground(round(color(t.state), dp(2)));
        outer.addView(bar);

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setLayoutParams(new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        TextView name = tv(t.name, 15, INK, true);
        name.setMaxLines(2);
        col.addView(name);

        String meta = (t.course == null || t.course.isEmpty() ? t.type : (t.course + " · " + t.type));
        TextView m = tv(meta, 12, SUB, false);
        LinearLayout.LayoutParams mlp = wrap();
        mlp.topMargin = dp(4);
        col.addView(m, mlp);

        TextView line = tv("截止 " + t.deadline + (t.status.isEmpty() ? "" : "   " + t.status),
                12, t.done ? SUB : color(t.state), false);
        LinearLayout.LayoutParams dlp = wrap();
        dlp.topMargin = dp(4);
        col.addView(line, dlp);

        outer.addView(col);
        outer.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                openLink(t.link);
            }
        });
        outer.setOnLongClickListener(new View.OnLongClickListener() {
            @Override
            public boolean onLongClick(View v) {
                openExternal(t.link);
                return true;
            }
        });
        return outer;
    }

    private void updateChips() {
        filterRow.removeAllViews();
        int[] counts = new int[3];
        for (Tasks.T t : all) {
            counts[Tasks.rank(t.state)]++;
        }
        for (int i = 0; i < Tasks.ORDER.length; i++) {
            final int idx = i;
            TextView chip = new TextView(this);
            chip.setText(Tasks.label(Tasks.ORDER[i]) + " " + counts[i]);
            chip.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
            chip.setTypeface(Typeface.DEFAULT_BOLD);
            chip.setPadding(dp(12), dp(7), dp(12), dp(7));
            if (on[i]) {
                chip.setTextColor(0xFFFFFFFF);
                chip.setBackground(round(color(Tasks.ORDER[i]), dp(16)));
            } else {
                chip.setTextColor(SUB);
                chip.setBackground(round(0xFFE9EDF3, dp(16)));
            }
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.rightMargin = dp(8);
            filterRow.addView(chip, lp);

            chip.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    toggle(idx);
                }
            });
        }
    }

    private void toggle(int idx) {
        boolean any = false;
        for (boolean b : on) {
            if (b) {
                any = true;
            }
        }
        if (on[idx] && onlyOneOn()) {
            toast("至少要保留一块");
            return;
        }
        on[idx] = !on[idx];
        render();
    }

    private boolean onlyOneOn() {
        int n = 0;
        for (boolean b : on) {
            if (b) {
                n++;
            }
        }
        return n <= 1;
    }

    private static int color(String state) {
        if (Tasks.OVERDUE.equals(state)) {
            return C_OVER;
        }
        if (Tasks.DONE.equals(state)) {
            return C_DONE;
        }
        return C_OPEN;
    }

    private void openLink(String link) {
        if (link == null || link.isEmpty()) {
            toast("这一条没有可打开的链接");
            return;
        }
        try {
            Intent i = new Intent(this, WebAct.class);
            i.putExtra("url", link);
            startActivityForResult(i, REQ_WEB);
        } catch (Exception e) {
            toast("内置视图打不开，改用系统浏览器");
            openExternal(link);
        }
    }

    /** 长按一行：用系统浏览器打开（内置视图渲染异常时的兜底）。 */
    private void openExternal(String link) {
        if (link == null || link.isEmpty()) {
            toast("这一条没有可打开的链接");
            return;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(link)));
        } catch (Exception e) {
            toast("没有可用的浏览器");
        }
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        if (req == REQ_WEB) {
            boolean loaded = data != null && data.getBooleanExtra("loaded", false);
            if (loaded && !all.isEmpty()) {
                setStatus("回到列表。想刷新状态就点「提取」。", SUB);
            }
            return;
        }
        super.onActivityResult(req, res, data);
    }

    // ------------------------------------------------------------------ 导出
    private void exportCsv() {
        List<Tasks.T> shown = new ArrayList<>();
        for (Tasks.T t : all) {
            if (on[Tasks.rank(t.state)]) {
                shown.add(t);
            }
        }
        if (shown.isEmpty()) {
            toast("没有可导出的条目");
            return;
        }
        StringBuilder sb = new StringBuilder();
        sb.append("类型,课程,名称,状态,截止时间,链接\n");
        for (Tasks.T t : shown) {
            sb.append(q(t.type)).append(',')
                    .append(q(t.course)).append(',')
                    .append(q(t.name)).append(',')
                    .append(q(t.status)).append(',')
                    .append(q(t.deadline)).append(',')
                    .append(q(t.link)).append('\n');
        }
        String name = "Deadline_" + new SimpleDateFormat("yyyyMMdd_HHmm", Locale.CHINA).format(new Date()) + ".csv";
        String where;
        try {
            byte[] data = sb.toString().getBytes(Charset.forName("UTF-8"));
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues cv = new ContentValues();
                cv.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                cv.put(MediaStore.MediaColumns.MIME_TYPE, "text/csv");
                cv.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
                Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
                if (uri == null) {
                    throw new Exception("无法创建文件");
                }
                java.io.OutputStream os = getContentResolver().openOutputStream(uri);
                if (os == null) {
                    throw new Exception("无法写入文件");
                }
                os.write(data);
                os.flush();
                os.close();
                where = "已保存到「下载」：" + name;
            } else {
                File dir = getExternalFilesDir(null);
                if (dir == null) {
                    throw new Exception("没有可写的目录");
                }
                File f = new File(dir, name);
                FileOutputStream out = new FileOutputStream(f);
                out.write(data);
                out.flush();
                out.close();
                where = "已保存到：" + f.getAbsolutePath();
            }
            toast(where);
        } catch (Exception e) {
            toast("导出失败：" + e.getMessage());
        }
    }

    private static String q(String s) {
        if (s == null) {
            return "\"\"";
        }
        return "\"" + s.replace("\"", "\"\"") + "\"";
    }

    // ------------------------------------------------------------------ 小工具
    private int dp(float v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private TextView tv(String text, float size, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, size);
        t.setTextColor(color);
        if (bold) {
            t.setTypeface(Typeface.DEFAULT_BOLD);
        }
        return t;
    }

    private LinearLayout card() {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setBackground(round(CARD, dp(16)));
        l.setPadding(dp(16), dp(16), dp(16), dp(12));
        return l;
    }

    private GradientDrawable round(int color, int radius) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(radius);
        return d;
    }

    private LinearLayout.LayoutParams wrap() {
        return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private void setStatus(String text, int color) {
        tvStatus.setText(text);
        tvStatus.setTextColor(color);
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
    }
}
