# -*- coding: utf-8 -*-
"""
GameBoost · 配置模块
config.json 与程序（脚本/EXE）同目录，首次运行自动生成，用户可直接编辑。
"""
import json
import os
import sys

APP_NAME = "GameBoost"
VERSION = "1.1.1"

DEFAULT_CONFIG = {
    "version": 3,
    # 每次启动是否自动检测新安装的启动器并合并进配置
    "auto_detect": True,
    # 启动器列表：{"name", "path", "processes", "enabled", "source"}
    "launchers": [],
    # 模式切换时清理的进程名（可编辑，建议只放明显无用的常驻软件）
    "kill_list": [
        "Doubao.exe", "aha_doctor.exe",
        "BaiduNetdisk.exe", "BaiduNetdiskHost.exe",
        "Thunder.exe", "ThunderPlatform.exe",
        "ldnews.exe", "QuarkCloudDrive.exe",
    ],
    # 永不清理（子串匹配，不区分大小写）——也是「极限清理」的白名单
    # 已覆盖：桌面外壳/输入法/搜索/安全软件/反作弊/鼠标宏/显卡与音频/
    #        Twinkle Tray/Discord/postgresql/Hermes/OBS/抖音直播/VPN/微信
    "keep_list": [
        "explorer", "ctfmon", "dwm", "sihost", "taskhostw", "runtimebroker",
        "textinputhost", "fontdrvhost", "searchhost", "searchindexer", "searchapp",
        "startmenuexperiencehost", "shellhost", "applicationframehost", "securityhealth",
        "msseces", "defender", "hudun", "zhudongfangyu", "360tray", "avgnt", "kaspersky",
        "ace-tray", "anticheat", "easyanticheat", "vanguard", "battleye", "faceit",
        "razer", "em915", "twinkle", "discord", "postgres", "hermes", "python",
        "gameboost", "obs", "douyin", "clash", "mihomo", "v2ray", "sogou",
        "conhost", "audiodg", "rdpclip", "widgets", "windowsinternal",
        "radeon", "amd",
    ],
    # 「极限清理」确认后的倒计时秒数（给用户保存浏览器/文档的时间）
    "cleanup_delay_sec": 10,
}


def app_dir():
    """程序所在目录：打包后 = EXE 目录，脚本运行 = 脚本目录。"""
    if getattr(sys, "frozen", False):  # PyInstaller
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def config_path():
    return os.path.join(app_dir(), "config.json")


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    user = {}
    if os.path.exists(config_path()):
        try:
            with open(config_path(), "r", encoding="utf-8") as f:
                user = json.load(f)
        except Exception:
            user = {}
    cfg.update(user)
    if user.get("version", 1) < 3:  # v2→v3：白名单补 AMD 驱动组件等，合并用户自定义
        defaults = DEFAULT_CONFIG["keep_list"]
        cfg["keep_list"] = list(defaults) + [k for k in (cfg.get("keep_list") or []) if k not in defaults]
        cfg["version"] = 3
        save_config(cfg)
    return cfg


def save_config(cfg):
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
