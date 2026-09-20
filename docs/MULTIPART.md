# 多 Part VPK 识别与 FAQ（v2.0）

## 为什么需要识别多 Part

三方战役常拆成 `Part 1/2/3`（如毁灭天堂 Part1=441MB 含地图，Part2/3=资源补充）。
按需加载必须**完整组整体移动**——只拿含 BSP 的 Part1 会导致材质/模型缺失。

## 证据分级（vpk_scan_group.py 自动归组依据）

| 等级 | 证据 | 可信度 |
|---|---|---|
| S | VPK 内 `addoninfo.txt` 的 `addonURL0`/Workshop ID 相同 | 绝对同组 |
| A | `addoninfo.txt` 的 title/author/version 相同 | 强同组 |
| B | 文件名归一化后相同（且组内含 BSP） | 弱同组 |
| C | 资源互补：Part1 含 bsp+mission，其他为资源 | 辅助 |

规则：**至少两类独立证据命中才自动归组**，否则进 `ungrouped` 人工确认。

## 文件名归一化规则

```text
1. 剥 .vpk
2. 剥全角标签：【Map】/【地图】前缀
3. 剥 Part 标记：Part N / P2 / 第N部分 / (-_N)
4. 剥尾部数字序号：大坝危机(Reservoir)2 → 大坝危机(Reservoir)
5. 纯数字文件名（workshop id 形式）不参与系列匹配
```

## 反例守恒（改算法必须重跑）

- `【Map】布宜诺斯艾利斯 音乐包.vpk` → 纯音频，保持音频分类
- `0resort1_pak1.vpk` → 音效包，保持原分类
- `半条命2补丁.vpk` → 功能性，保持原分类
- 只有文件名【Map】前缀而无 BSP 家族 → 不归地图

## 工具用法

```bash
# 1. 扫描归组（推荐 --no-hash 大批量加速）
python3 tools/vpk_scan_group.py /path/to/vpks --json scan.json

# 2. 生成 map_library + 服务器配置（v2.0 自动做权威章节提取）
python3 tools/generate_map_library.py scan.json /shared/left4dead2
```

输出解释：
- `groups[]` → 自动归组（campaign/title/parts/evidence）
- `ungrouped[]` → 未归组（category: map_single=单图战役 / resource=含mission资源 / other）

## 章节列表来自哪（v2.0 修正）

v1.0 从 VPK 内 bsp 文件名提取章节 → 全是小写 → 换图 `No such map`（L4D2 地图名区分大小写）。
v2.0 改为：
1. **权威**：从 VPK 内 `missions/*.txt` 内容提取 `modes.coop` 的 `map` 字段（**保留正确大小写**）
2. **补漏**：bsp 文件列表补漏（mission 缺失时兜底，原始大小写，去重）

换图失败 `No such map` 时，重跑 `generate_map_library.py` 即可。

## 人工补组的场景

- `0resort1_maps.vpk` + `0resort1_pak1/2.vpk`（文件名不归一、addoninfo 不同）：
  scanner 会分开，生产确认它们是配套后，可手动把 pak 文件放进同 campaign 目录
  （`map_library/0resort1/` 下命名 `part_2.vpk`、`part_3.vpk`），
  再重跑 `generate_map_library.py`（会自动重算 part 列表并写 cfg）。

## FAQ

**Q: VPK 内没有 addoninfo.txt 怎么办？**
靠文件名归一化 + BSP 判定。无 BSP 且无 title 的包进 ungrouped/other。

**Q: 多 Part 里 Part1 一定是含 BSP 的那个吗？**
通常如此，但工具不假设：按 `has_bsp` 排序，无 BSP 的组内成员按文件名顺序命名 part_N。

**Q: 识别错了会怎样？**
多 Part 拆散 → 加载后缺资源；误归组 → 加载多余文件。所以宁可进 ungrouped 人工确认，
也不自动猜。改完 `normalize_name` 必须重跑反例断言（上面的反例清单）。