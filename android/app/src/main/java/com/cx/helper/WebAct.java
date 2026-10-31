package com.cx.helper;

import android.app.Activity;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Message;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 内置网页视图：把本机加密保存的登录态同步进 WebView，直接在这里打开作业 / 考试页，
 * 让用户在 App 内作答、上传附件、提交，不必跳到外部浏览器。
 *
 * 说明：软件本身仍然只做「读取 + 展示」，页面里的任何操作都是用户本人在学习通官方页面上完成的。
 */
public class WebAct extends Activity {

    private static final int BG = 0xFFF3F5F9;
    private static final int CARD = 0xFFFFFFFF;
    private static final int INK = 0xFF1B2430;
    private static final int SUB = 0xFF7A8698;
    private static final int LINE = 0xFFE3E8EF;
    private static final int ACCENT = 0xFF2C6BED;

    private static final int REQ_FILE = 0x51;
    private static final int MATCH = ViewGroup.LayoutParams.MATCH_PARENT;
    private static final int WRAP = ViewGroup.LayoutParams.WRAP_CONTENT;

    private WebView web;
    private ProgressBar bar;
    private TextView tvTitle;
    private Map<String, String> ck = new LinkedHashMap<>();
    private ValueCallback<Uri[]> fileCb;
    private boolean loaded;

    @Override
    protected void onCreate(Bundle st) {
        super.onCreate(st);
        Intent it = getIntent();
        String url = it == null ? "" : it.getStringExtra("url");
        if (url == null || url.isEmpty()) {
            finish();
            return;
        }
        if (!url.startsWith("http")) {
            url = "https://" + url;
        }
        ck = Store.load(this);
        build();
        if (Build.VERSION.SDK_INT >= 19) {
            WebView.setWebContentsDebuggingEnabled(false);
        }
        seedCookies();
        web.loadUrl(url);
    }

    // ------------------------------------------------------------------ 界面
    private void build() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.setFitsSystemWindows(true);

        LinearLayout bar2 = new LinearLayout(this);
        bar2.setOrientation(LinearLayout.HORIZONTAL);
        bar2.setGravity(Gravity.CENTER_VERTICAL);
        bar2.setBackgroundColor(CARD);
        bar2.setPadding(dp(4), 0, dp(6), 0);
        root.addView(bar2, new LinearLayout.LayoutParams(MATCH, dp(46)));

