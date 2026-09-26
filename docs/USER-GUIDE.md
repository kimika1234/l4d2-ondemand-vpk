# 用户使用说明（玩家 + 管理员）v2.1

## 玩家：怎么换三方图

1. 聊天框输入 `!chmap`
2. 菜单选「三方地图」
3. 选你要的战役（如「毁灭天堂 Paradise of Doom」）
4. 选章节（如「1: 堕落之地」）
5. 提示「正在加载地图资源，完成后自动发起换图投票...」
6. 数秒后弹出原生投票，按 F1/F2 投票
7. 通过后自动换图

> 若 VPK 已经加载过（本服最近有人玩过且未回收），会跳过加载直接弹投票。

## 管理员：常用命令

```text
sm_ondemand_status              # 查看仓库战役数和加载状态（campaigns=N）
sm_ondemand_requests            # 查看请求目录路径
sm_ondemand_refresh             # 手动 update_addon_paths; mission_reload
sm plugins reload ondemand_vpk_bridge   # 桥接插件卡住时热载恢复
```

## 管理员：验收（部署完成后必做）

### 空服金丝雀（不打扰玩家）

在服务器请求目录放一个模拟请求（`<端口>_999.req`，端口 = 你的游戏端口，如 27015）：

```bash
REQ=/shared/left4dead2/addons/sourcemod/data/ondemand_vpk_requests
mkdir -p $REQ
printf 'campaign=2019\nmap=2019_M1b\nclient=0\n' > $REQ/27015_999.req
```

（`campaign` 和 `map` 换成你 `map_library/` 里真实存在的战役和章节，比如先看 cfg 里第一个战役）

然后：
- 控制器日志应出现 `stage ... OK`
- `ls /shared/left4dead2/addons/ondemand_*` 出现加载副本
- 请求目录出现 `27015_999.res`（内容 OK）

测试完清理：`rm -f $REQ/27015_999.*`

### 真人验证

1. 你进服 `!chmap` 走完整流程，确认能换到三方图
2. 玩一会，回官图或退出
3. 看回收器日志：`reclaim campaign=xxx files=N OK`
4. `ls addons/ondemand_*.vpk` 应为空，`map_library/<战役>/` 源完整

## 生产常驻（systemd）

`ondemand-stage.service`（控制器）：

```ini
[Unit]
Description=On-demand VPK stage controller
After=network.target

[Service]
EnvironmentFile=/opt/ondemand/ondemand.env
ExecStart=/usr/bin/python3 /opt/ondemand/stage_controller.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`ondemand-reclaim.service`（回收器）：同上，ExecStart 换成 `/usr/bin/python3 /opt/ondemand/reclaimer.py`。

```bash
systemctl daemon-reload
systemctl enable --now ondemand-stage ondemand-reclaim
journalctl -u ondemand-stage -f    # 看控制器日志
journalctl -u ondemand-reclaim -f  # 看回收器日志
```

## 故障排查

| 现象 | 排查 |
|---|---|
| 提示「正在加载」但一直不换图 | `sm plugins reload ondemand_vpk_bridge`；确认控制器 running（systemctl status ondemand-stage）；请求目录是否有残留 `.req`/`.res`（有残留说明没处理完）|
| 「按需地图加载失败」 | 同一玩家上次请求未完成；控制器没跑；宿主日志看具体 FAIL 原因 |
| 菜单里看不到三方战役 | `sm_ondemand_status` 看 campaigns；cfg 是否生成；bridge 是否加载 |
| 换图失败 `No such map` | 章节名大小写与 mission 文件不符 → 重跑 `generate_map_library.py` |
| 回收器不回收 | 服务器当前地图属于某仓库战役（故意保护）；有人在线；RCON 不通（看日志）。v2.1 已修复旧版大写残留文件永不回收的问题 |
| 控制器日志 `no parts in map_library/xxx` | 战役目录名大小写不一致（Linux 区分大小写）→ 重跑生成工具 |

## 管理员：新图自动入库（推荐，v2.2 看门狗增强）

如果你有网页上传/管理面板往 `addons/` 丢 VPK，**强烈建议加装** `host/ingest_new_vpk.py`（v2.2）+ `host/ingest_watchdog.py`（v2.2 宽容归组），新图自动归组进 `map_library`：

```bash
cp host/ingest_new_vpk.py host/ingest_watchdog.py /opt/ondemand/
cp tools/vpk_tool.py /opt/ondemand/

# 手动入库：python3 /opt/ondemand/ingest_new_vpk.py <游戏根> <文件名>

# 定时看门狗（推荐 systemd 5min，抄模板；也支持 cron 每分钟）
cp systemd/ingest-watchdog.service systemd/ingest-watchdog.timer /etc/systemd/system/
sed -i 's|<GAME_ROOT>|/shared/left4dead2|' /etc/systemd/system/ingest-watchdog.service
systemctl daemon-reload && systemctl enable --now ingest-watchdog.timer
systemctl list-timers | grep ingest   # ⛔ 必须看到 timer，否则看门狗永不自动跑
```

- 老图更新 = **替换**旧 part（按 VPK 内 bsp 集合判定，不是 mission 名；纯资源包按标题/大小匹配替换），不会堆积新旧版本
- **多分卷 Part 2+ 纯资源包**（无 mission 无 bsp，如批量下载的贴图/模型包、versus 独立图）被 ingest 拒后，看门狗 v2.2 自动按文件名/VPK 内 bsp 前缀匹配已有同战役目录 → append 进 `map_library/<战役>/part_N.vpk`（对标 45 `vpk_move_to_library3.py`）
- 功能包（无 mission 且无归属）自动跳过；`ondemand_` 前缀的 stage 副本跳过；看门狗失败自动重试（连试 5 次无归属才放弃）
- `map_library_archive/<战役>/` 存放被替换下来的旧版（可回滚，不影响运行）

## 安全边界（务必理解）

- **地图文件移动只由控制器做**，游戏内插件绝不复制大 VPK（会卡死服务器）
- 回收 = 删 addons 加载副本，`map_library/` 源永远保留
- 回收条件：没有任何服当前地图属于该战役 + 无人卡加载（有 10 分钟宽限期）
- **绝不**在有人玩图时批量移动 addons 文件
- 多分卷永远整组移动（part_1/2/3 一起），绝不只拿含地图的 part_1