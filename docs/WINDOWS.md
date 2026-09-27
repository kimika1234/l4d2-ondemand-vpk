# Windows 部署指南（v2.2-windows）

> 本包同时支持 Linux 与 Windows 服务器。**Linux 部署看 README.md，Windows 看本文档。** 插件（smx）、地图仓库、配置全部跨平台，只有常驻方式（systemd vs 任务计划程序）不同。

## 一、能跑什么

| 组件 | Windows 支持 | 说明 |
|---|---|---|
| 5 个 SourceMod 插件（smx） | ✅ | SourceMod 字节码跨平台，left4dhooks 有 Windows 版 |
| `tools/vpk_tool.py` | ✅ | 纯 Python，本地实测解析中文文件名 VPK 正常 |
| `tools/vpk_scan_group.py` / `generate_map_library.py` | ✅ | 纯解析 |
| `host/stage_controller.py` / `reclaimer.py` | ✅ | 纯 socket RCON + 文件操作，零 Unix API |
| `host/ingest_new_vpk.py` / `ingest_watchdog.py` | ✅ | v2.2 已参数化（见下） |
| 常驻（systemd） | ❌ | Windows 用任务计划程序 / NSSM（模板见 `windows/README.md`） |
| `deploy.sh` | ❌ | Windows 用 `scripts/deploy.ps1` |

## 二、安装步骤

### 1. 装插件（管理员 PowerShell）

```powershell
cd l4d2-ondemand-vpk-dist-v2.2-windows
.\scripts\deploy.ps1 -GameRoot "D:\steamcmd\steamapps\common\Left 4 Dead 2\left4dead2"
# 只预览：加 -DryRun
```

游戏内 RCON 热载：
```
sm plugins load ondemand_vpk_bridge
sm plugins reload l4d2_map_vote
```

### 2. 生成地图仓库

```powershell
python tools\vpk_scan_group.py D:\vpks --json scan.json
python tools\generate_map_library.py scan.json "D:\steamcmd\steamapps\common\Left 4 Dead 2\left4dead2"
```

> `generate_map_library.py` 的 `--scan-result` 默认 `%ONDEMAND_HOME%\scan_result.json`；不设环境变量时默认仍是 `/opt/ondemand/scan_result.json`（Linux 路径）——**Windows 上必须设 `ONDEMAND_HOME` 或显式传 `--scan-result`**。

### 3. 配置脚本目录 + 常驻

```powershell
# 建目录、拷脚本
mkdir C:\ondemand
copy host\*.py C:\ondemand\
copy tools\vpk_tool.py C:\ondemand\

# 设环境变量（重要！）
[Environment]::SetEnvironmentVariable("ONDEMAND_HOME", "C:\ondemand", "Machine")

# 配置
copy host\ondemand.env.example C:\ondemand\ondemand.env
notepad C:\ondemand\ondemand.env   # 改 ONDEMAND_GAME_ROOT / RCON 密码 / ONDEMAND_SERVERS
```

常驻挂法（任务计划程序 / NSSM）见 `windows/README.md`。

## 三、跨平台原理（给运维看）

- 脚本不再硬编码 `/opt/ondemand`，全部读 `ONDEMAND_HOME` 环境变量（Linux 默认 `/opt/ondemand` 保持向后兼容）
- 子进程调用不再硬编码 `python3`，用 `ONDEMAND_PYTHON`（默认 `sys.executable`，Windows 自动是 `python.exe`）
- RCON 用纯 socket，Windows/Linux 一致
- 路径拼接全部 `os.path.join`，自动适配 `\` / `/`

## 四、已知限制

- **sourcemod 路径分隔符**：cfg/翻译里若出现手写 `/` 路径（如 `addons/sourcemod/configs/ondemand_vpk.cfg` 的生成由工具负责，跨平台没问题）
- **大 VPK 移动**：`shutil.move` 同盘瞬时完成；map_library 与 addons 跨盘（C: vs D:）会变成拷贝+删除，略慢但正确
- **权限**：任务计划程序用 SYSTEM 跑，注意游戏服目录对 SYSTEM 可写（SteamCMD 装的通常没问题）
- **杀软**：个别杀软会扫 `ondemand_*` 大批文件移动，可加白名单 `C:\ondemand` 与游戏根
