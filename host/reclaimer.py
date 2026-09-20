# -*- coding: utf-8 -*-
"""on-demand VPK 生产多服回收器（宿主机本地版，零依赖）

规则（方案 X）：
- 回收 campaign 当且仅当【没有任何服】的当前地图属于该 campaign 的地图列表。
- 任一服 RCON 不通 / 人数未知 → 该服按未知处理，不回收（保守保留）。
- 回收 = 删除 addons 加载副本（cp 语义），map_library 源永远保留。
"""
import os
import re
import socket
import struct
import time

GAME_ROOT = os.environ.get("ONDEMAND_GAME_ROOT", "")
RCON_PASSWORD = os.environ.get("ONDEMAND_RCON_PASSWORD", "")
SERVERS = [int(x) for x in os.environ.get("ONDEMAND_SERVERS", "").split(",") if x.strip().isdigit()]
POLL = float(os.environ.get("ONDEMAND_POLL", "5"))
ADDONS_REL = os.environ.get("ONDEMAND_ADDONS_DIR", "addons")
CFG_REL = os.environ.get("ONDEMAND_CFG", "addons/sourcemod/configs/ondemand_vpk.cfg")


def log(msg):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + " " + msg, flush=True)


def packet(req, typ, body):
    payload = struct.pack("<ii", req, typ) + body.encode("utf-8") + b"\0\0"
    return struct.pack("<i", len(payload)) + payload


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        part = sock.recv(n - len(data))
        if not part:
            raise OSError("RCON EOF")
        data += part
    return data


def recv_packet(sock):
    size = struct.unpack("<i", recv_exact(sock, 4))[0]
    if size < 10 or size > 4 * 1024 * 1024:
        raise OSError(f"RCON invalid packet size={size}")
    data = recv_exact(sock, size)
    return struct.unpack("<ii", data[:8]), data[8:-2].decode("utf-8", "replace")


def rcon(port, command, timeout_extra=15):
    with socket.create_connection(("127.0.0.1", port), 8) as sock:
        sock.settimeout(3)
        sock.sendall(packet(1, 3, RCON_PASSWORD))
        deadline = time.time() + 10
        authenticated = False
        while time.time() < deadline:
            try:
                header, _ = recv_packet(sock)
                if header[0] == 1 and header[1] == 2:
                    authenticated = True
                    break
            except socket.timeout:
                continue
        if not authenticated:
            raise OSError("RCON authentication timeout")
        sock.sendall(packet(2, 2, command))
        parts = []
        deadline = time.time() + timeout_extra
        while time.time() < deadline:
            try:
                parts.append(recv_packet(sock)[1])
            except socket.timeout:
                break
        return "\n".join(x for x in parts if x).strip()


def parse_status(text):
    map_name = None
    humans = bots = None
    m = re.search(r"^map\s*:\s*(\S+)", text, re.M)
    if m:
        map_name = m.group(1)
    m = re.search(r"players\s*:\s*(\d+) humans,\s*(\d+) bots", text)
    if m:
        humans, bots = int(m.group(1)), int(m.group(2))
    return map_name, humans, bots


def load_campaign_maps():
    result = {}
    try:
        cfg_path = os.path.join(GAME_ROOT, CFG_REL)
        if not os.path.exists(cfg_path):
            return result
        current = None
        with open(cfg_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if (line.startswith('"') and not line.startswith('"display"') and not line.startswith('"mission"')
                        and not re.match(r'"chapter_\d+"', line) and not line.startswith('"chapter_display_')):
                    m = re.match(r'"([^"]+)"\s*$', line)
                    if m and not line.startswith('"OnDemandVPK"'):
                        current = m.group(1)
                        result[current] = []
                elif current and re.search(r'"chapter_(\d+)"\s+"([^"]+)"', line):
                    m = re.search(r'"chapter_(\d+)"\s+"([^"]+)"', line)
                    if m:
                        result[current].append(m.group(2))
        return result
    except Exception as exc:
        log(f"load cfg failed: {exc!r}")
        return result


def find_staged_campaigns():
    addons_dir = os.path.join(GAME_ROOT, ADDONS_REL)
    try:
        names = os.listdir(addons_dir)
    except OSError:
        return set()
    campaigns = set()
    for name in names:
        m = re.match(r"ondemand_(.+)_part_\d+\.vpk", name)
        if m:
            campaigns.add(m.group(1))
    return campaigns


def server_states():
    states = {}
    for port in SERVERS:
        try:
            text = rcon(port, "status")
            map_name, humans, bots = parse_status(text)
            if map_name and humans is not None:
                states[port] = (map_name, humans)
                continue
        except Exception:
            pass
        states[port] = None
    return states


RECENT_GRACE = 600  # 刚 stage 的副本宽限期（秒）：防止 stage→changelevel 窗口被回收器秒删


def reclaim_campaign(campaign):
    addons_dir = os.path.join(GAME_ROOT, ADDONS_REL)
    try:
        files = [n for n in os.listdir(addons_dir) if re.fullmatch(rf"ondemand_{campaign}_part_\d+\.vpk", n)]
    except OSError:
        return
    if not files:
        return
    now = time.time()
    for f in files:
        try:
            if now - os.path.getmtime(os.path.join(addons_dir, f)) < RECENT_GRACE:
                log(f"campaign={campaign} staged recently (<{RECENT_GRACE}s), keep")
                return
        except OSError:
            continue
    for f in files:
        try:
            os.remove(os.path.join(addons_dir, f))
        except OSError as exc:
            log(f"reclaim remove {f} failed: {exc!r}")
            return
    log(f"reclaim campaign={campaign} files={len(files)} OK")


def main():
    if not GAME_ROOT or not RCON_PASSWORD or not SERVERS:
        raise RuntimeError("缺少环境变量（GAME_ROOT/RCON_PASSWORD/SERVERS）")
    log(f"reclaimer armed servers={SERVERS}")
    while True:
        try:
            staged = find_staged_campaigns()
            if not staged:
                time.sleep(POLL)
                continue
            campaign_maps = load_campaign_maps()
            states = server_states()
            unknown = [p for p, s in states.items() if s is None]
            if unknown:
                log(f"unknown server states, skip reclaim: {unknown}")
                time.sleep(POLL)
                continue

            for campaign in sorted(staged):
                maps_in_campaign = set(campaign_maps.get(campaign, []))
                if not maps_in_campaign:
                    log(f"campaign={campaign} no chapter maps in cfg, keep (conservative)")
                    continue
                in_use_by = [p for p, (mp, hu) in states.items() if mp in maps_in_campaign]
                if in_use_by:
                    log(f"campaign={campaign} in use by servers {in_use_by}, keep")
                    continue
                log(f"campaign={campaign} no server on its maps -> reclaim")
                reclaim_campaign(campaign)
            time.sleep(POLL)
        except Exception as exc:
            log(f"reclaimer loop error={exc!r}")
            time.sleep(POLL)


if __name__ == "__main__":
    main()
