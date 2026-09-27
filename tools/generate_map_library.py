#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_map_library.py — 从扫描结果生成 map_library 仓库 + bridge 配置（v2.0）

用法:
    python3 generate_map_library.py scan.json <游戏根目录>
    python3 generate_map_library.py scan.json <游戏根目录> --dry-run   # 只打印计划

行为（一条命令全搞定）:
    1. 按 vpk_scan_group.py 的归组结果，把 VPK 复制到 <游戏根>/map_library/<战役ID>/part_N.vpk
    2. 从 VPK 内 missions/*.txt 提取权威章节名（保留正确大小写，changelevel 依赖它）
       —— 这是与 v1.0 最大的区别：v1.0 用 bsp 路径（全小写）导致换图 No such map
    3. bsp 列表补漏（mission 文件缺失时兜底，原始大小写）
    4. 生成 addons/sourcemod/configs/ondemand_vpk.cfg（生产格式，与 202/45 农场一致）
    5. 生成 /opt/ondemand/scan_result.json（后续工具对账用；可 --scan-result 改路径）

依赖: tools/vpk_tool.py（同目录）
"""
import argparse
import json
import os
import re
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vpk_tool

CFG_PATH_REL = os.path.join('addons', 'sourcemod', 'configs', 'ondemand_vpk.cfg')
LIB_REL = 'map_library'


def sanitize_campaign(name):
    """campaign key 必须 sanitize：特殊字符会触发 SM Ignoring invalid section"""
    s = re.sub(r'[^0-9a-zA-Z_]+', '_', name).strip('_')
    return s or 'campaign'


def read_entry_data(path, tree_size, chunks):
    out = b""
    for archive, off, ln in chunks:
        try:
            with open(path, "rb") as f:
                f.seek(12 + tree_size + off)
                out += f.read(ln)
        except OSError:
            pass
    return out


def parse_mission_maps(text):
    """从 missions/*.txt 内容提取 coop 模式地图列表（权威章节，大小写敏感）"""
    m = re.search(r'"modes"\s*{', text, re.I)
    if m:
        rest = text[m.end():]
        depth, i = 1, 0
        while i < len(rest) and depth > 0:
            if rest[i] == "{":
                depth += 1
            elif rest[i] == "}":
                depth -= 1
            i += 1
        modes_body = rest[:max(0, i - 1)]
        mc = re.search(r'"coop"\s*{', modes_body, re.I)
        if mc:
            rest2 = modes_body[mc.end():]
            depth, i = 1, 0
            while i < len(rest2) and depth > 0:
                if rest2[i] == "{":
                    depth += 1
                elif rest2[i] == "}":
                    depth -= 1
                i += 1
            coop_body = rest2[:max(0, i - 1)]
            maps = re.findall(r'"map"\s*"([^"]+)"', coop_body, re.I)
            if maps:
                return maps
    return re.findall(r'"map"\s*"([^"]+)"', text, re.I)


def get_mission_texts(path):
    """从 VPK 提取 missions/*.txt 内容列表 [(mission名, 内容), ...]"""
    with open(path, 'rb') as f:
        head = f.read(12)
        if len(head) < 12:
            return []
        magic, version, tree_size = struct.unpack_from('<III', head, 0)
        if magic != 0x55AA1234:
            return []
        f.seek(12)
        tree = f.read(tree_size)
    entries = vpk_tool.parse_tree(tree)
    out = []
    for e in entries:
        n = vpk_tool.entry_name(e[0], e[1], e[2])
        if n.endswith('.txt') and ('scripts/missions/' in n or n.startswith('missions/')):
            txt = read_entry_data(path, tree_size, e[4]).decode('utf-8', 'replace')
            base = os.path.splitext(os.path.basename(n))[0]
            out.append((base, txt))
    return out


def get_bsp_list_original_case(path):
    """从 VPK 提取 bsp 名（保留原始大小写！vpk_tool.entry_name 会 lower，这里直接读原始 base）"""
    with open(path, 'rb') as f:
        head = f.read(12)
        if len(head) < 12:
            return []
        magic, version, tree_size = struct.unpack_from('<III', head, 0)
        if magic != 0x55AA1234:
            return []
        f.seek(12)
        tree = f.read(tree_size)
    entries = vpk_tool.parse_tree(tree)
    maps = []
    for e in entries:
        ext, dirname, base = e[0], e[1], e[2]
        dirname_s = dirname.decode('latin-1', 'replace').replace('\\', '/').lower()
        if dirname_s in ('maps', 'maps/') and ext == b'bsp' and base != b' ':
            maps.append(base.decode('latin-1', 'replace'))
    return maps


def parse_mission_display_title(text):
    """从 missions/*.txt 内容提取 DisplayTitle（没有 addoninfo 时的显示名）"""
    m = re.search(r'"DisplayTitle"\s*"([^"]+)"', text)
    if m:
        return m.group(1).strip()
    return ''


def extract_authoritative_chapters(parts_dir):
    """权威章节：mission 文件内容优先（大小写敏感）+ bsp 补漏（原始大小写，去重）
    返回 (mission_name, chapters, display_title)"""
    parts = sorted([p for p in os.listdir(parts_dir) if re.fullmatch(r'part_\d+\.vpk', p)],
                   key=lambda x: int(re.search(r'(\d+)', x).group(1)))
    auth = []
    mission_name = None
    display_title = ''
    for p in parts:
        mis = get_mission_texts(os.path.join(parts_dir, p))
        if mis:
            mission_name = mis[0][0]
            for _, txt in mis:
                auth = parse_mission_maps(txt)
                if not display_title:
                    display_title = parse_mission_display_title(txt)
                if auth:
                    break
            if auth:
                break
    bsp_all = []
    for p in parts:
        bsp_all.extend(get_bsp_list_original_case(os.path.join(parts_dir, p)))
    merged = list(auth)
    seen_lower = {m.lower() for m in auth}
    for b in bsp_all:
        if b.lower() not in seen_lower:
            merged.append(b)
            seen_lower.add(b.lower())
    return mission_name, merged, display_title


def build_cfg(campaigns):
    """生产格式 cfg（与 202/45 农场完全一致）"""
    lines = ['"OnDemandVPK"', '{']
    for key in sorted(campaigns):
        info = campaigns[key]
        chapters = info['chapters']
        parts = info['parts']
        display = info['display']
        lines.append(f'    "{key}"')
        lines.append('    {')
        lines.append(f'        "display"       "{display}"')
        lines.append(f'        "mission"       "{key}"')
        lines.append(f'        "first_map"     "{chapters[0] if chapters else ""}"')
        lines.append(f'        "part_count"    "{len(parts)}"')
        for i, p in enumerate(parts, 1):
            lines.append(f'        "part_{i}"        "map_library/{key}/{p}"')
            lines.append(f'        "target_{i}"      "addons/ondemand_{key}_part_{i}.vpk"')
        lines.append(f'        "chapter_count" "{len(chapters)}"')
        for i, m in enumerate(chapters, 1):
            lines.append(f'        "chapter_{i}"     "{m}"')
            lines.append(f'        "chapter_display_{i}" "{i}: {m}"')
        lines.append('    }')
    lines.append('}')
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scan_json', help='vpk_scan_group.py 输出的 JSON')
    ap.add_argument('game_root', help='服务器 left4dead2 根目录')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--scan-result', default=os.path.join(os.environ.get('ONDEMAND_HOME', '/opt/ondemand'), 'scan_result.json'),
                    help='scan_result.json 输出路径（默认 <ONDEMAND_HOME>/scan_result.json）')
    args = ap.parse_args()

    with open(args.scan_json, encoding='utf-8') as f:
        scan = json.load(f)
    groups = scan.get('groups', [])
    vpk_dir = scan.get('vpk_dir') or os.path.dirname(os.path.abspath(args.scan_json))
    lib_root = os.path.join(args.game_root, LIB_REL)
    cfg_campaigns = {}
    skipped = []

    for g in groups:
        campaign = sanitize_campaign(g.get('campaign') or g.get('title') or 'campaign')
        title = g.get('title') or campaign
        parts = g.get('parts') or []
        camp_dir = os.path.join(lib_root, campaign)
        print(f'=== {campaign} ({title}) {len(parts)} parts ===')

        copied_parts = []
        for i, p in enumerate(parts, 1):
            # 源目录优先级：scan.json 里记录的 vpk_dir → scan.json 所在目录 → game_root/addons
            candidates = [
                os.path.join(vpk_dir, p.get('file', '')),
                os.path.join(os.path.dirname(os.path.abspath(args.scan_json)), p.get('file', '')),
                os.path.join(args.game_root, 'addons', p.get('file', '')),
            ]
            src = next((c for c in candidates if os.path.exists(c)), None)
            if not src:
                print(f'  !! 源文件缺失: {p.get("file")}')
                skipped.append(p.get('file'))
                continue
            dst = os.path.join(camp_dir, f'part_{i}.vpk')
            if args.dry_run:
                print(f'  [dry] {os.path.basename(src)} -> {dst}')
            else:
                os.makedirs(camp_dir, exist_ok=True)
                shutil.copy2(src, dst)
                print(f'  {os.path.basename(src)} -> part_{i}.vpk')
            copied_parts.append(f'part_{i}.vpk')

        if not copied_parts:
            print('  !! 无任何文件复制成功，跳过')
            continue

        # 权威章节提取（从 map_library 已落盘的文件）
        if not args.dry_run:
            mission_name, chapters, display_title = extract_authoritative_chapters(camp_dir)
            if display_title:
                title = display_title
        else:
            mission_name, chapters, display_title = None, [], ''
        if not chapters:
            print(f'  !! {campaign} 未提取到章节（无 mission 文件且无 bsp），仍会写 cfg 但无法换图')
        cfg_campaigns[campaign] = {
            'display': title,
            'mission': mission_name or campaign,
            'parts': copied_parts,
            'chapters': chapters,
        }

    if args.dry_run:
        print('\n[dry] 未复制/未写 cfg（以上为计划）')
        return

    # 写 cfg
    cfg_path = os.path.join(args.game_root, CFG_PATH_REL)
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, 'w', encoding='utf-8') as f:
        f.write(build_cfg(cfg_campaigns))
    print(f'\ncfg -> {cfg_path} (campaigns={len(cfg_campaigns)})')

    # 写 scan_result.json（对账/后续工具用）
    os.makedirs(os.path.dirname(args.scan_result), exist_ok=True)
    with open(args.scan_result, 'w', encoding='utf-8') as f:
        json.dump({'campaigns': {k: {'display': v['display'], 'mission': v['mission'],
                                     'parts': v['parts'], 'chapters': v['chapters']}
                                 for k, v in cfg_campaigns.items()}},
                  f, ensure_ascii=False, indent=1)
    print(f'scan_result -> {args.scan_result}')

    if skipped:
        print(f'\n⚠ 有 {len(skipped)} 个文件未复制（源缺失），已在上面列出')

    print('''
下一步：
  1) 把 addons 里还留着的老三方 VPK 移走（备份到 addons_off/），只留官图+功能包：
       mkdir -p <游戏根>/addons_off && mv <游戏根>/addons/*.vpk <游戏根>/addons_off/   # 注意分批/空服操作
  2) 装插件 + 跑控制器（见 README.md）
  3) RCON: sm plugins load ondemand_vpk_bridge; sm plugins reload l4d2_map_vote
  4) 玩家 !chmap 换图验证
''')


if __name__ == '__main__':
    main()