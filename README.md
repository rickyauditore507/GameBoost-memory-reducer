# GameBoost 

这些全是ai写的，其实就是一个内存清理工具，非常暴力，快下载试试吧，求求大佬们给我点反馈

一键进入游戏状态的车机风桌面工具：**清理后台进程 → 拉起游戏平台 → 计时**。

自动检测你电脑上装了哪些游戏启动器，配置全部在 `config.json` 里、随时可改。运行时零第三方依赖，纯 Python 标准库 + tkinter，单文件 EXE 双击即用。

## 功能

- **三种模式**：游戏（选平台 → 勾选预览清理 → 拉起）、办公（杀游戏、留办公）、正常（不干预）
- **极限清理**：停掉所有非必要进程（跨机器自动检测：会话+路径+白名单），预览勾选 + 倒计时保存时间
- **启动器自动检测**：Steam / Epic Games / 暴雪战网 / Ubisoft Connect / EA app / GOG Galaxy / 腾讯 WeGame / Xbox / PCL2 / HMCL / BakaXL
  检测顺序：注册表 → 卸载表 → 常见安装路径 → 开始菜单快捷方式
- **内存释放反馈**：清场前后各测一次内存，界面显示「本次释放 X.XG」
- **进程名单可配置**：`kill_list` 想清什么加什么；`keep_list` 永不误杀
- **车机竞技风 UI**：内存仪表盘（转速表）、倒角+阴影卡片、真实平台图标（运行时自动提取）、呼吸状态灯、游戏计时器

## 使用

### 方式一：EXE（推荐）

下载 `GameBoost.exe` 双击运行。首次运行会自动检测启动器，并在 EXE 同目录生成 `config.json` 和 `icons_cache\`。

> 某些启动器（如 WeGame）自身要求管理员权限，拉起时会弹一次 UAC，点「是」即可。

### 方式二：源码运行

需要 Windows + Python 3.9+（官方安装包自带 tkinter）：

```bash
python main.py
```

### 打包 EXE

```bat
build.bat
```

## 配置 config.json

```jsonc
{
  "auto_detect": true,          // 启动时自动检测并合并新装的启动器
  "launchers": [                // 启动器列表（自动检测 + 可手动添加）
    {
      "name": "Steam",          // 显示名
      "path": "D:\\Steam\\steam.exe",   // 启动器路径（UWP 用 shell: 协议）
      "processes": ["steam.exe", "steamwebhelper.exe"],  // 该平台进程（模式切换时清理其它平台）
      "enabled": true,          // false = 不在界面显示
      "source": "detected"      // detected / custom
    }
  ],
  "kill_list": [                // 模式切换时清理的进程名（任务管理器可查进程名）
    "Doubao.exe", "BaiduNetdisk.exe", "Thunder.exe"
  ],
  "keep_list": []               // 永不清理（优先级最高）
}
```

手动添加启动器：在 `launchers` 里照抄一条改 `name` / `path` / `processes` 即可。

## 常见问题

- **检测不到某个启动器**：绿色版/自定义路径装的可能没留注册表痕迹，手动加到 `config.json` 即可。
- **想清理更多进程**：把进程名加进 `kill_list`（在任务管理器「详细信息」页看名字，带 `.exe`）。
- **点平台没反应 / 提示未找到启动器**：打开 `config.json` 检查 `path` 是否真实存在。

## 开发

- 结构：`main.py`（入口）→ `gameboost.py`（界面+逻辑）→ `launchers.py`（检测+图标）→ `config.py`（配置）
- 新增启动器支持：在 `launchers.py` 的 `LAUNCHER_SPECS` 里加一条规则即可
- 欢迎 PR / Issue

## 免责声明

本工具会结束 `kill_list` 与其它平台名单中的进程，请只添加你确认无用的常驻软件，误加可能导致未保存的工作丢失。**使用风险自担。**

## License

[MIT](LICENSE)
