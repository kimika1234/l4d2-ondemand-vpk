# L4D2 按需加载地图部署包（On-Demand VPK）v2.0

> **干什么用的**：你的服务器平时只跑官方地图，玩家想玩三方图时——在游戏里 `!chmap` 选图 → 服务器自动把地图 VPK 调出来 → 弹原生投票 → 换图。玩完/人走，VPK 自动收回。不用再往服务器塞几百个地图包拖累加载和匹配。

> **适合谁**：普通 L4D2 服主。Docker 架设或裸机（直接跑 srcds）都能用。不需要装 webmap 网页选图，只需要游戏内 `!chmap`。

---

## 这个东西包含什么

```
l4d2-ondemand-vpk-dist-v2.0/
├── README.md                  # 本文件（部署说明，先读这个）
├── plugins/                   # 插件（装进 addons/sourcemod/plugins/）
│   ├── ondemand_vpk_bridge.smx        # 核心桥接（必须）
│   ├── l4d2_map_vote.smx              # 换图菜单（!chmap 必须）
│   ├── l4d2_nativevote.smx            # 依赖：原生投票库
│   ├── l4d2_source_keyvalues.smx      # 依赖：配置读取
│   ├── left4dhooks.smx                # 依赖：游戏钩子库
│   ├── include/ondemand_vpk.inc       # 给会写插件的人
│   └── translations/                  # 地图菜单翻译文件（中英）
├── host/                     # 自动化程序（控制器+回收器）
│   ├── stage_controller.py   # 玩家要图时，负责搬地图文件
│   ├── reclaimer.py          # 没人玩时，负责回收地图文件
│   └── ondemand.env.example  # 配置模板
├── tools/                    # 建地图仓库的工具
│   ├── vpk_scan_group.py     # 扫描你的 VPK，自动把同一个图的多分卷归组
│   ├── generate_map_library.py  # 生成地图仓库 + 服务器配置
│   └── vpk_tool.py           # 底层解析库（不用管）
├── scripts/
│   └── deploy.sh             # 一键装插件
└── docs/
    └── USER-GUIDE.md         # 玩家/管理员使用说明
```

---

## 部署前确认

- ✅ 服务器是 **Linux**（Ubuntu/Debian/CentOS 都行）
- ✅ 装有 **Metamod:Source + SourceMod 1.12**（绝大多数服都有；没有就先装，网上教程一大把）
- ✅ 你会用 **RCON**（游戏服务器控制台）执行命令
- ✅ 知道你的服务器 **left4dead2 目录**在哪
  - Docker 服：宿主机上挂载进容器的那个目录（比如 `/shared/left4dead2`）
  - 裸机服：srcds 所在目录（比如 `/home/steam/left4dead2`）
- ⛔ 不需要 webmap / 不需要数据库 / 不需要编译 C++

---

## 部署三步走

### 第 1 步：装插件

把整个包传到服务器上（比如放 `/root/l4d2-ondemand-vpk-dist-v2.0`），然后：

```bash
cd l4d2-ondemand-vpk-dist-v2.0
chmod +x scripts/deploy.sh

# 裸机服：
./scripts/deploy.sh /home/steam/left4dead2

# Docker 服（路径是宿主机挂载目录）：
./scripts/deploy.sh /shared/left4dead2 --docker
```

脚本会：备份旧插件 → 装上 5 个插件 + 翻译文件。装完用 RCON 执行热载：

```
sm plugins load ondemand_vpk_bridge
sm plugins reload l4d2_map_vote
```

确认加载成功：

```
sm plugins list
```

> 看到 `On-demand VPK Bridge` 和 `L4D2 Map vote` 都是 Running 就行。
> 如果 l4d2_map_vote 报错缺依赖，说明你之前没装过 nativevote/left4dhooks，deploy.sh 已经帮你装好了，再 reload 一次。

---

### 第 2 步：生成地图仓库

把你想开放给玩家的三方地图 VPK 放到一个目录（比如 `/root/vpks`，可以是从创意工坊/网盘下的），然后：

```bash
# 2.1 扫描并自动归组（同一个图多分卷的会归成一组）
python3 tools/vpk_scan_group.py /root/vpks --json scan.json

# 2.2 生成仓库 + 服务器配置（游戏根按你的实际情况填）
python3 tools/generate_map_library.py scan.json /shared/left4dead2
```

