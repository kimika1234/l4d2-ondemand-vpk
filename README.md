# L4D2 按需加载地图部署包（On-Demand VPK）v2.3-windows

> **干什么用的**：你的服务器平时只跑官方地图，玩家想玩三方图时——在游戏里 `!chmap` 选图 → 服务器自动把地图 VPK 调出来 → 弹原生投票 → 换图。玩完/人走，VPK 自动收回。不用再往服务器塞几百个地图包拖累加载和匹配。

> **适合谁**：普通 L4D2 服主。**Linux 和 Windows 服务器都能用**（Docker 架设或裸机直接跑 srcds）。不需要装 webmap 网页选图，只需要游戏内 `!chmap`。
>
> **Windows 用户**：插件/工具/控制器脚本全部跨平台，部署命令用 `scripts/deploy.ps1`，常驻挂任务计划程序——详细看 `docs/WINDOWS.md` 和 `windows/README.md`。

---

## 这个东西包含什么

```
l4d2-ondemand-vpk-dist-v2.2-windows/
├── README.md                  # 本文件（部署说明，先读这个）
├── plugins/                   # 插件（装进 addons/sourcemod/plugins/，跨平台）
│   ├── ondemand_vpk_bridge.smx        # 核心桥接（必须）
│   ├── l4d2_map_vote.smx              # 换图菜单（!chmap 必须）
│   ├── l4d2_nativevote.smx            # 依赖：原生投票库
│   ├── l4d2_source_keyvalues.smx      # 依赖：配置读取
│   ├── left4dhooks.smx                # 依赖：游戏钩子库
│   ├── include/ondemand_vpk.inc       # 给会写插件的人
│   └── translations/                  # 地图菜单翻译文件（中英）
├── host/                     # 自动化程序（控制器+回收器+入库，跨平台）
│   ├── stage_controller.py   # 玩家要图时，负责搬地图文件
│   ├── reclaimer.py          # 没人玩时，负责回收地图文件
│   ├── ingest_new_vpk.py     # 【推荐】新图入库：addons 新 VPK 自动归组到仓库
│   ├── ingest_watchdog.py    # 【推荐】配合 ingest 的定时扫描看门狗（v2.2 宽容归组）
│   └── ondemand.env.example  # 配置模板（含 ONDEMAND_HOME 跨平台说明）
├── systemd/                  # 看门狗 systemd 模板（Linux 用）
│   ├── ingest-watchdog.service
│   └── ingest-watchdog.timer
├── windows/                  # Windows 常驻模板（v2.2-windows 新增）
│   └── README.md             # 任务计划程序 / NSSM 挂常驻
├── tools/                    # 建地图仓库的工具（跨平台）
│   ├── vpk_scan_group.py     # 扫描你的 VPK，自动把同一个图的多分卷归组
│   ├── generate_map_library.py  # 生成地图仓库 + 服务器配置
│   └── vpk_tool.py           # 底层解析库（不用管）
├── scripts/
│   ├── deploy.sh             # 一键装插件（Linux）
│   └── deploy.ps1            # 一键装插件（Windows，v2.2-windows 新增）
└── docs/
    ├── USER-GUIDE.md         # 玩家/管理员使用说明
    ├── MULTIPART.md          # 多分卷 VPK 识别说明
    └── WINDOWS.md            # Windows 部署指南（v2.2-windows 新增）
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

把整个包传到服务器上（比如放 `/root/l4d2-ondemand-vpk-dist-v2.1`），然后：

```bash
cd l4d2-ondemand-vpk-dist-v2.1
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

## 【推荐】新图自动入库（ingest + 看门狗）

如果你有一个网页上传面板 / 管理面板会把玩家传的 VPK 直接丢进 `addons/`，**强烈建议加装 ingest**——否则新图会堆积在 addons 热区（引擎全量扫描 + 广播 1200B 溢出 + 换图卡死）。加装后新图**自动归组进 map_library**：

```bash
cp host/ingest_new_vpk.py host/ingest_watchdog.py /opt/ondemand/
cp tools/vpk_tool.py /opt/ondemand/        # ingest 依赖（stage 也会用到）
```

- 手动入库一个文件：`python3 /opt/ondemand/ingest_new_vpk.py <游戏根> <addons里的文件名>`
- 定时看门狗（**推荐 systemd，5 分钟自动扫 addons 里稳定 >5 分钟的新 VPK 入库**）：

