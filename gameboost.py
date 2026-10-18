# -*- coding: utf-8 -*-
"""
GameBoost · 主程序（App 界面 + 模式逻辑）
车机竞技风 · 纯 tkinter · 零第三方依赖。配置与检测见 config.py / launchers.py。
"""
import os
import math
import queue
import time
import subprocess
import ctypes
import threading
import tkinter as tk
from tkinter import font as tkfont, messagebox
import re

import config
import launchers

APP_TITLE = "GameBoost"

# ===== 配色（分层：底 → 面板 → 卡片 → hover，逐层变亮 = 层次感）=====
BG_MAIN  = "#0A0D12"
PANEL    = "#12161D"
CARD     = "#171D26"
CARD_HI  = "#1E2632"
EDGE     = "#26303C"
EDGE_HI  = "#323D4C"
SHADOW   = "#04060A"
RED      = "#E8102D"
RED_HI   = "#FF2D55"
RED_DK   = "#4A0A16"
FG       = "#F2F5F8"
FG_DIM   = "#9AA6B2"
FG_MUT   = "#5C6773"
GREEN    = "#00E676"
AMBER    = "#FFB300"

WIN_W, WIN_H = 800, 500
TOPBAR_H = 56
LOG_H = 34


# ===== 工具 =====
def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _hex(c):
    return "#%02x%02x%02x" % c


def round_rect_pts(x1, y1, x2, y2, r):
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


def draw_vgradient(cv, w, h, c_top, c_bot, steps=36):
    for i in range(steps):
        t = i / (steps - 1)
        cv.create_rectangle(0, i * h / steps, w, (i + 1) * h / steps,
                            fill=_hex(_lerp(c_top, c_bot, t)), outline="")


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint), ("dwMemoryLoad", ctypes.c_uint),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def ram_percent():
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.dwMemoryLoad, m.ullAvailPhys, m.ullTotalPhys


def fmt_gb(b):
    return f"{b / 1073741824:.1f}G"


_SAFE_PROCESS_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _normalize_process_name(name):
    if not isinstance(name, str):
        return None
    value = name.strip()
    if value.lower().endswith(".exe"):
        value = value[:-4]
    if not value or not _SAFE_PROCESS_NAME.fullmatch(value):
        return None
    return value


