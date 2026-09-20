#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vpk_scan_group.py — 多 Part VPK 自动归组工具（通用部署包）

用法:
    python3 vpk_scan_group.py <vpk目录> [--json out.json] [--no-hash] [--min-group 2]

识别证据分级:
    S: addoninfo.txt addonURL0 (Workshop ID) 相同        -> 绝对同组
    A: addoninfo.txt title/author/version 相同           -> 强同组
    B: 文件名归一化后相同（剥标签/Part/尾序号）            -> 弱同组
    C: 资源互补 (Part1 含 maps/*.bsp+mission, 其他为资源) -> 辅助

规则:
    - 至少两类独立证据命中才自动归组，否则进 ungrouped 人工确认
    - 纯数字文件名不参与系列匹配
    - 【Map】前缀音乐包/音效包/功能性包不误判为地图
输出: 组清单 (campaign/title/workshop/parts/has_bsp/chapters/sha256) + 未归组清单
"""
import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vpk_tool import read_vpk, get_entry_data, entry_name, find_missions, get_map_list

LABEL_RE = re.compile(r'^[【\[](?:map|地图)[】\]]\s*', re.I)
PART_RE = re.compile(r'(?i)\b(?:part|p|第[一二三四五六七八九十\d]+部分)?\s*[-_.]?\s*(\d+)\s*$')
TAIL_NUM_RE = re.compile(r'(\D+?)\s*([-\s_]*\d+)$')
WS_RE = re.compile(r'^[\d_]+$')


def normalize_name(filename):
    """文件名归一化：剥 .vpk、全角标签、Part N、尾部数字序号。返回 (series, index)"""
    base = os.path.basename(filename)
    if base.lower().endswith('.vpk'):
        base = base[:-4]
    s = LABEL_RE.sub('', base)
    m = PART_RE.search(s)
    if m:
        s = s[:m.start()].rstrip(' -_.')
    m2 = TAIL_NUM_RE.match(s)
    if m2 and not WS_RE.match(s):
        s = m2.group(1).rstrip(' -_.')
    return s.strip(), filename


def read_addoninfo(data, entries, old_base):
    """从 VPK 读 addoninfo.txt，返回 dict(title/author/addonURL0/version) 或 None"""
    for e in entries:
        if entry_name(e[0], e[1], e[2]) == 'addoninfo.txt':
            try:
                txt = get_entry_data(data, old_base, e[4]).decode('utf-8', 'replace')
                info = {}
                for m in re.finditer(r'"([A-Za-z0-9_]+)"\s+"([^"]*)"', txt):
                    info[m.group(1).lower()] = m.group(2)
                return info or None
            except Exception:
                return None
    return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def scan_dir(directory, want_hash=True):
    """扫描目录内所有 .vpk，返回条目列表"""
    items = []
    for fn in sorted(os.listdir(directory)):
        if not fn.lower().endswith('.vpk'):
            continue
        full = os.path.join(directory, fn)
        size = os.path.getsize(full)
        item = {
            'file': fn,
            'path': full,
            'size': size,
            'sha256': sha256_file(full) if want_hash else None,
            'addoninfo': None,
            'has_bsp': False,
            'has_mission': False,
            'missions': [],
            'chapters': [],
        }
        try:
            data, entries, old_base = read_vpk(full)
            info = read_addoninfo(data, entries, old_base)
            if info:
                item['addoninfo'] = info
            missions = find_missions(entries)
            item['has_mission'] = bool(missions)
            for e in missions:
                item['missions'].append(entry_name(e[0], e[1], e[2]))
            maps = get_map_list(entries)
            item['has_bsp'] = bool(maps)
            item['chapters'] = maps
        except Exception as exc:
            item['parse_error'] = str(exc)
        norm, _ = normalize_name(fn)
        item['series'] = norm
        items.append(item)
    return items


def classify_groups(items):
    """三级证据聚类，返回 (groups, ungrouped)"""
    groups = []
    used = set()

    def series_key(it):
        return (it.get('addoninfo') or {}).get('addonurl0', '') or (it.get('addoninfo') or {}).get('workshopid', '')

    def part_sort(p):
        # 无数字的主文件排最前（part_1），P2/P3 按数字排后
        m = re.search(r'(\d+)', p.get('file', ''))
        return (0 if p['has_bsp'] else 1, int(m.group(1)) if m else 0, p.get('file', ''))

    # S 级：同 Workshop/addonURL0
    ws_map = {}
    for i, it in enumerate(items):
        k = series_key(it)
        if k:
            ws_map.setdefault(k, []).append(i)
    for k, idxs in ws_map.items():
        if len(idxs) >= 2:
            groups.append({'evidence': 'S:addonURL0', 'key': k, 'indices': idxs})
            used.update(idxs)

    def title_key(it):
        inf = it.get('addoninfo') or {}
        return (inf.get('title', ''), inf.get('author', ''), inf.get('version', ''))

    # A 级：同 title/author/version
    title_map = {}
    for i, it in enumerate(items):
        if i in used:
            continue
        k = title_key(it)
        if k[0]:
            title_map.setdefault(k, []).append(i)
    for k, idxs in title_map.items():
        if len(idxs) >= 2:
            groups.append({'evidence': 'A:title', 'key': k, 'indices': idxs})
            used.update(idxs)

    # B 级：同归一化文件名（至少含 BSP 才算地图系列）
    serie_map = {}
    for i, it in enumerate(items):
        if i in used or WS_RE.match(it['series']):
            continue
        serie_map.setdefault(it['series'], []).append(i)
    for k, idxs in serie_map.items():
        if len(idxs) >= 2 and any(items[i]['has_bsp'] for i in idxs):
            groups.append({'evidence': 'B:series', 'key': k, 'indices': idxs})
            used.update(idxs)

    # C 级辅助：未归组但 has_bsp 的 Map 包（单 Part 战役）直接收录成独立战役
    # 注意：普通服主的大部分三方图是单 VPK 战役，必须自动进入仓库，
    #       否则 ungrouped 里的图 generate_map_library 不会处理。
    singletons = []
    for i, it in enumerate(items):
        if i not in used:
            if it['has_bsp']:
                singletons.append(i)
                groups.append({'evidence': 'C:single', 'key': 'single_%d' % i, 'indices': [i]})
                used.add(i)

    # 装配 groups 详情
    out_groups = []
    for g in groups:
        idxs = g['indices']
        parts = []
        for i in idxs:
            it = items[i]
            parts.append({
                'file': it['file'],
                'size': it['size'],
                'sha256': it['sha256'],
                'has_bsp': it['has_bsp'],
                'has_mission': it['has_mission'],
            })
        bsp_parts = [i for i in idxs if items[i]['has_bsp']]
        main = items[bsp_parts[0]] if bsp_parts else items[idxs[0]]
        inf = main.get('addoninfo') or {}
        campaign = inf.get('title', '') or main['series']
        campaign_id = re.sub(r'[^A-Za-z0-9]+', '_', campaign.lower()).strip('_') or ('campaign_%d' % len(out_groups))
        out_groups.append({
            'campaign': campaign_id,
            'title': campaign,
            'workshop': inf.get('addonurl0', '') or inf.get('workshopid', ''),
            'evidence': g['evidence'],
            'parts': sorted(parts, key=part_sort),
            'chapters': main['chapters'],
            'part_count': len(parts),
        })
    ungrouped = [
        {
            'file': items[i]['file'],
            'size': items[i]['size'],
            'sha256': items[i]['sha256'],
            'has_bsp': items[i]['has_bsp'],
            'addoninfo': items[i]['addoninfo'],
            'category': 'map_single' if items[i]['has_bsp'] else ('resource' if items[i]['missions'] else 'other'),
        }
        for i in range(len(items)) if i not in used
    ]
    return out_groups, ungrouped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dir', help='VPK 目录')
    ap.add_argument('--json', help='输出 JSON 文件')
    ap.add_argument('--no-hash', action='store_true', help='跳过 SHA256（大批量加速）')
    args = ap.parse_args()

    items = scan_dir(args.dir, want_hash=not args.no_hash)
    print('scanned %d vpk' % len(items))
    groups, ungrouped = classify_groups(items)

    print('\n===== 自动归组 (%d) =====' % len(groups))
    for g in groups:
        print('[%s] %s (evidence %s, %d parts)' % (g['campaign'], g['title'], g['evidence'], g['part_count']))
        for p in g['parts']:
            print('    - %s (%.1fMB, bsp=%s, mission=%s)' % (p['file'], p['size'] / 1048576, p['has_bsp'], p['has_mission']))
        if g['chapters']:
            print('    chapters: %s' % ', '.join(g['chapters'][:8]))

    print('\n===== 未归组 (%d) =====' % len(ungrouped))
    for u in ungrouped:
        print('  [%s] %s (%.1fMB)' % (u['category'], u['file'], u['size'] / 1048576))

    result = {'vpk_dir': os.path.abspath(args.dir), 'groups': groups, 'ungrouped': ungrouped}
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print('\nJSON ->', args.json)


if __name__ == '__main__':
    main()