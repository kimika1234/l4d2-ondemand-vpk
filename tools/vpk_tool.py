#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPK v1 工具 (L4D2):
  check  <vpk>          : 检查对抗模式 (打印 mission 的 versus 状态)
  process <in> <out>    : 注入对抗模式 (modes 补全) + 温和精简, 一步完成
  list   <vpk>          : 列出条目 (前 60 + 总数)
部署: g7 /www/maps/vpk_tool.py (药服传图用)
"""
import struct
import sys
import os
import re

RAW_VPK_MAGIC = 0x55AA1234
TERMINATOR = 0xFFFF


def read_cstr(data, pos):
    end = data.index(b"\x00", pos)
    return data[pos:end], end + 1


def parse_tree(tree):
    entries = []
    pos = 0
    while True:
        ext, pos = read_cstr(tree, pos)
        if not ext:
            break
        while True:
            dirname, pos = read_cstr(tree, pos)
            if not dirname:
                break
            while True:
                base, pos = read_cstr(tree, pos)
                if not base:
                    break
                crc = struct.unpack_from("<I", tree, pos)[0]
                pos += 4
                meta_len = struct.unpack_from("<H", tree, pos)[0]
                pos += 2
                chunks = []
                while True:
                    archive = struct.unpack_from("<H", tree, pos)[0]
                    pos += 2
                    if archive == TERMINATOR:
                        break
                    off, ln = struct.unpack_from("<II", tree, pos)
                    pos += 8
                    chunks.append((archive, off, ln))
                meta = tree[pos:pos + meta_len]
                pos += meta_len
                entries.append((ext, dirname, base, crc, chunks, meta))
    return entries


def entry_name(ext, dirname, base):
    name = ""
    if dirname != b" ":
        name += dirname.decode("latin-1") + "/"
    if base != b" ":
        name += base.decode("latin-1")
    if ext != b" ":
        name += "." + ext.decode("latin-1")
    return name.replace("\\", "/").lower()


def read_vpk(src):
    with open(src, "rb") as f:
        data = f.read()
    magic, version, tree_size = struct.unpack_from("<III", data, 0)
    if magic != RAW_VPK_MAGIC or version != 1:
        raise ValueError("仅支持 VPK v1 (magic=%08x v=%d)" % (magic, version))
    tree = data[12:12 + tree_size]
    entries = parse_tree(tree)
    old_base = 12 + tree_size
    return data, entries, old_base


def get_entry_data(data, old_base, chunks):
    out = b""
    for _, off, ln in chunks:
        out += data[old_base + off:old_base + off + ln]
    return out


def find_missions(entries):
    """mission 文件: missions/ 根 或 scripts/missions/"""
    found = []
    for e in entries:
        n = entry_name(e[0], e[1], e[2])
        if n.endswith(".txt") and ("scripts/missions/" in n or n.startswith("missions/")):
            found.append(e)
    return found


def check_versus(vpk):
    """返回 (has_mission, has_versus, details)"""
    data, entries, old_base = read_vpk(vpk)
    missions = find_missions(entries)
    if not missions:
        return False, False, "无 mission 文件"
    has_vs = False
    names = []
    for e in missions:
        n = entry_name(e[0], e[1], e[2])
        names.append(n)
        txt = get_entry_data(data, old_base, e[4]).decode("utf-8", "replace")
        low = txt.lower()
        modes_match = re.search(r'"modes"\s*\{', low)
        vs_ok = False
        if modes_match:
            rest = low[modes_match.end():]
            depth = 1
            i = 0
            while i < len(rest) and depth > 0:
                if rest[i] == "{":
                    depth += 1
                elif rest[i] == "}":
                    depth -= 1
                i += 1
            modes_body = rest[:i - 1]
            vs_ok = bool(re.search(r'"versus"\s*\{', modes_body))
        if not vs_ok:
            vs_ok = bool(re.search(r'"versus"\s*"1"', low))
        if vs_ok:
            has_vs = True
    return True, has_vs, ";".join(names)


def get_map_list(entries):
    names = []
    for e in entries:
        n = entry_name(e[0], e[1], e[2])
        if n.startswith("maps/") and n.endswith(".bsp"):
            names.append(n[len("maps/"):-len(".bsp")])
    names.sort(key=lambda x: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", x)])
    return names


def should_remove(ext, dirname, base):
    """温和精简 (与 TrimVPKForServer 同规则)"""
    name = entry_name(ext, dirname, base)
    e = name.rsplit(".", 1)[-1] if "." in name else ""
    if e in ("vmf", "vmx"):
        return True
    if name.startswith("materials/"):
        return e == "vtf"
    if name.startswith("sound/") or name.startswith("sounds/"):
        return e in ("mp3", "wav")
    if name.startswith("models/"):
        return e in ("vvd", "vtx")
    return False


def inject_versus(entry_data, map_list=None):
    """
    mission 补全对抗: 已有 modes.versus 不动; 有 modes 无 versus 复制 coop;
    无 modes 从 map_list 生成 modes 块 (coop + versus)
    """
    txt = entry_data.decode("utf-8", "replace")
    low = txt.lower()
    modes_match = re.search(r'"modes"\s*\{', low)
    if modes_match:
        rest = low[modes_match.end():]
        depth = 1
        i = 0
        while i < len(rest) and depth > 0:
            if rest[i] == "{":
                depth += 1
            elif rest[i] == "}":
                depth -= 1
            i += 1
        modes_body = rest[:i - 1]
        if re.search(r'"versus"\s*\{', modes_body):
            return entry_data, False
        coop_match = re.search(r'"coop"\s*\{', modes_body)
        if coop_match:
            depth = 1
            j = coop_match.end()
            while j < len(modes_body) and depth > 0:
                if modes_body[j] == "{":
                    depth += 1
                elif modes_body[j] == "}":
                    depth -= 1
                j += 1
            coop_body = modes_body[coop_match.end():j - 1]
            vs_block = '\n\t\t"versus"\n\t\t{\n' + coop_body + '\n\t\t}\n'
            m_idx = txt.lower().find('"modes"')
            insert_at = txt.find("{", m_idx) + 1
            new = txt[:insert_at] + vs_block + txt[insert_at:]
            return new.encode("utf-8"), True
        if map_list:
            vs_block = build_modes_block(map_list, only_versus=True)
            m_idx = txt.lower().find('"modes"')
            insert_at = txt.find("{", m_idx) + 1
            new = txt[:insert_at] + vs_block + txt[insert_at:]
            return new.encode("utf-8"), True
        return entry_data, False
    if map_list:
        modes_block = build_modes_block(map_list)
        idx = txt.find("{")
        if idx < 0:
            return entry_data, False
        new = txt[:idx + 1] + modes_block + txt[idx + 1:]
        return new.encode("utf-8"), True
    # 兜底: 布尔声明
    if '"versus"' in low:
        if re.search(r'"versus"\s*"1"', low):
            return entry_data, False
        new = re.sub(r'"versus"\s*"\d"', '"versus"\t\t"1"', txt, flags=re.I, count=1)
        return new.encode("utf-8"), True
    idx = txt.find("{")
    if idx < 0:
        return entry_data, False
    insert = '\n\t\t"versus"\t\t"1"\n'
    new = txt[:idx + 1] + insert + txt[idx + 1:]
    return new.encode("utf-8"), True


def build_modes_block(map_list, only_versus=False):
    lines = ['\n\t"modes"\n\t{']
    for mode in (["versus"] if only_versus else ["coop", "versus"]):
        lines.append('\t\t"%s"\n\t\t{' % mode)
        for i, m in enumerate(map_list, 1):
            lines.append(
                '\t\t\t"%d"\n\t\t\t{\n\t\t\t\t"Map"\t"%s"\n\t\t\t\t"DisplayName"\t"%s"\n\t\t\t}'
                % (i, m, m)
            )
        lines.append("\t\t}\n")
    lines.append("\t}\n")
    return "\n".join(lines)


def rebuild_vpk(entries_with_data, out_path):
    out_data = bytearray()
    kept = []
    for ext, dirname, base, crc, meta, edata in entries_with_data:
        chunks = []
        if edata:
            chunks = [(0x7FFF, len(out_data), len(edata))]
            out_data += edata
        kept.append((ext, dirname, base, crc, chunks, meta))
    out_tree = bytearray()
    last_ext = last_dir = None
    for ext, dirname, base, crc, chunks, meta in kept:
        if last_ext is None or ext != last_ext:
            if last_ext is not None:
                out_tree += b"\x00\x00"
            out_tree += ext + b"\x00"
            out_tree += dirname + b"\x00"
            last_ext, last_dir = ext, dirname
        elif dirname != last_dir:
            out_tree += b"\x00"
            out_tree += dirname + b"\x00"
            last_dir = dirname
        out_tree += base + b"\x00"
        out_tree += struct.pack("<I", crc)
        out_tree += struct.pack("<H", len(meta))
        for archive, off, ln in chunks:
            out_tree += struct.pack("<H", archive)
            out_tree += struct.pack("<II", off, ln)
        out_tree += struct.pack("<H", TERMINATOR)
        out_tree += meta
    if last_ext is not None:
        out_tree += b"\x00\x00\x00"
    with open(out_path, "wb") as f:
        f.write(struct.pack("<III", RAW_VPK_MAGIC, 1, len(out_tree)))
        f.write(out_tree)
        f.write(out_data)


def process(vpk, out):
    data, entries, old_base = read_vpk(vpk)
    map_list = get_map_list(entries)
    new_entries = []
    vs_added = 0
    for e in entries:
        ext, dirname, base, crc, chunks, meta = e
        name = entry_name(ext, dirname, base)
        edata = get_entry_data(data, old_base, chunks)
        if name.endswith(".txt") and ("scripts/missions/" in name or name.startswith("missions/")):
            edata, changed = inject_versus(edata, map_list)
            if changed:
                vs_added += 1
        if should_remove(ext, dirname, base):
            continue
        new_entries.append((ext, dirname, base, crc, meta, edata))
    rebuild_vpk(new_entries, out)
    return vs_added, len(entries) - len(new_entries)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "list":
        try:
            data, entries, old_base = read_vpk(sys.argv[2])
            names = sorted(entry_name(e[0], e[1], e[2]) for e in entries)
            for n in names[:60]:
                print(n)
            print("TOTAL %d" % len(names))
        except Exception as e:
            print("ERR:%s" % e)
    elif cmd == "check":
        try:
            has_m, has_vs, det = check_versus(sys.argv[2])
            print("mission=%s versus=%s %s" % ("有" if has_m else "无", "有" if has_vs else "无", det))
        except Exception as e:
            print("ERR:%s" % e)
    elif cmd == "process":
        try:
            vs, rm = process(sys.argv[2], sys.argv[3])
            print("OK vs_added=%d removed=%d out=%.1fMB" % (vs, rm, os.path.getsize(sys.argv[3]) / 1048576))
        except Exception as e:
            print("ERR:%s" % e)
