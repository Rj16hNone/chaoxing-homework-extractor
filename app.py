#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
超星学习通 · 未完成作业 / 考试 提取（桌面版）
================================================
本地桌面软件（tkinter），两种使用方式：

  ① 账号密码登录 —— 输入学习通账号（手机号/学号）+ 密码，登录成功后自动提取；
  ② Cookie 导入  —— 从浏览器导出 Cookie（或粘贴），直接提取。

安全说明：只发送 GET 请求读取数据，绝不提交 / 删除 / 作答任何作业或考试；
密码只用于本次登录，不保存、不上传；所有请求都在本机完成。
"""

import os
import sys
import csv
import threading
import queue
import datetime
import webbrowser

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import chaoxing_extractor as cx
import cx_login
import cx_vault
import cx_env
import cx_peer
import cx_keyring
import cx_guard
import cx_eula

APP_TITLE = "超星学习通 · 未完成作业 / 考试提取"
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# 配色
BG = "#f2f5f9"
CARD = "#ffffff"
BORDER = "#e3e8ef"
ACCENT = "#2f6fed"
INK = "#1f2933"
SUB = "#6b7785"


def _resource(*parts):
    """定位打包资源：开发时取源码目录，打包后取 PyInstaller 临时目录。"""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def _enable_hidpi():
    if sys.platform.startswith("win"):
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


class Rail(tk.Canvas):
    """自绘细滑轨滚动条。

    替代 ttk.Scrollbar：胶囊形滑块 + 淡色轨道，悬停时滑块加粗加深，
    点轨道整屏翻动、按住滑块跟手拖动；内容不足一屏时不画滑块（只留细轨占位，
    避免内容区宽度来回跳）。
    """

    def __init__(self, master, command, bg, thumb=None, thumb_hot=None):
        try:
            dpi = master.winfo_fpixels("1i")
        except Exception:
            dpi = 96.0
        self._s = max(1.0, round(dpi / 96.0, 2))
        self._w = int(11 * self._s)
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, takefocus=0,
                         width=self._w)
        self.command = command
        self.c_track = "#e6ecf4"
        self.c_thumb = thumb or "#c6d0de"
        self.c_hot = thumb_hot or "#94a3b8"
        self._first, self._last = 0.0, 1.0
        self._hover = False
        self._drag = False
        self._grab_dy = 0.0
        self._box = None            # 当前滑块 (x0, y0, x1, y1)
        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<MouseWheel>", self._on_wheel)
        self.after_idle(self.resync)

    # ---------------------------------------------------------------- 状态
    def resync(self):
        """主动向目标要一次可见范围（目标不主动推 yscrollcommand 时兜底）。"""
        try:
            v = self.command()
            if isinstance(v, (tuple, list)) and len(v) == 2:
                self.set(v[0], v[1])
        except Exception:
            pass

    def set(self, first, last):
        """供 yscrollcommand 调用。"""
        try:
            self._first, self._last = float(first), float(last)
        except (TypeError, ValueError):
            return
        self._redraw()

    def _span(self):
        return max(0.0, self._last - self._first)

    def _hidden(self):
        return self._span() >= 0.995

    # ---------------------------------------------------------------- 绘制
    def _round(self, x0, y0, x1, y1, r, **kw):
        r = max(1.0, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
        pts = [
            x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
            x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
            x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
        ]
        return self.create_polygon(pts, smooth=True, **kw)

    def _redraw(self):
        self.delete("all")
        h, w = self.winfo_height(), self.winfo_width()
        if h <= 2 or w <= 2:
            return
        s = self._s
        pad = int(3 * s)
        tw = max(2, int(3 * s))                     # 轨道宽度
        tx = (w - tw) // 2
        self._round(tx, pad, tx + tw, h - pad, tw / 2.0,
                    fill=self.c_track, outline="")
        if self._hidden():
            self._box = None
            return
        span = self._span()
        bh = max(int(26 * s), int(span * h))
        bh = min(bh, h - 2 * pad)
        y0 = int(self._first * h)
        y0 = max(pad, min(y0, h - bh - pad))
        thw = max(4, int((9 if self._hover else 6) * s))
        thw = min(thw, w - 2)
        x0 = (w - thw) // 2
        self._box = (x0, y0, x0 + thw, y0 + bh)
        self._round(x0, y0, x0 + thw, y0 + bh, thw / 2.0,
                    fill=(self.c_hot if self._hover else self.c_thumb), outline="")

    # ---------------------------------------------------------------- 交互
    def _on_configure(self, _=None):
        self._redraw()
        self.resync()

    def _on_enter(self, _=None):
        self._hover = True
        self._redraw()

    def _on_leave(self, _=None):
        if not self._drag:
            self._hover = False
            self._redraw()

    def _on_press(self, e):
        if self._hidden():
            return
        h = max(1, self.winfo_height())
        if self._box and self._box[1] <= e.y <= self._box[3]:
            self._drag = True
            self._grab_dy = (e.y - self._box[1]) / h
            return
        span = self._span()
        page = max(0.04, span * 0.9)
        bottom = self._box[3] if self._box else h
        target = self._first + (page if e.y > bottom else -page)
        self.command("moveto", max(0.0, min(1.0 - span, target)))

    def _on_drag(self, e):
        if not self._drag:
            return
        h = max(1, self.winfo_height())
        span = self._span()
        frac = e.y / h - self._grab_dy
        self.command("moveto", max(0.0, min(1.0 - span, frac)))

    def _on_release(self, _=None):
        self._drag = False

    def _on_wheel(self, e):
        """在滑轨上滚轮也能滚动目标（隐私窗口里没有全局滚轮绑定）。"""
        try:
            self.command("scroll", int(-e.delta / 120), "units")
        except Exception:
            pass
        return "break"


class ScrollArea(tk.Frame):
    """可滚动页面容器：内容高于窗口时自动出现滚动条，适配各种分辨率。"""

    def __init__(self, master, bg):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, takefocus=0)
        self.vsb = Rail(self, command=self.canvas.yview, bg=bg)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.body.bind("<Configure>", lambda e: self._refresh())
        self.canvas.bind("<Configure>", self._on_canvas)

    def _on_canvas(self, event):
        try:
            self.canvas.itemconfigure(self._win, width=event.width)
        except Exception:
            pass
        self._refresh()

    def _refresh(self):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except Exception:
            pass

    def _on_scroll(self, first, last):
        try:
            self.vsb.set(first, last)
        except Exception:
            pass

    def wheel(self, delta):
        try:
            self.canvas.yview_scroll(int(-delta / 120), "units")
        except Exception:
            pass


def _setup_styles(s):
    """全局 ttk 样式；主窗口、隐私窗口与首次运行对话框共用。"""
    st = ttk.Style()
    try:
        st.theme_use("clam")
    except Exception:
        pass
    st.configure(".", font=("Microsoft YaHei UI", 10), background=BG, foreground=INK)
    st.configure("TFrame", background=BG)
    st.configure("TLabel", background=BG, foreground=INK)
    st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                 borderwidth=0, focusthickness=0, padding=(s(18), s(9)),
                 font=("Microsoft YaHei UI", 10, "bold"))
    st.map("Accent.TButton",
           background=[("pressed", "#1e4fc4"), ("active", "#2560d4"),
                       ("disabled", "#e6ecf9")],
           foreground=[("disabled", "#9fb0cf")])
    st.configure("Ghost.TButton", background=CARD, foreground="#46505c",
                 borderwidth=1, relief="solid", padding=(s(13), s(7)),
                 font=("Microsoft YaHei UI", 9))
    st.map("Ghost.TButton",
           background=[("active", "#f2f6fd"), ("disabled", "#f7f8fa")],
           foreground=[("active", ACCENT), ("disabled", "#aab3bd")])
    try:
        st.layout("Mode.TRadiobutton", st.layout("Toolbutton"))
    except Exception:
        pass
    st.configure("Mode.TRadiobutton", background="#eef2f8", foreground="#46505c",
                 padding=(s(15), s(7)), font=("Microsoft YaHei UI", 9), borderwidth=0)
    st.map("Mode.TRadiobutton",
           background=[("selected", ACCENT), ("active", "#e2e9f7")],
           foreground=[("selected", "#ffffff"), ("active", "#2b3540")])
    st.configure("Treeview", background=CARD, fieldbackground=CARD, borderwidth=0,
                 rowheight=s(30), font=("Microsoft YaHei UI", 9))
    st.configure("Treeview.Heading", background="#f5f8fc", foreground="#5b6672",
                 relief="flat", font=("Microsoft YaHei UI", 9, "bold"),
                 padding=(s(8), s(7)))
    st.map("Treeview.Heading", background=[("active", "#eaf0fa")])
    st.map("Treeview", background=[("selected", "#dbe7ff")], foreground=[("selected", INK)])


class EulaDialog(tk.Toplevel):
    """首次运行时的许可与免责声明（同意后才进入主界面）。"""

    def __init__(self, master):
        super().__init__(master)
        self.result = False
        self.title(cx_eula.TITLE)
        try:
            dpi = self.winfo_fpixels("1i")
        except Exception:
            dpi = 96.0
        self.scale = max(1.0, round(dpi / 96.0, 2))
        self._s = lambda v: int(round(v * self.scale))
        s = self._s
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            w = min(780, max(560, int((sw - s(80)) / self.scale)))
            h = min(660, max(420, int((sh - s(120)) / self.scale)))
            self.geometry("%dx%d+%d+%d" % (
                s(w), s(h), max(0, (sw - s(w)) // 2), max(0, (sh - s(h)) // 2 - s(20))))
            self.minsize(s(520), s(400))
        except Exception:
            self.geometry("760x620")
        self.configure(bg=BG)
        try:
            # 主窗口此时是隐藏的：transient 到隐藏窗口在 Windows 上可能连自己也不显示，
            # 所以只在主窗口可见时才挂靠。
            if master is not None and master.winfo_viewable():
                self.transient(master)
        except Exception:
            pass
        self.protocol("WM_DELETE_WINDOW", self._decline)
        self.bind("<Escape>", lambda _e: self._decline())
        self._build()
        try:
            self.grab_set()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _img(self, name):
        try:
            hi = name.replace(".png", "@2x.png") if self.scale >= 1.4 else name
            p = _resource("assets", hi)
            if not os.path.exists(p):
                p = _resource("assets", name)
            self._logo = tk.PhotoImage(file=p)
            return self._logo
        except Exception:
            return None

    def _build(self):
        s = self._s
        wrap = tk.Frame(self, bg=BG, padx=s(20), pady=s(16))
        wrap.pack(fill="both", expand=True)

        head = tk.Frame(wrap, bg=BG)
        head.pack(fill="x")
        ic = self._img("shield.png")
        if ic:
            tk.Label(head, image=ic, bg=BG).pack(side="left", padx=(0, s(10)))
        ht = tk.Frame(head, bg=BG)
        ht.pack(side="left")
        tk.Label(ht, text=cx_eula.TITLE, bg=BG, fg=INK,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")
        tk.Label(ht, text="首次运行需要确认 · 版本 1.0 · MIT License", bg=BG, fg=SUB,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(s(2), 0))

        box = tk.Frame(wrap, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        self.txt = tk.Text(box, wrap="word", bd=0, highlightthickness=0,
                           bg=CARD, fg=INK, cursor="arrow", height=12,
                           font=("Microsoft YaHei UI", 9),
                           padx=s(14), pady=s(12),
                           spacing1=s(1), spacing2=s(2), spacing3=s(3))
        vsb = Rail(box, command=self.txt.yview, bg=CARD)
        self.txt.configure(yscrollcommand=vsb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y", padx=(s(4), s(2)), pady=s(6))
        self.txt.insert("1.0", cx_eula.BODY)
        self.txt.configure(state="disabled")
        self.txt.bind("<MouseWheel>",
                      lambda e: self.txt.yview_scroll(int(-e.delta / 120), "units"))

        foot = tk.Frame(wrap, bg=BG)
        foot.pack(side="bottom", fill="x", pady=(s(12), 0))
        box.pack(side="top", fill="both", expand=True, pady=(s(14), 0))
        self.var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            foot, text="我已阅读并同意上述条款", variable=self.var,
            command=self._sync, bg=BG, fg=INK, activebackground=BG, activeforeground=INK,
            selectcolor="#ffffff", bd=0, highlightthickness=0,
            font=("Microsoft YaHei UI", 9)).pack(side="left")

        self.btn_ok = ttk.Button(foot, text="同意并继续", style="Accent.TButton",
                                 command=self._agree, state="disabled")
        self.btn_ok.pack(side="right")
        ttk.Button(foot, text="退出", style="Ghost.TButton",
                   command=self._decline).pack(side="right", padx=s(8))

    def _sync(self):
        self.btn_ok.configure(state="normal" if self.var.get() else "disabled")

    def _agree(self):
        if not self.var.get():
            return
        cx_eula.accept()
        self.result = True
        self.destroy()

    def _decline(self):
        self.result = False
        self.destroy()


def _ask_eula(root):
    """弹出首次运行声明；返回 True 表示已同意。"""
    dlg = EulaDialog(root)
    root.wait_window(dlg)
    return bool(dlg.result)


class App:
    WATCH_MS = 10000        # 每 10 秒复核一次钥匙是否还在

    def __init__(self, root):
        self.root = root
        self.cookies = None      # 只读 Cookie 视图（来自加密仓库或本次登录）
        self.data = None         # 最近一次提取结果
        self.busy = False
        self.dlg = None          # 已打开的「隐私查看权限」窗口
        self._watch_running = False
        self._watch_job = None
        self._q = queue.Queue()      # 子线程 -> 主线程 的 UI 更新队列
        self.f_on = {k: True for k in cx.STATE_ORDER}   # 三块各自的显示开关（默认全选）
        self._row_tasks = {}         # Treeview 行 iid -> 任务对象（筛选后行号会变）
        self._chips = {}
        self._build_ui()
        self._pump()
        self.root.after(200, self._restore_session)
        self._watch_job = self.root.after(self.WATCH_MS, self._watch_tick)

    # ------------------------------------------------------------ 线程 <-> UI
    def _post(self, fn):
        """子线程把「更新界面」的动作投递到队列，由主线程执行（避免跨线程操作 Tk）。"""
        self._q.put(fn)

    def _pump(self):
        try:
            while True:
                fn = self._q.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        try:
            self.root.after(80, self._pump)
        except Exception:
            pass

    # ------------------------------------------------------------ 界面
    def _img(self, name):
        """加载 assets 下图标；高 DPI 时优先用 @2x 版本。"""
        try:
            if name in self._imgs:
                return self._imgs[name]
            hi = name.replace(".png", "@2x.png") if self.scale >= 1.4 else name
            p = _resource("assets", hi)
            if not os.path.exists(p):
                p = _resource("assets", name)
            im = tk.PhotoImage(file=p)
            self._imgs[name] = im
            return im
        except Exception:
            return None

    def _build_ui(self):
        root = self.root
        root.title(APP_TITLE)
        try:
            dpi = root.winfo_fpixels("1i")
        except Exception:
            dpi = 96.0
        self.scale = max(1.0, round(dpi / 96.0, 2))

        def s(v):
            return int(round(v * self.scale))

        self._imgs = {}
        _setup_styles(s)

        # 适应多种分辨率：不超过屏幕可用区域，小屏自动收缩并居中
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        max_w = max(640, int((sw - s(48)) / self.scale))
        max_h = max(440, int((sh - s(96)) / self.scale))
        win_w = min(1040, max_w)
        win_h = min(760, max_h)
        root.geometry("%dx%d+%d+%d" % (
            s(win_w), s(win_h),
            max(0, (sw - s(win_w)) // 2), max(0, (sh - s(win_h)) // 2 - s(12))))
        root.minsize(s(min(760, win_w)), s(min(460, win_h)))
        root.configure(bg=BG)
        try:
            root.iconbitmap(_resource("assets", "app.ico"))
        except Exception:
            pass

        # ---------------- 固定底栏（不随页面滚动）
        footer = tk.Frame(root, bg=BG, padx=s(20), pady=s(9))
        footer.pack(side="bottom", fill="x")
        tk.Label(footer, text="仅做读取，不会提交 / 删除 / 作答任何作业或考试",
                 bg=BG, fg=SUB, font=("Microsoft YaHei UI", 9), anchor="w").pack(side="left")
        self.gear = tk.Button(footer, text="隐私查看权限", image=self._img("gear.png"),
                              compound="left", bg=BG, fg="#46505c",
                              activebackground="#e8eefb", activeforeground=ACCENT,
                              relief="flat", bd=0, cursor="hand2",
                              padx=s(9), pady=s(3),
                              font=("Microsoft YaHei UI", 9), command=self._open_members)
        self.gear.pack(side="right")

        # ---------------- 可滚动页面
        self.page = ScrollArea(root, BG)
        self.page.pack(fill="both", expand=True)
        wrap = tk.Frame(self.page.body, bg=BG, padx=s(20), pady=s(14))
        wrap.pack(fill="both", expand=True)

        # 顶部标题
        head = tk.Frame(wrap, bg=BG)
        head.pack(fill="x")
        logo = self._img("logo.png")
        if logo:
            tk.Label(head, image=logo, bg=BG).pack(side="left", padx=(0, s(14)))
        ht = tk.Frame(head, bg=BG)
        ht.pack(side="left")
        tk.Label(ht, text="超星学习通 · 作业 / 考试提取", bg=BG, fg=INK,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")

        # 输入卡片
        card = tk.Frame(wrap, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(s(16), 0))
        inner = tk.Frame(card, bg=CARD, padx=s(20), pady=s(16))
        inner.pack(fill="x")

        modes = tk.Frame(inner, bg=CARD)
        modes.pack(fill="x")
        self.mode = tk.StringVar(value="account")
        for val, text in (("account", "账号密码"), ("cookie", "Cookie 导入"), ("saved", "已保存登录态")):
            ttk.Radiobutton(modes, text=text, value=val, variable=self.mode,
                            style="Mode.TRadiobutton",
                            command=self._switch_mode).pack(side="left", padx=(0, s(8)))

        self.input_holder = tk.Frame(inner, bg=CARD)
        self.input_holder.pack(fill="x", pady=(s(14), 0))

        # 账号密码
        self.account_frame = tk.Frame(self.input_holder, bg=CARD)
        self.var_user = tk.StringVar()
        self.var_pwd = tk.StringVar()
        self.var_fid = tk.StringVar()
        for col, (label, var, width, show) in enumerate((
            ("账号", self.var_user, 22, ""),
            ("密码", self.var_pwd, 18, "●"),
            ("学校 ID（可留空）", self.var_fid, 11, ""),
        )):
            pad_left = (0 if col == 0 else s(16), 0)
            tk.Label(self.account_frame, text=label, bg=CARD, fg=SUB,
                     font=("Microsoft YaHei UI", 9)).grid(row=0, column=col, sticky="w",
                                                          padx=pad_left)
            ent = tk.Entry(self.account_frame, textvariable=var, width=width, show=show,
                           relief="flat", bd=0, bg="#fbfcfe", fg=INK, insertbackground=INK,
                           highlightthickness=1, highlightbackground=BORDER,
                           highlightcolor=ACCENT, font=("Microsoft YaHei UI", 10))
            ent.grid(row=1, column=col, sticky="ew", pady=(s(5), 0), padx=pad_left, ipady=s(5))
            self.account_frame.columnconfigure(col, weight=(3, 2, 1)[col])
            if col == 0:
                self.ent_user = ent
            elif col == 1:
                self.ent_pwd = ent
        tk.Label(self.account_frame, text="密码只用于本次登录，不保存、不上传",
                 bg=CARD, fg=SUB, font=("Microsoft YaHei UI", 9)).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(s(9), 0))

        # Cookie 导入
        self.cookie_frame = tk.Frame(self.input_holder, bg=CARD)
        tk.Label(self.cookie_frame, text="粘贴浏览器导出的 Cookie（JSON 或 name=value;…）",
                 bg=CARD, fg=SUB, font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        self.txt_cookie = tk.Text(self.cookie_frame, height=5, relief="flat", bd=0,
                                  bg="#fbfcfe", fg=INK, insertbackground=INK,
                                  highlightthickness=1, highlightbackground=BORDER,
                                  highlightcolor=ACCENT, font=("Consolas", 9), wrap="word")
        self.txt_cookie.pack(fill="x", pady=(s(5), s(9)))
        crow = tk.Frame(self.cookie_frame, bg=CARD)
        crow.pack(fill="x")
        ttk.Button(crow, text="选择 Cookie 文件…", style="Ghost.TButton",
                   command=self._pick_cookie_file).pack(side="left")
        tk.Label(crow, text="支持 .json / .txt", bg=CARD, fg=SUB,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=s(10))

        # 已保存登录态
        self.saved_frame = tk.Frame(self.input_holder, bg=CARD)

        # 操作行
        act = tk.Frame(inner, bg=CARD)
        act.pack(fill="x", pady=(s(16), 0))
        self.btn_login = ttk.Button(act, text="登录并提取", style="Accent.TButton",
                                    image=self._img("play_white.png"), compound="left",
                                    command=self._on_primary)
        self.btn_login.pack(side="left")
        self.btn_refresh = ttk.Button(act, text="重新提取", style="Ghost.TButton",
                                      image=self._img("refresh.png"), compound="left",
                                      command=self._on_refresh, state="disabled")
        self.btn_refresh.pack(side="left", padx=s(9))
        self.btn_logout = ttk.Button(act, text="退出登录并清除", style="Ghost.TButton",
                                     image=self._img("trash.png"), compound="left",
                                     command=self._logout, state="disabled")
        self.btn_logout.pack(side="left")

        self.lbl_status = tk.Label(inner, text="", bg=CARD, fg=ACCENT, anchor="w",
                                   justify="left", wraplength=s(920),
                                   font=("Microsoft YaHei UI", 9))
        self.lbl_status.pack(fill="x", pady=(s(12), 0))

        # 空状态占位
        self.ph = tk.Frame(wrap, bg=BG, height=s(150))
        self.ph.pack(fill="x", pady=(s(10), 0))
        self.ph.pack_propagate(False)
        holder = tk.Frame(self.ph, bg=BG)
        holder.place(relx=0.5, rely=0.5, anchor="center")
        ph_icon = self._img("cookie_big.png")
        if ph_icon:
            tk.Label(holder, image=ph_icon, bg=BG).pack()
        tk.Label(holder, text="登录后这里按「未完成 / 超时未交 / 已完成」列出作业与考试", bg=BG,
                 fg="#9aa5b1", font=("Microsoft YaHei UI", 10)).pack(pady=(s(6), 0))
        tk.Label(holder, text="只读取，不会做任何提交或修改", bg=BG, fg="#b3bcc7",
                 font=("Microsoft YaHei UI", 9)).pack(pady=(s(2), 0))

        # 结果卡片
        self.res_card = tk.Frame(wrap, bg=CARD, highlightbackground=BORDER, highlightthickness=1)

        rhead = tk.Frame(self.res_card, bg=CARD, padx=s(18), pady=s(12))
        rhead.pack(fill="x")
        self.lbl_stats = tk.Label(rhead, text="", bg=CARD, fg=INK,
                                  font=("Microsoft YaHei UI", 10, "bold"))
        self.lbl_stats.pack(side="left")
        ttk.Button(rhead, text="导出日历", style="Ghost.TButton",
                   command=self._export_ics).pack(side="right")
        ttk.Button(rhead, text="导出 CSV", style="Ghost.TButton",
                   command=self._export_csv).pack(side="right", padx=s(8))

        # 三块筛选：点一下切换显示/隐藏，可只留一块、两块或全部
        fbar = tk.Frame(self.res_card, bg=CARD, padx=s(18))
        fbar.pack(fill="x", pady=(0, s(9)))
        for key in cx.STATE_ORDER:
            chip = tk.Label(fbar, text=cx.STATE_LABEL[key], bg="#eef2f8", fg="#5b6672",
                            font=("Microsoft YaHei UI", 9), padx=s(13), pady=s(6),
                            cursor="hand2", highlightthickness=1,
                            highlightbackground="#dfe6f0")
            chip.pack(side="left", padx=(0, s(8)))
            chip.bind("<Button-1>", lambda e, k=key: self._toggle_filter(k))
            chip.bind("<Enter>", lambda e, c=chip, k=key: self._chip_hover(c, k, True))
            chip.bind("<Leave>", lambda e, c=chip, k=key: self._chip_hover(c, k, False))
            self._chips[key] = chip
        self.lbl_filter = tk.Label(fbar, text="", bg=CARD, fg=SUB,
                                   font=("Microsoft YaHei UI", 9))
        self.lbl_filter.pack(side="right")

        tip = tk.Label(self.res_card, text="双击一行可在浏览器打开对应的作业 / 考试页面（仅查看）",
                       bg=CARD, fg=SUB, font=("Microsoft YaHei UI", 9),
                       padx=s(18), pady=s(9), anchor="w")
        tip.pack(side="bottom", fill="x")

        tbl = tk.Frame(self.res_card, bg=CARD, padx=s(14))
        tbl.pack(fill="both", expand=True, pady=(0, s(6)))
        cols = ("type", "course", "name", "status", "deadline")
        self.tree = ttk.Treeview(tbl, columns=cols, show="headings", height=9)
        for key, text, width, anchor in (
            ("type", "类型", 70, "center"),
            ("course", "课程", 190, "w"),
            ("name", "名称", 330, "w"),
            ("status", "状态", 100, "center"),
            ("deadline", "截止时间", 170, "w"),
        ):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=s(width), anchor=anchor)
        vsb = Rail(tbl, command=self.tree.yview, bg=CARD)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y", padx=(s(4), 0))
        self.tree.tag_configure("odd", background="#fafcff")
        self.tree.tag_configure("even", background="#ffffff")
        self.tree.tag_configure("overdue", background="#fff5f1", foreground="#b4432c")
        self.tree.tag_configure("done", background="#f7f8fa", foreground="#93a0ad")
        self.tree.bind("<Double-1>", self._open_selected)

        self._switch_mode()
        self.root.bind("<Return>", lambda e: self._on_primary())
        self.root.bind("<Configure>", self._on_resize)
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        self._resize_job = None

    # ------------------------------------------------------------ 自适应
    def _on_resize(self, event=None):
        """窗口尺寸变化时，重算换行宽度与表格列宽（防抖 120ms）。"""
        if event is not None and getattr(event, "widget", None) is not self.root:
            return
        try:
            if self._resize_job:
                self.root.after_cancel(self._resize_job)
        except Exception:
            pass
        try:
            self._resize_job = self.root.after(120, self._apply_resize)
        except Exception:
            pass

    def _apply_resize(self):
        self._resize_job = None
        try:
            w = self.root.winfo_width()
            pad = int(120 * self.scale)
            self.lbl_status.configure(wraplength=max(240, w - pad))
            self._fit_tree_columns()
            # 调整行数会改变页面高度，先记住滚动位置再恢复，避免页面跳动
            try:
                y = self.page.canvas.yview()[0]
            except Exception:
                y = 0.0
            self._fit_tree_rows()
            try:
                self.page.canvas.yview_moveto(y)
            except Exception:
                pass
        except Exception:
            pass

    def _fit_tree_rows(self):
        """决定表格行数：尽量填满可视区，但不低于 6 行、也不超过实际条数。"""
        try:
            if not self.res_card.winfo_ismapped():
                return
            row_h = max(22, int(30 * self.scale))
            body_h = self.page.body.winfo_reqheight()
            tree_h = self.tree.winfo_reqheight()
            other = body_h - tree_h            # 除表格外的高度（标题、输入区、卡片头…）
            avail = self.page.canvas.winfo_height() - other - int(20 * self.scale)
            # 页面本来就能滚，所以表格至少留 6 行，别把列表压成一条缝
            rows = max(6, min(16, int(avail // row_h)))
            # 筛选后只剩几条时把表格收下来，不留一排空白；太扁也不好看，最少 3 行
            n = len(self.tree.get_children())
            floor = 3
            if n:
                rows = min(rows, max(3, n))
                floor = max(3, min(6, n))
            # 一屏放得下就再收一点，但不低于 floor
            for _ in range(6):
                self.tree.configure(height=rows)
                self.page.body.update_idletasks()
                if self.page.body.winfo_reqheight() <= self.page.canvas.winfo_height():
                    break
                if rows <= floor:
                    break
                rows -= 1
        except Exception:
            pass

    def _fit_tree_columns(self):
        try:
            total = self.tree.winfo_width()
            if total <= 20:
                return
            ratios = (("type", 0.07), ("course", 0.18), ("name", 0.35),
                      ("status", 0.14), ("deadline", 0.26))
            for key, r in ratios:
                self.tree.column(key, width=max(int(56 * self.scale), int(total * r)))
        except Exception:
            pass

    def _on_wheel(self, event):
        try:
            w = self.root.winfo_containing(event.x_root, event.y_root)
            if w is not None:
                if isinstance(w, Rail):        # 鼠标停在自绘滑轨上：滚它的目标
                    w.command("scroll", int(-event.delta / 120), "units")
                    return
                cur = str(w)
                if cur.startswith(str(self.tree)) or cur.startswith(str(self.txt_cookie)):
                    return
            self.page.wheel(event.delta)
        except Exception:
            pass

    # ------------------------------------------------------------ 提示气泡
    def _tip(self, text):
        try:
            t = tk.Toplevel(self.root)
            t.wm_overrideredirect(True)
            x = self.root.winfo_rootx() + self.root.winfo_width() - 150
            y = self.root.winfo_rooty() + self.root.winfo_height() - 58
            t.wm_geometry("+%d+%d" % (x, y))
            tk.Label(t, text=text, bg="#1f2933", fg="#ffffff", padx=8, pady=4,
                     font=("Microsoft YaHei UI", 9)).pack()
            self._tipwin = t
        except Exception:
            pass

    def _untip(self):
        try:
            self._tipwin.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------ 交互
    def _switch_mode(self):
        m = self.mode.get()
        for f in (self.account_frame, self.cookie_frame, self.saved_frame):
            f.pack_forget()
        if m == "account":
            self.account_frame.pack(fill="x")
            self.btn_login.configure(text="登录并提取")
            self.root.after(50, lambda: self.ent_user.focus_set())
        elif m == "cookie":
            self.cookie_frame.pack(fill="x")
            self.btn_login.configure(text="提取")
        else:
            self.saved_frame.pack(fill="x")
            self.btn_login.configure(text="用已保存状态提取")

    def _pick_cookie_file(self):
        path = filedialog.askopenfilename(
            title="选择 Cookie 文件",
            filetypes=[("Cookie 文件", "*.json *.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                content = f.read()
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"读取文件失败：{e}")
            return
        self.txt_cookie.delete("1.0", "end")
        self.txt_cookie.insert("1.0", content)
        self.mode.set("cookie")
        self._switch_mode()
        self._set_status(f"已载入 Cookie 文件：{os.path.basename(path)}", "ok")

    def _set_status(self, text, kind="info"):
        colors = {"info": "#2f6fed", "ok": "#1f9d57", "err": "#d64545"}
        self.lbl_status.configure(text=text, fg=colors.get(kind, "#1f2933"))

    def _on_primary(self):
        if self.busy:
            return
        m = self.mode.get()
        if m == "account":
            user = self.var_user.get().strip()
            pwd = self.var_pwd.get().strip()
            if not user or not pwd:
                self._set_status("请先填写账号和密码。", "err")
                return
        elif m == "cookie":
            text = self.txt_cookie.get("1.0", "end").strip()
            if not text:
                self._set_status("请先粘贴 Cookie，或点「选择 Cookie 文件」。", "err")
                return
        else:
            if not cx_vault.session_file_exists():
                self._set_status("本机还没有保存的登录状态，请先用「账号密码登录」登录一次。", "err")
                return
            if not cx_keyring.cookie_readable():
                self._set_status("本机保存的登录状态暂时不可用，请重新登录一次。", "err")
                return
        self._run(mode=m)

    def _on_refresh(self):
        if self.busy or not self.cookies:
            return
        self._run(mode="cached")

    # ------------------------------------------------------------ 启动与解锁
    def _restore_session(self):
        """启动时静默校验解锁状态（设备 / 恢复密钥）。"""
        threading.Thread(target=self._boot_worker, daemon=True).start()

    def _boot_worker(self):
        try:
            st = cx_keyring.state()
        except Exception:  # noqa: BLE001
            st = {"state": "locked"}
        if st["state"] == "open":
            self._post(lambda: self.on_keyring_unlocked("full"))
            return
        self._post(self._set_locked)

    def on_keyring_unlocked(self, level="full"):
        """解锁后：载入已保存的登录状态，并把界面切到「已保存状态」模式。"""
        self.btn_login.configure(state="normal")
        if level == "full":
            self.btn_logout.configure(state="normal")
        try:
            sess = cx_vault.load_session()
        except Exception:
            sess = None
        if sess is not None:
            self.cookies = sess
            self.btn_refresh.configure(state="normal")
            if self.mode.get() != "saved":
                self.mode.set("saved")
                self._switch_mode()

    def _set_locked(self, msg=None):
        """主界面不展示锁定状态；按钮保持可用，点击时再说明原因。"""
        self.btn_refresh.configure(state="disabled")
        if msg:
            self._set_status(msg, "err")

    def _open_members(self):
        self._close_members_dialog()
        self.dlg = MembersDialog(self.root, app=self)

    def _close_members_dialog(self):
        dlg = getattr(self, "dlg", None)
        self.dlg = None
        if dlg is None:
            return
        try:
            if dlg.winfo_exists():
                dlg.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------ 权限周期复核
    def _watch_tick(self):
        """每 10 秒复核一次：钥匙不在了就收回权限。"""
        try:
            if not self.busy and not self._watch_running:
                self._watch_running = True
                threading.Thread(target=self._watch_worker, daemon=True).start()
        except Exception:
            self._watch_running = False
        try:
            self._watch_job = self.root.after(self.WATCH_MS, self._watch_tick)
        except Exception:
            pass

    def _watch_worker(self):
        res = None
        try:
            res = cx_keyring.revalidate()
        except Exception:  # noqa: BLE001
            res = None
        finally:
            self._watch_running = False
        if res and res.get("changed"):
            self._post(lambda: self._on_key_changed(res))

    def _on_key_changed(self, res):
        """钥匙状态变化：降级 / 失效时收回对应的访问能力。"""
        level = res.get("level") or "none"
        reason = res.get("reason") or ""
        if level == "full":
            # 升回完整权限：刷新权限窗口，并把已保存的登录态静默载回内存（不打断当前输入）
            if self.dlg is not None:
                try:
                    self.dlg.refresh()
                except Exception:
                    pass
            if self.cookies is None:
                try:
                    sess = cx_vault.load_session()
                except Exception:
                    sess = None
                if sess is not None:
                    self.cookies = sess
                    self.btn_refresh.configure(state="normal")
                    self.btn_logout.configure(state="normal")
                    self._set_status(
                        "已重新识别到管理设备，权限已恢复：可直接「重新提取」，"
                        "或切到「已保存登录态」。", "ok")
            return

        # 权限下降：先丢掉内存里的 Cookie 视图，再禁用复用入口
        self.cookies = None
        self.btn_refresh.configure(state="disabled")
        self.btn_logout.configure(state="disabled")

        # level == none：彻底关闭查看权限
        self._close_members_dialog()
        if self.mode.get() == "saved":
            self.mode.set("account")
            self._switch_mode()
        self._set_status("本机保存的登录状态暂时不可用，请重新登录一次。", "err")

    def _logout(self):
        """用户主动清除本地登录状态（唯一会删除 Cookie 的操作）。"""
        if self.busy:
            return
        if not messagebox.askyesno(
            APP_TITLE, "确定清除本地保存的登录状态吗？\n清除后需要重新登录才能提取。"
        ):
            return
        cx_vault.clear_session()
        self.cookies = None
        self.data = None
        for row in self.tree.get_children():
            self.tree.delete(row)
        self._row_tasks = {}
        self.res_card.pack_forget()
        try:
            self.ph.pack(expand=True, fill="both")
        except Exception:
            pass
        self.btn_refresh.configure(state="disabled")
        self.btn_logout.configure(state="disabled")
        self._set_status("已清除本地登录状态，相关加密文件已删除。", "info")

    def _run(self, mode):
        if mode == "saved" and not cx_keyring.cookie_readable():
            self._set_status("本机保存的登录状态暂时不可用，请重新登录一次。", "err")
            return
        self.busy = True
        self.btn_login.configure(state="disabled")
        self.btn_refresh.configure(state="disabled")
        self.res_card.pack_forget()
        self._set_status("正在登录…" if mode == "account" else "正在读取课程与作业/考试，请稍候…", "info")
        threading.Thread(target=self._worker, args=(mode,), daemon=True).start()

    # ------------------------------------------------------------ 后台任务
    def _worker(self, mode):
        try:
            if mode == "saved" and not cx_keyring.cookie_readable():
                raise cx.ChaoxingError("本机保存的登录状态暂时不可用，请重新登录一次。")
            if mode == "account":
                cookies, msg = cx_login.chaoxing_login(
                    self.var_user.get().strip(),
                    self.var_pwd.get().strip(),
                    fid=self.var_fid.get().strip() or "-1",
                )
                saved = cx_vault.save_session(cookies)
                self.cookies = cx_vault.ReadOnlyCookies(cookies)
                tip = "，已加密保存到本机" if saved else "（本地保存失败，仅本次有效）"
                self._post(lambda: self._set_status(
                    f"登录成功（{msg}）{tip}，正在提取课程与作业/考试…", "ok"))
            elif mode == "cookie":
                raw = self.txt_cookie.get("1.0", "end").strip()
                cookies, _domains = cx.normalize_cookies(raw)
                if not cookies:
                    raise cx.ChaoxingError("没有从输入内容里解析出任何 Cookie，请检查格式。")
                saved = cx_vault.save_session(cookies)
                self.cookies = cx_vault.ReadOnlyCookies(cookies)
                if saved:
                    self._post(lambda: self._set_status("Cookie 已加密保存到本机。", "ok"))
            elif mode == "saved":
                cookies = cx_vault.load_session()
                if not cookies:
                    if not cx_keyring.cookie_readable():
                        raise cx.ChaoxingError("本机保存的登录状态暂时不可用，请重新登录一次。")
                    raise cx.ChaoxingError(
                        "本机保存的登录状态解不开，请用「账号密码登录」重新登录一次")
                self.cookies = cookies
            else:
                cookies = self.cookies
                if not cookies:
                    raise cx.ChaoxingError("登录状态已失效，请重新登录。")

            client = cx.ChaoxingClient(cookies, timeout=25)
            warnings = client.diagnose()
            ok, msg = client.check_login()
            if not ok:
                raise cx.ChaoxingError(msg)
            # 三块（未完成 / 超时未交 / 已完成）都要，交给界面分块筛选
            data = client.extract_all(only_incomplete=False)
            data["warnings"] = warnings
            self.data = data
            self._post(lambda: self._show_result(data))
        except cx_login.LoginError as e:
            err = str(e)
            self._post(lambda m=err: self._set_status("登录失败：" + m, "err"))
        except cx.ChaoxingError as e:
            err = str(e)
            self._post(lambda m=err: self._set_status(m, "err"))
        except Exception as e:  # noqa: BLE001
            err = str(e)
            self._post(lambda m=err: self._set_status("出现异常：" + m, "err"))
        finally:
            self._post(self._done)

    def _done(self):
        self.busy = False
        self.btn_login.configure(state="normal")
        self.btn_refresh.configure(state="normal" if self.cookies else "disabled")
        self.btn_logout.configure(state="normal" if self.cookies else "disabled")

    # ------------------------------------------------------------ 展示结果
    # ------------------------------------------------------------ 三块分类
    def _state_of(self, t):
        st = t.get("state")
        return st if st in cx.STATE_ORDER else cx.task_state(t)

    def _counts(self):
        counts = {k: 0 for k in cx.STATE_ORDER}
        for t in (self.data or {}).get("tasks") or []:
            st = self._state_of(t)
            counts[st] = counts.get(st, 0) + 1
        return counts

    def _visible_tasks(self):
        """按当前开关取可见任务 -> [(state, task)]，块顺序固定（未完成在前）。"""
        groups = {k: [] for k in cx.STATE_ORDER}
        for t in (self.data or {}).get("tasks") or []:
            st = self._state_of(t)
            if self.f_on.get(st, True):
                groups[st].append(t)
        return [(k, t) for k in cx.STATE_ORDER for t in groups[k]]

    def _fill_tree(self):
        """整表重画：筛选一变就立刻重新填满，不留空行。"""
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_tasks = {}
        for i, (st, t) in enumerate(self._visible_tasks()):
            status = t.get("status") or ""
            exam_st = t.get("exam_status") or ""
            # exam_status 与 status 相同时（如都写「已交卷」）不要重复拼接
            if exam_st and exam_st != "进行中" and exam_st not in status:
                status = (status + " · " + exam_st).strip(" ·")
            if st == cx.STATE_OVERDUE:
                # 这一块的语义就是「到期未交」，状态列统一写清楚即可；
                # 原来把原状态和 exam_status 拼在后面（如「未交 · 已结束·超时」）又长又乱。
                show = "超时未交"
                tag = "overdue"
            elif st == cx.STATE_DONE:
                show = status or "已完成"
                tag = "done"
            else:
                show = status or "未完成"
                tag = "odd" if i % 2 else "even"
            iid = self.tree.insert(
                "", "end",
                values=(t.get("type"), t.get("course") or "—", t.get("name"),
                        show, t.get("deadline") or "未注明"),
                tags=(tag,),
            )
            self._row_tasks[iid] = t
        self._update_chips()

    def _update_chips(self):
        counts = self._counts()
        for key, chip in self._chips.items():
            on = self.f_on.get(key, True)
            chip.configure(
                text="%s %d" % (cx.STATE_LABEL[key], counts.get(key, 0)),
                bg=(ACCENT if on else "#eef2f8"),
                fg=("#ffffff" if on else "#5b6672"),
                highlightbackground=(ACCENT if on else "#dfe6f0"),
                highlightcolor=(ACCENT if on else "#dfe6f0"),
            )
        total = sum(counts.values())
        self.lbl_filter.configure(
            text="显示 %d / 共 %d 条" % (len(self._row_tasks), total))

    def _chip_hover(self, chip, key, on):
        if self.f_on.get(key, True):     # 已选中的块保持蓝底
            return
        chip.configure(bg="#e2e9f7" if on else "#eef2f8")

    def _toggle_filter(self, key):
        if not (self.data or {}).get("tasks"):
            return
        on_now = [k for k in cx.STATE_ORDER if self.f_on.get(k, True)]
        if self.f_on.get(key, True) and len(on_now) <= 1:
            # 三块至少留一块，否则表格会空掉 —— 直接切回全部显示
            self.f_on = {k: True for k in cx.STATE_ORDER}
            self._fill_tree()
            self._fit_tree_rows()
            self._set_status("三块至少要留一块，已自动切回「全部显示」。", "info")
            return
        self.f_on[key] = not self.f_on.get(key, True)
        self._fill_tree()
        self._fit_tree_rows()

    def _show_result(self, data):
        try:
            self.ph.pack_forget()
        except Exception:
            pass
        self.res_card.pack(fill="x", pady=(int(14 * self.scale), 0))
        tasks = data.get("tasks") or []
        counts = self._counts()
        self.lbl_stats.configure(
            text="扫描 %d 门课程 · 未完成 %d · 超时未交 %d · 已完成 %d"
                 % (data.get("courses_count", 0), counts[cx.STATE_OPEN],
                    counts[cx.STATE_OVERDUE], counts[cx.STATE_DONE]))
        self._fill_tree()
        self.root.after(60, self._apply_resize)

        msgs = []
        if tasks:
            msgs.append("提取完成：共 %d 条（未完成 %d · 超时未交 %d · 已完成 %d）。"
                        % (len(tasks), counts[cx.STATE_OPEN],
                           counts[cx.STATE_OVERDUE], counts[cx.STATE_DONE]))
        else:
            msgs.append("提取完成：没有找到作业或考试。")
        if data.get("hint"):
            msgs.append(data["hint"])
        if data.get("warnings"):
            msgs.append("提示：" + "；".join(data["warnings"]))
        if data.get("errors"):
            msgs.append("部分课程： " + "；".join(data["errors"][:5]))
        self._set_status(" ".join(msgs), "ok" if tasks else "info")

    def _open_selected(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        t = self._row_tasks.get(sel[0])
        if t and t.get("link"):
            webbrowser.open(t["link"])
        else:
            self._set_status("这一条没有可打开的链接。", "info")

    # ------------------------------------------------------------ 导出
    def _export_csv(self):
        rows = [t for _st, t in self._visible_tasks()]
        if not rows:
            messagebox.showinfo(APP_TITLE, "当前筛选下没有可导出的数据。")
            return
        path = filedialog.asksaveasfilename(
            title="导出 CSV", defaultextension=".csv",
            initialfile="作业考试列表.csv",
            filetypes=[("CSV 文件", "*.csv")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["分类", "类型", "课程", "名称", "状态", "截止时间", "链接"])
                for t in rows:
                    w.writerow([cx.STATE_LABEL.get(self._state_of(t), ""),
                                t.get("type"), t.get("course"), t.get("name"),
                                t.get("status"), t.get("deadline"), t.get("link")])
            self._set_status(f"已导出 CSV（当前筛选 {len(rows)} 条）：{path}", "ok")
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"导出失败：{e}")

    def _export_ics(self):
        tasks = [t for _st, t in self._visible_tasks()]
        if not tasks:
            messagebox.showinfo(APP_TITLE, "当前筛选下没有可导出的数据。")
            return
        path = filedialog.asksaveasfilename(
            title="导出日历", defaultextension=".ics",
            initialfile="作业考试.ics",
            filetypes=[("日历文件", "*.ics")],
        )
        if not path:
            return
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        def ics_dt(iso):
            if not iso:
                return None
            try:
                d = datetime.datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
                return d.strftime("%Y%m%dT%H%M%S")
            except ValueError:
                return None

        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CX Extractor//CN",
                 "CALSCALE:GREGORIAN"]
        added = 0
        for i, t in enumerate(tasks):
            end = ics_dt(t.get("deadline_iso"))
            if not end:
                continue
            start = ics_dt(t.get("start_iso")) or end
            added += 1
            lines += [
                "BEGIN:VEVENT",
                f"UID:cx{i}@cxextractor",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{start}",
                f"DTEND:{end}",
                "SUMMARY:" + (f"{t.get('type')}：{t.get('name')}（{t.get('course') or ''}）")
                .replace(",", " ").replace("\n", " "),
            ]
            if t.get("approx"):
                lines.append("DESCRIPTION:截止时间由「剩余时长」估算，请以学习通页面为准")
            if t.get("link"):
                lines.append("URL:" + t["link"])
            lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")
        if not added:
            messagebox.showinfo(APP_TITLE, "没有可导出到日历的截止时间。")
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write("\r\n".join(lines))
            self._set_status(f"已导出日历（{added} 个日程）：{path}", "ok")
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"导出失败：{e}")


# ================================================================ 设备记录窗口
class MembersDialog(tk.Toplevel):
    """隐私查看权限：管理设备、恢复密钥与设备记录（均由主密钥保护）。"""

    def __init__(self, master, app=None):
        super().__init__(master)
        self.app = app
        self.title("隐私查看权限")
        try:
            dpi = self.winfo_fpixels("1i")
        except Exception:
            dpi = 96.0
        self.scale = max(1.0, round(dpi / 96.0, 2))
        self._s = lambda v: int(round(v * self.scale))
        self._imgs = {}
        s = self._s
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            dw = min(880, max(600, int((sw - s(48)) / self.scale)))
            # 初始只显示最简面板，高度先给小的；识别到管理设备时 _relayout 会撑开
            dh = min(660, max(300, int((sh - s(96)) / self.scale)))
            self.geometry("%dx%d+%d+%d" % (
                s(dw), s(dh),
                max(0, (sw - s(dw)) // 2), max(0, (sh - s(dh)) // 2 - s(20))))
            self.minsize(s(min(700, dw)), s(250))
        except Exception:
            self.geometry("880x300")
        self.configure(bg=BG)
        self.transient(master)
        self._devices = []
        self._state = {"state": "unregistered", "device": None, "display": ""}
        self._members = []
        self._q = queue.Queue()
        self._resize_job = None
        self._build()
        self._pump()
        self.bind("<Configure>", self._on_resize)
        self.after(120, self.refresh)

    def _img(self, name):
        try:
            if name in self._imgs:
                return self._imgs[name]
            hi = name.replace(".png", "@2x.png") if self.scale >= 1.4 else name
            p = _resource("assets", hi)
            if not os.path.exists(p):
                p = _resource("assets", name)
            im = tk.PhotoImage(file=p)
            self._imgs[name] = im
            return im
        except Exception:
            return None

    # ------------------------------------------------------------ 自适应
    def _on_resize(self, event=None):
        if event is not None and getattr(event, "widget", None) is not self:
            return
        try:
            if self._resize_job:
                self.after_cancel(self._resize_job)
        except Exception:
            pass
        try:
            self._resize_job = self.after(120, self._apply_resize)
        except Exception:
            pass

    def _apply_resize(self):
        self._resize_job = None
        try:
            w = self.winfo_width()
            self.lbl_foot.configure(wraplength=max(self._s(280), w - self._s(64)))
            total = self.tree.winfo_width()
            if total > 20:
                for k, r in (("name", 0.28), ("type", 0.16), ("fp", 0.36), ("added", 0.20)):
                    self.tree.column(k, width=max(self._s(56), int(total * r)))
        except Exception:
            pass

    # ------------------------------------------------------------ 线程 <-> UI
    def _post(self, fn):
        self._q.put(fn)

    def _pump(self):
        try:
            while True:
                fn = self._q.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        try:
            self.after(80, self._pump)
        except Exception:
            pass

    # ------------------------------------------------------------ 界面
    def _build(self):
        s = self._s
        wrap = tk.Frame(self, bg=BG, padx=s(18), pady=s(16))
        wrap.pack(fill="both", expand=True)

        # 标题
        head = tk.Frame(wrap, bg=BG)
        head.pack(fill="x")
        ic = self._img("shield.png")
        if ic:
            tk.Label(head, image=ic, bg=BG).pack(side="left", padx=(0, s(10)))
        ht = tk.Frame(head, bg=BG)
        ht.pack(side="left")
        tk.Label(ht, text="隐私查看权限", bg=BG, fg=INK,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")

        # 状态卡
        card = tk.Frame(wrap, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(s(14), 0))
        inner = tk.Frame(card, bg=CARD, padx=s(16), pady=s(14))
        inner.pack(fill="x")

        self.lbl_key = tk.Label(inner, text="", bg=CARD, fg=ACCENT,
                                font=("Microsoft YaHei UI", 10, "bold"), anchor="w")
        self.lbl_key.pack(fill="x")

        row1 = tk.Frame(inner, bg=CARD)
        row1.pack(fill="x", pady=(s(12), 0))
        ttk.Button(row1, text="重新检测", style="Ghost.TButton", image=self._img("refresh.png"),
                   compound="left", command=self.refresh).pack(side="left")
        # 与设备相关的操作：只在「有高级权限」或「刚接入未登记的设备」时出现
        self.row2 = tk.Frame(inner, bg=CARD)
        self.btn_register = ttk.Button(self.row2, text="登记当前设备", style="Ghost.TButton",
                                       image=self._img("key.png"), compound="left",
                                       command=self._do_register, state="disabled")
        self.btn_unlock_bak = ttk.Button(self.row2, text="用恢复密钥解锁…", style="Ghost.TButton",
                                         image=self._img("unlock.png"), compound="left",
                                         command=self._unlock_with_backup, state="disabled")
        self.btn_backup = ttk.Button(self.row2, text="生成恢复密钥…", style="Ghost.TButton",
                                     image=self._img("shield.png"), compound="left",
                                     command=self._create_backup, state="disabled")

        # 记录卡（没有高级权限时整块隐藏）
        listcard = tk.Frame(wrap, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        self.listcard = listcard
        lhead = tk.Frame(listcard, bg=CARD, padx=s(16), pady=s(10))
        lhead.pack(fill="x")
        tk.Label(lhead, text="设备记录", bg=CARD, fg=INK,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        self.btn_remove = ttk.Button(lhead, text="删除选中", style="Ghost.TButton",
                                     image=self._img("trash.png"), compound="left",
                                     command=self._remove, state="disabled")
        self.btn_remove.pack(side="right")
        self.btn_add = ttk.Button(lhead, text="添加记录", style="Accent.TButton",
                                  command=self._add, state="disabled")
        self.btn_add.pack(side="right", padx=s(8))

        tbl = tk.Frame(listcard, bg=CARD, padx=s(14))
        tbl.pack(fill="both", expand=True, pady=(0, s(10)))
        cols = ("name", "type", "fp", "added")
        self.tree = ttk.Treeview(tbl, columns=cols, show="headings", height=8)
        for key, text, width, anchor in (
            ("name", "名称", 200, "w"),
            ("type", "类型", 100, "center"),
            ("fp", "标识", 230, "w"),
            ("added", "添加时间", 150, "w"),
        ):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=s(width), anchor=anchor)
        vsb = Rail(tbl, command=self.tree.yview, bg=CARD)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y", padx=(s(4), 0))
        self.tree.tag_configure("odd", background="#fafcff")
        self.tree.tag_configure("even", background="#ffffff")

        self.lbl_foot = tk.Label(wrap, text="", bg=BG, fg=SUB,
                                 font=("Microsoft YaHei UI", 9), anchor="w",
                                 justify="left", wraplength=s(800))
        self.lbl_foot.pack(fill="x", pady=(s(10), 0))

    # ------------------------------------------------------------ 检测
    def refresh(self):
        self.lbl_key.configure(text="")
        self.btn_register.configure(state="disabled")
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        try:
            try:
                cx_keyring.auto_cookie_key()      # 打开窗口时先探一次 keys/ 里的钥匙
            except Exception:
                pass
            devs = cx_env.scan_devices()
            st = cx_peer.state(devices=devs)
            level = cx_keyring.access_level()
            members = cx_peer.load_all() if st["state"] == "open" else None
            self._post(lambda: self._apply(devs, st, members, level))
        except Exception as e:  # noqa: BLE001
            err = str(e)
            self._post(lambda: self.lbl_key.configure(text=""))

    def _relayout(self, has_usb, advanced, unregistered):
        """按当前权限摆放面板：默认只露出最简信息，避免被旁人看到。

        · 没有高级权限 —— 不显示记录，也不显示设备相关的按钮；
        · 检测到未登记的设备 —— 只多给一个「登记当前设备」；
        · 拿到高级权限 —— 才展开设备操作与设备记录。
        """
        s = self._s
        key = (bool(has_usb), bool(advanced), bool(unregistered))
        if getattr(self, "_layout_key", None) == key:
            return
        self._layout_key = key

        show_row = has_usb and (advanced or unregistered)
        show_list = has_usb and advanced

        for b in (self.btn_register, self.btn_unlock_bak, self.btn_backup):
            b.pack_forget()
        if has_usb and unregistered:
            self.btn_register.pack(side="left", padx=(0, s(8)))
        if has_usb and not advanced:
            self.btn_unlock_bak.pack(side="left", padx=(0, s(8)))
        if has_usb and advanced:
            self.btn_backup.pack(side="left", padx=(0, s(8)))

        if show_row:
            self.row2.pack(fill="x", pady=(s(10), 0))
        else:
            self.row2.pack_forget()
        if show_list:
            # before=foot：记录卡要排在底部说明的上方，否则重新 pack 会跑到说明后面
            self.listcard.pack(fill="both", expand=True, pady=(s(12), 0),
                               before=self.lbl_foot)
        else:
            self.listcard.pack_forget()

        try:
            self.update_idletasks()
            w = self.winfo_width()
            if w <= 1:
                w = s(880)
            h = max(self.winfo_reqheight(), s(430) if show_list else s(220))
            h = min(h, self.winfo_screenheight() - s(80))
            self.minsize(min(w, s(700)), s(220))
            self.geometry("%dx%d" % (w, h))   # 高度随内容收缩/展开
        except Exception:
            pass

    def _apply(self, devs, st, members, level="full"):
        self._devices = devs
        self._state = st
        self._members = members or []
        advanced = level == "full"          # 高级权限：设备或恢复密钥解开了主密钥
        has_usb = bool(devs)

        # ---- 权限状态不显示任何文字
        self.lbl_key.configure(text="")

        # ---- 面板：默认只显示上面这一块（受限视图）
        self._relayout(has_usb, advanced, st["state"] == "unregistered")
        self.btn_register.configure(
            state="normal" if (has_usb and st["state"] == "unregistered") else "disabled")
        self.btn_backup.configure(state="normal" if (has_usb and advanced) else "disabled")
        self.btn_unlock_bak.configure(state="normal" if (has_usb and not advanced) else "disabled")

        for iid in self.tree.get_children():
            self.tree.delete(iid)
        if advanced and members is not None:
            for i, m in enumerate(members):
                self.tree.insert("", "end", values=(
                    m.get("name", ""), m.get("type", ""),
                    cx_env.mask_id(m.get("fp", "")), m.get("added_at", "")),
                    tags=("odd" if i % 2 else "even",))
            self.btn_add.configure(state="normal")
            self.btn_remove.configure(state="normal")
            self.lbl_foot.configure(text="当前共 %d 条记录。标识仅显示前后若干位，完整值加密保存。" % len(members))
        else:
            self.btn_add.configure(state="disabled")
            self.btn_remove.configure(state="disabled")
            msg = "解锁后可查看记录" if not advanced else "记录无法解密（文件可能被损坏）"
            self.tree.insert("", "end", values=("🔒 " + msg, "", "", ""))

        # 底部说明只在真正展开高级面板时出现；受限视图保持干净
        if not (has_usb and advanced):
            self.lbl_foot.configure(text="")
        elif members is not None:
            self.lbl_foot.configure(text="当前共 %d 条记录。标识仅显示前后若干位，完整值加密保存。"
                                        % len(members))
        else:
            self.lbl_foot.configure(text="记录无法解密（文件可能被损坏）。")

    # ------------------------------------------------------------ 操作
    def _choose_device(self):
        if len(self._devices) == 1:
            return self._devices[0]
        win = tk.Toplevel(self)
        win.title("选择设备")
        win.geometry("%dx%d" % (self._s(480), self._s(280)))
        win.configure(bg="#ffffff")
        win.transient(self)
        tk.Label(win, text="检测到多枚设备，请选择要登记为管理密钥的那一枚：",
                 bg="#ffffff", anchor="w", justify="left", wraplength=430).pack(
            fill="x", padx=14, pady=(12, 8))
        var = tk.IntVar(value=0)
        for i, d in enumerate(self._devices):
            txt = "设备 #%d  ·  标识 %s" % (i + 1, cx_env.mask_id(d["fp"]))
            tk.Radiobutton(win, text=txt, variable=var, value=i, bg="#ffffff",
                           anchor="w", justify="left").pack(fill="x", padx=18)
        picked = {"dev": None}

        def ok():
            picked["dev"] = self._devices[var.get()]
            win.destroy()

        ttk.Button(win, text="确定", command=ok).pack(pady=12)
        win.grab_set()
        self.wait_window(win)
        return picked["dev"]

    def _do_register(self):
        if not self._devices:
            messagebox.showinfo("隐私查看权限", "没有检测到设备，请接入后点「重新检测」。", parent=self)
            return
        dev = self._choose_device()
        if not dev:
            return
        tip = ("将把当前设备登记为「管理密钥」：\n\n标识：%s\n\n"
               "登记后，Cookie 与设备记录都由它保护：\n"
               "  · 接入这台设备才能登录、提取与查看记录；\n"
               "  · 设备丢失时，可用恢复密钥解锁；两者都丢失则数据无法恢复。\n\n确定继续？") % (
            cx_env.mask_id(dev["fp"]))
        if not messagebox.askyesno("确认登记", tip, parent=self):
            return
        ok, msg = cx_peer.setup(dev)
        if ok:
            messagebox.showinfo(
                "隐私查看权限",
                "登记成功。\n\n建议立刻点「生成恢复密钥…」，把备份文件存到网盘或手机里，"
                "以防设备丢失。",
                parent=self)
            if self.app:
                self.app.on_keyring_unlocked()
        else:
            messagebox.showerror("隐私查看权限", "登记失败：" + msg, parent=self)
        self.refresh()

    def _create_backup(self):
        if not cx_keyring.ready():
            return
        pwd = PassDialog(self, "生成恢复密钥", confirm=True, allow_nopass=True)
        if pwd.value is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="保存恢复密钥",
            defaultextension=".cxkey", initialfile="隐私权限备份.cxkey",
            filetypes=[("恢复密钥文件", "*.cxkey"), ("所有文件", "*.*")],
        )
        if not path:
            return
        ok, msg = cx_keyring.create_backup(path, pwd.value)
        if ok:
            extra = ("该文件未设口令，本身即为钥匙：复制到任何位置（含网盘、设备、另一台电脑）"
                     "都能直接使用。\n请务必妥善保管，不要随意外发。" if not pwd.value else
                     "该文件可复制到任意位置使用，解封时需要你设置的口令。\n请牢记口令，"
                     "丢失后备份文件将无法解封。")
            messagebox.showinfo(
                "隐私查看权限",
                "恢复密钥已保存：\n%s\n\n%s\n建议不要与数据文件放在同一目录。" % (path, extra),
                parent=self)
        else:
            messagebox.showerror("隐私查看权限", msg, parent=self)

    def _unlock_with_backup(self):
        path = filedialog.askopenfilename(
            parent=self, title="选择恢复密钥文件",
            filetypes=[("恢复密钥文件", "*.cxkey"), ("所有文件", "*.*")],
        )
        if not path:
            return
        pwd = PassDialog(self, "解封恢复密钥", confirm=False,
                         hint="输入生成备份时设置的口令；未设口令的备份直接点「确定」")
        if pwd.value is None:
            return
        ok, msg = cx_keyring.unlock_with_backup(path, pwd.value)
        if ok:
            messagebox.showinfo("隐私查看权限", "解锁成功。", parent=self)
            if self.app:
                self.app.on_keyring_unlocked()
            self.refresh()
        else:
            messagebox.showerror("隐私查看权限", msg, parent=self)

    def _add(self):
        dlg = AddMemberDialog(self)
        if not dlg.result:
            return
        ok, msg = cx_peer.add(
            dlg.result["name"], dlg.result["type"], dlg.result["fp"])
        if not ok:
            messagebox.showwarning("隐私查看权限", msg, parent=self)
        self.refresh()

    def _remove(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("隐私查看权限", "请先选中一行。", parent=self)
            return
        idx = self.tree.index(sel[0])
        name = self.tree.item(sel[0], "values")[0]
        if not messagebox.askyesno("删除成员", "确定删除「%s」吗？" % name, parent=self):
            return
        ok, msg = cx_peer.remove(idx)
        if not ok:
            messagebox.showwarning("隐私查看权限", msg, parent=self)
        self.refresh()


class PassDialog(tk.Toplevel):
    """口令输入框（生成 / 解封恢复密钥）。"""

    def __init__(self, master, title, confirm=False, hint="", allow_nopass=False):
        super().__init__(master)
        self.title(title)
        self.geometry("430x300" if allow_nopass else ("430x250" if confirm else "430x210"))
        self.configure(bg="#ffffff")
        self.transient(master)
        self.value = None
        self._confirm = confirm
        self._allow_nopass = allow_nopass
        self.var_nopass = tk.BooleanVar(value=False)
        self._build(hint)
        self.grab_set()
        master.wait_window(self)

    def _build(self, hint):
        pad = {"padx": 18}
        if hint:
            tk.Label(self, text=hint, bg="#ffffff", fg="#6b7785",
                     font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x", pady=(14, 0), **pad)
        tk.Label(self, text="口令", bg="#ffffff", anchor="w").pack(fill="x", pady=(14, 2), **pad)
        self.var1 = tk.StringVar()
        self.e1 = tk.Entry(self, textvariable=self.var1, show="●")
        self.e1.pack(fill="x", **pad)
        if self._confirm:
            tk.Label(self, text="再输一次", bg="#ffffff", anchor="w").pack(fill="x", pady=(10, 2), **pad)
            self.var2 = tk.StringVar()
            self.e2 = tk.Entry(self, textvariable=self.var2, show="●")
            self.e2.pack(fill="x", **pad)
        if self._allow_nopass:
            tk.Checkbutton(self, text="不设口令（文件本身即钥匙，复制到任何地方都能用）",
                           variable=self.var_nopass, bg="#ffffff", anchor="w",
                           command=self._toggle).pack(fill="x", pady=(8, 0), **pad)
        self.lbl_note = tk.Label(self, text="口令用于包裹主密钥，忘记后备份文件将无法解封",
                                 bg="#ffffff", fg="#6b7785",
                                 font=("Microsoft YaHei UI", 9), anchor="w")
        self.lbl_note.pack(fill="x", pady=(8, 0), **pad)
        row = tk.Frame(self, bg="#ffffff")
        row.pack(fill="x", pady=14, **pad)
        ttk.Button(row, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(row, text="确定", command=self._ok).pack(side="right", padx=8)
        self.e1.focus_set()
        self.e1.bind("<Return>", lambda e: self._ok())

    def _toggle(self):
        on = self.var_nopass.get()
        state = "disabled" if on else "normal"
        try:
            self.e1.configure(state=state)
            if self._confirm:
                self.e2.configure(state=state)
            self.lbl_note.configure(
                text="未设口令：拿到该文件即可解锁，请务必妥善保管" if on
                else "口令用于包裹主密钥，忘记后备份文件将无法解封")
        except Exception:
            pass

    def _ok(self):
        if self._allow_nopass and self.var_nopass.get():
            self.value = ""
            self.destroy()
            return
        v = self.var1.get()
        if not v:
            if self._confirm:
                messagebox.showwarning("口令", "口令不能为空；如不需要口令请勾选下方选项。", parent=self)
                return
            self.value = ""      # 解封时允许留空（对应未设口令的备份）
            self.destroy()
            return
        if len(v) < 6:
            messagebox.showwarning("口令", "口令太短，请至少 6 位。", parent=self)
            return
        if self._confirm and v != self.var2.get():
            messagebox.showwarning("口令", "两次输入不一致。", parent=self)
            return
        self.value = v
        self.destroy()


class AddMemberDialog(tk.Toplevel):
    """添加一个设备记录（名称 + 类型 + 标识）。"""

    def __init__(self, master):
        super().__init__(master)
        self.title("添加设备记录")
        self.geometry("540x330")
        self.configure(bg="#ffffff")
        self.transient(master)
        self.result = None
        self._build()
        self.grab_set()
        master.wait_window(self)

    def _build(self):
        pad = {"padx": 18}
        tk.Label(self, text="名称", bg="#ffffff").pack(anchor="w", pady=(16, 2), **pad)
        self.var_name = tk.StringVar()
        tk.Entry(self, textvariable=self.var_name).pack(fill="x", **pad)

        tk.Label(self, text="类型", bg="#ffffff").pack(anchor="w", pady=(10, 2), **pad)
        self.var_type = tk.StringVar(value="手机")
        ttk.Combobox(self, textvariable=self.var_type, values=["电脑", "手机", "平板", "其他"],
                     state="readonly").pack(fill="x", **pad)

        tk.Label(self, text="标识（手机可填「设置 → 关于手机」里的序列号 / 设备 ID）",
                 bg="#ffffff", fg="#6b7785", font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", pady=(10, 2), **pad)
        self.var_fp = tk.StringVar()
        tk.Entry(self, textvariable=self.var_fp).pack(fill="x", **pad)
        ttk.Button(self, text="使用本机标识", command=self._use_pc).pack(anchor="w", pady=(6, 0), **pad)

        row = tk.Frame(self, bg="#ffffff")
        row.pack(fill="x", pady=16, **pad)
        ttk.Button(row, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(row, text="确定添加", command=self._ok).pack(side="right", padx=8)

    def _use_pc(self):
        self.var_fp.set(cx_env.machine_id())
        if not self.var_name.get().strip():
            self.var_name.set("本机")

    def _ok(self):
        name = self.var_name.get().strip()
        fp = self.var_fp.get().strip()
        if not name:
            messagebox.showwarning("添加记录", "请填写名称。", parent=self)
            return
        if not fp:
            messagebox.showwarning("添加记录", "请填写标识，或点「使用本机标识」。", parent=self)
            return
        self.result = {"name": name, "type": self.var_type.get() or "其他", "fp": fp}
        self.destroy()


def _selftest(argv):
    """打包后的自检：用给定 Cookie 文件跑一次完整提取，结果写入日志。

    用法： 超星作业提取.exe --selftest <cookie文件路径>
    """
    log_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "selftest_log.txt")
    lines = []
    try:
        cookie_path = argv[0] if argv else ""
        lines.append(f"frozen={getattr(sys, 'frozen', False)}")
        lines.append(f"cwd={os.getcwd()}")
        import requests
        lines.append(f"requests={requests.__version__}")
        import bs4
        lines.append(f"bs4={bs4.__version__}")

        # 加密仓库自检（在临时目录里做，不碰用户真实会话）
        import tempfile
        import shutil
        tmp = tempfile.mkdtemp(prefix="cxvault_")
        try:
            # 会话加密需要主密钥：这里临时注入一把测试密钥
            import os as _os
            cx_keyring.set_master(_os.urandom(32), "selftest")
            fake = {"_uid": "u1", "fid": "123", "_d": "SECRET_XYZ"}
            saved = cx_vault.save_session(fake, base_dir=tmp)
            blob = open(os.path.join(tmp, "session.dat"), "rb").read()
            leak = any(v.encode() in blob for v in fake.values())
            ro = cx_vault.load_session(base_dir=tmp)
            readonly_ok = True
            try:
                ro["x"] = "y"
                readonly_ok = False
            except Exception:
                pass
            bad = bytearray(blob)
            bad[-1] ^= 0xFF
            open(os.path.join(tmp, "session.dat"), "wb").write(bytes(bad))
            tamper_ok = cx_vault.load_session(base_dir=tmp) is None
            lines.append(
                f"vault: save={saved} plaintext_leak={leak} load={ro is not None} "
                f"readonly={readonly_ok} tamper_detected={tamper_ok}"
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # 无需任何钥匙即可「创建」加密 cookie 文件（读取仍需解锁）
        tmp3 = tempfile.mkdtemp(prefix="cxnoauth_")
        orig_ckp = cx_keyring.cookie_key_path
        try:
            # 假装 keys 文件夹里没有 CookieKey，否则会自动识别并放行（那是另一条自检）
            cx_keyring.cookie_key_path = lambda base_dir=None: os.path.join(tmp3, "NoCookieKey")
            cx_keyring.lock()
            created = cx_vault.save_session({"_uid": "u2"}, base_dir=tmp3)
            read_blocked = cx_vault.load_session(base_dir=tmp3) is None
            lines.append(f"noauth_create: save={created} read_blocked={read_blocked}")
        finally:
            cx_keyring.cookie_key_path = orig_ckp
            cx_keyring.lock()
            shutil.rmtree(tmp3, ignore_errors=True)

        # 10 秒周期复核自检（拔出设备 -> 收回权限）
        tmp4 = tempfile.mkdtemp(prefix="cxwatch_")
        try:
            import hashlib as _hl
            hw = "USB|WTEST|SN1"
            dev = {"model": "WTEST", "serial": "SN1", "letters": "",
                   "hw_id": hw, "fp": _hl.sha256(hw.encode()).hexdigest()}
            ckp = os.path.join(tmp4, "CK")
            cx_keyring.lock()
            cx_keyring.register_device(dev, base_dir=tmp4)
            lv_present = cx_keyring.revalidate(devices=[dev], base_dir=tmp4, ck_path=ckp)["level"]
            lv_1 = cx_keyring.revalidate(devices=[], base_dir=tmp4, ck_path=ckp)["level"]
            lv_2 = cx_keyring.revalidate(devices=[], base_dir=tmp4, ck_path=ckp)["level"]
            lines.append(f"watch({cx_keyring.WATCH_INTERVAL}s): present={lv_present} "
                         f"strike1={lv_1} strike2={lv_2}")
        finally:
            shutil.rmtree(tmp4, ignore_errors=True)
            cx_keyring.lock()

        # CookieKey：一次创建、绑本机、自动检测
        tmp5 = tempfile.mkdtemp(prefix="cxckonly_")
        orig_ckp5 = cx_keyring.cookie_key_path
        orig_mark5 = cx_keyring.cookie_key_mark_path
        orig_ms5 = cx_guard.machine_secret
        try:
            ckp5 = os.path.join(tmp5, "CookieKey")
            # 全部隔离到临时目录，避免碰到真实的 CookieKey 与标记
            cx_keyring.cookie_key_path = lambda base_dir=None: os.path.join(tmp5, "__none__")
            cx_keyring.cookie_key_mark_path = lambda: os.path.join(tmp5, ".lock")
            cx_keyring.lock()
            made = cx_keyring.create_cookie_key(ckp5)[0]          # 不需要任何权限
            again = cx_keyring.create_cookie_key(ckp5)[0]         # 每台电脑只能创建一次
            cx_keyring.load_cookie_key(ckp5)
            saved5 = cx_vault.save_session({"_uid": "ck1"}, base_dir=tmp5)
            cx_keyring.lock()
            blocked = cx_vault.load_session(base_dir=tmp5) is None
            # 把 CookieKey 放回 keys 文件夹：自动识别即可读取
            cx_keyring.cookie_key_path = lambda base_dir=None: ckp5
            cx_keyring.lock()
            ro = cx_vault.load_session(base_dir=tmp5)
            auto = bool(ro)
            # 换台电脑（伪造本机标识）应当解不开
            cx_guard.machine_secret = lambda: b"selftest-other-pc\x1fguid\x1f123456"
            cx_keyring.lock()
            foreign_read = cx_vault.load_session(base_dir=tmp5)
            foreign_load = cx_keyring.load_cookie_key(ckp5)
            foreign_flag = cx_keyring.cookie_key_state()["foreign"]
            cx_guard.machine_secret = orig_ms5
            cx_keyring.lock()
            home_again = bool(cx_vault.load_session(base_dir=tmp5))
            lines.append(f"cookiekey: create={made} again={again} save={saved5} "
                         f"blocked_without={blocked} auto={auto} load={bool(ro)} "
                         f"uid={ro['_uid'] if ro else None} "
                         f"foreign_load={foreign_load} foreign_read={bool(foreign_read)} "
                         f"foreign_flag={foreign_flag} home_again={home_again}")
        finally:
            cx_guard.machine_secret = orig_ms5
            cx_keyring.cookie_key_path = orig_ckp5
            cx_keyring.cookie_key_mark_path = orig_mark5
            shutil.rmtree(tmp5, ignore_errors=True)
            cx_keyring.lock()

        # 首次运行声明：标记写一次后不再弹
        tmp6 = tempfile.mkdtemp(prefix="cxeula_")
        orig_pp = cx_eula._primary_path
        orig_fb = cx_eula._fallback_path
        try:
            cx_eula._primary_path = lambda: os.path.join(tmp6, ".eula.ok")
            cx_eula._fallback_path = lambda: os.path.join(tmp6, "fb", ".eula.ok")
            first_open = cx_eula.accepted()
            wrote = cx_eula.accept()
            second_open = cx_eula.accepted()
            lines.append(f"eula: first_open={first_open} write={wrote} "
                         f"second_open={second_open}")
        finally:
            cx_eula._primary_path = orig_pp
            cx_eula._fallback_path = orig_fb
            shutil.rmtree(tmp6, ignore_errors=True)

        # CookieKey 统一收进 keys/：旧布局（根目录）会被自动搬迁
        tmp7 = tempfile.mkdtemp(prefix="cxlayout_")
        orig_home7 = cx_keyring.ck_home_dir
        orig_leg7 = cx_keyring.legacy_cookie_key_path
        orig_legm7 = cx_keyring.legacy_mark_path
        try:
            cx_keyring.ck_home_dir = lambda base_dir=None: os.path.join(tmp7, "keys")
            cx_keyring.legacy_cookie_key_path = lambda: os.path.join(tmp7, "CookieKey")
            cx_keyring.legacy_mark_path = lambda: os.path.join(tmp7, ".cookiekey.lock")
            with open(os.path.join(tmp7, "CookieKey"), "wb") as f:
                f.write(b"CXCK1\x00legacy")
            with open(os.path.join(tmp7, ".cookiekey.lock"), "w", encoding="utf-8") as f:
                f.write("{}")
            moved = cx_keyring.migrate_layout()
            in_keys = os.path.exists(os.path.join(tmp7, "keys", "CookieKey"))
            legacy_gone = not os.path.exists(os.path.join(tmp7, "CookieKey"))
            lines.append(f"layout: moved={moved} in_keys={in_keys} "
                         f"legacy_gone={legacy_gone}")
        finally:
            cx_keyring.ck_home_dir = orig_home7
            cx_keyring.legacy_cookie_key_path = orig_leg7
            cx_keyring.legacy_mark_path = orig_legm7
            shutil.rmtree(tmp7, ignore_errors=True)

        # 设备门控自检（临时目录 + 假设备，不碰真实钥匙）
        tmp2 = tempfile.mkdtemp(prefix="cxusb_")
        try:
            import hashlib
            hw_id = "USB|TESTUSB|SN123"
            fake_dev = {
                "model": "TESTUSB", "serial": "SN123", "letters": "Z:",
                "hw_id": hw_id, "fp": hashlib.sha256(hw_id.encode()).hexdigest(),
            }
            reg = cx_peer.setup(fake_dev, base_dir=tmp2)[0]
            open_state = cx_peer.state(base_dir=tmp2, devices=[fake_dev])["state"]
            bak_ok = cx_keyring.create_backup(os.path.join(tmp2, "b.cxkey"), "selftest123")[0]
            cx_keyring.lock()
            locked_state = cx_peer.state(base_dir=tmp2, devices=[])["state"]
            locked_none = cx_peer.load_all(base_dir=tmp2) is None
            unlock_ok = cx_keyring.unlock_with_backup(
                os.path.join(tmp2, "b.cxkey"), "selftest123")[0]
            members_after = cx_peer.load_all(base_dir=tmp2)
            lines.append(
                f"members: register={reg} open={open_state} backup={bak_ok} "
                f"locked={locked_state} read_locked={locked_none} "
                f"unlock_backup={unlock_ok} count={len(members_after or [])}"
            )
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)
            cx_keyring.lock()

        if not cookie_path or not os.path.exists(cookie_path):
            lines.append(f"cookie 文件不存在: {cookie_path}")
        else:
            with open(cookie_path, "r", encoding="utf-8-sig", errors="replace") as f:
                raw = f.read()
            client = cx.ChaoxingClient(raw, timeout=25)
            ok, msg = client.check_login()
            lines.append(f"check_login={ok} | {msg}")
            data = client.extract_all(only_incomplete=True)
            lines.append(f"courses={data['courses_count']} tasks={len(data['tasks'])}")
            for t in data["tasks"]:
                lines.append(f"  [{t['type']}] {t['course']} | {t['name']} | {t['deadline']}")
            lines.append(f"errors={data['errors']}")
        lines.append("RESULT=OK")
    except Exception as e:  # noqa: BLE001
        import traceback
        lines.append("RESULT=FAIL " + str(e))
        lines.append(traceback.format_exc())
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass


def _enter_app_dir():
    """等价于启动脚本里的 cd /d "%~dp0"：无论从哪里启动，工作目录都切到程序所在目录。"""
    try:
        base = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
        d = os.path.dirname(os.path.abspath(base))
        if d and os.path.isdir(d):
            os.chdir(d)
    except Exception:
        pass


def main():
    _enter_app_dir()      # 内置原来 bat 里的「切换到程序目录」
    if "--selftest" in sys.argv:
        idx = sys.argv.index("--selftest")
        _selftest(sys.argv[idx + 1:])
        return
    _enable_hidpi()
    try:
        cx_keyring.migrate_layout()   # 旧版把 CookieKey 放在根目录，这里搬进 keys/
    except Exception:
        pass
    root = tk.Tk()
    root.withdraw()
    if not cx_eula.accepted():
        if not _ask_eula(root):
            root.destroy()
            return
    App(root)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
