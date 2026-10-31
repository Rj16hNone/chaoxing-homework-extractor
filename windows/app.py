#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deadline · 未完成作业 / 考试 提取（桌面版）
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
import cx_keyring
import cx_guard
import cx_eula

APP_TITLE = "Deadline · 未完成作业 / 考试提取"
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
    def __init__(self, root):
        self.root = root
        self.cookies = None      # 只读 Cookie 视图（来自加密仓库或本次登录）
        self.data = None         # 最近一次提取结果
        self.busy = False
        self._q = queue.Queue()      # 子线程 -> 主线程 的 UI 更新队列
        self.f_on = {k: True for k in cx.STATE_ORDER}   # 三块各自的显示开关（默认全选）
        self._row_tasks = {}         # Treeview 行 iid -> 任务对象（筛选后行号会变）
        self._chips = {}
        self._build_ui()
        self._pump()
        self.root.after(200, self._restore_session)

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
        tk.Label(ht, text="Deadline · 作业 / 考试提取", bg=BG, fg=INK,
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
        self._run(mode=m)

    def _on_refresh(self):
        if self.busy or not self.cookies:
            return
        self._run(mode="cached")

    # ------------------------------------------------------------ 启动
    def _restore_session(self):
        """启动时直接载入本机已保存的登录态，不需要任何钥匙。"""
        threading.Thread(target=self._boot_worker, daemon=True).start()

    def _boot_worker(self):
        self._post(self.on_keyring_unlocked)

    def on_keyring_unlocked(self):
        """载入已保存的登录状态，并把界面切到「已保存状态」模式。"""
        self.btn_login.configure(state="normal")
        try:
            sess = cx_vault.load_session()
        except Exception:
            sess = None
        if sess is not None:
            self.cookies = sess
            self.btn_refresh.configure(state="normal")
            self.btn_logout.configure(state="normal")
            if self.mode.get() != "saved":
                self.mode.set("saved")
                self._switch_mode()

    def refresh_session_view(self):
        """重新载入本机登录态（保留给外部调用，行为等同启动时）。"""
        return self.on_keyring_unlocked()

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
        self.busy = True
        self.btn_login.configure(state="disabled")
        self.btn_refresh.configure(state="disabled")
        self.res_card.pack_forget()
        self._set_status("正在登录…" if mode == "account" else "正在读取课程与作业/考试，请稍候…", "info")
        threading.Thread(target=self._worker, args=(mode,), daemon=True).start()

    # ------------------------------------------------------------ 后台任务
    def _worker(self, mode):
        try:
            if mode == "account":
                cookies, msg = cx_login.chaoxing_login(
                    self.var_user.get().strip(),
                    self.var_pwd.get().strip(),
                    fid=self.var_fid.get().strip() or "-1",
                )
                saved = cx_vault.save_session(cookies)
                self.cookies = cx_vault.ReadOnlyCookies(cookies)
                self._post(lambda: self.var_pwd.set(""))      # 密码用完即从输入框抹掉
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


def _selftest(argv):
    """打包后的自检：用给定 Cookie 文件跑一次完整提取，结果写入日志。

    用法： Deadline.exe --selftest <cookie文件路径>
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

        # 加密仓库自检（临时目录，不碰真实会话；不需要任何钥匙）
        import tempfile
        import shutil
        tmp = tempfile.mkdtemp(prefix="cxvault_")
        try:
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

        # 首次运行声明：标记写一次后不再弹
        tmp_eula = tempfile.mkdtemp(prefix="cxeula_")
        orig_pp = cx_eula._primary_path
        orig_fb = cx_eula._fallback_path
        try:
            cx_eula._primary_path = lambda: os.path.join(tmp_eula, ".eula.ok")
            cx_eula._fallback_path = lambda: os.path.join(tmp_eula, "fb", ".eula.ok")
            first_open = cx_eula.accepted()
            wrote = cx_eula.accept()
            second_open = cx_eula.accepted()
            lines.append(f"eula: first_open={first_open} write={wrote} "
                         f"second_open={second_open}")
        finally:
            cx_eula._primary_path = orig_pp
            cx_eula._fallback_path = orig_fb
            shutil.rmtree(tmp_eula, ignore_errors=True)

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


def _uninstall():
    """卸载：删快捷方式、卸载注册表项和整个安装目录（自己最后自删）。"""
    import subprocess
    import winreg

    exe = os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)
    d = os.path.dirname(exe)
    short = os.path.splitext(os.path.basename(exe))[0]     # 例如「Deadline」
    yes = "--yes" in sys.argv          # 供自动化/静默卸载使用
    root = tk.Tk()
    root.withdraw()
    if not yes and not messagebox.askyesno(
            APP_TITLE,
            "确定要卸载「%s」吗？\n\n将删除：\n· 程序文件（%s）\n"
            "· 开始菜单 / 桌面快捷方式\n· 控制面板里的卸载项\n\n"
            "（本机保存的登录状态也在这个目录里，会一并删除）" % (short, d)):
        root.destroy()
        return

    started = os.path.join(os.environ.get("APPDATA", ""),
                           r"Microsoft\Windows\Start Menu\Programs")
    desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    # 快捷方式可能按「短名」或「窗口标题」建的，两种都删；
    # 后两个是改名前的旧名，装了老版本的用户卸载时一并清掉
    names = {short, APP_TITLE,
             "超星作业提取", "超星学习通 · 未完成作业 / 考试提取"}
    links = []
    for nm in names:
        links.append(os.path.join(started, nm + ".lnk"))
        links.append(os.path.join(desktop, nm + ".lnk"))
        links.append(os.path.join(started, "超星学习通助手", nm + ".lnk"))
    for p in links:
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass
    for key in ("Deadline", "ChaoxingHelper"):     # 后者是改名前的旧键
        try:
            winreg.DeleteKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Uninstall\%s" % key)
        except OSError:
            pass

    # 先清空目录里除自己以外的文件，再由 cmd 等本进程退出后删掉自己和空目录
    try:
        for name in os.listdir(d):
            p = os.path.join(d, name)
            if os.path.abspath(p) == exe:
                continue
            try:
                if os.path.isdir(p):
                    import shutil
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except OSError:
                pass
    except OSError:
        pass
    try:
        subprocess.Popen(
            'cmd /c ping -n 3 127.0.0.1 >nul & cd /d "%%TEMP%%" & '
            'del /f /q "%s" & rd /s /q "%s"' % (exe, d),
            shell=True, creationflags=0x08000000)
    except Exception:
        pass
    if not yes:
        messagebox.showinfo(APP_TITLE, "已卸载，程序窗口将在几秒后关闭。")
    root.destroy()


def main():
    _enter_app_dir()      # 内置原来 bat 里的「切换到程序目录」
    if "--uninstall" in sys.argv:
        _uninstall()
        return
    if "--selftest" in sys.argv:
        idx = sys.argv.index("--selftest")
        _selftest(sys.argv[idx + 1:])
        return
    _enable_hidpi()
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