```bash
# 复制 systemd 模板（先替换 <GAME_ROOT> 为你的游戏根，如 /shared/left4dead2）
cp systemd/ingest-watchdog.service systemd/ingest-watchdog.timer /etc/systemd/system/
sed -i 's|<GAME_ROOT>|/shared/left4dead2|' /etc/systemd/system/ingest-watchdog.service
systemctl daemon-reload
systemctl enable --now ingest-watchdog.timer
systemctl list-timers | grep ingest   # 确认 timer 在跑
```

> ⛔ **注意**：只拷贝 `ingest_watchdog.py` 却不挂 timer/定时任务 = 看门狗永远不会自动跑，新图会滞留 addons（103 新家实测翻车：95 个非常驻 vpk 堆积）。**挂 timer 和拷脚本是两件事，都要做！**

也可以用 cron（每分钟）替代：`* * * * * cd /opt/ondemand && python3 ingest_watchdog.py <游戏根> >> /var/log/ondemand-ingest.log 2>&1`

ingest v2.2 特性：
- **老图更新 = 替换而不是堆积**：按 VPK 内 bsp 地图集合判定（不是按 mission 名），同图新版自动归档旧 part，目录不膨胀
- **纯资源包更新也替换**：贴图/音效 part（无 bsp）按 addontitle / 文件大小匹配替换，避免新旧资源包并存冲突
- **keep_ 常驻联动**：如果 addons 里有 `keep_<战役>_part_N.vpk` 常驻副本，入库后自动刷新为最新版

watchdog v2.2 特性：
- **失败自动重试**：被 ingest 拒绝的文件（如无 mission 的纯资源包）不再永久跳过，下次定时扫描自动再试（连试 5 次仍无归属才放弃）
- **宽容归组兜底**：多分卷战役的 Part 2+ 纯资源包（vmt/mdl 贴图模型包、versus 独立图，无 mission 无 bsp）被 ingest 拒后，看门狗会按文件名/VPK 内 bsp 前缀匹配已有的同战役目录 → 自动 append 进 `map_library/<战役>/part_N.vpk`（对标 45 农场 `vpk_move_to_library3.py` 的归组逻辑）。这样批量下载的多分卷图不会滞留 addons 热区。

> ⛔ ingest 会把文件从 addons **移动**进 map_library（除非加 `--keep`）。功能包（无 mission 的 VPK）会自动跳过不入库；看门狗会重试，若确实无归属（真孤儿）连续 5 次后记入状态放弃。

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
| addons 里 `ondemand_` 残留文件永不回收 | 旧版本控制器生成的文件大小写与 cfg 不一致（v2.0 时代）。升级到 v2.1 的 reclaimer.py 后会自动识别回收；急着清理可手动 `rm addons/ondemand_*`（map_library 源不受影响） |
| addons 里堆积大量 `【Map】xxx Part 2/3...` 非常驻 vpk | 看门狗没挂 timer 或旧版 watchdog 失败不进重试。① 确认 `systemctl list-timers | grep ingest` 在跑；② 升级 v2.2 watchdog（失败自动重试 + 宽容归组）；③ 存量手动归组：清空 state（`echo '[]' > /opt/ondemand/ingest_watchdog_state.json`）后手动跑一次 `python3 /opt/ondemand/ingest_watchdog.py <游戏根>` |

更多细节见 `docs/USER-GUIDE.md`。

---

## 版本与更新日志

**v2.3-windows（2026-09-27）**：keep_ 常驻联动修复（与 main 分支 v2.3 同步）。
- 🔧 **新图入库不再自动创建 keep_ 常驻**（重要）：v2.1 引入的 keep_ 联动在 replace/append 后无条件把 `map_library/<key>/` 镜像到 `addons/keep_<key>_part_N.vpk`，导致**任何新传图都会自动变常驻**（实测药役传图 927MB 医疗改革 healthreform 意外进 addons 热区，mtime 与 map_library 完全一致 = 自动生成铁证）。v2.3 改为：**只有 addons 已存在 `keep_<key>` 的名单图才刷新常驻**（用户点名的热门图跟最新版），新 key 不自动建常驻
- 想新增常驻 = 人工复制 `keep_<key>_part_N.vpk` 到 addons（watchdog/reclaimer 已有 `keep_` 前缀跳过规则）
- 其余组件与 v2.2-windows 一致

