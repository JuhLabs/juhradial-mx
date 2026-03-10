#!/usr/bin/env python3
"""Probe Logi Options+ agent for sensitivity and scroll settings."""
import glob, json, socket, struct, time

DEVICE_ID = "dev00000000"

def find_socket():
    for s in glob.glob("/tmp/logitech_kiros_agent-*"):
        if "updater" not in s: return s
    return None

def connect(sock_path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(sock_path)
    s.recv(4)
    read_frame(s)
    read_frame(s)
    return s

def read_frame(s):
    header = b""
    while len(header) < 4:
        chunk = s.recv(4 - len(header))
        if not chunk: return None
        header += chunk
    frame_len = struct.unpack('>I', header)[0]
    body = b""
    while len(body) < frame_len:
        chunk = s.recv(frame_len - len(body))
        if not chunk: return None
        body += chunk
    return body

def send_json(s, msg):
    j = json.dumps(msg).encode()
    p = b"json"
    t = len(p) + len(j) + 8
    s.sendall(struct.pack('<I', t) + struct.pack('>I', len(p)) + p + struct.pack('>I', len(j)) + j)

def recv_json(s, timeout=5):
    s.settimeout(timeout)
    s.recv(4)
    pl = struct.unpack('>I', s.recv(4))[0]
    pn = s.recv(pl).decode()
    ml = struct.unpack('>I', s.recv(4))[0]
    d = b""
    while len(d) < ml: d += s.recv(ml - len(d))
    return json.loads(d) if pn == "json" else None

def query(verb, path):
    sp = find_socket()
    s = connect(sp)
    send_json(s, {"msgId": f"p-{time.time()}", "verb": verb, "path": path})
    r = recv_json(s)
    s.close()
    return r

# Find all sensitivity/scroll/pointer related routes
print("=" * 70)
print("FINDING RELEVANT ROUTES")
print("=" * 70)
resp = query("get", "/routes")
routes = resp.get("payload", {}).get("route", [])
keywords = ["sensitivity", "dpi", "pointer", "scroll", "wheel", "smart", "speed", "resolution", "ratchet"]
for r in routes:
    path = r.get("path", "").lower()
    if any(k in path for k in keywords) or DEVICE_ID in r.get("path", ""):
        if any(k in path for k in keywords):
            print(f"  {r.get('verb'):4s} {r.get('path')}")
            if r.get("exampleJson"):
                print(f"       example: {r['exampleJson'].strip()}")

# Query specific known endpoints
endpoints = [
    f"/devices/{DEVICE_ID}/dpi",
    f"/devices/{DEVICE_ID}/pointer_speed",
    f"/devices/{DEVICE_ID}/sensitivity",
    f"/devices/{DEVICE_ID}/scroll",
    f"/devices/{DEVICE_ID}/smartshift",
    f"/devices/{DEVICE_ID}/wheel",
    f"/devices/{DEVICE_ID}/thumbwheel",
    f"/pointer_speed/{DEVICE_ID}/config",
    f"/dpi/{DEVICE_ID}/config",
    f"/dpi/{DEVICE_ID}/dpi",
    f"/dpi/{DEVICE_ID}/sensor_dpi_list",
    f"/scroll/{DEVICE_ID}/config",
    f"/smartshift/{DEVICE_ID}/config",
    f"/wheel/{DEVICE_ID}/config",
    f"/thumbwheel/{DEVICE_ID}/config",
    f"/hires_scroll/{DEVICE_ID}/config",
]

for ep in endpoints:
    print(f"\n{'=' * 70}")
    print(f"GET {ep}")
    try:
        r = query("get", ep)
        code = r.get("result", {}).get("code", "?")
        if code == "SUCCESS":
            print(json.dumps(r.get("payload", {}), indent=2))
        else:
            print(f"  -> {code}")
    except Exception as e:
        print(f"  -> Error: {e}")