        TextView close = tv("返回", 13, ACCENT, true);
        close.setGravity(Gravity.CENTER);
        close.setPadding(dp(10), dp(8), dp(10), dp(8));
        bar2.addView(close, new LinearLayout.LayoutParams(WRAP, MATCH));
        close.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                back();
            }
        });

        tvTitle = tv("加载中…", 14, INK, true);
        tvTitle.setSingleLine(true);
        tvTitle.setEllipsize(TextUtils.TruncateAt.END);
        LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(0, WRAP, 1f);
        tlp.leftMargin = dp(6);
        tlp.rightMargin = dp(6);
        bar2.addView(tvTitle, tlp);

        TextView reload = tv("刷新", 13, ACCENT, true);
        reload.setGravity(Gravity.CENTER);
        reload.setPadding(dp(10), dp(8), dp(10), dp(8));
        bar2.addView(reload, new LinearLayout.LayoutParams(WRAP, MATCH));
        reload.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (web != null) {
                    web.reload();
                }
            }
        });

        View line = new View(this);
        line.setBackgroundColor(LINE);
        root.addView(line, new LinearLayout.LayoutParams(MATCH, dp(1)));

        bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        bar.setMax(100);
        bar.setProgress(0);
        if (Build.VERSION.SDK_INT >= 21) {
            bar.setProgressTintList(ColorStateList.valueOf(ACCENT));
        }
        root.addView(bar, new LinearLayout.LayoutParams(MATCH, dp(2)));

        web = new WebView(this);
        root.addView(web, new LinearLayout.LayoutParams(MATCH, 0, 1f));

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setJavaScriptCanOpenWindowsAutomatically(true);
        s.setSupportMultipleWindows(true);
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setAllowFileAccess(false);
        s.setGeolocationEnabled(false);
        s.setSaveFormData(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        // 用桌面 UA：作业/考试页的电脑版模板才带完整作答与提交入口
        s.setUserAgentString(C.UA);
        if (Build.VERSION.SDK_INT >= 21) {
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        }

        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        if (Build.VERSION.SDK_INT >= 21) {
            cm.setAcceptThirdPartyCookies(web, true);
        }

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, String u) {
                return handle(u);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView v, android.webkit.WebResourceRequest r) {
                return handle(r.getUrl() == null ? null : r.getUrl().toString());
            }

            @Override
            public void onPageStarted(WebView v, String u, android.graphics.Bitmap fav) {
                syncCookies(u);
                bar.setVisibility(View.VISIBLE);
            }

            @Override
            public void onPageFinished(WebView v, String u) {
                bar.setVisibility(View.GONE);
                String t = v.getTitle();
                if (!TextUtils.isEmpty(t)) {
                    tvTitle.setText(t);
                }
                loaded = true;
                refreshFromWeb(u);
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView v, int p) {
                bar.setProgress(p);
                bar.setVisibility(p >= 100 ? View.GONE : View.VISIBLE);
            }

            @Override
            public void onReceivedTitle(WebView v, String t) {
                if (!TextUtils.isEmpty(t)) {
                    tvTitle.setText(t);
                }
            }

            @Override
            public boolean onCreateWindow(WebView v, boolean dialog, boolean gesture, Message msg) {
                // window.open / target=_blank：不弹新窗口，直接在当前视图里打开
                final WebView tmp = new WebView(WebAct.this);
                tmp.setWebViewClient(new WebViewClient() {
                    @Override
                    public boolean shouldOverrideUrlLoading(WebView x, String u) {
                        if (u != null && u.startsWith("http")) {
                            web.loadUrl(u);
                        }
                        return true;
                    }

                    @Override
                    public boolean shouldOverrideUrlLoading(WebView x, android.webkit.WebResourceRequest r) {
                        return shouldOverrideUrlLoading(x, r.getUrl() == null ? null : r.getUrl().toString());
                    }
                });
                WebView.WebViewTransport tr = (WebView.WebViewTransport) msg.obj;
                tr.setWebView(tmp);
                msg.sendToTarget();
                return true;
            }

            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb,
                                             FileChooserParams params) {
                if (fileCb != null) {
                    fileCb.onReceiveValue(null);
                }
                fileCb = cb;
                try {
                    startActivityForResult(params.createIntent(), REQ_FILE);
                    return true;
                } catch (Exception e) {
                    fileCb = null;
                    toast("没有可用的文件选择器");
                    return false;
                }
            }
        });

        setContentView(root);
    }

    // ------------------------------------------------------------------ Cookie
    private void seedCookies() {
        if (ck.isEmpty()) {
            return;
        }
        CookieManager cm = CookieManager.getInstance();
        String[] hosts = C.CK_HOSTS.split(",");
        for (String h : hosts) {
            if (h == null || h.isEmpty()) {
                continue;
            }
            applyTo(cm, "https://" + h + "/");
        }
        cm.flush();
    }

    private void syncCookies(String url) {
        if (url == null || ck.isEmpty()) {
            return;
        }
        String h = Uri.parse(url).getHost();
        if (h == null || h.isEmpty()) {
            return;
        }
        CookieManager cm = CookieManager.getInstance();
        applyTo(cm, "https://" + h + "/");
        cm.flush();
    }

    private void applyTo(CookieManager cm, String base) {
        for (Map.Entry<String, String> e : ck.entrySet()) {
            String k = e.getKey();
            String v = e.getValue();
            if (k == null || k.isEmpty() || v == null) {
                continue;
            }
            cm.setCookie(base, k + "=" + v + "; path=/");
        }
    }

    /**
     * 浏览过程中学习通会刷新会话 Cookie（例如续期、补 token）。页面加载完就把新值并回
     * 加密仓库，下次「提取」用的就是最新的一份，不会因为旧 token 掉登录。
     */
    private void refreshFromWeb(String url) {
        try {
            String all = CookieManager.getInstance().getCookie(url);
            if (all == null || all.isEmpty()) {
                return;
            }
            Map<String, String> now = new LinkedHashMap<>(ck);
            boolean dirty = false;
            for (String kv : all.split(";")) {
                String one = kv.trim();
                int i = one.indexOf('=');
                if (i <= 0) {
                    continue;
                }
                String k = one.substring(0, i).trim();
                String v = one.substring(i + 1);
                if (k.isEmpty()) {
                    continue;
                }
                String old = now.get(k);
                if (old == null || !old.equals(v)) {
                    now.put(k, v);
                    dirty = true;
                }
            }
            if (dirty && Store.save(this, now)) {
                ck = now;
            }
        } catch (Exception ignore) {
            // 更新失败不影响本次浏览
        }
    }

    // ------------------------------------------------------------------ 跳转
    private boolean handle(String u) {
        if (u == null) {
            return false;
        }
        if (u.startsWith("http://") || u.startsWith("https://")) {
            return false;          // 站内跳转仍留在本视图，Cookie 由 onPageStarted 同步
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(u)));
        } catch (Exception ignore) {
            // 外部协议没人接管就算了
        }
        return true;
    }

    private void back() {
        if (web != null && web.canGoBack()) {
            web.goBack();
            return;
        }
        done();
    }

    private void done() {
        Intent r = new Intent();
        r.putExtra("loaded", loaded);
        setResult(RESULT_OK, r);
        finish();
    }

    @Override
    public void onBackPressed() {
        back();
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        if (req == REQ_FILE) {
            if (fileCb != null) {
                Uri[] out = null;
                try {
                    out = WebChromeClient.FileChooserParams.parseResult(res, data);
                } catch (Exception ignore) {
                    out = null;
                }
                fileCb.onReceiveValue(out);
                fileCb = null;
            }
            return;
        }
        super.onActivityResult(req, res, data);
    }

    @Override
    protected void onDestroy() {
        // 离开页面即抹掉 WebView 里的 Cookie 与页面存储：磁盘上只留加密的那一份
        try {
            CookieManager cm = CookieManager.getInstance();
            cm.removeAllCookies(null);
            cm.flush();
        } catch (Exception ignore) {
            // 清不掉也不影响使用
        }
        try {
            WebStorage.getInstance().deleteAllData();
        } catch (Exception ignore) {
            // 同上
        }
        if (web != null) {
            try {
                web.loadUrl("about:blank");
                web.destroy();
            } catch (Exception ignore) {
                // 同上
            }
            web = null;
        }
        super.onDestroy();
    }

    // ------------------------------------------------------------------ 小工具
    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density + 0.5f);
    }

    private TextView tv(String text, int sp, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        if (bold) {
            t.setTypeface(Typeface.DEFAULT_BOLD);
        }
        return t;
    }

    private void toast(String m) {
        Toast.makeText(this, m, Toast.LENGTH_SHORT).show();
    }
}