**v2.2-windows（2026-09-27）**：Windows 适配版（Linux 版 v2.2 原样保留在 main 分支/release v2.2）。
- 🌍 **一套代码双平台**：宿主脚本不再硬编码 `/opt/ondemand`，全部读 `ONDEMAND_HOME` 环境变量（Linux 默认 `/opt/ondemand` 保持向后兼容）；子进程不再硬编码 `python3`，用 `ONDEMAND_PYTHON`（默认 `sys.executable`）
- ✨ **新增 `scripts/deploy.ps1`**：Windows 一键装插件（等价 deploy.sh，支持 -GameRoot / -DryRun）
- ✨ **新增 `windows/README.md`**：任务计划程序（schtasks）/ NSSM 挂常驻模板
- ✨ **新增 `docs/WINDOWS.md`**：Windows 完整部署指南（装插件→建仓库→配常驻→验证）+ 已知限制（跨盘 move、杀软白名单）
- 实测：`vpk_tool.py` 在 Windows 解析真实 VPK（含中文文件名）正常；`stage_controller/reclaimer` 零 Unix API 可直接跑
- 注意：Windows 上**必须设 `ONDEMAND_HOME`**（或显式传 `--scan-result`），否则脚本默认找 `/opt/ondemand` 会错

**v2.2（2026-09-26）**：看门狗增强 + systemd 模板（103 新家 95 个滞留实锤驱动）。
- 🔧 **watchdog 失败自动重试**（重要）：旧版 ingest 失败的文件也记入 state → 永久跳过。v2.2 仅成功/已处理才记 state，被拒文件（无 mission 纯资源包等）下次定时扫描自动再试，连续 5 次仍无归属才放弃
- ✨ **watchdog 宽容归组兜底**：多分卷战役的 Part 2+ 纯资源包（无 mission 无 bsp）被 ingest 拒后，按文件名/VPK 内 bsp 前缀匹配已有同战役目录 → 自动 append 进 map_library（对标 45 `vpk_move_to_library3.py`）。批量下载的多分卷图不再滞留 addons 热区
- ✨ **新增 `systemd/ingest-watchdog.service + .timer` 模板**（5min，抄 45 生产）——只拷脚本不挂 timer = 看门狗永不自动跑（103 实测翻车点）
- 状态文件升级为 `{"done": {...}, "retries": {...}}`，兼容旧版纯数组
- 其余组件（bridge 0.5.1 / map_vote v3 / stage_controller / reclaimer / ingest_new_vpk v2.2）与 v2.1 一致，均为生产同款 hash

**v2.1（2026-09-26）**：生产修复同步。
- 🔧 **回收器大小写修复**（重要）：旧版 reclaimer 只认 `ondemand_<小写key>_part_N.vpk`，遇到历史遗留的大写/混合大小写文件（如 `ondemand_BlackoutBasement_part_1.vpk`）永不回收 → addons 堆积残留。v2.1 回收时自动 sanitize 小写对齐 cfg key + 大小写不敏感匹配，残留可正常回收
- ✨ **新增 ingest v2.2 可选组件**：新图自动入库（老图更新替换式、纯资源包替换、keep_ 常驻联动），详见上文「可选：新图自动入库」
- 其余组件（bridge 0.5.1 / map_vote v3 / stage_controller / vpk_tool）与 v2.0 一致，均为 2026-09-25 双服生产同款 hash

**v2.0（2026-09-20）**：基于 45/202 农场生产验证组件打包。
- bridge 0.5.1（RCON 实时回调 + 心跳自愈 + requestId 防串）
- map_vote v3 适配（!chmap 全链路，生产同款 smx）
- 控制器/回收器 = 2026-09-19 生产同款（大小写兜底 + 回收宽限期 600s + 并发安全 + 零依赖）
- 无 webmap 集成（目标服不需要网页选图）
- 章节名从 mission 文件提取（大小写敏感，杜绝换图 No such map）

部署时请注意：**不要在服务器有真人时批量移动 addons 里的 VPK**（会炸服）。移图前先让玩家下线或选在凌晨。
