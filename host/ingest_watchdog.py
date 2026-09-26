# -*- coding: utf-8 -*-
"""addons 新图自动入库 watchdog v2.2（2026-09-27）
扫描 addons 中非 ondemand_ 前缀、非功能包、mtime 稳定 >300s 的 vpk，
自动调 ingest_new_vpk.py 归组到 map_library。

v2.2 变更（2026-09-27，103 新家 95 个滞留实锤驱动）：
1. 失败不进 state：仅当 ingest 明确成功（ok / duplicate）才记入状态，
   被拒文件（无 mission 纯资源包等）下次自动重试，不再永久跳过。
2. 宽容归组兜底：ingest 拒绝「无 mission（功能包/资源包）」时，尝试按文件名
   英文关键词 + VPK 内 bsp 前缀匹配 scan_result 已有战役目录 → append 进
   map_library/<key>/part_N.vpk（对标 45 vpk_move_to_library3 的归组逻辑，
   解决汽水多分卷战役 Part 2+ 纯资源包滞留 addons 热区的问题）。
3. 归组成功同样记 state；仍无法归属的（真孤儿）不记 state 但计数重试，
   连续 RETRY_LIMIT 次仍无归属后记入 state 放弃（防日志刷屏）。

状态文件结构升级：{"done": {"<fn>": <n>}, "retries": {"<fn>": <n>}}
（兼容旧版纯数组：load 时旧数组自动转成 done dict）
"""
import os, re, sys, time, subprocess, json, shutil

GAME_ROOT = sys.argv[1]
ADDONS = os.path.join(GAME_ROOT, "addons")
LIB = os.path.join(GAME_ROOT, "map_library")
STATE = "/opt/ondemand/ingest_watchdog_state.json"
SCAN = "/opt/ondemand/scan_result.json"
STABLE_AFTER = 300  # 文件 mtime 稳定秒数
RETRY_LIMIT = 5     # 真孤儿连续重试上限（防日志刷屏，超过记 state 放弃）

