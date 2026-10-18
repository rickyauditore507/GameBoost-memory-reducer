# -*- coding: utf-8 -*-
"""
GameBoost · 启动器自动检测 + 图标提取（仅 Windows）

检测顺序（每种启动器）：
  1. 注册表（安装路径键）
  2. 卸载表（DisplayName 匹配 → 安装目录递归找 / DisplayIcon 文件名匹配）
  3. 常见安装路径
  4. 开始菜单快捷方式（.lnk 目标文件名匹配）

图标：从检测到的 exe 用 System.Drawing 提取为 PNG，缓存到 icons_cache/。
"""
import fnmatch
import hashlib
import os
import subprocess
import winreg

# 每个规则：name 显示名 / reg 注册表 / uninstall 卸载表匹配 / paths 常见路径 /
#           exe_pats 可执行文件名匹配 / processes 该平台进程名
LAUNCHER_SPECS = [
    {
        "name": "Steam",
        "reg": [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath", r"\steam.exe"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath", r"\steam.exe"),
        ],
        "uninstall": ["steam"],
        "paths": [
            r"C:\Program Files (x86)\Steam\steam.exe",
            r"D:\Steam\steam.exe", r"E:\Steam\steam.exe",
            r"F:\Steam\steam.exe", r"G:\Steam\steam.exe",
        ],
        "exe_pats": ["steam.exe"],
        "processes": ["steam.exe", "steamwebhelper.exe"],
    },
    {
        "name": "Epic Games",
        "reg": [],
        "uninstall": ["epic games launcher"],
        "paths": [
            r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
            r"D:\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
            r"E:\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
        ],
        "exe_pats": ["EpicGamesLauncher.exe"],
        "processes": ["EpicGamesLauncher.exe", "EpicWebHelper.exe"],
    },
    {
        "name": "暴雪战网 Battle.net",
        "reg": [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Battle.net\Client", "InstallPath", r"\Battle.net.exe"),
        ],
        "uninstall": ["battle.net"],
        "paths": [
            r"C:\Program Files (x86)\Battle.net\Battle.net.exe",
            r"D:\Battle.net\Battle.net.exe", r"E:\Battle.net\Battle.net.exe",
        ],
        "exe_pats": ["Battle.net.exe", "Battle.net Launcher.exe"],
        "processes": ["Battle.net.exe"],
    },
    {
        "name": "Ubisoft Connect",
        "reg": [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Ubisoft\Launcher", "InstallDir", r"\UbisoftGameLauncher.exe"),
        ],
        "uninstall": ["ubisoft connect", "uplay"],
        "paths": [
            r"C:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\UbisoftConnect.exe",
            r"C:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\upc.exe",
            r"D:\Ubisoft Game Launcher\UbisoftConnect.exe",
        ],
        "exe_pats": ["UbisoftConnect.exe", "UbisoftGameLauncher.exe", "upc.exe"],
        "processes": ["UbisoftConnect.exe", "upc.exe", "UbisoftGameLauncher.exe"],
    },
    {
        "name": "EA app",
        "reg": [],
        "uninstall": ["ea app", "origin"],
        "paths": [
            r"C:\Program Files\Electronic Arts\EA Desktop\EA Desktop\EADesktop.exe",
            r"C:\Program Files\EA Games\EADesktop\EADesktop.exe",
            r"C:\Program Files (x86)\Origin\Origin.exe",
        ],
        "exe_pats": ["EADesktop.exe", "Origin.exe"],
        "processes": ["EADesktop.exe", "Origin.exe"],
    },
    {
        "name": "GOG Galaxy",
        "reg": [],
        "uninstall": ["gog galaxy"],
        "paths": [
            r"C:\Program Files (x86)\GOG Galaxy\GalaxyClient.exe",
            r"D:\GOG Galaxy\GalaxyClient.exe",
        ],
        "exe_pats": ["GalaxyClient.exe"],
        "processes": ["GalaxyClient.exe"],
    },
    {
        "name": "腾讯 WeGame",
        "reg": [],
        "uninstall": ["wegame"],
        "paths": [
            r"C:\Program Files (x86)\WeGame\wegame.exe",
            r"D:\WeGame\wegame.exe", r"E:\WeGame\wegame.exe", r"F:\WeGame\wegame.exe",
        ],
        "exe_pats": ["wegame.exe", "WeGame.exe"],
        "processes": ["wegame.exe", "wegameservice.exe", "WeGameOverlayHost.exe"],
    },
    {
        "name": "PCL2 (我的世界)",
        "reg": [],
        "uninstall": [],
        "paths": [],
        "exe_pats": ["Plain Craft Launcher*.exe", "PCL*.exe"],
        "processes": ["Plain Craft Launcher 2.exe"],
    },
    {
        "name": "HMCL (我的世界)",
        "reg": [],
        "uninstall": [],
        "paths": [],
        "exe_pats": ["HMCL*.exe"],
        "processes": ["HMCL.exe"],
    },
    {
        "name": "BakaXL (我的世界)",
        "reg": [],
        "uninstall": [],
        "paths": [],
        "exe_pats": ["BakaXL*.exe"],
        "processes": ["BakaXL.exe"],
    },
]

