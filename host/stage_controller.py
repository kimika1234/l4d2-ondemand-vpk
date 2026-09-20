# -*- coding: utf-8 -*-
"""on-demand VPK 生产多服控制器（宿主机本地版，零依赖）

部署在 L4D2 宿主机上：文件操作本地（map_library → addons 原子提交），
RCON 直连 127.0.0.1:<port>（docker 端口映射）。无 paramiko 依赖。

轮询共享请求目录（<port>_<id>.req / .req.part）→ 白名单校验 →
cp 完整 Part 组到共享 addons（原子提交）→ 目标服 RCON
update_addon_paths; mission_reload → 写 <port>_<id>.res。
"""
import os
import re
import socket
import struct
import shutil
import time

GAME_ROOT = os.environ.get("ONDEMAND_GAME_ROOT", "")
RCON_PASSWORD = os.environ.get("ONDEMAND_RCON_PASSWORD", "")
SERVERS = [int(x) for x in os.environ.get("ONDEMAND_SERVERS", "").split(",") if x.strip().isdigit()]
POLL = float(os.environ.get("ONDEMAND_POLL", "2"))
REQ_DIR_REL = os.environ.get("ONDEMAND_REQ_DIR", "addons/sourcemod/data/ondemand_vpk_requests")
LIB_REL = os.environ.get("ONDEMAND_LIB_DIR", "map_library")
ADDONS_REL = os.environ.get("ONDEMAND_ADDONS_DIR", "addons")
CFG_REL = os.environ.get("ONDEMAND_CFG", "addons/sourcemod/configs/ondemand_vpk.cfg")
CAMPAIGNS = [c.strip() for c in os.environ.get("ONDEMAND_CAMPAIGNS", "").split(",") if c.strip()]


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


def rcon(port, command, timeout_extra=20):
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


def parse_request(raw):
    values = {}
    for line in raw.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values.get("campaign", ""), values.get("map", ""), values.get("client", "0")


def load_campaign_chapters():
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


def find_campaign_dir(campaign):
    base = os.path.join(GAME_ROOT, LIB_REL)
    direct = os.path.join(base, campaign)
    if os.path.isdir(direct):
        return direct
    # 大小写不敏感兜底（webmap/!chmap 可能传与目录不同大小写的 campaign 名）
    try:
        for name in os.listdir(base):
            if name.lower() == campaign.lower():
                return os.path.join(base, name)
    except OSError:
        pass
    return None


def write_result(port, request_id, value, campaign="", map_name="", client=0):
    res_path = os.path.join(GAME_ROOT, REQ_DIR_REL, f"{port}_{request_id}.res")
    with open(res_path, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    # RCON 主动通知 bridge（实时主通道；res 文件仅作兜底）
    try:
        ok = 1 if value == "OK" else 0
        notify_out = rcon(port, f"sm_ondemand_notify {request_id} \"{campaign}\" \"{map_name}\" {client} {ok}", timeout_extra=8)
        if notify_out:
            log(f"notify port={port} id={request_id} ok={ok} out={notify_out[:80]}")
    except Exception as exc:
        log(f"notify port={port} id={request_id} failed={exc!r}")


def stage(port, request_id, campaign, map_name, chapters, client=0):
    if CAMPAIGNS and campaign not in CAMPAIGNS:
        log(f"req {port}_{request_id} campaign not whitelisted: {campaign}")
        write_result(port, request_id, "FAIL", campaign, map_name, client)
        return
    if campaign in chapters and chapters[campaign] and map_name not in chapters[campaign]:
        log(f"req {port}_{request_id} map not in campaign chapters: {map_name}")
        write_result(port, request_id, "FAIL", campaign, map_name, client)
        return
    if port not in SERVERS:
        log(f"req {port}_{request_id} port not in server list")
        write_result(port, request_id, "FAIL", campaign, map_name, client)
        return

    lib_camp = find_campaign_dir(campaign) or os.path.join(GAME_ROOT, LIB_REL, campaign)
    addons_dir = os.path.join(GAME_ROOT, ADDONS_REL)
    try:
        parts = sorted([p for p in os.listdir(lib_camp) if re.fullmatch(r"part_\d+\.vpk", p)])
    except OSError:
        parts = []
    if not parts:
        log(f"req {port}_{request_id} no parts in {lib_camp}")
        write_result(port, request_id, "FAIL", campaign, map_name, client)
        return

    try:
        os.makedirs(addons_dir, exist_ok=True)
        for i, src in enumerate(parts, 1):
            dst = f"ondemand_{campaign}_part_{i}.vpk"
            src_path = os.path.join(lib_camp, src)
            dst_path = os.path.join(addons_dir, dst)
            if not os.path.isfile(src_path):
                raise RuntimeError(f"source missing: {src_path}")
            if os.path.exists(dst_path):
                # 并发/重试：另一台服已 stage 或本服曾成功——目标已就绪则跳过，不视为失败
                log(f"target already present (concurrent/retry): {dst_path}")
                continue
            tmp_path = dst_path + ".part"
            shutil.copy2(src_path, tmp_path)
            if os.path.getsize(src_path) != os.path.getsize(tmp_path):
                raise RuntimeError(f"size mismatch for {dst}")
            os.rename(tmp_path, dst_path)
        log(f"stage port={port} request={request_id} campaign={campaign} map={map_name} OK")
    except Exception as exc:
        log(f"stage port={port} request={request_id} failed={exc!r}")
        write_result(port, request_id, "FAIL", campaign, map_name, client)
        return

    try:
        out = rcon(port, "update_addon_paths; mission_reload", timeout_extra=180)
        log(f"mission_reload port={port} out={out[-200:]}")
    except Exception as exc:
        log(f"mission_reload port={port} failed={exc!r}")
        write_result(port, request_id, "FAIL", campaign, map_name, client)
        return
    time.sleep(2)
    write_result(port, request_id, "OK", campaign, map_name, client)


def main():
    if not GAME_ROOT or not RCON_PASSWORD or not SERVERS:
        raise RuntimeError("缺少环境变量（GAME_ROOT/RCON_PASSWORD/SERVERS）")
    log(f"stage controller armed servers={SERVERS}")
    req_dir = os.path.join(GAME_ROOT, REQ_DIR_REL)
    os.makedirs(req_dir, exist_ok=True)
    chapters = load_campaign_chapters()
    log(f"campaign chapters loaded: {list(chapters.keys())}")
    while True:
        try:
            for filename in sorted(os.listdir(req_dir)):
                m = re.fullmatch(r"(\d+)_(\d+)\.req(?:\.part)?", filename)
                if not m:
                    continue
                port = int(m.group(1))
                request_id = int(m.group(2))
                path = os.path.join(req_dir, filename)
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        raw = f.read()
                    campaign, map_name, client = parse_request(raw)
                    if not campaign or not map_name:
                        log(f"req {port}_{request_id} incomplete content, skip")
                        continue
                    stage(port, request_id, campaign, map_name, chapters, client)
                except Exception as exc:
                    log(f"stage port={port} request={request_id} failed={exc!r}")
                    write_result(port, request_id, "FAIL", campaign, map_name, client)
                try:
                    os.remove(path)
                except OSError:
                    pass
            time.sleep(POLL)
        except Exception as exc:
            log(f"controller loop error={exc!r}")
            time.sleep(POLL)


if __name__ == "__main__":
    main()
