# 源码说明（v2.0）

本目录是部署包内所有魔改插件的源码，与 `plugins/` 里的 smx 一一对应（生产同款，2026-09-20 验证）。

## 对应关系

| 源码 | 编译产物 | 说明 |
|---|---|---|
| `ondemand_vpk_bridge/ondemand_vpk_bridge.sp` | `plugins/ondemand_vpk_bridge.smx`（v0.5.1）| 核心桥接：!chmap 请求、RCON 回调、心跳自愈、cfg 实时读取 |
| `l4d2_map_vote_ondemand/l4d2_map_vote_ondemand.sp` | `plugins/l4d2_map_vote.smx`（v3 适配）| 换图菜单：!chmap → 原生投票，集成 ODVPK_RequestStage |
| `include/ondemand_vpk.inc` | — | bridge 暴露的 API（OnDemandVPKStageResult forward + RequestStage native） |

## 编译方法

用 SourceMod 1.12 spcomp（1.11 不支持自定义析构，编不了）：

```bash
spcomp64 ondemand_vpk_bridge/ondemand_vpk_bridge.sp -i include
spcomp64 l4d2_map_vote_ondemand/l4d2_map_vote_ondemand.sp -i include -i <其他依赖include目录>
```

> ⚠️ 必须加 `-i include`（自定义 include 路径），否则报
> `error 417: cannot read from file: "ondemand_vpk"` 即使文件就在 include/ 下。
>
> map_vote 还依赖以下 include（原版开源，不在本包源码内）：
> `l4d2_nativevote.inc` / `l4d2_source_keyvalues.inc` / `localizer.inc` / `left4dhooks.inc` / `colors.inc`
> 编译时把这些 include 目录都加进 `-i`。

## bridge v0.5.1 特性（生产迭代结论）

- **RCON 实时回调主通道**：宿主 stage 完成后 `sm_ondemand_notify <id> <campaign> <map> <client> <ok>` → CommandNotify → forward 到 map_vote（不再只靠 2s 轮询 res）
- **requestId 防旧 res 误读**：NativeRequestStage 写 .req 前先清同 id 旧 .res；CommandNotify 处理完清 .res
- **心跳自愈**：进服 5s 后检测轮询 Timer 心跳，死了自动重建（hibernating 冷启动场景）
- **不 delete Timer**：OnMapStart/心跳回调里 delete Timer 会崩插件（SourceMod 部分版本实测），改为 flag + 覆盖重建
- **cfg 实时读取**：每次调用 new KeyValues + ImportFromFile，无持久缓存；GetFileTime 用 FileTime_LastChange
- **hostport 自动实例前缀**：ondemand_vpk_instance 为空时自动用 hostport，请求文件名 `<port>_<id>.req`，单服/多服零配置

## map_vote v3 特性

- `!chmap` 菜单 → 三方战役列表（读 ondemand_vpk.cfg）→ ODVPK_RequestStage → 等 StageResult → StartVoteChangeMap 原生投票
- FAIL 时兜底 `ODVPK_IsMapStaged(campaign)`（并发场景另一服已 stage 时当成功继续投票）
- 翻译文件 `translations/`（missions/chapters phrases，中英）

## 改完怎么部署

1. 本地编译出 smx
2. 上传到服务器 `addons/sourcemod/plugins/`（覆盖）
3. RCON `sm plugins reload ondemand_vpk_bridge`（或对应插件）
4. `sm plugins info ondemand_vpk_bridge` 看 Timestamp/Hash 确认跑的是新版