# -*- coding: utf-8 -*-
"""Deadline —— Windows 安装程序（向导式）。

界面：欢迎 → 许可协议 → 选择安装位置 → 安装进度 → 完成。
安装动作：复制主程序、创建开始菜单/桌面快捷方式、写入控制面板卸载项。
卸载：控制面板里点「卸载」，或运行安装目录下的程序加 --uninstall。

打包（见 build_installer.bat）：
    pyinstaller --onefile --noconsole --icon assets/app.ico \
        --add-data "Deadline.exe;payload" --add-data "README.md;payload" \
        --name "Windows-Setup" installer.py
"""

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "Deadline"
APP_VER = "1.0.0"
PUBLISHER = "Deadline"
REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Deadline"
EXE_NAME = APP_NAME + ".exe"

BG = "#f5f7fb"
CARD = "#ffffff"
ACCENT = "#2f6fed"
TEXT = "#1f2937"
SUB = "#6b7280"


def _asset(name, meipass_attr="_MEIPASS"):
    base = getattr(sys, meipass_attr, None) or os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(base, name)
    return p if os.path.exists(p) else None


def _payload():
    """内嵌的主程序与说明文件（源码目录下直接跑时就是当前目录）。"""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(base, "payload")
    return p if os.path.isdir(p) else base


def _default_dir():
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(root, "Programs", APP_NAME)


def _ps_shortcut(lnk, target, workdir, desc=""):
    """用 WScript.Shell 创建 .lnk（不依赖 pywin32）。"""
    esc = lambda s: s.replace("'", "''")
    script = (
        "$W=New-Object -ComObject WScript.Shell;"
        "$s=$W.CreateShortcut('%s');"
        "$s.TargetPath='%s';$s.WorkingDirectory='%s';"
        "$s.IconLocation='%s,0';$s.Description='%s';$s.Save()"
        % (esc(lnk), esc(target), esc(workdir), esc(target), esc(desc))
    )
    # PowerShell 首次冷启动偶尔会超时/失败，重试一次
    for _ in range(2):
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                 "-Command", script],
                creationflags=0x08000000, timeout=90, check=False,
            )
        except Exception:
            pass
        if os.path.exists(lnk):
            return True
    return False


def _sync_shortcut(lnk, wanted, exe, workdir):
    """需要的就建，不需要的（上次装过留下的）就删。"""
    if wanted:
        try:
            os.makedirs(os.path.dirname(lnk), exist_ok=True)
        except OSError:
            pass
        _ps_shortcut(lnk, exe, workdir, "%s - 作业/考试时间提取" % APP_NAME)
    else:
        try:
            if os.path.exists(lnk):
                os.remove(lnk)
        except OSError:
            pass


def _reg_write(target, exe):
    """写入「设置 → 应用」里的卸载项（HKCU，不需要管理员）。"""
    import winreg
    size = 0
    try:
        size = os.path.getsize(exe) // 1024
    except OSError:
        pass
    values = [
        ("DisplayName", APP_NAME),
        ("DisplayVersion", APP_VER),
        ("Publisher", PUBLISHER),
        ("DisplayIcon", exe),
        ("InstallLocation", target),
        ("UninstallString", '"%s" --uninstall' % exe),
        ("QuietUninstallString", '"%s" --uninstall' % exe),
        ("NoModify", 1),
        ("NoRepair", 1),
        ("EstimatedSize", size),
    ]
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY)
        for name, val in values:
            if isinstance(val, int):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, val)
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, val)
        winreg.CloseKey(key)
    except OSError:
        pass          # 注册表写不进去不影响使用，只是没有卸载项


def _install_core(target, menu=True, desktop=True, step=None):
    """真正的安装动作：GUI 与 --silent 共用。返回装好的 exe 路径。"""
    step = step or (lambda pct, msg: None)
    src = os.path.join(_payload(), EXE_NAME)
    if not os.path.exists(src):
        raise RuntimeError("安装包内缺少主程序（payload 未内嵌）。")

    step(10, "准备安装目录…")
    os.makedirs(target, exist_ok=True)

    step(30, "复制程序文件…")
    dst = os.path.join(target, EXE_NAME)
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy2(src, dst)

    step(50, "复制说明文件…")
    for name in ("README.md", "LICENSE"):
        s = os.path.join(_payload(), name)
        if os.path.exists(s):
            try:
                shutil.copy2(s, os.path.join(target, name))
            except OSError:
                pass

    step(65, "创建快捷方式…")
    sm = os.path.join(os.environ.get("APPDATA", ""),
                      r"Microsoft\Windows\Start Menu\Programs")
    desk = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    _sync_shortcut(os.path.join(sm, APP_NAME + ".lnk"), menu, dst, target)
    _sync_shortcut(os.path.join(desk, APP_NAME + ".lnk"), desktop, dst, target)

    step(85, "登记卸载信息…")
    _reg_write(target, dst)
    return dst


