#!/usr/bin/env bash
# ============================================================
# on-demand VPK 部署包 v2.1 — 服务器端一键安装插件
#
# 用法:
#   ./deploy.sh <游戏根目录>            # 普通 Linux 服（srcds 裸跑）
#   ./deploy.sh <游戏根目录> --docker   # Docker 服：传宿主机上挂载进容器的游戏根
#   ./deploy.sh <游戏根目录> --dry-run  # 只打印计划
#
# 要求: 在目标服务器上执行（root），或 scp 到服务器后执行
# 注意: 目标服只需要 SourceMod 1.12（Metamod 自带）。不需要装 webmap。
# ============================================================
set -euo pipefail

GAME_ROOT="${1:?用法: ./deploy.sh <游戏根目录> [--docker] [--dry-run]}"
WITH_DOCKER=0
DRY=0
for arg in "$@"; do
  case "$arg" in
    --docker) WITH_DOCKER=1 ;;
    --dry-run) DRY=1 ;;
  esac
done

DIST_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SM_DIR="$GAME_ROOT/addons/sourcemod"
PLUGIN_DIR="$SM_DIR/plugins"
CFG_DIR="$SM_DIR/configs"
TRANS_DIR="$SM_DIR/translations"
TS="$(date +%Y%m%d_%H%M%S)"

echo "== on-demand VPK 部署 v2.1 =="
echo "  游戏根: $GAME_ROOT"
[ $WITH_DOCKER = 1 ] && echo "  模式: Docker（路径是宿主机挂载目录）"
echo "  插件目录: $PLUGIN_DIR"
echo "  时间戳: $TS"
[ -d "$GAME_ROOT" ] || { echo "错误: $GAME_ROOT 不存在"; exit 1; }
[ -d "$PLUGIN_DIR" ] || { echo "错误: $PLUGIN_DIR 不存在（确认是 left4dead2 根）"; exit 1; }

run() {
  if [ $DRY = 1 ]; then echo "  [dry] $*"; else eval "$*"; fi
}

# 1. 备份旧插件（如果有）
BACKUP="$PLUGIN_DIR/.backup/ondemand-$TS"
mkdir -p "$BACKUP"
for f in ondemand_vpk_bridge.smx l4d2_map_vote.smx; do
  if [ -f "$PLUGIN_DIR/$f" ]; then
    echo "备份: $f"
    run "cp -p '$PLUGIN_DIR/$f' '$BACKUP/'"
  fi
done

# 2. 安装核心插件（bridge + map_vote）
echo "安装: ondemand_vpk_bridge.smx"
run "cp -p '$DIST_DIR/plugins/ondemand_vpk_bridge.smx' '$PLUGIN_DIR/'"
echo "安装: l4d2_map_vote.smx（!chmap 换图菜单）"
run "cp -p '$DIST_DIR/plugins/l4d2_map_vote.smx' '$PLUGIN_DIR/'"

# 3. 安装依赖插件（map_vote 运行必需；已存在则跳过不覆盖）
for dep in l4d2_nativevote.smx l4d2_source_keyvalues.smx left4dhooks.smx; do
  if [ -f "$PLUGIN_DIR/$dep" ]; then
    echo "依赖已存在，跳过: $dep"
  else
    echo "安装依赖: $dep"
    run "cp -p '$DIST_DIR/plugins/$dep' '$PLUGIN_DIR/'"
  fi
done

# 4. 安装翻译文件（map_vote 菜单中文/英文显示；已存在则跳过不覆盖）
mkdir -p "$TRANS_DIR"
for t in missions.phrases.txt missions_zh.phrases.txt chapters.phrases.txt chapters_zh.phrases.txt; do
  if [ -f "$TRANS_DIR/$t" ]; then
    echo "翻译已存在，跳过: $t"
  else
    echo "安装翻译: $t"
    run "cp -p '$DIST_DIR/plugins/translations/$t' '$TRANS_DIR/'"
  fi
done

# 5. include（给二次开发）
[ -d "$SM_DIR/scripting/include" ] || mkdir -p "$SM_DIR/scripting/include"
echo "安装: include/ondemand_vpk.inc"
run "cp -p '$DIST_DIR/plugins/include/ondemand_vpk.inc' '$SM_DIR/scripting/include/'"

echo ""
echo "== 下一步 =="
echo "1) 生成地图仓库（在服务器或管理机）:"
echo "     python3 tools/vpk_scan_group.py <你的VPK目录> --json scan.json"
echo "     python3 tools/generate_map_library.py scan.json $GAME_ROOT"
echo "2) 配置 host/ondemand.env 并启动控制器/回收器（见 README.md 第 3 步）"
echo "3) RCON 热载: sm plugins load ondemand_vpk_bridge; sm plugins reload l4d2_map_vote"
echo "4) 验收: 玩家进服 !chmap 选三方图 → 自动加载 → 投票 → 换图"
echo ""
echo "备份目录: $BACKUP"
[ $DRY = 1 ] && echo "[dry-run] 未做任何修改"