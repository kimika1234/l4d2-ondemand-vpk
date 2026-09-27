# Windows 常驻服务模板（on-demand VPK v2.2-windows）

三个 Python 常驻进程在 Windows 上的两种挂法：**任务计划程序（schtasks，系统自带，推荐）** 或 **NSSM（服务方式，开机自启更稳）**。选一种即可。

## 前置

1. 安装 Python 3.10+（勾选 "Add python.exe to PATH"）
2. 把 `host/` 和 `tools/vpk_tool.py` 拷到统一目录，例如 `C:\ondemand\`
3. 设置系统环境变量 `ONDEMAND_HOME=C:\ondemand`（控制器/回收器/看门狗都读它；不设则默认 `/opt/ondemand` 会找错路径！）
   ```powershell
   [Environment]::SetEnvironmentVariable("ONDEMAND_HOME", "C:\ondemand", "Machine")
   ```
4. 配置 `C:\ondemand\ondemand.env`（复制 host\ondemand.env.example，改游戏根/RCON 密码/端口）

## 方式 A：任务计划程序（schtasks，推荐）

用管理员 PowerShell 执行（把 `D:\steamcmd\...\left4dead2` 换成你的游戏根）：

```powershell
# 控制器（开机启动 + 每 5 分钟防挂自动重启一次）
schtasks /Create /F /TN "L4D2OnDemandStage" /SC ONSTART /RU SYSTEM /RL HIGHEST `
  /TR "cmd /c \"set ONDEMAND_HOME=C:\ondemand && cd /d C:\ondemand && python stage_controller.py\""

# 回收器
schtasks /Create /F /TN "L4D2OnDemandReclaim" /SC ONSTART /RU SYSTEM /RL HIGHEST `
  /TR "cmd /c \"set ONDEMAND_HOME=C:\ondemand && cd /d C:\ondemand && python reclaimer.py\""

# 看门狗（每 5 分钟跑一次，oneshot 入库）
schtasks /Create /F /TN "L4D2OnDemandIngest" /SC MINUTE /MO 5 /RU SYSTEM `
  /TR "cmd /c \"set ONDEMAND_HOME=C:\ondemand && cd /d C:\ondemand && python ingest_watchdog.py D:\steamcmd\steamapps\common\Left 4 Dead 2\left4dead2\""
```

立即启动：
```powershell
schtasks /Run /TN "L4D2OnDemandStage"
schtasks /Run /TN "L4D2OnDemandReclaim"
schtasks /Run /TN "L4D2OnDemandIngest"
```

查日志：控制器的轮询/搬图日志在 `C:\ondemand\stage.log` 等（重定向）——上面的 /TR 没带重定向，正式用时建议加 `>> C:\ondemand\stage.log 2>&1`。

## 方式 B：NSSM 服务（可选，更稳）

装 NSSM（https://nssm.cc）后，管理员 PowerShell：

```powershell
nssm install L4D2OnDemandStage "C:\Windows\System32\cmd.exe" "/c set ONDEMAND_HOME=C:\ondemand && cd /d C:\ondemand && python stage_controller.py"
nssm install L4D2OnDemandReclaim "C:\Windows\System32\cmd.exe" "/c set ONDEMAND_HOME=C:\ondemand && cd /d C:\ondemand && python reclaimer.py"
nssm start L4D2OnDemandStage
nssm start L4D2OnDemandReclaim
```

## 验证

- `schtasks /Query /TN "L4D2OnDemandStage"`（或 `nssm status L4D2OnDemandStage`）显示 Running
- 游戏内 `!chmap` 选一张三方图，看 `C:\ondemand` 是否出现 `.req` / addons 是否出现 `ondemand_xxx_part_1.vpk`
- 回收：玩完回官图，过几分钟 `ondemand_*` 消失

> ⚠️ RCON 端口：Windows 裸机服 RCON 就是本机端口（27015 等），`ONDEMAND_SERVERS` 填服端口即可；RCON 密码是 `server.cfg` 的 `rcon_password`。
