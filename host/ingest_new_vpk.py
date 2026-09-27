#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单图入库 ingest_new_vpk.py v2.2（版本替换 + 纯资源包替换 + keep_ 常驻联动）
把 addons 里的新地图 VPK 归组到 map_library + 更新 scan_result + 重生成 cfg/maplist。
用法: python3 ingest_new_vpk.py <game_root> <vpk_filename> [--keep]
  --keep 保留 addons 原文件（默认 move 入库）
返回 JSON: {ok, campaign, part, chapters, action, replaced?, keep_sync?, error?}
  action = replace    同图更新替换（旧 part 已归档到 <root>/map_library_archive/<key>/）
         = append     新分包/新章节追加（原行为）
         = duplicate  内容与库中某 part 完全相同，addons 源文件已清理
  keep_sync = [(op, filename), ...]  keep_ 常驻镜像联动结果（refreshed/added/removed）

v2（2026-09-24）：替换判定依据 = bsp 地图集合交集（不是 mission 名！wildride/blackmesa 分卷每 part mission 同名但 bsp 不同）。
v2.1（2026-09-24）：keep_ 常驻联动——replace/append 后把 map_library/<key>/ 全部 part 镜像到
  addons/keep_<key>_part_N.vpk（常驻热门图跟最新版）：刷新内容变化 part、删除 map_library 已无的
  多余 part、补上新 part。key 目录不存在时不动（人工管理）。内容相同（size+sha）不重拷。
v2.2（2026-09-25）：纯资源包（无 bsp）替换判定——原逻辑 b_new 为空时直接 append，导致
  作者更新贴图/音效 part 时旧资源包永留库中、新旧并存 stage 冲突（实测 202 库 133 个纯资源 part 中招）。
  新逻辑分层匹配：①新包有 addontitle → 找库内无 bsp 且标题一致的 part 替换；②无标题/无匹配 →
  按文件大小最接近（0.5x~2x 内，唯一最小 diff）替换；③等距歧义/超阈值 → 保守 append。
  资源包替换时保留旧 display（新资源包常无 addonname，避免 display 被覆盖成文件名）。
