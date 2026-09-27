# ============================================================
# on-demand VPK 部署包 v2.2-windows — Windows 服务器一键安装插件
#
# 用法（PowerShell 5.1+，管理员权限）:
#   .\deploy.ps1 -GameRoot "D:\steamcmd\steamapps\common\Left 4 Dead 2\left4dead2"
#   .\deploy.ps1 -GameRoot <游戏根> -DryRun        # 只打印计划
#
# 要求: 目标 Windows 服装有 SourceMod 1.12（Metamod 自带）。
# 注意: smx 插件与 Linux 通用（SourceMod 字节码跨平台），翻译/配置通用。
# ============================================================
param(
    [Parameter(Mandatory = $true)][string]$GameRoot,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$DistDir = Split-Path -Parent $PSScriptRoot
$SM = Join-Path $GameRoot "addons\sourcemod"
$PluginDir = Join-Path $SM "plugins"
$TransDir = Join-Path $SM "translations"
$IncludeDir = Join-Path $SM "scripting\include"
$Ts = Get-Date -Format "yyyyMMdd_HHmmss"

Write-Host "== on-demand VPK 部署 v2.2 (Windows) =="
Write-Host "  游戏根: $GameRoot"
Write-Host "  插件目录: $PluginDir"

if (-not (Test-Path $GameRoot)) { Write-Error "错误: $GameRoot 不存在"; exit 1 }
if (-not (Test-Path $PluginDir)) { Write-Error "错误: $PluginDir 不存在（确认是 left4dead2 根）"; exit 1 }

function Invoke-Step {
    param([string]$Desc, [string]$Action)
    if ($DryRun) { Write-Host "  [dry] $Action" }
    else { Write-Host "  $Desc"; Invoke-Expression $Action }
}

# 1. 备份旧插件
$Backup = Join-Path $PluginDir ".backup\ondemand-$Ts"
New-Item -ItemType Directory -Force -Path $Backup | Out-Null
foreach ($f in @("ondemand_vpk_bridge.smx", "l4d2_map_vote.smx")) {
    $p = Join-Path $PluginDir $f
    if (Test-Path $p) { Write-Host "备份: $f"; Invoke-Step "备份 $f" "Copy-Item -LiteralPath '$p' -Destination '$Backup' -Force" }
}

# 2. 安装核心插件
foreach ($f in @("ondemand_vpk_bridge.smx", "l4d2_map_vote.smx")) {
    $src = Join-Path $DistDir "plugins\$f"
    $dst = Join-Path $PluginDir $f
    Invoke-Step "安装: $f" "Copy-Item -LiteralPath '$src' -Destination '$dst' -Force"
}

# 3. 安装依赖插件（已存在跳过）
foreach ($f in @("l4d2_nativevote.smx", "l4d2_source_keyvalues.smx", "left4dhooks.smx")) {
    $dst = Join-Path $PluginDir $f
    if (Test-Path $dst) { Write-Host "依赖已存在，跳过: $f" }
    else { Invoke-Step "安装依赖: $f" "Copy-Item -LiteralPath '$(Join-Path $DistDir "plugins\$f")' -Destination '$dst' -Force" }
}

# 4. 安装翻译文件（已存在跳过）
New-Item -ItemType Directory -Force -Path $TransDir | Out-Null
foreach ($f in @("missions.phrases.txt", "missions_zh.phrases.txt", "chapters.phrases.txt", "chapters_zh.phrases.txt")) {
    $dst = Join-Path $TransDir $f
    if (Test-Path $dst) { Write-Host "翻译已存在，跳过: $f" }
    else { Invoke-Step "安装翻译: $f" "Copy-Item -LiteralPath '$(Join-Path $DistDir "plugins\translations\$f")' -Destination '$dst' -Force" }
}

# 5. include（二次开发）
New-Item -ItemType Directory -Force -Path $IncludeDir | Out-Null
Invoke-Step "安装: include/ondemand_vpk.inc" "Copy-Item -LiteralPath '$(Join-Path $DistDir "plugins\include\ondemand_vpk.inc")' -Destination '$(Join-Path $IncludeDir "ondemand_vpk.inc")' -Force"

Write-Host ""
Write-Host "== 下一步 =="
Write-Host "1) 生成地图仓库（在服务器或管理机）:"
Write-Host "     python tools\vpk_scan_group.py <你的VPK目录> --json scan.json"
Write-Host "     python tools\generate_map_library.py scan.json $GameRoot"
Write-Host "2) 配置 host\ondemand.env 并启动控制器/回收器（见 docs\WINDOWS.md）"
Write-Host "3) 游戏内 RCON 热载: sm plugins load ondemand_vpk_bridge; sm plugins reload l4d2_map_vote"
Write-Host "4) 验收: 玩家进服 !chmap 选三方图 → 自动加载 → 投票 → 换图"
Write-Host ""
Write-Host "备份目录: $Backup"
if ($DryRun) { Write-Host "[dry-run] 未做任何修改" }