class Setup(tk.Tk):
    STEPS = ("欢迎", "许可协议", "安装位置", "完成")

    def __init__(self):
        super().__init__()
        self.title("%s 安装程序" % APP_NAME)
        self.configure(bg=BG)
        self.resizable(False, False)
        ico = _asset(os.path.join("assets", "app.ico"))
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        self.dir_var = tk.StringVar(value=_default_dir())
        self.desktop_var = tk.BooleanVar(value=True)
        self.menu_var = tk.BooleanVar(value=True)
        self.run_var = tk.BooleanVar(value=True)
        self.q = queue.Queue()
        self._step = 0
        self._installing = False

        self._center(660, 470)
        self._build()
        self._show(0)

    # ------------------------------------------------------------------ 布局
    def _center(self, w, h):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 3))

    def _build(self):
        head = tk.Frame(self, bg=ACCENT, height=76)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text=APP_NAME + "  安装程序", bg=ACCENT, fg="white",
                 font=("Microsoft YaHei UI", 15, "bold")).pack(side="left", padx=24)
        tk.Label(head, text="v" + APP_VER, bg=ACCENT, fg="#dbe6ff",
                 font=("Microsoft YaHei UI", 10)).pack(side="right", padx=24)

        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True, padx=20, pady=14)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=20, pady=(0, 14))
        self.btn_back = ttk.Button(bar, text="上一步", command=self._back, width=10)
        self.btn_next = ttk.Button(bar, text="下一步", command=self._next, width=10)
        self.btn_cancel = ttk.Button(bar, text="取消", command=self._cancel, width=10)
        self.btn_cancel.pack(side="right")
        self.btn_next.pack(side="right", padx=8)
        self.btn_back.pack(side="right")

        self.pages = [self._page_welcome(), self._page_license(),
                      self._page_dir(), self._page_done()]

    def _card(self):
        f = tk.Frame(self.body, bg=CARD, highlightthickness=1,
                     highlightbackground="#e3e8f0")
        f.pack(fill="both", expand=True)
        return f

    def _page_welcome(self):
        f = self._card()
        tk.Label(f, text="欢迎使用 %s" % APP_NAME, bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", padx=24, pady=(24, 8))
        txt = (
            "本程序会把学习通里「还没做的作业、还没考的试」一次性列出来，\n"
            "按「未完成 / 超时未交 / 已完成」分块显示，可导出 CSV 或日历。\n\n"
            "它只做读取：不会提交作业、不会答题、不会改动任何数据。\n\n"
            "安装程序会把程序装到下面的位置，并创建开始菜单快捷方式（可选桌面快捷方式），"
            "卸载时可在「设置 → 应用」里直接卸掉。\n\n"
            "继续之前，请先阅读并同意下一步的许可与免责声明。"
        )
        tk.Label(f, text=txt, bg=CARD, fg=SUB, justify="left",
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=24)
        return f

    def _page_license(self):
        f = self._card()
        tk.Label(f, text="许可与免责声明", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=24, pady=(18, 6))
        box = tk.Text(f, wrap="word", height=13, relief="flat", bg="#fbfcfe",
                      fg=TEXT, font=("Microsoft YaHei UI", 9),
                      padx=12, pady=10, highlightthickness=1,
                      highlightbackground="#e3e8f0")
        box.pack(fill="both", expand=True, padx=24)
        try:
            import cx_eula
            body = cx_eula.BODY
        except Exception:
            body = ("本软件按「现状」提供，不附带任何明示或暗示的担保。\n"
                    "仅用于个人学习辅助，请遵守所在学校规定与学习通服务条款。\n"
                    "作者不对使用本软件造成的任何后果负责。\n\n"
                    "许可：MIT。")
        box.insert("1.0", body)
        box.configure(state="disabled")
        self.agree = tk.BooleanVar(value=False)

        def _flip():
            self.btn_next.configure(state="normal" if self.agree.get() else "disabled")

        ttk.Checkbutton(f, text="我已阅读并同意上述条款", variable=self.agree,
                        command=_flip).pack(anchor="w", padx=24, pady=10)
        return f

    def _page_dir(self):
        f = self._card()
        tk.Label(f, text="选择安装位置", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=24, pady=(20, 4))
        tk.Label(f, text="装在当前用户目录下不需要管理员权限；装到 Program Files 需要管理员。",
                 bg=CARD, fg=SUB, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=24)

        row = tk.Frame(f, bg=CARD)
        row.pack(fill="x", padx=24, pady=(14, 6))
        ttk.Entry(row, textvariable=self.dir_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="浏览…", command=self._browse, width=8).pack(side="left", padx=8)

        ttk.Checkbutton(f, text="创建开始菜单快捷方式", variable=self.menu_var).pack(
            anchor="w", padx=24, pady=(4, 0))
        ttk.Checkbutton(f, text="创建桌面快捷方式", variable=self.desktop_var).pack(
            anchor="w", padx=24, pady=(6, 0))

        tk.Label(f, text="安装内容", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=24, pady=(18, 2))
        size = 0
        try:
            size = os.path.getsize(os.path.join(_payload(), EXE_NAME)) // (1024 * 1024)
        except OSError:
            pass
        tk.Label(f, text="· %s（主程序，约 %d MB）\n· README / LICENSE" % (EXE_NAME, size or 18),
                 bg=CARD, fg=SUB, justify="left",
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=24)

        self.pb = ttk.Progressbar(f, mode="determinate", maximum=100)
        self.pb.pack(fill="x", padx=24, pady=(16, 4))
        self.lbl_pb = tk.Label(f, text="", bg=CARD, fg=SUB, font=("Microsoft YaHei UI", 9))
        self.lbl_pb.pack(anchor="w", padx=24)
        return f

    def _page_done(self):
        f = self._card()
        tk.Label(f, text="安装完成", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", padx=24, pady=(28, 8))
        self.lbl_done = tk.Label(f, text="", bg=CARD, fg=SUB, justify="left",
                                 font=("Microsoft YaHei UI", 10))
        self.lbl_done.pack(anchor="w", padx=24)
        ttk.Checkbutton(f, text="立即运行 %s" % APP_NAME, variable=self.run_var).pack(
            anchor="w", padx=24, pady=(20, 0))
        return f

    # ------------------------------------------------------------------ 流程
    def _show(self, i):
        self._step = i
        for n, p in enumerate(self.pages):
            p.pack_forget()
        self.pages[i].pack(fill="both", expand=True)
        last = i == len(self.pages) - 1
        self.btn_back.configure(state="disabled" if i == 0 or last else "normal")
        self.btn_cancel.configure(state="disabled" if last else "normal")
        if i == 1:
            self.btn_next.configure(text="安装", state="normal" if self.agree.get() else "disabled")
        elif i == 2:
            self.btn_next.configure(text="安装", state="normal")
        elif last:
            self.btn_next.configure(text="完成", state="normal")
        else:
            self.btn_next.configure(text="下一步", state="normal")

    def _next(self):
        if self._step == 1:
            # 许可页的「安装」：先跳到目录页确认路径
            self._show(2)
            return
        if self._step == 2:
            self._start()
            return
        if self._step == len(self.pages) - 1:
            self._finish()
            return
        self._show(self._step + 1)

    def _back(self):
        if self._step in (1, 2):
            self._show(self._step - 1)

    def _cancel(self):
        if self._installing:
            if not messagebox.askyesno(APP_NAME, "正在安装，确定要中断吗？"):
                return
        self.destroy()

    def _browse(self):
        p = filedialog.askdirectory(title="选择安装位置",
                                    initialdir=self.dir_var.get() or _default_dir())
        if p:
            self.dir_var.set(os.path.join(p, APP_NAME) if os.path.basename(p) != APP_NAME else p)

    # ------------------------------------------------------------------ 安装
    def _start(self):
        target = (self.dir_var.get() or "").strip()
        if not target:
            messagebox.showerror(APP_NAME, "请填写安装位置。")
            return
        self._installing = True
        self.btn_next.configure(state="disabled")
        self.btn_back.configure(state="disabled")
        self.btn_cancel.configure(state="disabled")
        threading.Thread(target=self._worker, args=(target,), daemon=True).start()
        self.after(80, self._drain)

    def _worker(self, target):
        def step(pct, msg):
            self.q.put(("progress", pct, msg))

        try:
            dst = _install_core(target, self.menu_var.get(), self.desktop_var.get(), step)
            step(100, "完成")
            self.q.put(("done", target, dst))
        except Exception as e:  # noqa: BLE001
            self.q.put(("error", str(e)))

    def _write_reg(self, target, exe):
        _reg_write(target, exe)

    def _drain(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "progress":
                    _, pct, text = msg
                    self.pb.configure(value=pct)
                    self.lbl_pb.configure(text=text)
                elif msg[0] == "done":
                    _, target, exe = msg
                    self._installing = False
                    self._target, self._exe = target, exe
                    self.lbl_done.configure(
                        text="程序已安装到：\n%s\n\n开始菜单里已有「%s」，"
                             "也可以在「设置 → 应用」里卸载。" % (target, APP_NAME))
                    self._show(len(self.pages) - 1)
                    return
                elif msg[0] == "error":
                    self._installing = False
                    messagebox.showerror(APP_NAME, "安装失败：\n%s" % msg[1])
                    self.btn_next.configure(state="normal")
                    self.btn_back.configure(state="normal")
                    self.btn_cancel.configure(state="normal")
                    return
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _finish(self):
        if self.run_var.get() and getattr(self, "_exe", None):
            try:
                subprocess.Popen([self._exe], cwd=self._target)
            except Exception:
                pass
        self.destroy()


def main():
    argv = sys.argv[1:]
    if "--silent" in argv:
        target = _default_dir()
        if "--dir" in argv:
            i = argv.index("--dir")
            if i + 1 < len(argv):
                target = argv[i + 1]
        print("INSTALLING", target)
        dst = _install_core(target, "--no-menu" not in argv, "--no-desktop" not in argv,
                            lambda p, m: print("  %3d%% %s" % (p, m)))
        print("INSTALL_OK", dst)
        return
    try:
        app = Setup()
        style = ttk.Style(app)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(10, 4))
        app.mainloop()
    except Exception as e:  # noqa: BLE001
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("安装程序", "启动失败：%s" % e)
        root.destroy()


if __name__ == "__main__":
    main()