def kill_procs(names):
    """按精确进程名清理，返回 (成功终止数, 工作集字节总和)。"""
    names = [n for n in (_normalize_process_name(x) for x in names) if n]
    if not names:
        return 0, 0
    ps = (
        "$names = @(" + ",".join("'" + n.replace("'", "''") + "'" for n in names) + "); "
        "$s = 0; $n = 0; "
        "$names | ForEach-Object { $targetName = $_; "
        "$c = @(Get-Process | Where-Object { $_.ProcessName -eq $targetName }); "
        "$s += ($c | Measure-Object WorkingSet64 -Sum).Sum; "
        "$n += $c.Count; "
        "$c | Stop-Process -Force -ErrorAction SilentlyContinue }; "
        "Write-Output ($n.ToString() + ';' + $s.ToString())"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=60,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        out = (r.stdout or b"").decode("utf-8", errors="replace").strip()
        parts = out.split(";")
        n = int(parts[0]) if len(parts) > 0 and parts[0].lstrip("-").isdigit() else 0
        mem = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else 0
        return n, mem
    except Exception:
        return 0, 0


def kill_procs_by_pid(targets):
    """按预览时的 (name, pid) 精确校验并清理进程。"""
    safe_targets = []
    for item in targets:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        name = _normalize_process_name(item[0])
        try:
            pid = int(item[1])
        except (TypeError, ValueError):
            continue
        if name and pid > 0:
            safe_targets.append((name, pid))
    if not safe_targets:
        return 0, 0
    pairs = ",".join(
        "@{Name='" + name.replace("'", "''") + "';Pid=" + str(pid) + "}"
        for name, pid in safe_targets
    )
    ps = (
        "$targets = @(" + pairs + "); $s = 0; $n = 0; "
        "$targets | ForEach-Object { $target = $_; "
        "$p = Get-Process -Id $target.Pid -ErrorAction SilentlyContinue; "
        "if ($null -ne $p -and $p.ProcessName -eq $target.Name) { "
        "$s += $p.WorkingSet64; $p | Stop-Process -Force -ErrorAction SilentlyContinue; $n++ } }; "
        "Write-Output ($n.ToString() + ';' + $s.ToString())"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=60,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        out = (r.stdout or b"").decode("utf-8", errors="replace").strip()
        parts = out.split(";")
        n = int(parts[0]) if len(parts) > 0 and parts[0].lstrip("-").isdigit() else 0
        mem = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else 0
        return n, mem
    except Exception:
        return 0, 0


# 系统/商店目录：其中的进程一律不清理（跨机器通用）
SYSTEM_DIRS = (
    r"c:\windows",
    r"c:\program files\windowsapps",
    r"c:\programdata\package cache",
)
GAME_DIR_MARKERS = (
    "\\steamapps\\common\\",
    "\\epic games\\",
    "\\wegameapps\\",
    "\\.minecraft\\",
    "\\games\\",
)

# 自身相关进程名（无论配置如何都不杀）
_SELF_KEEP = ("gameboost", "python", "powershell")


def detect_cleanable(keep_substrings):
    """跨机器通用的可清理进程检测。

    规则：当前用户会话内、路径不在系统目录、名字不含任何保留子串的进程
    = 候选（「大力停止」对象）。返回 [(进程名, PID, MB)]，按内存降序。
    """
    ps = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$sid = (Get-Process -Id $PID).SessionId; "
        "$fg = 0; $sig = 'using System; using System.Runtime.InteropServices; namespace Win32 { "
        "public static class NativeMethods { [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow(); "
        "[DllImport(\"user32.dll\")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p); } }'; "
        "Add-Type -TypeDefinition $sig -ErrorAction SilentlyContinue; "
        "if ('Win32.NativeMethods' -as [type]) { $fp = 0; "
        "$h = [Win32.NativeMethods]::GetForegroundWindow(); "
        "$null = [Win32.NativeMethods]::GetWindowThreadProcessId($h, [ref]$fp); $fg = $fp }; "
        "Get-Process | Where-Object { $_.SessionId -eq $sid -and $_.Id -ne $fg -and "
        "$_.MainWindowHandle -eq 0 } | "
        "ForEach-Object { '{0}|{1}|{2}|{3}' -f $_.Id, $_.ProcessName, "
        "[math]::Round($_.WorkingSet64 / 1MB, 0), ($_.Path -replace '\\|', '_') }"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=60,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        return []
    keep = [k.lower() for k in keep_substrings if k] + list(_SELF_KEEP)
    cands = []
    for line in (r.stdout or b"").decode("utf-8", errors="replace").splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        try:
            pid, name = int(parts[0]), parts[1].strip()
            mb = int(float(parts[2]))
        except ValueError:
            continue
        path = parts[3].strip()
        if not path:
            continue  # 拿不到路径 → 保守不碰
        path_lower = path.lower().replace("/", "\\")
        if path_lower.startswith(SYSTEM_DIRS):
            continue
        if any(marker in path_lower for marker in GAME_DIR_MARKERS):
            continue
        nl = name.lower()
        if any(k in nl for k in keep):
            continue
        cands.append((name, pid, mb))
    cands.sort(key=lambda x: -x[2])
    return cands


def launch(path):
    if not path:
        return False, "无启动器"
    if path.startswith("shell:"):
        try:
            subprocess.Popen(["explorer.exe", path], close_fds=True)
            return True, "已拉起(UWP)"
        except Exception as e:
            return False, str(e)
    if not os.path.exists(path):
        return False, "未找到启动器"
    try:
        os.startfile(path)  # ShellExecute：需要管理员时自动弹 UAC
        return True, "已启动"
    except OSError as e:
        if getattr(e, "winerror", 0) == 1223:
            return False, "已取消（需管理员权限）"
        return False, str(e)
    except Exception as e:
        return False, str(e)


# ===== 主窗口 =====
class App(tk.Tk):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.kill_list = list(cfg.get("kill_list") or [])
        self.keep_list = list(cfg.get("keep_list") or [])

        self.title(APP_TITLE)
        self.configure(bg=BG_MAIN)
        self.resizable(False, False)
        self._center(WIN_W, WIN_H)

        self._f_title = tkfont.Font(family="Microsoft YaHei UI", size=17, weight="bold")
        self._f_btn   = tkfont.Font(family="Microsoft YaHei UI", size=13, weight="bold")
        self._f_big   = tkfont.Font(family="Microsoft YaHei UI", size=24, weight="bold")
        self._f_timer = tkfont.Font(family="Consolas", size=40, weight="bold")
        self._f_small = tkfont.Font(family="Microsoft YaHei UI", size=9)
        self._f_dim   = tkfont.Font(family="Microsoft YaHei UI", size=10)

        self.current_mode = "正常"
        self.timer_sec = 0
        self._timer_id = None
        self.active_platform = None
        self._ui_queue = queue.Queue()
        self._hover_idx = None
        self._current_screen = None
        self.icons = {}

        self._launchers = self._enabled_launchers()

        self._build_topbar()
        self._build_screens()
        self._build_log()
        self.show_screen("home")
        if getattr(config, "CONFIG_ERROR", None):
            self._log(config.CONFIG_ERROR + "；已使用默认配置，请修正 config.json")

        self._pulse_phase = 0
        self._pulse()
        self._refresh_memory()
        self._poll_queue()
        self._run_async(self._extract_icons_async)

    # ---------- 启动器 ----------
    def _enabled_launchers(self):
        return [l for l in (self.cfg.get("launchers") or [])
                if isinstance(l, dict) and l.get("enabled", True) and l.get("path")]

    def _all_platform_procs(self):
        return [p for l in self._launchers for p in (l.get("processes") or [])]

    def _effective_kill(self, names):
        keep = [k.lower() for k in self.keep_list if k]
        return [n for n in names if not any(k in n.lower() for k in keep)]

    # ---------- 图标（后台提取 + 队列更新） ----------
    def _extract_icons_async(self):
        cache = os.path.join(config.app_dir(), "icons_cache")
        for l in self._launchers:
            png = launchers.extract_icon(l.get("path"), cache)
            if png:
                self._ui_queue.put(("icon", l["name"], png))
        self._ui_queue.put(("icons_done", None))

    def _load_icon(self, name, png):
        try:
            self.icons[name] = tk.PhotoImage(file=png)
        except Exception:
            pass

    def _rebuild_platform(self):
        if not getattr(self, "_built_platform", False):
            return
        if hasattr(self, "_card_cv"):
            try:
                self._card_cv.destroy()
            except Exception:
                pass
        self._built_platform = False
        self._hover_idx = None
        if self._current_screen == "platform":
            self._build_platform()

    def _do_redetect(self):
        self._ui_queue.put(("log", "正在重新检测启动器..."))
        try:
            detected = launchers.detect_launchers()
            merged = launchers.merge_launchers(self.cfg["launchers"], detected)
            self.cfg["launchers"] = merged
            config.save_config(self.cfg)
            self._launchers = self._enabled_launchers()
            self._ui_queue.put(("redetect_done", len(self._launchers)))
        except Exception as e:
            self._ui_queue.put(("log", f"检测失败：{e}"))

    # ---------- 基础 ----------
    def _center(self, w, h):
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    def _flat_btn(self, parent, text, cmd, bg, fg=FG, font=None, padx=20, pady=12):
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                         activebackground=RED_HI, activeforeground="#000",
                         font=font or self._f_btn, relief="flat", bd=0,
                         cursor="hand2", padx=padx, pady=pady)

    def _run_async(self, fn, *args):
        threading.Thread(target=fn, args=args, daemon=True).start()

    # ---------- 队列轮询 ----------
    def _poll_queue(self):
        try:
            while True:
                item = self._ui_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._log(item[1])
                elif kind == "freed":
                    self._show_freed(item[1])
                elif kind == "icon":
                    self._load_icon(item[1], item[2])
                elif kind == "icons_done":
                    self._rebuild_platform()
                elif kind == "redetect_done":
                    self._rebuild_platform()
                    self._log(f"检测完成，共 {item[1]} 个启动器")
                    self._run_async(self._extract_icons_async)
                elif kind == "extreme_preview":
                    self._show_extreme_preview(item[1], item[2])
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # ---------- 顶栏 ----------
    def _build_topbar(self):
        bar = tk.Frame(self, bg=PANEL, height=TOPBAR_H)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text=APP_TITLE, bg=PANEL, fg=FG, font=self._f_title).pack(side="left", padx=20)
        self.status_dot = tk.Canvas(bar, width=16, height=16, bg=PANEL, highlightthickness=0)
        self.status_dot.pack(side="right", padx=8)
        self._dot = self.status_dot.create_oval(3, 3, 13, 13, fill=GREEN, outline="")
        self.mode_label = tk.Label(bar, text="正常模式", bg=PANEL, fg=FG_DIM, font=self._f_dim)
        self.mode_label.pack(side="right", padx=(0, 4))
        tk.Label(bar, text="状态", bg=PANEL, fg=FG_DIM, font=self._f_small).pack(side="right", padx=6)

    def _set_mode_label(self, text, color=FG_DIM):
        self.mode_label.config(text=text, fg=color)

    # ---------- 日志 ----------
    def _build_log(self):
        box = tk.Frame(self, bg=PANEL, height=LOG_H)
        box.pack(side="bottom", fill="x")
        box.pack_propagate(False)
        self.log_box = tk.Label(box, text="就绪", bg=PANEL, fg=FG_DIM,
                                font=self._f_small, anchor="w", padx=12)
        self.log_box.pack(fill="both", expand=True)

    def _log(self, msg):
        if hasattr(self, "log_box"):
            self.log_box.config(text=msg)

    def _show_freed(self, freed):
        if hasattr(self, "freed_lbl"):
            if freed > 50 * 1024 * 1024:
                self.freed_lbl.config(text=f"本次释放 {fmt_gb(freed)} 内存", fg=GREEN)
            else:
                self.freed_lbl.config(text="内存无明显变化", fg=FG_DIM)

    # ---------- 屏幕容器 ----------
    def _build_screens(self):
        self.content = tk.Frame(self, bg=BG_MAIN)
        self.content.pack(fill="both", expand=True)
        self.content_h = WIN_H - TOPBAR_H - LOG_H
        self.screens = {}
        for key in ("home", "platform", "panel"):
            f = tk.Frame(self.content, bg=BG_MAIN)
            f.place(x=0, y=0, width=WIN_W, height=self.content_h)
            self.screens[key] = f

    def show_screen(self, key, slide=True):
        self._current_screen = key
        for k, f in self.screens.items():
            if k != key:
                f.place_forget()
        f = self.screens[key]
        f.place(x=WIN_W if slide else 0, y=0, width=WIN_W, height=self.content_h)
        self._build_if_needed(key)
        if slide:
            self._slide(f, WIN_W, 0)

    def _slide(self, f, x, target):
        if x <= target:
            f.place_configure(x=target)
            return
        step = max(40, (x - target) // 6)
        f.place_configure(x=x - step)
        self.after(8, lambda: self._slide(f, x - step, target))

    def _build_if_needed(self, key):
        if getattr(self, f"_built_{key}", False):
            return
        setattr(self, f"_built_{key}", True)
        if key == "home":
            self._build_home()
        elif key == "platform":
            self._build_platform()
        elif key == "panel":
            self._build_panel()

    # ---------- 呼吸灯 ----------
    def _pulse(self):
        self._pulse_phase += 0.12
        v = (math.sin(self._pulse_phase) + 1) / 2
        r = int(3 + v * 3)
        col = _hex(_lerp((0x00, 0xE6, 0x76), (0x3A, 0xFF, 0x8F), v))
        self.status_dot.coords(self._dot, 8 - r, 8 - r, 8 + r, 8 + r)
        self.status_dot.itemconfig(self._dot, fill=col)
        self.after(40, self._pulse)

    # ---------- 内存刷新 ----------
    def _refresh_memory(self):
        pct, avail, total = ram_percent()
        if hasattr(self, "needle"):
            self._draw_needle(180 - (pct / 100) * 180)
            self.gauge.itemconfig(self.mem_val, text=f"{pct}%")
            self.gauge.itemconfig(self.mem_sub, text=f"{fmt_gb(total - avail)} / {fmt_gb(total)} 已用")
        if hasattr(self, "ring") and self.active_platform:
            self._draw_ring(pct)
            self._ring_val.config(text=f"{pct}%")
        self.after(2000, self._refresh_memory)

    # ---------- L1 主界面 ----------
    def _build_home(self):
        f = self.screens["home"]
        self.gauge = tk.Canvas(f, width=380, height=self.content_h, highlightthickness=0)
        self.gauge.place(x=0, y=0)
        draw_vgradient(self.gauge, 380, self.content_h, (0x0E, 0x12, 0x17), (0x07, 0x0A, 0x0E))
        self._draw_gauge()
        self.needle = None

        right = tk.Frame(f, bg=BG_MAIN)
        right.place(x=410, y=24, width=370, height=self.content_h - 24)
        tk.Label(right, text="选择模式", bg=BG_MAIN, fg=FG_DIM, font=self._f_dim).pack(pady=(0, 10))
        self._btn_live = self._flat_btn(right, "直播模式", lambda: self.show_screen("platform"), RED, FG)
        self._btn_live.pack(fill="x", pady=7)
        self._btn_extreme = self._flat_btn(right, "极限清理", self._extreme_cleanup, AMBER, "#111")
        self._btn_extreme.pack(fill="x", pady=7)
        self._btn_normal = self._flat_btn(right, "正常模式", self._do_normal, PANEL, FG)
        self._btn_normal.pack(fill="x", pady=7)
        self._btn_office = self._flat_btn(right, "办公模式", self._do_office, PANEL, FG)
        self._btn_office.pack(fill="x", pady=7)
        tk.Label(right, text="直播 = 清场 + 拉起平台\n极限 = 停掉所有非必要进程(预览+倒计时)\n正常 = 不干预\n办公 = 杀游戏、留办公\n配置：编辑 config.json",
                 bg=BG_MAIN, fg=FG_MUT, font=self._f_small, justify="left").pack(pady=(12, 0), anchor="w")

    def _draw_gauge(self):
        c = self.gauge
        cx, cy, r = 190, 150, 95
        c.create_arc(cx - r, cy - r, cx + r, cy + r, start=180, extent=180, style="arc", outline=PANEL, width=15)
        for i in range(0, 101, 10):
            ang = 180 - (i / 100) * 180
            a = math.radians(ang)
            x1 = cx + (r - 16) * math.cos(a); y1 = cy - (r - 16) * math.sin(a)
            x2 = cx + (r - 6) * math.cos(a);  y2 = cy - (r - 6) * math.sin(a)
            c.create_line(x1, y1, x2, y2, fill=FG_DIM, width=2)
        self.mem_val = c.create_text(cx, cy + 18, text="--%", fill=FG, font=self._f_big)
        self.mem_sub = c.create_text(cx, cy + 52, text="", fill=FG_DIM, font=self._f_small)
        c.create_text(cx, cy + r + 22, text="内存占用", fill=FG_MUT, font=self._f_small)
        self._gauge_c = (cx, cy, r)

    def _draw_needle(self, ang):
        if self.needle:
            self.gauge.delete(self.needle)
        cx, cy, r = self._gauge_c
        a = math.radians(ang)
        x2 = cx + (r - 26) * math.cos(a); y2 = cy - (r - 26) * math.sin(a)
        self.needle = self.gauge.create_line(cx, cy, x2, y2, fill=RED_HI, width=4)
        self.gauge.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill=RED, outline="")

    # ---------- L2 平台选择 ----------
    def _build_platform(self):
        f = self.screens["platform"]
        cv = tk.Canvas(f, width=WIN_W, height=self.content_h, highlightthickness=0)
        cv.place(x=0, y=0)
        self._card_cv = cv
        draw_vgradient(cv, WIN_W, self.content_h, (0x0E, 0x12, 0x17), (0x07, 0x0A, 0x0E))
        cv.create_text(22, 22, text="直播模式 · 选择游戏平台", anchor="w", fill=FG, font=self._f_btn)
        back = cv.create_text(700, 22, text="‹ 返回", anchor="e", fill=FG_DIM, font=self._f_dim)
        cv.tag_bind(back, "<Button-1>", lambda e: self.show_screen("home"))
        redetect = cv.create_text(774, 22, text="重新检测", anchor="e", fill=FG_DIM, font=self._f_dim)
        cv.tag_bind(redetect, "<Button-1>", lambda e: self._run_async(self._do_redetect))

        self._card_rects = []
        self._card_ids = []
        cols = 4
        card_w, card_h = 176, 100
        gap_x, gap_y = 12, 12
        start_x, start_y = 20, 50
        for i, l in enumerate(self._launchers[:12]):
            col, row = i % cols, i // cols
            x = start_x + col * (card_w + gap_x)
            y = start_y + row * (card_h + gap_y)
            self._draw_card(cv, x, y, card_w, card_h, l["name"], i)
        cv.bind("<Motion>", self._on_card_motion)
        cv.bind("<Leave>", lambda e: self._set_card_hover(None))

    def _draw_card(self, cv, x, y, w, h, name, idx):
        r = 5
        tag = f"card{idx}"
        cv.create_polygon(round_rect_pts(x + 3, y + 5, x + w + 3, y + h + 5, r), fill=SHADOW, smooth=True, outline="", tags=tag)
        card_id = cv.create_polygon(round_rect_pts(x, y, x + w, y + h, r), fill=CARD, smooth=True, outline=EDGE, width=1, tags=tag)
        cv.create_line(x + r, y + 1, x + w - r, y + 1, fill=EDGE_HI, width=1, tags=tag)
        img = self.icons.get(name)
        if img:
            cv.create_image(x + w // 2, y + 32, image=img, tags=tag)
        else:
            glyph = "✕" if name == "Xbox" else name[0]
            cv.create_text(x + w // 2, y + 32, text=glyph, fill=RED_HI if name == "Xbox" else FG,
                           font=self._f_big, tags=tag)
        cv.create_text(x + w // 2, y + h - 18, text=name, fill=FG, font=self._f_btn, tags=tag)
        cv.tag_bind(tag, "<Button-1>", lambda e, n=name: self._enter_platform(n))
        self._card_rects.append((x, y, w, h))
        self._card_ids.append(card_id)

    def _on_card_motion(self, event):
        x, y = event.x, event.y
        cur = None
        for i, (cx, cy, cw, ch) in enumerate(self._card_rects):
            if cx <= x <= cx + cw and cy <= y <= cy + ch:
                cur = i
                break
        self._set_card_hover(cur)

    def _set_card_hover(self, idx):
        if self._hover_idx == idx:
            return
        if self._hover_idx is not None:
            self._card_cv.itemconfig(self._card_ids[self._hover_idx], fill=CARD, outline=EDGE)
        self._hover_idx = idx
        if idx is not None:
            self._card_cv.itemconfig(self._card_ids[idx], fill=CARD_HI, outline=RED_HI)

    # ---------- L3 平台面板 ----------
    def _build_panel(self):
        f = self.screens["panel"]
        self.panel_title = tk.Label(f, text="", bg=BG_MAIN, fg=FG, font=self._f_title)
        self.panel_title.place(x=20, y=10)
        back = self._flat_btn(f, "‹ 返回平台", self._back_to_platform, PANEL, FG_DIM, self._f_dim, padx=10, pady=5)
        back.place(x=690, y=6)

        self.launch_btn = tk.Button(f, text="启动平台", command=self._launch_current,
                                    bg=RED, fg=FG, activebackground=RED_HI, activeforeground="#000",
                                    font=self._f_big, relief="flat", bd=0, cursor="hand2", width=11, height=2)
        self.launch_btn.place(relx=0.5, rely=0.30, anchor="center")

        self.freed_lbl = tk.Label(f, text="", bg=BG_MAIN, fg=GREEN, font=self._f_btn)
        self.freed_lbl.place(x=0, y=172, width=WIN_W)

        self.timer_lbl = tk.Label(f, text="00:00:00", bg=BG_MAIN, fg=RED_HI, font=self._f_timer)
        self.timer_lbl.place(x=0, y=218, width=WIN_W)
        tk.Label(f, text="本次游戏时长", bg=BG_MAIN, fg=FG_DIM, font=self._f_small).place(x=0, y=283, width=WIN_W)

        self.exit_btn = self._flat_btn(f, "退出模式", self._confirm_exit, RED_DK, FG, self._f_btn, padx=16, pady=8)
        self.exit_btn.place(x=650, y=330)

        self.ring = tk.Canvas(f, width=110, height=110, bg=BG_MAIN, highlightthickness=0)
        self.ring.place(x=50, y=45)
        self._ring_val = tk.Label(f, text="", bg=BG_MAIN, fg=FG, font=self._f_dim)
        self._ring_val.place(x=50, y=88, width=110)

    def _draw_ring(self, pct):
        c = self.ring
        c.delete("all")
        cx = cy = 55; r = 45
        c.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=-360, style="arc", outline=PANEL, width=10)
        ext = -int(360 * pct / 100)
        c.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=ext, style="arc", outline=RED_HI, width=10)

    # ---------- 模式逻辑 ----------
    def _enter_platform(self, name):
        same = (name == self.active_platform and self.current_mode == "直播")
        self.active_platform = name
        self.current_mode = "直播"
        self._set_mode_label(f"直播 · {name}", RED_HI)
        if not same:
            self.timer_sec = 0
        self.show_screen("panel")
        self.panel_title.config(text=f"直播模式 · {name}")
        self._update_timer()
        if same:
            self._log(f"已回到 {name}，游戏计时继续")
        else:
            if hasattr(self, "freed_lbl"):
                self.freed_lbl.config(text="等待确认清场...", fg=FG_DIM)
            self._confirm_live_kill(name)

    def _back_to_platform(self):
        """返回平台页：不退出模式、不停表，游戏继续。"""
        self.show_screen("platform")

    def _measure_kill_freed(self, names):
        """清理进程，返回 (成功清理数, 释放字节数)。"""
        return kill_procs(self._effective_kill(names))

    def _live_kill_targets(self, name):
        procs = next((l.get("processes") or [] for l in self._launchers if l["name"] == name), [])
        own = {p.lower() for p in procs if isinstance(p, str)}
        kill_other = [
            p for p in self._all_platform_procs()
            if isinstance(p, str) and p.lower() not in own
        ]
        return list(dict.fromkeys(kill_other + self.kill_list))

    def _confirm_live_kill(self, name):
        requested = self._live_kill_targets(name)
        listed = "\n".join(f"• {p}" for p in requested) or "（没有配置待清理进程）"
        ok = messagebox.askyesno(
            "确认直播清场",
            f"进入 {name} 前将尝试清理以下进程：\n\n{listed}\n\n"
            "请确认这些进程没有未保存内容、上传或下载任务。",
            parent=self,
        )
        if ok:
            self._run_async(self._do_live_kill, name, requested)
        else:
            self._log(f"已取消 {name} 的直播清场")
            if hasattr(self, "freed_lbl"):
                self.freed_lbl.config(text="已取消清场", fg=FG_DIM)

    def _do_live_kill(self, name, requested=None):
        requested = self._live_kill_targets(name) if requested is None else requested
        n, freed = self._measure_kill_freed(requested)
        self._ui_queue.put(("freed", freed))
        delta = f"，释放 {fmt_gb(freed)} 内存" if freed > 50 * 1024 * 1024 else "，内存无明显变化"
        listed = ", ".join(dict.fromkeys(requested)) or "无"
        self._ui_queue.put(("log", f"已清场 {n} 个进程（请求：{listed}；保留 {name}）{delta} · 点「启动平台」拉起"))

    def _launch_current(self):
        if not self.active_platform:
            return
        name = self.active_platform
        path = next((l.get("path") for l in self._launchers if l["name"] == name), None)
        self._log(f"正在启动 {name} ...")
        ok, msg = launch(path)
        self._log(f"{name} {msg}" + (" ✓" if ok else " ✗"))
        if ok:
            self._start_timer()

    # ---------- 计时 ----------
    def _start_timer(self):
        if self._timer_id is None:
            self._timer_id = self.after(1000, self._tick)

    def _tick(self):
        self.timer_sec += 1
        self._update_timer()
        self._timer_id = self.after(1000, self._tick)

    def _update_timer(self):
        h, rem = divmod(self.timer_sec, 3600)
        m, s = divmod(rem, 60)
        self.timer_lbl.config(text=f"{h:02d}:{m:02d}:{s:02d}")

    def _stop_timer(self):
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None

    # ---------- 退出 / 正常 / 办公 ----------
    def _confirm_exit(self):
        top = tk.Toplevel(self)
        top.title("确认")
        top.configure(bg=PANEL)
        top.resizable(False, False)
        top.attributes("-topmost", True)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        top.geometry(f"360x140+{(sw - 360) // 2}+{(sh - 140) // 2}")
        tk.Label(top, text="确认退出当前模式？", bg=PANEL, fg=FG, font=self._f_btn).pack(pady=16)
        tk.Label(top, text="（游戏继续保留，仅结束计时并返回）", bg=PANEL, fg=FG_DIM, font=self._f_small).pack()
        row = tk.Frame(top, bg=PANEL)
        row.pack(pady=12)
        tk.Button(row, text="取消", command=top.destroy, bg=PANEL, fg=FG, font=self._f_dim,
                  relief="flat", padx=18, pady=6, cursor="hand2").pack(side="left", padx=8)
        tk.Button(row, text="确认退出", command=lambda: (top.destroy(), self._exit_panel()),
                  bg=RED, fg=FG, font=self._f_btn, relief="flat", padx=18, pady=6, cursor="hand2").pack(side="left", padx=8)

    def _exit_panel(self):
        self._stop_timer()
        self._set_mode_label("正常模式", FG_DIM)
        self.current_mode = "正常"
        self.active_platform = None
        self.show_screen("platform")

    def _do_normal(self):
        self._stop_timer()
        self.current_mode = "正常"
        self._set_mode_label("正常模式", FG_DIM)
        self._log("正常模式：不干预，保持现状")

    def _do_office(self):
        self._stop_timer()
        self.current_mode = "办公"
        self._set_mode_label("办公模式", AMBER)
        self._run_async(self._office_kill)

    def _office_kill(self):
        n, freed = self._measure_kill_freed(self._all_platform_procs() + self.kill_list)
        self._ui_queue.put(("freed", freed))
        delta = f"，释放 {fmt_gb(freed)} 内存" if freed > 50 * 1024 * 1024 else ""
        self._ui_queue.put(("log", f"办公模式：已清理 {n} 个进程{delta}"))

    # ---------- 极限清理（保留主要进程，其余大力停止） ----------
    def _extreme_cleanup(self):
        self._log("正在检测可清理进程...")
        self._run_async(self._do_extreme_detect)

    def _do_extreme_detect(self):
        cands = detect_cleanable(self.keep_list)
        self._ui_queue.put(("extreme_preview", cands, sum(c[2] for c in cands)))

    def _show_extreme_preview(self, cands, total_mb):
        if not cands:
            self._log("极限清理：没有可清理的进程")
            return
        self._pending_extreme = cands
        top = tk.Toplevel(self)
        top.title("极限清理 · 预览")
        top.configure(bg=PANEL)
        top.resizable(False, False)
        top.attributes("-topmost", True)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = 470, 440
        top.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        tk.Label(top, text=f"将停止 {len(cands)} 个进程 · 释放约 {total_mb / 1024:.1f}G",
                 bg=PANEL, fg=RED_HI, font=self._f_btn).pack(pady=(14, 2))
        tk.Label(top, text="系统/驱动/反作弊/输入法/安全软件/VPN 已自动保护",
                 bg=PANEL, fg=FG_MUT, font=self._f_small).pack(pady=(0, 8))
        box = tk.Frame(top, bg=PANEL)
        box.pack(fill="both", expand=True, padx=16)
        sb = tk.Scrollbar(box)
        lst = tk.Listbox(box, bg=BG_MAIN, fg=FG_DIM, font=self._f_small,
                         selectmode="none", yscrollcommand=sb.set,
                         highlightthickness=0, bd=0)
        sb.config(command=lst.yview)
        for name, pid, mb in cands:
            lst.insert("end", f"  {name:<30} {mb:>6}MB  (PID {pid})")
        lst.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        row = tk.Frame(top, bg=PANEL)
        row.pack(pady=12)
        tk.Button(row, text="取消", command=top.destroy, bg=PANEL, fg=FG,
                  font=self._f_dim, relief="flat", padx=20, pady=7,
                  cursor="hand2").pack(side="left", padx=10)
        tk.Button(row, text="确认清理 →",
                  command=lambda: (top.destroy(), self._start_extreme_countdown()),
                  bg=RED, fg=FG, font=self._f_btn, relief="flat", padx=20, pady=7,
                  cursor="hand2").pack(side="left", padx=10)

    def _start_extreme_countdown(self):
        if not getattr(self, "_pending_extreme", None):
            return
        top = tk.Toplevel(self)
        top.title("极限清理")
        top.configure(bg=PANEL)
        top.resizable(False, False)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        top.geometry(f"430x170+{(sw - 430) // 2}+{(sh - 170) // 2}")
        remain = [int(self.cfg.get("cleanup_delay_sec", 10))]
        self._cd_active = True
        lbl = tk.Label(top, text=f"{remain[0]} 秒后开始清理", bg=PANEL, fg=AMBER, font=self._f_big)
        lbl.pack(pady=(22, 6))
        tk.Label(top, text="立即保存浏览器 / 文档内容！", bg=PANEL, fg=FG, font=self._f_btn).pack()
        row = tk.Frame(top, bg=PANEL)
        row.pack(pady=14)

        def cancel():
            self._cd_active = False
            top.destroy()

        def go():
            if not self._cd_active:
                return
            self._cd_active = False
            top.destroy()
            self._run_async(self._execute_extreme)

        def tick():
            if not self._cd_active:
                return
            remain[0] -= 1
            if remain[0] <= 0:
                go()
                return
            lbl.config(text=f"{remain[0]} 秒后开始清理")
            top.after(1000, tick)

        top.after(1000, tick)
        tk.Button(row, text="取消", command=cancel, bg=PANEL, fg=FG, font=self._f_dim,
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left", padx=8)
        tk.Button(row, text="立即执行", command=go, bg=RED, fg=FG, font=self._f_btn,
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left", padx=8)

    def _execute_extreme(self):
        cands = getattr(self, "_pending_extreme", None)
        if not cands:
            return
        n, freed = kill_procs_by_pid([(c[0], c[1]) for c in cands])
        try:
            logp = os.path.join(config.app_dir(), "cleanup_log.txt")
            with open(logp, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} 极限清理：停止 {n} 个进程，释放约 {freed // 1048576}MB\n")
                for name, pid, mb in cands:
                    f.write(f"    {name}  PID {pid}  {mb}MB\n")
        except Exception:
            pass
        self._pending_extreme = None
        self._ui_queue.put(("freed", freed))
        if n:
            self._ui_queue.put(("log", f"极限清理完成：停止 {n} 个进程，释放 {fmt_gb(freed)} 内存"))
        else:
            self._ui_queue.put(("log", "极限清理：没有进程被停止"))


def main():
    cfg = config.load_config()
    if cfg.get("auto_detect", True):
        try:
            detected = launchers.detect_launchers()
            merged = launchers.merge_launchers(cfg["launchers"], detected)
            if merged != cfg["launchers"]:
                cfg["launchers"] = merged
                config.save_config(cfg)
        except Exception:
            pass
    App(cfg).mainloop()


if __name__ == "__main__":
    main()