XBOX_NAME = "Xbox"
XBOX_SHELL = "shell:AppsFolder\\Microsoft.GamingApp_8wekyb3d8bbwe!App"

# PowerShell 强制 UTF-8 输出（避免中文在重定向时被吞）
_PS_UTF8 = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "


def _run_ps(script, timeout=30):
    """跑 PowerShell，返回按 UTF-8 解码的 stdout 字符串。"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", _PS_UTF8 + script],
                           capture_output=True, timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return (r.stdout or b"").decode("utf-8", errors="replace")
    except Exception:
        return ""


# ---------- 注册表 / 卸载表 ----------
def _reg_exe(hive, key, value, suffix):
    try:
        with winreg.OpenKey(hive, key) as k:
            v, _ = winreg.QueryValueEx(k, value)
        if v:
            p = str(v).rstrip("\\/")
            p = os.path.join(p, suffix.lstrip("\\/")) if suffix else p
            p = os.path.normpath(p)
            if os.path.exists(p):
                return p
    except OSError:
        pass
    return None


def _scan_uninstall():
    """扫卸载表，返回 {DisplayName小写: (DisplayIcon, InstallLocation)}。"""
    result = {}
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, base in roots:
        try:
            with winreg.OpenKey(hive, base) as root:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(root, i)
                        i += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(hive, base + "\\" + sub) as k:
                            def qv(n):
                                try:
                                    v, _ = winreg.QueryValueEx(k, n)
                                    return str(v)
                                except OSError:
                                    return ""
                            name = qv("DisplayName")
                            if name:
                                result[name.lower()] = (qv("DisplayIcon"), qv("InstallLocation"))
                    except OSError:
                        pass
        except OSError:
            pass
    return result


def _clean_icon_path(icon):
    """DisplayIcon 形如 "C:\\path\\app.exe,0" → 取 exe 路径（需存在）。"""
    if not icon:
        return None
    p = icon.strip().strip('"')
    if "," in p:
        p = p.split(",")[0]
    if p.lower().endswith(".exe") and os.path.exists(p):
        return p
    return None


def _find_exe_in_dir(loc, exe_pats, maxdepth=8):
    """在安装目录下递归（限深度）找 exe_pats 匹配的文件，偏好 Portal/Win64。"""
    if not loc or not os.path.isdir(loc):
        return None
    loc = os.path.abspath(loc)
    base_depth = loc.rstrip("\\/").count(os.sep)
    matches = []
    for dp, dns, fns in os.walk(loc):
        if dp.rstrip("\\/").count(os.sep) - base_depth > maxdepth:
            dns[:] = []
            continue
        for f in fns:
            fl = f.lower()
            for pat in exe_pats:
                if ("*" in pat and fnmatch.fnmatch(fl, pat.lower())) or fl == pat.lower():
                    matches.append(os.path.join(dp, f))
    if not matches:
        return None

    def rank(p):
        pl = p.lower()
        score = 0
        if "portal" in pl:
            score += 2
        if "win64" in pl:
            score += 1
        if "win32" in pl:
            score -= 1
        return -score

    matches.sort(key=rank)
    return matches[0]


def _match_uninstall(frag, uninstall_map):
    """DisplayName == frag 或以 'frag ' 开头（避免 'steam' 误配 SteamVR）。"""
    for name, (icon, loc) in uninstall_map.items():
        if name == frag or name.startswith(frag + " "):
            return icon, loc
    return None, None


# ---------- 开始菜单 .lnk ----------
def _scan_startmenu():
    """一次 PowerShell 调用，返回 {exe文件名小写: 完整路径}。"""
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$dirs = @(\"$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\", "
        "\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\"); "
        "foreach ($d in $dirs) { if (Test-Path $d) { "
        "Get-ChildItem $d -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object { "
        "try { $t = $ws.CreateShortcut($_.FullName).TargetPath; "
        "if ($t) { Write-Output ($_.FullName + [char]9 + $t) } } catch {} } } }"
    )
    mapping = {}
    for line in _run_ps(ps).splitlines():
        if "\t" in line:
            _, target = line.split("\t", 1)
            t = target.strip().strip('"').lower()
            if t.endswith(".exe") and os.path.exists(t):
                mapping[os.path.basename(t)] = t
    return mapping


def _xbox_available():
    return "YES" in _run_ps("if (Get-AppxPackage -Name Microsoft.GamingApp) { 'YES' }", timeout=20)


# ---------- 主检测 ----------
def detect_launchers():
    """检测已安装的启动器 → {名称: {"path":..., "processes":[...]}}。"""
    found = {}
    uninstall_map = _scan_uninstall()
    startmenu = _scan_startmenu()

    for spec in LAUNCHER_SPECS:
        path = None
        # 1. 注册表
        for hive, key, value, suffix in spec["reg"]:
            path = _reg_exe(hive, key, value, suffix)
            if path:
                break
        # 2. 卸载表：先安装目录递归找，再 DisplayIcon（文件名必须匹配）
        if not path:
            for frag in spec["uninstall"]:
                icon, loc = _match_uninstall(frag, uninstall_map)
                path = _find_exe_in_dir(loc, spec["exe_pats"])
                if not path:
                    icon_path = _clean_icon_path(icon)
                    if icon_path:
                        base = os.path.basename(icon_path).lower()
                        for pat in spec["exe_pats"]:
                            if fnmatch.fnmatch(base, pat.lower()):
                                path = icon_path
                                break
                if path:
                    break
        # 3. 常见路径
        if not path:
            for p in spec["paths"]:
                if os.path.exists(p):
                    path = os.path.normpath(p)
                    break
        # 4. 开始菜单快捷方式
        if not path:
            for pat in spec["exe_pats"]:
                for base, target in startmenu.items():
                    if fnmatch.fnmatch(base, pat.lower()):
                        path = target
                        break
                if path:
                    break

        if path:
            found[spec["name"]] = {"path": path, "processes": list(spec["processes"])}

    # Xbox（UWP）
    if _xbox_available():
        found[XBOX_NAME] = {"path": XBOX_SHELL, "processes": ["GameBar.exe"]}

    return found


# ---------- 合并配置 ----------
def merge_launchers(existing, detected):
    """保留用户配置，并刷新失效的 detected 启动器路径。"""
    result = []
    seen = set()
    for e in existing:
        if isinstance(e, dict) and e.get("name"):
            item = dict(e)
            name = e["name"]
            info = detected.get(name)
            source = e.get("source", "detected")
            old_path = e.get("path") or ""
            old_exists = old_path.startswith("shell:") or os.path.exists(old_path)
            new_path = info.get("path") if isinstance(info, dict) else None
            new_exists = bool(new_path) and (new_path.startswith("shell:") or os.path.exists(new_path))
            if (source == "detected" and info and not old_exists
                    and new_exists):
                item["path"] = new_path
                item["processes"] = list(info.get("processes") or [])
            result.append(item)
            seen.add(name)
    for name, info in detected.items():
        if name not in seen:
            result.append({
                "name": name,
                "path": info["path"],
                "processes": list(info["processes"]),
                "enabled": True,
                "source": "detected",
            })
    return result


# ---------- 图标 ----------
def extract_icon(exe_path, cache_dir, size=48):
    """提取 exe 图标 → PNG（缓存）。返回 PNG 路径或 None。"""
    if not exe_path or exe_path.startswith("shell:"):
        return None
    if not os.path.exists(exe_path):
        return None
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.md5(exe_path.encode("utf-8")).hexdigest()[:12]
    out = os.path.join(cache_dir, key + ".png")
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    exe_q = exe_path.replace("'", "''")
    out_q = out.replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Drawing; "
        f"$ic = [System.Drawing.Icon]::ExtractAssociatedIcon('{exe_q}'); "
        f"$bmp = New-Object System.Drawing.Bitmap($ic.ToBitmap(), {size}, {size}); "
        f"$bmp.Save('{out_q}', [System.Drawing.Imaging.ImageFormat]::Png)"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", _PS_UTF8 + ps],
                       capture_output=True, text=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return out
    except Exception:
        pass
    return None