跑完：
- `map_library/<战役>/part_N.vpk` —— 地图仓库（平时不加载）
- `addons/sourcemod/configs/ondemand_vpk.cfg` —— 服务器配置（自动生成）

**重要**：如果你把 VPK 直接放在 `addons/` 里（老习惯），生成仓库后要把它们移出来，否则服务器启动时还是会全部加载，起不到「按需」效果：

```bash
# 空服时操作！分批移，别一次挪几百个
mkdir -p /shared/left4dead2/addons_off
mv /shared/left4dead2/addons/*.vpk /shared/left4dead2/addons_off/
# 注意：addons_off 只是备份，服务器不再加载这些文件
```

移完后 RCON 执行一次刷新：

```
sm plugins reload ondemand_vpk_bridge
```

---

### 第 3 步：启动控制器 + 回收器

```bash
# 3.1 建配置文件
mkdir -p /opt/ondemand
cp host/ondemand.env.example /opt/ondemand/ondemand.env
nano /opt/ondemand/ondemand.env    # 改这 3 个：游戏根 / RCON密码 / 服务器端口
chmod 600 /opt/ondemand/ondemand.env

# 3.2 常驻运行（推荐用 systemd，开机自启 + 崩了自动拉起）
cp host/stage_controller.py host/reclaimer.py /opt/ondemand/
```

创建 `/etc/systemd/system/ondemand-stage.service`：

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

再创建 `/etc/systemd/system/ondemand-reclaim.service`（内容同上，ExecStart 换成 `/usr/bin/python3 /opt/ondemand/reclaimer.py`）。然后：

```bash
systemctl daemon-reload
systemctl enable --now ondemand-stage ondemand-reclaim
systemctl status ondemand-stage ondemand-reclaim    # 两个都 active 就行
```

> 临时跑也行：`python3 /opt/ondemand/stage_controller.py` 前台挂着看日志。

---

## 玩家怎么用（一句话）

> 聊天框输入 `!chmap` → 选「三方地图」→ 选战役 → 选章节 → 提示「正在加载地图资源」→ 几秒后弹原生投票 → 通过即换图。

---

## 部署完成怎么验收

1. [ ] `sm plugins list` 里 bridge 和 map_vote 都是 Running
2. [ ] `ls /shared/left4dead2/addons/` 里没有三方战役 VPK（应该在 `map_library/`）
3. [ ] 空服实验：`journalctl -u ondemand-stage -n 20` 看有没有 `controller armed` 日志
4. [ ] 你进服 `!chmap` 选一张三方图，能加载 → 投票 → 换过去
5. [ ] 换图后 `ls /shared/left4dead2/addons/` 出现 `ondemand_xxx_part_1.vpk`（自动加载的副本）
6. [ ] 玩完回官图/退出，过几分钟再 `ls`，副本被回收（`ondemand_*` 消失），`map_library/` 里的源还在

---

## 常见问题（极简版）

| 现象 | 处理 |
|---|---|
| `!chmap` 提示加载中但不弹投票 | RCON `sm plugins reload ondemand_vpk_bridge`；确认控制器在跑（systemctl status ondemand-stage）|
| 换图报 `No such map` | 用生成工具重跑一次（章节名必须大小写正确）；确认 `map_library/<战役>/` 有 part_*.vpk |
| 菜单里看不到三方战役 | `sm_ondemand_status` 看 campaigns 数量；确认 cfg 生成了 |
| 回收器不回收 | 正常：有人在线/当前地图在仓库里时不回收。看日志 `journalctl -u ondemand-reclaim -n 20` |

更多细节见 `docs/USER-GUIDE.md`。

---

## 版本

**v2.0（2026-09-20）**：基于 45/202 农场生产验证组件打包。
- bridge 0.5.1（RCON 实时回调 + 心跳自愈 + requestId 防串）
- map_vote v3 适配（!chmap 全链路，生产同款 smx）
- 控制器/回收器 = 2026-09-19 生产同款（大小写兜底 + 回收宽限期 600s + 并发安全 + 零依赖）
- 无 webmap 集成（目标服不需要网页选图）
- 章节名从 mission 文件提取（大小写敏感，杜绝换图 No such map）

部署时请注意：**不要在服务器有真人时批量移动 addons 里的 VPK**（会炸服）。移图前先让玩家下线或选在凌晨。