"""
import os, re, json, sys, shutil, subprocess, hashlib, time

# 跨平台：ONDEMAND_HOME 环境变量指定脚本目录（Linux 默认 /opt/ondemand，Windows 如 C:\ondemand）
ONDEMAND_HOME = os.environ.get('ONDEMAND_HOME', '/opt/ondemand')
PYTHON = os.environ.get('ONDEMAND_PYTHON', sys.executable) or 'python'

ROOT = sys.argv[1]
FN = sys.argv[2]
KEEP = '--keep' in sys.argv
ADDONS = os.path.join(ROOT, 'addons')
LIB = os.path.join(ROOT, 'map_library')
ARCHIVE = os.path.join(ROOT, 'map_library_archive')
SRC = os.path.join(ADDONS, FN)
SCAN = os.environ.get('OND_SCAN', os.path.join(ONDEMAND_HOME, 'scan_result.json'))

def out(d):
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0 if d.get('ok') else 1)

if not os.path.isfile(SRC):
    out({'ok': False, 'error': 'addons 中找不到 %s' % FN})

if FN.lower().startswith('ondemand_'):
    out({'ok': False, 'error': 'ondemand_ 前缀是 stage 副本，跳过入库'})

sys.path.insert(0, ONDEMAND_HOME)
import vpk_tool

def parse_mission_maps(text):
    """从 mission 文件提取章节 map 列表：优先 modes.coop 下的 Map，否则顶层 Map"""
    low = text
    m = re.search(r'"modes"\s*{', low, re.I)
    maps = []
    if m:
        rest = low[m.end():]
        depth = 1
        i = 0
        while i < len(rest) and depth > 0:
            if rest[i] == '{':
                depth += 1
            elif rest[i] == '}':
                depth -= 1
            i += 1
        modes_body = rest[:max(0, i - 1)]
        mc = re.search(r'"coop"\s*{', modes_body, re.I)
        if mc:
            rest2 = modes_body[mc.end():]
            depth = 1
            i = 0
            while i < len(rest2) and depth > 0:
                if rest2[i] == '{':
                    depth += 1
                elif rest2[i] == '}':
                    depth -= 1
                i += 1
            coop_body = rest2[:max(0, i - 1)]
            for mm in re.finditer(r'"map"\s*"([^"]+)"', coop_body, re.I):
                maps.append(mm.group(1))
    if not maps:
        for mm in re.finditer(r'"map"\s*"([^"]+)"', low, re.I):
            maps.append(mm.group(1))
    return maps

def sanitize_key(s):
    return re.sub(r'[^0-9a-zA-Z_]', '_', s).strip('_')

def part_num(p):
    m = re.search(r'(\d+)', p)
    return int(m.group(1)) if m else 0

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def read_addoninfo_title(path):
    """读 VPK 内 addoninfo.txt 的 addontitle（空 = 无标题/读取失败）"""
    try:
        data, entries, old_base = vpk_tool.read_vpk(path)
        for e in entries:
            n = vpk_tool.entry_name(e[0], e[1], e[2])
            if n == 'addoninfo.txt':
                ai = vpk_tool.get_entry_data(data, old_base, e[4]).decode('utf-8', 'replace')
                m = re.search(r'"addontitle"\s*"([^"]*)"', ai, re.I)
                if m and m.group(1).strip():
                    return m.group(1).strip()
                return ''
    except Exception:
        return ''
    return ''

def sync_keep_for_key(root, key):
    """把 map_library/<key>/ 全部 part 镜像到 addons/keep_<key>_part_N.vpk。
    key 目录不存在/无 part → 不动（人工管理）。返回 [(op, filename), ...]"""
    lib_dir = os.path.join(root, 'map_library', key)
    addons_dir = os.path.join(root, 'addons')
    if not os.path.isdir(lib_dir):
        return []
    parts = sorted([p for p in os.listdir(lib_dir) if re.fullmatch(r'part_\d+\.vpk', p)], key=part_num)
    if not parts:
        return []
    res = []
    prefix = 'keep_%s_part_' % key
    cur = {}
    for f in sorted(os.listdir(addons_dir)):
        if f.startswith(prefix) and f.endswith('.vpk'):
            cur[f] = os.path.join(addons_dir, f)
    expect = {}
    for p in parts:
        fn = 'keep_%s_%s' % (key, p)
        expect[fn] = (os.path.join(lib_dir, p), os.path.join(addons_dir, fn))
    # 1) 删除多余 keep_（map_library 已无对应 part）
    for f, fp in cur.items():
        if f not in expect:
            try:
                os.remove(fp)
                res.append(('removed', f))
            except Exception as e:
                res.append(('err', '%s remove: %s' % (f, e)))
    # 2) 刷新/新增
    for fn, (src, dst) in expect.items():
        need = True
        try:
            if os.path.isfile(dst):
                need = os.path.getsize(dst) != os.path.getsize(src)
                if not need and sha256_file(dst) == sha256_file(src):
                    need = False
        except Exception:
            need = True
        if need:
            tmp = dst + '.tmp'
            try:
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
                res.append(('refreshed' if os.path.isfile(dst) else 'added', fn))
            except Exception as e:
                res.append(('err', '%s copy: %s' % (fn, e)))
    return res

try:
    data, entries, old_base = vpk_tool.read_vpk(SRC)
except Exception as e:
    out({'ok': False, 'error': 'VPK 读取失败: %s' % e})

missions = vpk_tool.find_missions(entries)
if not missions:
    out({'ok': False, 'error': '无 mission 文件（功能包/资源包），不入库'})

miss_names = []
chapters = []
display = os.path.splitext(FN)[0]
for e in missions:
    n = vpk_tool.entry_name(e[0], e[1], e[2])
    miss_names.append(os.path.basename(n).rsplit('.', 1)[0])
    txt = vpk_tool.get_entry_data(data, old_base, e[4]).decode('utf-8', 'replace')
    ms = parse_mission_maps(txt)
    if ms:
        chapters = ms
        break
    if not chapters:
        for e2 in entries:
            n2 = vpk_tool.entry_name(e2[0], e2[1], e2[2])
            if n2 == 'addoninfo.txt':
                ai = vpk_tool.get_entry_data(data, old_base, e2[4]).decode('utf-8', 'replace')
                mm = re.search(r'"addonname"\s*"([^"]*)"', ai, re.I)
                if mm and mm.group(1).strip():
                    display = mm.group(1).strip()
                break

if not miss_names:
    out({'ok': False, 'error': 'mission 名提取失败'})

key = sanitize_key(miss_names[0])
if not key:
    out({'ok': False, 'error': 'campaign key 为空'})

key_dir = os.path.join(LIB, key)
os.makedirs(key_dir, exist_ok=True)

existing = [p for p in os.listdir(key_dir) if re.fullmatch(r'part_\d+\.vpk', p)]
existing.sort(key=part_num)
b_new = set(vpk_tool.get_map_list(entries))

# ===== v2: 版本替换判定（bsp 交集） =====
candidates = []  # [(part_name, part_num)]
if b_new and existing:
    for p in existing:
        pp = os.path.join(key_dir, p)
        try:
            _, p_entries, _ = vpk_tool.read_vpk(pp)
            b_old = set(vpk_tool.get_map_list(p_entries))
        except Exception:
            continue
        if b_new & b_old:
            candidates.append((p, part_num(p)))

# ===== v2.2: 纯资源包（无 bsp）替换判定 =====
# bsp 交集覆盖主图/分包更新；纯资源包（无 bsp = 贴图/音效 part）走标题+大小分层匹配，
# 否则旧逻辑 append 导致新旧资源包并存（133 个纯资源 part 实测中招）。
res_replace = False
if not candidates and not b_new and existing:
    new_title = read_addoninfo_title(SRC)
    new_size = os.path.getsize(SRC)
    # 库内无 bsp 的 part
    res_parts = []  # [(part_name, part_num, title, size)]
    for p in existing:
        pp = os.path.join(key_dir, p)
        try:
            _, p_entries, _ = vpk_tool.read_vpk(pp)
            if vpk_tool.get_map_list(p_entries):
                continue  # 只考虑无 bsp 的资源 part
        except Exception:
            continue
        res_parts.append((p, part_num(p), read_addoninfo_title(pp), os.path.getsize(pp)))
    if res_parts:
        # 第一层：标题一致（唯一匹配）
        if new_title:
            cand = [(c[0], c[1]) for c in res_parts if c[2] == new_title]
            if len(cand) == 1:
                candidates = cand
        # 第二层：无标题/标题无唯一匹配 → 大小最接近（0.25x~4x 内，唯一最小 diff）
        if not candidates:
            best = None
            best_diff = None
            for r in res_parts:
                if r[3] <= 0:
                    continue
                ratio = new_size / r[3]
                if ratio < 0.25 or ratio > 4.0:
                    continue  # 大小悬殊，不像同资源包更新
                diff = abs(new_size - r[3])
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    best = r
            if best is not None:
                # 等距歧义：多个 part 同最小 diff（如 poolcore part_1/part_3 都是 69788B）→ 保守 append
                ties = [r for r in res_parts if abs(abs(new_size - r[3]) - best_diff) < max(1, new_size * 0.01)]
                if len(ties) == 1:
                    candidates = [(best[0], best[1])]
        if candidates:
            res_replace = True

action = 'append'
replaced = []
keep_sync = []
nxt = max([part_num(p) for p in existing], default=0) + 1
dst_name = 'part_%d.vpk' % nxt

if candidates:
    # 1) 重复上传：sha256 完全相同 → 不归档不替换
    dup = None
    try:
        h_new = sha256_file(SRC)
        for p, pn in candidates:
            pp = os.path.join(key_dir, p)
            try:
                if os.path.getsize(pp) == os.path.getsize(SRC) and sha256_file(pp) == h_new:
                    dup = p
                    break
            except Exception:
                continue
    except Exception:
        h_new = None
    if dup:
        if not KEEP and os.path.abspath(SRC) != os.path.abspath(os.path.join(key_dir, dup)):
            os.remove(SRC)
        out({'ok': True, 'campaign': key, 'part': dup, 'chapters': chapters,
             'action': 'duplicate', 'replaced': [], 'keep_sync': [], 'display': display})
    # 2) 同图更新：归档候选 part 到 map_library_archive/<key>/，删除，新文件补位
    action = 'replace'
    ts = time.strftime('%Y%m%d_%H%M%S')
    for p, pn in candidates:
        src_p = os.path.join(key_dir, p)
        arch_dir = os.path.join(ARCHIVE, key)
        os.makedirs(arch_dir, exist_ok=True)
        arch_p = os.path.join(arch_dir, '%s.%s' % (p, ts))
        try:
            shutil.move(src_p, arch_p)
            replaced.append(p)
        except Exception as e:
            out({'ok': False, 'error': '归档 %s 失败: %s' % (p, e)})
    dst_name = 'part_%d.vpk' % min(pn for _, pn in candidates)
    nxt = min(pn for _, pn in candidates)

dst = os.path.join(key_dir, dst_name)
if os.path.abspath(SRC) != os.path.abspath(dst):
    if not KEEP:
        shutil.move(SRC, dst)
    else:
        shutil.copy2(SRC, dst)

# ===== v2.1: keep_ 常驻镜像联动（replace/append 都触发；duplicate 已 return） =====
keep_sync = sync_keep_for_key(ROOT, key)

# ===== scan_result 更新 =====
scan = {}
if os.path.isfile(SCAN):
    try:
        with open(SCAN, encoding='utf-8') as f:
            scan = json.load(f)
    except Exception:
        scan = {}
camps = scan.get('campaigns', {})
info = camps.get(key, {
    'display': display, 'version': '', 'mission': key,
    'parts': [], 'chapters': [],
})
if action == 'replace':
    for rp in replaced:
        if rp in info.get('parts', []):
            info['parts'].remove(rp)
    if res_replace:
        # 纯资源包替换：保留旧 display（新资源包常无 addonname，避免被文件名覆盖）
        pass
    else:
        info['display'] = display
elif info.get('display', '') == os.path.splitext(FN)[0] or not info.get('display'):
    info['display'] = display
if dst_name not in info['parts']:
    info['parts'].append(dst_name)
info['parts'] = sorted(info['parts'], key=part_num)
if chapters:
    if action == 'replace':
        info['chapters'] = chapters  # 同图更新章节跟最新版
    elif not info.get('chapters'):
        info['chapters'] = chapters
info['mission'] = key
camps[key] = info
scan['campaigns'] = camps
if 'non_campaign' not in scan:
    scan['non_campaign'] = []
if FN in scan.get('non_campaign', []):
    scan['non_campaign'].remove(FN)
try:
    with open(SCAN, 'w', encoding='utf-8') as f:
        json.dump(scan, f, ensure_ascii=False, indent=2)
except Exception as e:
    out({'ok': False, 'error': 'scan_result 写入失败: %s' % e})

try:
    subprocess.run([PYTHON, os.path.join(ONDEMAND_HOME, 'gen_ondemand_cfg2.py'), ROOT],
                   capture_output=True, text=True, timeout=120)
except Exception:
    pass
try:
    subprocess.run([PYTHON, os.path.join(ONDEMAND_HOME, 'export_authoritative_maplist.py'), ROOT],
                   capture_output=True, text=True, timeout=300)
except Exception:
    pass

out({'ok': True, 'campaign': key, 'part': dst_name,
     'chapters': chapters, 'action': action, 'replaced': replaced,
     'keep_sync': keep_sync, 'display': display})