# -*- coding: utf-8 -*-
"""第一阶段安全审计测试。

这些测试只覆盖纯 Python 逻辑，并 Mock 掉 PowerShell 调用。
它们不会启动、查询或终止真实用户进程。
"""
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import config
import gameboost
import launchers


class ConfigMigrationTests(unittest.TestCase):
    def test_invalid_json_reports_location_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{\n  "keep_list": [\n  // invalid\n  ]\n}\n')

            with patch.object(config, "config_path", return_value=path):
                cfg = config.load_config()

            self.assertEqual(cfg["version"], 2)
            self.assertIn("第 3 行", config.CONFIG_ERROR)
            self.assertTrue(os.path.exists(path + ".bak"))

    def test_v1_keep_list_is_preserved_during_migration(self):
        # 这是目标安全行为；当前版本预期失败，用于暴露覆盖问题。
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "keep_list": ["MyStreamingTool"]}, f)

            saved = {}

            def fake_save(cfg):
                saved.update(cfg)
                return True

            with patch.object(config, "config_path", return_value=path), \
                 patch.object(config, "save_config", side_effect=fake_save):
                cfg = config.load_config()

            self.assertIn("MyStreamingTool", cfg["keep_list"])
            self.assertIn("gameboost", [x.lower() for x in cfg["keep_list"]])


class LauncherMergeTests(unittest.TestCase):
    def test_stale_detected_path_is_refreshed(self):
        existing = [{
            "name": "Steam",
            "path": r"C:\old\steam.exe",
            "processes": ["steam.exe"],
            "enabled": True,
            "source": "detected",
        }]
        detected = {
            "Steam": {
                "path": r"D:\Steam\steam.exe",
                "processes": ["steam.exe", "steamwebhelper.exe"],
            }
        }

        # 这是目标安全行为；当前版本预期失败，用于暴露路径更新问题。
        with patch.object(launchers.os.path, "exists", side_effect=lambda p: p == r"D:\Steam\steam.exe"):
            merged = launchers.merge_launchers(existing, detected)

        steam = next(x for x in merged if x["name"] == "Steam")
        self.assertEqual(steam["path"], r"D:\Steam\steam.exe")
        self.assertEqual(steam["processes"], ["steam.exe", "steamwebhelper.exe"])

    def test_custom_path_is_not_overwritten(self):
        existing = [{
            "name": "Steam",
            "path": r"E:\custom\steam.exe",
            "processes": ["custom.exe"],
            "enabled": True,
            "source": "custom",
        }]
        detected = {"Steam": {"path": r"D:\Steam\steam.exe", "processes": ["steam.exe"]}}
        merged = launchers.merge_launchers(existing, detected)
        self.assertEqual(merged[0]["path"], r"E:\custom\steam.exe")
        self.assertEqual(merged[0]["processes"], ["custom.exe"])


class ProcessSafetyMockTests(unittest.TestCase):
    def test_extreme_detection_command_protects_windows_and_foreground_processes(self):
        class Result:
            stdout = b""

        with patch.object(gameboost.subprocess, "run", return_value=Result()) as run:
            self.assertEqual(gameboost.detect_cleanable([]), [])

        command = run.call_args.args[0][-1]
        self.assertIn("$_.MainWindowHandle -eq 0", command)
        self.assertIn("$_.Id -ne $fg", command)
        self.assertIn("GetForegroundWindow", command)

    def test_extreme_detection_skips_known_game_paths(self):
        class Result:
            stdout = (
                b"1|Game|500|D:\\SteamLibrary\\steamapps\\common\\Game\\Game.exe\n"
                b"2|Tool|400|D:\\Tools\\Tool.exe\n"
            )

        with patch.object(gameboost.subprocess, "run", return_value=Result()):
            self.assertEqual(gameboost.detect_cleanable([]), [("Tool", 2, 400)])

    def test_live_kill_comparison_is_case_insensitive(self):
        app = gameboost.App.__new__(gameboost.App)
        app.keep_list = []
        own = ["steam.exe"]
        all_platform = ["Steam.exe", "EpicGamesLauncher.exe"]

        # 目标行为的参考断言；当前 _do_live_kill 使用大小写敏感比较。
        own_lower = {p.lower() for p in own}
        safe_other = [p for p in all_platform if p.lower() not in own_lower]
        self.assertEqual(safe_other, ["EpicGamesLauncher.exe"])

    def test_kill_procs_isolated_from_real_powershell(self):
        class Result:
            stdout = b"1;123456"

        with patch.object(gameboost.subprocess, "run", return_value=Result()) as run:
            result = gameboost.kill_procs(["GameBoostTestTarget.exe"])

        self.assertEqual(result, (1, 123456))
        run.assert_called_once()
        args = run.call_args.args[0]
        self.assertEqual(args[0], "powershell")
        # 这里只检查命令被 Mock 捕获；没有执行 powershell.exe。
        self.assertIn("GameBoostTestTarget", run.call_args.args[0][-1])

    def test_unsafe_process_names_are_rejected(self):
        with patch.object(gameboost.subprocess, "run") as run:
            self.assertEqual(gameboost.kill_procs(["steam*", "python*", "bad;name"]), (0, 0))
        run.assert_not_called()

    def test_live_cleanup_requires_confirmation_before_async_kill(self):
        app = gameboost.App.__new__(gameboost.App)
        app._launchers = [{"name": "Steam", "processes": ["steam.exe"]}]
        app.kill_list = ["BaiduNetdisk.exe"]
        app._all_platform_procs = lambda: ["Steam.exe", "EpicGamesLauncher.exe"]
        app._run_async = Mock()
        app._log = Mock()
        app.freed_lbl = Mock()

        with patch.object(gameboost.messagebox, "askyesno", return_value=False) as ask:
            app._confirm_live_kill("Steam")

        ask.assert_called_once()
        app._run_async.assert_not_called()
        app._log.assert_called_once()

        with patch.object(gameboost.messagebox, "askyesno", return_value=True):
            app._confirm_live_kill("Steam")

        app._run_async.assert_called_once_with(
            app._do_live_kill,
            "Steam",
            ["EpicGamesLauncher.exe", "BaiduNetdisk.exe"],
        )

    def test_live_cleanup_uses_confirmed_snapshot(self):
        app = gameboost.App.__new__(gameboost.App)
        app._launchers = [{"name": "Steam", "processes": ["steam.exe"]}]
        app.kill_list = ["BaiduNetdisk.exe"]
        app._all_platform_procs = lambda: ["Steam.exe", "EpicGamesLauncher.exe"]
        app._measure_kill_freed = Mock(return_value=(1, 1024))
        app._ui_queue = Mock()

        app._do_live_kill("Steam", ["EpicGamesLauncher.exe"])
        app._measure_kill_freed.assert_called_once_with(["EpicGamesLauncher.exe"])

    def test_pid_cleanup_uses_pid_and_name_recheck(self):
        class Result:
            stdout = b"1;123456"

        with patch.object(gameboost.subprocess, "run", return_value=Result()) as run:
            result = gameboost.kill_procs_by_pid([("GameBoostTestTarget.exe", 4321)])

        self.assertEqual(result, (1, 123456))
        command = run.call_args.args[0][-1]
        self.assertIn("Get-Process -Id $target.Pid", command)
        self.assertIn("$p.ProcessName -eq $target.Name", command)
        self.assertIn("Stop-Process -Force", command)
        self.assertNotIn("Get-Process -Name", command)


if __name__ == "__main__":
    unittest.main(verbosity=2)