def load_state():
    """兼容旧版 list 与新版 dict 两种结构"""
    try:
        with open(STATE, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return {"done": {x: 0 for x in raw}, "retries": {}}
        if isinstance(raw, dict):
            return {"done": raw.get("done", {}), "retries": raw.get("retries", {})}
    except Exception:
        pass
    return {"done": {}, "retries": {}}

def save_state(state):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump({"done": state["done"], "retries": state["retries"]},
                      f, ensure_ascii=False, indent=0)
    except Exception:
        pass

def norm(s):
    return re.sub(r"[^0-9a-z]+", "_", s.lower()).strip("_")

def part_num(name):
    m = re.search(r"(?:part|p)\s*(\d+)", name, re.I)
    return int(m.group(1)) if m else None

def clean_base(s):
    """文件名/display 归一：去 .vpk / 【Map】/ Part N → norm"""
    s = s.replace(".vpk", "").replace("【Map】", "").replace("【", "").replace("】", "").strip()
    s = re.sub(r"(?:part|p)\s*\d+", "", s, flags=re.I)
    return norm(s)

def load_scan_campaigns():
    """scan_result campaigns: key -> info + display 反查索引"""
    try:
        with open(SCAN, encoding="utf-8") as f:
            scan = json.load(f)
        camps = scan.get("campaigns", {})
        idx = {}
        for k, v in camps.items():
            idx[norm(k)] = k
            disp = str(v.get("display", ""))
            if disp:
                cb = clean_base(disp)
                if cb:
                    idx[cb] = k
        return camps, idx
    except Exception:
        return {}, {}

def read_vpk_bsp_prefixes(path):
    """读 VPK 内 bsp 文件名（轻量，只解析 tree）"""
    try:
        sys.path.insert(0, "/opt/ondemand")
        import vpk_tool
        data, entries, old_base = vpk_tool.read_vpk(path)
        bsp = set()
        for e in entries:
            if e[0] == b"bsp" and e[2]:
                bsp.add(os.path.basename(e[2].decode("utf-8", "replace")).rsplit(".", 1)[0].lower())
        return bsp
    except Exception:
        return set()

def find_group_target(fn):
    """宽容归组目标：中文 display 子串 → 文件名/display norm → bsp 前缀匹配已有战役。
    返回 (key, part) 或 None。对标 vpk_move_to_library3 + scan_result display 中文反查。"""
    camps, idx = load_scan_campaigns()
    if not camps:
        return None
    pnum = part_num(fn)
    base = clean_base(fn)
    # 0) 文件名中文段 ⊆ display（最可靠，103 实测：地心引力=dxyl / 地狱景象=viewofhell 全靠这个）
    cn_parts = re.findall(r"[\u4e00-\u9fff]+", fn)
    if cn_parts:
        for cn in cn_parts:
            if len(cn) < 2:
                continue
            for k, v in camps.items():
                if cn in str(v.get("display", "")):
                    return k, pnum
    # 1) 文件名 norm 精确
    if base and base in idx:
        return idx[base], pnum
    # 2) 文件名 norm 前缀（>=6）
    if base and len(base) >= 6:
        for kk, tk in idx.items():
            if len(kk) >= 6 and (kk.startswith(base[:6]) or base.startswith(kk[:6])):
                return tk, pnum
    # 3) bsp 前缀匹配（长 key）
    bsp = read_vpk_bsp_prefixes(os.path.join(ADDONS, fn))
    if bsp:
        for bn in sorted(bsp):
            bnc = norm(bn)
            if len(bnc) < 6:
                continue
            for kk, tk in idx.items():
                if len(kk) >= 8 and (kk.startswith(bnc[:8]) or bnc.startswith(kk[:8])):
                    return tk, pnum
    return None

def group_append(fn, key, pnum):
    """把 addons 文件 move 到 map_library/<key>/part_N.vpk，返回 True/False"""
    try:
        dstdir = os.path.join(LIB, key)
        os.makedirs(dstdir, exist_ok=True)
        dst = os.path.join(dstdir, "part_%d.vpk" % pnum) if pnum else os.path.join(dstdir, fn)
        if os.path.exists(dst):
            dst = dst + ".dup"
        shutil.move(os.path.join(ADDONS, fn), dst)
        return True
    except Exception:
        return False

def ingest_ok(msg):
    return ('"ok": true' in msg or '"ok": True' in msg or "duplicate" in msg.lower())

def mark_done(state, fn):
    state["done"][fn] = state["done"].get(fn, 0) + 1

def mark_retry(state, fn, reason):
    n = state["retries"].get(fn, 0) + 1
    if n >= RETRY_LIMIT:
        mark_done(state, fn)
        print(f"[{time.strftime('%H:%M:%S')}] {fn} -> GIVE-UP after {n} retries ({reason})")
    else:
        state["retries"][fn] = n
        print(f"[{time.strftime('%H:%M:%S')}] {fn} -> RETRY {n}/{RETRY_LIMIT} ({reason})")

def main():
    state = load_state()
    now = time.time()
    if not os.path.isdir(ADDONS):
        print("addons 目录不存在:", ADDONS)
        return
    candidates = []
    for fn in sorted(os.listdir(ADDONS)):
        if not fn.lower().endswith(".vpk"):
            continue
        if fn.lower().startswith("ondemand_"):
            continue  # stage 副本
        if fn.lower().startswith("keep_"):
            continue  # 热门常驻图（keep_ 前缀），不回收不误入库
        if fn in state["done"]:
            continue
        p = os.path.join(ADDONS, fn)
        try:
            mtime = os.path.getmtime(p)
        except OSError:
            continue
        if now - mtime < STABLE_AFTER:
            continue  # 可能还在上传/写入
        candidates.append(fn)
    if not candidates:
        return
    for fn in candidates:
        p = os.path.join(ADDONS, fn)
        try:
            m1 = os.path.getmtime(p)
        except OSError:
            continue
        time.sleep(0.5)
        try:
            m2 = os.path.getmtime(p)
        except OSError:
            continue
        if abs(m1 - m2) > 2:
            continue
        proc = subprocess.run(
            ["python3", "/opt/ondemand/ingest_new_vpk.py", GAME_ROOT, fn],
            capture_output=True, text=True, timeout=600,
        )
        msg = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
        if not proc.stdout:
            msg = (proc.stderr or "")[-200:]

        if ingest_ok(msg):
            mark_done(state, fn)
            print(f"[{time.strftime('%H:%M:%S')}] {fn} -> OK {msg[:160]}")
        elif "无 mission" in msg or "mission 名提取失败" in msg or "VPK 读取失败" in msg:
            grp = find_group_target(fn)
            if grp:
                key, pnum = grp
                if group_append(fn, key, pnum):
                    mark_done(state, fn)
                    print(f"[{time.strftime('%H:%M:%S')}] {fn} -> LENIENT-GROUP {key}/part_{pnum}.vpk")
                else:
                    mark_retry(state, fn, "group-failed")
            else:
                mark_retry(state, fn, "no-target")
        else:
            mark_retry(state, fn, "other")
    save_state(state)

if __name__ == "__main__":
    main()
