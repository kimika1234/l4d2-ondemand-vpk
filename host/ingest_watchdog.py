# -*- coding: utf-8 -*-
"""addons 新图自动入库 watchdog（202/45 宿主）
扫描 addons 中非 ondemand_ 前缀、非功能包、mtime 稳定 >300s 的 vpk，
自动调 ingest_new_vpk.py 归组到 map_library。
处理过的文件名记入状态文件，避免重复处理。
"""
import os, re, sys, time, subprocess, hashlib

GAME_ROOT = sys.argv[1]
ADDONS = os.path.join(GAME_ROOT, "addons")
STATE = "/opt/ondemand/ingest_watchdog_state.json"
STABLE_AFTER = 300  # 文件 mtime 稳定秒数
KNOWN_NON_MAP = set()  # 预留：明确非地图名单（默认按 ingest 脚本自动判断）

def load_state():
    import json
    try:
        with open(STATE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_state(state):
    import json
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(sorted(state), f, ensure_ascii=False, indent=0)
    except Exception:
        pass

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
        if fn in state:
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
        # 再次确认 mtime 稳定（避免快照竞态）
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
        tail = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
        msg = tail
        if not proc.stdout:
            msg = (proc.stderr or "")[-200:]
        state.add(fn)
        print(f"[{time.strftime('%H:%M:%S')}] {fn} -> {msg[:160]}")
    save_state(state)

if __name__ == "__main__":
    main()